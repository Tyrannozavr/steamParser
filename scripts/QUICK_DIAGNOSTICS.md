# Быстрая диагностика БД для клиента

## 📋 Анализ логов

**Вывод:** Логи выглядят нормально! Это просто перезапуск контейнера.

Что видно в логах:
- ✅ `FATAL: terminating connection due to administrator command` - нормально при остановке контейнера
- ✅ `LOG: database system is ready to accept connections` - БД успешно запустилась
- ✅ `PostgreSQL Database directory appears to contain a database; Skipping initialization` - БД уже существует, данные сохранены

**Это не ошибка!** Это нормальный процесс перезапуска контейнера.

---

## 🚀 Команды для диагностики

### 1. Быстрая проверка (все в одном):
```bash
./scripts/check_db_health.sh
```

### 2. Проверка статуса контейнера:
```bash
docker compose ps postgres
```

### 3. Проверка доступности БД:
```bash
docker compose exec postgres pg_isready -U steam_user -d steam_monitor
```

### 4. Активные соединения:
```bash
docker compose exec postgres psql -U steam_user -d steam_monitor -c "SELECT pid, usename, application_name, state, query_start, left(query, 100) as query FROM pg_stat_activity WHERE datname = 'steam_monitor' AND pid != pg_backend_pid() ORDER BY query_start DESC LIMIT 10;"
```

### 5. Проверка блокировок:
```bash
docker compose exec postgres psql -U steam_user -d steam_monitor -c "SELECT l.locktype, l.relation::regclass, l.mode, l.granted, a.pid, left(a.query, 80) as query FROM pg_locks l LEFT JOIN pg_stat_activity a ON l.pid = a.pid WHERE l.database = (SELECT oid FROM pg_database WHERE datname = 'steam_monitor') LIMIT 20;"
```

### 6. Долгие транзакции (>30 сек):
```bash
docker compose exec postgres psql -U steam_user -d steam_monitor -c "SELECT pid, usename, application_name, state, age(now(), xact_start) as tx_age, left(query, 100) as query FROM pg_stat_activity WHERE datname = 'steam_monitor' AND xact_start IS NOT NULL AND age(now(), xact_start) > interval '30 seconds';"
```

### 7. Долгие запросы (>5 сек):
```bash
docker compose exec postgres psql -U steam_user -d steam_monitor -c "SELECT pid, usename, application_name, state, age(now(), query_start) as query_age, left(query, 100) as query FROM pg_stat_activity WHERE datname = 'steam_monitor' AND query_start IS NOT NULL AND age(now(), query_start) > interval '5 seconds';"
```

### 8. Статистика по таблицам:
```bash
docker compose exec postgres psql -U steam_user -d steam_monitor -c "SELECT tablename, n_live_tup as rows, n_dead_tup as dead_rows, last_vacuum, last_autovacuum FROM pg_stat_user_tables WHERE tablename IN ('monitoring_tasks', 'found_items', 'proxies') ORDER BY tablename;"
```

### 9. Размер БД:
```bash
docker compose exec postgres psql -U steam_user -d steam_monitor -c "SELECT pg_size_pretty(pg_database_size('steam_monitor')) as database_size;"
```

### 10. Последние ошибки в логах:
```bash
docker compose logs postgres --tail 100 | grep -i "error\|fatal\|panic"
```

---

## 🔍 Что проверить

### ✅ Нормально:
- `FATAL: terminating connection due to administrator command` - при остановке контейнера
- `LOG: database system is ready to accept connections` - БД работает
- Перезапуск контейнера

### ⚠️ Требует внимания:
- Много долгих запросов (>5 сек)
- Много блокировок
- Много мертвых строк (dead_tup)
- Ошибки в логах после запуска

### ❌ Проблемы:
- БД не запускается
- `FATAL` ошибки при работе (не при остановке)
- Deadlocks
- Потеря данных

---

## 📊 Интерпретация результатов

### Если все хорошо:
- Контейнер `Running`
- `pg_isready` возвращает `accepting connections`
- Активных соединений: 5-20 (нормально)
- Блокировок: 0-5 (нормально)
- Долгих запросов: 0 (отлично)

### Если есть проблемы:
- Много долгих запросов → проверить индексы
- Много блокировок → проверить транзакции
- Много мертвых строк → запустить VACUUM
- Ошибки в логах → проверить конфигурацию

---

## 🛠️ Быстрые исправления

### Если много мертвых строк:
```bash
docker compose exec postgres psql -U steam_user -d steam_monitor -c "VACUUM ANALYZE monitoring_tasks;"
docker compose exec postgres psql -U steam_user -d steam_monitor -c "VACUUM ANALYZE found_items;"
```

### Если нужно перезапустить БД:
```bash
docker compose restart postgres
```

### Если нужно проверить логи в реальном времени:
```bash
docker compose logs -f postgres
```

---

## 📝 Вывод

**По логам все нормально!** Это просто перезапуск контейнера. 

Если после перезапуска все работает (приложения подключаются, нет ошибок), то проблем нет.

Если есть проблемы после перезапуска - запустите команды диагностики выше.
