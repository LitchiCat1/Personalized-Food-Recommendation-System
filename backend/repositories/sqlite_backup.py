"""本機 SQLite 的備份：手動備份（scripts/backup_db.py）和後端開著時的自動備份共用這裡。

用 SQLite 自己的備份功能複製：後端開著時剛寫的資料還在 -wal 檔裡，直接複製 .db 檔
會漏掉那些資料，這個方式不會。備份先寫成暫存檔，檢查沒有損毀才改成正式檔名，
備份資料夾裡看得到的 .db 都是完整、檢查過的。

檔名：
- 手動備份：nutrilens-20261025-163819.db
- 自動備份：nutrilens-auto-20261026-090000.db（只有這種會依保留份數清掉舊的）
- 升級資料庫結構前：nutrilens-before-v2-20261026-090000.db
"""

import os
import re
import shutil
import sqlite3
import threading
from datetime import datetime, timedelta

AUTO_LABEL = "auto"
DEFAULT_AUTO_HOURS = 24
DEFAULT_AUTO_KEEP = 30
# 備份失敗（例如硬碟滿了）時隔多久再試；不能馬上重試，不然會一直空轉
RETRY_SECONDS = 3600


class BackupError(Exception):
    pass


def check_database(path: str) -> str:
    """PRAGMA quick_check 的結果：完好是 "ok"，其他就是哪裡壞了。"""
    try:
        conn = sqlite3.connect(path)
    except sqlite3.Error as error:
        return str(error)
    try:
        return conn.execute("PRAGMA quick_check").fetchone()[0]
    except sqlite3.DatabaseError as error:
        return str(error)
    finally:
        conn.close()


def stamp(now: datetime | None = None) -> str:
    return (now or datetime.now()).strftime("%Y%m%d-%H%M%S")


def _base_name(source: str) -> str:
    return os.path.splitext(os.path.basename(source))[0]


def _free_name(folder: str, stem: str) -> str:
    target = os.path.join(folder, f"{stem}.db")
    counter = 2
    # 同一秒備份兩次時不要蓋掉前一份
    while os.path.exists(target):
        target = os.path.join(folder, f"{stem}-{counter}.db")
        counter += 1
    return target


def backup_database(source: str, backup_dir: str, now: datetime | None = None, label: str = "") -> str:
    """把 source 完整複製一份到 backup_dir，回傳備份檔的路徑。"""
    # sqlite3.connect 遇到不存在的檔案會建一個空的，所以先檢查
    if not os.path.isfile(source):
        raise BackupError(f"找不到資料庫檔案：{source}")
    os.makedirs(backup_dir, exist_ok=True)
    stem = "-".join(part for part in (_base_name(source), label, stamp(now)) if part)
    target = _free_name(backup_dir, stem)
    partial = target + ".partial"

    try:
        src = sqlite3.connect(source)
        dst = sqlite3.connect(partial)
        try:
            src.backup(dst)
            # 複製出來的檔案沿用 WAL 模式，之後打開它（連唯讀也是）會在旁邊多出 -wal、-shm，
            # 只搬 .db 的話可能漏資料。備份改成單一檔案；還原後後端開檔時會再切回 WAL。
            dst.execute("PRAGMA journal_mode=DELETE")
        finally:
            dst.close()
            src.close()
        result = check_database(partial)
        if result != "ok":
            raise BackupError(f"備份檔檢查沒通過（{result}），原本的資料庫可能已經損毀：{source}")
        os.replace(partial, target)
    finally:
        # 沒寫完或沒通過檢查的暫存檔不留，免得被當成可以還原的備份
        if os.path.exists(partial):
            os.remove(partial)
    return target


def list_backups(backup_dir: str) -> list[str]:
    if not os.path.isdir(backup_dir):
        return []
    return sorted(
        os.path.join(backup_dir, name) for name in os.listdir(backup_dir) if name.endswith(".db")
    )


def _auto_pattern(source: str):
    return re.compile(rf"^{re.escape(_base_name(source))}-{AUTO_LABEL}-(\d{{8}}-\d{{6}})(?:-\d+)?\.db$")


def auto_backups(source: str, folder: str) -> list[tuple[datetime, str]]:
    """folder 裡這個資料庫的自動備份，舊的在前。時間看檔名：搬資料夾會改掉檔案的修改時間。"""
    if not os.path.isdir(folder):
        return []
    pattern = _auto_pattern(source)
    found = []
    for name in os.listdir(folder):
        match = pattern.match(name)
        if match:
            found.append((datetime.strptime(match.group(1), "%Y%m%d-%H%M%S"), os.path.join(folder, name)))
    return sorted(found)


