#!/usr/bin/env python3
"""
Генерирует HTML отчет для проверки данных о наклейках.
"""
import asyncio
import sys
import json
from pathlib import Path
from datetime import datetime
import urllib.parse

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import Config, DatabaseManager, FoundItem

async def generate_verification_report(item_id: int):
    """Генерирует HTML отчет для проверки предмета."""
    
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    session = await db_manager.get_session()
    
    try:
        # Получаем предмет из БД
        item = await session.get(FoundItem, item_id)
        if not item:
            print(f"❌ Предмет с ID {item_id} не найден")
            return
        
        item_data = json.loads(item.item_data_json)
        
        # Генерируем HTML
        html_content = f"""
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Проверка предмета #{item_id}</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        .container {{
            background: white;
            border-radius: 10px;
            padding: 30px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        .header {{
            text-align: center;
            margin-bottom: 30px;
            padding-bottom: 20px;
            border-bottom: 2px solid #eee;
        }}
        .item-info {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-bottom: 30px;
        }}
        .info-card {{
            background: #f8f9fa;
            padding: 20px;
            border-radius: 8px;
            border-left: 4px solid #007bff;
        }}
        .stickers-section {{
            margin-bottom: 30px;
        }}
        .sticker-card {{
            background: #fff3cd;
            border: 1px solid #ffeaa7;
            border-radius: 8px;
            padding: 15px;
            margin-bottom: 10px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .verification-links {{
            background: #e7f3ff;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
        }}
        .link-button {{
            display: inline-block;
            background: #007bff;
            color: white;
            padding: 10px 20px;
            text-decoration: none;
            border-radius: 5px;
            margin: 5px;
            transition: background 0.3s;
        }}
        .link-button:hover {{
            background: #0056b3;
        }}
        .steam-button {{ background: #1b2838; }}
        .csfloat-button {{ background: #ff6b35; }}
        .inspect-button {{ background: #4CAF50; }}
        .market-button {{ background: #f39c12; }}
        .checklist {{
            background: #d4edda;
            border: 1px solid #c3e6cb;
            border-radius: 8px;
            padding: 20px;
        }}
        .checklist ul {{
            list-style-type: none;
            padding: 0;
        }}
        .checklist li {{
            padding: 8px 0;
            border-bottom: 1px solid #c3e6cb;
        }}
        .checklist li:before {{
            content: "☐ ";
            font-size: 18px;
            margin-right: 10px;
        }}
        .price-highlight {{
            font-size: 1.2em;
            font-weight: bold;
            color: #28a745;
        }}
        .float-pattern {{
            font-family: 'Courier New', monospace;
            background: #f8f9fa;
            padding: 5px 10px;
            border-radius: 4px;
        }}
        @media (max-width: 768px) {{
            .item-info {{
                grid-template-columns: 1fr;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🔍 Проверка предмета #{item_id}</h1>
            <p>Сгенерировано: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </div>
        
        <div class="item-info">
            <div class="info-card">
                <h3>📦 Основная информация</h3>
                <p><strong>Название:</strong> {item.item_name}</p>
                <p><strong>Цена:</strong> <span class="price-highlight">${item.price:.2f}</span></p>
                <p><strong>Listing ID:</strong> {item_data.get('listing_id', 'N/A')}</p>
                <p><strong>Найден:</strong> {item.found_at.strftime('%Y-%m-%d %H:%M:%S')}</p>
            </div>
            
            <div class="info-card">
                <h3>🎯 Технические данные</h3>
                <p><strong>Float:</strong> <span class="float-pattern">{item_data.get('float_value', 'N/A')}</span></p>
                <p><strong>Паттерн:</strong> <span class="float-pattern">{item_data.get('pattern', 'N/A')}</span></p>
                <p><strong>StatTrak:</strong> {'✅ Да' if item_data.get('is_stattrak') else '❌ Нет'}</p>
                <p><strong>Тип:</strong> {item_data.get('item_type', 'N/A')}</p>
            </div>
        </div>
        """
        
        # Добавляем информацию о наклейках
        stickers = item_data.get('stickers', [])
        total_price = item_data.get('total_stickers_price', 0.0)
        
        if stickers:
            html_content += f"""
        <div class="stickers-section">
            <h3>🏷️ Наклейки ({len(stickers)} шт.)</h3>
            <p><strong>Общая цена:</strong> <span class="price-highlight">${total_price:.2f}</span></p>
            """
            
            for i, sticker in enumerate(stickers, 1):
                name = sticker.get('name', 'Unknown')
                price = sticker.get('price', 0.0)
                position = sticker.get('position', -1)
                
                html_content += f"""
            <div class="sticker-card">
                <div>
                    <strong>{i}. {name}</strong><br>
                    <small>Позиция: Slot {position + 1 if position >= 0 else 'N/A'}</small>
                </div>
                <div class="price-highlight">${price:.2f}</div>
            </div>
                """
            
            html_content += "</div>"
        
        # Добавляем ссылки для проверки
        html_content += """
        <div class="verification-links">
            <h3>🔗 Ссылки для проверки</h3>
            <div>
        """
        
        # Steam Market ссылка
        if item.market_url:
            encoded_name = urllib.parse.quote(item.market_url)
            steam_url = f"https://steamcommunity.com/market/listings/730/{encoded_name}"
            html_content += f'<a href="{steam_url}" target="_blank" class="link-button steam-button">📱 Steam Market</a>'
        
        # Inspect ссылка
        inspect_links = item_data.get('inspect_links', [])
        if inspect_links:
            html_content += f'<a href="{inspect_links[0]}" class="link-button inspect-button">🔍 Inspect in Game</a>'
        
        # Внешние сервисы
        listing_id = item_data.get('listing_id')
        if listing_id:
            html_content += f'<a href="https://csfloat.com/item/{listing_id}" target="_blank" class="link-button csfloat-button">🌐 CSFloat</a>'
            html_content += f'<a href="https://cs2floatchecker.com/" target="_blank" class="link-button csfloat-button">🌐 CS2 Float Checker</a>'
        
        html_content += """
            </div>
        </div>
        """
        
        # Добавляем ссылки на наклейки
        if stickers:
            html_content += """
        <div class="verification-links">
            <h3>💰 Проверка цен наклеек</h3>
            <div>
            """
            
            unique_stickers = {}
            for sticker in stickers:
                name = sticker.get('name', '')
                price = sticker.get('price', 0.0)
                if name and name not in unique_stickers:
                    unique_stickers[name] = price
            
            for sticker_name, our_price in unique_stickers.items():
                encoded_sticker = urllib.parse.quote(f"Sticker | {sticker_name}")
                sticker_url = f"https://steamcommunity.com/market/listings/730/Sticker%20%7C%20{encoded_sticker}"
                html_content += f'<a href="{sticker_url}" target="_blank" class="link-button market-button">🏷️ {sticker_name} (${our_price:.2f})</a><br>'
            
            html_content += """
            </div>
        </div>
            """
        
        # Добавляем чек-лист для проверки
        html_content += f"""
        <div class="checklist">
            <h3>📋 Чек-лист для проверки</h3>
            <ul>
                <li>Откройте Steam Market и сравните название предмета</li>
                <li>Проверьте цену предмета (должна быть ${item.price:.2f})</li>
                <li>Используйте Inspect in Game для проверки float ({item_data.get('float_value', 'N/A')})</li>
                <li>Проверьте паттерн через inspect ({item_data.get('pattern', 'N/A')})</li>
                <li>Сравните количество наклеек ({len(stickers)} шт.)</li>
                <li>Проверьте цены наклеек на Steam Market</li>
                <li>Убедитесь, что общая сумма наклеек корректна (${total_price:.2f})</li>
                <li>Проверьте данные на CSFloat или CS2FloatChecker</li>
            </ul>
        </div>
        
        <div style="text-align: center; margin-top: 30px; color: #666;">
            <p>Этот отчет сгенерирован автоматически системой мониторинга Steam Market</p>
        </div>
    </div>
</body>
</html>
        """
        
        # Сохраняем HTML файл
        report_path = Path(__file__).parent.parent / "reports" / f"verification_item_{item_id}.html"
        report_path.parent.mkdir(exist_ok=True)
        
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        print(f"✅ HTML отчет сгенерирован: {report_path}")
        print(f"🌐 Откройте файл в браузере для проверки")
        
        return str(report_path)
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await session.close()
        await db_manager.close()

async def main():
    """Главная функция."""
    if len(sys.argv) > 1:
        try:
            item_id = int(sys.argv[1])
            await generate_verification_report(item_id)
        except ValueError:
            print("❌ Неверный ID предмета. Используйте: python3 generate_verification_report.py <item_id>")
    else:
        print("💡 Использование: python3 generate_verification_report.py <item_id>")

if __name__ == "__main__":
    asyncio.run(main())
