#!/bin/bash
# Скрипт для быстрой диагностики состояния БД

echo "=========================================="
echo "🔍 ДИАГНОСТИКА БД"
echo "=========================================="
echo ""

echo "1️⃣ Проверка статуса контейнера PostgreSQL:"
docker compose ps postgres
echo ""

echo "2️⃣ Проверка доступности БД:"
docker compose exec -T postgres pg_isready -U steam_user -d steam_monitor
echo ""

echo "3️⃣ Количество активных соединений:"
docker compose exec -T postgres psql -U steam_user -d steam_monitor -c "SELECT count(*) as active_connections FROM pg_stat_activity WHERE datname = 'steam_monitor';"
echo ""

echo "4️⃣ Долгие запросы (>5 сек):"
docker compose exec -T postgres psql -U steam_user -d steam_monitor -c "SELECT pid, usename, application_name, state, age(now(), query_start) as query_age, left(query, 80) as query FROM pg_stat_activity WHERE datname = 'steam_monitor' AND query_start IS NOT NULL AND age(now(), query_start) > interval '5 seconds' ORDER BY query_start;"
echo ""

echo "5️⃣ Блокировки:"
docker compose exec -T postgres psql -U steam_user -d steam_monitor -c "SELECT count(*) as locks_count FROM pg_locks WHERE database = (SELECT oid FROM pg_database WHERE datname = 'steam_monitor');"
echo ""

echo "6️⃣ Размер БД:"
docker compose exec -T postgres psql -U steam_user -d steam_monitor -c "SELECT pg_size_pretty(pg_database_size('steam_monitor')) as database_size;"
echo ""

echo "7️⃣ Статистика по таблицам:"
docker compose exec -T postgres psql -U steam_user -d steam_monitor -c "SELECT schemaname, tablename, n_live_tup as rows, n_dead_tup as dead_rows, last_vacuum, last_autovacuum FROM pg_stat_user_tables WHERE tablename IN ('monitoring_tasks', 'found_items', 'proxies') ORDER BY tablename;"
echo ""

echo "8️⃣ Последние ошибки в логах (если есть):"
docker compose logs postgres --tail 50 | grep -i "error\|fatal\|panic" | tail -10
echo ""

echo "=========================================="
echo "✅ Диагностика завершена"
echo "=========================================="
