from collections import defaultdict
from datetime import datetime, timedelta, timezone
import uuid

from psycopg2.extras import Json, RealDictCursor
from services.app_time_service import app_now, app_today
from services.nutrient_service import NUTRITION_FIELDS, get_nutrient_value, nutrient_number


class StorageRepository:
    def __init__(self, db, use_mongo: bool, mem_users: dict, mem_records: list, mem_custom_foods: list, pg_conn=None):
        self.db = db
        self.use_mongo = use_mongo
        self.pg_conn = pg_conn
        self.use_postgres = pg_conn is not None
        self.mem_users = mem_users
        self.mem_records = mem_records
        self.mem_custom_foods = mem_custom_foods
        self.mem_restaurant_menus: dict = {}
        if self.use_postgres:
            self._init_postgres_tables()

    def _init_postgres_tables(self):
        with self.pg_conn.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    doc JSONB NOT NULL,
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                );
                """
            )
            cursor.execute(
                """
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
                """
            )
            for nutrient in ("sugar", "saturated_fat", "trans_fat"):
                cursor.execute(
                    f"ALTER TABLE records ADD COLUMN IF NOT EXISTS total_{nutrient} DOUBLE PRECISION DEFAULT 0;"
                )
            cursor.execute(
                """
                UPDATE records
                SET client_record_id = COALESCE(
                    client_record_id,
                    'legacy_record_' || id::text || '_' || substr(md5(random()::text), 1, 8)
                )
                WHERE client_record_id IS NULL;
                """
            )
            cursor.execute("ALTER TABLE records ALTER COLUMN client_record_id SET NOT NULL;")
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS custom_foods (
                    owner_key TEXT PRIMARY KEY,
                    food_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    doc JSONB NOT NULL,
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                );
                """
            )
            cursor.execute("ALTER TABLE custom_foods ADD COLUMN IF NOT EXISTS owner_key TEXT;")
            cursor.execute("ALTER TABLE custom_foods ADD COLUMN IF NOT EXISTS food_id TEXT;")
            cursor.execute(
                """
                UPDATE custom_foods
                SET owner_key = COALESCE(owner_key, user_id || ':' || food_id)
                WHERE owner_key IS NULL
                  AND user_id IS NOT NULL
                  AND food_id IS NOT NULL;
                """
            )
            cursor.execute("ALTER TABLE custom_foods DROP CONSTRAINT IF EXISTS custom_foods_pkey;")
            cursor.execute("ALTER TABLE custom_foods ALTER COLUMN owner_key SET NOT NULL;")
            cursor.execute("ALTER TABLE custom_foods ADD PRIMARY KEY (owner_key);")
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS restaurant_menus (
                    venue_key TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    doc JSONB NOT NULL,
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                );
                """
            )
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_records_user_timestamp ON records (user_id, timestamp DESC);")
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_records_user_client_record ON records (user_id, client_record_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_custom_foods_user_id ON custom_foods (user_id);")
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_custom_foods_owner_key ON custom_foods (owner_key);")

    def _fetch_json_doc(self, table: str, key_field: str, key_value: str):
        with self.pg_conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(f"SELECT doc FROM {table} WHERE {key_field} = %s", (key_value,))
            row = cursor.fetchone()
        return row["doc"] if row else None

    def get_user(self, user_id: str):
        user_doc = None
        if self.use_postgres:
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
                "diet_type": "均衡飲食",
                "updated_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
            }
            self.upsert_user(user_doc)

        return user_doc


    def upsert_user(self, user_doc: dict):
        if self.use_postgres:
            with self.pg_conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO users (user_id, doc, updated_at)
                    VALUES (%s, %s, NOW())
                    ON CONFLICT (user_id)
                    DO UPDATE SET doc = EXCLUDED.doc, updated_at = NOW()
                    """,
                    (user_doc["user_id"], Json(user_doc)),
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


        if self.use_postgres:
            with self.pg_conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO records (
                        user_id, client_record_id, timestamp, meal_type, foods,
                        total_calories, total_protein, total_carbs,
                        total_fat, total_sodium, total_fiber, total_sugar,
                        total_saturated_fat, total_trans_fat, source
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        record.get("user_id"),
                        record.get("client_record_id"),
                        record.get("timestamp"),
                        record.get("meal_type"),
                        Json(record.get("foods", [])),
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
                    ),
                )
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
        if self.use_postgres:
            with self.pg_conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT user_id, client_record_id, timestamp, meal_type, foods, total_calories, total_protein,
                           total_carbs, total_fat, total_sodium, total_fiber,
                           total_sugar, total_saturated_fat, total_trans_fat, source
                    FROM records
                    WHERE user_id = %s AND client_record_id = %s
                    LIMIT 1
                    """,
                    (user_id, client_record_id),
                )
                row = cursor.fetchone()
            return self._enrich_record_totals(dict(row)) if row else None
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

        if self.use_postgres:
            with self.pg_conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    UPDATE records
                    SET timestamp = %s, meal_type = %s, foods = %s,
                        total_calories = %s, total_protein = %s, total_carbs = %s,
                        total_fat = %s, total_sodium = %s, total_fiber = %s,
                        total_sugar = %s, total_saturated_fat = %s,
                        total_trans_fat = %s,
                        source = %s
                    WHERE user_id = %s AND client_record_id = %s
                    RETURNING user_id, client_record_id, timestamp, meal_type, foods,
                              total_calories, total_protein, total_carbs, total_fat,
                              total_sodium, total_fiber, total_sugar,
                              total_saturated_fat, total_trans_fat, source
                    """,
                    (
                        record.get("timestamp"),
                        record.get("meal_type"),
                        Json(record.get("foods", [])),
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
                        user_id,
                        client_record_id,
                    ),
                )
                row = cursor.fetchone()
            return self._enrich_record_totals(dict(row)) if row else None

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
        if self.use_postgres:
            with self.pg_conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    DELETE FROM records
                    WHERE user_id = %s AND client_record_id = %s
                    RETURNING user_id, client_record_id, timestamp, meal_type, foods,
                              total_calories, total_protein, total_carbs, total_fat,
                              total_sodium, total_fiber, total_sugar,
                              total_saturated_fat, total_trans_fat, source
                    """,
                    (user_id, client_record_id),
                )
                row = cursor.fetchone()
            return self._enrich_record_totals(dict(row)) if row else None

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
        if self.use_postgres:
            sql = """
                SELECT user_id, client_record_id, timestamp, meal_type, foods, total_calories, total_protein,
                       total_carbs, total_fat, total_sodium, total_fiber,
                       total_sugar, total_saturated_fat, total_trans_fat, source
                FROM records
                WHERE user_id = %s
            """
            params = [user_id]
            if date_str:
                sql += " AND timestamp LIKE %s"
                params.append(f"{date_str}%")
            sql += " ORDER BY timestamp DESC LIMIT %s OFFSET %s"
            params.extend([limit, offset])
            with self.pg_conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(sql, params)
                rows = cursor.fetchall()
            return [self._enrich_record_totals(dict(row)) for row in rows]

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

        if self.use_postgres:
            nutrient_sums = ",\n                           ".join(
                f"SUM(total_{nutrient}) AS {nutrient}" for nutrient in NUTRITION_FIELDS
            )
            with self.pg_conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    f"""
                    SELECT SUBSTRING(timestamp, 1, 10) AS date,
                           COUNT(*) AS record_count,
                           {nutrient_sums}
                    FROM records
                    WHERE user_id = %s
                      AND timestamp >= %s
                      AND timestamp <= %s
                    GROUP BY SUBSTRING(timestamp, 1, 10)
                    ORDER BY date ASC
                    """,
                    (user_id, start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d") + "T23:59:59"),
                )
                rows = cursor.fetchall()
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
        if self.use_postgres:
            sql = "SELECT doc FROM custom_foods"
            params = []
            if user_id:
                sql += " WHERE user_id = %s"
                params.append(user_id)
            sql += " ORDER BY updated_at DESC"
            with self.pg_conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(sql, params)
                rows = cursor.fetchall()
            return [row["doc"] for row in rows]

        if self.use_mongo:
            query = {"user_id": user_id} if user_id else {}
            return list(self.db.custom_foods.find(query, {"_id": 0}).sort("updated_at", -1))

        docs = list(self.mem_custom_foods)
        if user_id:
            docs = [doc for doc in docs if doc.get("user_id") == user_id]
        return docs

    def _custom_food_owner_key(self, user_id: str | None, food_id: str) -> str:
        normalized_user_id = user_id or "demo_user"
        return f"{normalized_user_id}:{food_id}"

    # ─── 店家菜單快取 ────────────────────────────────────────
    # Gemini 分析一家店要 20~30 秒，Render 的檔案系統又是暫存的
    # （寫回 restaurant_catalog.json 重啟就沒了），所以存進資料庫。
    @staticmethod
    def venue_cache_key(name: str) -> str:
        return str(name or "").strip().lower()

    def get_restaurant_menu(self, name: str):
        key = self.venue_cache_key(name)
        if not key:
            return None
        if self.use_postgres:
            with self.pg_conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SELECT doc FROM restaurant_menus WHERE venue_key = %s LIMIT 1", (key,))
                row = cursor.fetchone()
            return row["doc"] if row else None
        if self.use_mongo:
            return self.db.restaurant_menus.find_one({"venue_key": key}, {"_id": 0})
        return self.mem_restaurant_menus.get(key)

    def save_restaurant_menu(self, name: str, items: list) -> None:
        key = self.venue_cache_key(name)
        if not key or not items:
            return
        doc = {"venue_key": key, "name": name, "items": items}
        if self.use_postgres:
            with self.pg_conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO restaurant_menus (venue_key, name, doc, updated_at)
                    VALUES (%s, %s, %s, NOW())
                    ON CONFLICT (venue_key)
                    DO UPDATE SET name = EXCLUDED.name, doc = EXCLUDED.doc, updated_at = NOW()
                    """,
                    (key, name, Json(doc)),
                )
            return
        if self.use_mongo:
            self.db.restaurant_menus.update_one({"venue_key": key}, {"$set": doc}, upsert=True)
            return
        self.mem_restaurant_menus[key] = doc

    def get_custom_food(self, food_id: str, user_id: str | None = None):
        if not user_id:
            return None
        if self.use_postgres:
            with self.pg_conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    "SELECT doc FROM custom_foods WHERE owner_key = %s LIMIT 1",
                    (self._custom_food_owner_key(user_id, food_id),),
                )
                row = cursor.fetchone()
            return row["doc"] if row else None
        if self.use_mongo:
            return self.db.custom_foods.find_one({"food_id": food_id, "user_id": user_id}, {"_id": 0})
        for doc in self.mem_custom_foods:
            if doc.get("food_id") == food_id and doc.get("user_id") == user_id:
                return doc
        return None

    def upsert_custom_food(self, food_doc: dict):
        owner_key = self._custom_food_owner_key(food_doc.get("user_id"), food_doc["food_id"])
        stored_doc = {**food_doc, "owner_key": owner_key}
        if self.use_postgres:
            with self.pg_conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO custom_foods (owner_key, food_id, user_id, doc, updated_at)
                    VALUES (%s, %s, %s, %s, NOW())
                    ON CONFLICT (owner_key)
                    DO UPDATE SET food_id = EXCLUDED.food_id, user_id = EXCLUDED.user_id, doc = EXCLUDED.doc, updated_at = NOW()
                    """,
                    (owner_key, stored_doc["food_id"], stored_doc.get("user_id"), Json(stored_doc)),
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
