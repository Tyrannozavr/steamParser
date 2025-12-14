# Команды для отладки проблемы с сохранением в БД

## Проблема
- В БД не сохраняются изменения задач (total_checks, last_check)
- Количество проверок прибавляется раз через 2
- На Windows у клиента

## Команды для диагностики

### 1. Проверка статуса контейнеров
```bash
docker ps
```

### 2. Проверка логов parsing-worker (последние 100 строк)
```bash
docker logs --tail 100 steamparser-parsing-worker
```

### 3. Проверка логов telegram-bot (последние 100 строк)
```bash
docker logs --tail 100 steamparser-telegram-bot
```

### 4. Проверка логов PostgreSQL (последние 100 строк)
```bash
docker logs --tail 100 steam-postgres
```

### 5. Проверка подключения к PostgreSQL
```bash
docker exec -it steam-postgres psql -U steam_user -d steam_monitor -c "SELECT id, name, total_checks, last_check, next_check FROM monitoring_tasks ORDER BY id;"
```

### 6. Проверка последних ошибок в PostgreSQL
```bash
docker exec -it steam-postgres psql -U steam_user -d steam_monitor -c "SELECT * FROM pg_stat_activity WHERE state = 'idle in transaction' OR wait_event_type = 'Lock';"
```

### 7. Проверка настроек таймаутов PostgreSQL
```bash
docker exec -it steam-postgres psql -U steam_user -d steam_monitor -c "SHOW statement_timeout; SHOW lock_timeout;"
```

### 8. Проверка блокировок в БД
```bash
docker exec -it steam-postgres psql -U steam_user -d steam_monitor -c "SELECT pid, locktype, relation::regclass, mode, granted FROM pg_locks WHERE relation::regclass::text = 'monitoring_tasks';"
```

### 9. Проверка RabbitMQ (если доступен)
```bash
docker exec -it steam-rabbitmq rabbitmqctl list_queues name messages consumers
```

### 10. Проверка переменных окружения (RabbitMQ)
```bash
docker exec steamparser-telegram-bot env | grep RABBITMQ
docker exec steamparser-parsing-worker env | grep RABBITMQ
```

### 11. Мониторинг логов в реальном времени (parsing-worker)
```bash
docker logs -f steamparser-parsing-worker
```

### 12. Проверка последних обновлений в таблице monitoring_tasks
```bash
docker exec -it steam-postgres psql -U steam_user -d steam_monitor -c "SELECT id, name, total_checks, last_check, updated_at, EXTRACT(EPOCH FROM (NOW() - updated_at)) as seconds_since_update FROM monitoring_tasks ORDER BY updated_at DESC LIMIT 5;"
```

### 13. Проверка активных транзакций
```bash
docker exec -it steam-postgres psql -U steam_user -d steam_monitor -c "SELECT pid, usename, application_name, state, query_start, state_change, wait_event_type, wait_event FROM pg_stat_activity WHERE datname = 'steam_monitor' AND state != 'idle';"
```

## Что искать в логах

1. **В логах parsing-worker:**
   - Ошибки "Ошибка при сохранении задачи"
   - Ошибки "canceling statement due to user request"
   - Сообщения о таймаутах

2. **В логах PostgreSQL:**
   - Ошибки "canceling statement due to user request"
   - Долгие транзакции
   - Блокировки

3. **В логах telegram-bot:**
   - "RabbitMQ сервис не инициализирован"
   - Ошибки подключения к RabbitMQ

## Возможные причины

1. **Таймаут БД слишком короткий** - исправлено (увеличено до 30 секунд)
2. **Ошибка в results_processor** - исправлено (добавлен fallback сохранение)
3. **RabbitMQ не инициализирован** - нужно проверить переменные окружения
4. **Блокировки в БД** - проверить командами выше
5. **Долгие транзакции** - проверить активные транзакции
