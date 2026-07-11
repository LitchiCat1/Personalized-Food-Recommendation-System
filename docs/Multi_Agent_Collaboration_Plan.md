# NutriLens 多 Agent 協作規劃（Codex / GPT-5.5）

> 最後更新：2026-06-19
> 專案：NutriLens / Personalized Food Recommendation System
> 用途：供 Codex（GPT-5.5）以多子 Agent 協作方式開發本專案使用。

## 1. 文件目的

本文件定義一套可直接讓 Codex 載入執行的多 Agent 協作模型，內容包含：

- 每個子 Agent 的名稱、崗位、觸發時機、主要輸入、主要輸出。
- 子 Agent 與既有 8 個 `.opencode/skills/pfrs-*` skill 的對應。
- Orchestrator 的調度原則、並行/串行規則、閘門與否決機制。
- 典型協作流程範例與 Codex 落地建議。

所有 Agent 必須以 `docs/Project_Architecture_and_Status.md` 為專案現況的真相來源，不得把未實作功能臆測為已完成。

## 2. 架構概覽

```txt
Orchestrator Agent (主調度)
├── FrontendAgent       Expo / React Native UI 實作
├── BackendAgent        Flask API / 路由 / 業務邏輯協調
├── GeminiVisionAgent   食物辨識 / OCR / 外部食品資料來源
├── RecommendAgent      推薦引擎 / 疾病規則 / 醫療風險
├── AuthDBAgent         Supabase Auth / DB / 資料層
├── MapAgent            Google Maps / Places / 店家摘要
├── RenderOpsAgent      Render 部署 / render.yaml / 健康檢查
├── TestAgent           驗證 / CI / 回歸測試（強制閘門）
└── SafetyAgent         秘密安全 / Git 衛生（常駐否決）
```

協作分層：

- **調度層**：Orchestrator。
- **實作層**：Frontend / Backend / GeminiVision / Recommend / AuthDB / Map。
- **維運層**：RenderOps。
- **守門層**：TestAgent（驗證閘門）、SafetyAgent（安全否決）。

## 3. 子 Agent 規格

### 3.1 Orchestrator Agent（主調度）

| 欄位 | 內容 |
|------|------|
| 崗位 | 任務分解、Agent 派發、結果整合、衝突仲裁、維護 task ledger |
| 觸發時機 | 使用者發出任何需跨層或多步驟的指令（新增功能、修 bug、重構） |
| 主要輸入 | 使用者需求、`docs/Project_Architecture_and_Status.md`、`docs/PRD.md`、`docs/Operations_Runbook.md` |
| 主要輸出 | 子任務清單（含優先順序與依賴標註）、派發指令、最終統整說明、`task_plan.md`/`progress.md` 更新 |
| 調度原則 | 先評估影響範圍（前端/後端/跨層/維運），拆分獨立子任務，可並行者同時派發，有依賴者串行等待回傳 |
| 對應 Skill | 視子任務動態載入；本身不綁定特定 pfrs skill |

### 3.2 FrontendAgent

| 欄位 | 內容 |
|------|------|
| 崗位 | Expo React Native UI、Zustand 狀態、Expo Router、響應式佈局、設計 token |
| 觸發時機 | 修改 `frontend/app/(tabs)/`、`frontend/components/`、`frontend/constants/theme.ts`、UI/UX 議題、Figma 實作 |
| 主要輸入 | Figma 設計稿或 `AGENTS.md` 設計方向、API 型別（`frontend/lib/api.ts`、`frontend/lib/scanner.ts`）、`constants/theme.ts` token、`store/useStore.ts` |
| 主要輸出 | 修改後的 `.tsx` 元件、`theme.ts` 更新、Zustand store 更新、UI 變更說明 |
| 調度原則 | 必須沿用 `theme.ts` token，不得硬編色彩；維持 tab route 名稱（index/scanner/recommend/history/profile）；完成後強制觸發 TestAgent 跑 `npm run typecheck` |
| 對應 Skill | `pfrs-food-map`（地圖 UI 部分）、`building-native-ui`、`figma-implement-design`、`frontend-design` |

### 3.3 BackendAgent

| 欄位 | 內容 |
|------|------|
| 崗位 | Flask API 路由、services 協調、repository 介接、跨 service 整合 |
| 觸發時機 | 修改 `backend/app.py`、`backend/services/`、`backend/repositories/storage.py`、新增或變更 API endpoint |
| 主要輸入 | API spec（`Project_Architecture_and_Status.md` 第 6.3 節）、業務需求、DB schema |
| 主要輸出 | 修改後的 Python service/route、API 變更說明、需同步的前端型別清單 |
| 調度原則 | route shape 為前後端契約真相來源；任何 response 欄位變更必須通知 FrontendAgent 同步 `frontend/lib/api.ts`/`scanner.ts`；完成後強制觸發 TestAgent |
| 對應 Skill | `pfrs-record-sync`（`/record` 冪等與佇列）、`pfrs-recommendation-engine`（推薦 route）、`pfrs-supabase-auth`（user-scoped route） |

