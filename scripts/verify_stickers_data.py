#!/usr/bin/env python3
"""
Скрипт для проверки правильности данных о наклейках.
Сравнивает данные из разных источников для верификации.
"""
import asyncio
import sys
import json
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import Config, DatabaseManager, FoundItem

async def verify_stickers_for_item(item_id: int):
    """
    Проверяет данные о наклейках для конкретного предмета.
    
    Args:
        item_id: ID найденного предмета в БД
    """
    print(f"🔍 Проверка данных о наклейках для предмета ID: {item_id}")
    print("=" * 70)
    
    # Подключаемся к БД
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    session = await db_manager.get_session()
    
    try:
        # Получаем предмет из БД
        item = await session.get(FoundItem, item_id)
        if not item:
            print(f"❌ Предмет с ID {item_id} не найден")
            return
        
        # Парсим данные предмета
        item_data = json.loads(item.item_data_json)
        
        print(f"📦 Предмет: {item.item_name}")
        print(f"💰 Цена: ${item.price:.2f}")
        print(f"🔗 Listing ID: {item_data.get('listing_id', 'N/A')}")
        print(f"🎯 Float: {item_data.get('float_value', 'N/A')}")
        print(f"🎨 Паттерн: {item_data.get('pattern', 'N/A')}")
        
        # Анализируем наклейки
        stickers = item_data.get('stickers', [])
        total_price = item_data.get('total_stickers_price', 0.0)
        
        if not stickers:
            print("❌ Наклеек не найдено")
            return
        
        print(f"\n🏷️ Найдено наклеек: {len(stickers)}")
        print(f"💰 Общая цена наклеек: ${total_price:.2f}")
        
        print(f"\n📋 Детали наклеек:")
        calculated_total = 0.0
        
        for i, sticker in enumerate(stickers, 1):
            name = sticker.get('name', 'Unknown')
            price = sticker.get('price', 0.0)
            position = sticker.get('position', -1)
            wear = sticker.get('wear', '')
            
            calculated_total += price
            
            print(f"   {i}. {name}")
            print(f"      💰 Цена: ${price:.2f}")
            print(f"      📍 Позиция: {position + 1 if position >= 0 else 'N/A'}")
            if wear and wear != name:
                print(f"      🏷️ Wear: {wear}")
            print()
        
        # Проверяем правильность суммы
        print(f"🧮 Проверка суммы:")
        print(f"   Сохраненная общая цена: ${total_price:.2f}")
        print(f"   Рассчитанная сумма: ${calculated_total:.2f}")
        
        if abs(total_price - calculated_total) < 0.01:
            print("   ✅ Суммы совпадают")
        else:
            print("   ❌ Суммы НЕ совпадают!")
        
        # Генерируем ссылки для проверки
        print(f"\n🔗 Ссылки для проверки:")
        
        # 1. Steam Market ссылка
        if item.market_url:
            import urllib.parse
            encoded_name = urllib.parse.quote(item.market_url)
            steam_url = f"https://steamcommunity.com/market/listings/730/{encoded_name}"
            print(f"   📱 Steam Market: {steam_url}")
        
        # 2. Inspect ссылка
        inspect_links = item_data.get('inspect_links', [])
        if inspect_links:
            print(f"   🔍 Inspect in Game: {inspect_links[0]}")
        
        # 3. Внешние сервисы для проверки наклеек
        listing_id = item_data.get('listing_id')
        if listing_id:
            print(f"   🌐 CSFloat: https://csfloat.com/item/{listing_id}")
            print(f"   🌐 CS2 Float Checker: https://cs2floatchecker.com/")
        
        # 4. Проверка цен наклеек на Steam Market
        print(f"\n💰 Проверка цен наклеек на Steam Market:")
        unique_stickers = {}
        for sticker in stickers:
            name = sticker.get('name', '')
            price = sticker.get('price', 0.0)
            if name and name not in unique_stickers:
                unique_stickers[name] = price
        
        for sticker_name, our_price in unique_stickers.items():
            encoded_sticker = urllib.parse.quote(f"Sticker | {sticker_name}")
            sticker_url = f"https://steamcommunity.com/market/listings/730/Sticker%20%7C%20{encoded_sticker}"
            print(f"   🏷️ {sticker_name}: ${our_price:.2f}")
            print(f"      🔗 {sticker_url}")
        
        print(f"\n📋 Инструкции для проверки:")
        print(f"1. 📱 Откройте Steam Market ссылку и сравните наклейки визуально")
        print(f"2. 🔍 Используйте Inspect in Game для проверки float и паттерна")
        print(f"3. 🌐 Проверьте на CSFloat или CS2FloatChecker для подтверждения")
        print(f"4. 💰 Сравните цены наклеек на Steam Market")
        print(f"5. 🧮 Убедитесь, что общая сумма наклеек корректна")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await session.close()
        await db_manager.close()

async def find_recent_items_with_stickers():
    """Находит последние предметы с наклейками для проверки."""
    print("🔍 Поиск последних предметов с наклейками...")
    
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    session = await db_manager.get_session()
    
    try:
        from sqlalchemy import select, desc, text
        
        # Ищем предметы с наклейками (где total_stickers_price > 0)
        result = await session.execute(
            select(FoundItem)
            .where(text("item_data_json::jsonb->>'total_stickers_price' != '0'"))
            .order_by(desc(FoundItem.found_at))
            .limit(10)
        )
        items = list(result.scalars().all())
        
        if not items:
            print("❌ Предметы с наклейками не найдены")
            return
        
        print(f"✅ Найдено {len(items)} предметов с наклейками:")
        print()
        
        for item in items:
            try:
                item_data = json.loads(item.item_data_json)
                stickers_count = len(item_data.get('stickers', []))
                stickers_price = item_data.get('total_stickers_price', 0.0)
                
                print(f"📦 ID: {item.id} | {item.item_name}")
                print(f"   💰 Цена: ${item.price:.2f} | Наклеек: {stickers_count} (${stickers_price:.2f})")
                print(f"   📅 Найден: {item.found_at.strftime('%Y-%m-%d %H:%M:%S')}")
                print()
            except:
                continue
        
        print("💡 Для детальной проверки используйте:")
        print("   python3 scripts/verify_stickers_data.py <item_id>")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
    finally:
        await session.close()
        await db_manager.close()

async def main():
    """Главная функция."""
    if len(sys.argv) > 1:
        try:
            item_id = int(sys.argv[1])
            await verify_stickers_for_item(item_id)
        except ValueError:
            print("❌ Неверный ID предмета. Используйте: python3 verify_stickers_data.py <item_id>")
    else:
        await find_recent_items_with_stickers()

if __name__ == "__main__":
    asyncio.run(main())
