"""Локальная панель управления VPN-роутером (VLESS + Telegram ID)."""
import http.server
import json
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

STYLE = """
  body { font-family: -apple-system, sans-serif; max-width: 560px;
         margin: 30px auto; padding: 16px; background: #f5f5f5; color:#222; }
  h2 { color: #333; margin-bottom: 4px; }
  h3 { font-size: 15px; color:#555; margin: 24px 0 8px; }
  label { font-size: 14px; color: #555; display: block; margin-top: 14px; }
  input, textarea {
    width: 100%; padding: 10px; margin: 6px 0 4px;
    border: 1px solid #ccc; border-radius: 6px;
    font-size: 14px; box-sizing: border-box;
  }
  textarea { height: 80px; resize: vertical; }
  .hint { font-size: 12px; color: #999; margin-bottom: 4px; }
  button { background: #2196F3; color: white; border: none;
    padding: 12px; border-radius: 6px; font-size: 15px;
    cursor: pointer; width: 100%; margin-top: 14px; }
  button:hover { background: #1976D2; }
  .card { background: white; border-radius: 8px; padding: 14px;
          margin: 10px 0; font-size: 14px; }
  .ok { color: #2e7d32; } .err { color: #c62828; } .muted { color:#888; }
  .row { display:flex; gap:8px; align-items:center; justify-content:space-between;
         background:white; border-radius:8px; padding:12px; margin:8px 0; }
  .row.active { border-left: 4px solid #4CAF50; }
  .row .name { font-weight:600; }
  .row .sub { font-size:12px; color:#888; }
  .btns { display:flex; gap:6px; }
  .btns button { width:auto; margin:0; padding:8px 12px; font-size:13px; }
  .bgrey { background:#757575; } .bgrey:hover { background:#616161; }
  .bred  { background:#e53935; } .bred:hover  { background:#c62828; }
  .bgreen{ background:#43a047; } .bgreen:hover{ background:#388e3c; }
  .actions { display:flex; gap:8px; flex-wrap:wrap; }
  .actions form { flex:1; min-width:150px; }
"""

HTML_PAGE = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Панель VPN-роутера</title>
<style>{style}</style>
</head>
<body>
<h2>&#127760; Панель VPN-роутера</h2>
{status_block}

<div class="actions">
{power_button}
  <form method="POST" action="/reapply">
    <button class="bgrey" type="submit">&#128260; Применить настройки</button>
  </form>
</div>
<div class="hint">«Применить настройки» — пересобрать конфиг и перезапустить Xray
(нужно после обновления или если что-то подвисло).</div>

<h3>Мои подключения</h3>
{links_block}

<h3>Добавить подключение</h3>
<form method="POST" action="/apply">
  <label>Название</label>
  <div class="hint">Как вам удобно: «Финляндия», «Рабочий», «Запасной»</div>
  <input type="text" name="title" placeholder="например: Финляндия" maxlength="40">
  <label>VLESS-ссылка</label>
  <textarea name="vless" placeholder="vless://..."></textarea>
  <label>Telegram ID владельца</label>
  <div class="hint">Узнать свой ID: напиши @userinfobot в Telegram</div>
  <input type="number" name="admin_id" placeholder="например: 123456789"
         value="{current_admin}">
  <button type="submit">&#9658; Добавить и включить</button>
</form>

<p class="muted" style="font-size:12px;margin-top:20px">
  Страница доступна только в локальной сети роутера.
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
<style>body {{ font-family:-apple-system,sans-serif; max-width:500px;
  margin:60px auto; padding:20px; text-align:center; }}
 .icon {{ font-size:64px; }}</style>
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
        with open("/opt/tgbot/admin.json") as f:
            return str(json.load(f).get("admin_id", ""))
    except Exception:
        return ""


def xray_ok() -> bool:
    try:
        return subprocess.run(["pgrep", "-f", "/usr/bin/xray"],
                              capture_output=True, timeout=2).returncode == 0
    except Exception:
        return False


def tproxy_ok() -> bool:
    try:
        return subprocess.run(["nft", "list", "table", "inet", "vless_tproxy"],
                              capture_output=True, timeout=2).returncode == 0
    except Exception:
        return False


def esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def get_status_block() -> str:
    links  = storage.list_all()
    active = storage.get_active()
    if not links:
        return '<div class="card">&#9888; Нет ни одного подключения. Добавьте первое ниже.</div>'
    if active and xray_ok() and tproxy_ok():
        return (f'<div class="card ok">&#9989; <b>VPN включён</b><br>'
                f'<small>Активно: {esc(active["remark"])} &nbsp;|&nbsp; '
                f'Подключений: {len(links)}</small></div>')
    if active:
        return (f'<div class="card">&#9898; <b>VPN выключен</b><br>'
                f'<small>Выбрано: {esc(active["remark"])}</small></div>')
    return '<div class="card err">&#10060; Нет активного подключения.</div>'


def get_power_button() -> str:
    if tproxy_ok():
        return ('  <form method="POST" action="/vpn_off">\n'
                '    <button class="bred" type="submit">&#9209; Выключить VPN</button>\n'
                '  </form>')
    return ('  <form method="POST" action="/vpn_on">\n'
            '    <button class="bgreen" type="submit">&#9654; Включить VPN</button>\n'
            '  </form>')