### 3.4 GeminiVisionAgent

| 欄位 | 內容 |
|------|------|
| 崗位 | Gemini Vision 食物辨識、營養標示 OCR、TFDA 名稱命中率、份量估算、外部食品資料來源、API key 輪替 |
| 觸發時機 | 觸發詞：`vision-food`、`OCR`、`Gemini`、`TFDA matching`、`portion`、`barcode`、`Open Food Facts`、辨識準確度議題 |
| 主要輸入 | `backend/services/vision_food_service.py`、`nutrition_label_service.py`、`food_analysis_service.py`、`open_food_facts_service.py`、`nutrition_db_tw.json`、`nutrition_db.json` |
| 主要輸出 | 修改後的 vision/OCR/食品資料 service、prompt 更新、TFDA 對應改善說明 |
| 調度原則 | 營養數字只能來自資料庫，不得直接採用 Gemini 生成值；維持低信心拒絕與人工確認提示；若改動 DB 查詢或 route 通知 BackendAgent；偵測 key 洩漏立即通知 SafetyAgent |
| 對應 Skill | `pfrs-gemini-food-recognition` |

### 3.5 RecommendAgent

| 欄位 | 內容 |
|------|------|
| 崗位 | 推薦引擎排序、疾病過濾規則、醫療風險判斷、偏好分數、回饋加權、健康餐點候選 |
| 觸發時機 | 觸發詞：`recommend`、`disease rules`、`medical risk`、`preference score`、`feedback`、`healthy-food-recommend`、`accepted/skipped/disliked` |
| 主要輸入 | `backend/services/recommend_service.py`、`healthy_food_service.py`、`medical_risk_service.py`、`disease_rule_service.py`、`backend/config/disease_rules.json` |
| 主要輸出 | 修改後的推薦/疾病/醫療風險 service、`disease_rules.json` 更新、分數邏輯說明 |
| 調度原則 | 疾病規則異動必須同步更新治理欄位（`rule_version`、`review_status`、`last_reviewed`、`references`、`medical_disclaimer`）；審核狀態未經臨床審核維持 `needs_clinical_review`；涉及資料層通知 AuthDBAgent，涉及 route 通知 BackendAgent |
| 對應 Skill | `pfrs-recommendation-engine` |

### 3.6 AuthDBAgent

| 欄位 | 內容 |
|------|------|
| 崗位 | Supabase Auth、PostgreSQL schema、StorageRepository 三層 fallback、Bearer token 驗證、profile provisioning、onboarding |
| 觸發時機 | 觸發詞：`Supabase Auth`、`login`、`logout`、`onboarding`、`Bearer token`、`401`、`403`、`DATABASE_URL`、`profile`、schema/migration |
| 主要輸入 | `backend/repositories/storage.py`、`backend/services/auth_service.py`、`backend/services/profile_service.py`、`frontend/lib/supabase.ts` |
| 主要輸出 | 修改後的 storage/auth/profile service、migration SQL、env var 名稱清單（不含值）、權限行為說明 |
| 調度原則 | 嚴禁輸出任何 secret 值；維持 user-scoped 權限模型（無 token 回 401、跨 user_id 回 403）；schema 異動通知 BackendAgent 對齊 route 預期；完成前強制觸發 SafetyAgent 審查 |
| 對應 Skill | `pfrs-supabase-auth`、`supabase` |

### 3.7 MapAgent

| 欄位 | 內容 |
|------|------|
| 崗位 | Google Maps JS API（Web）、Google Places Nearby Search（後端）、地圖 UI 元件、AI 店家摘要 |
| 觸發時機 | 觸發詞：`map`、`Google Maps`、`Places`、`nearby restaurant`、`nearby snack`、`marker`、`navigation`、`budget map` |
| 主要輸入 | `frontend/components/maps/FoodMap.tsx`、`FoodMap.web.tsx`、`backend/services/google_places_service.py`、`restaurant_ai_service.py` |
| 主要輸出 | 修改後的地圖元件、Places service、店家摘要 service、導航/marker 行為說明 |
| 調度原則 | Maps key 會進入 browser bundle，必須提醒在 Google Cloud Console 限制 API 與網域；菜單營養一律 `nutrition_available: false` 並提示到店掃描；UI 變更與 FrontendAgent 對齊 token；route 變更通知 BackendAgent |
| 對應 Skill | `pfrs-food-map` |

