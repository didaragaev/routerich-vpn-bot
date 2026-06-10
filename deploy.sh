#!/bin/sh
# =============================================================================
# RouteRich VPN Bot — Deploy Script
# Репо: https://github.com/didaragaev/routerich-vpn-bot
#
# Использование:
#   bash deploy.sh --token "BOT_TOKEN" --admin-id "TELEGRAM_ID"
#
# Пример:
#   bash deploy.sh --token "1234567890:AAH..." --admin-id "123456789"
#
# Скрипт поддерживает resume: если прервался на каком-то шаге,
# запусти повторно с теми же параметрами — продолжит с нужного места.
# =============================================================================

REPO="https://raw.githubusercontent.com/didaragaev/routerich-vpn-bot/main"
BOT_DIR="/opt/tgbot"
STAGE_FILE="/etc/deploy_stage"
LOG_FILE="/tmp/deploy.log"

# --- Цвета ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# --- Аргументы ---
BOT_TOKEN=""
ADMIN_ID=""

while [ $# -gt 0 ]; do
    case "$1" in
        --token)   BOT_TOKEN="$2";  shift 2 ;;
        --admin-id) ADMIN_ID="$2"; shift 2 ;;
        *) echo "Неизвестный параметр: $1"; exit 1 ;;
    esac
done

# --- Проверка параметров ---
if [ -z "$BOT_TOKEN" ] || [ -z "$ADMIN_ID" ]; then
    echo ""
    echo "Использование:"
    echo "  bash deploy.sh --token \"BOT_TOKEN\" --admin-id \"TELEGRAM_ID\""
    echo ""
    echo "Пример:"
    echo "  bash deploy.sh --token \"1234567890:AAH...\" --admin-id \"123456789\""
    echo ""
    exit 1
fi

# --- Утилиты ---
log() { echo "[$(date '+%H:%M:%S')] $1" | tee -a "$LOG_FILE"; }
ok()  { echo "${GREEN}  ✅ $1${NC}"; log "OK: $1"; }
err() { echo "${RED}  ❌ $1${NC}"; log "ERR: $1"; }
inf() { echo "${BLUE}  → $1${NC}"; log "INF: $1"; }
warn(){ echo "${YELLOW}  ⚠️  $1${NC}"; log "WARN: $1"; }

get_stage() { cat "$STAGE_FILE" 2>/dev/null || echo "0"; }
set_stage() { echo "$1" > "$STAGE_FILE"; }

# --- Заголовок ---
echo ""
echo "============================================"
echo "  RouteRich VPN Bot — Deploy"
echo "  Токен: ${BOT_TOKEN:0:20}..."
echo "  Admin ID: $ADMIN_ID"
echo "  Лог: $LOG_FILE"
echo "============================================"
echo ""

STAGE=$(get_stage)
inf "Продолжаем с этапа: $STAGE"
echo ""

# =============================================================================
# ЭТАП 1: Проверка среды
# =============================================================================
if [ "$STAGE" -lt 1 ]; then
    echo "${BLUE}[1/7] Проверка среды...${NC}"

    # Проверка что это OpenWrt/RouteRich
    if [ ! -f /etc/openwrt_release ]; then
        err "Это не OpenWrt/RouteRich! Скрипт предназначен только для RouteRich MT7981."
        exit 1
    fi
    ok "RouteRich OS обнаружена"

    # Проверка интернета
    if ! curl -s --max-time 5 https://api.github.com > /dev/null 2>&1; then
        err "Нет интернета. Убедись что WAN-кабель подключён и роутер получил IP."
        exit 1
    fi
    ok "Интернет есть"

    # Проверка root
    if [ "$(id -u)" -ne 0 ]; then
        err "Запусти скрипт от root: sudo bash deploy.sh ..."
        exit 1
    fi
    ok "Права root"

    set_stage 1
    ok "Этап 1 завершён"
    echo ""
fi