def get_links_block() -> str:
    links = storage.list_all()
    if not links:
        return '<div class="card muted">Пока пусто.</div>'
    active_id = storage.load().get("active")
    rows = []
    for ln in links:
        is_active = ln["id"] == active_id
        cls  = "row active" if is_active else "row"
        mark = " &#9989;" if is_active else ""
        sub  = f'{esc(ln.get("country", ""))} {esc(ln["host"])}:{esc(ln["port"])}'
        btns = []
        if not is_active:
            btns.append(
                f'<form method="POST" action="/activate">'
                f'<input type="hidden" name="id" value="{esc(ln["id"])}">'
                f'<button type="submit">Включить</button></form>')
        btns.append(
            f'<form method="POST" action="/delete" '
            f'onsubmit="return confirm(\'Удалить это подключение?\')">'
            f'<input type="hidden" name="id" value="{esc(ln["id"])}">'
            f'<button class="bred" type="submit">Удалить</button></form>')
        rows.append(
            f'<div class="{cls}">'
            f'<div><div class="name">{esc(ln["remark"])}{mark}</div>'
            f'<div class="sub">{sub}</div></div>'
            f'<div class="btns">{"".join(btns)}</div></div>')
    return "".join(rows)


def apply_link(link: dict):
    """Пересобрать конфиг под ссылку, перезапустить xray и tproxy."""
    parsed = parse_vless(link["raw"])
    write_config(build_config(parsed))
    subprocess.run([XRAY_INIT, "restart"], timeout=15)
    time.sleep(2)
    subprocess.run([TPROXY_INIT, "stop"],  timeout=10)
    subprocess.run([TPROXY_INIT, "start"], timeout=10)


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

    def result(self, ok: bool, title: str, message: str):
        self.send_html(200, HTML_RESULT.format(
            icon="&#9989;" if ok else "&#10060;",
            title=title, message=message))

    def do_GET(self):
        self.send_html(200, HTML_PAGE.format(
            style=STYLE,
            status_block=get_status_block(),
            power_button=get_power_button(),
            links_block=get_links_block(),
            current_admin=get_current_admin(),
        ))

    def read_params(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length).decode("utf-8", errors="replace")
        return parse_qs(body)

    def do_POST(self):
        routes = {
            "/apply":   self.h_apply,
            "/activate": self.h_activate,
            "/delete":  self.h_delete,
            "/vpn_on":  self.h_vpn_on,
            "/vpn_off": self.h_vpn_off,
            "/reapply": self.h_reapply,
        }
        handler = routes.get(self.path)
        if not handler:
            self.send_html(404, "<h1>404</h1>")
            return
        try:
            handler(self.read_params())
        except Exception as e:
            self.result(False, "Ошибка", esc(e))

    # --- обработчики ---

    def h_apply(self, params):
        admin_str = params.get("admin_id", [""])[0].strip()
        vless     = params.get("vless",    [""])[0].strip()
        title     = params.get("title",    [""])[0].strip()
        parts = []

        if admin_str:
            try:
                set_admin_id(int(admin_str))
                subprocess.run(["sh", "-c", "kill $(pgrep -f bot.py) 2>/dev/null"],
                               timeout=3)
                parts.append(f"Telegram ID сохранён: {esc(admin_str)}")
            except ValueError:
                self.result(False, "Ошибка", "Telegram ID должен быть числом")
                return

        if vless:
            if not vless.startswith("vless://"):
                self.result(False, "Ошибка", "Ссылка должна начинаться с vless://")
                return
            parsed = parse_vless(vless)
            if title:
                parsed["remark"] = title
            country, cc = get_country(parsed["host"])
            entry = storage.add_link(parsed, country=country, country_code=cc)
            storage.set_active(entry["id"])
            apply_link(entry)
            parts.append(f"VPN включён: {esc(entry['remark'])}")

        if not parts:
            self.result(False, "Ошибка", "Нечего применять — заполните хотя бы одно поле")
            return
        self.result(True, "Готово!", "<br>".join(parts))

    def h_activate(self, params):
        link_id = params.get("id", [""])[0]
        link = storage.get(link_id)
        if not link:
            self.result(False, "Ошибка", "Подключение не найдено")
            return
        storage.set_active(link_id)
        apply_link(link)
        self.result(True, "Переключено", f"Активно: {esc(link['remark'])}")

    def h_delete(self, params):
        link_id = params.get("id", [""])[0]
        link = storage.get(link_id)
        if not link:
            self.result(False, "Ошибка", "Подключение не найдено")
            return
        name = link["remark"]
        was_active = (storage.load().get("active") == link_id)
        storage.remove_link(link_id)
        msg = f"Удалено: {esc(name)}"
        if was_active:
            new_active = storage.get_active()
            if new_active:
                apply_link(new_active)
                msg += f"<br>Переключено на: {esc(new_active['remark'])}"
            else:
                subprocess.run([TPROXY_INIT, "stop"], timeout=10)
                msg += "<br>Подключений не осталось — VPN выключен"
        self.result(True, "Готово", msg)

    def h_vpn_on(self, params):
        active = storage.get_active()
        if not active:
            self.result(False, "Ошибка", "Нет активного подключения")
            return
        apply_link(active)
        self.result(True, "VPN включён", esc(active["remark"]))

    def h_vpn_off(self, params):
        subprocess.run([TPROXY_INIT, "stop"], timeout=10)
        self.result(True, "VPN выключен",
                    "Интернет работает напрямую, без туннеля.")

    def h_reapply(self, params):
        active = storage.get_active()
        if not active:
            self.result(False, "Ошибка", "Нет активного подключения")
            return
        apply_link(active)
        self.result(True, "Настройки применены",
                    f"Конфиг пересобран, Xray перезапущен.<br>"
                    f"Активно: {esc(active['remark'])}")


def run():
    server = http.server.HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Setup server on port {PORT}")
    server.serve_forever()


if __name__ == "__main__":
    run()
