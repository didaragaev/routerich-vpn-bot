#!/bin/sh
# =============================================================================
# RouteRich/Cudy VPN Bot — Deploy Script v2
# Репо: https://github.com/didaragaev/routerich-vpn-bot
#
# Использование (один раз):
#   sh deploy.sh --token "BOT_TOKEN" --admin-id "TELEGRAM_ID"
#
# Скрипт полностью автономный:
#   - Сам перезапускается после ребута через rc.local
#   - Идемпотентный: можно запускать сколько угодно раз
#   - Проверяет факты, не флаги
# =============================================================================

REPO="https://raw.githubusercontent.com/didaragaev/routerich-vpn-bot/main"
BOT_DIR="/opt/tgbot"
LOG_FILE="/var/log/deploy.log"
RC_LOCAL="/etc/rc.local"
SELF="$0"

# --- Парсим аргументы ---
BOT_TOKEN=""
ADMIN_ID=""

while [ $# -gt 0 ]; do
    case "$1" in
        --token)    BOT_TOKEN="$2"; shift 2 ;;
        --admin-id) ADMIN_ID="$2";  shift 2 ;;
        --resume)   RESUME=1;       shift 1 ;;
        *) echo "Неизвестный параметр: $1"; exit 1 ;;
    esac
done

# --- Проверка параметров ---
# При resume читаем сохранённые параметры
if [ "${RESUME}" = "1" ] && [ -f /etc/deploy_params ]; then
    . /etc/deploy_params
fi

if [ -z "$BOT_TOKEN" ] || [ -z "$ADMIN_ID" ]; then
    echo ""
    echo "Использование:"
    echo "  sh deploy.sh --token \"BOT_TOKEN\" --admin-id \"TELEGRAM_ID\""
    echo ""
    exit 1
fi

# --- Утилиты ---
log()  { echo "[$(date '+%H:%M:%S')] $1" | tee -a "$LOG_FILE"; }
ok()   { log "OK:   $1"; echo "  [OK] $1"; }
err()  { log "ERR:  $1"; echo "  [!!] $1"; }
inf()  { log "    : $1"; echo "  ... $1"; }
warn() { log "WARN: $1"; echo "  [~] $1"; }

# --- Сохраняем параметры для resume ---
save_params() {
    cat > /etc/deploy_params << EOF
BOT_TOKEN="$BOT_TOKEN"
ADMIN_ID="$ADMIN_ID"
EOF
}

# --- Прописываем себя в rc.local для автозапуска после ребута ---
register_resume() {
    # Удаляем старую запись если есть
    unregister_resume

    # Добавляем перед exit 0
    RESUME_CMD="sh /root/deploy.sh --resume >> /var/log/deploy.log 2>&1 &"
    if [ -f "$RC_LOCAL" ]; then
        # Вставляем перед последней строкой (exit 0)
        sed -i "/^exit 0/i $RESUME_CMD" "$RC_LOCAL"
    else
        printf "#!/bin/sh\n$RESUME_CMD\nexit 0\n" > "$RC_LOCAL"
        chmod +x "$RC_LOCAL"
    fi
    log "Зарегистрирован автозапуск после ребута"
}

# --- Удаляем себя из rc.local ---
unregister_resume() {
    if [ -f "$RC_LOCAL" ]; then
        sed -i '/deploy\.sh/d' "$RC_LOCAL"
    fi
    rm -f /etc/deploy_params
}

# =============================================================================
# ПРОВЕРКИ СОСТОЯНИЯ (вместо флагов)
# =============================================================================

is_extroot_active() {
    mount | grep -q '/dev/sda.*on /overlay'
}

is_usb_present() {
    [ -b /dev/sda ]
}

is_extroot_partition() {
    block info 2>/dev/null | grep -q 'LABEL="extroot".*TYPE="ext4"'
}

is_xray_installed() {
    [ -x /usr/bin/xray ]
}

is_python_installed() {
    [ -x /usr/bin/python3 ]
}

is_bot_installed() {
    [ -f "$BOT_DIR/bot.py" ] && [ -f "$BOT_DIR/config.py" ]
}

is_bot_configured() {
    [ -f "$BOT_DIR/config.py" ] && grep -q "$BOT_TOKEN" "$BOT_DIR/config.py" 2>/dev/null
}

is_autostart_configured() {
    [ -f /etc/rc.d/S100tgbot ] && [ -f /etc/rc.d/S99xray ] && [ -f /etc/rc.d/S95vless-tproxy ]
}

# =============================================================================
# ЗАГОЛОВОК
# =============================================================================

