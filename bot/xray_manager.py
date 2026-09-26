"""Генерация Xray config.json: VLESS-аутбаунд + SOCKS/HTTP/TPROXY-инбаунды."""
import json
import os
import subprocess

XRAY_CONFIG_PATH = "/etc/xray/config.json"
TPROXY_MARK = 255

PRIVATE_IP_RANGES = [
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "127.0.0.0/8",
    "169.254.0.0/16",
    "::1/128",
    "fc00::/7",
    "fe80::/10",
]

GEOIP_DAT = "/usr/share/xray/geoip.dat"
GEOSITE_DAT = "/usr/share/xray/geosite.dat"
ROUTING_FILE = "/opt/tgbot/routing.json"


def _dat_ok(path: str) -> bool:
    return os.path.exists(path) and os.path.getsize(path) > 1024


def _has_geoip() -> bool:
    return _dat_ok(GEOIP_DAT)


def _has_geosite() -> bool:
    return _dat_ok(GEOSITE_DAT)


def _load_routing() -> dict:
    """Кастомные правила из routing.json (пишет бот). Нет файла — пусто."""
    default = {"direct_domains": [], "direct_ips": [], "node_domains": []}
    if not os.path.exists(ROUTING_FILE):
        return default
    try:
        with open(ROUTING_FILE) as f:
            data = json.load(f)
        for k in default:
            default[k] = [str(x).strip() for x in data.get(k, []) if str(x).strip()]
    except (json.JSONDecodeError, OSError):
        pass
    return default


def build_vless_outbound(link: dict) -> dict:
    stream = {
        "network":  link["type"],
        "security": link["security"],
        "sockopt":  {"mark": TPROXY_MARK},
    }

    if link["security"] == "reality":
        stream["realitySettings"] = {
            "serverName": link["sni"],
            "fingerprint": link["fp"] or "chrome",
            "publicKey": link["pbk"],
            "shortId": link["sid"],
            "spiderX": link["spx"] or "/",
        }
    elif link["security"] == "tls":
        stream["tlsSettings"] = {
            "serverName": link["sni"],
            "fingerprint": link["fp"] or "chrome",
        }

    user = {"id": link["uuid"], "encryption": link["encryption"] or "none"}
    if link["flow"]:
        user["flow"] = link["flow"]

    return {
        "tag": "vless-out",
        "protocol": "vless",
        "settings": {
            "vnext": [{
                "address": link["host"],
                "port": link["port"],
                "users": [user],
            }]
        },
        "streamSettings": stream,
    }


def build_routing() -> dict:
    """Модель: по умолчанию DIRECT; в ноду — только заблокированное.
    Порядок правил = приоритет (первое совпадение выигрывает)."""
    geoip = _has_geoip()
    geosite = _has_geosite()
    custom = _load_routing()
    rules = []

    # 0. Локальные сети — всегда напрямую
    rules.append({"type": "field", "ip": PRIVATE_IP_RANGES, "outboundTag": "direct"})

    # 1. Кастом-direct (облачная 1С, краевые случаи) — из routing.json
    if custom["direct_domains"]:
        rules.append({"type": "field", "domain": custom["direct_domains"], "outboundTag": "direct"})
    if custom["direct_ips"]:
        rules.append({"type": "field", "ip": custom["direct_ips"], "outboundTag": "direct"})

    # 2. Российское — напрямую (домены + IP)
    if geosite:
        rules.append({"type": "field", "domain": ["geosite:category-ru"], "outboundTag": "direct"})
    if geoip:
        rules.append({"type": "field", "ip": ["geoip:ru", "geoip:private"], "outboundTag": "direct"})

    # 3. Apple / iCloud — напрямую (лечит почту и «отключите VPN»)
    if geosite:
        rules.append({"type": "field", "domain": ["geosite:apple"], "outboundTag": "direct"})

    # 4. Заблокированное — через ноду (авто-фид РКН + кастом из бота)
    if geosite:
        rules.append({"type": "field", "domain": ["geosite:ru-blocked"], "outboundTag": "vless-out"})
    if geoip:
        rules.append({"type": "field", "ip": ["geoip:ru-blocked", "geoip:re-filter"], "outboundTag": "vless-out"})
    if custom["node_domains"]:
        rules.append({"type": "field", "domain": custom["node_domains"], "outboundTag": "vless-out"})

    # 4b. YouTube — через ноду (остальной Google идёт direct).
    if geosite:
        rules.append({"type": "field", "domain": ["geosite:youtube"], "outboundTag": "vless-out"})

    # 5. Всё остальное — напрямую (ПЕРЕВОРОТ модели: раньше падало в ноду)
    rules.append({"type": "field", "network": "tcp,udp", "outboundTag": "direct"})

    return {"domainStrategy": "IPIfNonMatch", "rules": rules}


def build_config(link: dict) -> dict:
    return {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "tag": "socks-in",
                "port": 10808,
                "listen": "0.0.0.0",
                "protocol": "socks",
                "settings": {"udp": True, "auth": "noauth"},
                "sniffing": {"enabled": True, "destOverride": ["http", "tls"]},
            },
            {
                "tag": "http-in",
                "port": 10809,
                "listen": "0.0.0.0",
                "protocol": "http",
                "sniffing": {"enabled": True, "destOverride": ["http", "tls"]},
            },
            {
                "tag": "tproxy-in",
                "port": 12345,
                "listen": "0.0.0.0",
                "protocol": "dokodemo-door",
                "settings": {"network": "tcp,udp", "followRedirect": True},
                "sniffing": {
                    "enabled": True,
                    "destOverride": ["http", "tls", "quic"],
                    "routeOnly": False,
                },
                "streamSettings": {
                    "sockopt": {"tproxy": "tproxy", "mark": TPROXY_MARK}
                },
            },
        ],
        "outbounds": [
            build_vless_outbound(link),
            {"tag": "direct", "protocol": "freedom", "settings": {"domainStrategy": "UseIPv4"}},
            {"tag": "block",  "protocol": "blackhole"},
        ],
        "routing": build_routing(),
    }


def write_config(config: dict, path: str = XRAY_CONFIG_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def restart_xray() -> tuple:
    try:
        result = subprocess.run(
            ["/etc/init.d/xray", "restart"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return True, "Xray перезапущен"
        return False, f"Xray restart failed: {result.stderr.strip()}"
    except subprocess.TimeoutExpired:
        return False, "Xray restart timeout"
    except FileNotFoundError:
        return False, "init-скрипт xray не найден"


def is_running() -> bool:
    try:
        result = subprocess.run(
            ["pgrep", "-f", "/usr/bin/xray"],
            capture_output=True, text=True, timeout=3
        )
        return result.returncode == 0
    except Exception:
        return False
