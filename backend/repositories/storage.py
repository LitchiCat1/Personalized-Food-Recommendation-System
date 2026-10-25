from collections import defaultdict
from datetime import datetime, timedelta, timezone
import uuid

from repositories.sqlite_db import SqliteDatabase, from_json, to_json, utc_iso
from services.app_time_service import app_now, app_today
from services.nutrient_service import NUTRITION_FIELDS, get_nutrient_value, nutrient_number


# 飲食紀錄表的欄位（不含流水號 id）。insert / update / select 都照這個順序。
RECORD_COLUMNS = (
    "user_id", "client_record_id", "timestamp", "meal_type", "foods",
    "total_calories", "total_protein", "total_carbs", "total_fat",
    "total_sodium", "total_fiber", "total_sugar",
    "total_saturated_fat", "total_trans_fat", "source",
)
RECORD_SELECT = ", ".join(RECORD_COLUMNS)


# Render 用的 Supabase（Postgres）。型別跟 nutrilens 專案現有的表一致：
# 表已經存在時 CREATE ... IF NOT EXISTS 什麼都不做，舊資料原封不動。
# 每張表都開 RLS：後端是表的擁有者不受影響，但 Supabase 的公開 API（anon key）就讀不到。
POSTGRES_TABLES = """
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    doc JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS records (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    client_record_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    meal_type TEXT,
    foods JSONB,
    total_calories DOUBLE PRECISION DEFAULT 0,
    total_protein DOUBLE PRECISION DEFAULT 0,
    total_carbs DOUBLE PRECISION DEFAULT 0,
    total_fat DOUBLE PRECISION DEFAULT 0,
    total_sodium DOUBLE PRECISION DEFAULT 0,
    total_fiber DOUBLE PRECISION DEFAULT 0,
    total_sugar DOUBLE PRECISION DEFAULT 0,
    total_saturated_fat DOUBLE PRECISION DEFAULT 0,
    total_trans_fat DOUBLE PRECISION DEFAULT 0,
    source TEXT DEFAULT 'camera'
);
CREATE INDEX IF NOT EXISTS idx_records_user_timestamp ON records (user_id, timestamp DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_records_user_client_record ON records (user_id, client_record_id);
CREATE TABLE IF NOT EXISTS custom_foods (
    owner_key TEXT PRIMARY KEY,
    food_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    doc JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_custom_foods_user_id ON custom_foods (user_id);
CREATE TABLE IF NOT EXISTS restaurant_menus (
    venue_key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    name_key TEXT,
    doc JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_restaurant_menus_name ON restaurant_menus (name_key);
CREATE TABLE IF NOT EXISTS restaurant_menu_failures (
    venue_key TEXT PRIMARY KEY,
    reason TEXT NOT NULL,
    failed_until TIMESTAMPTZ NOT NULL
);
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE records ENABLE ROW LEVEL SECURITY;
ALTER TABLE custom_foods ENABLE ROW LEVEL SECURITY;
ALTER TABLE restaurant_menus ENABLE ROW LEVEL SECURITY;
ALTER TABLE restaurant_menu_failures ENABLE ROW LEVEL SECURITY;
"""


