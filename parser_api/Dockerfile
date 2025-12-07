FROM python:3.11-slim

WORKDIR /app

# Копируем requirements и устанавливаем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь проект
COPY . .

# Устанавливаем переменные окружения
ENV PYTHONPATH=/app
ENV LOG_LEVEL=INFO
ENV LOG_DIR=/app/logs

# Создаем директорию для логов
RUN mkdir -p /app/logs

# Запускаем FastAPI сервис
CMD ["uvicorn", "parser_api.app:app", "--host", "0.0.0.0", "--port", "8000"]




