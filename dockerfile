FROM python:3.11-slim

WORKDIR /app

ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_DEFAULT_TIMEOUT=120
ARG PIP_RETRIES=10

COPY requirements.txt .
RUN pip install \
    --no-cache-dir \
    --index-url "${PIP_INDEX_URL}" \
    --timeout "${PIP_DEFAULT_TIMEOUT}" \
    --retries "${PIP_RETRIES}" \
    -r requirements.txt

COPY main.py .

EXPOSE 8000

# 生产环境建议用 --workers 根据 CPU 核数调整
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
