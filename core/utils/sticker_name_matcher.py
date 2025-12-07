"""
Утилита для гибкого сопоставления названий наклеек.
Помогает находить совпадения даже при небольших различиях в названиях.
"""
import re
from typing import Optional, Dict, List, Tuple


def normalize_sticker_name(name: str) -> str:
    """
    Нормализует название наклейки для сравнения.
    Убирает лишние пробелы, приводит к нижнему регистру, удаляет специальные символы.
    
    Примеры:
        "Crown (Foil)" -> "crown foil"
        "Team EnVyUs | Cluj-Napoca 2015" -> "team envyus cluj napoca 2015"
        "MOUZ | Austin 2025" -> "mouz austin 2025"
    """
    if not name:
        return ""
    
    # Приводим к нижнему регистру
    normalized = name.lower()
    
    # Убираем специальные символы, оставляем только буквы, цифры и пробелы
    normalized = re.sub(r'[^\w\s]', ' ', normalized)
    
    # Заменяем множественные пробелы на один
    normalized = re.sub(r'\s+', ' ', normalized)
    
    # Убираем пробелы в начале и конце
    normalized = normalized.strip()
    
    return normalized


def calculate_similarity(name1: str, name2: str) -> float:
    """
    Вычисляет схожесть двух названий (0.0 - 1.0).
    Использует простое сравнение слов.
    
    Args:
        name1: Первое название
        name2: Второе название
        
    Returns:
        Коэффициент схожести от 0.0 до 1.0
    """
    if not name1 or not name2:
        return 0.0
    
    # Нормализуем оба названия
    norm1 = normalize_sticker_name(name1)
    norm2 = normalize_sticker_name(name2)
    
    # Точное совпадение
    if norm1 == norm2:
        return 1.0
    
    # Разбиваем на слова
    words1 = set(norm1.split())
    words2 = set(norm2.split())
    
    if not words1 or not words2:
        return 0.0
    
    # Вычисляем коэффициент Жаккара (пересечение / объединение)
    intersection = len(words1 & words2)
    union = len(words1 | words2)
    
    if union == 0:
        return 0.0
    
    jaccard = intersection / union
    
    # Дополнительная проверка: если одно название содержит другое
    if norm1 in norm2 or norm2 in norm1:
        jaccard = max(jaccard, 0.8)
    
    return jaccard


def find_best_match(
    requested_name: str,
    available_names: Dict[str, any],
    min_similarity: float = 0.7
) -> Optional[Tuple[str, float]]:
    """
    Находит лучшее совпадение для запрошенного названия среди доступных.
    
    Args:
        requested_name: Запрошенное название наклейки
        available_names: Словарь {название: значение} доступных названий
        min_similarity: Минимальный коэффициент схожести (по умолчанию 0.7)
        
    Returns:
        Кортеж (найденное_название, коэффициент_схожести) или None
        
    Примеры:
        Запрошено: "Crown (Foil)"
        Доступно: {"Crown Foil": 540.50, "Crown (Foil)": 540.50}
        Результат: ("Crown (Foil)", 1.0) - точное совпадение
        
        Запрошено: "Team EnVyUs | Cluj-Napoca 2015"
        Доступно: {"Team EnVyUs Cluj-Napoca 2015": 2.5}
        Результат: ("Team EnVyUs Cluj-Napoca 2015", 0.95) - почти точное совпадение
    """
    if not requested_name or not available_names:
        return None
    
    # Сначала проверяем точное совпадение (регистронезависимо)
    requested_normalized = normalize_sticker_name(requested_name)
    for available_name, value in available_names.items():
        if normalize_sticker_name(available_name) == requested_normalized:
            return (available_name, 1.0)
    
    # Если точного совпадения нет, ищем наиболее похожее
    best_match = None
    best_similarity = 0.0
    
    for available_name, value in available_names.items():
        similarity = calculate_similarity(requested_name, available_name)
        if similarity > best_similarity and similarity >= min_similarity:
            best_similarity = similarity
            best_match = available_name
    
    if best_match:
        return (best_match, best_similarity)
    
    return None


# Примеры использования для тестирования
if __name__ == "__main__":
    # Пример 1: Точное совпадение
    print("Пример 1: Точное совпадение")
    requested = "Crown (Foil)"
    available = {"Crown (Foil)": 540.50, "Crown Foil": 540.50}
    match = find_best_match(requested, available)
    print(f"  Запрошено: '{requested}'")
    print(f"  Доступно: {list(available.keys())}")
    print(f"  Найдено: {match}")
    print()
    
    # Пример 2: Различие в скобках
    print("Пример 2: Различие в скобках")
    requested = "Team EnVyUs | Cluj-Napoca 2015"
    available = {"Team EnVyUs Cluj-Napoca 2015": 2.5, "Team EnVyUs | Cluj-Napoca 2015": 2.5}
    match = find_best_match(requested, available)
    print(f"  Запрошено: '{requested}'")
    print(f"  Доступно: {list(available.keys())}")
    print(f"  Найдено: {match}")
    print()
    
    # Пример 3: Различие в регистре и пробелах
    print("Пример 3: Различие в регистре и пробелах")
    requested = "MOUZ | Austin 2025"
    available = {"mouz austin 2025": 0.03, "MOUZ Austin 2025": 0.03}
    match = find_best_match(requested, available)
    print(f"  Запрошено: '{requested}'")
    print(f"  Доступно: {list(available.keys())}")
    print(f"  Найдено: {match}")
    print()
    
    # Пример 4: Нет совпадения
    print("Пример 4: Нет совпадения")
    requested = "Some Unknown Sticker"
    available = {"Crown (Foil)": 540.50, "Bosh (Holo)": 3.94}
    match = find_best_match(requested, available)
    print(f"  Запрошено: '{requested}'")
    print(f"  Доступно: {list(available.keys())}")
    print(f"  Найдено: {match}")





