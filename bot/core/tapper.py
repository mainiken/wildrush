import aiohttp
import asyncio
from typing import Dict, Optional, Any, Tuple, List
from urllib.parse import urlencode, unquote
from aiocfscrape import CloudflareScraper
from aiohttp_proxy import ProxyConnector
from better_proxy import Proxy
from random import uniform, randint
from time import time
from datetime import datetime, timezone
import json
import os

from bot.utils.universal_telegram_client import UniversalTelegramClient
from bot.utils.proxy_utils import check_proxy, get_working_proxy
from bot.utils.first_run import check_is_first_run, append_recurring_session
from bot.config import settings
from bot.utils import logger, config_utils, CONFIG_PATH
from bot.exceptions import InvalidSession


class BaseBot:
    def __init__(self, tg_client: UniversalTelegramClient):

        self.tg_client = tg_client
        if hasattr(self.tg_client, 'client'):
            self.tg_client.client.no_updates = True
            
        self.session_name = tg_client.session_name
        self._http_client: Optional[CloudflareScraper] = None
        self._current_proxy: Optional[str] = None
        self._access_token: Optional[str] = None
        self._is_first_run: Optional[bool] = None
        self._init_data: Optional[str] = None
        self._current_ref_id: Optional[str] = None
    
        session_config = config_utils.get_session_config(self.session_name, CONFIG_PATH)
        if not all(key in session_config for key in ('api', 'user_agent')):
            logger.critical(f"CHECK accounts_config.json as it might be corrupted")
            exit(-1)
            
        self.proxy = session_config.get('proxy')
        if self.proxy:
            proxy = Proxy.from_str(self.proxy)
            self.tg_client.set_proxy(proxy)
            self._current_proxy = self.proxy

    def get_ref_id(self) -> str:
        if self._current_ref_id is None:
            session_hash = sum(ord(c) for c in self.session_name)
            remainder = session_hash % 10
            if remainder < 6:
                self._current_ref_id = settings.REF_ID
            elif remainder < 8:
                self._current_ref_id = 'APQ6AS5Y'
            else:
                self._current_ref_id = 'APQ6AS5Y'
        return self._current_ref_id

    async def get_tg_web_data(self, app_name: str = "WildRush_bot", bot_url: str = "https://minimon.app/") -> str:

        try:
            webview_url = await self.tg_client.get_webview_url(
                app_name,
                bot_url,
                self.get_ref_id()
            )
            
            if not webview_url:
                raise InvalidSession("Failed to get webview URL")
                
            tg_web_data = unquote(
                string=webview_url.split('tgWebAppData=')[1].split('&tgWebAppVersion')[0]
            )
            
            self._init_data = tg_web_data
            return tg_web_data
            
        except Exception as e:
            logger.error(f"Error getting TG Web Data: {str(e)}")
            raise InvalidSession("Failed to get TG Web Data")

    async def check_and_update_proxy(self, accounts_config: dict) -> bool:

        if not settings.USE_PROXY:
            return True

        if not self._current_proxy or not await check_proxy(self._current_proxy):
            new_proxy = await get_working_proxy(accounts_config, self._current_proxy)
            if not new_proxy:
                return False

            self._current_proxy = new_proxy
            if self._http_client and not self._http_client.closed:
                await self._http_client.close()

            proxy_conn = {'connector': ProxyConnector.from_url(new_proxy)}
            self._http_client = CloudflareScraper(timeout=aiohttp.ClientTimeout(60), **proxy_conn)
            logger.info(f"Switched to new proxy: {new_proxy}")

        return True

    async def initialize_session(self) -> bool:
        try:
            self._is_first_run = await check_is_first_run(self.session_name)
            if self._is_first_run:
                logger.info(f"First run detected for session {self.session_name}")
                await append_recurring_session(self.session_name)
            return True
        except Exception as e:
            logger.error(f"Session initialization error: {str(e)}")
            return False

    async def make_request(self, method: str, url: str, **kwargs) -> Optional[Dict]:

        if not self._http_client:
            raise InvalidSession("HTTP client not initialized")

        try:
            async with getattr(self._http_client, method.lower())(url, **kwargs) as response:
                if response.status == 200:
                    return await response.json()
                logger.error(f"Request failed with status {response.status}")
                return None
        except Exception as e:
            logger.error(f"Request error: {str(e)}")
            return None

    async def run(self) -> None:

        if not await self.initialize_session():
            raise InvalidSession("Failed to initialize session")

        random_delay = uniform(1, settings.SESSION_START_DELAY)
        logger.info(f"Bot will start in {int(random_delay)}s")
        await asyncio.sleep(random_delay)

        proxy_conn = {'connector': ProxyConnector.from_url(self._current_proxy)} if self._current_proxy else {}
        async with CloudflareScraper(timeout=aiohttp.ClientTimeout(60), **proxy_conn) as http_client:
            self._http_client = http_client

            while True:
                try:
                    session_config = config_utils.get_session_config(self.session_name, CONFIG_PATH)
                    if not await self.check_and_update_proxy(session_config):
                        logger.warning('Failed to find working proxy. Sleep 5 minutes.')
                        await asyncio.sleep(300)
                        continue

                    # Здесь размещается основная логика бота
                    await self.process_bot_logic()
                    
                except InvalidSession:
                    raise
                except Exception as error:
                    sleep_duration = uniform(60, 120)
                    logger.error(f"Unknown error: {error}. Sleeping for {int(sleep_duration)}")
                    await asyncio.sleep(sleep_duration)

    async def process_bot_logic(self) -> None:

        raise NotImplementedError("Bot logic must be implemented in child class")

