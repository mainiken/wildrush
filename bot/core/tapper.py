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
from bot.core.ads_view_mixin import AdsViewMixin


class BaseBot:
    def __init__(self, tg_client: UniversalTelegramClient):

        self.tg_client = tg_client
        if hasattr(self.tg_client, 'client'):
            self.tg_client.client.no_updates = True
            
        self.session_name = tg_client.session_name
        self._http_client: Optional[CloudflareScraper] = None
        self._current_proxy: Optional[str] = None
        self._access_token: Optional[str] = None
        self._access_token_created_time: Optional[float] = None
        self._token_live_time: int = settings.TOKEN_LIVE_TIME
        self._is_first_run: Optional[bool] = None
        self._init_data: Optional[str] = None
        self._current_ref_id: Optional[str] = None
    
        session_config = config_utils.get_session_config(self._get_session_name(), CONFIG_PATH)
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
            session_hash = sum(ord(c) for c in self._get_session_name())
            remainder = session_hash % 10
            if remainder < 6:
                self._current_ref_id = settings.REF_ID
            elif remainder < 8:
                self._current_ref_id = 'APQ6AS5Y'
            else:
                self._current_ref_id = 'APQ6AS5Y'
        return self._current_ref_id

    def _is_token_expired(self) -> bool:
        """Проверяет, истек ли токен"""
        if self._access_token_created_time is None:
            return True
        return time() - self._access_token_created_time > self._token_live_time

    async def _restart_authorization(self) -> bool:
        """Перезапускает авторизацию с получением новых init_data"""
        try:
            # Сбрасываем старые данные
            self._init_data = None
            self._access_token = None
            self._access_token_created_time = None
            
            # Получаем новые init_data
            await self.get_tg_web_data()
            
            # Обновляем время создания токена
            self._access_token_created_time = time()
            
            return True
            
        except Exception as e:
            logger.error(f"{self._get_session_name()} | Ошибка при обновлении init_data: {e}")
            return False

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
            # Устанавливаем время создания токена при получении новых init_data
            if self._access_token_created_time is None:
                self._access_token_created_time = time()
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
            self._is_first_run = await check_is_first_run(self._get_session_name())
            if self._is_first_run:
                logger.info(f"First run detected for session {self._get_session_name()}")
                await append_recurring_session(self._get_session_name())
            return True
        except Exception as e:
            logger.error(f"Session initialization error: {str(e)}")
            return False

    async def make_request(self, method: str, url: str, **kwargs) -> Optional[Dict]:

        if not self._http_client:
            raise InvalidSession("HTTP client not initialized")

        for attempt in range(2):
            try:
                async with getattr(self._http_client, method.lower())(url, **kwargs) as response:
                    if response.status == 200:
                        return await response.json()
                    
                    if response.status in (502, 503, 504):
                        from bot.exceptions import ServerUnavailableError
                        logger.warning(f"\u0421\u0435\u0440\u0432\u0435\u0440 \u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u0435\u043d ({response.status}), \u043f\u043e\u0432\u0442\u043e\u0440 \u0447\u0435\u0440\u0435\u0437 10\u0441...")
                        if attempt < 1:
                            await asyncio.sleep(10)
                            continue
                        else:
                            raise ServerUnavailableError(f"Server unavailable: {response.status}")
                    
                    if response.status == 400:
                        try:
                            error_data = await response.json()
                            error_message = error_data.get("message", "Unknown error")
                            logger.error(f"Request failed with status 400: {error_message}")
                        except:
                            response_text = await response.text()
                            logger.error(f"Request failed with status 400: {response_text[:200]}")
                    else:
                        logger.error(f"Request failed with status {response.status}")
                    return None
            except Exception as e:
                if "ServerUnavailableError" in str(type(e).__name__):
                    raise
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
                    session_config = config_utils.get_session_config(self._get_session_name(), CONFIG_PATH)
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

