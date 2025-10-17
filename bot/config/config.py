from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Dict, Tuple
from enum import Enum

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True)

    API_ID: int = None
    API_HASH: str = None
    GLOBAL_CONFIG_PATH: str = "TG_FARM"

    FIX_CERT: bool = False

    SESSION_START_DELAY: int = 360

    REF_ID: str = 'APQ6AS5Y'
    SESSIONS_PER_PROXY: int = 1
    USE_PROXY: bool = True
    DISABLE_PROXY_REPLACE: bool = False

    DEVICE_PARAMS: bool = False

    DEBUG_LOGGING: bool = False

    AUTO_UPDATE: bool = False
    CHECK_UPDATE_INTERVAL: int = 60
    BLACKLISTED_SESSIONS: str = ""
    
    MOVE_INVALID_SESSIONS_TO_ERROR: bool = True
    TOKEN_LIVE_TIME: int = 3600  # Время жизни токена в секундах (1 час)
    
    # Настройки выполнения заданий
    AUTO_DAILY_TASKS: bool = True  # Автоматическое выполнение ежедневных заданий
    AUTO_ADS_VIEWING: bool = True  # Автоматический просмотр рекламы
    AUTO_BONUS_CLAIM: bool = True  # Автоматическое получение ежедневных бонусов

    @property
    def blacklisted_sessions(self) -> List[str]:
        return [s.strip() for s in self.BLACKLISTED_SESSIONS.split(',') if s.strip()]

settings = Settings()
