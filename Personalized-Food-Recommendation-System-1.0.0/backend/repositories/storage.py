from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import threading
import uuid

from repositories.sqlite_db import SqliteDatabase, from_json, to_json, utc_iso
from services.app_time_service import app_now, app_today
from services.nutrient_service import NUTRITION_FIELDS, get_nutrient_value, nutrient_number
from services.nutrition_profile_service import NutritionProfileError
from services.record_nutrition_service import aggregate_record_coverage, enrich_record_nutrition


# 飲食紀錄表的欄位（不含流水號 id）。insert / update / select 都照這個順序。
RECORD_COLUMNS = (
    "user_id", "client_record_id", "timestamp", "meal_type", "foods",
    "total_calories", "total_protein", "total_carbs", "total_fat",
    "total_sodium", "total_fiber", "total_sugar",
    "total_saturated_fat", "total_trans_fat", "source",
    "nutrition_contract_version", "nutrition_context",
)
RECORD_SELECT = ", ".join(RECORD_COLUMNS)


class StorageRepository:
    """SQLite persistence, with explicit temporary dictionaries for isolated tests/demo."""

    def __init__(self, mem_users: dict, mem_records: list, mem_custom_foods: list, *, sql: SqliteDatabase | None = None):
        self.sql = sql
        self.use_sql = sql is not None
        self.mem_users = mem_users
        self.mem_records = mem_records
        self.mem_custom_foods = mem_custom_foods
        self._record_lock = threading.RLock()
        self.mem_restaurant_menus: dict = {}
        self.mem_restaurant_menu_failures: dict = {}
        if self.use_sql:
            self._init_tables()

    def _init_tables(self):
        # SQLite 沒有 JSON 與時間型別：doc / foods 存 JSON 字串，時間存 utc_iso() 的字串
        self.sql.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                doc TEXT NOT NULL,
                updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                client_record_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                meal_type TEXT,
                foods TEXT,
                total_calories REAL DEFAULT 0,
                total_protein REAL DEFAULT 0,
                total_carbs REAL DEFAULT 0,
                total_fat REAL DEFAULT 0,
                total_sodium REAL DEFAULT 0,
                total_fiber REAL DEFAULT 0,
                total_sugar REAL DEFAULT 0,
                total_saturated_fat REAL DEFAULT 0,
                total_trans_fat REAL DEFAULT 0,
                source TEXT DEFAULT 'camera',
                nutrition_contract_version INTEGER,
                nutrition_context TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_records_user_timestamp ON records (user_id, timestamp DESC);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_records_user_client_record ON records (user_id, client_record_id);
            CREATE TABLE IF NOT EXISTS custom_foods (
                owner_key TEXT PRIMARY KEY,
                food_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                doc TEXT NOT NULL,
                updated_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_custom_foods_user_id ON custom_foods (user_id);
            CREATE TABLE IF NOT EXISTS restaurant_menus (
                venue_key TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                name_key TEXT,
                doc TEXT NOT NULL,
                updated_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_restaurant_menus_name ON restaurant_menus (name_key);
            CREATE TABLE IF NOT EXISTS restaurant_menu_failures (
                venue_key TEXT PRIMARY KEY,
                reason TEXT NOT NULL,
                failed_until TEXT NOT NULL
            );
            """
        )
        self._require_record_dedupe_index()

    def _require_record_dedupe_index(self):
        """存紀錄的 ON CONFLICT (user_id, client_record_id) 要靠這個唯一索引。

        CREATE UNIQUE INDEX IF NOT EXISTS 只看名字：舊資料庫若已有同名的一般索引，
        它會直接跳過，之後每一次存紀錄都失敗。在啟動時就停下來說清楚。
        """
        wanted = {"user_id", "client_record_id"}
        found = any(
            {info["name"] for info in self.sql.query_all(f"PRAGMA index_info('{index['name']}')")} == wanted
            for index in self.sql.query_all("PRAGMA index_list('records')")
            if index["unique"]
        )
        if not found:
            raise RuntimeError(
                "records 表缺少 (user_id, client_record_id) 的唯一索引，存紀錄會失敗。"
                "通常是舊資料庫已有同名的一般索引 idx_records_user_client_record："
                "確認沒有重複資料後，刪掉那個索引再重新啟動，後端會自動建立唯一索引。"
            )

    def _fetch_json_doc(self, table: str, key_field: str, key_value: str):
        row = self.sql.query_one(f"SELECT doc FROM {table} WHERE {key_field} = ?", (key_value,))
        return from_json(row["doc"]) if row else None

    def _record_from_row(self, row: dict | None):
        if not row:
            return None
        record = dict(row)
        record.pop("id", None)
        record["foods"] = from_json(record.get("foods")) or []
        record["nutrition_context"] = from_json(record.get("nutrition_context"))
        return self._enrich_record_totals(record)

    @staticmethod
    def _record_values(record: dict) -> tuple:
        return (
            record.get("user_id"),
            record.get("client_record_id"),
            record.get("timestamp"),
            record.get("meal_type"),
            to_json(record.get("foods", [])),
            record.get("total_calories", 0),
            record.get("total_protein", 0),
            record.get("total_carbs", 0),
            record.get("total_fat", 0),
            record.get("total_sodium", 0),
            record.get("total_fiber", 0),
            record.get("total_sugar", 0),
            record.get("total_saturated_fat", 0),
            record.get("total_trans_fat", 0),
            record.get("source", "camera"),
            record.get("nutrition_contract_version"),
            to_json(record.get("nutrition_context")),
        )

    def get_user(self, user_id: str):
        user_doc = None
        if self.use_sql:
            user_doc = self._fetch_json_doc("users", "user_id", user_id)
        else:
            user_doc = self.mem_users.get(user_id)

        # Only the explicit demo identity gets a generated profile; real users must sign up.
        if not user_doc and user_id == "demo_user":
            user_doc = {
                "user_id": "demo_user",
                "name": "本機測試帳號",
                "gender": "male",
                "height": 170.0,
                "weight": 70.0,
                "age": 25,
                "activity_level": "中等活動量",
                "activity_multiplier": 1.55,
                "bmi": 24.2,
                "bmr": 1624,
                "tdee": 2517,
                "daily_calorie_target": 2517,
                "health_conditions": [],
                "allergens": [],
                "target_weight": 65.0,
                "diet_type": "葷食",
                "updated_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
            }
            self.upsert_user(user_doc)

        return user_doc


    def upsert_user(self, user_doc: dict):
        if self.use_sql:
            self.sql.execute(
                """
                INSERT INTO users (user_id, doc, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT (user_id)
                DO UPDATE SET doc = excluded.doc, updated_at = excluded.updated_at
                """,
                (user_doc["user_id"], to_json(user_doc), utc_iso()),
            )
            return user_doc
        self.mem_users[user_doc["user_id"]] = user_doc
        return user_doc

    def _enrich_record_totals(self, record: dict) -> dict:
        if not record or "foods" not in record:
            return record

        record = deepcopy(record)
        if record.get("nutrition_contract_version") == 2:
            return enrich_record_nutrition(record)

        foods = record.get("foods") or []
        if foods:
            for nutrient in NUTRITION_FIELDS:
                record[f"total_{nutrient}"] = round(
                    sum(nutrient_number(get_nutrient_value(food, nutrient)) for food in foods),
                    2,
                )
        record["contains_fried_food"] = any(food.get("is_fried") is True for food in foods)
        return enrich_record_nutrition(record)

    def insert_record(self, record: dict):
        record = deepcopy(record)
        if not record.get("client_record_id"):
            record = {**record, "client_record_id": f"server_record_{uuid.uuid4().hex}"}
        existing = self.get_record_by_client_record_id(record.get("user_id"), record.get("client_record_id"))
        if existing:
            return {**self._enrich_record_totals(existing), "_deduplicated": True}


        if self.use_sql:
            placeholders = ", ".join("?" for _ in RECORD_COLUMNS)
            # 同一筆同時送兩次（離線補傳加上手動重按）時，上面兩邊都查不到。唯一索引
            # 擋得住重複，但後到的那個會撞 IntegrityError 變成 500；讓 SQLite 直接略過，
            # 再查回先寫進去的那筆。
            inserted = self.sql.execute(
                f"INSERT INTO records ({RECORD_SELECT}) VALUES ({placeholders}) "
                "ON CONFLICT (user_id, client_record_id) DO NOTHING",
                self._record_values(record),
            )
            if not inserted:
                existing = self.get_record_by_client_record_id(record.get("user_id"), record.get("client_record_id"))
                return {**existing, "_deduplicated": True}
            return self._enrich_record_totals(record)
        with self._record_lock:
            existing = self.get_record_by_client_record_id(record.get("user_id"), record.get("client_record_id"))
            if existing:
                return {**existing, "_deduplicated": True}
            self.mem_records.append(record)
        return self._enrich_record_totals(record)

    def upsert_record(self, record: dict):
        return self.insert_record(record)

    def get_record_by_client_record_id(self, user_id: str | None, client_record_id: str | None):
        if not user_id or not client_record_id:
            return None
        if self.use_sql:
            row = self.sql.query_one(
                f"SELECT {RECORD_SELECT} FROM records WHERE user_id = ? AND client_record_id = ? LIMIT 1",
                (user_id, client_record_id),
            )
            return self._record_from_row(row)
        for record in self.mem_records:
            if record.get("user_id") == user_id and record.get("client_record_id") == client_record_id:
                return self._enrich_record_totals(record)
        return None

    def update_record(self, record: dict, *, expected_revision=None, nutrition_contract_version=None):
        record = deepcopy(record)
        legacy_client = nutrition_contract_version == 1
        user_id = record.get("user_id")
        client_record_id = record.get("client_record_id")
        if not user_id or not client_record_id:
            return None
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 0):
            raise NutritionProfileError("invalid_record", "expected_revision must be a nonnegative integer")

        if self.use_sql:
            values = self._record_values(record)
            # 前兩個是 user_id / client_record_id，放到 WHERE
            assignments = ", ".join(f"{column} = ?" for column in RECORD_COLUMNS[2:])
            revision_filter = ""
            revision_params = ()
            if expected_revision is not None:
                revision_filter = (" AND nutrition_contract_version = 2"
                                   " AND json_type(nutrition_context, '$.revision') = 'integer'"
                                   " AND json_extract(nutrition_context, '$.revision') = ?")
                revision_params = (expected_revision,)
            if legacy_client:
                revision_filter += " AND (nutrition_contract_version IS NULL OR nutrition_contract_version <> 2)"
            with self.sql.transaction():
                changed = self.sql.execute(
                    f"UPDATE records SET {assignments} WHERE user_id = ? AND client_record_id = ?{revision_filter}",
                    (*values[2:], user_id, client_record_id, *revision_params),
                )
                if not changed:
                    current = self.get_record_by_client_record_id(user_id, client_record_id)
                    if legacy_client and current and current.get("nutrition_contract_version") == 2:
                        raise NutritionProfileError("upgrade_required", "Nutrition contract version 2 is required")
                    return None
                return self.get_record_by_client_record_id(user_id, client_record_id)

        with self._record_lock:
            for index, existing in enumerate(self.mem_records):
                if existing.get("user_id") == user_id and existing.get("client_record_id") == client_record_id:
                    if legacy_client and existing.get("nutrition_contract_version") == 2:
                        raise NutritionProfileError("upgrade_required", "Nutrition contract version 2 is required")
                    if expected_revision is not None and (
                        existing.get("nutrition_contract_version") != 2 or
                        type(existing.get("nutrition_context", {}).get("revision")) is not int or
                        existing["nutrition_context"]["revision"] != expected_revision
                    ):
                        return None
                    self.mem_records[index] = record
                    return self._enrich_record_totals(record)
        return None

    def delete_record(self, user_id: str, client_record_id: str, *, nutrition_contract_version=None):
        legacy_client = nutrition_contract_version == 1

        def check_legacy_access(record):
            if legacy_client and record and record.get("nutrition_contract_version") == 2:
                raise NutritionProfileError("upgrade_required", "Nutrition contract version 2 is required")

        if self.use_sql:
            with self.sql.transaction():
                existing = self.get_record_by_client_record_id(user_id, client_record_id)
                check_legacy_access(existing)
                if existing:
                    version_filter = (" AND (nutrition_contract_version IS NULL OR nutrition_contract_version <> 2)"
                                      if legacy_client else "")
                    changed = self.sql.execute(
                        f"DELETE FROM records WHERE user_id = ? AND client_record_id = ?{version_filter}",
                        (user_id, client_record_id),
                    )
                    if not changed:
                        check_legacy_access(self.get_record_by_client_record_id(user_id, client_record_id))
                        return None
            return existing

        with self._record_lock:
            for index, record in enumerate(self.mem_records):
                if record.get("user_id") == user_id and record.get("client_record_id") == client_record_id:
                    check_legacy_access(record)
                    return self._enrich_record_totals(self.mem_records.pop(index))
        return None

    def get_records(self, user_id: str, date_str: str | None = None, limit: int = 50, offset: int = 0):
        if self.use_sql:
            sql = f"SELECT {RECORD_SELECT} FROM records WHERE user_id = ?"
            params = [user_id]
            if date_str:
                sql += " AND timestamp LIKE ?"
                params.append(f"{date_str}%")
            sql += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            return [self._record_from_row(row) for row in self.sql.query_all(sql, params)]

        records = [r for r in self.mem_records if r.get("user_id") == user_id]
        if date_str:
            records = [r for r in records if str(r.get("timestamp", "")).startswith(date_str)]
        records.sort(key=lambda record: str(record.get("timestamp", "")), reverse=True)
        slice_records = records[offset:offset + limit]
        return [self._enrich_record_totals(r) for r in slice_records]

    def get_all_records(self, user_id: str, date_str: str | None = None):
        """Read a complete aggregation range without the UI pagination limit."""
        if self.use_sql:
            query = f"SELECT {RECORD_SELECT} FROM records WHERE user_id = ?"
            params = [user_id]
            if date_str:
                query += " AND timestamp LIKE ?"
                params.append(f"{date_str}%")
            query += " ORDER BY timestamp DESC"
            return [self._record_from_row(row) for row in self.sql.query_all(query, params)]
        records = [row for row in self.mem_records if row.get("user_id") == user_id
                   and (not date_str or str(row.get("timestamp", "")).startswith(date_str))]
        return [self._enrich_record_totals(row) for row in sorted(
            records, key=lambda row: str(row.get("timestamp", "")), reverse=True)]

    def get_today_records(self, user_id: str):
        return self.get_all_records(user_id, app_today())

    def get_history(self, user_id: str, days: int, *, nutrition_contract_version=1):
        end_date = app_now().replace(tzinfo=None)
        start_date = end_date - timedelta(days=days)
        # 上限用「明天」且不含：紀錄的時間後面還有微秒和時區（+08:00），先前用字串
        # "今天T23:59:59" 當上限，按字串比較，23:59:59 那一秒的紀錄會被排除
        start_key = start_date.strftime("%Y-%m-%d")
        end_key = (end_date + timedelta(days=1)).strftime("%Y-%m-%d")

        if self.use_sql:
            records = [self._record_from_row(row) for row in self.sql.query_all(
                f"SELECT {RECORD_SELECT} FROM records WHERE user_id = ? AND timestamp >= ? AND timestamp < ?",
                (user_id, start_key, end_key),
            )]
        else:
            records = [self._enrich_record_totals(row) for row in self.mem_records
                       if row.get("user_id") == user_id
                       and start_key <= str(row.get("timestamp", "")) < end_key]
        if nutrition_contract_version != 2 and any(
            record.get("nutrition_contract_version") == 2 for record in records
        ):
            raise NutritionProfileError("upgrade_required", "Nutrition contract version 2 is required")

        grouped = defaultdict(list)
        for record in records:
            grouped[str(record.get("timestamp", ""))[:10]].append(record)
        result = []
        for day, daily_records in sorted(grouped.items()):
            row = {"date": day, "record_count": len(daily_records)}
            if nutrition_contract_version == 2:
                coverage = aggregate_record_coverage(daily_records)
                row.update({nutrient: coverage["nutrients"][nutrient]["known_sum"]
                            for nutrient in NUTRITION_FIELDS})
                row["nutrition_coverage"] = coverage
            else:
                row.update({nutrient: round(sum(nutrient_number(record.get(f"total_{nutrient}"))
                                               for record in daily_records), 1)
                            for nutrient in NUTRITION_FIELDS})
            result.append(row)
        return result

    def get_custom_foods(self, user_id: str | None = None):
        if self.use_sql:
            sql = "SELECT doc FROM custom_foods"
            params = []
            if user_id:
                sql += " WHERE user_id = ?"
                params.append(user_id)
            sql += " ORDER BY updated_at DESC"
            return [from_json(row["doc"]) for row in self.sql.query_all(sql, params)]

        docs = list(self.mem_custom_foods)
        if user_id:
            docs = [doc for doc in docs if doc.get("user_id") == user_id]
        return docs

    def count_custom_foods(self) -> int:
        """/health 用。只要筆數，不必把每個人的自訂食品整份讀出來再解析。"""
        if self.use_sql:
            return int(self.sql.query_one("SELECT COUNT(*) AS n FROM custom_foods")["n"])
        return len(self.mem_custom_foods)

    def _custom_food_owner_key(self, user_id: str | None, food_id: str) -> str:
        normalized_user_id = user_id or "demo_user"
        return f"{normalized_user_id}:{food_id}"

    # ─── 店家菜單快取 ────────────────────────────────────────
    # Gemini 分析一家店要 20~30 秒，寫回 restaurant_catalog.json 又會跟著程式碼走，
    # 所以存進資料庫。
    @staticmethod
    def venue_name_key(name: str) -> str:
        return str(name or "").strip().lower()

    @classmethod
    def venue_cache_key(cls, name: str = "", place_id: str = "") -> str:
        """place_id 優先。Places 新舊版 API 回的店名可能不同，place_id 不會變。"""
        place_id = str(place_id or "").strip()
        if place_id:
            return f"place:{place_id}"
        name_key = cls.venue_name_key(name)
        return f"name:{name_key}" if name_key else ""

    def get_restaurant_menu(self, name: str = "", place_id: str = ""):
        keys = []
        if place_id:
            keys.append(self.venue_cache_key(place_id=place_id))
        name_key = self.venue_name_key(name)
        if name_key:
            keys.append(f"name:{name_key}")
        if not keys:
            return None

        if self.use_sql:
            placeholders = ", ".join("?" for _ in keys)
            row = self.sql.query_one(
                f"SELECT doc FROM restaurant_menus WHERE venue_key IN ({placeholders}) OR name_key = ? LIMIT 1",
                (*keys, name_key),
            )
            return from_json(row["doc"]) if row else None
        for key in keys:
            if key in self.mem_restaurant_menus:
                return self.mem_restaurant_menus[key]
        return next(
            (doc for doc in self.mem_restaurant_menus.values() if doc.get("name_key") == name_key),
            None,
        )

    # 店家會改菜單、漲價、換營業時間。快取沒有時效的話，建過一次就永遠
    # 不會更新，錯的資料會一直被當成真的用下去。
    MENU_CACHE_MAX_AGE_DAYS = 30

    def restaurant_menu_age_days(self, doc: dict) -> float | None:
        cached_at = (doc or {}).get("cached_at")
        if not cached_at:
            return None
        try:
            stamp = datetime.fromisoformat(str(cached_at))
        except ValueError:
            return None
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - stamp).total_seconds() / 86400

    def restaurant_menu_is_stale(self, doc: dict, max_age_days: float | None = None) -> bool:
        """沒有時間戳的舊資料視為過期，重建一次就會補上。"""
        age = self.restaurant_menu_age_days(doc)
        if age is None:
            return True
        return age > (max_age_days if max_age_days is not None else self.MENU_CACHE_MAX_AGE_DAYS)

    def list_restaurant_menus(self, limit: int = 60) -> list[dict]:
        """建檔過的店家全部拿出來。推薦讀這個來取得菜色營養。"""
        if self.use_sql:
            rows = self.sql.query_all("SELECT doc FROM restaurant_menus ORDER BY updated_at DESC LIMIT ?", (limit,))
            return [from_json(row["doc"]) for row in rows]
        return list(self.mem_restaurant_menus.values())[:limit]

    def count_restaurant_menus(self) -> int:
        if self.use_sql:
            return int(self.sql.query_one("SELECT COUNT(*) AS n FROM restaurant_menus")["n"])
        return len(self.mem_restaurant_menus)

    def clear_restaurant_menus(self) -> int:
        """清空菜單快取。建檔邏輯改過之後（例如開始過濾歇業店家），
        舊資料是用舊規則建的，要重建才拿得到乾淨的結果。"""
        removed = self.count_restaurant_menus()
        if self.use_sql:
            self.sql.execute("DELETE FROM restaurant_menus")
        else:
            self.mem_restaurant_menus.clear()
        return removed

    def save_restaurant_menu(self, name: str, items: list, venue: dict | None = None) -> None:
        venue = venue or {}
        place_id = venue.get("google_place_id") or ""
        key = self.venue_cache_key(name, place_id)
        if not key or not items:
            return
        name_key = self.venue_name_key(name)
        doc = {
            "venue_key": key, "name": name, "name_key": name_key, "items": items,
            "cached_at": datetime.now(timezone.utc).isoformat(),
            **venue,
        }
        if self.use_sql:
            self.sql.execute(
                """
                INSERT INTO restaurant_menus (venue_key, name, name_key, doc, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (venue_key)
                DO UPDATE SET name = excluded.name, name_key = excluded.name_key,
                              doc = excluded.doc, updated_at = excluded.updated_at
                """,
                (key, name, name_key, to_json(doc), utc_iso()),
            )
            return
        self.mem_restaurant_menus[key] = doc

    # ─── 問不出菜單的店家 ────────────────────────────────────
    # 模型看不出一家店賣什麼時，幾小時內再問多半還是一樣，只會把下一次建檔的
    # 時間預算燒在同一家上。記在資料庫而不是記憶體：後端重啟後記憶體裡的紀錄
    # 會全部消失。
    def active_restaurant_menu_failures(self, keys: list[str]) -> set[str]:
        """這些 venue key 裡，哪些還在冷卻期。"""
        keys = [key for key in keys if key]
        if not keys:
            return set()
        now = datetime.now(timezone.utc)
        if self.use_sql:
            placeholders = ", ".join("?" for _ in keys)
            rows = self.sql.query_all(
                f"SELECT venue_key FROM restaurant_menu_failures WHERE venue_key IN ({placeholders}) AND failed_until > ?",
                (*keys, utc_iso(now)),
            )
            return {row["venue_key"] for row in rows}
        return {
            key for key in keys
            if key in self.mem_restaurant_menu_failures
            and self.mem_restaurant_menu_failures[key]["failed_until"] > now
        }

    def mark_restaurant_menu_failure(self, key: str, reason: str, cooldown_seconds: float) -> None:
        if not key:
            return
        now = datetime.now(timezone.utc)
        failed_until = now + timedelta(seconds=cooldown_seconds)
        if self.use_sql:
            with self.sql.transaction():
                # 過期的順手清掉，表格才不會一直長大
                self.sql.execute("DELETE FROM restaurant_menu_failures WHERE failed_until <= ?", (utc_iso(now),))
                self.sql.execute(
                    """
                    INSERT INTO restaurant_menu_failures (venue_key, reason, failed_until)
                    VALUES (?, ?, ?)
                    ON CONFLICT (venue_key)
                    DO UPDATE SET reason = excluded.reason, failed_until = excluded.failed_until
                    """,
                    (key, reason, utc_iso(failed_until)),
                )
            return
        for expired in [k for k, v in self.mem_restaurant_menu_failures.items() if v["failed_until"] <= now]:
            del self.mem_restaurant_menu_failures[expired]
        self.mem_restaurant_menu_failures[key] = {"reason": reason, "failed_until": failed_until}

    def clear_restaurant_menu_failures(self) -> None:
        """清除菜單檔案重建時一起清，先前問不出菜單的店也要照新規則再問一次。"""
        if self.use_sql:
            self.sql.execute("DELETE FROM restaurant_menu_failures")
        else:
            self.mem_restaurant_menu_failures.clear()

    def get_custom_food(self, food_id: str, user_id: str | None = None):
        if not user_id:
            return None
        if self.use_sql:
            return self._fetch_json_doc("custom_foods", "owner_key", self._custom_food_owner_key(user_id, food_id))
        for doc in self.mem_custom_foods:
            if doc.get("food_id") == food_id and doc.get("user_id") == user_id:
                return doc
        return None

    def upsert_custom_food(self, food_doc: dict):
        owner_key = self._custom_food_owner_key(food_doc.get("user_id"), food_doc["food_id"])
        stored_doc = {**food_doc, "owner_key": owner_key}
        if self.use_sql:
            self.sql.execute(
                """
                INSERT INTO custom_foods (owner_key, food_id, user_id, doc, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (owner_key)
                DO UPDATE SET food_id = excluded.food_id, user_id = excluded.user_id,
                              doc = excluded.doc, updated_at = excluded.updated_at
                """,
                (owner_key, stored_doc["food_id"], stored_doc.get("user_id"), to_json(stored_doc), utc_iso()),
            )
            return stored_doc
        for idx, existing in enumerate(self.mem_custom_foods):
            if existing.get("owner_key") == owner_key:
                self.mem_custom_foods[idx] = stored_doc
                break
        else:
            self.mem_custom_foods.append(stored_doc)
        return stored_doc
