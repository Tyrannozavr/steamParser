FROM python:3.12-slim

WORKDIR /app

# Копируем зависимости Parsing Worker
COPY parsing/requirements.txt /app/requirements.txt

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
CMD ["python", "parsing/parsing_worker.py"]