def prune_auto_backups(source: str, folder: str, keep: int) -> list[str]:
    """只留最近 keep 份自動備份，回傳清掉的檔案。手動備份和升級前的備份不會動。"""
    old = auto_backups(source, folder)[:-keep] if keep > 0 else []
    removed = []
    for _, path in old:
        try:
            os.remove(path)
            removed.append(path)
        except OSError as error:
            print(f"[WARN] 舊的自動備份刪不掉，下次再試：{path}（{error}）")
    return removed


class AutoBackup:
    """後端開著時每隔一段時間備份一次，只留最近幾份自動備份。

    先前只能手動執行 backup_db.py：2026-10-25 資料庫被蓋成空的時候，能還原全靠
    剛好有一份當天下午的手動備份。備份會順便檢查整份資料庫，所以也等於每天做一次
    損毀檢查。copy_dir 可以設到另一顆硬碟或雲端硬碟的資料夾，硬碟壞掉時還有一份。
    """

    def __init__(self, source: str, backup_dir: str, interval_hours: float = DEFAULT_AUTO_HOURS,
                 keep: int = DEFAULT_AUTO_KEEP, copy_dir: str | None = None, clock=datetime.now):
        self.source = source
        self.backup_dir = backup_dir
        self.interval = timedelta(hours=interval_hours)
        self.keep = keep
        self.copy_dir = copy_dir
        self.clock = clock
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def seconds_until_due(self) -> float:
        backups = auto_backups(self.source, self.backup_dir)
        if not backups:
            return 0.0
        wait = (backups[-1][0] + self.interval - self.clock()).total_seconds()
        # 電腦時間被往回調時，最新那份看起來在未來；最多只等一個週期
        return min(max(wait, 0.0), self.interval.total_seconds())

    def run_once(self) -> str | None:
        """備份一次，回傳備份檔；失敗時印出原因、回 None，後端照常運作。"""
        try:
            target = backup_database(self.source, self.backup_dir, now=self.clock(), label=AUTO_LABEL)
        except (BackupError, OSError, sqlite3.Error) as error:
            print(f"[ERROR] 自動備份失敗，{RETRY_SECONDS // 60} 分鐘後再試：{error}")
            return None
        print(f"[OK] 自動備份：{target}")
        prune_auto_backups(self.source, self.backup_dir, self.keep)
        if self.copy_dir:
            try:
                os.makedirs(self.copy_dir, exist_ok=True)
                shutil.copy2(target, os.path.join(self.copy_dir, os.path.basename(target)))
                prune_auto_backups(self.source, self.copy_dir, self.keep)
            except OSError as error:
                # 隨身碟沒插、雲端硬碟沒開都會這樣；本機那份已經備好了
                print(f"[WARN] 自動備份複製到 {self.copy_dir} 失敗：{error}")
        return target

    def _loop(self) -> None:
        delay = self.seconds_until_due()
        while not self._stop.wait(delay):
            delay = self.interval.total_seconds() if self.run_once() else min(RETRY_SECONDS, self.interval.total_seconds())

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="sqlite-auto-backup", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)


def _number(environ, name: str, default: float) -> float:
    raw = (environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        print(f"[WARN] {name}={raw} 不是數字，改用預設值 {default:g}")
        return default


def auto_backup_from_env(source: str, environ=None) -> AutoBackup | None:
    """依 AUTO_BACKUP_HOURS（0 是關掉）、AUTO_BACKUP_KEEP、AUTO_BACKUP_COPY_DIR 建立自動備份。"""
    environ = os.environ if environ is None else environ
    hours = _number(environ, "AUTO_BACKUP_HOURS", DEFAULT_AUTO_HOURS)
    if hours <= 0:
        return None
    # 太密的話一天就是幾百份備份；至少隔一小時
    hours = max(hours, 1)
    keep = max(int(_number(environ, "AUTO_BACKUP_KEEP", DEFAULT_AUTO_KEEP)), 1)
    copy_dir = (environ.get("AUTO_BACKUP_COPY_DIR") or "").strip() or None
    if copy_dir:
        copy_dir = os.path.abspath(os.path.expanduser(os.path.expandvars(copy_dir)))
    backup_dir = os.path.join(os.path.dirname(source), "backups")
    return AutoBackup(source, backup_dir, interval_hours=hours, keep=keep, copy_dir=copy_dir)
