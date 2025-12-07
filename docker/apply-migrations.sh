#!/bin/bash
# Скрипт для применения миграций базы данных
# Может быть вызван из любого сервиса при старте

set -e

echo "🔄 Проверка и применение миграций базы данных..."

# Экспортируем переменные окружения для psql
export PGPASSWORD="${POSTGRES_PASSWORD:-steam_password}"

# Параметры подключения
POSTGRES_USER="${POSTGRES_USER:-steam_user}"
POSTGRES_DB="${POSTGRES_DB:-steam_monitor}"
POSTGRES_HOST="${POSTGRES_HOST:-postgres}"

# Ждем, пока PostgreSQL будет готов
echo "⏳ Ожидание готовности PostgreSQL на ${POSTGRES_HOST}..."
max_attempts=30
attempt=0
until pg_isready -h "${POSTGRES_HOST}" -U "${POSTGRES_USER}" -d postgres; do
    attempt=$((attempt + 1))
    if [ $attempt -ge $max_attempts ]; then
        echo "❌ PostgreSQL не готов после $max_attempts попыток"
        exit 1
    fi
    sleep 1
done
echo "✅ PostgreSQL готов"

# Применение миграций (если они есть)
MIGRATIONS_DIR="/app/migrations"
if [ ! -d "$MIGRATIONS_DIR" ]; then
    echo "ℹ️ Директория миграций не найдена: $MIGRATIONS_DIR"
    exit 0
fi

echo "📋 Найдена директория миграций: $MIGRATIONS_DIR"

# Создаем таблицу для отслеживания миграций ПЕРВОЙ (если её нет)
echo "📋 Создание таблицы для отслеживания миграций..."
psql -h "${POSTGRES_HOST}" -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" <<EOF > /dev/null 2>&1
CREATE TABLE IF NOT EXISTS schema_migrations (
  id SERIAL PRIMARY KEY,
  migration_name VARCHAR(255) UNIQUE NOT NULL,
  applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
EOF

# Применяем миграции в порядке их номеров
migrations_applied=0
for migration_file in $(ls -1 "$MIGRATIONS_DIR"/*.sql 2>/dev/null | sort); do
    migration_name=$(basename "$migration_file")
    echo "🔄 Проверка миграции: $migration_name"
    
    # Проверяем, была ли миграция уже применена
    MIGRATION_APPLIED=$(psql -h "${POSTGRES_HOST}" -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -tAc \
        "SELECT 1 FROM schema_migrations WHERE migration_name='$migration_name'" 2>/dev/null || echo "")
    
    if [ -z "$MIGRATION_APPLIED" ]; then
        # Применяем миграцию
        echo "   ➡️ Применение миграции $migration_name..."
        if psql -h "${POSTGRES_HOST}" -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -f "$migration_file" 2>&1; then
            echo "   ✅ Миграция $migration_name применена успешно"
            
            # Записываем информацию о примененной миграции
            psql -h "${POSTGRES_HOST}" -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c "
                INSERT INTO schema_migrations (migration_name) VALUES ('$migration_name')
                ON CONFLICT (migration_name) DO NOTHING;
            " > /dev/null 2>&1
            migrations_applied=$((migrations_applied + 1))
        else
            echo "   ⚠️ Миграция $migration_name не применена (возможно, таблица еще не создана)"
        fi
    else
        echo "   ℹ️ Миграция $migration_name уже применена, пропускаем"
    fi
done

if [ $migrations_applied -gt 0 ]; then
    echo "✅ Применено новых миграций: $migrations_applied"
else
    echo "✅ Все миграции уже применены"
fi

