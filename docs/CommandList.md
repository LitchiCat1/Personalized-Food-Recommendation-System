最優先前置:
(安裝依賴套件)
cd frontend ; npm install 或是 cd frontend && npm install

Git指令:
(將GitHub的最新程式碼下載並合併到目前的workspace)
git pull

(列出目前目前本機上所有的分支)
git branch

(在已存在的分支之間切換)
git switch <分支名稱>

(建立一個全新的獨立分支並切換過去)
git switch -c <分支名稱>

(建立並切換至新的分支) 
git checkout -b <分支名稱>

(將當前目錄所有變更加入暫存區並建立提交) 
git add . && git commit -m "這個版本做了什麼事"

測試專案畫面用的指令:
(切換到前端目錄並啟動伺服器 前置：要通過cd在前端目錄下執行)
cd frontend && npx expo start --tunnel

(關閉Expo伺服器 前置：要在下方正在執行Expo的終端機視窗內操作) 
npx kill-port 8081

(清除快取並重啟Expo) 
npx expo start -c
