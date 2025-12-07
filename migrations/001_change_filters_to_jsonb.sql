-- Миграция для изменения типа поля filters_json с TEXT на JSONB
-- Это позволит выполнять эффективные запросы по JSON данным
-- ВАЖНО: Эта миграция применяется только если таблица monitoring_tasks уже существует

DO \$\$
BEGIN
  -- Проверяем, существует ли таблица
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'monitoring_tasks') THEN
    -- Проверяем, нужно ли применять миграцию (если поле уже JSONB, пропускаем)
    IF EXISTS (
      SELECT 1 FROM information_schema.columns 
      WHERE table_name = 'monitoring_tasks' 
      AND column_name = 'filters_json' 
      AND data_type != 'jsonb'
    ) THEN
      -- Добавляем новое JSONB поле
      ALTER TABLE monitoring_tasks ADD COLUMN filters_jsonb JSONB;

      -- Копируем данные из старого поля, преобразуя TEXT в JSONB
      UPDATE monitoring_tasks SET filters_jsonb = filters_json::JSONB WHERE filters_json IS NOT NULL;

      -- Удаляем старое поле
      ALTER TABLE monitoring_tasks DROP COLUMN filters_json;

      -- Переименовываем новое поле
      ALTER TABLE monitoring_tasks RENAME COLUMN filters_jsonb TO filters_json;

      -- Добавляем NOT NULL ограничение
      ALTER TABLE monitoring_tasks ALTER COLUMN filters_json SET NOT NULL;

      -- Добавляем комментарий
      COMMENT ON COLUMN monitoring_tasks.filters_json IS 'JSONB с настройками фильтров';

      -- Создаем индекс для эффективных запросов по JSONB
      CREATE INDEX idx_monitoring_tasks_filters_gin ON monitoring_tasks USING GIN (filters_json);

      -- Создаем индексы для часто используемых полей в JSON
      CREATE INDEX IF NOT EXISTS idx_monitoring_tasks_max_price ON monitoring_tasks USING BTREE ((filters_json->>'max_price'));
      CREATE INDEX IF NOT EXISTS idx_monitoring_tasks_item_type ON monitoring_tasks USING BTREE ((filters_json->'pattern_list'->>'item_type'));
    END IF;
  END IF;
END \$\$;
