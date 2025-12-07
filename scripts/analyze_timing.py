#!/usr/bin/env python3
"""
Скрипт для анализа времени выполнения этапов мониторинга Steam Market.
Анализирует логи и показывает время каждого этапа от добавления задачи до отправки уведомления.
"""
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import json

@dataclass
class TimingEvent:
    """Событие с временной меткой."""
    timestamp: datetime
    event_type: str
    task_id: Optional[int]
    item_id: Optional[int]
    details: str
    log_file: str

class TimingAnalyzer:
    """Анализатор времени выполнения этапов."""
    
    def __init__(self, logs_dir: Path):
        self.logs_dir = logs_dir
        self.events: List[TimingEvent] = []
        
        # Паттерны для извлечения событий из логов
        self.patterns = {
            # Создание задачи в Telegram боте
            'task_created': re.compile(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*Добавлена задача мониторинга:.*\(ID: (\d+)\)'),
            
            # Запуск мониторинга задачи
            'monitoring_started': re.compile(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*Запущен мониторинг для задачи:.*\(ID: (\d+)\)'),
            
            # Публикация задачи в Redis
            'task_published': re.compile(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*Задача (\d+): Публикуем задачу в Redis канал'),
            
            # Получение задачи Parsing Worker
            'task_received': re.compile(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*ParsingWorker: Получена задача парсинга: task_id=(\d+)'),
            
            # Начало парсинга
            'parsing_started': re.compile(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*Выполняем парсинг для задачи (\d+):'),
            
            # Результат парсинга
            'parsing_completed': re.compile(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*Результат парсинга для задачи (\d+):.*success=(\w+).*items=(\d+)'),
            
            # Сохранение предмета
            'item_saved': re.compile(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*Предмет добавлен для сохранения:.*\(\$[\d.]+\)'),
            
            # Публикация уведомления в Redis
            'notification_published': re.compile(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*ParsingWorker: Публикуем уведомление для предмета (\d+)'),
            
            # Получение уведомления Telegram ботом
            'notification_received': re.compile(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*TelegramBot: Получено сообщение из Redis.*found_item'),
            
            # Отправка уведомления в Telegram
            'notification_sent': re.compile(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*TelegramBot.*Уведомление успешно отправлено для предмета.*\(ID: (\d+)\)'),
        }
    
    def parse_logs(self, date_filter: Optional[str] = None):
        """Парсит логи и извлекает события."""
        log_files = []
        
        if date_filter:
            # Ищем логи за конкретную дату
            for pattern in ['telegram_bot_*.log', 'parsing_worker_*.log', 'steam_monitor_*.log']:
                log_files.extend(self.logs_dir.glob(pattern.replace('*', f'*{date_filter}*')))
        else:
            # Берем все логи
            for pattern in ['telegram_bot_*.log', 'parsing_worker_*.log', 'steam_monitor_*.log']:
                log_files.extend(self.logs_dir.glob(pattern))
        
        print(f"📁 Анализируем {len(log_files)} файлов логов...")
        
        for log_file in sorted(log_files):
            print(f"   📄 Обрабатываем: {log_file.name}")
            self._parse_log_file(log_file)
        
        # Сортируем события по времени
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
                                
                                # Извлекаем task_id и item_id в зависимости от типа события
                                task_id = None
                                item_id = None
                                
                                if event_type in ['task_created', 'monitoring_started', 'task_published', 
                                                'task_received', 'parsing_started', 'parsing_completed']:
                                    task_id = int(match.group(2))
                                elif event_type in ['notification_published', 'notification_sent']:
                                    item_id = int(match.group(2))
                                
                                event = TimingEvent(
                                    timestamp=timestamp,
                                    event_type=event_type,
                                    task_id=task_id,
                                    item_id=item_id,
                                    details=line.strip(),
                                    log_file=log_file.name
                                )
                                self.events.append(event)
                            except (ValueError, IndexError) as e:
                                print(f"⚠️ Ошибка парсинга строки {line_num} в {log_file.name}: {e}")
                                continue
        except Exception as e:
            print(f"❌ Ошибка чтения файла {log_file}: {e}")
    
    def analyze_task_timing(self, task_id: int) -> Dict[str, any]:
        """Анализирует время выполнения для конкретной задачи."""
        task_events = [e for e in self.events if e.task_id == task_id]
        
        if not task_events:
            return {"error": f"События для задачи {task_id} не найдены"}
        
        # Группируем события по типам
        events_by_type = {}
        for event in task_events:
            if event.event_type not in events_by_type:
                events_by_type[event.event_type] = []
            events_by_type[event.event_type].append(event)
        
        # Находим ключевые моменты времени
        timeline = {}
        
        if 'task_created' in events_by_type:
            timeline['task_created'] = events_by_type['task_created'][0].timestamp
        
        if 'monitoring_started' in events_by_type:
            timeline['monitoring_started'] = events_by_type['monitoring_started'][0].timestamp
        
        if 'task_published' in events_by_type:
            timeline['task_published'] = events_by_type['task_published'][-1].timestamp  # Последняя публикация
        
        if 'task_received' in events_by_type:
            timeline['task_received'] = events_by_type['task_received'][-1].timestamp
        
        if 'parsing_started' in events_by_type:
            timeline['parsing_started'] = events_by_type['parsing_started'][-1].timestamp
        
        if 'parsing_completed' in events_by_type:
            timeline['parsing_completed'] = events_by_type['parsing_completed'][-1].timestamp
        
        # Вычисляем интервалы
        intervals = {}
        timeline_keys = list(timeline.keys())
        
        for i in range(len(timeline_keys) - 1):
            current_key = timeline_keys[i]
            next_key = timeline_keys[i + 1]
            interval = timeline[next_key] - timeline[current_key]
            intervals[f"{current_key}_to_{next_key}"] = interval.total_seconds()
        
        return {
            "task_id": task_id,
            "timeline": timeline,
            "intervals": intervals,
            "events_count": len(task_events),
            "total_time": (max(timeline.values()) - min(timeline.values())).total_seconds() if timeline else 0
        }
    
    def analyze_recent_activity(self, hours: int = 24) -> Dict[str, any]:
        """Анализирует активность за последние N часов."""
        cutoff_time = datetime.now() - timedelta(hours=hours)
        recent_events = [e for e in self.events if e.timestamp >= cutoff_time]
        
        if not recent_events:
            return {"message": f"Событий за последние {hours} часов не найдено"}
        
        # Группируем по задачам
        tasks = {}
        for event in recent_events:
            if event.task_id:
                if event.task_id not in tasks:
                    tasks[event.task_id] = []
                tasks[event.task_id].append(event)
        
        # Анализируем каждую задачу
        results = {}
        for task_id, task_events in tasks.items():
            results[task_id] = self.analyze_task_timing(task_id)
        
        return {
            "period_hours": hours,
            "total_events": len(recent_events),
            "tasks_analyzed": len(tasks),
            "tasks": results
        }
    
    def print_task_analysis(self, task_id: int):
        """Выводит детальный анализ времени для задачи."""
        analysis = self.analyze_task_timing(task_id)
        
        if "error" in analysis:
            print(f"❌ {analysis['error']}")
            return
        
        print(f"\n📊 Анализ времени выполнения для задачи #{task_id}")
        print("=" * 60)
        
        timeline = analysis['timeline']
        intervals = analysis['intervals']
        
        print(f"📅 Временная шкала:")
        for stage, timestamp in timeline.items():
            print(f"   {stage:20} | {timestamp.strftime('%H:%M:%S.%f')[:-3]}")
        
        print(f"\n⏱️ Интервалы между этапами:")
        for interval_name, seconds in intervals.items():
            stages = interval_name.replace('_to_', ' → ')
            print(f"   {stages:40} | {seconds:8.3f} сек")
        
        print(f"\n📈 Общая статистика:")
        print(f"   Всего событий: {analysis['events_count']}")
        print(f"   Общее время:   {analysis['total_time']:.3f} сек")
        
        # Показываем самые медленные этапы
        if intervals:
            slowest = max(intervals.items(), key=lambda x: x[1])
            print(f"   Самый медленный этап: {slowest[0].replace('_to_', ' → ')} ({slowest[1]:.3f} сек)")

def main():
    """Главная функция."""
    logs_dir = Path(__file__).parent.parent / "logs"
    
    if not logs_dir.exists():
        print(f"❌ Директория логов не найдена: {logs_dir}")
        return
    
    analyzer = TimingAnalyzer(logs_dir)
    
    # Парсим логи за сегодня
    today = datetime.now().strftime('%Y-%m-%d')
    print(f"🔍 Анализируем логи за {today}...")
    analyzer.parse_logs(date_filter=today)
    
    if len(sys.argv) > 1:
        # Анализируем конкретную задачу
        try:
            task_id = int(sys.argv[1])
            analyzer.print_task_analysis(task_id)
        except ValueError:
            print("❌ Неверный ID задачи. Используйте: python analyze_timing.py <task_id>")
    else:
        # Показываем общую активность
        print("\n📊 Анализ активности за последние 24 часа:")
        recent = analyzer.analyze_recent_activity(24)
        
        if "message" in recent:
            print(f"ℹ️ {recent['message']}")
        else:
            print(f"📈 Всего событий: {recent['total_events']}")
            print(f"📋 Задач проанализировано: {recent['tasks_analyzed']}")
            
            for task_id, task_analysis in recent['tasks'].items():
                if "error" not in task_analysis:
                    print(f"\n🎯 Задача #{task_id}:")
                    print(f"   Общее время: {task_analysis['total_time']:.3f} сек")
                    print(f"   Событий: {task_analysis['events_count']}")
        
        print(f"\n💡 Для детального анализа конкретной задачи используйте:")
        print(f"   python analyze_timing.py <task_id>")

if __name__ == "__main__":
    main()