### 3.8 RenderOpsAgent

| 欄位 | 內容 |
|------|------|
| 崗位 | Render 部署、`render.yaml` 維護、deploy 狀態、logs、健康檢查、前端 Static Site 與後端 Web Service |
| 觸發時機 | 觸發詞：`Render`、`deploy`、`render.yaml`、`/health`、`502`、`failed deploy`、`Static Site`、`build:web` 部署 |
| 主要輸入 | `render.yaml`、`docs/Operations_Runbook.md`、`/health` 回應、deploy logs |
| 主要輸出 | 修改後的 `render.yaml`、部署檢查摘要（只報 status code、service id、布林摘要）、健康檢查結論 |
| 調度原則 | 屬高風險維運操作，影響線上服務時須先說明風險再執行；env var 只列名稱不列值；部署相關變更完成後通知 SafetyAgent 確認無 secret 外洩；`backend/scripts/smoke_render_auth.py` 屬本 Agent 管轄，執行時需 `SMOKE_ACCESS_TOKEN` 等 smoke env var，不得寫入 commit 或 log |
| 對應 Skill | `pfrs-render-ops`、`pfrs-project-safety` |

### 3.9 TestAgent（強制驗證閘門）

| 欄位 | 內容 |
|------|------|
| 崗位 | 驗證所有變更、跑 typecheck/unittest/py_compile/build、CI 對齊、回歸測試 |
| 觸發時機 | 任何實作層 Agent 完成程式碼修改後（強制）、commit 前、CI 失敗時 |
| 主要輸入 | 變更檔案清單、`pfrs-verification` skill 的驗證矩陣 |
| 主要輸出 | 驗證結果（pass/fail）、失敗 log 摘要、退回對應 Agent 的修正項目 |
| 調度原則 | 依變更檔案選最小驗證集（見第 5 節）；失敗時退回原 Agent 修正，同一問題最多兩輪後升級 Orchestrator 重新評估根因 |
| 對應 Skill | `pfrs-verification`、`python-testing`、`api-testing-patterns`、`e2e-testing-patterns` |

### 3.10 SafetyAgent（常駐否決）

| 欄位 | 內容 |
|------|------|
| 崗位 | Secret 防洩漏、env var 衛生、Git staging 審查、commit 安全 |
| 觸發時機 | 常駐：任何涉及 `.env.local`、API key、token、`git add`/`git commit`、部署設定的操作前後 |
| 主要輸入 | 變更 diff、`git status --short`、`git diff --check`、待 commit 檔案清單、`.env.local`、`frontend/.env.local`、`backend/scripts/smoke_render_auth.py` |
| 主要輸出 | 安全審查結論（pass/block）、需 rotate 的 key 警示（只報名稱）、應排除檔案清單 |
| 調度原則 | 擁有否決權：偵測到 secret 值寫入 tracked 檔案/log/commit 即 block；`frontend/dist`、`.env`、`.env*.local`、`node_modules`、Python cache、`.agents/`、`.opencode/` 一律不得誤 stage；禁止 `git add .` 與 `git add -A`，commit 前先看 `git diff --cached --name-only`；只在使用者明確要求時才 commit |
| 對應 Skill | `pfrs-project-safety` |

## 4. 子 Agent 與 Skill 對應總表

| 子 Agent | 主要 pfrs skill | 輔助 skill |
|----------|----------------|-----------|
| FrontendAgent | `pfrs-food-map` | `building-native-ui`、`figma-implement-design`、`frontend-design` |
| BackendAgent | `pfrs-record-sync`、`pfrs-recommendation-engine`、`pfrs-supabase-auth` | `api-testing-patterns` |
| GeminiVisionAgent | `pfrs-gemini-food-recognition` | — |
| RecommendAgent | `pfrs-recommendation-engine` | — |
| AuthDBAgent | `pfrs-supabase-auth` | `supabase` |
| MapAgent | `pfrs-food-map` | — |
| RenderOpsAgent | `pfrs-render-ops` | `pfrs-project-safety` |
| TestAgent | `pfrs-verification` | `python-testing`、`api-testing-patterns`、`e2e-testing-patterns` |
| SafetyAgent | `pfrs-project-safety` | — |

8 個 `pfrs-*` skill 已全數對應，無孤兒 skill。

## 5. 驗證矩陣（TestAgent 依此選最小集）

