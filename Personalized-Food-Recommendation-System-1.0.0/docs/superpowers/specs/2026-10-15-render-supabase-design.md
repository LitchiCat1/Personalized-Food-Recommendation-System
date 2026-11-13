# Render 用 Supabase、本機用 SQLite：設計

日期：2026-10-15　分支：v0.0.9

## 目標

- Render 上的後端（`pfrs`）改把資料存在 Supabase 的 `nutrilens` 專案（Postgres），部署和休眠都不會再清空帳號與紀錄。
- 本機照舊用 SQLite（`%LOCALAPPDATA%\NutriLens\nutrilens.db`），不需要網路、不需要任何雲端帳號。
- 登入方式兩邊一樣：暱稱＋密碼（bcrypt），後端發 token。前端完全不改。
- `nutrilens` 專案裡的舊資料接得上：18 個舊帳號用原本的 Email 當暱稱、原本的密碼登入，388 筆紀錄和 213 份店家菜單照常使用。

## 不做的事

- 不用 Supabase Auth，也不裝回 `@supabase/supabase-js`。
- 不支援把店家菜單放在另一個資料庫（舊的 `MENU_DATABASE_URL` 不再讀取）。
- 不做本機 SQLite 和 Supabase 之間的資料同步。
- 不碰另一個專案 `NutriLens-Zhuang`。

## 現況

- `backend/repositories/sqlite_db.py` 的 `SqliteDatabase` 提供 `execute`、`executescript`、`query_one`、`query_all`、`column_names`、`transaction`、`close`。整個後端只開一條連線，用 `RLock` 排隊。
- `StorageRepository`（`storage.py`）和 `AuthRepository`（`auth_repository.py`）透過這個介面下 SQL：佔位符是 `?`，新增或更新用 `ON CONFLICT ... DO UPDATE` / `DO NOTHING`，日期查詢用 `substr(timestamp, 1, 10)` 和 `LIKE`。這些寫法 Postgres 都支援。
- JSON 欄位（`doc`、`foods`）存成字串，讀回來用 `from_json()` 解析；時間存成 `utc_iso()` 的固定寬度字串。
- `app.py` 啟動時只建 SQLite（`resolve_database_path()`），沒有資料庫時退回 MongoDB 或記憶體。
- Supabase `nutrilens` 專案現有的表：`users`、`records`、`custom_foods`、`restaurant_menus`、`restaurant_menu_failures`（還有用不到的 `recommendation_feedback`），全部開著 RLS。欄位型別和 SQLite 版不同：`doc`、`foods` 是 `jsonb`，`updated_at`、`failed_until` 是 `timestamptz`，`records.id` 是 `bigint` 自動編號，`records.timestamp` 是 `text`（和 SQLite 一樣）。`records` 多了 `total_calcium`、`total_iron` 兩欄，程式不會用到，有預設值 0。
- 舊帳號在 Supabase 的 `auth.users`，沒有 `auth_users` / `auth_sessions` 這兩張表。

## 設計

### 1. 選資料庫

`app.py` 啟動時：

1. 有設 `DATABASE_URL` → 建 `PostgresDatabase(DATABASE_URL)`。
2. 沒設 → 跟現在一樣走 `resolve_database_path()` 建 `SqliteDatabase`。
3. 兩個都沒有 → 跟現在一樣退回 MongoDB 或記憶體。

有設 `DATABASE_URL` 但連不上時，印出錯誤後**直接結束程式**（exit code 1），不退回記憶體。Render 部署會失敗並繼續跑上一版，不會出現「看起來正常、資料其實沒存」的狀況。錯誤訊息裡不能出現連線字串裡的密碼。

`backend/.env.local` 目前沒有 `DATABASE_URL`，所以本機不受影響。測試一律在開頭移除 `DATABASE_URL`（和現在移除 `DATABASE_PATH` 的做法一樣），避免開發者的環境變數讓測試連到正式資料庫。

`scripts/reset_password.py` 用同一套選法，設了 `DATABASE_URL` 就能重設 Render 上的帳號密碼。

選資料庫的邏輯放在新檔 `repositories/database.py` 的 `open_database()`，`app.py` 和 `reset_password.py` 共用。它回傳 `(資料庫物件或 None, 說明文字)`，說明文字給啟動訊息用，不含密碼。

### 2. `PostgresDatabase`

新檔 `backend/repositories/postgres_db.py`，用 `psycopg2-binary`（加進 `requirements.txt`）。介面和 `SqliteDatabase` 一模一樣，另外多一個屬性 `dialect`：SQLite 版是 `"sqlite"`，Postgres 版是 `"postgres"`。

