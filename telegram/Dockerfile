FROM python:3.12-slim

WORKDIR /app

# Устанавливаем postgresql-client для применения миграций
RUN apt-get update && \
    apt-get install -y --no-install-recommends postgresql-client && \
    rm -rf /var/lib/apt/lists/*

# Копируем зависимости Telegram бота
COPY telegram/requirements.txt /app/requirements.txt

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь проект (для доступа к core, services и т.д.)
COPY . /app

# Создаем необходимые директории с правильными правами
RUN mkdir -p /app/data /app/logs && \
    chmod -R 777 /app/data /app/logs

# Устанавливаем рабочую директорию
WORKDIR /app

# Устанавливаем PYTHONPATH для импортов
ENV PYTHONPATH=/app

# Команда по умолчанию
CMD ["python", "telegram/telegram_bot_app.py"]