class StorageRepository:
    def __init__(self, db, use_mongo: bool, mem_users: dict, mem_records: list, mem_custom_foods: list, sql: SqliteDatabase | None = None):
        self.db = db
        self.use_mongo = use_mongo
        self.sql = sql
        self.use_sql = sql is not None
        self.mem_users = mem_users
        self.mem_records = mem_records
        self.mem_custom_foods = mem_custom_foods
        self.mem_restaurant_menus: dict = {}
        self.mem_restaurant_menu_failures: dict = {}
        if self.use_sql:
            self._init_tables()

    def _init_tables(self):
        if self.sql.dialect == "postgres":
            self.sql.executescript(POSTGRES_TABLES)
            return
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
                source TEXT DEFAULT 'camera'
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

    def _fetch_json_doc(self, table: str, key_field: str, key_value: str):
        row = self.sql.query_one(f"SELECT doc FROM {table} WHERE {key_field} = ?", (key_value,))
        return from_json(row["doc"]) if row else None

    def _record_from_row(self, row: dict | None):
        if not row:
            return None
        record = dict(row)
        record.pop("id", None)
        record["foods"] = from_json(record.get("foods")) or []
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
        )

    def get_user(self, user_id: str):
        user_doc = None
        if self.use_sql:
            user_doc = self._fetch_json_doc("users", "user_id", user_id)
        elif self.use_mongo:
            user_doc = self.db.users.find_one({"user_id": user_id}, {"_id": 0})
        else:
            user_doc = self.mem_users.get(user_id)

        # Developer auto-fallback: auto-create default user profile for demo_user if missing
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
        if self.use_mongo:
            self.db.users.update_one({"user_id": user_doc["user_id"]}, {"$set": user_doc}, upsert=True)
        else:
            self.mem_users[user_doc["user_id"]] = user_doc
        return user_doc

    def _enrich_record_totals(self, record: dict) -> dict:
        if not record or "foods" not in record:
            return record

        foods = record.get("foods") or []
        if foods:
            for nutrient in NUTRITION_FIELDS:
                record[f"total_{nutrient}"] = round(
                    sum(nutrient_number(get_nutrient_value(food, nutrient)) for food in foods),
                    2,
                )
        record["contains_fried_food"] = any(food.get("is_fried") is True for food in foods)
        return record

    def insert_record(self, record: dict):
        if not record.get("client_record_id"):
            record = {**record, "client_record_id": f"server_record_{uuid.uuid4().hex}"}
        existing = self.get_record_by_client_record_id(record.get("user_id"), record.get("client_record_id"))
        if existing:
            return {**self._enrich_record_totals(existing), "_deduplicated": True}


        if self.use_sql:
            placeholders = ", ".join("?" for _ in RECORD_COLUMNS)
            # 同一筆同時送兩次（離線補傳加上手動重按）時，上面兩邊都查不到。唯一索引
            # 擋得住重複，但後到的那個會撞 IntegrityError 變成 500；讓資料庫直接略過，
            # 再查回先寫進去的那筆。SQLite 和 Postgres 都支援這個寫法。
            inserted = self.sql.execute(
                f"INSERT INTO records ({RECORD_SELECT}) VALUES ({placeholders}) "
                "ON CONFLICT (user_id, client_record_id) DO NOTHING",
                self._record_values(record),
            )
            if not inserted:
                existing = self.get_record_by_client_record_id(record.get("user_id"), record.get("client_record_id"))
                return {**existing, "_deduplicated": True}
            return self._enrich_record_totals(record)
        if self.use_mongo:
            self.db.records.insert_one(record)
        else:
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
        if self.use_mongo:
            res = self.db.records.find_one({"user_id": user_id, "client_record_id": client_record_id}, {"_id": 0})
            return self._enrich_record_totals(res) if res else None
        for record in self.mem_records:
            if record.get("user_id") == user_id and record.get("client_record_id") == client_record_id:
                return self._enrich_record_totals(record)
        return None

    def update_record(self, record: dict):
        user_id = record.get("user_id")
        client_record_id = record.get("client_record_id")
        if not user_id or not client_record_id:
            return None

        if self.use_sql:
            values = self._record_values(record)
            # 前兩個是 user_id / client_record_id，放到 WHERE
            assignments = ", ".join(f"{column} = ?" for column in RECORD_COLUMNS[2:])
            with self.sql.transaction():
                changed = self.sql.execute(
                    f"UPDATE records SET {assignments} WHERE user_id = ? AND client_record_id = ?",
                    (*values[2:], user_id, client_record_id),
                )
                if not changed:
                    return None
                return self.get_record_by_client_record_id(user_id, client_record_id)

        if self.use_mongo:
            result = self.db.records.update_one(
                {"user_id": user_id, "client_record_id": client_record_id},
                {"$set": record},
            )
            if result.matched_count == 0:
                return None
            return self.get_record_by_client_record_id(user_id, client_record_id)

        for index, existing in enumerate(self.mem_records):
            if existing.get("user_id") == user_id and existing.get("client_record_id") == client_record_id:
                self.mem_records[index] = record
                return self._enrich_record_totals(record)
        return None

    def delete_record(self, user_id: str, client_record_id: str):
        if self.use_sql:
            with self.sql.transaction():
                existing = self.get_record_by_client_record_id(user_id, client_record_id)
                if existing:
                    self.sql.execute(
                        "DELETE FROM records WHERE user_id = ? AND client_record_id = ?",
                        (user_id, client_record_id),
                    )
            return existing

        if self.use_mongo:
            record = self.db.records.find_one_and_delete(
                {"user_id": user_id, "client_record_id": client_record_id}
            )
            if record:
                record.pop("_id", None)
            return self._enrich_record_totals(record) if record else None

        for index, record in enumerate(self.mem_records):
            if record.get("user_id") == user_id and record.get("client_record_id") == client_record_id:
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

        if self.use_mongo:
            query = {"user_id": user_id}
            if date_str:
                query["timestamp"] = {"$regex": f"^{date_str}"}
            res_list = list(self.db.records.find(query, {"_id": 0}).sort("timestamp", -1).skip(offset).limit(limit))
            return [self._enrich_record_totals(r) for r in res_list]

        records = [r for r in self.mem_records if r.get("user_id") == user_id]
        if date_str:
            records = [r for r in records if str(r.get("timestamp", "")).startswith(date_str)]
        records.sort(key=lambda record: str(record.get("timestamp", "")), reverse=True)
        slice_records = records[offset:offset + limit]
        return [self._enrich_record_totals(r) for r in slice_records]

    def get_today_records(self, user_id: str):
        return self.get_records(user_id, app_today(), limit=500)

    def get_history(self, user_id: str, days: int):
        end_date = app_now().replace(tzinfo=None)
        start_date = end_date - timedelta(days=days)

        if self.use_sql:
            nutrient_sums = ",\n                       ".join(
                f"SUM(total_{nutrient}) AS {nutrient}" for nutrient in NUTRITION_FIELDS
            )
            rows = self.sql.query_all(
                f"""
                SELECT substr(timestamp, 1, 10) AS date,
                       COUNT(*) AS record_count,
                       {nutrient_sums}
                FROM records
                WHERE user_id = ?
                  AND timestamp >= ?
                  AND timestamp <= ?
                GROUP BY substr(timestamp, 1, 10)
                ORDER BY date ASC
                """,
                (user_id, start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d") + "T23:59:59"),
            )
            return [
                {
                    "date": row["date"],
                    "record_count": int(row["record_count"] or 0),
                    **{nutrient: round(row[nutrient] or 0, 1) for nutrient in NUTRITION_FIELDS},
                }
                for row in rows
            ]

        if self.use_mongo:
            pipeline = [
                {
                    "$match": {
                        "user_id": user_id,
                        "timestamp": {
                            "$gte": start_date.strftime("%Y-%m-%d"),
                            "$lte": end_date.strftime("%Y-%m-%d") + "T23:59:59",
                        },
                    }
                },
                {
                    "$group": {
                        "_id": {"$substr": ["$timestamp", 0, 10]},
                        "record_count": {"$sum": 1},
                        **{
                            nutrient: {"$sum": f"$total_{nutrient}"}
                            for nutrient in NUTRITION_FIELDS
                        },
                    }
                },
                {"$sort": {"_id": 1}},
            ]
            daily = list(self.db.records.aggregate(pipeline))
            return [
                {
                    "date": d["_id"],
                    "record_count": d["record_count"],
                    **{nutrient: d.get(nutrient, 0) for nutrient in NUTRITION_FIELDS},
                }
                for d in daily
            ]

        agg = defaultdict(lambda: {"record_count": 0, **{nutrient: 0 for nutrient in NUTRITION_FIELDS}})
        for record in self.mem_records:
            if record.get("user_id") != user_id:
                continue
            day = str(record.get("timestamp", ""))[:10]
            if not day:
                continue
            agg[day]["record_count"] += 1
            record = self._enrich_record_totals(record)
            for nutrient in NUTRITION_FIELDS:
                agg[day][nutrient] += record.get(f"total_{nutrient}", 0)
        return [{"date": k, **v} for k, v in sorted(agg.items())]

    def get_custom_foods(self, user_id: str | None = None):
        if self.use_sql:
            sql = "SELECT doc FROM custom_foods"
            params = []
            if user_id:
                sql += " WHERE user_id = ?"
                params.append(user_id)
            sql += " ORDER BY updated_at DESC"
            return [from_json(row["doc"]) for row in self.sql.query_all(sql, params)]

        if self.use_mongo:
            query = {"user_id": user_id} if user_id else {}
            return list(self.db.custom_foods.find(query, {"_id": 0}).sort("updated_at", -1))

        docs = list(self.mem_custom_foods)
        if user_id:
            docs = [doc for doc in docs if doc.get("user_id") == user_id]
        return docs

    def count_custom_foods(self) -> int:
        """/health 用。只要筆數，不必把每個人的自訂食品整份讀出來再解析。"""
        if self.use_sql:
            return int(self.sql.query_one("SELECT COUNT(*) AS n FROM custom_foods")["n"])
        if self.use_mongo:
            return self.db.custom_foods.count_documents({})
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
        if self.use_mongo:
            return self.db.restaurant_menus.find_one(
                {"$or": [{"venue_key": {"$in": keys}}, {"name_key": name_key}]}, {"_id": 0}
            )
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
        if self.use_mongo:
            return list(self.db.restaurant_menus.find({}, {"_id": 0}).limit(limit))
        return list(self.mem_restaurant_menus.values())[:limit]

    def count_restaurant_menus(self) -> int:
        if self.use_sql:
            return int(self.sql.query_one("SELECT COUNT(*) AS n FROM restaurant_menus")["n"])
        if self.use_mongo:
            return self.db.restaurant_menus.count_documents({})
        return len(self.mem_restaurant_menus)

    def clear_restaurant_menus(self) -> int:
        """清空菜單快取。建檔邏輯改過之後（例如開始過濾歇業店家），
        舊資料是用舊規則建的，要重建才拿得到乾淨的結果。"""
        removed = self.count_restaurant_menus()
        if self.use_sql:
            self.sql.execute("DELETE FROM restaurant_menus")
        elif self.use_mongo:
            self.db.restaurant_menus.delete_many({})
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
        if self.use_mongo:
            self.db.restaurant_menus.update_one({"venue_key": key}, {"$set": doc}, upsert=True)
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
        if self.use_mongo:
            docs = self.db.restaurant_menu_failures.find(
                {"venue_key": {"$in": keys}, "failed_until": {"$gt": now}}, {"_id": 0, "venue_key": 1}
            )
            return {doc["venue_key"] for doc in docs}
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
        if self.use_mongo:
            self.db.restaurant_menu_failures.delete_many({"failed_until": {"$lte": now}})
            self.db.restaurant_menu_failures.update_one(
                {"venue_key": key},
                {"$set": {"venue_key": key, "reason": reason, "failed_until": failed_until}},
                upsert=True,
            )
            return
        for expired in [k for k, v in self.mem_restaurant_menu_failures.items() if v["failed_until"] <= now]:
            del self.mem_restaurant_menu_failures[expired]
        self.mem_restaurant_menu_failures[key] = {"reason": reason, "failed_until": failed_until}

    def clear_restaurant_menu_failures(self) -> None:
        """清除菜單檔案重建時一起清，先前問不出菜單的店也要照新規則再問一次。"""
        if self.use_sql:
            self.sql.execute("DELETE FROM restaurant_menu_failures")
        elif self.use_mongo:
            self.db.restaurant_menu_failures.delete_many({})
        else:
            self.mem_restaurant_menu_failures.clear()

    def get_custom_food(self, food_id: str, user_id: str | None = None):
        if not user_id:
            return None
        if self.use_sql:
            return self._fetch_json_doc("custom_foods", "owner_key", self._custom_food_owner_key(user_id, food_id))
        if self.use_mongo:
            return self.db.custom_foods.find_one({"food_id": food_id, "user_id": user_id}, {"_id": 0})
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
        if self.use_mongo:
            self.db.custom_foods.update_one({"owner_key": owner_key}, {"$set": stored_doc}, upsert=True)
        else:
            for idx, existing in enumerate(self.mem_custom_foods):
                if existing.get("owner_key") == owner_key:
                    self.mem_custom_foods[idx] = stored_doc
                    break
            else:
                self.mem_custom_foods.append(stored_doc)
        return stored_doc
