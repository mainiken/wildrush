"""
Миксин для работы с рекламой в Minimon.
Использует curl_cffi для обхода детекции ботов.
"""

import asyncio
import json
import random
import time
from typing import Dict, List, Optional, Any
from urllib.parse import urlencode

from curl_cffi import requests
from bot.utils import logger


class AdsViewMixin:
    """Миксин для работы с рекламой через API Minimon и Adsgram."""
    
    def __init__(self):
        """Инициализация миксина для просмотра рекламы."""
        self._ads_session: Optional[requests.Session] = None
        self._last_ad_request_time: float = 0
        self._min_delay_between_ads: int = 15  # минимальная задержка между рекламой
        self._max_delay_between_ads: int = 30  # максимальная задержка между рекламой
    
    def _get_session_name(self) -> str:
        """Получение имени сессии для логирования."""
        return getattr(self, 'session_name', 'Unknown')
    
    def _create_ads_session(self) -> requests.Session:
        """Создание сессии для работы с рекламой."""
        from bot.core.headers import headers
        
        session = requests.Session(impersonate="chrome110")
        
        # Используем те же заголовки, что и основная сессия
        session.headers.update(headers())
        
        return session
    
    def _get_ads_session(self) -> requests.Session:
        """Получение или создание сессии для рекламы."""
        # Если есть основная сессия бота, используем её
        if hasattr(self, 'session') and self.session:
            return self.session
        
        # Иначе создаем отдельную сессию для рекламы
        if self._ads_session is None:
            self._ads_session = self._create_ads_session()
        return self._ads_session
    
    def _make_ads_request(
        self, 
        method: str, 
        url: str, 
        headers: Optional[Dict[str, str]] = None,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, str]] = None,
        timeout: int = 30
    ) -> Optional[Dict[str, Any]]:
        """
        Выполнение запроса к API рекламы.
        
        Args:
            method: HTTP метод
            url: URL для запроса
            headers: Дополнительные заголовки
            data: Данные для POST запроса
            params: Параметры для GET запроса
            timeout: Таймаут запроса
            
        Returns:
            Ответ API или None при ошибке
        """
        # Используем основную сессию бота если доступна, иначе создаем новую
        if hasattr(self, 'session') and self.session:
            session = self.session
        else:
            session = self._get_ads_session()
        
        try:
            # Используем единую функцию headers() для всех запросов
            from bot.core.headers import headers as get_headers
            request_headers = get_headers()
                
            if headers:
                request_headers.update(headers)
            
            if "minimon.app" in url:
                request_headers.update({
                    "origin": "https://minimon.app",
                    "referer": "https://minimon.app/app.html?v=61&preload=1&_v=MST060",
                    "priority": "u=1, i"
                })
            elif "adsgram.ai" in url:
                request_headers.update({
                    "accept": "*/*",
                    "accept-language": "ru,en;q=0.9,en-GB;q=0.8,en-US;q=0.7",
                    "cache-control": "max-age=0",
                    "origin": "https://minimon.app",
                    "priority": "u=1, i",
                    "referer": "https://minimon.app/",
                    "sec-ch-ua": '"Microsoft Edge WebView2";v="141", "Chromium";v="141", "Microsoft Edge";v="141", "Not?A_Brand";v="8"',
                    "sec-ch-ua-mobile": "?0",
                    "sec-ch-ua-platform": '"Windows"',
                    "sec-fetch-dest": "empty",
                    "sec-fetch-mode": "cors",
                    "sec-fetch-site": "cross-site",
                    "x-color-scheme": "dark",
                    "x-is-fullscreen": "false"
                })
            
            if method.upper() == "POST":
                response = session.post(
                    url,
                    headers=request_headers,
                    json=data,
                    timeout=timeout
                )
            else:
                response = session.get(
                    url,
                    headers=request_headers,
                    params=params,
                    timeout=timeout
                )
            
            session_name = self._get_session_name()
            
            # Логируем полный URL для отладки
            if params:
                full_url = f"{url}?{urlencode(params)}"
                logger.debug(f"{session_name} | Полный URL запроса: {full_url}")
            else:
                logger.debug(f"{session_name} | URL запроса: {url}")
            
            # Логируем заголовки для отладки (только для adsgram.ai)
            if "adsgram.ai" in url:
                logger.debug(f"{session_name} | Заголовки запроса: {request_headers}")
            
            logger.info(f"{session_name} | {method} запрос к {url}: статус {response.status_code}")
            
            # Обрабатываем различные статусы ответа
            if response.status_code == 400:
                try:
                    error_data = response.json()
                    logger.warning(f"{session_name} | Ошибка 400: {error_data}")
                except:
                    logger.warning(f"{session_name} | Ошибка 400: {response.text[:200]}")
                return None
            elif response.status_code == 200:
                try:
                    json_response = response.json()
                    if "adsgram.ai" in url:
                        logger.info(f"{session_name} | Успешный ответ от adsgram.ai: {json_response}")
                    return json_response
                except json.JSONDecodeError:
                    logger.warning(f"{session_name} | Не удалось декодировать JSON ответ: {response.text[:200]}")
                    return None
            else:
                logger.warning(f"{session_name} | Неожиданный статус ответа {response.status_code}: {response.text[:200]}")
                return None
                
        except Exception as e:
            logger.error(f"{session_name} | Ошибка при выполнении запроса к {url}: {e}")
            return None
    
    def get_ad_tasks(self, init_data: str) -> Optional[List[Dict[str, Any]]]:
        """
        Получение списка заданий для просмотра рекламы.
        
        Args:
            init_data: Telegram init data
            
        Returns:
            Список заданий или None при ошибке
        """
        url = "https://minimon.app/php/tasks.php"
        data = {
            "initData": init_data,
            "action": "list"
        }
        
        response = self._make_ads_request("POST", url, data=data)
        
        if response and response.get("ok"):
            tasks = response.get("data", {}).get("tasks", [])
            # Фильтруем только задания для просмотра рекламы
            ad_tasks = [
                task for task in tasks 
                if task.get("kind") in ["video_view", "video_click", "ads_threshold"]
                and not task.get("done", True)
            ]
            return ad_tasks
        
        logger.warning(f"{session_name} | Не удалось получить список заданий")
        return None
    
    def request_ad(self, init_data: str, block_id: str = "16054") -> Optional[Dict[str, Any]]:
        """
        Запрос рекламы от Adsgram.
        
        Args:
            init_data: Telegram init data
            block_id: ID блока рекламы
            
        Returns:
            Данные рекламы или None при ошибке/отсутствии рекламы
        """
        session_name = self._get_session_name()
        logger.info(f"{session_name} | Начинаем запрос рекламы, длина init_data: {len(init_data)}")
        
        # Парсим init_data для получения параметров
        parsed_data = self._parse_telegram_init_data(init_data)
        if not parsed_data:
            logger.error(f"{session_name} | Не удалось распарсить init_data")
            return None
        
        # Отладочное логирование
        logger.info(f"{session_name} | Распарсенные данные: {list(parsed_data.keys())}")
        logger.info(f"{session_name} | Signature: {parsed_data.get('signature', 'НЕ НАЙДЕНА')}")
        
        user_data = parsed_data.get("user", {})
        tg_id = user_data.get("id")
        is_premium = user_data.get("is_premium", False)
        language_code = user_data.get("language_code", "ru")
        
        # Формируем data_check_string правильно - это должна быть base64-кодированная строка
        # содержащая все параметры кроме signature и hash
        import base64
        from urllib.parse import unquote
        
        # Декодируем init_data
        decoded_init_data = unquote(init_data)
        
        # Создаем data_check_string из параметров без signature и hash
        data_parts = []
        for key, value in parsed_data.items():
            if key not in ['signature', 'hash']:
                if isinstance(value, dict):
                    import json
                    data_parts.append(f"{key}={json.dumps(value, separators=(',', ':'), ensure_ascii=False)}")
                else:
                    data_parts.append(f"{key}={value}")
        
        # Сортируем параметры и объединяем
        data_parts.sort()
        data_string = '\n'.join(data_parts)
        data_check_string = base64.b64encode(data_string.encode('utf-8')).decode('ascii')
        
        logger.info(f"{session_name} | Сформированный data_check_string длина: {len(data_check_string)}")
        
        # Извлекаем chat_type и chat_instance из parsed_data
        chat_type = parsed_data.get("chat_type", "sender")
        chat_instance = parsed_data.get("chat_instance", "")
        
        # Параметры для запроса рекламы согласно рабочему примеру
        params = {
            "envType": "telegram",
            "blockId": block_id,
            "platform": "Win32",
            "language": language_code,
            "chat_type": chat_type,
            "chat_instance": chat_instance,
            "top_domain": "minimon.app",
            "signature": parsed_data.get("signature", ""),
            "data_check_string": data_check_string,
            "sdk_version": "1.31.3",
            "tg_id": str(tg_id) if tg_id else "",
            "tg_platform": "tdesktop",
            "tma_version": "9.1",
            "request_id": str(int(time.time() * 1000)) + str(random.randint(100000, 999999)),
            "raw": "8389510628c8d09db29cf66a676dee309159bfd242d5d3870e80c6934603e789"
        }
        
        url = "https://api.adsgram.ai/adv"
        
        response = self._make_ads_request("GET", url, params=params)
        
        session_name = self._get_session_name()
        if response:
            banners = response.get("banners", [])
            if banners:
                logger.info(f"{session_name} | Получена реклама: {len(banners)} баннеров")
                return response
            else:
                logger.info(f"{session_name} | Реклама не найдена")
                return None
        
        logger.info(f"{session_name} | Не удалось получить рекламу (возможно, ошибка 400)")
        return None
    
    def send_ad_tracking_event(self, tracking_url: str) -> bool:
        """
        Отправка события отслеживания рекламы.
        
        Args:
            tracking_url: URL для отслеживания события
            
        Returns:
            True если событие отправлено успешно
        """
        try:
            response = self._make_ads_request("GET", tracking_url)
            return response is not None
        except Exception as e:
            logger.error(f"Ошибка при отправке события отслеживания: {e}")
            return False
    
    def send_ad_view_event(self, init_data: str) -> Optional[Dict[str, Any]]:
        """
        Отправка события просмотра рекламы для получения награды.
        
        Args:
            init_data: Telegram init data
            
        Returns:
            Ответ сервера с информацией о балансе
        """
        session_name = self._get_session_name()
        url = "https://minimon.app/php/tasks.php"
        data = {
            "initData": init_data,
            "action": "ads_event",
            "kind": "view"
        }
        
        response = self._make_ads_request("POST", url, data=data)
        
        if response and response.get("ok"):
            balances = response.get("data", {}).get("balances", {})
            logger.info(f"{session_name} | Событие просмотра рекламы отправлено успешно. Баланс: {balances}")
            return response
        
        logger.warning(f"{session_name} | Не удалось отправить событие просмотра рекламы")
        return None
    
    async def watch_single_ad(self, init_data: str) -> bool:
        """
        Упрощенный метод просмотра одной рекламы согласно новому алгоритму.
        
        Args:
            init_data: Telegram init data
            
        Returns:
            True если реклама просмотрена успешно
        """
        session_name = self._get_session_name()
        
        try:
            # 1. Запрашиваем рекламу
            logger.info(f"{session_name} | Запрашиваем рекламу")
            logger.info(f"{session_name} | DEBUG: Вызываем request_ad с init_data длиной {len(init_data)}")
            ad_data = self.request_ad(init_data)
            logger.info(f"{session_name} | DEBUG: request_ad вернул: {ad_data is not None}")
            
            if not ad_data:
                logger.error(f"{session_name} | Реклама недоступна - request_ad вернул False")
                return False
            
            # 2. Отправляем событие просмотра для получения награды
            logger.info(f"{session_name} | Отправляем событие просмотра рекламы")
            result = self.send_ad_view_event(init_data)
            logger.info(f"{session_name} | DEBUG: send_ad_view_event вернул: {result}")
            
            if result and result.get("ok"):
                logger.info(f"{session_name} | Событие просмотра отправлено успешно")
                
                # 3. Проверяем прогресс (данные могут обновиться не сразу)
                await asyncio.sleep(1)  # Небольшая задержка
                progress_result = await self.check_ad_progress(init_data)
                
                if progress_result:
                    logger.info(f"{session_name} | Реклама просмотрена успешно! Прогресс обновлен")
                    return True
                else:
                    logger.info(f"{session_name} | Событие отправлено, но прогресс не обновился")
                    return True  # Считаем успешным, так как событие отправлено
            else:
                logger.error(f"{session_name} | Не удалось засчитать просмотр рекламы. Результат: {result}")
                return False
        except Exception as e:
            logger.error(f"{session_name} | Ошибка в watch_single_ad: {e}")
            return False
    
    async def check_ad_progress(self, init_data: str, delay: int = 2) -> Optional[Dict[str, Any]]:
        """
        Проверка прогресса заданий с задержкой.
        
        Args:
            init_data: Telegram init data
            delay: Задержка перед проверкой в секундах
            
        Returns:
            Данные о заданиях или None при ошибке
        """
        session_name = self._get_session_name()
        
        if delay > 0:
            logger.info(f"{session_name} | Ожидаем {delay} секунд перед проверкой прогресса")
            await asyncio.sleep(delay)
        
        logger.info(f"{session_name} | Проверяем обновленный прогресс заданий")
        return self.get_ad_tasks(init_data)
    
    async def simulate_ad_viewing(
        self, 
        ad_data: Dict[str, Any], 
        init_data: str,
        view_duration: Optional[int] = None
    ) -> bool:
        """
        Симуляция просмотра рекламы с отправкой всех необходимых событий.
        
        Args:
            ad_data: Данные рекламы от Adsgram
            init_data: Telegram init data
            view_duration: Длительность просмотра в секундах
            
        Returns:
            True если просмотр прошел успешно
        """
        session_name = self._get_session_name()
        banners = ad_data.get("banners", [])
        if not banners:
            logger.warning(f"{session_name} | Нет баннеров для просмотра")
            return False
        
        banner = banners[0]  # Берем первый баннер
        trackings = banner.get("banner", {}).get("trackings", [])
        
        # Создаем словарь событий отслеживания
        tracking_events = {}
        for tracking in trackings:
            event_name = tracking.get("name")
            event_url = tracking.get("value")
            if event_name and event_url:
                tracking_events[event_name] = event_url
        
        try:
            # 1. Отправляем событие render (показ рекламы)
            if "render" in tracking_events:
                logger.info(f"{session_name} | Отправляем событие render")
                self.send_ad_tracking_event(tracking_events["render"])
                await asyncio.sleep(1)
            
            # 2. Отправляем событие show (начало показа)
            if "show" in tracking_events:
                logger.info(f"{session_name} | Отправляем событие show")
                self.send_ad_tracking_event(tracking_events["show"])
                await asyncio.sleep(1)
            
            # 3. Симулируем просмотр рекламы
            if view_duration is None:
                view_duration = random.randint(self._min_delay_between_ads, self._max_delay_between_ads)
            
            logger.info(f"{session_name} | Симулируем просмотр рекламы в течение {view_duration} секунд")
            await asyncio.sleep(view_duration)
            
            # 4. Отправляем событие reward (получение награды)
            if "reward" in tracking_events:
                logger.info(f"{session_name} | Отправляем событие reward")
                self.send_ad_tracking_event(tracking_events["reward"])
                await asyncio.sleep(1)
            
            # 5. Отправляем событие в Minimon для получения награды
            logger.info(f"{session_name} | Отправляем событие просмотра в Minimon")
            result = self.send_ad_view_event(init_data)
            
            if result:
                balances = result.get("data", {}).get("balances", {})
                logger.info(f"{session_name} | Награда получена! Баланс: {balances}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"{session_name} | Ошибка при симуляции просмотра рекламы: {e}")
            return False
    
    async def watch_ads_cycle(self, init_data: str, max_ads: int = 5) -> Dict[str, Any]:
        """
        Цикл просмотра рекламы согласно новому алгоритму.
        
        Args:
            init_data: Telegram init data
            max_ads: Максимальное количество рекламы для просмотра
            
        Returns:
            Статистика просмотра рекламы
        """
        stats = {
            "total_requested": 0,
            "total_viewed": 0,
            "total_rewards": 0,
            "errors": 0,
            "initial_progress": {},
            "final_progress": {}
        }
        
        session_name = self._get_session_name()
        logger.info(f"{session_name} | Начинаем цикл просмотра рекламы (максимум {max_ads} роликов)")
        
        # Получаем начальный прогресс
        initial_tasks = self.get_ad_tasks(init_data)
        if initial_tasks:
            for task in initial_tasks:
                if task.get("kind") in ["video_view", "video_click"]:
                    stats["initial_progress"][task.get("kind")] = {
                        "cur": task.get("cur", 0),
                        "max": task.get("max", 0)
                    }
        
        for i in range(max_ads):
            try:
                # Проверяем задания
                tasks = self.get_ad_tasks(init_data)
                if not tasks:
                    logger.info(f"{session_name} | Нет доступных заданий для рекламы")
                    break
                
                # Ищем незавершенные задания
                available_task = None
                for task in tasks:
                    if task.get("cur", 0) < task.get("max", 0):
                        available_task = task
                        break
                
                if not available_task:
                    logger.info(f"{session_name} | Все задания для рекламы выполнены")
                    break
                
                # Используем новый упрощенный метод просмотра
                logger.info(f"{session_name} | Просматриваем рекламу (попытка {i + 1}/{max_ads})")
                success = await self.watch_single_ad(init_data)
                
                if success:
                    stats["total_viewed"] += 1
                    stats["total_rewards"] += 1
                    logger.info(f"{session_name} | Реклама {i + 1} просмотрена успешно")
                    
                    # Проверяем обновленный прогресс
                    await self.check_ad_progress(init_data, delay=2)
                else:
                    stats["errors"] += 1
                    logger.warning(f"{session_name} | Ошибка при просмотре рекламы {i + 1}")
                
                stats["total_requested"] += 1
                
                # Задержка между запросами рекламы
                if i < max_ads - 1:
                    delay = random.randint(3, 7)
                    logger.info(f"{session_name} | Ожидаем {delay} секунд перед следующим запросом")
                    await asyncio.sleep(delay)
                    
            except Exception as e:
                logger.error(f"{session_name} | Ошибка в цикле просмотра рекламы: {e}")
                stats["errors"] += 1
                continue
        
        # Получаем финальный прогресс
        final_tasks = self.get_ad_tasks(init_data)
        if final_tasks:
            for task in final_tasks:
                if task.get("kind") in ["video_view", "video_click"]:
                    stats["final_progress"][task.get("kind")] = {
                        "cur": task.get("cur", 0),
                        "max": task.get("max", 0)
                    }
        
        logger.info(f"{session_name} | Цикл просмотра рекламы завершен. Статистика: {stats}")
        return stats
    
    def _parse_telegram_init_data(self, init_data: str) -> Optional[Dict[str, Any]]:
        """
        Парсинг Telegram init data.
        
        Args:
            init_data: Строка с init data
            
        Returns:
            Словарь с распарсенными данными
        """
        try:
            # Разбираем URL-encoded строку
            from urllib.parse import parse_qs, unquote
            
            parsed = parse_qs(init_data)
            result = {}
            
            for key, values in parsed.items():
                if values:
                    value = values[0]
                    if key == "user":
                        # Декодируем JSON данные пользователя
                        try:
                            result[key] = json.loads(unquote(value))
                        except json.JSONDecodeError:
                            result[key] = value
                    else:
                        result[key] = value
            
            return result
            
        except Exception as e:
            logger.error(f"Ошибка при парсинге init_data: {e}")
            return None