# =============================================================================
# ЭТАП 2: Флешка — форматирование и extroot
# =============================================================================
if [ "$STAGE" -lt 2 ]; then
    echo "${BLUE}[2/7] Настройка флешки и extroot...${NC}"

    # Ждём пока USB-устройство определится
    inf "Жду определения USB-устройства..."
    sleep 3

    USB_DEV=""
    for i in $(seq 1 10); do
        if [ -b /dev/sda ]; then
            USB_DEV="/dev/sda"
            break
        fi
        sleep 2
    done

    if [ -z "$USB_DEV" ]; then
        err "USB-флешка не найдена! Вставь флешку и запусти скрипт снова."
        exit 1
    fi
    ok "Флешка найдена: $USB_DEV"

    # Проверяем нет ли уже ext4-раздела с меткой extroot
    EXISTING=$(block info 2>/dev/null | grep 'LABEL="extroot"' | grep 'TYPE="ext4"')
    if [ -n "$EXISTING" ]; then
        warn "Раздел extroot уже существует — пропускаем форматирование"
    else
        inf "Форматирую флешку (все данные будут удалены)..."

        # Размечаем флешку
        (
            echo o   # новая DOS-таблица
            echo n   # новый раздел
            echo p   # primary
            echo 1   # номер 1
            echo     # start по умолчанию
            echo     # end по умолчанию (весь объём)
            echo w   # записать
        ) | fdisk "$USB_DEV" >> "$LOG_FILE" 2>&1

        sleep 2

        # Проверяем что /dev/sda1 появился
        if [ ! -b "${USB_DEV}1" ]; then
            err "Не удалось создать раздел ${USB_DEV}1"
            exit 1
        fi

        # Форматируем в ext4
        mkfs.ext4 -L extroot "${USB_DEV}1" >> "$LOG_FILE" 2>&1
        if [ $? -ne 0 ]; then
            err "Ошибка форматирования в ext4"
            exit 1
        fi
        ok "Флешка отформатирована в ext4 (${USB_DEV}1)"
    fi

    # Получаем UUID
    UUID=$(block info "${USB_DEV}1" 2>/dev/null | grep -o 'UUID="[^"]*"' | cut -d'"' -f2)
    if [ -z "$UUID" ]; then
        err "Не удалось получить UUID раздела"
        exit 1
    fi
    ok "UUID: $UUID"

    # Настраиваем extroot
    # Сначала монтируем флешку
    mkdir -p /mnt/sda1
    mount "${USB_DEV}1" /mnt/sda1

    # Копируем overlay на флешку
    inf "Копирую overlay на флешку..."
    tar -C /overlay -cvf - . | tar -C /mnt/sda1 -xf - >> "$LOG_FILE" 2>&1
    ok "Overlay скопирован"

    # Прописываем fstab
    uci -q delete fstab.@mount[0] 2>/dev/null
    uci add fstab mount
    uci set fstab.@mount[-1].target='/overlay'
    uci set fstab.@mount[-1].uuid="$UUID"
    uci set fstab.@mount[-1].fstype='ext4'
    uci set fstab.@mount[-1].enabled='1'
    uci set fstab.@mount[-1].options='rw,noatime'
    uci commit fstab
    ok "fstab настроен"

    umount /mnt/sda1

    set_stage 2

    ok "Этап 2 завершён — НУЖНА ПЕРЕЗАГРУЗКА"
    echo ""
    warn "Роутер перезагрузится для применения extroot."
    warn "После загрузки (2-3 мин) запусти скрипт снова с теми же параметрами!"
    echo ""
    inf "Перезагружаю через 5 секунд..."
    sleep 5
    reboot
    exit 0
fi

