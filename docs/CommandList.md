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
