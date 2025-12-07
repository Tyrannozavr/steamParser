#!/bin/bash
set -e

echo "Инициализация базы данных PostgreSQL..."

# Экспортируем переменные окружения для psql
export PGPASSWORD="${POSTGRES_PASSWORD}"

# Ждем, пока PostgreSQL будет готов
echo "Ожидание готовности PostgreSQL..."
until pg_isready -U "${POSTGRES_USER}" -d postgres; do
  sleep 1
done

# Проверяем, существует ли база данных
DB_EXISTS=$(psql -U "${POSTGRES_USER}" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='${POSTGRES_DB}'" 2>/dev/null || echo "")

if [ -z "$DB_EXISTS" ]; then
  echo "Создание базы данных ${POSTGRES_DB}..."
  psql -U "${POSTGRES_USER}" -d postgres -c "CREATE DATABASE ${POSTGRES_DB};"
  echo "✅ База данных ${POSTGRES_DB} создана успешно."
else
  echo "ℹ️ База данных ${POSTGRES_DB} уже существует."
fi

# Применение миграций (если они есть)
echo "Проверка миграций..."
MIGRATIONS_DIR="/docker-entrypoint-initdb.d/migrations"
if [ -d "$MIGRATIONS_DIR" ]; then
  echo "📋 Найдена директория миграций: $MIGRATIONS_DIR"
  
  # Создаем таблицу для отслеживания миграций ПЕРВОЙ (если её нет)
  echo "📋 Создание таблицы для отслеживания миграций..."
  psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" <<EOF > /dev/null 2>&1
CREATE TABLE IF NOT EXISTS schema_migrations (
  id SERIAL PRIMARY KEY,
  migration_name VARCHAR(255) UNIQUE NOT NULL,
  applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
EOF
  
  # Применяем миграции в порядке их номеров
  for migration_file in $(ls -1 "$MIGRATIONS_DIR"/*.sql 2>/dev/null | sort); do
    migration_name=$(basename "$migration_file")
    echo "🔄 Применение миграции: $migration_name"
    
    # Проверяем, была ли миграция уже применена
    MIGRATION_APPLIED=$(psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -tAc \
      "SELECT 1 FROM schema_migrations WHERE migration_name='$migration_name'" 2>/dev/null || echo "")
    
    if [ -z "$MIGRATION_APPLIED" ]; then
      # Применяем миграцию (игнорируем ошибки, если таблица еще не существует - она создастся через SQLAlchemy)
      if psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -f "$migration_file" > /dev/null 2>&1; then
        echo "✅ Миграция $migration_name применена успешно"
        
        # Записываем информацию о примененной миграции
        psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c "
          INSERT INTO schema_migrations (migration_name) VALUES ('$migration_name')
          ON CONFLICT (migration_name) DO NOTHING;
        " > /dev/null 2>&1
      else
        echo "⚠️ Миграция $migration_name не применена (возможно, таблица еще не создана - будет применена при следующем запуске через SQLAlchemy)"
      fi
    else
      echo "ℹ️ Миграция $migration_name уже применена, пропускаем"
    fi
  done
else
  echo "ℹ️ Директория миграций не найдена, пропускаем применение миграций"
fi

echo "Инициализация завершена."

