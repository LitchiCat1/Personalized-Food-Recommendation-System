"""重設某個帳號的密碼。

本地端沒有寄信功能，忘記密碼時就在這台電腦上執行（在專案根目錄）：

    python backend/scripts/reset_password.py someone@example.com

會要求輸入兩次新密碼（輸入時畫面上不會顯示）。重設後，這個帳號在每個裝置
上都要重新登入。不帶 Email 執行會列出所有帳號。
"""

import getpass
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

from repositories.auth_repository import AuthRepository  # noqa: E402
from repositories.sqlite_db import SqliteDatabase, resolve_database_path  # noqa: E402
from services.auth_service import AuthError, reset_password  # noqa: E402
from services.env_service import load_local_env  # noqa: E402


def main() -> int:
    load_local_env()
    database_path = resolve_database_path()
    if not database_path or database_path == ":memory:" or not os.path.exists(database_path):
        print(f"找不到資料庫檔案：{database_path}")
        return 1

    sql = SqliteDatabase(database_path)
    repo = AuthRepository(sql)

    if len(sys.argv) < 2:
        rows = sql.query_all("SELECT email, created_at FROM auth_users ORDER BY created_at")
        print(f"共 {len(rows)} 個帳號：")
        for row in rows:
            print(f"  {row['email']}（{(row['created_at'] or '')[:10]} 建立）")
        print("\n用法：python backend/scripts/reset_password.py <Email>")
        return 0

    email = sys.argv[1]
    new_password = getpass.getpass("新密碼：")
    if new_password != getpass.getpass("再輸入一次："):
        print("兩次輸入的密碼不一樣，沒有變更。")
        return 1
    try:
        user = reset_password(repo, email, new_password)
    except AuthError as error:
        print(error)
        return 1
    print(f"已重設 {user['email']} 的密碼。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
