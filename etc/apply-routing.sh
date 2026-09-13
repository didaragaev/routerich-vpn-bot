#!/bin/sh
# =============================================================================
#  apply-routing.sh — пересобирает /etc/xray/config.json из активной ссылки
#  БЕЗ участия бота. Нужен потому, что deploy.sh обновляет только КОД,
#  а config.json пересобирается лишь когда бот применяет ссылку.
#  Если бот не стартанул (extroot и т.п.) — роутер живёт на СТАРОЙ модели.
#
#  Запуск на роутере:  sh /usr/share/xray/apply-routing.sh
# =============================================================================
BOT_DIR=/opt/tgbot
CFG=/etc/xray/config.json
AD=/usr/share/xray
export XRAY_LOCATION_ASSET="$AD"

echo "[*] Пересборка конфига из активной ссылки (без бота)..."

[ -s "$BOT_DIR/links.json" ] || { echo "[ERR] нет $BOT_DIR/links.json — сначала добавь ссылку через бота"; exit 1; }
[ -s "$BOT_DIR/xray_manager.py" ] || { echo "[ERR] нет $BOT_DIR/xray_manager.py — прогони deploy.sh"; exit 1; }

[ -s "$CFG" ] && cp -f "$CFG" "$CFG.bak"

cd "$BOT_DIR" || exit 1
python3 - <<'PYEOF'
import json, sys
sys.path.insert(0, "/opt/tgbot")
from vless_parser import parse_vless
from xray_manager import build_config, write_config

data = json.load(open("/opt/tgbot/links.json"))
active_id = data.get("active")
link = None
for x in data.get("links", []):
    if x["id"] == active_id:
        link = x
        break
if link is None:
    links = data.get("links", [])
    if not links:
        print("НЕТ ССЫЛОК"); sys.exit(2)
    link = links[0]
    print("  (активная не задана — беру первую: %s)" % link.get("remark"))

parsed = parse_vless(link["raw"])
write_config(build_config(parsed))
print("  конфиг собран для: %s" % link.get("remark", link["host"]))
PYEOF

RC=$?
if [ $RC -ne 0 ]; then
    echo "[ERR] сборка не удалась (код $RC) — конфиг не менял"
    [ -s "$CFG.bak" ] && cp -f "$CFG.bak" "$CFG"
    exit 1
fi

echo "[*] Валидация (xray -test)..."
if ! /usr/bin/xray -test -c "$CFG" >/dev/null 2>&1; then
    echo "[ERR] xray -test НЕ прошёл — откатываю"
    [ -s "$CFG.bak" ] && cp -f "$CFG.bak" "$CFG"
    exit 1
fi
echo "[OK] конфиг валиден"

echo "[*] Рестарт xray + tproxy..."
/etc/init.d/xray restart >/dev/null 2>&1
sleep 2
/etc/init.d/vless-tproxy stop >/dev/null 2>&1
/etc/init.d/vless-tproxy start >/dev/null 2>&1
sleep 1

echo ""
echo "============================================"
pgrep -f '/usr/bin/xray' >/dev/null && echo "[OK] xray работает" || echo "[ERR] xray НЕ запущен: logread | grep xray"
nft list table inet vless_tproxy >/dev/null 2>&1 && echo "[OK] tproxy активен" || echo "[ERR] tproxy не применился"
echo "--- правила маршрутизации ---"
grep -c 'outboundTag' "$CFG" 2>/dev/null | sed 's/^/    правил: /'
grep -q 'ru-blocked' "$CFG" && echo "    [OK] НОВАЯ модель (ru-blocked, default direct)" \
                            || echo "    [!!] СТАРАЯ модель — xray_manager.py не обновился, прогони deploy.sh"
echo "============================================"
echo ""
echo "Проверка через 1-2 минуты работы:"
echo "  logread | grep xray | grep -c direct      # должно быть НЕ 0"
echo "  logread | grep xray | grep -c vless-out   # тоже НЕ 0"
