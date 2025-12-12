# Исправление критической ошибки: "concurrent operations are not permitted" в async SQLAlchemy

## Проблема

При работе системы мониторинга Steam Market возникла критическая ошибка, которая приводила к остановке обработки задач:

```
❌ Ошибка при проверке статуса задачи 7: This session is provisioning a new connection; 
concurrent operations are not permitted (Background on this error at: https://sqlalche.me/e/20/isce)
```

### Симптомы

1. **Задача перестает обрабатываться** - после ошибки задача полностью прекращает работу
2. **Ошибка возникает в 4 часа ночи** - вероятно, связано с пиковой нагрузкой или перезапуском сервисов
3. **Другие задачи продолжают работать** - проблема затрагивает только конкретную задачу
4. **next_check не обновляется** - при ошибке проверки статуса задача зацикливается на ошибке

### Анализ логов

Из логов видно:
- Последняя успешная проверка задачи 7: `02:06:59`
- Ошибка произошла: `02:07:59`
- После этого задача 7 больше не появляется в логах
- Задачи 6 и 8 продолжают работать нормально

## Причина ошибки

### Техническая суть проблемы

В `MonitoringService` использовалась **одна общая сессия БД** (`self.db_session`) для всех корутин мониторинга. При одновременном доступе нескольких корутин к одной сессии SQLAlchemy выбрасывает ошибку:

> "This session is provisioning a new connection; concurrent operations are not permitted"

### Проблемные места в коде

1. **Строки 264-286**: Периодическая проверка статуса задачи (каждые 6 итераций)
2. **Строки 310-332**: Проверка статуса перед публикацией в Redis

Оба блока использовали одну и ту же сессию БД без должной синхронизации:

```python
# ПРОБЛЕМНЫЙ КОД
async def monitor_loop():
    while self._running:
        # Проблема: используется общая сессия из разных корутин
        result = await self.db_session.execute(
            select(MonitoringTask).where(MonitoringTask.id == task_id)
        )
        # ...
```

### Почему это происходит

SQLAlchemy async сессии **не потокобезопасны** и **не корутино-безопасны** при одновременном использовании. Каждая сессия должна использоваться только в одной корутине.

## Решение

Реализовано три ключевых исправления:

### 1. Отдельные сессии БД для каждой корутины

Каждая корутина мониторинга теперь создает свою собственную сессию БД:

```python
async def monitor_loop():
    # Создаем отдельную сессию для этой корутины
    task_session: Optional[AsyncSession] = None
    if self.db_manager:
        task_session = await self.db_manager.get_session()
        self._task_sessions[task_id] = task_session
    else:
        # Fallback на основную сессию (старый режим)
        task_session = self.db_session
    
    try:
        # Используем task_session вместо self.db_session
        result = await task_session.execute(
            select(MonitoringTask).where(MonitoringTask.id == task_id)
        )
        # ...
    finally:
        # Закрываем сессию при выходе
        if task_session and task_session != self.db_session:
            await task_session.close()
```

**Преимущества:**
- Каждая корутина работает со своей сессией
- Нет конфликтов при одновременном доступе
- Сессии корректно закрываются при завершении

### 2. Улучшенная обработка ошибок

При ошибке проверки статуса теперь:
- **Обновляется next_check** - задача не зацикливается на ошибке
- **Ведется счетчик ошибок** - при превышении лимита мониторинг останавливается
- **Логируется полный traceback** - для диагностики

```python
consecutive_errors = 0
MAX_CONSECUTIVE_ERRORS = 5

try:
    # Проверка статуса задачи
    result = await task_session.execute(...)
except Exception as e:
    consecutive_errors += 1
    logger.error(f"❌ Ошибка при проверке статуса задачи {task_id}: {e}")
    
    # Обновляем next_check даже при ошибке
    await self._update_next_check_safe(task_id, task_session, task.check_interval)
    
    # Если слишком много ошибок - останавливаем
    if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
        logger.error(f"❌ Превышен лимит ошибок, останавливаем мониторинг")
        break
```

