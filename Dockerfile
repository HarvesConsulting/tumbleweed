FROM python:3.11-slim

WORKDIR /app

# Env
ENV PYTHONUNBUFFERED=1
ENV PORT=8080
ENV PIP_NO_CACHE_DIR=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

# Системні залежності — тільки для компіляції.
# Після pip install — видаляємо, щоб не тягнути в образ.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libxml2-dev libxslt1-dev libcurl4-openssl-dev \
    && pip install --upgrade pip \
    && rm -rf /var/lib/apt/lists/*

# Копіюємо тільки необхідне (без tests/, .venv/, __pycache__)
COPY pyproject.toml ./
COPY src ./src
COPY data ./data

# Встановлюємо залежності + gunicorn
RUN pip install . \
    && pip install gunicorn \
    && apt-get purge -y --auto-remove gcc g++ libxml2-dev libxslt1-dev libcurl4-openssl-dev

EXPOSE 8080

# Запуск через gunicorn
CMD gunicorn --workers 1 --threads 4 --timeout 180 --bind 0.0.0.0:$PORT tumbleweed.webhook:app