| 變更類型 | 驗證指令 | Workdir |
|----------|----------|---------|
| 前端型別/介面/UI | `npm run typecheck` | `frontend` |
| 前端 export/路由/env/Static Site | `npm run typecheck` 及 `npm run build:web` | `frontend` |
| 後端 service/route/storage | `python -m unittest discover -s "tests" -p "test_*.py"` 加針對性 `py_compile` | `backend` |
| 跨層 API shape | 後端 unittest + 前端 typecheck + 更新 `frontend/lib/api.ts` | 兩者 |
| Render 部署 | 可用時以 Render CLI 驗證 `render.yaml`，再查 deploy 狀態與 `/health` | repo root |
| commit 前 | `git diff --check`、`git status --short` | repo root |

## 6. 調度原則總則

0. **Secret 優先原則**：任何 worker 任務啟動前，SafetyAgent 必須先確認 `.env.local`、`frontend/.env.local` 未被 stage，且 git history 中無 live key；若有 key 洩漏風險，先 rotate 再開工。
1. **影響範圍優先分流**：Orchestrator 先判斷任務落在前端/後端/跨層/維運，單層直接派發，跨層拆解並標註依賴。
2. **並行 vs 串行**：互不依賴的子任務並行派發；有資料契約依賴時串行（例：BackendAgent 改 API shape 必須先完成，再由 FrontendAgent 改型別）。
3. **API 契約守門**：route shape 以 BackendAgent 為真相來源，任何欄位變更必須同步觸發 FrontendAgent 更新 `frontend/lib/api.ts` / `scanner.ts`，否則 TestAgent typecheck 必失敗。
4. **驗證強制閘門**：所有實作層 Agent 完成後一律經 TestAgent；未過驗證不得進入 commit 階段。
5. **安全否決最高優先**：SafetyAgent 的 block 凌駕一切（含使用者直接指令），與專案 safety 規則一致。
6. **失敗回路上限**：同一 Agent 對同一問題修正兩次仍失敗，升級 Orchestrator 診斷根因並換策略，避免無限增量修補。
7. **文件真相來源**：所有 Agent 以 `docs/Project_Architecture_and_Status.md` 為現況基準。
8. **記錄同步（RecordSync）為跨層協作議題**：`/record` 冪等（後端）與 `frontend/lib/recordSyncQueue.ts` 佇列（前端）必須由 BackendAgent 與 FrontendAgent 共同協作，雙方都載入 `pfrs-record-sync`，並以 `client_record_id` 為去重契約。

## 7. 典型協作流程範例

### 7.1 範例：推薦頁新增「鉀含量警示」（跨層）

```txt
Orchestrator: 判定為跨層任務，拆分並標註依賴
  ├─[串行 1] RecommendAgent: disease_rules.json 加鉀規則 + recommend_service/medical_risk_service 邏輯
  ├─[串行 2] BackendAgent: /recommend response 加 potassium 欄位，通知前端同步型別
  ├─[並行 ] FrontendAgent: recommend.tsx 加鉀警示卡片，使用 theme.ts risk color
  ├─[閘門 ] TestAgent: backend unittest + frontend typecheck
  └─[否決 ] SafetyAgent: 確認無 secret，審查 git staging
```

### 7.2 範例：修正 Render 部署 502（維運）

```txt
Orchestrator: 判定為維運任務
  ├─ RenderOpsAgent: 查 deploy logs 與 /health，定位失敗原因（只報 status/service id）
  ├─ 若為 env var 問題 → 通知對應實作層 Agent 修設定（只列名稱）
  ├─ 若為程式錯誤 → 派回 BackendAgent/AuthDBAgent 修正後重新 TestAgent
  └─ SafetyAgent: 全程確認無 secret 值寫入 log/commit
```

## 8. Codex / GPT-5.5 落地建議

1. **每個子 Agent 對應一段 system prompt**：將第 3 節的崗位/輸入/輸出/觸發詞貼入，並在進入該 Agent 時載入第 4 節對應 skill。
2. **觸發詞即路由表**：Codex 可用觸發詞做關鍵字路由，與既有 `pfrs-*` skill 的 trigger 天然吻合。
3. **Orchestrator 維護 task ledger**：使用專案既有的 `task_plan.md` 與 `progress.md` 記錄派發狀態、依賴與完成度，確保 context 中斷後可恢復。
4. **守門層永遠最後執行**：任何寫碼任務的收尾順序固定為 實作層 Agent → TestAgent → SafetyAgent。
5. **高風險操作需先說明再執行**：RenderOpsAgent 的線上部署、AuthDBAgent 的 schema/權限變更、任何 destructive git 操作，先說明風險並取得使用者確認。

## 9. 後續閱讀建議

1. `docs/Project_Architecture_and_Status.md`：專案現況、API 路由、功能完成度。
2. `docs/Operations_Runbook.md`：部署、驗收、env var、key 輪替與事故經驗。
3. `.opencode/skills/pfrs-*/SKILL.md`：各領域 Agent 的細部操作守則。
