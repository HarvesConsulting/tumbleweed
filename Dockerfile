FROM python:3.11-slim

WORKDIR /app

# Системні залежності
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libxml2-dev libxslt1-dev libcurl4-openssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Копіюємо проект
COPY pyproject.toml ./
COPY src ./src
COPY data ./data

# Встановлюємо залежності + gunicorn
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e . && \
    pip install --no-cache-dir gunicorn

# Env
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

EXPOSE 8080

# Запуск через gunicorn (1 worker, 4 threads — для async)
CMD gunicorn --workers 1 --threads 4 --timeout 180 --bind 0.0.0.0:$PORT tumbleweed.webhook:app
