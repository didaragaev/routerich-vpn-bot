"""Telegram HTTP-клиент с fallback: direct -> HTTP-прокси через Xray."""
import logging
import time
import requests

from config import TELEGRAM_API, HTTP_TIMEOUT

log = logging.getLogger("tg_client")

PROXY = {
    "http":  "http://127.0.0.1:10809",
    "https": "http://127.0.0.1:10809",
}

_mode = None
_last_check = 0.0
_RECHECK_INTERVAL = 60


def _check_direct() -> bool:
    try:
        r = requests.get(f"{TELEGRAM_API}/getMe", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def _check_proxy() -> bool:
    try:
        r = requests.get(f"{TELEGRAM_API}/getMe", proxies=PROXY, timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def _decide_mode():
    global _mode, _last_check
    _last_check = time.time()
    if _check_direct():
        if _mode != "direct":
            log.info("Mode: DIRECT")
        _mode = "direct"
        return
    if _check_proxy():
        if _mode != "proxy":
            log.info("Mode: PROXY (VLESS)")
        _mode = "proxy"
        return
    if _mode != "down":
        log.warning("Mode: DOWN — нет связи с Telegram")
    _mode = "down"


def _ensure_mode():
    global _mode, _last_check
    if _mode is None:
        _decide_mode()
        return
    if _mode == "down":
        _decide_mode()
        return
    if _mode == "proxy" and time.time() - _last_check > _RECHECK_INTERVAL:
        if _check_direct():
            log.info("Direct восстановлен")
            _mode = "direct"
        _last_check = time.time()


def _request(method: str, endpoint: str, **kwargs):
    _ensure_mode()
    if _mode == "down":
        return None
    proxies = None if _mode == "direct" else PROXY
    url = f"{TELEGRAM_API}/{endpoint}"
    try:
        if method == "GET":
            r = requests.get(url, proxies=proxies, **kwargs)
        else:
            r = requests.post(url, proxies=proxies, **kwargs)
        if r.status_code == 200:
            return r.json().get("result")
        log.warning("HTTP %s on %s", r.status_code, endpoint)
    except Exception as e:
        log.debug("%s failed (%s): %s", endpoint, _mode, e)
        _decide_mode()
    return None


def get(endpoint: str, params: dict = None, timeout: int = HTTP_TIMEOUT):
    return _request("GET", endpoint, params=params, timeout=timeout)


def post(endpoint: str, payload: dict, timeout: int = HTTP_TIMEOUT):
    return _request("POST", endpoint, json=payload, timeout=timeout)


def current_mode() -> str:
    return _mode or "unknown"