echo ""
echo "============================================"
echo "  RouteRich VPN Bot — Deploy v2"
echo "  Токен: ${BOT_TOKEN:0:20}..."
echo "  Admin ID: $ADMIN_ID"
echo "  Лог: $LOG_FILE"
if [ "${RESUME}" = "1" ]; then
echo "  Режим: АВТОПРОДОЛЖЕНИЕ после ребута"
fi
echo "============================================"
echo ""

log "=== Deploy start (resume=${RESUME:-0}) ==="

# =============================================================================
# ЭТАП 1: Проверка среды
# =============================================================================

echo "[1/6] Проверка среды..."

if [ ! -f /etc/openwrt_release ]; then
    err "Это не OpenWrt/RouteRich!"
    exit 1
fi
ok "OpenWrt обнаружен"

if [ "$(id -u)" -ne 0 ]; then
    err "Нужны права root"
    exit 1
fi
ok "Права root"

# Проверка интернета
if ! wget -q --spider https://raw.githubusercontent.com 2>/dev/null; then
    err "Нет интернета. Подключи WAN-кабель."
    exit 1
fi
ok "Интернет есть"

# Определяем тип прошивки и настраиваем opkg
if grep -q "RouteRich" /etc/openwrt_release 2>/dev/null; then
    ok "Прошивка: RouteRich"
else
    ok "Прошивка: чистый OpenWrt"
    # Исправляем репозитории если там SNAPSHOT
    if grep -q "SNAPSHOT" /etc/opkg/distfeeds.conf 2>/dev/null; then
        inf "Исправляю репозитории (SNAPSHOT -> 24.10.5)..."
        ARCH=$(grep DISTRIB_ARCH /etc/openwrt_release | cut -d"'" -f2)
        cat > /etc/opkg/distfeeds.conf << FEEDEOF
src/gz openwrt_core https://downloads.openwrt.org/releases/24.10.5/targets/mediatek/filogic/packages
src/gz openwrt_base https://downloads.openwrt.org/releases/24.10.5/packages/${ARCH}/base
src/gz openwrt_luci https://downloads.openwrt.org/releases/24.10.5/packages/${ARCH}/luci
src/gz openwrt_packages https://downloads.openwrt.org/releases/24.10.5/packages/${ARCH}/packages
src/gz openwrt_routing https://downloads.openwrt.org/releases/24.10.5/packages/${ARCH}/routing
FEEDEOF
        ok "Репозитории исправлены"
    fi
    # Отключаем SSL проверку (нет CA-сертификатов на чистом OpenWrt)
    if ! grep -q "no_check_certificate" /etc/opkg.conf 2>/dev/null; then
        echo "option no_check_certificate 1" >> /etc/opkg.conf
        ok "SSL проверка отключена для opkg"
    fi
fi

# Копируем скрипт в /root чтобы был доступен после ребута
if [ "$SELF" != "/root/deploy.sh" ]; then
    cp "$SELF" /root/deploy.sh
    chmod +x /root/deploy.sh
fi

echo ""

# =============================================================================
# ЭТАП 2: Флешка и extroot
# =============================================================================

echo "[2/6] Флешка и extroot..."

if is_extroot_active; then
    ok "extroot уже активен ($(df -h / | tail -1 | awk '{print $2}') total)"
else
    # Ждём флешку
    inf "Жду USB-устройство..."
    I=0
    while [ $I -lt 15 ] && ! is_usb_present; do
        sleep 1
        I=$((I+1))
    done

    if ! is_usb_present; then
        err "USB-флешка не найдена! Вставь флешку и запусти скрипт снова."
        exit 1
    fi
    ok "Флешка найдена: /dev/sda"

    if ! is_extroot_partition; then
        # Определяем текущий тип ФС
        CURRENT_TYPE=$(block info /dev/sda1 2>/dev/null | grep -o 'TYPE="[^"]*"' | cut -d'"' -f2)

        # Отмонтируем всё с флешки
        for MNT in $(mount | grep '/dev/sda' | awk '{print $3}'); do
            umount "$MNT" 2>/dev/null
        done
        umount /dev/sda1 2>/dev/null
        sleep 1

        if [ -n "$CURRENT_TYPE" ] && [ "$CURRENT_TYPE" != "ext4" ]; then
            inf "Обнаружена $CURRENT_TYPE — форматирую в ext4..."
        else
            inf "Форматирую флешку в ext4..."
        fi

        # Размечаем
        printf "o\nn\np\n1\n\n\nw\n" | fdisk /dev/sda >> "$LOG_FILE" 2>&1
        sleep 2

        if [ ! -b /dev/sda1 ]; then
            err "Не удалось создать раздел /dev/sda1"
            exit 1
        fi

        mkfs.ext4 -L extroot /dev/sda1 >> "$LOG_FILE" 2>&1
        if [ $? -ne 0 ]; then
            err "Ошибка форматирования ext4"
            exit 1
        fi
        ok "Флешка отформатирована в ext4"
    else
        ok "ext4-раздел с меткой extroot уже есть"
    fi

    # Получаем UUID
    UUID=$(block info /dev/sda1 2>/dev/null | grep -o 'UUID="[^"]*"' | cut -d'"' -f2)
    if [ -z "$UUID" ]; then
        err "Не удалось получить UUID"
        exit 1
    fi
    ok "UUID: $UUID"

    # Копируем overlay на флешку
    mkdir -p /mnt/extroot
    mount /dev/sda1 /mnt/extroot 2>/dev/null

    # Копируем только если флешка пустая (нет upper/)
    if [ ! -d /mnt/extroot/upper ]; then
        inf "Копирую overlay на флешку..."
        tar -C /overlay -cf - . | tar -C /mnt/extroot -xf - >> "$LOG_FILE" 2>&1
        ok "Overlay скопирован"
    else
        ok "Overlay уже скопирован"
    fi

    # Настраиваем fstab напрямую (не через uci — избегаем I/O error)
    FSTAB_ENTRY="