class WildRush(BaseBot, AdsViewMixin):
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
        AdsViewMixin.__init__(self)
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
                logger.info(f"{self.EMOJI['success']} {self._get_session_name()} | Качественно вошел")
                return True
            else:
                logger.error(f"{self.EMOJI['error']} {self._get_session_name()} | Хули ты так зашел? Выйди и зайди нормально!")
                return False
                
        except Exception as e:
            logger.error(f"{self.EMOJI['error']} {self._get_session_name()} | Причина твоих проблем: {e}")
            return False

    async def get_status(self) -> Optional[Dict]:
        if not self.user_data:
            logger.warning(f"{self.EMOJI['warning']} {self._get_session_name()} | Ты кто сука?")
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
                f"{self.EMOJI['info']} {self._get_session_name()} | "
                f"{user_info['first_name']} Баланс монетков: {user_info['coins']}, "
                f"гемов: {user_info['gems']}"
            )
            
            return user_info
            
        except Exception as e:
            logger.error(f"{self.EMOJI['error']} {self._get_session_name()} | Я хуй знает что происходит, но: {e}")
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
                logger.error(f"{self.EMOJI['error']} {self._get_session_name()} | Чет пизда майнингу, ошибочки пошли")
                return None
                
            mining_data = response.get("data", {}).get("mining", {})
            
            if not mining_data:
                logger.warning(f"{self.EMOJI['warning']} {self._get_session_name()} | Данные майнинга не найдены")
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
                f"{self.EMOJI['info']} {self._get_session_name()} | "
                f"Статус майнинга: {label} | "
                f"Сосал?: {'Да' if can_collect else 'Нет'} | "
                f"Некст: {hours:02d}:{minutes:02d}:{seconds:02d}"
            )
            
            if reward:
                logger.info(
                    f"{self.EMOJI['reward']} {self._get_session_name()} | "
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
            logger.error(f"{self.EMOJI['error']} {self._get_session_name()} | Ошибка проверки статуса майнинга: {e}")
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
                f"{self.EMOJI['info']} {self._get_session_name()} | "
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
                logger.error(f"{self.EMOJI['error']} {self._get_session_name()} | Ошибка получения награды")
                return False
                
            mining_data = response.get("data", {}).get("mining", {})
            reward = mining_data.get("reward", {})
            
            if reward:
                logger.success(
                    f"{self.EMOJI['success']} {self._get_session_name()} | "
                    f"С кайфом залутали: {reward.get('coins', 0)} монет, "
                    f"{reward.get('amount', 0)} {reward.get('currency', 'TON')}"
                )
            else:
                logger.success(f"{self.EMOJI['success']} {self._get_session_name()} | Вот это я молодец, монетки забрал")
                
            # Обновляем данные пользователя если они есть в ответе
            user_data = response.get("data", {}).get("user")
            if user_data:
                self.user_data.update(user_data)
                
            return True
            
        except Exception as e:
            logger.error(f"{self.EMOJI['error']} {self._get_session_name()} | Ошибка при получении награды: {e}")
            return False

    async def check_premium_active(self) -> Optional[bool]:
        """
        Проверяет наличие активного премиум-пасса у текущего аккаунта.

        Returns:
            True при активном премиуме, False при неактивном, None при ошибке
        """
        try:
            from bot.core.headers import headers

            payload = {
                "initData": self._init_data
            }

            response = await self.make_request(
                method="POST",
                url="https://minimon.app/php/get_wallet.php",
                headers=headers(),
                json=payload
            )

            if not response:
                logger.error(
                    f"{self.EMOJI['error']} {self._get_session_name()} | "
                    f"Не удалось проверить статус премиума"
                )
                return None

            data = response.get("data", response)
            is_premium = data.get("is_premium")

            if isinstance(is_premium, bool):
                return is_premium
            if isinstance(is_premium, int):
                return is_premium == 1

            # На случай иной схемы ответа: isPremium
            is_premium_alt = data.get("isPremium")
            if isinstance(is_premium_alt, bool):
                return is_premium_alt
            if isinstance(is_premium_alt, int):
                return is_premium_alt == 1

            logger.warning(
                f"{self.EMOJI['warning']} {self._get_session_name()} | "
                f"Поле статуса премиума не найдено в ответе"
            )
            return None
        except Exception as e:
            logger.error(
                f"{self.EMOJI['error']} {self._get_session_name()} | "
                f"Ошибка проверки премиума: {e}"
            )
            return None

    async def get_premium_state(self) -> Optional[Dict[str, Any]]:
        """
        Получает состояние премиум-пасса и время до ближайшего клейма.

        Returns:
            Dict с ключами: is_premium, next_claim_at (datetime), sleep_seconds
            или None при ошибке
        """
        try:
            from bot.core.headers import headers
            from datetime import datetime, timezone
            from time import time

            payload = {
                "initData": self._init_data,
                "action": "state"
            }

            response = await self.make_request(
                method="POST",
                url="https://minimon.app/php/premium.php",
                headers=headers(),
                json=payload
            )

            if not response or not response.get("ok"):
                logger.error(
                    f"{self.EMOJI['error']} {self._get_session_name()} | "
                    f"Не удалось получить состояние премиума"
                )
                return None

            data = response.get("data", {})
            is_premium = data.get("isPremium", False)
            next_claim_ms = data.get("nextClaimAt")

            if next_claim_ms is None:
                logger.warning(
                    f"{self.EMOJI['warning']} {self._get_session_name()} | "
                    f"В ответе отсутствует nextClaimAt"
                )
                return None

            now_sec = time()
            next_claim_sec = max(0, int(next_claim_ms / 1000))
            sleep_seconds = max(0, next_claim_sec - int(now_sec))

            result = {
                "is_premium": bool(is_premium),
                "next_claim_at": datetime.fromtimestamp(next_claim_sec, tz=timezone.utc),
                "sleep_seconds": sleep_seconds
            }

            return result
        except Exception as e:
            logger.error(
                f"{self.EMOJI['error']} {self._get_session_name()} | "
                f"Ошибка получения состояния премиума: {e}"
            )
            return None

    async def sleep_until_next_premium_event(self) -> None:
        """
        Проверяет наличие премиума и засыпает до ближайшего события премиума.
        Если премиум отсутствует или время не найдено, завершает без ожидания.
        """
        try:
            premium_active = await self.check_premium_active()
            if premium_active is False:
                logger.info(
                    f"{self.EMOJI['info']} {self._get_session_name()} | "
                    f"Премиум-пасс не активен, ожидание не требуется"
                )
                return

            if premium_active is None:
                logger.warning(
                    f"{self.EMOJI['warning']} {self._get_session_name()} | "
                    f"Статус премиума неизвестен, пропускаю ожидание"
                )
                return

            state = await self.get_premium_state()
            if not state:
                logger.warning(
                    f"{self.EMOJI['warning']} {self._get_session_name()} | "
                    f"Не удалось определить время события премиума"
                )
                return

            if not state.get("is_premium", False):
                logger.info(
                    f"{self.EMOJI['info']} {self._get_session_name()} | "
                    f"Премиум-пасс не активен по данным состояния"
                )
                return

            sleep_seconds = state.get("sleep_seconds", 0)
            if sleep_seconds <= 0:
                logger.info(
                    f"{self.EMOJI['info']} {self._get_session_name()} | "
                    f"Событие уже доступно или время неизвестно"
                )
                return

            bonus = randint(0, 60)
            total_sleep = sleep_seconds + bonus
            hours = total_sleep // 3600
            minutes = (total_sleep % 3600) // 60
            seconds = total_sleep % 60

            logger.info(
                f"{self.EMOJI['info']} {self._get_session_name()} | "
                f"Сон до премиума: {hours:02d}:{minutes:02d}:{seconds:02d}"
            )
            await asyncio.sleep(total_sleep)
        except Exception as e:
            logger.error(
                f"{self.EMOJI['error']} {self._get_session_name()} | "
                f"Ошибка ожидания премиум события: {e}"
            )

    async def sleep_until_nearest_event(self, mining_left_seconds: Optional[int]) -> None:
        """
        Засыпает до ближайшего события: майнинг или премиум-клейм.
        При отсутствии обоих времен использует стандартное ожидание.
        """
        try:
            premium_seconds: Optional[int] = None
            premium_active = await self.check_premium_active()
            if premium_active is True:
                state = await self.get_premium_state()
                if state and state.get("is_premium", False):
                    sec = int(state.get("sleep_seconds", 0))
                    if sec > 0:
                        premium_seconds = sec

            candidates = []
            if mining_left_seconds and mining_left_seconds > 0:
                candidates.append((mining_left_seconds, "Майнинг"))
            if premium_seconds and premium_seconds > 0:
                candidates.append((premium_seconds, "Премиум"))

            if candidates:
                sleep_seconds, source = min(candidates, key=lambda x: x[0])
                hours = sleep_seconds // 3600
                minutes = (sleep_seconds % 3600) // 60
                seconds = sleep_seconds % 60
                logger.info(
                    f"{self.EMOJI['info']} {self._get_session_name()} | "
                    f"Ожидание ближайшего события [{source}]: "
                    f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                )
                await asyncio.sleep(sleep_seconds)
                return

            sleep_duration = uniform(3600, 7200)
            logger.info(
                f"{self.EMOJI['info']} {self._get_session_name()} | "
                f"Сон {int(sleep_duration)}с"
            )
            await asyncio.sleep(sleep_duration)
        except Exception as e:
            logger.error(
                f"{self.EMOJI['error']} {self._get_session_name()} | "
                f"Ошибка ожидания ближайшего события: {e}"
            )

    async def claim_premium_reward(self) -> bool:
        """
        Получает награду премиум-пасса и логирует результат.

        Returns:
            True если награда успешно получена, False в противном случае
        """
        try:
            from bot.core.headers import headers

            random_delay = uniform(2, 8)
            logger.info(
                f"{self.EMOJI['info']} {self._get_session_name()} | "
                f"Небольшая задержка перед клеймом: {int(random_delay)}с"
            )
            await asyncio.sleep(random_delay)

            payload = {
                "initData": self._init_data,
                "action": "claim"
            }

            response = await self.make_request(
                method="POST",
                url="https://minimon.app/php/premium.php",
                headers=headers(),
                json=payload
            )

            if not response or not response.get("ok"):
                logger.error(
                    f"{self.EMOJI['error']} {self._get_session_name()} | "
                    f"Ошибка получения награды премиума"
                )
                return False

            data = response.get("data", {})
            applied = data.get("applied", {})
            reward_type = applied.get("type")
            reward_qty = applied.get("qty")
            balances = data.get("balances", {})

            if reward_type and reward_qty is not None:
                logger.success(
                    f"{self.EMOJI['success']} {self._get_session_name()} | "
                    f"Премиум награда: {reward_qty} {reward_type}"
                )
            else:
                logger.success(
                    f"{self.EMOJI['success']} {self._get_session_name()} | "
                    f"Премиум награда получена"
                )

            if balances:
                coins = balances.get("coins")
                gems = balances.get("gems")
                dust = balances.get("dust")
                ton = balances.get("ton")
                logger.info(
                    f"{self.EMOJI['balance']} {self._get_session_name()} | "
                    f"Баланс: монет={coins}, гемов={gems}, пыли={dust}, TON={ton}"
                )

            next_claim_ms = data.get("nextClaimAt")
            if next_claim_ms:
                from time import time
                left_seconds = max(0, int(next_claim_ms / 1000) - int(time()))
                hours = left_seconds // 3600
                minutes = (left_seconds % 3600) // 60
                seconds = left_seconds % 60
                logger.info(
                    f"{self.EMOJI['info']} {self._get_session_name()} | "
                    f"Следующий премиум-клейм через: {hours:02d}:{minutes:02d}:{seconds:02d}"
                )

            return True
        except Exception as e:
            logger.error(
                f"{self.EMOJI['error']} {self._get_session_name()} | "
                f"Ошибка клейма премиума: {e}"
            )
            return False

    async def get_tasks_list(self) -> Optional[List[Dict]]:
        """
        Получает список всех доступных заданий.
        
        Returns:
            List[Dict] со списком заданий или None при ошибке
        """
        try:
            from bot.core.headers import headers
            
            payload = {
                "initData": self._init_data,
                "action": "list"
            }
            
            response = await self.make_request(
                method="POST",
                url="https://minimon.app/php/tasks.php",
                headers=headers(),
                json=payload
            )
            
            if not response or not response.get("ok"):
                logger.error(f"{self.EMOJI['error']} {self._get_session_name()} | Ошибка получения списка заданий")
                return None
                
            tasks = response.get("data", {}).get("tasks", [])
            logger.info(f"{self.EMOJI['task']} {self._get_session_name()} | Получено {len(tasks)} заданий")
            
            return tasks
            
        except Exception as e:
            logger.error(f"{self.EMOJI['error']} {self._get_session_name()} | Ошибка при получении заданий: {e}")
            return None

    async def start_task(self, task_id: int) -> Optional[Dict]:
        """
        Запускает выполнение задания.
        
        Args:
            task_id: ID задания для запуска
            
        Returns:
            Dict с результатом запуска или None при ошибке
        """
        try:
            from bot.core.headers import headers
            
            payload = {
                "initData": self._init_data,
                "action": "start",
                "task_id": task_id
            }
            
            response = await self.make_request(
                method="POST",
                url="https://minimon.app/php/tasks.php",
                headers=headers(),
                json=payload
            )
            
            if not response:
                logger.error(f"{self.EMOJI['error']} {self._get_session_name()} | Не удалось получить ответ при запуске задания {task_id}")
                return None
                
            if not response.get("ok"):
                error_message = response.get("message", "Неизвестная ошибка")
                logger.error(f"{self.EMOJI['error']} {self._get_session_name()} | Ошибка запуска задания {task_id}: {error_message}")
                return None
                
            data = response.get("data", {})
            verify_delay = data.get("verify_delay_sec", 0)
            
            logger.debug(f"{self.EMOJI['task']} {self._get_session_name()} | Задание {task_id} запущено, ожидание {verify_delay}с")
            
            return data
            
        except Exception as e:
            logger.error(f"{self.EMOJI['error']} {self._get_session_name()} | Ошибка при запуске задания {task_id}: {e}")
            return None

    async def claim_task_reward(self, task_id: int, task_name: str = "", task_desc: str = "", task_rewards: List[Dict] = None) -> bool:
        """
        Забирает награду за выполненное задание.
        
        Args:
            task_id: ID задания для получения награды
            task_name: Название задания для логирования
            task_desc: Описание задания для логирования
            task_rewards: Список наград задания для логирования
            
        Returns:
            True если награда получена, False в противном случае
        """
        try:
            from bot.core.headers import headers
            
            payload = {
                "initData": self._init_data,
                "action": "claim",
                "task_id": task_id
            }
            
            response = await self.make_request(
                method="POST",
                url="https://minimon.app/php/tasks.php",
                headers=headers(),
                json=payload
            )
            
            if not response or not response.get("ok"):
                logger.error(f"{self.EMOJI['error']} {self._get_session_name()} | Ошибка получения награды за задание {task_id}")
                return False
                
            data = response.get("data", {})
            balances = data.get("balances", {})
            
            # Формируем строку с наградами
            rewards_text = ""
            if task_rewards:
                reward_parts = []
                for reward in task_rewards:
                    reward_type = reward.get("type", "")
                    reward_amount = reward.get("amount", 0)
                    if reward_type == "coin":
                        reward_parts.append(f"{reward_amount} монет")
                    elif reward_type == "gem":
                        reward_parts.append(f"{reward_amount} гемов")
                    elif reward_type == "dust":
                        reward_parts.append(f"{reward_amount} пыли")
                    else:
                        reward_parts.append(f"{reward_amount} {reward_type}")
                rewards_text = ", ".join(reward_parts)
            
            # Формируем сообщение
            if task_name and task_desc:
                message = f"'{task_name}' '{task_desc}' выполнено!"
            elif task_name:
                message = f"'{task_name}' выполнено!"
            else:
                message = f"Задание {task_id} выполнено!"
                
            if rewards_text:
                message += f" Награда: {rewards_text}!"
            
            logger.success(f"{self.EMOJI['success']} {self._get_session_name()} | {message}")
            
            # Обновляем данные пользователя если они есть
            if self.user_data and balances:
                self.user_data.update(balances)
                
            return True
            
        except Exception as e:
            logger.error(f"{self.EMOJI['error']} {self._get_session_name()} | Ошибка при получении награды за задание {task_id}: {e}")
            return False

    async def complete_task(self, task: Dict) -> bool:
        """
        Выполняет одно задание полностью (запуск + ожидание + получение награды).
        
        Args:
            task: Словарь с данными задания
            
        Returns:
            True если задание выполнено успешно, False в противном случае
        """
        try:
            task_id = task.get("id")
            task_name = task.get("name", "")
            task_desc = task.get("desc", "")
            task_rewards = task.get("rewards", [])
            task_can_claim = task.get("canClaim", False)
            task_done = task.get("done", False)
            task_cur = task.get("cur", 0)
            task_max = task.get("max", 1)
            
            # Если задание уже готово к получению награды
            if task_can_claim:
                success = await self.claim_task_reward(task_id, task_name, task_desc, task_rewards)
                return success
            
            # Если задание уже выполнено, но награда не готова
            if task_done:
                logger.debug(f"{self.EMOJI['info']} {self._get_session_name()} | Задание '{task_name}' уже выполнено, ожидаем готовности награды")
                return True
            
            # Проверяем, можно ли запустить задание
            if task_cur >= task_max:
                logger.debug(f"{self.EMOJI['warning']} {self._get_session_name()} | Задание '{task_name}' уже достигло максимального прогресса ({task_cur}/{task_max})")
                return True
            
            # Запускаем новое задание
            logger.debug(f"{self.EMOJI['task']} {self._get_session_name()} | Запускаем задание '{task_name}' (ID: {task_id})")
            start_result = await self.start_task(task_id)
            if not start_result:
                logger.warning(f"{self.EMOJI['warning']} {self._get_session_name()} | Не удалось запустить задание '{task_name}' (возможно, оно недоступно)")
                return False
                
            # Ждем время верификации
            verify_delay = start_result.get("verify_delay_sec", 8)
            if verify_delay > 0:
                await asyncio.sleep(verify_delay)
            
            # Добавляем небольшую дополнительную задержку
            additional_delay = uniform(2, 5)
            await asyncio.sleep(additional_delay)
            
            # Получаем награду
            success = await self.claim_task_reward(task_id, task_name, task_desc, task_rewards)
            return success
                
        except Exception as e:
            logger.error(f"{self.EMOJI['error']} {self._get_session_name()} | Ошибка при выполнении задания: {e}")
            return False

    async def process_ad_tasks(self) -> None:
        """
        Обрабатывает рекламные задания независимо от AUTO_DAILY_TASKS.
        """
        try:
            # Проверяем блеклист для автоматического просмотра рекламы
            session_name = self._get_session_name()
            if settings.is_ads_viewing_disabled_for_session(session_name):
                if settings.AUTO_ADS_VIEWING == "ALL":
                    logger.info(f"{self.EMOJI['info']} {session_name} | Автоматический просмотр рекламы отключен для всех сессий")
                else:
                    logger.info(f"{self.EMOJI['info']} {session_name} | Автоматический просмотр рекламы отключен для этой сессии")
                return
                
            logger.info(f"{self.EMOJI['task']} {self._get_session_name()} | Начинаем поиск рекламных заданий...")
            
            # Получаем список заданий
            tasks = await self.get_tasks_list()
            if not tasks:
                logger.warning(f"{self.EMOJI['warning']} {self._get_session_name()} | Не удалось получить список заданий")
                return
            
            # Фильтруем только рекламные задания
            ad_tasks = []
            claimable_ad_tasks = []
            
            logger.info(f"{self.EMOJI['debug']} {self._get_session_name()} | Всего получено заданий: {len(tasks)}")
            
            for task in tasks:
                task_kind = task.get("kind", "")
                task_done = task.get("done", False)
                task_can_claim = task.get("canClaim", False)
                task_cur = task.get("cur", 0)
                task_max = task.get("max", 1)
                task_name = task.get("name", "")
                
                # Ищем только video_view и video_click задания
                is_ad_task = task_kind in ["video_view", "video_click"]
                
                if is_ad_task:
                    logger.info(f"{self.EMOJI['debug']} {self._get_session_name()} | Найдено видео задание: '{task_name}' (kind='{task_kind}', done={task_done}, canClaim={task_can_claim}, прогресс={task_cur}/{task_max})")
                    if task_can_claim:
                        claimable_ad_tasks.append(task)
                        logger.info(f"{self.EMOJI['info']} {self._get_session_name()} | Задание готово к получению награды: '{task_name}'")
                    elif not task_done and not task_can_claim:
                        ad_tasks.append(task)
                        remaining = task_max - task_cur
                        logger.info(f"{self.EMOJI['info']} {self._get_session_name()} | Добавлено видео задание в очередь: '{task_name}' (осталось выполнить: {remaining})")
            
            total_ad_tasks = len(ad_tasks) + len(claimable_ad_tasks)
            
            if total_ad_tasks == 0:
                logger.info(f"{self.EMOJI['info']} {self._get_session_name()} | Нет доступных видео заданий (video_view/video_click)")
                return
            
            logger.info(f"{self.EMOJI['info']} {self._get_session_name()} | Найдено {len(claimable_ad_tasks)} готовых к получению наград и {len(ad_tasks)} новых видео заданий")
            
            completed_count = 0
            
            # Сначала забираем готовые награды за рекламные задания
            for task in claimable_ad_tasks:
                task_name = task.get("name", "")
                task_desc = task.get("desc", "")
                task_rewards = task.get("rewards", [])
                task_id = task.get("id")
                
                # Добавляем задержку между заданиями
                delay = uniform(2, 5)
                await asyncio.sleep(delay)
                
                success = await self.claim_task_reward(task_id, task_name, task_desc, task_rewards)
                if success:
                    completed_count += 1
                    
                # Дополнительная задержка после получения награды
                await asyncio.sleep(uniform(1, 3))
            
            # Затем выполняем новые рекламные задания
            for ad_task in ad_tasks:
                try:
                    # Получаем init_data для рекламных запросов
                    init_data = await self.get_tg_web_data()
                    
                    # Запускаем просмотр рекламы
                    result = await self.watch_ads_cycle(init_data, max_attempts=100)
                    success = result.get('success', False)
                    if success:
                        completed_count += 1
                        logger.info(f"{self.EMOJI['success']} {self._get_session_name()} | Рекламное задание выполнено: {ad_task.get('name', '')}")
                    else:
                        logger.warning(f"{self.EMOJI['warning']} {self._get_session_name()} | Не удалось выполнить рекламное задание: {ad_task.get('name', '')}")
                    
                    # Задержка между рекламными заданиями
                    await asyncio.sleep(uniform(5, 10))
                    
                except Exception as ad_error:
                    logger.error(f"{self.EMOJI['error']} {self._get_session_name()} | Ошибка при выполнении рекламного задания: {ad_error}")
            
            if completed_count > 0:
                logger.info(f"{self.EMOJI['success']} {self._get_session_name()} | Обработано {completed_count} рекламных заданий")
            
        except Exception as e:
            logger.error(f"{self.EMOJI['error']} {self._get_session_name()} | Ошибка при обработке рекламных заданий: {e}")

    async def process_tasks(self) -> None:
        """
        Обрабатывает все доступные задания, исключая рекламные (video_view, video_click).
        """
        try:
            # Проверяем флаг автоматического выполнения ежедневных заданий
            if not settings.AUTO_DAILY_TASKS:
                logger.info(f"{self.EMOJI['info']} {self._get_session_name()} | Автоматическое выполнение ежедневных заданий отключено")
                return
                
            logger.info(f"{self.EMOJI['task']} {self._get_session_name()} | Начинаем обработку заданий...")
            
            # Получаем список заданий
            tasks = await self.get_tasks_list()
            if not tasks:
                logger.warning(f"{self.EMOJI['warning']} {self._get_session_name()} | Не удалось получить список заданий")
                return
            
            # Фильтруем задания с правильной логикой статусов (исключаем рекламные)
            available_tasks = []
            claimable_tasks = []
            
            for task in tasks:
                task_kind = task.get("kind", "")
                task_done = task.get("done", False)
                task_can_claim = task.get("canClaim", False)
                task_cur = task.get("cur", 0)
                task_max = task.get("max", 1)
                task_name = task.get("name", "")
                
                # Пропускаем рекламные задания (они обрабатываются отдельно)
                is_ad_task = task_kind in ["video_view", "video_click"]
                
                if is_ad_task:
                    logger.debug(f"{self.EMOJI['debug']} {self._get_session_name()} | Пропускаем рекламное задание: '{task_name}' (обрабатывается отдельно)")
                    continue
                
                # Пропускаем автоматические задания (computed, ads_threshold)
                if task_kind in ["computed", "ads_threshold"]:
                    # logger.debug(f"{self.EMOJI['debug']} {self._get_session_name()} | Пропускаем автоматическое задание: {task_name}")
                    continue
                
                # Логика обработки статусов:
                if task_can_claim:
                    # Задание готово к получению награды
                    claimable_tasks.append(task)
                elif not task_done and task_cur < task_max:
                    # Задание не выполнено и есть прогресс для выполнения
                    available_tasks.append(task)
            
            total_tasks = len(available_tasks) + len(claimable_tasks)
            
            logger.info(f"{self.EMOJI['info']} {self._get_session_name()} | Найдено {len(claimable_tasks)} заданий с готовыми наградами и {len(available_tasks)} новых заданий")
            
            if total_tasks == 0:
                logger.info(f"{self.EMOJI['info']} {self._get_session_name()} | Нет доступных заданий для обработки")
                return
            
            completed_count = 0
            
            # Сначала забираем готовые награды
            for task in claimable_tasks:
                task_name = task.get("name", "")
                task_desc = task.get("desc", "")
                task_rewards = task.get("rewards", [])
                task_id = task.get("id")
                
                # Добавляем задержку между заданиями
                delay = uniform(2, 5)
                await asyncio.sleep(delay)
                
                success = await self.claim_task_reward(task_id, task_name, task_desc, task_rewards)
                if success:
                    completed_count += 1
                    
                # Дополнительная задержка после получения награды
                await asyncio.sleep(uniform(1, 3))
            
            # Затем выполняем новые задания
            for task in available_tasks:
                # Добавляем задержку между заданиями
                delay = uniform(3, 8)
                await asyncio.sleep(delay)
                
                success = await self.complete_task(task)
                if success:
                    completed_count += 1
                    
                # Дополнительная задержка после выполнения
                await asyncio.sleep(uniform(2, 5))
            
            logger.info(f"{self.EMOJI['success']} {self._get_session_name()} | Обработано {completed_count} из {total_tasks} заданий")
            
        except Exception as e:
            logger.error(f"{self.EMOJI['error']} {self._get_session_name()} | Ошибка при обработке заданий: {e}")

    async def get_bonus_correct_answers(self) -> Optional[Tuple[List[int], str]]:
        """
        Получает правильные ответы для ежедневного бонуса из GitHub Gist.
        
        Returns:
            Tuple[List[int], str] с правильными индексами и датой или None при ошибке
        """
        try:
            gist_url = "https://gist.githubusercontent.com/mainiken/b91f1e6353271d76b9864ae599ca7942/raw/promocode_data.json"
            
            if not self._http_client:
                logger.error(f"{self.EMOJI['error']} {self._get_session_name()} | HTTP клиент не инициализирован")
                return None
            
            # Используем прямой HTTP запрос для получения текстовых данных
            async with self._http_client.get(gist_url) as response:
                if response.status != 200:
                    logger.error(f"{self.EMOJI['error']} {self._get_session_name()} | Ошибка получения данных бонуса: {response.status}")
                    return None
                
                text_data = await response.text()
                logger.debug(f"{self.EMOJI['debug']} {self._get_session_name()} | Получен ответ от Gist: '{text_data[:200]}...'")
                
                if not text_data.strip() or text_data.strip().lower() == 'none':
                    logger.warning(f"{self.EMOJI['warning']} {self._get_session_name()} | GitHub Gist содержит некорректные данные: '{text_data.strip()}'")
                    return None
                
                # Парсим JSON из текстового ответа
                data = json.loads(text_data)
                
            correct_idx = data.get("correctIdx", [])
            gist_day = data.get("day", "")
            
            logger.info(
                f"{self.EMOJI['info']} {self._get_session_name()} | "
                f"Получены правильные ответы для {gist_day}: {correct_idx}"
            )
            
            return correct_idx, gist_day
            
        except json.JSONDecodeError as e:
            logger.error(f"{self.EMOJI['error']} {self._get_session_name()} | Ошибка парсинга JSON: {e}")
            return None
        except Exception as e:
            logger.error(f"{self.EMOJI['error']} {self._get_session_name()} | Ошибка получения правильных ответов: {e}")
            return None

    async def validate_bonus_data_sync(self, api_day: str, gist_day: str) -> bool:
        """
        Проверяет синхронизацию данных между API и Gist.
        
        Args:
            api_day: Дата из API bonus.php
            gist_day: Дата из GitHub Gist
            
        Returns:
            True если данные можно использовать, False в противном случае
        """
        try:
            if not api_day or not gist_day:
                logger.warning(f"{self.EMOJI['warning']} {self._get_session_name()} | Отсутствуют данные о дате")
                return False
                
            # Логируем несоответствие дат, но продолжаем использовать данные
            if api_day != gist_day:
                logger.info(
                    f"{self.EMOJI['info']} {self._get_session_name()} | "
                    f"Даты не совпадают: API: {api_day}, Gist: {gist_day}. "
                    f"Используем доступные данные из Gist."
                )
                # Возвращаем True, так как данные можно использовать
                return True
                
            logger.info(
                f"{self.EMOJI['success']} {self._get_session_name()} | "
                f"Данные синхронизированы для {api_day}"
            )
            return True
            
        except Exception as e:
            logger.error(f"{self.EMOJI['error']} {self._get_session_name()} | Ошибка проверки синхронизации: {e}")
            return False

    async def check_bonus_status(self) -> Optional[Dict]:
        """
        Проверяет статус ежедневного бонуса.
        
        Returns:
            Dict с информацией о бонусе или None при ошибке
        """
        try:
            from bot.core.headers import headers
            
            payload = {
                "initData": self._init_data,
                "action": "status"
            }
            
            response = await self.make_request(
                method="POST",
                url="https://minimon.app/php/bonus.php",
                headers=headers(),
                json=payload
            )
            
            if not response or not response.get("ok"):
                logger.error(f"{self.EMOJI['error']} {self._get_session_name()} | Ошибка проверки статуса бонуса")
                return None
                
            bonus_data = response.get("data", {})
            day = bonus_data.get("day", "")
            grid_size = bonus_data.get("grid_size", 0)
            correct_targets = bonus_data.get("correct_targets", 0)
            already_claimed = bonus_data.get("already_claimed", False)
            
            logger.info(
                f"{self.EMOJI['info']} {self._get_session_name()} | "
                f"Статус бонуса на {day}: "
                f"{'Уже получен' if already_claimed else 'Доступен'} | "
                f"Сетка: {grid_size}, Целей: {correct_targets}"
            )
            
            return bonus_data
            
        except Exception as e:
            logger.error(f"{self.EMOJI['error']} {self._get_session_name()} | Ошибка проверки статуса бонуса: {e}")
            return None

    async def claim_bonus_reward(self, correct_answers: List[int]) -> bool:
        """
        Получает награду за ежедневный бонус.
        
        Args:
            correct_answers: Список правильных индексов
            
        Returns:
            True если награда успешно получена, False в противном случае
        """
        try:
            from bot.core.headers import headers
            
            payload = {
                "initData": self._init_data,
                "action": "claim",
                "selected": correct_answers
            }
            
            response = await self.make_request(
                method="POST",
                url="https://minimon.app/php/bonus.php",
                headers=headers(),
                json=payload
            )
            
            if not response or not response.get("ok"):
                logger.error(f"{self.EMOJI['error']} {self._get_session_name()} | Ошибка получения бонуса")
                return False
                
            bonus_data = response.get("data", {})
            day = bonus_data.get("day", "")
            ok_count = bonus_data.get("ok", 0)
            total_count = bonus_data.get("total", 0)
            coins = bonus_data.get("coins", 0)
            gems = bonus_data.get("gems", 0)
            correct_idx = bonus_data.get("correctIdx", [])
            selected_idx = bonus_data.get("selectedIdx", [])
            
            logger.success(
                f"{self.EMOJI['success']} {self._get_session_name()} | "
                f"Бонус за {day} получен! "
                f"Угадано: {ok_count}/{total_count} | "
                f"Награда: {coins} монет, {gems} гемов"
            )
            
            logger.debug(
                f"{self.EMOJI['debug']} {self._get_session_name()} | "
                f"Правильные: {correct_idx}, Выбранные: {selected_idx}"
            )
            
            # Обновляем данные пользователя если они есть в ответе
            if self.user_data and coins > 0:
                self.user_data['coins'] = self.user_data.get('coins', 0) + coins
                self.user_data['gems'] = self.user_data.get('gems', 0) + gems
                
            return True
            
        except Exception as e:
            logger.error(f"{self.EMOJI['error']} {self._get_session_name()} | Ошибка при получении бонуса: {e}")
            return False

    async def process_daily_bonus(self) -> None:
        """
        Обрабатывает ежедневный бонус: проверяет статус и получает награду если возможно.
        """
        try:
            if not settings.AUTO_BONUS_CLAIM:
                logger.debug(f"{self.EMOJI['debug']} {self._get_session_name()} | Автоматическое получение бонусов отключено")
                return
                
            logger.info(f"{self.EMOJI['info']} {self._get_session_name()} | Проверяем ежедневный бонус...")
            
            # Проверяем статус бонуса
            bonus_status = await self.check_bonus_status()
            if not bonus_status:
                return
                
            # Если бонус уже получен, выходим
            if bonus_status.get("already_claimed", False):
                logger.info(f"{self.EMOJI['info']} {self._get_session_name()} | Ежедневный бонус уже получен")
                return
                
            api_day = bonus_status.get("day", "")
            
            # Получаем правильные ответы и дату из Gist
            gist_data = await self.get_bonus_correct_answers()
            if not gist_data:
                logger.warning(
                    f"{self.EMOJI['warning']} {self._get_session_name()} | "
                    f"Не удалось получить правильные ответы из Gist. "
                    f"GitHub Gist недоступен или содержит некорректные данные. "
                    f"Пропускаем получение бонуса."
                )
                return
                
            correct_answers, gist_day = gist_data
            
            # Проверяем синхронизацию данных между API и Gist
            if not await self.validate_bonus_data_sync(api_day, gist_day):
                logger.warning(
                    f"{self.EMOJI['warning']} {self._get_session_name()} | "
                    f"Пропускаем получение бонуса из-за несинхронизированных данных. "
                    f"API дата: {api_day}, Gist дата: {gist_day}. "
                    f"Попробуем позже, когда Gist обновится."
                )
                return
                
            # Добавляем случайную задержку перед получением бонуса
            random_delay = uniform(5, 15)
            logger.info(f"{self.EMOJI['info']} {self._get_session_name()} | Ожидание {int(random_delay)}с перед получением бонуса")
            await asyncio.sleep(random_delay)
            
            # Получаем бонус
            success = await self.claim_bonus_reward(correct_answers)
            if success:
                logger.success(f"{self.EMOJI['success']} {self._get_session_name()} | Ежедневный бонус успешно получен!")
            else:
                logger.error(f"{self.EMOJI['error']} {self._get_session_name()} | Не удалось получить ежедневный бонус")
                
        except Exception as e:
            logger.error(f"{self.EMOJI['error']} {self._get_session_name()} | Ошибка при обработке ежедневного бонуса: {e}")

    async def process_bot_logic(self) -> None:
        try:
            # Проверяем время жизни токена перед выполнением операций
            if self._is_token_expired():
                logger.debug(f"{self.EMOJI['info']} {self._get_session_name()} | Токен истек, обновляем init_data...")
                if not await self._restart_authorization():
                    logger.error(f"{self.EMOJI['error']} {self._get_session_name()} | Не удалось обновить init_data")
                    return
            
            if not await self.login():
                logger.error(f"{self.EMOJI['error']} {self._get_session_name()} | Шерстяные движения при авторизации")
                return
                
            await self.get_status()

            logger.info(f"{self.EMOJI['info']} {self._get_session_name()} | Проверяем премиум-пасс...")
            premium_active = await self.check_premium_active()
            if premium_active is True:
                premium_state = await self.get_premium_state()
                if premium_state:
                    sleep_seconds = premium_state.get("sleep_seconds", 0)
                    hours = sleep_seconds // 3600
                    minutes = (sleep_seconds % 3600) // 60
                    seconds = sleep_seconds % 60
                    logger.info(
                        f"{self.EMOJI['info']} {self._get_session_name()} | "
                        f"Премиум активен | Следующий клейм через: "
                        f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                    )
                else:
                    logger.warning(
                        f"{self.EMOJI['warning']} {self._get_session_name()} | "
                        f"Состояние премиума недоступно"
                    )
            elif premium_active is False:
                logger.info(
                    f"{self.EMOJI['info']} {self._get_session_name()} | "
                    f"Премиум-пасс не активен"
                )
            else:
                logger.warning(
                    f"{self.EMOJI['warning']} {self._get_session_name()} | "
                    f"Не удалось проверить премиум-пасс"
                )

            # Обрабатываем ежедневный бонус
            await self.process_daily_bonus()
            
            # Выполняем доступные задания (исключая рекламные)
            await self.process_tasks()
            
            # Обрабатываем рекламные задания независимо от AUTO_DAILY_TASKS
            await self.process_ad_tasks()
            
            # Проверяем статус майнинга
            mining_status = await self.check_mining_status()
            if mining_status:
                # Если награду можно забрать
                if mining_status.get("can_collect", False):
                    logger.info(f"{self.EMOJI['reward']} {self._get_session_name()} | Награда готова к получению!")
                    success = await self.collect_mining_reward()
                    if success:
                        # После получения награды проверяем обновленный статус
                        await asyncio.sleep(2)
                        updated_status = await self.check_mining_status()
                        if updated_status:
                            left_seconds = int(updated_status.get("left_seconds", 0))
                            await self.sleep_until_nearest_event(left_seconds)
                        else:
                            await self.sleep_until_nearest_event(None)
                    else:
                        # Если не удалось получить награду, ждем и пробуем снова
                        sleep_duration = uniform(300, 600)
                        logger.info(f"{self.EMOJI['warning']} {self._get_session_name()} | Повтор через {int(sleep_duration)}с")
                        await asyncio.sleep(sleep_duration)
                else:
                    # Награда еще не готова, ждем указанное время + рандом
                    left_seconds = int(mining_status.get("left_seconds", 0))
                    await self.sleep_until_nearest_event(left_seconds)
            else:
                # Если не удалось получить статус майнинга, спим стандартное время
                await self.sleep_until_nearest_event(None)
            
        except Exception as e:
            logger.error(f"{self.EMOJI['error']} {self._get_session_name()} | Ошибка в логике бота: {e}")
            raise

async def run_tapper(tg_client: UniversalTelegramClient):
    bot = WildRush(tg_client=tg_client)
    try:
        await bot.run()
    except InvalidSession as e:
        logger.error(f"Invalid Session: {e}")
        raise
