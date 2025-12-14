#!/bin/bash
# Скрипт для запуска теста задачи через Docker

echo "🚀 Запуск теста реальной задачи с паттерном через Docker..."
echo ""

# Проверяем, что контейнер запущен
if ! docker ps | grep -q "steamparser-parsing-worker"; then
    echo "❌ Контейнер steamparser-parsing-worker не запущен"
    echo "   Запустите: docker compose up -d"
    exit 1
fi

# Запускаем тест внутри контейнера
docker exec -it steamparser-parsing-worker python3 /app/scripts/test_real_task_with_pattern.py
