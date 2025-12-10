#!/bin/bash
# Скрипт для проверки логов через 20 минут

cd /home/dmiv/PycharmProjects/freelance/steam

echo "=========================================="
echo "Проверка логов через 20 минут"
echo "Время: $(date)"
echo "=========================================="
echo ""

echo "📊 Ошибки за последние 20 минут:"
docker compose -f docker-compose.dev.yml logs --since 20m parsing-worker 2>&1 | grep -E "(concurrent|another operation|ERROR|CRITICAL)" | wc -l
echo ""

echo "📋 Детали ошибок:"
docker compose -f docker-compose.dev.yml logs --since 20m parsing-worker 2>&1 | grep -E "(concurrent|another operation|ERROR|CRITICAL)" | tail -10
echo ""

echo "✅ Задачи (завершенные/запущенные):"
docker compose -f docker-compose.dev.yml logs --since 20m parsing-worker 2>&1 | grep -E "(ЗАДАЧА.*ЗАВЕРШЕНА|НАЧАЛО ОБРАБОТКИ)" | wc -l
echo ""

echo "📋 Последние задачи:"
docker compose -f docker-compose.dev.yml logs --since 20m parsing-worker 2>&1 | grep -E "(ЗАДАЧА.*ЗАВЕРШЕНА|НАЧАЛО ОБРАБОТКИ)" | tail -10
echo ""

echo "🔓 Прокси (разблокированные):"
docker compose -f docker-compose.dev.yml logs --since 20m parsing-worker 2>&1 | grep -E "✅.*разблокирован" | wc -l
echo ""

echo "📊 Telegram-bot ошибки:"
docker compose -f docker-compose.dev.yml logs --since 20m telegram-bot 2>&1 | grep -E "(ERROR|CRITICAL|concurrent)" | wc -l
echo ""

echo "=========================================="
echo "Проверка завершена"
echo "=========================================="
