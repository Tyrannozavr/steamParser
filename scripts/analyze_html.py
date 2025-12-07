"""
Детальный анализ HTML страницы Steam Market для поиска float и паттерна.
"""
import json
import re
from bs4 import BeautifulSoup


def analyze_html():
    """Анализирует HTML и ищет все возможные места с float и паттерном."""
    with open('debug_page.html', 'r', encoding='utf-8') as f:
        html = f.read()
    
    soup = BeautifulSoup(html, 'lxml')
    scripts = soup.find_all('script')
    
    print("=" * 70)
    print("АНАЛИЗ HTML СТРАНИЦЫ STEAM MARKET")
    print("=" * 70)
    
    # 1. Ищем g_rgAssets
    print("\n1️⃣ Анализ g_rgAssets:")
    for script in scripts:
        if script.string and 'g_rgAssets' in script.string:
            match = re.search(r'var g_rgAssets = (\{.*?\});', script.string, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1))
                    if '730' in data:
                        for contextid, items in data['730'].items():
                            for itemid, item in list(items.items())[:1]:  # Первый предмет
                                print(f"  Предмет ID: {itemid}")
                                print(f"  Ключи в описаниях:")
                                if 'descriptions' in item:
                                    for desc in item['descriptions']:
                                        if desc.get('name'):
                                            print(f"    - {desc['name']}: {desc.get('value', '')[:100]}")
                                break
                            break
                except Exception as e:
                    print(f"  Ошибка парсинга: {e}")
                break
    
    # 2. Ищем все упоминания wear/float
    print("\n2️⃣ Поиск упоминаний 'wear' и 'float':")
    wear_patterns = [
        (r'"wear"\s*:\s*"?([0-9]+\.[0-9]+)', 'wear в JSON'),
        (r'wear\s*:\s*([0-9]+\.[0-9]+)', 'wear без кавычек'),
        (r'Float[^:]*:\s*([0-9]+\.[0-9]+)', 'Float в тексте'),
    ]
    
    for pattern, desc in wear_patterns:
        matches = re.findall(pattern, html, re.IGNORECASE)
        if matches:
            print(f"  {desc}: {matches[:3]}")
    
    # 3. Ищем paintseed/pattern
    print("\n3️⃣ Поиск упоминаний 'paintseed' и 'pattern':")
    pattern_patterns = [
        (r'"paintseed"\s*:\s*"?([0-9]+)', 'paintseed в JSON'),
        (r'paintseed\s*:\s*([0-9]+)', 'paintseed без кавычек'),
        (r'Pattern[^:]*:\s*([0-9]+)', 'Pattern в тексте'),
    ]
    
    for pattern, desc in pattern_patterns:
        matches = re.findall(pattern, html, re.IGNORECASE)
        if matches:
            print(f"  {desc}: {matches[:3]}")
    
    # 4. Ищем в JavaScript переменных
    print("\n4️⃣ Поиск в JavaScript переменных:")
    js_vars = ['g_rgItemInfo', 'rgItem', 'Market_LoadOrderSpread', 'iteminfo']
    for var_name in js_vars:
        for script in scripts:
            if script.string and var_name in script.string:
                # Ищем определение переменной
                pattern = rf'var\s+{var_name}\s*=\s*(\{{.*?\}});'
                match = re.search(pattern, script.string, re.DOTALL)
                if match:
                    try:
                        data = json.loads(match.group(1))
                        print(f"  {var_name} найден!")
                        print(f"    Ключи: {list(data.keys())[:10]}")
                        # Ищем wear/paintseed
                        if isinstance(data, dict):
                            for key in ['wear', 'float', 'paintseed', 'pattern']:
                                if key in data:
                                    print(f"    {key}: {data[key]}")
                    except:
                        pass
    
    # 5. Ищем в описаниях предметов (descriptions)
    print("\n5️⃣ Анализ descriptions в g_rgAssets:")
    for script in scripts:
        if script.string and 'g_rgAssets' in script.string:
            match = re.search(r'var g_rgAssets = (\{.*?\});', script.string, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1))
                    if '730' in data:
                        for contextid, items in data['730'].items():
                            for itemid, item in list(items.items())[:1]:
                                if 'descriptions' in item:
                                    print("  Описания предмета:")
                                    for desc in item['descriptions']:
                                        name = desc.get('name', '')
                                        value = desc.get('value', '')
                                        if 'wear' in name.lower() or 'float' in name.lower() or 'pattern' in name.lower() or 'paintseed' in name.lower():
                                            print(f"    {name}: {value}")
                                        elif value and ('0.' in value or re.search(r'\b[0-9]{1,5}\b', value)):
                                            # Проверяем, может это число
                                            nums = re.findall(r'\b([0-9]+\.[0-9]+|[0-9]{1,5})\b', value)
                                            if nums:
                                                print(f"    {name}: {value[:100]} (числа: {nums[:3]})")
                                break
                            break
                except Exception as e:
                    print(f"  Ошибка: {e}")
                break
    
    print("\n" + "=" * 70)


if __name__ == "__main__":
    analyze_html()

