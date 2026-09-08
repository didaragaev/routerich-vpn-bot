#!/bin/sh
# Авто-обновление geo-списков РКН (заблокированные домены/IP) от runetfreedom.
# Крон раз в сутки. Скачивает обе .dat, при успехе валидирует конфиг через
# xray -test и только тогда перезапускает xray. Если тест не прошёл — откат.
AD=/usr/share/xray
BASE="https://raw.githubusercontent.com/runetfreedom/russia-v2ray-rules-dat/release"
XRAY=/usr/bin/xray
CFG=/etc/xray/config.json
LOG=/tmp/geo-update.log
export XRAY_LOCATION_ASSET="$AD"

log() { echo "$(date '+%F %T') $*" >> "$LOG"; }

DL=0
for GF in geoip geosite; do
    if wget -q -O "$AD/$GF.dat.new" "$BASE/$GF.dat" && \
       [ "$(wc -c < "$AD/$GF.dat.new" 2>/dev/null || echo 0)" -gt 1000000 ]; then
        DL=$((DL + 1))
    else
        rm -f "$AD/$GF.dat.new"
        log "$GF.dat: скачать не удалось"
    fi
done

# обновляем только если скачались ОБА файла
if [ "$DL" -eq 2 ]; then
    cp -f "$AD/geoip.dat"   "$AD/geoip.dat.bak"   2>/dev/null
    cp -f "$AD/geosite.dat" "$AD/geosite.dat.bak" 2>/dev/null
    mv "$AD/geoip.dat.new"   "$AD/geoip.dat"
    mv "$AD/geosite.dat.new" "$AD/geosite.dat"
    if [ -x "$XRAY" ] && "$XRAY" -test -c "$CFG" >/dev/null 2>&1; then
        /etc/init.d/xray restart >/dev/null 2>&1
        rm -f "$AD/geoip.dat.bak" "$AD/geosite.dat.bak"
        log "OK: списки обновлены, xray перезапущен"
    else
        mv -f "$AD/geoip.dat.bak"   "$AD/geoip.dat"   2>/dev/null
        mv -f "$AD/geosite.dat.bak" "$AD/geosite.dat" 2>/dev/null
        log "ОТКАТ: xray -test не прошёл — вернул прежние списки"
    fi
else
    rm -f "$AD"/*.dat.new
    log "пропуск обновления: скачались не оба файла"
fi
