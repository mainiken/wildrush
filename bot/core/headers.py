from typing import Dict
from bot.core.agents import generate_random_user_agent

def headers(init_data: str = None) -> dict:
    return {
        "accept": "*/*",
        "accept-language": "ru,en;q=0.9,en-GB;q=0.8,en-US;q=0.7",
        "content-type": "application/json;charset=UTF-8",
        "origin": "https://minimon.app",
        "priority": "u=1, i",
        "referer": "https://minimon.app/?tgWebAppStartParam=APQ6AS5Y",
        "sec-ch-ua": '"Microsoft Edge WebView2";v="141", "Chromium";v="141", "Microsoft Edge";v="141", "Not?A_Brand";v="8"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36 Edg/141.0.0.0"
    }

