"""
Модуль с методами работы с Steam Market API.
Вынесено из steam_parser.py для улучшения структуры кода.
"""
import asyncio
import json
from typing import Optional, Dict, Any, List, Tuple
from urllib.parse import quote
from loguru import logger
import httpx


class SteamAPIMethods:
    """Миксин с методами работы с Steam Market API."""
    
    # URL для поиска вариантов предметов
    SEARCH_SUGGESTIONS_URL = "https://steamcommunity.com/market/searchsuggestionsresults"
    
    async def get_item_variants(self, item_name: str) -> List[Dict[str, Any]]:
        """
        Получает все варианты предмета (разные износы) через searchsuggestionsresults API.
        Возвращает список вариантов для дальнейшего парсинга каждого.
        
        Args:
            item_name: Название предмета для поиска
            
        Returns:
            Список вариантов предмета с их hash_name и извлеченной степенью износа
        """
        await self._ensure_client()
        
        # ВАЖНО: Если есть proxy_manager, получаем прокси для этого запроса
        if self.proxy_manager and not self.proxy:
            proxy = await self.proxy_manager.get_next_proxy(force_refresh=False)
            if proxy:
                self.proxy = proxy.url
                # Пересоздаем клиент с новым прокси
                if self._client:
                    await self._client.aclose()
                    self._client = None
                await self._ensure_client()
                logger.debug(f"🌐 get_item_variants: Используем прокси ID={proxy.id} для '{item_name}'")
            else:
                # Нет доступных прокси - запускаем автоматическую проверку
                logger.warning(f"⚠️ get_item_variants: Нет доступных прокси при первом запросе, запускаем автоматическую проверку...")
                logger.warning(f"   Предмет: '{item_name}'")
                
                try:
                    check_result = await self.proxy_manager.check_all_proxies_parallel(
                        max_concurrent=20,
                        update_redis_status=True
                    )
                    working_after_check = check_result.get('working', 0)
                    unblocked = check_result.get('unblocked_count', 0)
                    
                    logger.info(f"📊 get_item_variants: Результаты проверки прокси: работающих={working_after_check}, разблокировано={unblocked}")
                    
                    if working_after_check > 0:
                        await self.proxy_manager._update_redis_cache()
                        proxy = await self.proxy_manager.get_next_proxy(force_refresh=False)
                        if proxy:
                            self.proxy = proxy.url
                            if self._client:
                                await self._client.aclose()
                                self._client = None
                            await self._ensure_client()
                            logger.info(f"✅ get_item_variants: Получен прокси ID={proxy.id} после проверки")
                        else:
                            logger.error(f"❌ get_item_variants: После проверки все еще нет доступных прокси")
                            return []
                    else:
                        logger.warning(f"⚠️ get_item_variants: После проверки не найдено работающих прокси")
                        return []
                except Exception as check_error:
                    logger.error(f"❌ get_item_variants: Ошибка при проверке прокси: {check_error}")
                    import traceback
                    logger.debug(f"Traceback: {traceback.format_exc()}")
                    return []
        
        params = {"q": item_name}
        
        # Максимальное количество попыток с переключением прокси при 429
        max_proxy_switches = 50
        retry_delay = 5.0  # Задержка до 5 сек для снижения частоты запросов и избежания 429
        
        for attempt in range(max_proxy_switches):
            try:
                # Задержка перед запросом (только для повторных попыток)
                # Первый запрос выполняется сразу - задержки управляются через get_next_proxy()
                if attempt > 0:
                    logger.debug(f"⏳ get_item_variants: Задержка {retry_delay} сек перед попыткой {attempt + 1} для '{item_name}'")
                    await asyncio.sleep(retry_delay)
                
                # Обновляем заголовки перед каждым запросом (ротация User-Agent и всех заголовков)
                # Это помогает обойти блокировки, так как каждый запрос выглядит как с нового устройства
                headers = self._get_browser_headers()
                self._client.headers.update(headers)
                if attempt > 0:
                    logger.debug(f"🔄 Попытка {attempt + 1}/{max_proxy_switches}: Обновлены заголовки (User-Agent и др.) для '{item_name}'")
                
                # Используем URL из класса, так как это миксин
                search_url = getattr(self, 'SEARCH_SUGGESTIONS_URL', 'https://steamcommunity.com/market/searchsuggestionsresults')
                logger.debug(f"📡 Попытка {attempt + 1}/{max_proxy_switches}: Поиск вариантов предмета '{item_name}'")
                
                # ВАЖНО: Используем увеличенный таймаут для этого запроса (60 секунд)
                # так как прокси могут быть медленными
                import httpx
                extended_timeout = httpx.Timeout(60.0, connect=10.0)
                response = await self._client.get(search_url, params=params, timeout=extended_timeout)
                logger.debug(f"📥 Попытка {attempt + 1}/{max_proxy_switches}: Получен ответ: status_code={response.status_code}")
                
                if response.status_code == 429:
                    logger.warning(f"⚠️ get_item_variants: '{item_name}' - получен 429 на попытке {attempt + 1}/{max_proxy_switches}")
                    
                    # Быстро блокируем текущий прокси и переключаемся на следующий
                    current_proxy = await self._get_current_proxy()
                    if current_proxy:
                        await self._handle_429_fast(current_proxy, f"Поиск вариантов для '{item_name}'")
                    
                    # Задержка перед переключением прокси (чтобы не перегружать Steam)
                    await asyncio.sleep(3.0)  # Увеличена задержка до 3 сек перед переключением прокси
                    
                    # Переключение на следующий прокси
                    if self.proxy_manager:
                        # Используем skip_delay=True для мгновенного переключения
                        new_proxy = await self.proxy_manager.get_next_proxy(force_refresh=False, skip_delay=True)
                        if new_proxy:
                            self.proxy = new_proxy.url
                            if self._client:
                                await self._client.aclose()
                                self._client = None
                            await self._ensure_client()
                            logger.info(f"⚡ Мгновенное переключение на прокси ID={new_proxy.id}, продолжаем попытку {attempt + 1}/{max_proxy_switches}")
                            continue
                        else:
                            # Все прокси заблокированы - запускаем автоматическую проверку
                            logger.warning(f"⚠️ get_item_variants: Все прокси заблокированы, запускаем автоматическую проверку всех прокси...")
                            logger.warning(f"   Предмет: '{item_name}'")
                            logger.warning(f"   Попытка: {attempt + 1}/{max_proxy_switches}")
                            
                            try:
                                # Запускаем автоматическую проверку всех прокси
                                check_result = await self.proxy_manager.check_all_proxies_parallel(
                                    max_concurrent=20,
                                    update_redis_status=True
                                )
                                working_after_check = check_result.get('working', 0)
                                unblocked = check_result.get('unblocked_count', 0)
                                
                                logger.info(f"📊 get_item_variants: Результаты проверки прокси: работающих={working_after_check}, разблокировано={unblocked}")
                                
                                if working_after_check > 0:
                                    # Обновляем кэш и пробуем получить прокси снова
                                    await self.proxy_manager._update_redis_cache()
                                    new_proxy = await self.proxy_manager.get_next_proxy(force_refresh=False, skip_delay=True)
                                    if new_proxy:
                                        self.proxy = new_proxy.url
                                        if self._client:
                                            await self._client.aclose()
                                            self._client = None
                                        await self._ensure_client()
                                        logger.info(f"✅ get_item_variants: Получен прокси ID={new_proxy.id} после проверки, продолжаем попытку {attempt + 1}/{max_proxy_switches}")
                                        continue
                                    else:
                                        logger.error(f"❌ get_item_variants: После проверки все еще нет доступных прокси")
                                        return []
                                else:
                                    logger.warning(f"⚠️ get_item_variants: После проверки не найдено работающих прокси")
                                    return []
                            except Exception as check_error:
                                logger.error(f"❌ get_item_variants: Ошибка при проверке прокси: {check_error}")
                                import traceback
                                logger.debug(f"Traceback: {traceback.format_exc()}")
                                return []
                    else:
                        logger.error(f"❌ Нет ProxyManager для переключения прокси")
                        return []
                
                if response.status_code == 200:
                    data = response.json()
                    results = data.get("results", [])
                    logger.info(f"✅ Найдено вариантов предмета: {len(results)}")
                    if not results:
                        logger.warning(f"⚠️ API вернул пустой список результатов для '{item_name}'")
                    
                    # Извлекаем степени износа из названий
                    import re
                    wear_patterns = {
                        'Factory New': r'\(Factory New\)',
                        'Minimal Wear': r'\(Minimal Wear\)',
                        'Field-Tested': r'\(Field-Tested\)',
                        'Well-Worn': r'\(Well-Worn\)',
                        'Battle-Scarred': r'\(Battle-Scarred\)'
                    }
                    
                    for i, item in enumerate(results, 1):
                        name = item.get('market_hash_name', 'Unknown')
                        price = item.get('min_price', 0) / 100
                        
                        # Определяем, является ли предмет StatTrak™
                        is_stattrak = 'StatTrak™' in name or 'StatTrak' in name
                        item['is_stattrak'] = is_stattrak
                        
                        # Извлекаем степень износа
                        wear_condition = None
                        for wear_name, pattern in wear_patterns.items():
                            if re.search(pattern, name, re.IGNORECASE):
                                wear_condition = wear_name
                                break
                        
                        item['wear_condition'] = wear_condition
                        stattrack_label = "StatTrak™" if is_stattrak else "Обычный"
                        logger.info(f"  {i}. {name} - ${price:.2f} ({stattrack_label}, износ: {wear_condition or 'N/A'})")
                    
                    return results
                else:
                    logger.error(f"❌ Ошибка поиска вариантов: {response.status_code}")
                    if response.status_code != 429:  # 429 уже обработано выше
                        return []
                    # Для 429 продолжаем цикл
                    continue
                    
            except Exception as e:
                logger.error(f"❌ Исключение при поиске вариантов для '{item_name}' на попытке {attempt + 1}: {e}")
                import traceback
                logger.debug(f"Traceback: {traceback.format_exc()}")
                
                if attempt < max_proxy_switches - 1:
                    # Задержка перед переключением прокси при исключении
                    switch_delay = 3.0
                    logger.debug(f"⏳ get_item_variants: Задержка {switch_delay} сек перед переключением прокси после исключения для '{item_name}'")
                    await asyncio.sleep(switch_delay)
                    
                    # Пробуем переключить прокси и продолжить
                    if self.proxy_manager:
                        # Пробуем получить новый прокси
                        new_proxy = await self.proxy_manager.get_next_proxy(force_refresh=False, skip_delay=True)
                        if new_proxy:
                            self.proxy = new_proxy.url
                            if self._client:
                                await self._client.aclose()
                                self._client = None
                            await self._ensure_client()
                            logger.info(f"🔄 get_item_variants: Переключение на прокси ID={new_proxy.id} после исключения, продолжаем попытку {attempt + 1}/{max_proxy_switches}")
                            continue
                        else:
                            # Все прокси заблокированы - запускаем автоматическую проверку
                            logger.warning(f"⚠️ get_item_variants: Все прокси заблокированы после исключения, запускаем автоматическую проверку...")
                            try:
                                check_result = await self.proxy_manager.check_all_proxies_parallel(
                                    max_concurrent=20,
                                    update_redis_status=True
                                )
                                working_after_check = check_result.get('working', 0)
                                if working_after_check > 0:
                                    await self.proxy_manager._update_redis_cache()
                                    new_proxy = await self.proxy_manager.get_next_proxy(force_refresh=False, skip_delay=True)
                                    if new_proxy:
                                        self.proxy = new_proxy.url
                                        if self._client:
                                            await self._client.aclose()
                                            self._client = None
                                        await self._ensure_client()
                                        logger.info(f"✅ get_item_variants: Получен прокси ID={new_proxy.id} после проверки, продолжаем попытку {attempt + 1}/{max_proxy_switches}")
                                        continue
                            except Exception as check_error:
                                logger.error(f"❌ get_item_variants: Ошибка при проверке прокси после исключения: {check_error}")
                    continue
                else:
                    logger.error(f"❌ Достигнут лимит попыток для '{item_name}'")
                    return []
        
        # Если дошли сюда, значит все попытки исчерпаны
        logger.error(f"❌ Не удалось получить варианты для '{item_name}' после {max_proxy_switches} попыток")
        return []
    
    async def validate_hash_name(self, appid: int, hash_name: str) -> Tuple[bool, Optional[int]]:
        """
        Проверяет корректность hash_name и возвращает количество доступных лотов.
        
        Args:
            appid: ID приложения
            hash_name: Хэш-имя предмета для проверки
            
        Returns:
            Tuple[bool, Optional[int]]: (валидность, количество лотов или None)
        """
        logger.info(f"🔍 validate_hash_name: Начинаю проверку '{hash_name}' (appid={appid})")
        logger.info(f"   Прокси: {self.proxy[:50] if self.proxy else 'нет'}...")
        logger.info(f"   ProxyManager: {'есть' if self.proxy_manager else 'нет'}")
        
        # Используем _fetch_render_api из этого же класса
        # ВАЖНО: count=20 - максимальное значение, которое работает корректно
        render_data = await self._fetch_render_api(appid, hash_name, start=0, count=20)
        
        if render_data is None:
            logger.warning(f"❌ validate_hash_name: '{hash_name}' - render_data is None (API не вернул данные или ошибка запроса)")
            logger.warning(f"   Это может быть из-за:")
            logger.warning(f"   1. 429 ошибок (все прокси заблокированы)")
            logger.warning(f"   2. Предмет не найден (404)")
            logger.warning(f"   3. Временные проблемы с API")
            
            # Проверяем, есть ли активные прокси в ProxyManager
            if self.proxy_manager:
                try:
                    active_proxies = await self.proxy_manager.get_active_proxies(force_refresh=False)
                    if len(active_proxies) == 0:
                        logger.error(f"   ⚠️ КРИТИЧЕСКАЯ ПРОБЛЕМА: Все прокси заблокированы в ProxyManager!")
                        logger.error(f"   🔄 ProxyManager должен автоматически проверить все прокси и разблокировать работающие")
                        logger.error(f"   📊 Попробуйте получить активные прокси с force_refresh=True для запуска автоматической проверки")
                    else:
                        logger.debug(f"   📊 ProxyManager: Доступно {len(active_proxies)} активных прокси")
                except Exception as e:
                    logger.debug(f"   ⚠️ Не удалось проверить активные прокси: {e}")
            
            # ВАЖНО: Если render_data is None, это может быть из-за 429 ошибок
            # Но с ProxyManager 429 должны обрабатываться автоматически через переключение прокси
            # Если все равно None, значит либо нет доступных прокси, либо предмет действительно невалиден
            return False, None
        
        total_count = render_data.get('total_count', 0)
        success = render_data.get('success', False)
        results = render_data.get('results', [])
        results_html = render_data.get('results_html', '')
        results_html_len = len(results_html.strip()) if results_html else 0
        
        logger.info(f"📊 validate_hash_name: '{hash_name}' - success={success}, total_count={total_count}, results={len(results)}, results_html_len={results_html_len}")
        
        # ВАЖНО: Если total_count > 0, считаем валидным, даже если нет результатов в ответе
        # Результаты могут быть на следующих страницах или временно недоступны
        if total_count > 0:
            logger.info(f"✅ validate_hash_name: '{hash_name}' валиден: {total_count} лотов доступно")
            return True, total_count
        else:
            logger.warning(f"❌ validate_hash_name: '{hash_name}' невалиден: total_count=0 (success={success})")
            # Дополнительная информация для отладки
            if results_html_len > 0:
                logger.warning(f"   Но есть results_html длиной {results_html_len} - возможно, лоты есть, но total_count не установлен")
            return False, None
    
    async def _fetch_render_api(self, appid: int, hash_name: str, start: int = 0, count: int = 20) -> Optional[Dict[str, Any]]:
        """
        Загружает данные через API /render/ для получения паттерна и float напрямую из JSON.
        
        Args:
            appid: ID приложения
            hash_name: Хэш-имя предмета
            start: Начальная позиция (для пагинации)
            count: Количество лотов на странице
            
        Returns:
            JSON данные или None при ошибке
        """
        await self._ensure_client()
        
        # ВАЖНО: Если есть proxy_manager, получаем прокси для этого запроса
        if self.proxy_manager and not self.proxy:
            proxy = await self.proxy_manager.get_next_proxy(force_refresh=False)
            if proxy:
                self.proxy = proxy.url
                # Пересоздаем клиент с новым прокси
                if self._client:
                    await self._client.aclose()
                    self._client = None
                await self._ensure_client()
                logger.debug(f"🌐 _fetch_render_api: Используем прокси ID={proxy.id} для '{hash_name}'")
            else:
                # Нет доступных прокси - запускаем автоматическую проверку
                logger.warning(f"⚠️ _fetch_render_api: Нет доступных прокси при первом запросе, запускаем автоматическую проверку...")
                logger.warning(f"   Предмет: '{hash_name}' (appid={appid})")
                
                try:
                    check_result = await self.proxy_manager.check_all_proxies_parallel(
                        max_concurrent=20,
                        update_redis_status=True
                    )
                    working_after_check = check_result.get('working', 0)
                    unblocked = check_result.get('unblocked_count', 0)
                    
                    logger.info(f"📊 _fetch_render_api: Результаты проверки прокси: работающих={working_after_check}, разблокировано={unblocked}")
                    
                    if working_after_check > 0:
                        await self.proxy_manager._update_redis_cache()
                        proxy = await self.proxy_manager.get_next_proxy(force_refresh=False)
                        if proxy:
                            self.proxy = proxy.url
                            if self._client:
                                await self._client.aclose()
                                self._client = None
                            await self._ensure_client()
                            logger.info(f"✅ _fetch_render_api: Получен прокси ID={proxy.id} после проверки")
                        else:
                            logger.error(f"❌ _fetch_render_api: После проверки все еще нет доступных прокси")
                            return None
                    else:
                        logger.warning(f"⚠️ _fetch_render_api: После проверки не найдено работающих прокси")
                        return None
                except Exception as check_error:
                    logger.error(f"❌ _fetch_render_api: Ошибка при проверке прокси: {check_error}")
                    import traceback
                    logger.debug(f"Traceback: {traceback.format_exc()}")
                    return None
        
        # URL для API /render/
        base_url = f"https://steamcommunity.com/market/listings/{appid}/{quote(hash_name)}/render/"
        params = {
            "query": "",
            "start": start,
            "count": count,
            "country": "BY",
            "language": "english",
            "currency": 1
        }
        url = base_url + "?" + "&".join([f"{k}={v}" for k, v in params.items()])
        
        # Максимальное количество попыток с переключением прокси при 429
        max_proxy_switches = 10  # Уменьшено с 50 до 10, чтобы не зависать долго
        retry_delay = 5.0  # Увеличена задержка до 5 сек для снижения частоты запросов и избежания 429
        initial_delay = 3.0  # Увеличена задержка перед первым запросом до 3 сек
        
        for attempt in range(max_proxy_switches):
            try:
                # Задержка перед запросом (включая первый запрос)
                if attempt == 0:
                    logger.debug(f"⏳ _fetch_render_api: Задержка {initial_delay} сек перед первым запросом для '{hash_name}'")
                    await asyncio.sleep(initial_delay)
                else:
                    logger.debug(f"⏳ _fetch_render_api: Задержка {retry_delay} сек перед попыткой {attempt + 1} для '{hash_name}'")
                    await asyncio.sleep(retry_delay)
                
                # Обновляем заголовки перед каждым запросом (ротация User-Agent и всех заголовков)
                # Это помогает обойти блокировки, так как каждый запрос выглядит как с нового устройства
                headers = self._get_browser_headers()
                self._client.headers.update(headers)
                if attempt > 0:
                    logger.debug(f"🔄 Попытка {attempt + 1}/{max_proxy_switches}: Обновлены заголовки (User-Agent и др.) для '{hash_name}'")
                
                logger.debug(f"📡 Попытка {attempt + 1}/{max_proxy_switches}: API /render/ запрос (start={start}, count={count})")
                response = await self._client.get(url)
                logger.debug(f"📥 Попытка {attempt + 1}/{max_proxy_switches}: Получен ответ: status_code={response.status_code}")
                
                if response.status_code == 429:
                    logger.warning(f"⚠️ _fetch_render_api: '{hash_name}' - получен 429 на попытке {attempt + 1}/{max_proxy_switches}")
                    
                    # Быстро блокируем текущий прокси и переключаемся на следующий
                    current_proxy = await self._get_current_proxy()
                    if current_proxy:
                        await self._handle_429_fast(current_proxy, f"API /render/ запрос для '{hash_name}'")
                    
                    # Задержка перед переключением прокси (чтобы не перегружать Steam)
                    await asyncio.sleep(3.0)  # Увеличена задержка до 3 сек перед переключением прокси
                    
                    # Переключение на следующий прокси
                    if self.proxy_manager:
                        # Используем skip_delay=True для мгновенного переключения
                        new_proxy = await self.proxy_manager.get_next_proxy(force_refresh=False, skip_delay=True)
                        if new_proxy:
                            self.proxy = new_proxy.url
                            if self._client:
                                await self._client.aclose()
                                self._client = None
                            await self._ensure_client()
                            logger.info(f"⚡ Мгновенное переключение на прокси ID={new_proxy.id}, продолжаем попытку {attempt + 1}/{max_proxy_switches}")
                            continue
                        else:
                            # Все прокси заблокированы - быстро возвращаем None, чтобы не зависать
                            # listing_parser будет ждать в цикле и проверять прокси каждые 5 минут
                            logger.warning(f"⚠️ _fetch_render_api: Все прокси заблокированы на попытке {attempt + 1}/{max_proxy_switches}")
                            logger.warning(f"   Предмет: '{hash_name}' (appid={appid})")
                            logger.warning(f"   💡 Возвращаем None - listing_parser будет ждать доступных прокси в цикле")
                            return None  # Сразу возвращаем None, не ждем остальные попытки
                    else:
                        logger.error(f"❌ _fetch_render_api: Нет ProxyManager для переключения прокси")
                        logger.error(f"   Предмет: '{hash_name}' (appid={appid})")
                        logger.error(f"   Попытка: {attempt + 1}/{max_proxy_switches}")
                        return None
                
                if response.status_code == 200:
                    try:
                        data = response.json()
                        success = data.get('success', False)
                        total_count = data.get('total_count', 0)
                        results = data.get('results', [])
                        results_html = data.get('results_html', '')
                        results_html_len = len(results_html.strip()) if results_html else 0
                        
                        # Детальное логирование для отладки
                        logger.info(f"📥 _fetch_render_api: '{hash_name}' - success={success}, total_count={total_count}, results={len(results)}, results_html_len={results_html_len}")
                        logger.info(f"   URL запроса: {url}")
                        logger.debug(f"   Ключи в ответе: {list(data.keys())}")
                        
                        # Логируем полный ответ (без results_html, т.к. он очень большой)
                        data_for_log = {k: v for k, v in data.items() if k != 'results_html'}
                        logger.debug(f"   Полный ответ (без results_html): {data_for_log}")
                        
                        if 'total_count' not in data:
                            logger.warning(f"   ⚠️ В ответе нет ключа 'total_count'! Доступные ключи: {list(data.keys())}")
                        if total_count == 0 and results_html_len > 0:
                            logger.warning(f"   ⚠️ total_count=0, но results_html_len={results_html_len} - возможно, лоты есть в HTML")
                        
                        if success:
                            # Проверяем total_count - это основной индикатор наличия лотов
                            # ВАЖНО: Если total_count > 0, считаем валидным, даже если нет результатов в ответе
                            # Результаты могут быть на следующих страницах или временно недоступны
                            if total_count > 0:
                                logger.info(f"✅ API /render/ вернул {total_count} лотов, {len(results)} в results, HTML длина: {results_html_len}")
                                return data
                            else:
                                # Дополнительная проверка: если есть results_html, возможно лоты есть, но total_count не установлен
                                # Или total_count может быть в другом месте ответа
                                if results_html_len > 100:
                                    logger.warning(f"⚠️ _fetch_render_api: '{hash_name}' - API вернул success=true, но total_count=0, хотя results_html_len={results_html_len}")
                                    logger.warning(f"   Возможно, лоты есть, но total_count не установлен. Проверяем results_html...")
                                    
                                    # Пытаемся извлечь количество лотов из HTML
                                    # Ищем паттерны типа "Showing 1-X of Y listings" или просто проверяем наличие элементов
                                    import re
                                    # Ищем упоминания количества в HTML
                                    count_patterns = [
                                        r'(\d+)\s+listings?',
                                        r'showing\s+(\d+)',
                                        r'total[:\s]+(\d+)',
                                    ]
                                    found_count = None
                                    for pattern in count_patterns:
                                        match = re.search(pattern, results_html, re.IGNORECASE)
                                        if match:
                                            found_count = int(match.group(1))
                                            logger.info(f"   Найдено количество лотов в HTML: {found_count}")
                                            break
                                    
                                    # Если нашли количество в HTML, используем его
                                    if found_count and found_count > 0:
                                        logger.info(f"   Используем количество из HTML: {found_count}")
                                        data['total_count'] = found_count
                                        return data
                                    
                                    # Если не нашли, но results_html достаточно большой, считаем что лоты есть
                                    # Минимальная длина results_html для одного лота обычно > 500 символов
                                    if results_html_len > 500:
                                        logger.info(f"   results_html_len={results_html_len} достаточно большой, считаем что лоты есть")
                                        # Устанавливаем примерное количество на основе длины HTML
                                        # Примерно 1 лот = 500-1000 символов
                                        estimated_count = max(1, results_html_len // 800)
                                        logger.info(f"   Устанавливаем примерное количество: {estimated_count}")
                                        data['total_count'] = estimated_count
                                        return data
                                    else:
                                        logger.info(f"   results_html_len={results_html_len} слишком мал, лотов нет")
                                        return None
                                else:
                                    logger.info(f"❌ _fetch_render_api: '{hash_name}' - API вернул success=true, но total_count=0 и results_html пуст (нет доступных лотов)")
                                    return None
                        else:
                            error_msg = data.get('error', 'Unknown error')
                            logger.warning(f"❌ _fetch_render_api: '{hash_name}' - API вернул success=false, error='{error_msg}' (предмет не найден или недоступен)")
                            return None
                    except json.JSONDecodeError as e:
                        logger.error(f"❌ _fetch_render_api: '{hash_name}' - Ошибка парсинга JSON: {e}")
                        if attempt < max_proxy_switches - 1:
                            continue
                        logger.info(f"❌ _fetch_render_api: '{hash_name}' - Не удалось распарсить JSON после {max_proxy_switches} попыток")
                        return None
                elif response.status_code == 404:
                    logger.info(f"❌ _fetch_render_api: '{hash_name}' - API вернул 404 (предмет не найден)")
                    return None
                else:
                    logger.info(f"❌ _fetch_render_api: '{hash_name}' - API вернул status_code={response.status_code}")
                    if attempt < max_proxy_switches - 1:
                        continue
                    logger.info(f"❌ _fetch_render_api: '{hash_name}' - Не удалось получить данные после {max_proxy_switches} попыток (status_code={response.status_code})")
                    return None
                    
            except httpx.TimeoutException as e:
                logger.warning(f"⚠️ _fetch_render_api: '{hash_name}' - Timeout на попытке {attempt + 1}/{max_proxy_switches}: {e}")
                # Быстро переключаемся на следующий прокси или возвращаем None
                if self.proxy_manager:
                    new_proxy = await self.proxy_manager.get_next_proxy(force_refresh=False, skip_delay=True)
                    if new_proxy:
                        self.proxy = new_proxy.url
                        if self._client:
                            await self._client.aclose()
                            self._client = None
                        await self._ensure_client()
                        logger.info(f"🔄 _fetch_render_api: Переключение на прокси ID={new_proxy.id} после timeout")
                        if attempt < max_proxy_switches - 1:
                            await asyncio.sleep(2.0)
                            continue
                    else:
                        # Все прокси заблокированы - сразу возвращаем None
                        logger.warning(f"⚠️ _fetch_render_api: Все прокси заблокированы после timeout, возвращаем None")
                        return None
                if attempt < max_proxy_switches - 1:
                    await asyncio.sleep(2.0)
                    continue
                logger.info(f"❌ _fetch_render_api: '{hash_name}' - Timeout после {max_proxy_switches} попыток")
                return None
            except Exception as e:
                logger.error(f"❌ _fetch_render_api: '{hash_name}' - Ошибка при запросе: {e}")
                import traceback
                logger.debug(f"Traceback: {traceback.format_exc()}")
                # Быстро переключаемся на следующий прокси или возвращаем None
                if self.proxy_manager:
                    new_proxy = await self.proxy_manager.get_next_proxy(force_refresh=False, skip_delay=True)
                    if new_proxy:
                        self.proxy = new_proxy.url
                        if self._client:
                            await self._client.aclose()
                            self._client = None
                        await self._ensure_client()
                        logger.info(f"🔄 _fetch_render_api: Переключение на прокси ID={new_proxy.id} после ошибки")
                        if attempt < max_proxy_switches - 1:
                            await asyncio.sleep(2.0)
                            continue
                    else:
                        # Все прокси заблокированы - сразу возвращаем None
                        logger.warning(f"⚠️ _fetch_render_api: Все прокси заблокированы после ошибки, возвращаем None")
                        return None
                if attempt < max_proxy_switches - 1:
                    await asyncio.sleep(2.0)
                    continue
                logger.info(f"❌ _fetch_render_api: '{hash_name}' - Исключение после {max_proxy_switches} попыток: {type(e).__name__}")
                return None
        
        return None
    
    async def _fetch_listing_page(self, appid: int, hash_name: str, listing_id: str) -> Optional[str]:
        """
        Загружает HTML страницу конкретного лота (где есть наклейки в HTML).
        
        Args:
            appid: ID приложения
            hash_name: Хэш-имя предмета
            listing_id: ID лота
            
        Returns:
            HTML содержимое или None при ошибке
        """
        await self._ensure_client()
        from urllib.parse import quote
        url = f"https://steamcommunity.com/market/listings/{appid}/{quote(hash_name)}"
        
        max_retries = 3
        retry_delay = 5
        
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    delay = await self._random_delay(min_seconds=0.5, max_seconds=1.5)
                    logger.info(f"⏳ Задержка {delay:.1f} сек перед повторной попыткой загрузки страницы лота")
                else:
                    await self._random_delay(min_seconds=0.5, max_seconds=1.5)
                
                if attempt > 0:
                    headers = self._get_browser_headers()
                    self._client.headers.update(headers)
                    logger.info(f"🔄 Попытка {attempt + 1}/{max_retries}: Обновлен User-Agent для загрузки страницы лота")
                
                logger.info(f"📡 Попытка {attempt + 1}/{max_retries}: Загрузка страницы лота: listing_id={listing_id}, hash_name={hash_name}")
                response = await self._client.get(url)
                logger.info(f"📥 Попытка {attempt + 1}/{max_retries}: Получен ответ: status_code={response.status_code}")
                
                if response.status_code == 429:
                    # Быстро обрабатываем 429 и переключаем прокси
                    current_proxy = await self._get_current_proxy()
                    await self._handle_429_fast(current_proxy, f"загрузка страницы лота (listing_id={listing_id})")
                    
                    # Переключаемся на другой прокси и повторяем попытку
                    if self.proxy_manager:
                        proxy_switched = await self._switch_proxy()
                        if proxy_switched:
                            logger.info(f"✅ Прокси переключен для загрузки страницы лота, повторяем попытку {attempt + 1}/{max_retries}")
                            headers = self._get_browser_headers()
                            self._client.headers.update(headers)
                            continue
                        else:
                            logger.warning(f"⚠️ Не удалось переключить прокси для загрузки страницы лота")
                            return None
                    else:
                        logger.warning(f"⚠️ Нет ProxyManager для переключения прокси при загрузке страницы лота")
                        return None
                
                response.raise_for_status()
                return response.text
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    # Быстро обрабатываем 429 и переключаем прокси
                    current_proxy = await self._get_current_proxy()
                    await self._handle_429_fast(current_proxy, f"загрузка страницы лота (listing_id={listing_id}) (HTTPStatusError)")
                    
                    # Переключаемся на другой прокси и повторяем попытку
                    if self.proxy_manager:
                        proxy_switched = await self._switch_proxy()
                        if proxy_switched:
                            logger.info(f"✅ Прокси переключен для загрузки страницы лота (HTTPStatusError), повторяем попытку {attempt + 1}/{max_retries}")
                            headers = self._get_browser_headers()
                            self._client.headers.update(headers)
                            continue
                        else:
                            logger.warning(f"⚠️ Не удалось переключить прокси для загрузки страницы лота (HTTPStatusError)")
                            return None
                    else:
                        logger.warning(f"⚠️ Нет ProxyManager для переключения прокси при загрузке страницы лота (HTTPStatusError)")
                        return None
                else:
                    raise
            except Exception as e:
                logger.error(f"Ошибка при загрузке страницы лота {url}: {e}")
                return None
        
        return None
    
    async def _fetch_item_page(self, appid: int, hash_name: str, page: int = 1) -> Optional[str]:
        """
        Загружает HTML страницу предмета с поддержкой пагинации.

        Args:
            appid: ID приложения
            hash_name: Хэш-имя предмета
            page: Номер страницы (начинается с 1)

        Returns:
            HTML содержимое или None при ошибке
        """
        await self._ensure_client()
        from urllib.parse import quote
        url = f"https://steamcommunity.com/market/listings/{appid}/{quote(hash_name)}"
        if page > 1:
            url += f"?p={page}"

        max_retries = 3
        retry_delay = 5
        
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    delay = await self._random_delay(min_seconds=0.5, max_seconds=1.5)
                    logger.info(f"⏳ Задержка {delay:.1f} сек перед повторной попыткой загрузки страницы предмета")
                else:
                    await self._random_delay(min_seconds=0.5, max_seconds=1.5)
                
                if attempt > 0:
                    headers = self._get_browser_headers()
                    self._client.headers.update(headers)
                    logger.info(f"🔄 Попытка {attempt + 1}/{max_retries}: Обновлен User-Agent для загрузки страницы предмета")
                
                logger.info(f"📡 Попытка {attempt + 1}/{max_retries}: Загрузка страницы предмета: {hash_name}")
                response = await self._client.get(url)
                logger.info(f"📥 Попытка {attempt + 1}/{max_retries}: Получен ответ: status_code={response.status_code}")
                
                if response.status_code == 429:
                    should_retry = await self._handle_429_error(
                        response=response,
                        attempt=attempt,
                        max_retries=max_retries,
                        base_delay=retry_delay,
                        context=f"загрузка страницы предмета '{hash_name}'"
                    )
                    if should_retry:
                        headers = self._get_browser_headers()
                        self._client.headers.update(headers)
                        continue
                    else:
                        return None
                
                response.raise_for_status()
                return response.text
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    should_retry = await self._handle_429_error(
                        response=e.response,
                        attempt=attempt,
                        max_retries=max_retries,
                        base_delay=retry_delay,
                        context=f"загрузка страницы предмета '{hash_name}' (HTTPStatusError)"
                    )
                    if should_retry:
                        headers = self._get_browser_headers()
                        self._client.headers.update(headers)
                        continue
                    else:
                        return None
                else:
                    logger.error(f"❌ HTTP ошибка {e.response.status_code} при загрузке страницы предмета: {e}")
                    raise
            except Exception as e:
                logger.error(f"Ошибка при загрузке страницы {url}: {e}")
                return None
        
        return None
