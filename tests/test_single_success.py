"""
Тест одного успешного запроса с большой задержкой.
"""
import asyncio
import httpx
import json
from urllib.parse import quote
from loguru import logger
import time

async def test_single_request():
    """Тестирует один запрос с большой задержкой"""
    hash_name = "AK-47 | Redline (Field-Tested)"
    appid = 730
    
    logger.info("=" * 80)
    logger.info(f"🧪 Тест одного запроса с задержкой 30 секунд")
    logger.info(f"Предмет: {hash_name}")
    logger.info("Ждем 30 секунд перед запросом...")
    await asyncio.sleep(30)
    
    base_url = f"https://steamcommunity.com/market/listings/{appid}/{quote(hash_name)}/render/"
    params = {
        "query": "",
        "start": 0,
        "count": 10,
        "country": "BY",
        "language": "english",
        "currency": 1
    }
    url = base_url + "?" + "&".join([f"{k}={v}" for k, v in params.items()])
    
    logger.info(f"URL: {url}")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(url)
            logger.info(f"Status Code: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                
                logger.info(f"\n📊 Структура ответа:")
                logger.info(f"   Ключи: {list(data.keys())}")
                
                # Проверяем каждый ключ
                for key in data.keys():
                    value = data[key]
                    if key == 'results_html':
                        logger.info(f"   {key}: длина={len(str(value))} символов")
                    elif key == 'assets':
                        logger.info(f"   {key}: тип={type(value)}, ключи={list(value.keys()) if isinstance(value, dict) else 'не словарь'}")
                    elif key == 'results':
                        logger.info(f"   {key}: тип={type(value)}, длина={len(value) if isinstance(value, list) else 'не список'}")
                    else:
                        logger.info(f"   {key}: {value}")
                
                # Проверяем total_count
                total_count = data.get('total_count', 'НЕТ В ОТВЕТЕ')
                success = data.get('success', False)
                results_html = data.get('results_html', '')
                results_html_len = len(results_html.strip()) if results_html else 0
                
                logger.info(f"\n📈 Анализ:")
                logger.info(f"   success: {success}")
                logger.info(f"   total_count: {total_count} (тип: {type(total_count)})")
                logger.info(f"   results_html_len: {results_html_len}")
                
                # Сохраняем ответ
                data_for_save = {k: v for k, v in data.items() if k != 'results_html'}
                with open('test_success_response.json', 'w', encoding='utf-8') as f:
                    json.dump(data_for_save, f, indent=2, ensure_ascii=False)
                logger.info(f"\n💾 Ответ сохранен в test_success_response.json")
                
                return data
            else:
                logger.error(f"❌ Ошибка: status_code={response.status_code}")
                logger.error(f"   Ответ: {response.text[:500]}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Исключение: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None

if __name__ == "__main__":
    asyncio.run(test_single_request())

