# Миграции базы данных

## Применение миграций

### 1. Миграция на JSONB (001_change_filters_to_jsonb.sql)

Эта миграция изменяет тип поля `filters_json` с `TEXT` на `JSONB` для более эффективных запросов.

**Преимущества JSONB:**
- Более быстрые запросы по JSON данным
- Возможность создания индексов на JSON поля
- Автоматическая валидация JSON структуры
- Сжатие данных

**Применение:**

```bash
# Подключитесь к PostgreSQL
psql -h localhost -U your_user -d steam_monitor

# Выполните миграцию
\i migrations/001_change_filters_to_jsonb.sql
```

**Или через Docker:**

```bash
# Если используете Docker Compose
docker-compose exec postgres psql -U steam_user -d steam_monitor -f /migrations/001_change_filters_to_jsonb.sql
```

**Проверка результата:**

```sql
-- Проверьте тип поля
\d monitoring_tasks

-- Проверьте индексы
\di monitoring_tasks*

-- Тестовый запрос по JSONB
SELECT id, name, filters_json->>'max_price' as max_price 
FROM monitoring_tasks 
WHERE filters_json->>'max_price' IS NOT NULL;
```

## Откат миграций

Если нужно откатить миграцию:

```sql
-- Создайте резервную копию перед откатом!
CREATE TABLE monitoring_tasks_backup AS SELECT * FROM monitoring_tasks;

-- Откат к TEXT
ALTER TABLE monitoring_tasks ALTER COLUMN filters_json TYPE TEXT;
DROP INDEX IF EXISTS idx_monitoring_tasks_filters_gin;
DROP INDEX IF EXISTS idx_monitoring_tasks_max_price;
DROP INDEX IF EXISTS idx_monitoring_tasks_item_type;
```

## Рекомендации

1. **Всегда создавайте резервную копию** перед применением миграций
2. **Тестируйте миграции** на копии продакшн данных
3. **Применяйте миграции в maintenance window** для минимизации простоя
4. **Мониторьте производительность** после применения миграций
