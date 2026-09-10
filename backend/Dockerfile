# 讓後端不綁定單一平台。Koyeb、Fly.io、Railway、Hugging Face Spaces
# 都接受 Dockerfile，換家時不必再改設定。
FROM python:3.12-slim

# psycopg2-binary 是預編譯的輪子，不需要編譯工具鏈；
# 這裡只留執行期需要的東西，映像檔才不會沒必要地變大。
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 各家平台注入的埠號不同，app.py 讀 PORT；沒有就用 8000。
ENV PORT=8000
EXPOSE 8000

# app.py 在非 debug 模式下用 waitress 啟動，不是 Flask 的開發伺服器。
CMD ["python", "-u", "app.py"]
