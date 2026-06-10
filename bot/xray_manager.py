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


def _has_geoip() -> bool:
    """Проверяет есть ли geoip.dat на роутере."""
    import os
    return os.path.exists(GEOIP_DAT) and os.path.getsize(GEOIP_DAT) > 1024


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
            {"tag": "direct", "protocol": "freedom", "settings": {"domainStrategy": "UseIP"}},
            {"tag": "block",  "protocol": "blackhole"},
        ],
        "routing": {
            "domainStrategy": "IPIfNonMatch",
            "rules": [
                # Локальные сети — всегда напрямую
                {"type": "field", "ip": PRIVATE_IP_RANGES, "outboundTag": "direct"},
                # Российские IP — напрямую (если есть geoip.dat)
                *([
                    {"type": "field", "ip": ["geoip:ru"], "outboundTag": "direct"},
                    {"type": "field", "ip": ["geoip:private"], "outboundTag": "direct"},
                ] if _has_geoip() else []),
                # Всё остальное — через VLESS
            ],
        },
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