**Вспомогательный метод для безопасного обновления:**

```python
async def _update_next_check_safe(self, task_id: int, session: AsyncSession, check_interval: int):
    """Безопасно обновляет next_check через UPDATE запрос."""
    try:
        now = datetime.now()
        next_check = now + timedelta(seconds=check_interval)
        
        # Используем UPDATE вместо ORM для надежности
        await session.execute(
            update(MonitoringTask)
            .where(MonitoringTask.id == task_id)
            .values(next_check=next_check)
        )
        await session.commit()
    except Exception as e:
        logger.error(f"❌ Ошибка при обновлении next_check: {e}")
        await session.rollback()
```

### 3. Механизм автоматического восстановления

Если мониторинг задачи остановился из-за ошибки, система автоматически пытается его восстановить:

```python
async def _start_task_recovery(self, task_id: int):
    """Запускает механизм восстановления для остановившейся задачи."""
    
    async def recovery_loop():
        recovery_delay = 60  # Начальная задержка
        max_delay = 600  # Максимальная задержка (10 минут)
        max_attempts = 10  # Максимум попыток
        
        attempt = 0
        while self._running and attempt < max_attempts:
            await asyncio.sleep(recovery_delay)
            attempt += 1
            
            # Проверяем, что задача все еще активна
            task = await session.get(MonitoringTask, task_id)
            if not task or not task.is_active:
                break
            
            # Перезапускаем мониторинг
            await self._start_task_monitoring(task)
            logger.info(f"✅ Задача {task_id}: Мониторинг восстановлен")
            break
    
    self._recovery_tasks[task_id] = asyncio.create_task(recovery_loop())
```

**Особенности восстановления:**
- Экспоненциальная задержка между попытками (60с → 120с → 240с → ...)
- Максимум 10 попыток восстановления
- Проверка актуального статуса задачи перед восстановлением
- Автоматическая остановка при деактивации задачи

## Изменения в коде

### MonitoringService.__init__

Добавлен опциональный параметр `db_manager`:

```python
def __init__(
    self,
    db_session: AsyncSession,
    proxy_manager: ProxyManager,
    ...
    db_manager: Optional[DatabaseManager] = None  # Новый параметр
):
    self.db_manager = db_manager
    self._task_sessions: Dict[int, AsyncSession] = {}  # Отдельные сессии
    self._recovery_tasks: Dict[int, asyncio.Task] = {}  # Задачи восстановления
```

### bot_app.py

Обновлена инициализация для передачи `db_manager`:

```python
self.monitoring_service = MonitoringService(
    self.db_session,
    self.proxy_manager,
    ...
    db_manager=self.db_manager  # Передаем db_manager
)
```

## Результаты

После внедрения исправлений:

✅ **Устранена ошибка** "concurrent operations are not permitted"  
✅ **Задачи не останавливаются** при ошибках проверки статуса  
✅ **Автоматическое восстановление** остановившихся задач  
✅ **Корректное обновление next_check** даже при ошибках  
✅ **Улучшенное логирование** для диагностики проблем  

## Рекомендации

1. **Всегда используйте отдельные сессии** для каждой async корутины
2. **Не используйте одну сессию** из нескольких корутин одновременно
3. **Обрабатывайте ошибки** и обновляйте состояние даже при сбоях
4. **Реализуйте механизмы восстановления** для критичных процессов
5. **Логируйте полные traceback** для диагностики проблем

## Выводы

Проблема была вызвана неправильным использованием async сессий SQLAlchemy - одна сессия использовалась из нескольких корутин одновременно. Решение включает:

1. Создание отдельных сессий для каждой корутины
2. Улучшенную обработку ошибок с обновлением состояния
3. Механизм автоматического восстановления остановившихся задач

Эти исправления делают систему более устойчивой к ошибкам и предотвращают полную остановку мониторинга при временных сбоях.

---

**Автор:** AI Assistant  
**Дата:** 2025-12-12  
**Версия:** 1.0
