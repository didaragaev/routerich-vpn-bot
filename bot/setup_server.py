"""Локальный веб-сервер для первоначальной настройки VLESS + Telegram ID."""
import http.server
import subprocess
import time
from urllib.parse import parse_qs

import storage
from config import set_admin_id
from vless_parser import parse_vless
from ip_utils import get_country
from xray_manager import build_config, write_config

XRAY_INIT   = "/etc/init.d/xray"
TPROXY_INIT = "/etc/init.d/vless-tproxy"
PORT        = 8080

HTML_FORM = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Настройка VPN</title>
<style>
  body {{ font-family: -apple-system, sans-serif; max-width: 500px;
          margin: 40px auto; padding: 20px; background: #f5f5f5; }}
  h2   {{ color: #333; }}
  label {{ font-size: 14px; color: #555; display: block; margin-top: 14px; }}
  input, textarea {{
    width: 100%; padding: 10px; margin: 6px 0 4px;
    border: 1px solid #ccc; border-radius: 6px;
    font-size: 14px; box-sizing: border-box;
  }}
  textarea {{ height: 90px; resize: vertical; }}
  .hint {{ font-size: 12px; color: #999; margin-bottom: 4px; }}
  button {{
    background: #2196F3; color: white; border: none;
    padding: 13px; border-radius: 6px; font-size: 16px;
    cursor: pointer; width: 100%; margin-top: 16px;
  }}
  button:hover {{ background: #1976D2; }}
  .info {{ background: white; border-radius: 6px;
           padding: 12px; margin: 10px 0; font-size: 14px; }}
  .ok  {{ color: #4CAF50; }}
  .err {{ color: #f44336; }}
</style>
</head>
<body>
<h2>🌐 Настройка VPN-роутера</h2>
{status_block}
<form method="POST" action="/apply">
  <label>Telegram ID владельца</label>
  <div class="hint">Узнать свой ID: напиши @userinfobot в Telegram</div>
  <input type="number" name="admin_id" placeholder="например: 123456789"
         value="{current_admin}" required>
  <label>VLESS-ссылка</label>
  <textarea name="vless" placeholder="vless://..."></textarea>
  <div class="hint">Оставьте пустым если хотите только обновить Telegram ID</div>
  <button type="submit">&#9658; Применить</button>
</form>
<p style="color:#999;font-size:12px;margin-top:20px">
  Эта страница доступна только в локальной сети роутера.
</p>
</body>
</html>"""

HTML_RESULT = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="refresh" content="3;url=/">
<title>Готово</title>
<style>
  body {{ font-family: -apple-system, sans-serif; max-width: 500px;
          margin: 60px auto; padding: 20px; text-align: center; }}
  .icon {{ font-size: 64px; }}
</style>
</head>
<body>
<div class="icon">{icon}</div>
<h2>{title}</h2>
<p>{message}</p>
<p style="color:#999;font-size:13px">Возврат через 3 секунды...</p>
</body>
</html>"""


def get_current_admin() -> str:
    try:
        import json
        with open("/opt/tgbot/admin.json") as f:
            return str(json.load(f).get("admin_id", ""))
    except Exception:
        return ""


def get_status_block() -> str:
    links = storage.list_all()
    active = storage.get_active()
    try:
        xray_ok = subprocess.run(
            ["pgrep", "-f", "/usr/bin/xray"],
            capture_output=True, timeout=2
        ).returncode == 0
    except Exception:
        xray_ok = False
    try:
        tproxy_ok = subprocess.run(
            ["nft", "list", "table", "inet", "vless_tproxy"],
            capture_output=True, timeout=2
        ).returncode == 0
    except Exception:
        tproxy_ok = False

    if not links:
        return '<div class="info">&#9888; Нет ни одной ссылки. Добавьте первую ниже.</div>'
    elif active and xray_ok and tproxy_ok:
        return (f'<div class="info ok">&#9989; VPN работает<br>'
                f'<small>Активна: {active["remark"]} | Ссылок: {len(links)}</small></div>')
    elif active:
        return (f'<div class="info">&#9898; Ссылка есть, VPN остановлен<br>'
                f'<small>{active["remark"]}</small></div>')
    return '<div class="info err">&#10060; Нет активной ссылки.</div>'


class Handler(http.server.BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass

    def send_html(self, code: int, body: str):
        b = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(b))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        self.send_html(200, HTML_FORM.format(
            status_block=get_status_block(),
            current_admin=get_current_admin(),
        ))

    def do_POST(self):
        if self.path != "/apply":
            self.send_html(404, "<h1>404</h1>")
            return

        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length).decode("utf-8", errors="replace")
        params = parse_qs(body)

        admin_str = params.get("admin_id", [""])[0].strip()
        vless     = params.get("vless",    [""])[0].strip()
        errors = []
        entry = None

        if admin_str:
            try:
                admin_id = int(admin_str)
                set_admin_id(admin_id)
                subprocess.run(
                    ["sh", "-c", "kill $(pgrep -f bot.py) 2>/dev/null"],
                    timeout=3
                )
            except ValueError:
                errors.append("Telegram ID должен быть числом")

        if vless and not errors:
            if not vless.startswith("vless://"):
                errors.append("Ссылка должна начинаться с vless://")
            else:
                try:
                    parsed  = parse_vless(vless)
                    country, cc = get_country(parsed["host"])
                    entry   = storage.add_link(parsed, country=country, country_code=cc)
                    config  = build_config(parsed)
                    write_config(config)
                    subprocess.run([XRAY_INIT, "restart"], timeout=15)
                    time.sleep(2)
                    subprocess.run([TPROXY_INIT, "stop"],  timeout=10)
                    subprocess.run([TPROXY_INIT, "start"], timeout=10)
                except Exception as e:
                    errors.append(f"Ошибка: {e}")

        if errors:
            self.send_html(200, HTML_RESULT.format(
                icon="&#10060;", title="Ошибка",
                message="<br>".join(errors)
            ))
            return

        parts = []
        if admin_str:
            parts.append(f"Telegram ID сохранён: {admin_str}")
        if vless and entry:
            parts.append(f"VPN запущен: {entry['remark']}")
        parts.append("Управление через Telegram-бот")

        self.send_html(200, HTML_RESULT.format(
            icon="&#9989;", title="Готово!",
            message="<br>".join(parts)
        ))


def run():
    server = http.server.HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Setup server on port {PORT}")
    server.serve_forever()


if __name__ == "__main__":
    run()
