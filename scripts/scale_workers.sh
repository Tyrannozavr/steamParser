#!/bin/bash
# Скрипт для масштабирования parsing-worker воркеров

WORKERS_COUNT=${1:-2}  # По умолчанию 2 воркера

echo "🔧 Масштабирование parsing-worker до $WORKERS_COUNT воркеров..."

# Останавливаем текущие воркеры
docker compose stop parsing-worker

# Удаляем старые контейнеры
docker compose rm -f parsing-worker

# Запускаем указанное количество воркеров
docker compose up -d --scale parsing-worker=$WORKERS_COUNT

echo "✅ Запущено $WORKERS_COUNT воркеров"
echo "📊 Проверьте статус: docker compose ps parsing-worker"
