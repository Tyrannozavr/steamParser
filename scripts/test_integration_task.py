"""
Интеграционный тест: добавление задачи и проверка полного цикла.
Проверяет, что предмет спарсился, прошел фильтры и уведомление отправлено в телеграм.
"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from core import DatabaseManager, MonitoringTask, FoundItem, SearchFilters, FloatRange, PatternList
from services import MonitoringService
from services.redis_service import RedisService
from loguru import logger


async def main():
    """Основная функция интеграционного теста."""
    print("=" * 70)
    print("🧪 ИНТЕГРАЦИОННЫЙ ТЕСТ: Полный цикл парсинга и уведомлений")
    print("=" * 70)
    
    # Параметры задачи
    task_params = {
        "name": "AK-47 | Redline (Field-Tested) - Паттерн 522 (Integration Test)",
        "item_name": "AK-47 | Redline (Field-Tested)",
        "appid": 730,
        "currency": 1,
        "max_price": 50.0,
        "float_range": FloatRange(min=0.350000, max=0.360000),
        "pattern_list": PatternList(patterns=[522], item_type="skin")
    }
    
    async with DatabaseManager() as db:
        session = await db.get_session()
        redis_service = RedisService()
        await redis_service.connect()
        
        try:
            monitoring_service = MonitoringService(session, redis_service)
            
            # Ищем существующую задачу с такими параметрами
            existing_task = await session.execute(
                select(MonitoringTask).where(
                    MonitoringTask.item_name == task_params["item_name"],
                    MonitoringTask.is_active == True
                )
            )
            existing = existing_task.scalar_one_or_none()
            
            if existing:
                print(f"⚠️  Найдена существующая активная задача ID={existing.id}, удаляем...")
                await monitoring_service.delete_monitoring_task(existing.id)
                await session.commit()
            
            # Создаем новую задачу
            print(f"\n📝 Создаем новую задачу с параметрами:")
            print(f"   Предмет: {task_params['item_name']}")
            print(f"   Макс. цена: ${task_params['max_price']:.2f}")
            print(f"   Float: {task_params['float_range'].min} - {task_params['float_range'].max}")
            print(f"   Паттерны: {task_params['pattern_list'].patterns}")
            
            filters = SearchFilters(
                item_name=task_params["item_name"],
                appid=task_params["appid"],
                currency=task_params["currency"],
                max_price=task_params["max_price"],
                float_range=task_params["float_range"],
                pattern_list=task_params["pattern_list"]
            )
            
            task_id = await monitoring_service.add_monitoring_task(
                name=task_params["name"],
                item_name=task_params["item_name"],
                filters=filters
            )
            
            await session.commit()
            print(f"✅ Задача создана с ID={task_id}")
            
            # Добавляем задачу в очередь Redis
            task_data = {
                "task_id": task_id,
                "action": "parse"
            }
            await redis_service.push_to_queue("parsing_tasks", task_data)
            print(f"✅ Задача добавлена в очередь Redis")
            
            # Ждем обработки задачи и проверяем результаты
            print(f"\n⏳ Ожидаем обработки задачи (максимум 5 минут)...")
            max_wait_time = 300  # 5 минут
            check_interval = 10  # проверяем каждые 10 секунд
            waited = 0
            
            while waited < max_wait_time:
                await asyncio.sleep(check_interval)
                waited += check_interval
                
                # Проверяем, есть ли найденные предметы
                found_items = await session.execute(
                    select(FoundItem).where(FoundItem.task_id == task_id)
                )
                items = found_items.scalars().all()
                
                if items:
                    print(f"\n✅ Найдено {len(items)} предметов!")
                    for item in items:
                        print(f"   - ID={item.id}, Название={item.item_name}, Цена=${item.price:.2f}")
                        print(f"     Уведомление отправлено: {'Да' if item.notification_sent else 'Нет'}")
                    
                    # Проверяем, что уведомление было отправлено
                    if any(item.notification_sent for item in items):
                        print(f"\n🎉 УСПЕХ! Предмет найден, фильтры пройдены, уведомление отправлено в Telegram!")
                        return True
                    else:
                        print(f"\n⚠️  Предмет найден, но уведомление еще не отправлено. Ждем еще...")
                
                print(f"   Проверка через {waited} секунд... (найдено: {len(items)})")
            
            print(f"\n❌ Таймаут: задача не была обработана за {max_wait_time} секунд")
            
            # Проверяем статус задачи
            task = await session.get(MonitoringTask, task_id)
            if task:
                print(f"   Статус задачи: активна={task.is_active}, проверок={task.total_checks}, найдено={task.items_found}")
            
            return False
            
        except Exception as e:
            logger.error(f"❌ Ошибка при выполнении интеграционного теста: {e}")
            import traceback
            traceback.print_exc()
            
            # Удаляем задачу при ошибке
            try:
                task = await session.get(MonitoringTask, task_id)
                if task:
                    await monitoring_service.delete_monitoring_task(task_id)
                    await session.commit()
                    print(f"🗑️  Задача {task_id} удалена из-за ошибки")
            except:
                pass
            
            return False
        
        finally:
            await session.close()
            await redis_service.disconnect()


if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result else 1)

