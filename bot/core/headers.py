from typing import Dict
from bot.core.agents import generate_random_user_agent

def headers(init_data: str = None) -> dict:
    # Используем динамический user-agent для лучшей имитации браузера
    user_agent = generate_random_user_agent(platform='windows', browser='chrome')
    
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
        "user-agent": user_agent
    }