# =============================================================================
# ЭТАП 3: Проверка extroot и установка пакетов
# =============================================================================
if [ "$STAGE" -lt 3 ]; then
    echo "${BLUE}[3/7] Проверка extroot и установка пакетов...${NC}"

    # Проверяем что extroot применился
    OVERLAY_DEV=$(mount | grep ' /overlay ' | awk '{print $1}')
    if echo "$OVERLAY_DEV" | grep -q "sda"; then
        ok "extroot активен: $OVERLAY_DEV → /overlay"
    else
        err "extroot не применился! /overlay смонтирован с $OVERLAY_DEV"
        err "Убедись что флешка вставлена и перезагрузи роутер вручную."
        exit 1
    fi

    # Показываем свободное место
    FREE=$(df -h / | tail -1 | awk '{print $4}')
    ok "Свободно на /: $FREE"

    # Обновляем списки пакетов
    inf "opkg update..."
    opkg update >> "$LOG_FILE" 2>&1
    if [ $? -ne 0 ]; then
        err "opkg update не удался. Проверь интернет."
        exit 1
    fi
    ok "Списки пакетов обновлены"

    # Устанавливаем нужные пакеты
    for pkg in xray-core python3 python3-requests; do
        inf "Устанавливаю $pkg..."
        if opkg list-installed | grep -q "^$pkg "; then
            ok "$pkg уже установлен"
        else
            opkg install "$pkg" >> "$LOG_FILE" 2>&1
            if [ $? -ne 0 ]; then
                err "Не удалось установить $pkg"
                exit 1
            fi
            ok "$pkg установлен"
        fi
    done

    set_stage 3
    ok "Этап 3 завершён"
    echo ""
fi

# =============================================================================
# ЭТАП 4: Загрузка файлов бота
# =============================================================================
if [ "$STAGE" -lt 4 ]; then
    echo "${BLUE}[4/7] Загрузка файлов бота...${NC}"

    mkdir -p "$BOT_DIR"
    mkdir -p /etc/xray/configs

    # Список файлов для скачивания
    BOT_FILES="bot.py tg_client.py storage.py vless_parser.py xray_manager.py ip_utils.py setup_server.py"

    for f in $BOT_FILES; do
        inf "Скачиваю $f..."
        wget -q -O "$BOT_DIR/$f" "$REPO/bot/$f"
        if [ $? -ne 0 ] || [ ! -s "$BOT_DIR/$f" ]; then
            err "Не удалось скачать $f"
            exit 1
        fi
        ok "$f"
    done

    ok "Все файлы бота скачаны"
    set_stage 4
    echo ""
fi

# =============================================================================
# ЭТАП 5: Конфигурация
# =============================================================================
if [ "$STAGE" -lt 5 ]; then
    echo "${BLUE}[5/7] Создание конфигурации...${NC}"

    # config.py с токеном и admin_id
    cat > "$BOT_DIR/config.py" << PYEOF
"""Конфигурация бота — сгенерировано deploy.sh"""
import json
import os

TOKEN = "$BOT_TOKEN"

_ADMIN_FILE = "/opt/tgbot/admin.json"

def get_admin_id():
    try:
        with open(_ADMIN_FILE) as f:
            return int(json.load(f).get("admin_id", 0))
    except Exception:
        return 0

def set_admin_id(chat_id):
    with open(_ADMIN_FILE, "w") as f:
        json.dump({"admin_id": chat_id}, f)

ADMIN_ID = get_admin_id()

LINKS_FILE    = "/opt/tgbot/links.json"
TELEGRAM_API  = "https://api.telegram.org/bot" + TOKEN
IP_INFO_API   = "http://ip-api.com/json/{ip}?fields=country,countryCode,city,query"
XRAY_INIT     = "/etc/init.d/xray"
TPROXY_INIT   = "/etc/init.d/vless-tproxy"
PING_TIMEOUT  = 2
HTTP_TIMEOUT  = 10
POLL_TIMEOUT  = 30
PYEOF

    # admin.json с admin_id
    cat > "$BOT_DIR/admin.json" << JSONEOF
{"admin_id": $ADMIN_ID}
JSONEOF

    ok "config.py создан"
    ok "admin.json создан (ID: $ADMIN_ID)"

    # sysctl для TPROXY
    cat > /etc/sysctl.d/99-vless-tproxy.conf << EOF
