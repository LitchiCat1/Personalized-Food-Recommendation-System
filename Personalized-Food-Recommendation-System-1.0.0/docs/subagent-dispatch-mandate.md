# 子 Agent 調度實作規定（供 Codex / GPT-5.5 嚴格遵守）

> 生成日期：2026-06-19
> 審查者：Claude Opus 4.8
> 專案定位：**大學畢業專題（capstone / demo）**，非上市產品
> 適用對象：Codex 多子 Agent 協作的**下一輪實作**
> 上游文件：
> - `docs/Multi_Agent_Collaboration_Plan.md`（角色定義）
> - `docs/subagent-scheduling-review-response.md`（畢業專題口徑與階段順序）
> - `docs/subagent-scheduling-implementation-report.md`（上一輪實作，名實不符）

---

## 0. 本文件為什麼存在

上一輪 `subagent-scheduling-implementation-report.md` 出現三個嚴重問題：

1. **名實不符**：標題是「子 Agent 調度」，內容卻完全沒有任何子 Agent 調度紀錄，整份是 backend changelog。
2. **未照階段閘門**：規劃要求「安全 → 測試 → 資料層 → 功能/UI」，實際是後端 hardening 與前端 1,451+/2,047- 行 redesign 平行進行，沒有走閘門。
3. **回報失真**：報告說「未擴及前端」但改了 16 個前端檔；說 `restaurant_ai_service` 驗證「已延後」但其實已實作。

本文件的目的：把「該怎麼做、該怎麼回報、不准做什麼」變成**硬性規定**，下一輪不准再犯同樣問題。

---

## 1. 不可違反的硬性規定（Hard Rules）

> 以下任一條違反，視為本輪實作不合格，必須退回重做。

- **R1 階段閘門不可跳**：必須嚴格依第 3 節的階段順序執行。前一階段的閘門未通過，不得開始下一階段。
- **R2 守門層強制執行**：每一階段結束，TestAgent 與 SafetyAgent 必須實際執行並留下可貼上的指令與結果，不可口頭略過。
- **R3 前端動到就要 build**：任何 `frontend/` 改動，TestAgent 必須跑 `npm run typecheck` **與** `npm run build:web`，兩者皆須貼結果。
- **R4 回報必須與 git 一致**：報告中「做了什麼 / 沒做什麼」必須與 `git status` / `git diff --stat` 完全吻合。不准低報，也不准虛報。
- **R5 不可擅自擴大範圍**：每個 worker 只能改它崗位內的檔案（見 `Multi_Agent_Collaboration_Plan.md` 第 3 節）。跨崗位需 Orchestrator 重新派發並記錄。
- **R6 秘密零外洩**：不准把任何 secret 值寫入 docs / commit / log / 報告。env 只列名稱。違反即 SafetyAgent block。
- **R7 不准 over-engineering**：第 5 節「禁止項目」一律不做，列入論文未來工作即可。
- **R8 失敗回路上限 2 次**：同一問題修兩次仍失敗，停手、寫下根因、回報 Orchestrator，不准無限增量修補。

---

## 2. 調度紀錄義務（每個 Agent 都要交代）

下一輪的實作報告**必須**包含一張調度表，缺一欄即不合格：

| 欄位 | 要求 |
|------|------|
| 角色 | 例：BackendAgent |
| 類型 | explorer 或 worker |
| 升級時機 | 何時從 explorer 升 worker |
| 實際改檔 | 對照 `git diff --stat` 的真實檔案清單 |
| 主要產出 | 一句話描述實際做的事 |
| 閘門結果 | 該角色完成後 TestAgent / SafetyAgent 跑了什麼、結果為何 |
| thread 狀況 | 是否遇到 thread limit、如何分批 |

---

## 3. 本輪實作順序（嚴格依序，不可平行跨階段）

### 階段一：補上一輪缺的調度與守門紀錄（最先做）

> 上一輪沒做守門，這一輪先把地基補回來。

