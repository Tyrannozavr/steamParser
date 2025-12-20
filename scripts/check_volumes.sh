#!/bin/bash
# Скрипт для проверки volumes и их использования

echo "=========================================="
echo "📦 ПРОВЕРКА VOLUMES"
echo "=========================================="
echo ""

echo "1️⃣ Все volumes проекта:"
docker volume ls | grep -E "steam|postgres|rabbitmq|redis" || echo "Volumes не найдены"
echo ""

echo "2️⃣ Статус контейнеров:"
docker compose ps
echo ""

echo "3️⃣ Детали volumes:"
for volume in $(docker volume ls -q | grep -E "steam|postgres|rabbitmq|redis"); do
    echo "--- Volume: $volume ---"
    docker volume inspect $volume 2>/dev/null | grep -E "Name|Mountpoint|CreatedAt" || echo "Volume не найден"
    echo ""
done

echo "4️⃣ Какие контейнеры используют volumes:"
docker ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Mounts}}" | grep -E "steam|postgres|rabbitmq|redis|NAMES"
echo ""

echo "5️⃣ Проверка монтирования postgres-data:"
docker compose config | grep -A 5 "postgres-data" || echo "postgres-data не найден в конфиге"
echo ""

echo "=========================================="
echo "💡 ИНТЕРПРЕТАЦИЯ:"
echo "=========================================="
echo ""
echo "Серый volume = не используется запущенными контейнерами"
echo "Зеленый volume = используется активными контейнерами"
echo ""
echo "Если postgres-data серый:"
echo "  - Контейнер postgres остановлен (нормально, если не нужен)"
echo "  - ИЛИ volume не примонтирован (проблема!)"
echo ""
echo "Чтобы запустить контейнеры:"
echo "  docker compose up -d"
echo ""