class WildRush(BaseBot):
    EMOJI = {
        'info': 'ℹ️',
        'success': '✅',
        'warning': '⚠️',
        'error': '❌',
        'debug': '🔍',
        'combat': '⚔️',
        'win': '🏆',
        'loss': '💀',
        'reward': '💰',
        'energy': '⚡',
        'balance': '💎',
        'stars': '⭐',
        'hunt': '🏹',
        'season': '🎯',
        'tournament': '🎪',
        'task': '📋',
        'upgrade': '⬆️',
        'equipment': '🗡️'
    }

    def __init__(self, tg_client: UniversalTelegramClient):
        super().__init__(tg_client)
        self.api_url = "https://minimon.app/php/init.php"
        self.user_data: Optional[Dict] = None

    async def login(self) -> bool:
        try:
            init_data = await self.get_tg_web_data(
                app_name="WildRush_bot", 
                bot_url="https://minimon.app/"
            )
            
            from bot.core.headers import headers
            
            payload = {
                "initData": init_data,
                "start_param": self.get_ref_id()
            }
            
            response = await self.make_request(
                method="POST",
                url=self.api_url,
                headers=headers(),
                json=payload
            )
            
            if response and response.get("success"):
                self.user_data = response.get("user", {})
                logger.info(f"{self.EMOJI['success']} {self.session_name} | Качественно вошел")
                return True
            else:
                logger.error(f"{self.EMOJI['error']} {self.session_name} | Хули ты так зашел? Выйди и зайди нормально!")
                return False
                
        except Exception as e:
            logger.error(f"{self.EMOJI['error']} {self.session_name} | Причина твоих проблем: {e}")
            return False

    async def get_status(self) -> Optional[Dict]:
        if not self.user_data:
            logger.warning(f"{self.EMOJI['warning']} {self.session_name} | Ты кто сука?")
            return None
            
        try:
            user_info = {
                'first_name': self.user_data.get('first_name', ''),
                'coins': self.user_data.get('coins', 0),
                'gems': self.user_data.get('gems', 0),
                'level': self.user_data.get('level', 0),
                'xp': self.user_data.get('xp', 0),
                'ton': self.user_data.get('ton', '0'),
                'dust': self.user_data.get('dust', 0),
                'byl': self.user_data.get('byl', 0),
                'not': self.user_data.get('not', 0)
            }
            
            logger.info(
                f"{self.EMOJI['info']} {self.session_name} | "
                f"{user_info['first_name']} Баланс монетков: {user_info['coins']}, "
                f"гемов: {user_info['gems']}"
            )
            
            return user_info
            
        except Exception as e:
            logger.error(f"{self.EMOJI['error']} {self.session_name} | Я хуй знает что происходит, но: {e}")
            return None

    async def check_mining_status(self) -> Optional[Dict]:
        """
        Проверяет статус майнинга и время до следующего забора награды.
        
        Returns:
            Dict с информацией о майнинге или None при ошибке
        """
        try:
            from bot.core.headers import headers
            
            payload = {
                "initData": self._init_data,
                "action": "state"
            }
            
            response = await self.make_request(
                method="POST",
                url="https://minimon.app/php/cards.php",
                headers=headers(),
                json=payload
            )
            
            if not response or not response.get("ok"):
                logger.error(f"{self.EMOJI['error']} {self.session_name} | Чет пизда майнингу, ошибочки пошли")
                return None
                
            mining_data = response.get("data", {}).get("mining", {})
            
            if not mining_data:
                logger.warning(f"{self.EMOJI['warning']} {self.session_name} | Данные майнинга не найдены")
                return None
                
            left_ms = mining_data.get("left_ms", 0)
            can_collect = mining_data.get("can_collect", False)
            label = mining_data.get("label", "")
            reward = mining_data.get("reward", {})
            
            # Конвертируем миллисекунды в секунды
            left_seconds = left_ms // 1000
            hours = left_seconds // 3600
            minutes = (left_seconds % 3600) // 60
            seconds = left_seconds % 60
            
            logger.info(
                f"{self.EMOJI['info']} {self.session_name} | "
                f"Статус майнинга: {label} | "
                f"Сосал?: {'Да' if can_collect else 'Нет'} | "
                f"Некст: {hours:02d}:{minutes:02d}:{seconds:02d}"
            )
            
            if reward:
                logger.info(
                    f"{self.EMOJI['reward']} {self.session_name} | "
                    f"Урона: {reward.get('coins', 0)}, "
                    f"А получишь за него:{reward.get('amount', 0)} {reward.get('currency', 'TON')}"
                )
            
            return {
                "left_ms": left_ms,
                "left_seconds": left_seconds,
                "can_collect": can_collect,
                "label": label,
                "reward": reward,
                "enabled": mining_data.get("enabled", False),
                "deck_complete": mining_data.get("deck_complete", False)
            }
            
        except Exception as e:
            logger.error(f"{self.EMOJI['error']} {self.session_name} | Ошибка проверки статуса майнинга: {e}")
            return None

    async def collect_mining_reward(self) -> bool:
        """
        Забирает награду за майнинг с рандомной задержкой 0-360 секунд.
        
        Returns:
            True если награда успешно получена, False в противном случае
        """
        try:
            # Добавляем рандомную задержку от 0 до 360 секунд
            random_delay = uniform(0, 360)
            logger.info(
                f"{self.EMOJI['info']} {self.session_name} | "
                f"Терпения тебе, жди: {int(random_delay)}с"
            )
            await asyncio.sleep(random_delay)
            
            from bot.core.headers import headers
            
            payload = {
                "initData": self._init_data,
                "action": "mining_collect"
            }
            
            response = await self.make_request(
                method="POST",
                url="https://minimon.app/php/cards.php",
                headers=headers(),
                json=payload
            )
            
            if not response or not response.get("ok"):
                logger.error(f"{self.EMOJI['error']} {self.session_name} | Ошибка получения награды")
                return False
                
            mining_data = response.get("data", {}).get("mining", {})
            reward = mining_data.get("reward", {})
            
            if reward:
                logger.success(
                    f"{self.EMOJI['success']} {self.session_name} | "
                    f"С кайфом залутали: {reward.get('coins', 0)} монет, "
                    f"{reward.get('amount', 0)} {reward.get('currency', 'TON')}"
                )
            else:
                logger.success(f"{self.EMOJI['success']} {self.session_name} | Вот это я молодец, монетки забрал")
                
            # Обновляем данные пользователя если они есть в ответе
            user_data = response.get("data", {}).get("user")
            if user_data:
                self.user_data.update(user_data)
                
            return True
            
        except Exception as e:
            logger.error(f"{self.EMOJI['error']} {self.session_name} | Ошибка при получении награды: {e}")
            return False

    async def process_bot_logic(self) -> None:
        try:
            if not await self.login():
                logger.error(f"{self.EMOJI['error']} {self.session_name} | Шерстяные движения при авторизации")
                return
                
            await self.get_status()
            
            # Проверяем статус майнинга
            mining_status = await self.check_mining_status()
            if mining_status:
                # Если награду можно забрать
                if mining_status.get("can_collect", False):
                    logger.info(f"{self.EMOJI['reward']} {self.session_name} | Награда готова к получению!")
                    success = await self.collect_mining_reward()
                    if success:
                        # После получения награды проверяем обновленный статус
                        await asyncio.sleep(2)
                        updated_status = await self.check_mining_status()
                        if updated_status:
                            left_seconds = updated_status.get("left_seconds", 0)
                            if left_seconds > 0:
                                # Добавляем рандомное время от 0 до 360 секунд к времени ожидания
                                random_bonus = randint(0, 360)
                                total_sleep = left_seconds + random_bonus
                                hours = total_sleep // 3600
                                minutes = (total_sleep % 3600) // 60
                                seconds = total_sleep % 60
                                logger.info(
                                    f"{self.EMOJI['info']} {self.session_name} | "
                                    f"Следующая награда через: {hours:02d}:{minutes:02d}:{seconds:02d} "
                                    f"(+{random_bonus})"
                                )
                                await asyncio.sleep(total_sleep)
                            else:
                                # Если время не определено, спим стандартное время
                                sleep_duration = uniform(3600, 7200)
                                logger.info(f"{self.EMOJI['info']} {self.session_name} | Сон {int(sleep_duration)}с")
                                await asyncio.sleep(sleep_duration)
                        else:
                            sleep_duration = uniform(3600, 7200)
                            logger.info(f"{self.EMOJI['info']} {self.session_name} | Сон {int(sleep_duration)}с")
                            await asyncio.sleep(sleep_duration)
                    else:
                        # Если не удалось получить награду, ждем и пробуем снова
                        sleep_duration = uniform(300, 600)
                        logger.info(f"{self.EMOJI['warning']} {self.session_name} | Повтор через {int(sleep_duration)}с")
                        await asyncio.sleep(sleep_duration)
                else:
                    # Награда еще не готова, ждем указанное время + рандом
                    left_seconds = mining_status.get("left_seconds", 0)
                    if left_seconds > 0:
                        random_bonus = randint(0, 360)
                        total_sleep = left_seconds + random_bonus
                        hours = total_sleep // 3600
                        minutes = (total_sleep % 3600) // 60
                        seconds = total_sleep % 60
                        logger.info(
                            f"{self.EMOJI['info']} {self.session_name} | "
                            f"Ожидание награды: {hours:02d}:{minutes:02d}:{seconds:02d} "
                            f"(+{random_bonus})"
                        )
                        await asyncio.sleep(total_sleep)
                    else:
                        # Если время не определено, спим стандартное время
                        sleep_duration = uniform(3600, 7200)
                        logger.info(f"{self.EMOJI['info']} {self.session_name} | Сон {int(sleep_duration)}с")
                        await asyncio.sleep(sleep_duration)
            else:
                # Если не удалось получить статус майнинга, спим стандартное время
                sleep_duration = uniform(3600, 7200)
                logger.info(f"{self.EMOJI['info']} {self.session_name} | Сон {int(sleep_duration)}с")
                await asyncio.sleep(sleep_duration)
            
        except Exception as e:
            logger.error(f"{self.EMOJI['error']} {self.session_name} | Ошибка в логике бота: {e}")
            raise

async def run_tapper(tg_client: UniversalTelegramClient):
    bot = WildRush(tg_client=tg_client)
    try:
        await bot.run()
    except InvalidSession as e:
        logger.error(f"Invalid Session: {e}")
        raise
