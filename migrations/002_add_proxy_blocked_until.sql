-- Миграция: Добавление поля blocked_until в таблицу proxies
-- Дата: 2025-12-05
-- Описание: Добавляет поле для временных блокировок прокси вместо хранения в Redis

-- Добавляем поле blocked_until для временных блокировок
ALTER TABLE proxies 
ADD COLUMN IF NOT EXISTS blocked_until TIMESTAMP NULL;

-- Добавляем комментарий к полю
COMMENT ON COLUMN proxies.blocked_until IS 'Время до которого прокси заблокирован (NULL = не заблокирован)';

-- Создаем индекс для быстрого поиска активных и не заблокированных прокси
CREATE INDEX IF NOT EXISTS idx_proxies_active_not_blocked 
ON proxies(is_active, blocked_until) 
WHERE is_active = true AND (blocked_until IS NULL OR blocked_until < NOW());

-- Создаем индекс для поиска заблокированных прокси (для автоматической разблокировки)
CREATE INDEX IF NOT EXISTS idx_proxies_blocked_until 
ON proxies(blocked_until) 
WHERE blocked_until IS NOT NULL AND blocked_until >= NOW();

