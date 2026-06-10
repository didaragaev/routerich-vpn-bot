"""Хранение VLESS-ссылок и состояния в JSON-файле."""
import json
import os
import secrets
from datetime import datetime

from config import LINKS_FILE


def _empty() -> dict:
    return {"links": [], "active": None}


def load() -> dict:
    if not os.path.exists(LINKS_FILE):
        return _empty()
    try:
        with open(LINKS_FILE, "r") as f:
            data = json.load(f)
        data.setdefault("links", [])
        data.setdefault("active", None)
        return data
    except (json.JSONDecodeError, OSError):
        return _empty()


def save(data: dict) -> None:
    os.makedirs(os.path.dirname(LINKS_FILE), exist_ok=True)
    tmp = LINKS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, LINKS_FILE)


def add_link(parsed: dict, country: str = "", country_code: str = "") -> dict:
    data = load()
    link_id = secrets.token_hex(4)
    entry = {
        "id": link_id,
        "remark": parsed.get("remark", "").strip() or f"{parsed['host']}:{parsed['port']}",
        "host": parsed["host"],
        "port": parsed["port"],
        "protocol": "vless",
        "transport": parsed.get("type", "tcp"),
        "security": parsed.get("security", "none"),
        "country": country,
        "country_code": country_code,
        "raw": parsed["raw"],
        "added_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }
    data["links"].append(entry)
    if not data["active"]:
        data["active"] = link_id
    save(data)
    return entry


def remove_link(link_id: str) -> bool:
    data = load()
    before = len(data["links"])
    data["links"] = [x for x in data["links"] if x["id"] != link_id]
    if data["active"] == link_id:
        data["active"] = data["links"][0]["id"] if data["links"] else None
    save(data)
    return len(data["links"]) < before


def set_active(link_id) -> bool:
    data = load()
    if link_id is None:
        data["active"] = None
        save(data)
        return True
    if any(x["id"] == link_id for x in data["links"]):
        data["active"] = link_id
        save(data)
        return True
    return False


def get(link_id: str):
    data = load()
    for x in data["links"]:
        if x["id"] == link_id:
            return x
    return None


def list_all() -> list:
    return load()["links"]


def get_active():
    data = load()
    if not data["active"]:
        return None
    return get(data["active"])
