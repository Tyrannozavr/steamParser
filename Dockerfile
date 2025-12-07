# Production Dockerfile
FROM python:3.12-slim

WORKDIR /app

# Установка зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование кода
COPY . .

# Создание директорий для данных и логов
RUN mkdir -p /app/data /app/logs

# Переменные окружения
ENV PYTHONUNBUFFERED=1
ENV DATABASE_PATH=/app/data/steam_monitor.db
ENV LOG_DIR=/app/logs

# Volume для персистентности данных
VOLUME ["/app/data", "/app/logs"]

# Запуск приложения (бот)
CMD ["python", "bot_app.py"]

