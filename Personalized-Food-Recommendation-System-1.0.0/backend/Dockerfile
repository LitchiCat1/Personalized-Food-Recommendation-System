# Optional API-only development image; production uses the Windows scheduled task.
# Mount persistent SQLite storage and supply credentials outside the image.
FROM python:3.12-slim

# 相依套件都有預編譯的輪子，不需要編譯工具鏈；
# 這裡只留執行期需要的東西，映像檔才不會沒必要地變大。
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Container port publishing requires binding inside the container to all interfaces.
ENV PORT=8000
ENV SHARE_ON_LAN=true
EXPOSE 8000

# app.py 在非 debug 模式下用 waitress 啟動，不是 Flask 的開發伺服器。
CMD ["python", "-u", "app.py"]
