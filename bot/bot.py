"""Telegram-бот управления VLESS-ссылками на роутере."""
import logging
import subprocess
import time
import traceback

import tg_client
import storage
from config import ADMIN_ID, POLL_TIMEOUT, XRAY_INIT, TPROXY_INIT
from ip_utils import flag, get_country, ping, current_external_ip
from vless_parser import parse_vless
from xray_manager import build_config, write_config, is_running

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
)
log = logging.getLogger("bot")

STATE = {}


def send(chat_id, text, keyboard=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if keyboard:
        payload["reply_markup"] = {"inline_keyboard": keyboard}
    return tg_client.post("sendMessage", payload)


def edit(chat_id, message_id, text, keyboard=None):
    payload = {"chat_id": chat_id, "message_id": message_id,
               "text": text, "parse_mode": "HTML"}
    if keyboard:
        payload["reply_markup"] = {"inline_keyboard": keyboard}
    return tg_client.post("editMessageText", payload)


def answer_callback(callback_id, text=""):
    tg_client.post("answerCallbackQuery",
                   {"callback_query_id": callback_id, "text": text})


def tproxy_running():
    try:
        r = subprocess.run(["nft", "list", "table", "inet", "vless_tproxy"],
                           capture_output=True, timeout=2)
        return r.returncode == 0
    except Exception:
        return False


def apply_active_link():
    active = storage.get_active()
    if not active:
        return False, "Нет активной ссылки"
    try:
        parsed = parse_vless(active["raw"])
        config = build_config(parsed)
        write_config(config)
        subprocess.run([XRAY_INIT, "restart"], timeout=10)
        time.sleep(2)
        if not is_running():
            return False, "Xray не запустился"
        subprocess.run([TPROXY_INIT, "stop"], timeout=10)
        subprocess.run([TPROXY_INIT, "start"], timeout=10)
        return True, f"Активна: {active['remark']}"
    except Exception as e:
        return False, f"Ошибка: {e}"


def stop_vpn():
    try:
        subprocess.run([TPROXY_INIT, "stop"], timeout=10)
        return True, "VPN отключён"
    except Exception as e:
        return False, f"Ошибка: {e}"


def main_menu_text():
    active = storage.get_active()
    tproxy_on = tproxy_running()
    xray_on = is_running()
    mode = tg_client.current_mode()
    mode_str = "\n<i>📡 Бот работает через VLESS</i>" if mode == "proxy" else ""
    if active and tproxy_on and xray_on:
        ip = current_external_ip()
        f = flag(active.get("country_code", ""))
        return (f"🌐 <b>Активна:</b> {f} {active['remark']}\n"
                f"📡 <b>IP:</b> {ip}\n✅ VPN работает{mode_str}")
    elif active and not tproxy_on:
        f = flag(active.get("country_code", ""))
        return (f"⚪ <b>Выбрана:</b> {f} {active['remark']}\n"
                f"🚫 VPN отключён{mode_str}")
    else:
        return f"📋 Список ссылок пуст.\nНажми ➕ <b>Добавить</b>.{mode_str}"


def main_menu_kb():
    links = storage.list_all()
    active_id = storage.load().get("active")
    rows = []
    for link in links:
        f = flag(link.get("country_code", ""))
        mark = " ✅" if link["id"] == active_id and tproxy_running() else ""
        rows.append([{"text": f"{f} {link['remark']}{mark}",
                      "callback_data": f"sw:{link['id']}"}])
    rows.append([{"text": "🚫 Без VPN", "callback_data": "stop"}])
    rows.append([{"text": "➕ Добавить", "callback_data": "add"},
                 {"text": "🗑 Удалить", "callback_data": "rm_menu"}])
    rows.append([{"text": "📊 Статус", "callback_data": "status"}])
    return rows


def remove_menu_kb():
    rows = []
    for link in storage.list_all():
        f = flag(link.get("country_code", ""))
        rows.append([{"text": f"❌ {f} {link['remark']}",
                      "callback_data": f"rm:{link['id']}"}])
    rows.append([{"text": "↩️ Назад", "callback_data": "menu"}])
    return rows


def is_admin(chat_id):
    return chat_id == ADMIN_ID


def show_main_menu(chat_id, message_id=None):
    text = main_menu_text()
    kb = main_menu_kb()
    if message_id:
        edit(chat_id, message_id, text, kb)
    else:
        send(chat_id, text, kb)


def handle_message(msg):
    chat_id = msg["chat"]["id"]
    text = msg.get("text", "").strip()
    if not is_admin(chat_id):
        log.warning("Чужой %s: %s", chat_id, text[:40])
        return
    if STATE.get(chat_id) == "awaiting_link":
        STATE[chat_id] = None
        if text.startswith("vless://"):
            try:
                parsed = parse_vless(text)
                country, cc = get_country(parsed["host"])
                entry = storage.add_link(parsed, country=country, country_code=cc)
                f = flag(cc)
                send(chat_id,
                     f"✅ Добавлено: {f} <b>{entry['remark']}</b>\n"
                     f"<code>{entry['host']}:{entry['port']}</code>\n"
                     f"Всего: {len(storage.list_all())}")
                show_main_menu(chat_id)
            except Exception as e:
                send(chat_id, f"❌ Не распарсилось:\n<code>{e}</code>\n/add — заново")
        elif text == "/cancel":
            send(chat_id, "Отменено.")
            show_main_menu(chat_id)
        else:
            send(chat_id, "Жду <code>vless://...</code> или /cancel")
            STATE[chat_id] = "awaiting_link"
        return
    if text in ("/start", "/menu", "/status"):
        show_main_menu(chat_id)
    elif text == "/add":
        STATE[chat_id] = "awaiting_link"
        send(chat_id, "📥 Пришли VLESS-ссылку.\n/cancel — отмена")
    elif text == "/list":
        links = storage.list_all()
        if not links:
            send(chat_id, "Пусто. /add")
        else:
            lines = [f"{flag(l.get('country_code',''))} <b>{l['remark']}</b>\n  "
                     f"<code>{l['host']}:{l['port']}</code>" for l in links]
            send(chat_id, "📋\n\n" + "\n\n".join(lines))
    else:
        show_main_menu(chat_id)


def handle_callback(cq):
    chat_id = cq["message"]["chat"]["id"]
    message_id = cq["message"]["message_id"]
    callback_id = cq["id"]
    data = cq.get("data", "")
    if not is_admin(chat_id):
        answer_callback(callback_id, "Доступ запрещён")
        return
    if data.startswith("sw:"):
        link_id = data[3:]
        link = storage.get(link_id)
        if not link:
            answer_callback(callback_id, "Не найдено")
            return
        answer_callback(callback_id, f"Пинг {link['host']}...")
        alive = ping(link["host"])
        warn = "" if alive else "⚠️ Не отвечает.\n"
        f = flag(link.get("country_code", ""))
        kb = [[{"text": "✅ Переключить", "callback_data": f"do_sw:{link_id}"}],
              [{"text": "↩️ Отмена", "callback_data": "menu"}]]
        edit(chat_id, message_id, f"{warn}На {f} <b>{link['remark']}</b>?", kb)
        return
    if data.startswith("do_sw:"):
        link_id = data[6:]
        if not storage.set_active(link_id):
            answer_callback(callback_id, "Ошибка")
            return
        answer_callback(callback_id, "Применяю...")
        ok, msg = apply_active_link()
        edit(chat_id, message_id, f"{'✅' if ok else '❌'} {msg}", main_menu_kb())
        time.sleep(1)
        show_main_menu(chat_id, message_id)
        return
    if data == "stop":
        answer_callback(callback_id, "Отключаю...")
        ok, msg = stop_vpn()
        edit(chat_id, message_id, f"{'✅' if ok else '❌'} {msg}", main_menu_kb())
        time.sleep(1)
        show_main_menu(chat_id, message_id)
        return
    if data == "rm_menu":
        if not storage.list_all():
            answer_callback(callback_id, "Пусто")
            return
        answer_callback(callback_id)
        edit(chat_id, message_id, "🗑 Какую?", remove_menu_kb())
        return
    if data.startswith("rm:"):
        link_id = data[3:]
        link = storage.get(link_id)
        if not link:
            answer_callback(callback_id, "Не найдено")
            return
        answer_callback(callback_id)
        kb = [[{"text": "✅ Удалить", "callback_data": f"do_rm:{link_id}"}],
              [{"text": "↩️ Отмена", "callback_data": "rm_menu"}]]
        f = flag(link.get("country_code", ""))
        edit(chat_id, message_id, f"Удалить {f} <b>{link['remark']}</b>?", kb)
        return
    if data.startswith("do_rm:"):
        link_id = data[6:]
        active_id = storage.load().get("active")
        was_active = (link_id == active_id)
        storage.remove_link(link_id)
        answer_callback(callback_id, "Удалено")
        if was_active and tproxy_running():
            stop_vpn()
        show_main_menu(chat_id, message_id)
        return
    if data == "add":
        STATE[chat_id] = "awaiting_link"
        answer_callback(callback_id)
        edit(chat_id, message_id, "📥 Пришли VLESS-ссылку.\n/cancel — отмена")
        return
    if data == "status":
        answer_callback(callback_id, "Обновляю")
        show_main_menu(chat_id, message_id)
        return
    if data == "menu":
        answer_callback(callback_id)
        show_main_menu(chat_id, message_id)
        return
    answer_callback(callback_id)


def main():
    log.info("Bot started. ADMIN_ID=%s", ADMIN_ID)
    offset = 0
    while True:
        try:
            result = tg_client.get(
                "getUpdates",
                params={"offset": offset, "timeout": POLL_TIMEOUT},
                timeout=POLL_TIMEOUT + 10,
            )
            if not result:
                time.sleep(5)
                continue
            for u in result:
                offset = u["update_id"] + 1
                try:
                    if "message" in u:
                        handle_message(u["message"])
                    elif "callback_query" in u:
                        handle_callback(u["callback_query"])
                except Exception:
                    log.error("Handler: %s", traceback.format_exc())
        except KeyboardInterrupt:
            log.info("Stopped")
            break
        except Exception:
            log.error("Loop: %s", traceback.format_exc())
            time.sleep(3)


if __name__ == "__main__":
    main()
