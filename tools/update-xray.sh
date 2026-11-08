#!/bin/sh
# update-xray.sh - обновление xray-core на роутере (OpenWrt, arm64)
# Запуск: wget -O /tmp/u.sh <raw-url> && sh /tmp/u.sh

VER="26.7.28"
ZIP="Xray-linux-arm64-v8a.zip"
URL="https://github.com/XTLS/Xray-core/releases/download/v$VER"
BIN="$(command -v xray || echo /usr/bin/xray)"
TMP="/tmp/xray-upd"

echo "== Текущая версия =="
"$BIN" version 2>/dev/null | head -1
if "$BIN" version 2>/dev/null | head -1 | grep -q "Xray $VER "; then
  echo "Уже $VER, обновлять не нужно"
  logread | grep -i xray | tail -8
  exit 0
fi

[ "$(uname -m)" = "aarch64" ] || { echo "ОШИБКА: архитектура $(uname -m), не aarch64"; exit 1; }

rm -rf "$TMP"; mkdir -p "$TMP"; cd "$TMP" || exit 1

dl() { wget -q -O "$2" "$1" || wget -q --no-check-certificate -O "$2" "$1"; }

echo "== Скачиваю $VER =="
dl "$URL/$ZIP" "$ZIP" || { echo "ОШИБКА: не скачался zip"; exit 1; }
dl "$URL/$ZIP.dgst" "$ZIP.dgst" || { echo "ОШИБКА: не скачался dgst"; exit 1; }

WANT=$(grep -i 'SHA2-256' "$ZIP.dgst" | awk '{print $2}')
GOT=$(sha256sum "$ZIP" | awk '{print $1}')
if [ -z "$WANT" ] || [ "$WANT" != "$GOT" ]; then
  echo "ОШИБКА: sha256 не совпал, ничего не менял"; exit 1
fi
echo "sha256 OK"

command -v unzip >/dev/null || { opkg update >/dev/null 2>&1; opkg install unzip >/dev/null 2>&1; }
command -v unzip >/dev/null || { echo "ОШИБКА: нет unzip"; exit 1; }
unzip -o -q "$ZIP" xray || { echo "ОШИБКА: распаковка"; exit 1; }
chmod +x xray

echo "== Тест конфига новым xray =="
if ! ./xray run -test -confdir /etc/xray >/dev/null 2>&1; then
  ./xray run -test -c /etc/xray/config.json || { echo "ОШИБКА: конфиг не прошёл тест, ничего не менял"; exit 1; }
fi
echo "конфиг OK"

echo "== Замена бинарника =="
cp "$BIN" /root/xray.bak
/etc/init.d/xray stop
cp xray "$BIN" && chmod +x "$BIN"
/etc/init.d/xray start
sleep 5

if ! pidof xray >/dev/null; then
  echo "ОШИБКА: новый xray не стартовал, откатываю"
  /etc/init.d/xray stop
  cp /root/xray.bak "$BIN"
  /etc/init.d/xray start
  exit 1
fi

opkg flag hold xray-core >/dev/null 2>&1
[ -x /etc/init.d/tgbot ] && /etc/init.d/tgbot restart

echo "== ГОТОВО =="
"$BIN" version | head -1
echo "== Лог =="
logread | grep -i xray | tail -8
rm -rf "$TMP"
