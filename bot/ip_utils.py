"""Вспомогательные функции: ping, определение страны IP, текущий внешний IP."""
import subprocess
import requests

from config import IP_INFO_API, PING_TIMEOUT


def flag(country_code: str) -> str:
    if not country_code or len(country_code) != 2:
        return "🏳️"
    OFFSET = 127397
    return chr(ord(country_code[0].upper()) + OFFSET) + chr(ord(country_code[1].upper()) + OFFSET)


def ping(host: str, timeout: int = PING_TIMEOUT) -> bool:
    """Пингует хост одним пакетом. Возвращает True если ответил."""
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", str(timeout), host],
            capture_output=True, timeout=timeout + 2
        )
        return result.returncode == 0
    except Exception:
        return False


def get_country(ip: str) -> tuple:
    """Возвращает (country_name, country_code) или ('', '')."""
    try:
        r = requests.get(IP_INFO_API.format(ip=ip), timeout=5)
        if r.status_code == 200:
            data = r.json()
            return data.get("country", ""), data.get("countryCode", "")
    except Exception:
        pass
    return "", ""


def current_external_ip() -> str:
    """Возвращает текущий внешний IP роутера."""
    try:
        r = requests.get("https://ifconfig.me", timeout=5)
        if r.status_code == 200:
            return r.text.strip()
    except Exception:
        pass
    return "недоступно"
