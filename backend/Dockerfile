FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# (опционально, но полезно) пакеты для сборки зависимостей
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libspatialindex-dev \
    && rm -rf /var/lib/apt/lists/*

# сначала зависимости
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# затем код
COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