config mount
	option target '/overlay'
	option uuid '$UUID'
	option fstype 'ext4'
	option enabled '1'
	option options 'rw,noatime'"

    # Проверяем нет ли уже такой записи
    if ! grep -q "option uuid '$UUID'" /etc/config/fstab 2>/dev/null; then
        echo "$FSTAB_ENTRY" >> /etc/config/fstab
        # Синхронизируем на флешку
        if [ -d /mnt/extroot/upper/etc/config ]; then
            echo "$FSTAB_ENTRY" >> /mnt/extroot/upper/etc/config/fstab
        fi
        ok "fstab настроен (UUID: $UUID)"
    else
        ok "fstab уже настроен"
    fi

    umount /mnt/extroot 2>/dev/null

    # Сохраняем параметры и регистрируем автозапуск
    save_params
    register_resume

    warn "Перезагружаю роутер для активации extroot..."
    warn "Скрипт продолжится автоматически после загрузки (~2-3 мин)"
    echo ""
    sleep 3
    reboot
    exit 0
fi

echo ""

# =============================================================================
# ЭТАП 3: Установка пакетов
# =============================================================================

echo "[3/6] Установка пакетов..."

NEED_UPDATE=0

if ! is_xray_installed; then
    NEED_UPDATE=1
fi
if ! is_python_installed; then
    NEED_UPDATE=1
fi

if [ $NEED_UPDATE -eq 1 ]; then
    inf "opkg update..."
    opkg update >> "$LOG_FILE" 2>&1
    if [ $? -ne 0 ]; then
        err "opkg update не удался"
        exit 1
    fi
fi

for PKG in xray-core python3 python3-requests; do
    if opkg list-installed 2>/dev/null | grep -q "^$PKG "; then
        ok "$PKG уже установлен"
    else
        inf "Устанавливаю $PKG..."
        opkg install "$PKG" >> "$LOG_FILE" 2>&1
        if [ $? -ne 0 ]; then
            err "Не удалось установить $PKG"
            exit 1
        fi
        ok "$PKG установлен"
    fi
done

echo ""

# =============================================================================
# ЭТАП 4: Файлы бота и конфигурация
# =============================================================================

echo "[4/6] Файлы бота и конфигурация..."

mkdir -p "$BOT_DIR"
mkdir -p /etc/xray/configs
mkdir -p /usr/share/xray

# Скачиваем файлы бота
BOT_FILES="bot.py tg_client.py storage.py vless_parser.py xray_manager.py ip_utils.py setup_server.py"

for F in $BOT_FILES; do
    # Перескачиваем если файл отсутствует или пустой
    if [ ! -s "$BOT_DIR/$F" ]; then
        inf "Скачиваю $F..."
        wget -q -O "$BOT_DIR/$F" "$REPO/bot/$F"
        if [ $? -ne 0 ] || [ ! -s "$BOT_DIR/$F" ]; then
            err "Не удалось скачать $F"
            exit 1
        fi
        ok "$F"
    else
        ok "$F (уже есть)"
    fi
done

# config.py — создаём или обновляем если токен изменился
if ! is_bot_configured; then
    inf "Создаю config.py..."
    cat > "$BOT_DIR/config.py" << PYEOF
"""Конфигурация бота — создано deploy.sh"""
import json, os

TOKEN = "$BOT_TOKEN"

_ADMIN_FILE = "/opt/tgbot/admin.json"

def get_admin_id():
    try:
        with open(_ADMIN_FILE) as f:
            return int(json.load(f).get("admin_id", 0))
    except:
        return 0

