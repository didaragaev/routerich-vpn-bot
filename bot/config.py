"""
Конфигурация бота.
ВНИМАНИЕ: этот файл — шаблон.
Реальный config.py с токеном создаётся скриптом deploy.sh автоматически.
"""
import json
import os

# Токен бота — вставляется deploy.sh
TOKEN = "DEPLOY_WILL_SET_THIS"

_ADMIN_FILE = "/opt/tgbot/admin.json"


def get_admin_id() -> int:
    try:
        with open(_ADMIN_FILE) as f:
            return int(json.load(f).get("admin_id", 0))
    except Exception:
        return 0


def set_admin_id(chat_id: int) -> None:
    with open(_ADMIN_FILE, "w") as f:
        json.dump({"admin_id": chat_id}, f)


ADMIN_ID = get_admin_id()

LINKS_FILE   = "/opt/tgbot/links.json"
TELEGRAM_API = "https://api.telegram.org/bot" + TOKEN
IP_INFO_API  = "http://ip-api.com/json/{ip}?fields=country,countryCode,city,query"
XRAY_INIT    = "/etc/init.d/xray"
TPROXY_INIT  = "/etc/init.d/vless-tproxy"
PING_TIMEOUT = 2
HTTP_TIMEOUT = 10
POLL_TIMEOUT = 30