- **連線**：一條連線，`autocommit = True`，和 SQLite 版一樣用 `RLock` 排隊。主機是 `localhost` / `127.0.0.1` 用 `sslmode=prefer`，其他一律 `sslmode=require`；網址自己寫了 `sslmode=` 就照網址的。設 `connect_timeout=10`。
- **佔位符**：先把 SQL 裡的 `%` 換成 `%%`，再把 `?` 換成 `%s`。目前的 SQL 字串裡沒有字面上的 `?`；`LIKE` 的 `%` 都放在參數裡，不受影響。
- **讀回來的型別**：
  - `jsonb` 欄位 psycopg2 會直接解析成 dict / list。`from_json()` 改成：收到的已經不是字串就原樣回傳。
  - `timestamptz` 欄位會變成 `datetime`。`query_one` / `query_all` 把每個 `datetime` 轉成 `utc_iso()` 字串，上層看到的格式和 SQLite 一樣。
- **寫入的型別**：繼續傳 JSON 字串和 ISO 時間字串。Postgres 會把這種沒標型別的字串自動轉成欄位的型別（`jsonb`、`timestamptz`），所以 `storage.py` 的寫入不用改。
- **`execute`** 回傳 `cursor.rowcount`，`INSERT ... ON CONFLICT DO NOTHING` 撞到時是 0，`create_user` 判斷暱稱重複的邏輯照樣成立。
- **`executescript`** 直接把整段 SQL 交給一次 `execute`（psycopg2 接受多句）。
- **`column_names(table)`** 改查 `information_schema.columns`。
- **`transaction()`**：在鎖裡下 `BEGIN`，成功 `COMMIT`，出錯 `ROLLBACK` 再把錯誤往外丟。
- **斷線重連**：Render 休眠醒來或 Supabase 關掉閒置連線時，第一次查詢會丟 `OperationalError` / `InterfaceError`。此時重開連線、把**同一句**再試一次；第二次還失敗就丟出去。交易進行中斷線不重試（避免只做一半），直接丟錯。

### 3. 建表

`StorageRepository._init_tables()` 和 `AuthRepository._init_tables()` 依 `self.sql.dialect` 選建表語法。SQLite 版不變。Postgres 版：

- `users`、`records`、`custom_foods`、`restaurant_menus`、`restaurant_menu_failures`：`CREATE TABLE IF NOT EXISTS`，型別和 Supabase 現有的表一致（`jsonb`、`timestamptz`、`BIGSERIAL`），加上同樣的索引（`CREATE INDEX IF NOT EXISTS`）。表已經存在就什麼都不做，不改現有欄位。
- `auth_users`：`id TEXT PRIMARY KEY`、`email TEXT NOT NULL UNIQUE`、`password_hash TEXT NOT NULL`、`created_at TIMESTAMPTZ DEFAULT now()`。
- `auth_sessions`：`token_hash TEXT PRIMARY KEY`、`user_id TEXT NOT NULL REFERENCES auth_users (id) ON DELETE CASCADE`、`expires_at TIMESTAMPTZ NOT NULL`、`created_at TIMESTAMPTZ DEFAULT now()`，索引 `user_id`。
- 每張表建完都 `ALTER TABLE ... ENABLE ROW LEVEL SECURITY`。後端用資料表擁有者的身分連線，不受 RLS 限制；但 Supabase 的公開 API（anon key）就讀不到密碼雜湊和 token 雜湊。

### 4. 舊帳號搬進新的登入表

**在第一次部署之前**，在 `nutrilens` 專案執行一次。先建登入表（和後端 `POSTGRES_AUTH_TABLES` 一模一樣，後端啟動時 `IF NOT EXISTS` 就什麼都不做），再把帳號搬進去：

（先前的順序是部署之後才搬。Render 上預設開放註冊，部署到搬帳號之間，舊使用者登入失敗、用同一個 Email 重新註冊的話，搬帳號時 `ON CONFLICT DO NOTHING` 會默默略過他的舊帳號，他就再也看不到以前的紀錄。先搬再部署就沒有這段空檔。）

```sql
CREATE TABLE IF NOT EXISTS public.auth_users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS public.auth_sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES public.auth_users (id) ON DELETE CASCADE,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_user_id ON public.auth_sessions (user_id);
ALTER TABLE public.auth_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.auth_sessions ENABLE ROW LEVEL SECURITY;

INSERT INTO public.auth_users (id, email, password_hash, created_at)
SELECT id::text, lower(email), encrypted_password, created_at
FROM auth.users
WHERE email IS NOT NULL
  AND encrypted_password LIKE '$2%'
ON CONFLICT DO NOTHING;
```

- `id` 沿用 Supabase 的 UUID，就是舊資料裡的 `user_id`，所以健康檔案和紀錄直接接上。
- Supabase 存的是 bcrypt（`$2a$...`），Python 的 `bcrypt.checkpw` 認得，原密碼能登入。
- `sign_in()` 不檢查暱稱長度，Email 超過 30 個字也能登入。
- 這句會寫入正式資料庫，執行前要再問一次使用者。可以透過 Supabase MCP 執行，或由使用者貼到 Supabase 的 SQL Editor。
- 執行後用下面三句回報：搬了幾個、沒搬幾個（沒有 Email、沒有密碼或不是 bcrypt 的，例如用第三方登入的；`encrypted_password` 是 NULL 的也要算進去）、有沒有撞名（同一個 Email 在 `auth_users` 裡是別的 id）。

