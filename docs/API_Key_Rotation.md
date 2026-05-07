# API Key Rotation

本專案使用 Gemini API 進行營養標示 OCR。Render 部署環境建議使用 `GEMINI_API_KEYS` 放多組 key 做輪替；本機開發可使用單一 `GEMINI_API_KEY` 或同樣使用 `GEMINI_API_KEYS`。

## 放置位置

- 檔案路徑：`.env.local`
- 目前後端啟動時會自動讀取：
  - `./.env.local`
  - `backend/.env.local`

建議統一使用專案根目錄的 `.env.local`。

## 格式

單一 key：

```env
GEMINI_API_KEY=你的新APIKEY
```

多 key 輪替：

```env
GEMINI_API_KEYS=key1,key2,key3
```

如果兩者同時存在，後端會優先使用 `GEMINI_API_KEYS`，並保留 `GEMINI_API_KEY` / `GOOGLE_API_KEY` 作為 fallback。輪替會在 Gemini 回傳 `401`、`403`、`429`、`500`、`502`、`503`、`504` 時嘗試下一組 key。

如果之後要切換模型，也可以加入：

```env
GEMINI_MODEL=gemini-1.5-flash
```

## 輪替步驟

1. 到 Google AI Studio 產生新的 Gemini API key。
2. 本機開發：更新專案根目錄 `.env.local` 的 `GEMINI_API_KEY` 或 `GEMINI_API_KEYS`。
3. Render 部署：更新 Web Service 的 `GEMINI_API_KEYS` environment variable。
4. 儲存環境變數並重新部署後端。

## 注意事項

- `.env.local` 已被 `.gitignore` 忽略，不應提交到 git。
- 不要把 API key 寫死在 `backend/app.py` 或前端程式碼中。
- 不要把 API key 貼到聊天、文件、issue、PR 或 commit 中；貼出後應視為外洩並立即刪除/重建。
- 若 key 已失效，營養標示 OCR API `/ocr/nutrition-label` 會回傳錯誤。
- 若要在其他機器部署，請在該機器同樣建立 `.env.local`。

## 目前使用到 API key 的功能

- `POST /ocr/nutrition-label`
- 前端掃描頁中的「辨識營養標示照片」流程