def set_admin_id(chat_id):
    with open(_ADMIN_FILE, "w") as f:
        json.dump({"admin_id": chat_id}, f)

ADMIN_ID      = get_admin_id()
LINKS_FILE    = "/opt/tgbot/links.json"
TELEGRAM_API  = "https://api.telegram.org/bot" + TOKEN
IP_INFO_API   = "http://ip-api.com/json/{ip}?fields=country,countryCode,city,query"
XRAY_INIT     = "/etc/init.d/xray"
TPROXY_INIT   = "/etc/init.d/vless-tproxy"
PING_TIMEOUT  = 2
HTTP_TIMEOUT  = 10
POLL_TIMEOUT  = 30
PYEOF
    ok "config.py создан"
else
    ok "config.py уже настроен"
fi

# admin.json
if [ ! -f "$BOT_DIR/admin.json" ]; then
    printf '{"admin_id": %s}' "$ADMIN_ID" > "$BOT_DIR/admin.json"
    ok "admin.json создан (ID: $ADMIN_ID)"
else
    ok "admin.json уже есть"
fi

# sysctl
cat > /etc/sysctl.d/99-vless-tproxy.conf << EOF
net.ipv4.ip_forward=1
net.ipv4.conf.all.rp_filter=0
net.ipv4.conf.default.rp_filter=0
net.ipv4.conf.lo.rp_filter=0
EOF
sysctl -p /etc/sysctl.d/99-vless-tproxy.conf >> "$LOG_FILE" 2>&1
ok "sysctl настроен"

# nftables правила
if [ ! -s /etc/vless-tproxy.nft ]; then
    inf "Скачиваю vless-tproxy.nft..."
    wget -q -O /etc/vless-tproxy.nft "$REPO/etc/vless-tproxy.nft"
    if [ $? -ne 0 ] || [ ! -s /etc/vless-tproxy.nft ]; then
        err "Не удалось скачать vless-tproxy.nft"
        exit 1
    fi
    ok "vless-tproxy.nft загружен"
else
    ok "vless-tproxy.nft уже есть"
fi

# geoip.dat
if [ ! -s /usr/share/xray/geoip.dat ]; then
    inf "Скачиваю geoip.dat (~18MB)..."
    wget -q -O /usr/share/xray/geoip.dat \
        "https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download/geoip.dat"
    if [ -s /usr/share/xray/geoip.dat ]; then
        ok "geoip.dat ($(du -h /usr/share/xray/geoip.dat | cut -f1))"
    else
        warn "geoip.dat не скачался — трафик пойдёт весь через VLESS"
        rm -f /usr/share/xray/geoip.dat
    fi
else
    ok "geoip.dat уже есть ($(du -h /usr/share/xray/geoip.dat | cut -f1))"
fi

# Xray UCI
uci set xray.enabled.enabled='1' 2>/dev/null
uci commit xray 2>/dev/null
ok "Xray UCI включён"

echo ""

# =============================================================================
# ЭТАП 5: Init-скрипты и автозапуск
# =============================================================================

echo "[5/6] Автозапуск..."

for INIT in vless-tproxy tgbot; do
    if [ ! -f /etc/init.d/$INIT ]; then
        inf "Скачиваю init/$INIT..."
        wget -q -O /etc/init.d/$INIT "$REPO/etc/init.d/$INIT"
        chmod +x /etc/init.d/$INIT
        ok "init/$INIT загружен"
    else
        ok "init/$INIT уже есть"
    fi
    /etc/init.d/$INIT enable 2>/dev/null
done

/etc/init.d/xray enable 2>/dev/null

# Проверяем что все три в автозапуске
ALL_OK=1
for S in xray vless-tproxy tgbot; do
    if ls /etc/rc.d/S*$S > /dev/null 2>&1; then
        ok "Автозапуск $S"
    else
        err "Автозапуск $S не настроен!"
        ALL_OK=0
    fi
done

if [ $ALL_OK -eq 0 ]; then
    exit 1
fi

echo ""

# =============================================================================
# ЭТАП 6: Финальный ребут
# =============================================================================

echo "[6/6] Финальная перезагрузка..."

# Убираем себя из rc.local — деплой завершён
unregister_resume

echo ""
echo "============================================"
ok "Деплой завершён!"
echo ""
inf "Токен: ${BOT_TOKEN:0:20}..."
inf "Admin ID: $ADMIN_ID"
inf "Веб-панель: http://$(uci get network.lan.ipaddr 2>/dev/null || echo '192.168.x.1'):8080"
echo "============================================"
echo ""
inf "Перезагружаю через 5 секунд..."
log "=== Deploy complete ==="

sleep 5
reboot