```sql
SELECT count(*) FROM public.auth_users a JOIN auth.users u ON u.id::text = a.id;
SELECT count(*) FROM auth.users
WHERE email IS NULL OR encrypted_password IS NULL OR encrypted_password NOT LIKE '$2%';
SELECT lower(u.email) AS email FROM auth.users u
JOIN public.auth_users a ON a.email = lower(u.email)
WHERE a.id <> u.id::text;
```

### 5. Render 設定

- 使用者在 Render 後台的 `pfrs` 服務設 `DATABASE_URL`：Supabase 專案 → Connect → **Session pooler** 的連線字串（埠 5432）。Render 只能走 IPv4，Supabase 的直連網址 `db.<ref>.supabase.co` 只有 IPv6，連不上。密碼由使用者自己填，Claude 不經手。
- 如果 `pfrs` 從 Supabase 時期就留著 `DATABASE_URL`，先確認它指向 `nutrilens` 專案、用的是 pooler 網址。
- `render.yaml` 的 `nutrilens-backend` 加上 `DATABASE_URL`（`sync: false`），並把「免費方案磁碟每次部署都會清空」那段註解改成說明現在資料在 Supabase。Render 不會套用這個檔，它只是說明。

### 6. `/health`

- `database` 多一個值 `"postgres"`。
- `database_path` 只在 SQLite 時、而且是本機請求才回傳（和現在一樣）；Postgres 時不回傳主機或連線字串。
- 部署後用 `https://pfrs.onrender.com/health` 看到 `"database": "postgres"` 就表示切換成功。

### 7. 錯誤處理

- 啟動時連不上：結束程式（見第 1 節）。
- 執行中連不上：重連一次再試（見第 2 節），還是失敗就讓那個 API 回 500，和 SQLite 出錯時一樣。
- 錯誤訊息和 log 都不印出連線字串。

## 測試

本機沒有 Postgres，測試分三層：

1. **單元測試（`tests/test_postgres_db.py`，新）**：用假的 psycopg2 連線測
   - `?` → `%s`、`%` → `%%` 的轉換，包含 `IN (?, ?, ?)`；
   - `datetime` 轉成 `utc_iso()` 字串、`jsonb` 讀回的 dict 原樣通過 `from_json()`；
   - `transaction()` 成功會 COMMIT、出錯會 ROLLBACK 並把錯誤往外丟；
   - 斷線時重連並重試一次、第二次失敗就丟錯、交易中不重試；
   - SSL 模式的判斷；
   - 錯誤訊息不含密碼。
2. **選資料庫的測試**：有 `DATABASE_URL` 時建的是 `PostgresDatabase`（用假的），沒有時是 `SqliteDatabase`；有設卻連不上時程式結束、不退回記憶體。
3. **現有測試**：`python -m unittest discover -s tests` 全部照跑，仍然只用 SQLite / 記憶體。

**真的 Postgres**：兩個選項，實作到這一步時再問使用者——

- (a) 部署後驗證：`/health`、註冊新暱稱、登入、新增一筆紀錄、重新部署後資料還在、用舊帳號登入看得到舊紀錄。
- (b) 經使用者同意，在 `nutrilens` 專案開一個暫時的 schema，對它跑一次 `StorageRepository` / `AuthRepository` 的整合測試，跑完刪掉。

## 上線順序

1. 程式改好、測試通過、commit（先不 push）。
2. 使用者在 Render 設好 `DATABASE_URL`（現在線上那版還不認得這個變數，設了也不影響）。
3. 經使用者同意後執行第 4 節的建表＋搬帳號 SQL，並回報那三個數字。
4. 經使用者同意後 push 到 `v0.0.9`（`git push origin refs/heads/v0.0.9:refs/heads/v0.0.9`），Render 自動部署。
5. `/health` 確認 `database: postgres`、`auth_provider: local-postgres`。
6. 用舊帳號和新帳號各登入一次確認。

順序要先設 `DATABASE_URL` 再 push：反過來的話，新版程式沒有 `DATABASE_URL` 會照舊用 Render 上暫時的 SQLite，不會壞，但要等設好後再部署一次才會切過去。

## 風險

- **Supabase 免費專案閒置 7 天會暫停**：暫停期間 Render 後端啟動失敗。要到 Supabase 後台恢復。
- **舊資料的格式**：舊的 `users.doc` 可能缺 `profile_complete` 等後來才加的欄位。`profile_service.py` 已經會在讀取時補正，但要用舊帳號實際登入看過。
- **單一連線**：和 SQLite 版一樣所有請求排隊。這個專案的流量很小，夠用；真的不夠再換連線池。
