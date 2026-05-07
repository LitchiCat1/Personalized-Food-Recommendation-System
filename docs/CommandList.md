最優先前置:
(安裝依賴套件)
cd frontend && npm install

Git指令:
(將GitHub的最新程式碼下載並合併到目前的workspace)
git pull

(列出目前本機端所有的分支)
git branch

(在已存在的分支之間跳躍)
git switch <分支名稱>

(建立一個全新的獨立開發分支並立刻切換過去)
git switch -c <分支名稱>

(建立並切換至新的branch 前置：在main branch處於最新狀態時用) 
git checkout -b <分支名稱>

(將當前目錄所有變更加入暫存區並建立提交 前置：確認程式碼可以正常運行並準備紀錄新版本時使用) 
git add . && git commit -m "這個版本做了什麼事"

測試專案畫面用的指令:
(切換到前端目錄並啟動伺服器 前置：要通過cd在前端目錄下執行)
cd frontend && npx expo start --tunnel

(關閉Expo伺服器 前置動作：要在正在執行Expo的終端機視窗內操作，也就是下方) 
npx kill-port 8081

(清除快取並重新啟動Expo) 
npx expo start -c

避免 empty_stream / 上游串流中斷的檢查方式:
(原則：優先跑短指令、分段檢查，避免一次啟動耗時模型或長時間無輸出)

(後端輕量 smoke test，不啟動 Flask、不載入 YOLO 模型)
python -m unittest discover backend/tests

(後端語法檢查)
python -m py_compile "backend/app.py" "backend/repositories/storage.py" "backend/services/disease_rule_service.py" "backend/services/history_service.py" "backend/services/predict_service.py" "backend/services/recommend_service.py" "backend/services/healthy_food_service.py"

(YOLO/TFDA 映射與手動搜尋建議檢查)
python backend/scripts/verify_mapping.py

(前端型別檢查)
cd frontend && npm run typecheck

(前端 lint；若 expo lint 在環境中卡住，可改用底層 ESLint)
cd frontend && npx eslint .

Render / Supabase 部署後驗收:
(原則：不要在終端輸出 access token、API key、database password；只輸出狀態碼與必要 user id)

(檢查 Render deploy 狀態)
render deploys list srv-d7u2qhdckfvc73ei96l0 --output json

(檢查 Render health)
curl https://personalized-food-recommendation-system-nq8t.onrender.com/health

(權限驗收標準)
GET /user/<user_id> 不帶 Authorization 應回 401
GET /user/<user_id> 帶正確 Supabase Bearer token 應回 200
GET /user/demo_user 帶其他使用者 token 應回 403

(前端型別檢查與 Web 驗收)
cd frontend && npm run typecheck
cd frontend && npm run web -- --port 8083

安全提醒:
聊天、commit、README、docs 中都不要放 Render API key、Supabase database password、Gemini API key、Supabase service_role key。
如果 key 曾經貼到聊天或日誌中，直接視為 compromised，應立即輪替或撤銷。