net.ipv4.ip_forward=1
net.ipv4.conf.all.rp_filter=0
net.ipv4.conf.default.rp_filter=0
net.ipv4.conf.lo.rp_filter=0
EOF
    sysctl -p /etc/sysctl.d/99-vless-tproxy.conf >> "$LOG_FILE" 2>&1
    ok "sysctl настроен"

    # nftables правила
    wget -q -O /etc/vless-tproxy.nft "$REPO/etc/vless-tproxy.nft"
    if [ $? -ne 0 ] || [ ! -s /etc/vless-tproxy.nft ]; then
        err "Не удалось скачать vless-tproxy.nft"
        exit 1
    fi
    ok "vless-tproxy.nft загружен"

    # UCI: включаем Xray
    uci set xray.enabled.enabled='1'
    uci commit xray
    ok "Xray UCI включён"

    set_stage 5
    echo ""
fi

# =============================================================================
# ЭТАП 6: Init-скрипты и автозапуск
# =============================================================================
if [ "$STAGE" -lt 6 ]; then
    echo "${BLUE}[6/7] Настройка автозапуска...${NC}"

    # vless-tproxy init
    wget -q -O /etc/init.d/vless-tproxy "$REPO/etc/init.d/vless-tproxy"
    chmod +x /etc/init.d/vless-tproxy
    /etc/init.d/vless-tproxy enable
    ok "vless-tproxy init скрипт"

    # tgbot init
    wget -q -O /etc/init.d/tgbot "$REPO/etc/init.d/tgbot"
    chmod +x /etc/init.d/tgbot
    /etc/init.d/tgbot enable
    ok "tgbot init скрипт"

    # xray уже включён выше
    /etc/init.d/xray enable
    ok "xray автозапуск"

    # Проверяем что все три в rc.d
    for s in xray vless-tproxy tgbot; do
        if ls /etc/rc.d/S*$s > /dev/null 2>&1; then
            ok "Автозапуск $s ✅"
        else
            err "Автозапуск $s не настроен!"
        fi
    done

    set_stage 6
    echo ""
fi

# =============================================================================
# ЭТАП 7: Финальный ребут и проверка
# =============================================================================
if [ "$STAGE" -lt 7 ]; then
    echo "${BLUE}[7/7] Финальная перезагрузка...${NC}"
    set_stage 7

    echo ""
    ok "Все этапы завершены! Перезагружаю роутер..."
    echo ""
    warn "После загрузки (2-3 мин) проверь:"
    warn "  1. SSH на роутер"
    warn "  2. Запусти: bash /tmp/check.sh"
    warn "  3. Открой браузер: http://192.168.5.1:8080"
    warn "  4. Telegram: напиши боту /start"
    echo ""

    # Сохраняем скрипт проверки
    cat > /tmp/check.sh << 'CHECKEOF'
#!/bin/sh
echo ""
echo "=== Проверка после деплоя ==="
echo ""
pgrep -f /usr/bin/xray    > /dev/null && echo "✅ Xray работает"    || echo "❌ Xray не запущен"
pgrep -f "python3 bot.py" > /dev/null && echo "✅ Бот работает"     || echo "❌ Бот не запущен"
pgrep -f "setup_server"   > /dev/null && echo "✅ Веб-панель работает" || echo "❌ Веб-панель не запущена"
nft list table inet vless_tproxy > /dev/null 2>&1 && echo "✅ TPROXY правила загружены" || echo "❌ TPROXY не настроен"
echo ""
echo "Порты:"
netstat -tlnp 2>/dev/null | grep -E "10808|10809|12345|8080" | awk '{print "  " $4 " " $7}'
echo ""
echo "Свободно места:"
df -h / | tail -1 | awk '{print "  " $4 " свободно из " $2}'
echo ""
CHECKEOF

    sleep 5
    reboot
fi

# Если добрались сюда — всё уже сделано
echo ""
echo "============================================"
ok "Деплой завершён!"
echo ""
inf "Токен бота: ${BOT_TOKEN:0:20}..."
inf "Admin ID: $ADMIN_ID"
inf "Веб-панель: http://192.168.5.1:8080"
inf "Telegram: /start боту"
echo "============================================"
echo ""

# Очищаем флаг этапов
rm -f "$STAGE_FILE"
