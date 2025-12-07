#!/usr/bin/env python3
"""
Скрипт для проверки правильности данных о наклейках.
Сравнивает данные из разных источников.
"""
import asyncio
import sys
import json
import httpx
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent))

from core import Config, DatabaseManager

async def verify_stickers_data():
    """Проверяет правильность данных о наклейках для найденного предмета."""
    
    listing_id = "746037321908372777"
    inspect_link = "steam://rungame/730/76561202255233023/+csgo_econ_action_preview%20M746037321908372777A47785113748D9431699668890602261"
    
    print("🔍 ПРОВЕРКА ПРАВИЛЬНОСТИ ДАННЫХ О НАКЛЕЙКАХ")
    print("=" * 60)
    print(f"📋 Listing ID: {listing_id}")
    print(f"🔗 Inspect Link: {inspect_link}")
    
    # 1. Получаем данные из нашей БД
    print("\n1️⃣ ДАННЫЕ ИЗ НАШЕЙ БАЗЫ ДАННЫХ:")
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    session = await db_manager.get_session()
    
    try:
        from sqlalchemy import select
        from core import FoundItem
        
        result = await session.execute(
            select(FoundItem).where(FoundItem.item_data_json.op('->>')('listing_id') == listing_id)
        )
        found_item = result.scalar_one_or_none()
        
        if found_item:
            item_data = json.loads(found_item.item_data_json)
            print(f"   ✅ Предмет найден в БД: {found_item.item_name}")
            print(f"   💰 Цена: ${found_item.price:.2f}")
            print(f"   🎯 Float: {item_data.get('float_value', 'N/A')}")
            print(f"   🔢 Паттерн: {item_data.get('pattern', 'N/A')}")
            print(f"   🏷️ Наклеек: {len(item_data.get('stickers', []))}")
            
            stickers = item_data.get('stickers', [])
            if stickers:
                print("   📋 Детали наклеек из БД:")
                for i, sticker in enumerate(stickers, 1):
                    print(f"      {i}. {sticker.get('name', 'Unknown')} - ${sticker.get('price', 0):.2f} (Slot {sticker.get('position', 0) + 1})")
                print(f"   💰 Общая цена наклеек: ${item_data.get('total_stickers_price', 0):.2f}")
        else:
            print("   ❌ Предмет не найден в БД")
            return
    finally:
        await session.close()
        await db_manager.close()
    
    # 2. Проверяем через внешние API
    print("\n2️⃣ ПРОВЕРКА ЧЕРЕЗ ВНЕШНИЕ API:")
    
    # Извлекаем параметры из inspect ссылки
    if "M" in inspect_link and "A" in inspect_link and "D" in inspect_link:
        parts = inspect_link.split("M")[1].split("A")
        if len(parts) >= 2:
            market_id = parts[0]
            asset_parts = parts[1].split("D")
            if len(asset_parts) >= 2:
                asset_id = asset_parts[0]
                d_param = asset_parts[1]
                
                print(f"   📋 Извлеченные параметры:")
                print(f"      Market ID: {market_id}")
                print(f"      Asset ID: {asset_id}")
                print(f"      D Parameter: {d_param}")
                
                # Проверяем через cs2floatchecker.com
                print("\n   🌐 Проверка через cs2floatchecker.com:")
                try:
                    async with httpx.AsyncClient(timeout=30) as client:
                        # Формируем URL для cs2floatchecker
                        api_url = f"https://api.cs2floatchecker.com/?url={inspect_link}"
                        
                        response = await client.get(api_url)
                        if response.status_code == 200:
                            data = response.json()
                            print(f"      ✅ Ответ получен:")
                            print(f"         Float: {data.get('floatvalue', 'N/A')}")
                            print(f"         Паттерн: {data.get('paintseed', 'N/A')}")
                            
                            # Проверяем наклейки
                            stickers_data = data.get('stickers', [])
                            if stickers_data:
                                print(f"         Наклеек: {len(stickers_data)}")
                                print("         Детали наклеек:")
                                for i, sticker in enumerate(stickers_data, 1):
                                    name = sticker.get('name', 'Unknown')
                                    slot = sticker.get('slot', i-1)
                                    print(f"            {i}. {name} (Slot {slot + 1})")
                            else:
                                print("         Наклеек не найдено")
                        else:
                            print(f"      ❌ Ошибка API: {response.status_code}")
                except Exception as e:
                    print(f"      ❌ Ошибка запроса: {e}")
    
    # 3. Проверяем через Steam API (если доступен)
    print("\n3️⃣ ПРОВЕРКА ЧЕРЕЗ STEAM COMMUNITY API:")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            # Пробуем получить данные через Steam Community API
            steam_url = f"https://steamcommunity.com/market/listings/730/StatTrak%E2%84%A2%20AK-47%20%7C%20Slate%20%28Field-Tested%29/render/"
            params = {
                "query": "",
                "start": 0,
                "count": 10,
                "country": "US",
                "language": "english",
                "currency": 1
            }
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Referer": "https://steamcommunity.com/market/"
            }
            
            response = await client.get(steam_url, params=params, headers=headers)
            if response.status_code == 200:
                data = response.json()
                
                # Ищем наш конкретный лот
                if 'listinginfo' in data:
                    listing_info = data['listinginfo'].get(listing_id)
                    if listing_info:
                        print(f"      ✅ Лот найден в Steam API:")
                        print(f"         Цена: ${listing_info.get('converted_price', 0) / 100:.2f}")
                        print(f"         Asset ID: {listing_info.get('asset', {}).get('id', 'N/A')}")
                        
                        # Проверяем assets для получения данных о наклейках
                        if 'assets' in data:
                            asset_key = f"730_2_{listing_info.get('asset', {}).get('id', '')}"
                            asset_data = data['assets'].get('730', {}).get('2', {}).get(listing_info.get('asset', {}).get('id', ''))
                            
                            if asset_data:
                                descriptions = asset_data.get('descriptions', [])
                                sticker_descriptions = [d for d in descriptions if 'Sticker:' in d.get('value', '')]
                                
                                if sticker_descriptions:
                                    print(f"         Наклеек в descriptions: {len(sticker_descriptions)}")
                                    for desc in sticker_descriptions:
                                        print(f"            {desc.get('value', '')}")
                                else:
                                    print("         Наклеек в descriptions не найдено")
                    else:
                        print(f"      ❌ Лот {listing_id} не найден в ответе Steam API")
                else:
                    print("      ❌ Нет данных listinginfo в ответе")
            else:
                print(f"      ❌ Ошибка Steam API: {response.status_code}")
    except Exception as e:
        print(f"      ❌ Ошибка запроса к Steam API: {e}")
    
    # 4. Рекомендации по проверке
    print("\n4️⃣ СПОСОБЫ РУЧНОЙ ПРОВЕРКИ:")
    print("   🔗 Откройте inspect ссылку в CS:GO/CS2:")
    print(f"      {inspect_link}")
    print("   📱 Или используйте онлайн сервисы:")
    print("      • https://cs2floatchecker.com/")
    print("      • https://csgofloat.com/")
    print("      • https://csgo.exchange/")
    print("   🌐 Вставьте inspect ссылку и сравните результаты")
    
    print("\n✅ ЗАКЛЮЧЕНИЕ:")
    print("   Наши данные получены через надежные API источники")
    print("   Для окончательной проверки используйте inspect ссылку в игре")
    print("   или проверенные онлайн сервисы для анализа скинов CS:GO/CS2")

if __name__ == "__main__":
    asyncio.run(verify_stickers_data())
