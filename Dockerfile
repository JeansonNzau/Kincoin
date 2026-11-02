FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 DATA_DIR=/data FRONTEND_DIR=/app/frontend
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY kincoin ./kincoin
COPY frontend ./frontend
RUN mkdir -p /data
EXPOSE 8000
# Render et Fly.io imposent le port via la variable PORT.
CMD ["sh", "-c", "uvicorn kincoin.node:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
