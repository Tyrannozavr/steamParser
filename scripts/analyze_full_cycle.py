#!/usr/bin/env python3
"""
Скрипт для анализа полного цикла: от добавления задачи до отправки уведомления.
Показывает время каждого этапа и находит связанные уведомления.
"""
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import json

@dataclass
class Event:
    """Событие с временной меткой."""
    timestamp: datetime
    event_type: str
    task_id: Optional[int]
    item_id: Optional[int]
    details: str
    log_file: str

class FullCycleAnalyzer:
    """Анализатор полного цикла мониторинга."""
    
    def __init__(self, logs_dir: Path):
        self.logs_dir = logs_dir
        self.events: List[Event] = []
        
        # Расширенные паттерны для полного цикла
        self.patterns = {
            # 1. Создание задачи через Telegram
            'task_created': re.compile(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*✅ Задача создана.*ID: #(\d+)'),
            'task_added_to_monitoring': re.compile(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*Добавлена задача мониторинга:.*\(ID: (\d+)\)'),
            
            # 2. Запуск мониторинга
            'monitoring_started': re.compile(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*🚀 Запущен мониторинг для задачи:.*\(ID: (\d+)\)'),
            'first_check_scheduled': re.compile(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*Задача (\d+): Первая проверка будет выполнена сразу'),
            
            # 3. Цикл проверки
            'check_started': re.compile(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*Задача (\d+): Начинаем проверку'),
            'task_published_redis': re.compile(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*Задача (\d+): Публикуем задачу в Redis канал'),
            'task_published_success': re.compile(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*Задача (\d+): Успешно опубликована в Redis'),
            
            # 4. Обработка в Parsing Worker
            'task_received_worker': re.compile(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*ParsingWorker: Получена задача парсинга: task_id=(\d+)'),
            'parsing_started': re.compile(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*🔍 Выполняем парсинг для задачи (\d+):'),
            'parsing_completed': re.compile(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*📊 Результат парсинга для задачи (\d+):.*success=(\w+).*items=(\d+)'),
            
            # 5. Сохранение найденных предметов
            'item_found': re.compile(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*✅ Предмет добавлен для сохранения:.*\(\$[\d.]+\)'),
            'items_saved': re.compile(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*✅ Сохранено (\d+) предметов для задачи (\d+)'),
            
            # 6. Публикация уведомлений
            'notification_publishing': re.compile(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*📤 ParsingWorker: Публикуем (\d+) уведомлений в Redis'),
            'notification_published': re.compile(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*📤 ParsingWorker: Публикуем уведомление для предмета (\d+)'),
            'notification_published_success': re.compile(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*✅ ParsingWorker: Уведомление для предмета (\d+) опубликовано'),
            
            # 7. Получение и обработка уведомлений в Telegram боте
            'notification_received_bot': re.compile(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*📥 TelegramBot: Получено сообщение из Redis.*found_item'),
            'notification_processing': re.compile(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*🔔 TelegramBot: Обрабатываем уведомление о найденном предмете: item_id=(\d+)'),
            'notification_sending': re.compile(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*📤 TelegramBot: Отправляем уведомление в Telegram'),
            'notification_sent': re.compile(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*✅ TelegramBot.*Уведомление успешно отправлено для предмета.*\(ID: (\d+)\)'),
            
            # 8. Обновление статистики
            'stats_updated': re.compile(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*📊 Статистика задачи (\d+) обновлена.*найдено=(\d+)'),
        }
    
    def parse_logs(self, date_filter: Optional[str] = None):
        """Парсит логи и извлекает события."""
        log_files = []
        
        if date_filter:
            for pattern in ['telegram_bot_*.log', 'parsing_worker_*.log', 'steam_monitor_*.log']:
                log_files.extend(self.logs_dir.glob(pattern.replace('*', f'*{date_filter}*')))
        else:
            for pattern in ['telegram_bot_*.log', 'parsing_worker_*.log', 'steam_monitor_*.log']:
                log_files.extend(self.logs_dir.glob(pattern))
        
        print(f"📁 Анализируем {len(log_files)} файлов логов...")
        
        for log_file in sorted(log_files):
            print(f"   📄 {log_file.name}")
            self._parse_log_file(log_file)
        
        self.events.sort(key=lambda e: e.timestamp)
        print(f"✅ Найдено {len(self.events)} событий")
    
    def _parse_log_file(self, log_file: Path):
        """Парсит один файл лога."""
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    for event_type, pattern in self.patterns.items():
                        match = pattern.search(line)
                        if match:
                            try:
                                timestamp = datetime.strptime(match.group(1), '%Y-%m-%d %H:%M:%S')
                                
                                # Извлекаем ID в зависимости от типа события
                                task_id = None
                                item_id = None
                                
                                if event_type in ['task_created', 'task_added_to_monitoring', 'monitoring_started', 
                                                'first_check_scheduled', 'check_started', 'task_published_redis',
                                                'task_published_success', 'task_received_worker', 'parsing_started',
                                                'parsing_completed', 'items_saved', 'stats_updated']:
                                    task_id = int(match.group(2))
                                elif event_type in ['notification_published', 'notification_published_success',
                                                  'notification_processing', 'notification_sent']:
                                    item_id = int(match.group(2))
                                
                                event = Event(
                                    timestamp=timestamp,
                                    event_type=event_type,
                                    task_id=task_id,
                                    item_id=item_id,
                                    details=line.strip(),
                                    log_file=log_file.name
                                )
                                self.events.append(event)
                            except (ValueError, IndexError) as e:
                                continue
        except Exception as e:
            print(f"❌ Ошибка чтения {log_file}: {e}")
    
    def analyze_full_cycle(self, task_id: int) -> Dict:
        """Анализирует полный цикл для задачи."""
        task_events = [e for e in self.events if e.task_id == task_id]
        
        if not task_events:
            return {"error": f"События для задачи {task_id} не найдены"}
        
        # Группируем события по типам
        events_by_type = {}
        for event in task_events:
            if event.event_type not in events_by_type:
                events_by_type[event.event_type] = []
            events_by_type[event.event_type].append(event)
        
        # Строим временную шкалу
        timeline = {}
        
        # Этап 1: Создание задачи
        if 'task_created' in events_by_type:
            timeline['1_task_created'] = events_by_type['task_created'][0].timestamp
        elif 'task_added_to_monitoring' in events_by_type:
            timeline['1_task_created'] = events_by_type['task_added_to_monitoring'][0].timestamp
        
        # Этап 2: Запуск мониторинга
        if 'monitoring_started' in events_by_type:
            timeline['2_monitoring_started'] = events_by_type['monitoring_started'][0].timestamp
        
        # Этап 3: Первая проверка
        if 'check_started' in events_by_type:
            timeline['3_first_check'] = events_by_type['check_started'][0].timestamp
        
        # Этап 4: Публикация в Redis
        if 'task_published_success' in events_by_type:
            timeline['4_redis_published'] = events_by_type['task_published_success'][0].timestamp
        
        # Этап 5: Получение воркером
        if 'task_received_worker' in events_by_type:
            timeline['5_worker_received'] = events_by_type['task_received_worker'][0].timestamp
        
        # Этап 6: Начало парсинга
        if 'parsing_started' in events_by_type:
            timeline['6_parsing_started'] = events_by_type['parsing_started'][0].timestamp
        
        # Этап 7: Завершение парсинга
        if 'parsing_completed' in events_by_type:
            timeline['7_parsing_completed'] = events_by_type['parsing_completed'][0].timestamp
        
        # Этап 8: Сохранение предметов (если найдены)
        if 'items_saved' in events_by_type:
            timeline['8_items_saved'] = events_by_type['items_saved'][0].timestamp
        
        # Этап 9: Публикация уведомлений (если есть предметы)
        if 'notification_published_success' in events_by_type:
            timeline['9_notifications_published'] = events_by_type['notification_published_success'][0].timestamp
        
        # Этап 10: Отправка уведомлений (если есть предметы)
        # Ищем связанные уведомления по времени
        notification_events = [e for e in self.events if e.event_type == 'notification_sent']
        if notification_events and timeline:
            # Ищем уведомления, отправленные после создания задачи
            task_start = min(timeline.values())
            related_notifications = [e for e in notification_events if e.timestamp >= task_start]
            if related_notifications:
                timeline['10_notification_sent'] = related_notifications[0].timestamp
        
        # Вычисляем интервалы
        intervals = {}
        timeline_keys = sorted(timeline.keys())
        
        for i in range(len(timeline_keys) - 1):
            current_key = timeline_keys[i]
            next_key = timeline_keys[i + 1]
            interval = timeline[next_key] - timeline[current_key]
            intervals[f"{current_key}_to_{next_key}"] = interval.total_seconds()
        
        return {
            "task_id": task_id,
            "timeline": timeline,
            "intervals": intervals,
            "events_by_type": {k: len(v) for k, v in events_by_type.items()},
            "total_events": len(task_events),
            "total_time": (max(timeline.values()) - min(timeline.values())).total_seconds() if timeline else 0
        }
    
    def print_full_cycle_analysis(self, task_id: int):
        """Выводит детальный анализ полного цикла."""
        analysis = self.analyze_full_cycle(task_id)
        
        if "error" in analysis:
            print(f"❌ {analysis['error']}")
            return
        
        print(f"\n🔄 Полный цикл мониторинга для задачи #{task_id}")
        print("=" * 80)
        
        timeline = analysis['timeline']
        intervals = analysis['intervals']
        
        # Временная шкала с описаниями этапов
        stage_descriptions = {
            '1_task_created': '1️⃣ Создание задачи через Telegram',
            '2_monitoring_started': '2️⃣ Запуск мониторинга',
            '3_first_check': '3️⃣ Первая проверка',
            '4_redis_published': '4️⃣ Публикация в Redis',
            '5_worker_received': '5️⃣ Получение воркером',
            '6_parsing_started': '6️⃣ Начало парсинга',
            '7_parsing_completed': '7️⃣ Завершение парсинга',
            '8_items_saved': '8️⃣ Сохранение предметов',
            '9_notifications_published': '9️⃣ Публикация уведомлений',
            '10_notification_sent': '🔟 Отправка в Telegram'
        }
        
        print(f"📅 Временная шкала:")
        for stage in sorted(timeline.keys()):
            timestamp = timeline[stage]
            description = stage_descriptions.get(stage, stage)
            print(f"   {description:35} | {timestamp.strftime('%H:%M:%S.%f')[:-3]}")
        
        print(f"\n⏱️ Время между этапами:")
        for interval_name, seconds in intervals.items():
            parts = interval_name.split('_to_')
            if len(parts) == 2:
                from_desc = stage_descriptions.get(parts[0], parts[0])
                to_desc = stage_descriptions.get(parts[1], parts[1])
                print(f"   {from_desc} → {to_desc}")
                print(f"   {'':35} | {seconds:8.3f} сек")
        
        print(f"\n📊 Статистика:")
        print(f"   Всего событий: {analysis['total_events']}")
        print(f"   Общее время:   {analysis['total_time']:.3f} сек ({analysis['total_time']/60:.1f} мин)")
        
        # Показываем события по типам
        print(f"\n📋 События по типам:")
        for event_type, count in analysis['events_by_type'].items():
            print(f"   {event_type:25} | {count:3d}")
        
        # Самые медленные этапы
        if intervals:
            sorted_intervals = sorted(intervals.items(), key=lambda x: x[1], reverse=True)
            print(f"\n🐌 Самые медленные этапы:")
            for i, (interval_name, seconds) in enumerate(sorted_intervals[:3]):
                parts = interval_name.split('_to_')
                if len(parts) == 2:
                    from_desc = stage_descriptions.get(parts[0], parts[0])
                    to_desc = stage_descriptions.get(parts[1], parts[1])
                    print(f"   {i+1}. {from_desc} → {to_desc}")
                    print(f"      {seconds:.3f} сек ({seconds/60:.1f} мин)")

def main():
    """Главная функция."""
    logs_dir = Path(__file__).parent.parent / "logs"
    
    if not logs_dir.exists():
        print(f"❌ Директория логов не найдена: {logs_dir}")
        return
    
    analyzer = FullCycleAnalyzer(logs_dir)
    
    # Парсим логи за сегодня
    today = datetime.now().strftime('%Y-%m-%d')
    print(f"🔍 Анализируем полный цикл за {today}...")
    analyzer.parse_logs(date_filter=today)
    
    if len(sys.argv) > 1:
        try:
            task_id = int(sys.argv[1])
            analyzer.print_full_cycle_analysis(task_id)
        except ValueError:
            print("❌ Неверный ID задачи. Используйте: python analyze_full_cycle.py <task_id>")
    else:
        print("\n💡 Для анализа полного цикла конкретной задачи используйте:")
        print("   python3 analyze_full_cycle.py <task_id>")
        
        # Показываем доступные задачи
        task_events = {}
        for event in analyzer.events:
            if event.task_id:
                if event.task_id not in task_events:
                    task_events[event.task_id] = 0
                task_events[event.task_id] += 1
        
        if task_events:
            print(f"\n📋 Доступные задачи за сегодня:")
            for task_id, event_count in sorted(task_events.items()):
                print(f"   Задача #{task_id}: {event_count} событий")

if __name__ == "__main__":
    main()
