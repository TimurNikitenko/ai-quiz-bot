FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir \
    --index-url https://mirror.yandex.ru/pypi/simple \
    --extra-index-url https://pypi.org/simple \
    --trusted-host mirror.yandex.ru \
    --trusted-host pypi.org \
    --trusted-host files.pythonhosted.org \
    --retries 10 \
    --default-timeout 120 \
    -r requirements.txt

COPY . .

CMD ["python", "run_bot.py"]