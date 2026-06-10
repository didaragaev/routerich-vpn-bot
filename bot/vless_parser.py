"""Парсит vless:// URL в словарь параметров."""
from urllib.parse import urlparse, parse_qs, unquote


def parse_vless(url: str) -> dict:
    if not url.startswith("vless://"):
        raise ValueError("не VLESS URL")

    parsed = urlparse(url)
    uuid = parsed.username
    host = parsed.hostname
    port = parsed.port

    if not (uuid and host and port):
        raise ValueError("VLESS URL не содержит uuid/host/port")

    params = parse_qs(parsed.query)
    p = {k: v[0] for k, v in params.items()}

    remark = unquote(parsed.fragment) if parsed.fragment else f"{host}:{port}"

    return {
        "uuid":       uuid,
        "host":       host,
        "port":       port,
        "type":       p.get("type", "tcp"),
        "encryption": p.get("encryption", "none"),
        "security":   p.get("security", "none"),
        "pbk":        p.get("pbk", ""),
        "fp":         p.get("fp", "chrome"),
        "sni":        p.get("sni", ""),
        "sid":        p.get("sid", ""),
        "spx":        unquote(p.get("spx", "/")),
        "flow":       p.get("flow", ""),
        "remark":     remark,
        "raw":        url,
    }
