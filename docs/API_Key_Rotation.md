# API Key Rotation

本專案目前將 Gemini 測試用 API key 放在專案根目錄的 `.env.local`。

## 放置位置

- 檔案路徑：`.env.local`
- 目前後端啟動時會自動讀取：
  - `./.env.local`
  - `backend/.env.local`

建議統一使用專案根目錄的 `.env.local`。

## 格式

```env
GEMINI_API_KEY=你的新APIKEY
```

如果之後要切換模型，也可以加入：

```env
GEMINI_MODEL=gemini-1.5-flash
```

## 輪替步驟

1. 開啟專案根目錄的 `.env.local`
2. 將 `GEMINI_API_KEY=` 後面的值替換成新的 key
3. 儲存檔案
4. 重新啟動後端 `backend/app.py`

## 注意事項

- `.env.local` 已被 `.gitignore` 忽略，不應提交到 git。
- 不要把 API key 寫死在 `backend/app.py` 或前端程式碼中。
- 若 key 已失效，營養標示 OCR API `/ocr/nutrition-label` 會回傳錯誤。
- 若要在其他機器部署，請在該機器同樣建立 `.env.local`。

## 目前使用到 API key 的功能

- `POST /ocr/nutrition-label`
- 前端掃描頁中的「辨識營養標示照片」流程
