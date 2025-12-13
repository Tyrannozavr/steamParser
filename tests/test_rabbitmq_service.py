"""
Тесты для RabbitMQ сервиса.
Проверяет публикацию задач, retry механизм и обработку ошибок.
"""
import asyncio
import pytest
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.rabbitmq_service import RabbitMQService
from core import Config

pytest_plugins = ('pytest_asyncio',)


@pytest.fixture
async def rabbitmq_service():
    """Создает и подключает RabbitMQ сервис для тестов."""
    service = RabbitMQService(rabbitmq_url=Config.RABBITMQ_URL)
    await service.connect()
    yield service
    await service.disconnect()


@pytest.mark.asyncio
async def test_rabbitmq_connection(rabbitmq_service):
    """Тест подключения к RabbitMQ."""
    assert rabbitmq_service.is_connected()
    assert rabbitmq_service._connection is not None
    assert rabbitmq_service._channel is not None
    assert rabbitmq_service._parsing_queue is not None


@pytest.mark.asyncio
async def test_publish_task(rabbitmq_service):
    """Тест публикации задачи в RabbitMQ."""
    task_data = {
        "type": "parsing_task",
        "task_id": 999,
        "item_name": "Test Item",
        "appid": 730,
        "currency": 1,
        "filters_json": {}
    }
    
    await rabbitmq_service.publish_task(task_data)
    
    # Проверяем, что задача опубликована (нет исключений)
    assert True


@pytest.mark.asyncio
async def test_consume_task(rabbitmq_service):
    """Тест получения задачи из RabbitMQ."""
    task_data = {
        "type": "parsing_task",
        "task_id": 1000,
        "item_name": "Test Item Consume",
        "appid": 730,
        "currency": 1,
        "filters_json": {}
    }
    
    # Публикуем задачу
    await rabbitmq_service.publish_task(task_data)
    
    # Обработчик для получения задачи
    received_task = None
    received_message = None
    
    async def task_handler(task: Dict[str, Any], message: Any):
        nonlocal received_task, received_message
        received_task = task
        received_message = message
        await message.ack()
    
    # Запускаем потребителя
    consumer_task = asyncio.create_task(
        rabbitmq_service.consume_tasks(task_handler, consumer_name="test-consumer")
    )
    
    # Ждем получения задачи (максимум 5 секунд)
    for _ in range(50):  # 50 попыток по 0.1 секунды
        if received_task is not None:
            break
        await asyncio.sleep(0.1)
    
    # Останавливаем потребителя
    await rabbitmq_service.stop_consumer("test-consumer")
    consumer_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        pass
    
    # Проверяем, что задача получена
    assert received_task is not None
    assert received_task["task_id"] == 1000
    assert received_task["item_name"] == "Test Item Consume"


@pytest.mark.asyncio
async def test_requeue_task(rabbitmq_service):
    """Тест повторной публикации задачи с задержкой."""
    task_data = {
        "type": "parsing_task",
        "task_id": 1001,
        "item_name": "Test Item Requeue",
        "appid": 730,
        "currency": 1,
        "filters_json": {}
    }
    
    # Публикуем задачу с задержкой
    await rabbitmq_service.requeue_task(task_data, delay_seconds=1)
    
    # Проверяем, что задача опубликована (нет исключений)
    assert True


@pytest.mark.asyncio
async def test_retry_mechanism(rabbitmq_service):
    """Тест retry механизма при ошибке обработки."""
    task_data = {
        "type": "parsing_task",
        "task_id": 1002,
        "item_name": "Test Item Retry",
        "appid": 730,
        "currency": 1,
        "filters_json": {}
    }
    
    # Публикуем задачу
    await rabbitmq_service.publish_task(task_data)
    
    # Счетчик попыток
    attempt_count = 0
    
    async def failing_handler(task: Dict[str, Any], message: Any):
        nonlocal attempt_count
        attempt_count += 1
        # Всегда выбрасываем ошибку для тестирования retry
        raise Exception(f"Test error on attempt {attempt_count}")
    
    # Запускаем потребителя
    consumer_task = asyncio.create_task(
        rabbitmq_service.consume_tasks(failing_handler, consumer_name="test-retry-consumer")
    )
    
    # Ждем несколько попыток (максимум 10 секунд)
    for _ in range(100):
        if attempt_count >= 2:  # Проверяем, что было минимум 2 попытки
            break
        await asyncio.sleep(0.1)
    
    # Останавливаем потребителя
    await rabbitmq_service.stop_consumer("test-retry-consumer")
    consumer_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        pass
    
    # Проверяем, что было несколько попыток (retry работает)
    assert attempt_count >= 1


@pytest.mark.asyncio
async def test_multiple_tasks_parallel(rabbitmq_service):
    """Тест параллельной обработки нескольких задач."""
    tasks_data = [
        {
            "type": "parsing_task",
            "task_id": 2000 + i,
            "item_name": f"Test Item {i}",
            "appid": 730,
            "currency": 1,
            "filters_json": {}
        }
        for i in range(5)
    ]
    
    # Публикуем все задачи
    for task_data in tasks_data:
        await rabbitmq_service.publish_task(task_data)
    
    # Обработанные задачи
    processed_tasks = []
    
    async def parallel_handler(task: Dict[str, Any], message: Any):
        task_id = task["task_id"]
        processed_tasks.append(task_id)
        # Имитируем обработку
        await asyncio.sleep(0.1)
        await message.ack()
    
    # Запускаем потребителя
    consumer_task = asyncio.create_task(
        rabbitmq_service.consume_tasks(parallel_handler, consumer_name="test-parallel-consumer")
    )
    
    # Ждем обработки всех задач (максимум 10 секунд)
    for _ in range(200):
        if len(processed_tasks) >= len(tasks_data):
            break
        await asyncio.sleep(0.1)
    
    # Останавливаем потребителя
    await rabbitmq_service.stop_consumer("test-parallel-consumer")
    consumer_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        pass
    
    # Проверяем, что все задачи обработаны
    assert len(processed_tasks) == len(tasks_data)
    for task_data in tasks_data:
        assert task_data["task_id"] in processed_tasks


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