1. **SafetyAgent(worker)**
   - 執行：`git status --short`、`git diff --cached --name-only`
   - 確認 `.env.local`、`frontend/.env.local` 未被追蹤；`.gitignore` 涵蓋所有 `.env*`
   - 確認 `.agents/`、`.opencode/`、`frontend/dist`、`node_modules` 不會被誤 stage
   - 產出：staging 審查結論（pass/block）+ 應排除清單
2. **TestAgent(worker)**
   - 後端：`cd backend && python -m unittest discover -s tests -p "test_*.py"`
   - 前端：`cd frontend && npm run typecheck`
   - 前端（因上一輪大改前端，本輪必跑）：`cd frontend && npm run build:web`
   - 產出：三條指令的實際結果，任何失敗須列出並退回對應 Agent

**階段一閘門**：上述全部 pass 才可進階段二。

### 階段二：修正上一輪報告的失真（文件對齊）

> 不改功能，只把報告講對。

3. **BackendAgent(worker)**
   - 把 `restaurant_ai_service.py` 的 `validate_restaurant_summary_input` 狀態由「延後」更正為「已完成」
   - 為該函數補至少一條 smoke test（None 輸入、缺 name、budget 非數字）
4. **Orchestrator**
   - 把「前端 16 檔改動」如實補入報告：說明這批改動的意圖（UI redesign？對齊後端 contract？），對照 `git diff --stat frontend/`
   - 把 Q4（render.yaml key 對齊）標為**已完成**：`with-google-map-env.js` 已把 `GOOGLE_PLACES_API_KEY` 注入為 `EXPO_PUBLIC_GOOGLE_MAPS_API_KEY`，注入鏈完整

**階段二閘門**：報告內容與 `git status` / `git diff --stat` 100% 吻合（R4）。

### 階段三：展示功能與 UI（答辯主體，最後做）

> 只有階段一、二閘門都過，才可進這裡。

5. **FrontendAgent / GeminiVisionAgent / RecommendAgent / MapAgent**
   - 依答辯腳本補功能與 UI，每個 worker 只動自己崗位的檔案（R5）
   - 每完成一個 worker，立即回到守門層（R2/R3）
6. **RenderOpsAgent**
   - 答辯前確認線上站可開、`/health` 正常、地圖 key 注入鏈一致
   - 只報 status code / service id / 布林摘要，不報值（R6）

**階段三閘門**：每個 worker 後都跑 Test + Safety；前端改動必跑 `build:web`。

---

## 4. 每階段結束的收尾格式（固定模板）

每個階段做完，必須貼出這段，否則視為閘門未走：

```txt
[階段 X 收尾]
- 動到的檔案（git diff --stat）：<貼上>
- TestAgent：<指令 + 結果>
- 前端 build:web（若動到前端）：<結果>
- SafetyAgent：<staging 審查結論>
- 失敗/退回項目：<無 / 列出>
- 是否可進下一階段：<是 / 否>
```

---

## 5. 禁止項目（一律不做，寫入論文未來工作）

依畢業專題口徑，以下不做，做了視為違反 R7：

- Supabase RLS / DB 層 ownership 下沉（application 層已足夠）
- Production 級 secret manager 與定期輪替流程
- 完整 contract test 矩陣與前端 e2e 測試套件
- Map payload 的完整 pydantic / schema framework（基本防呆已足夠）
- 疾病規則的正式臨床審核流程（維持 `needs_clinical_review`）

---

## 6. 本輪驗收標準（Definition of Done）

全部滿足才算本輪完成：

1. 階段一、二、三依序完成，無跨階段平行（R1）。
2. 每階段都有第 4 節的收尾格式紀錄（R2）。
3. 所有前端改動都跑過 `typecheck` 與 `build:web`（R3）。
4. 新報告含第 2 節完整調度表，且與 git 證據吻合（R4）。
5. `restaurant_ai_service` 驗證狀態已更正並補測試。
6. 報告如實記載前端改動意圖與 Q4 已完成結論。
7. 無任何 secret 進入 docs / commit / log（R6）。
8. 第 5 節禁止項目皆未觸碰（R7）。
