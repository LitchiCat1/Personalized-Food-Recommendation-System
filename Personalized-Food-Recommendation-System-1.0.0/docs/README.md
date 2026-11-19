# 文件索引

更新：2026-11-17（第82批照片結果）；目前版本 `v1.0.3`。

| 用途 | 現行文件 |
| --- | --- |
| 架構、登入、儲存與功能限制 | [專案架構與狀態](Project_Architecture_and_Status.md) |
| 第一次架設、排程、Funnel、來源安裝與回復 | [Windows 部署](Local_Server_Deployment.md) |
| 日常設定、測試、備份與故障處理 | [維運手冊](Operations_Runbook.md) |
| 營養補全規格、六個工作流、目前唯一下一步 | [企劃書](plans/2026-11-13-web-nutrition-fallback.md)及 [自行審查](plans/2026-11-13-web-nutrition-fallback-review.md) |
| 第80批進度核對、摘要修正與運行觀測範圍 | [進度一致性證據](food-nutrition-evaluation/2026-11-14/plan-progress-reconciliation-20261117.json) |
| 第81批真便當照片、本機查找與未完成門檻 | [真照片查找證據](food-nutrition-evaluation/2026-11-14/scanner-real-photo-local-priority-20261117.json) |
| 第82批蘋果照片、local miss與171688待確認來源選用 | [蘋果身分／來源選用證據](food-nutrition-evaluation/2026-11-14/scanner-apple-identity-20261117.json) |
| 實測範圍、結果及限制 | [照片測試](food-image-evaluation/README.md)與 [營養證據](food-nutrition-evaluation/2026-11-14/README.md) |
| 產品研究動機 | [PRD](PRD.md)，研究願景不等於已實作功能 |

部署採 Windows／Tailscale Funnel／SQLite，不使用 Render、Supabase、PostgreSQL 或 MongoDB。`DATABASE_URL` 的拒絕檢查與舊欄位／資料合約相容保護仍有用途，不能當廢碼刪除。

## 歷史資料

以下內容保留其當時版本，不作現行操作指示或新增待辦：

- [舊雲端維運](Operations_Runbook.historical.md)、[舊架構](Project_Architecture_and_Status.historical.md)。
- `superpowers/` 的2026-10-15雲端設計／實作計畫，以及舊多Agent規劃、調度規定、執行報告與2026-07-11交接簡報；文件開頭已標示失效範圍。
- [歷史架構圖](architecture/README.md)、壓力測試報告及原始機器證據；不改寫原始數字或來源以冒充新版驗收。
- 既有Word提案、版本彙整與Excel實測表是當時產物，不因本輪程式整理重製。兩個提案產生器的架構文案已改為目前方案，既有二進位成品不視為最新操作手冊。

第79批整理結果及保留理由見 [清理證據](food-nutrition-evaluation/2026-11-14/deployment-legacy-cleanup-20261117.json)。
