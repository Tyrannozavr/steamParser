#!/bin/bash
set -e

# Выполняем стандартный entrypoint PostgreSQL
exec /usr/local/bin/docker-entrypoint.sh "$@" &

# Ждем, пока PostgreSQL будет готов
echo "Ожидание готовности PostgreSQL..."
until pg_isready -U "${POSTGRES_USER}" -d postgres >/dev/null 2>&1; do
  sleep 1
done

# Экспортируем переменные окружения для psql
export PGPASSWORD="${POSTGRES_PASSWORD}"

# Проверяем, существует ли база данных
DB_EXISTS=$(psql -U "${POSTGRES_USER}" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='${POSTGRES_DB}'" 2>/dev/null || echo "")

if [ -z "$DB_EXISTS" ]; then
  echo "Создание базы данных ${POSTGRES_DB}..."
  psql -U "${POSTGRES_USER}" -d postgres -c "CREATE DATABASE ${POSTGRES_DB};"
  echo "✅ База данных ${POSTGRES_DB} создана успешно."
else
  echo "ℹ️ База данных ${POSTGRES_DB} уже существует."
fi

# Ждем завершения основного процесса
wait

