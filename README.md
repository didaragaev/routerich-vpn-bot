# RouteRich VPN Bot

> ⚠️ **Legal Disclaimer**
>
> This project is provided for **educational and research purposes only**.
>
> The use of VPN software may be **restricted or prohibited** by the laws of your country or region, including but not limited to the Russian Federation, where VPN services that are not registered with Roskomnadzor are subject to blocking and use may carry legal risk.
>
> By using this software, you confirm that:
> - You are solely responsible for ensuring compliance with all applicable local, national, and international laws
> - The author and contributors provide this software "as is" with no warranties
> - The author assumes **no liability** for any legal consequences arising from the use of this software
>
> If you are located in a jurisdiction where VPN use is restricted, **do not use this software**.

Automated VPN bot installation for RouteRich MT7981 routers (OpenWrt).

## What gets installed

- **Xray** (VLESS Reality) — VPN engine
- **Telegram bot** — manage VPN links from your phone
- **Web panel** (192.168.5.1:8080) — initial setup and emergency recovery
- **TPROXY** (nftables) — transparent proxying for all WiFi clients

## Quick Start

### Requirements
- RouteRich MT7981 router with RouteRich OS
- USB flash drive 4+ GB (insert before running)
- WAN cable connected, internet available
- Bot token from @BotFather
- Owner's Telegram ID (get it from @userinfobot)

### Install

```bash
wget -O deploy.sh https://raw.githubusercontent.com/didaragaev/routerich-vpn-bot/main/deploy.sh
bash deploy.sh --token "YOUR_TOKEN" --admin-id "YOUR_TELEGRAM_ID"
```

**Note:** the script reboots twice. After each reboot run it again with the same parameters — it will resume from where it stopped.

### Example

```bash
bash deploy.sh \
  --token "1234567890:AAHxxx..." \
  --admin-id "123456789"
```

### After installation

1. Wait for router to boot (2-3 minutes)
2. Run check: `bash /tmp/check.sh`
3. Open browser: `http://192.168.5.1:8080`
4. Enter your first VLESS link
5. Send `/start` to the bot in Telegram

## Repository structure

```
routerich-vpn-bot/
├── deploy.sh              — install script
├── bot/                   — Python bot code
│   ├── bot.py             — main bot logic
│   ├── tg_client.py       — Telegram API (direct + VLESS fallback)
│   ├── config.py          — config template
│   ├── storage.py         — link storage
│   ├── vless_parser.py    — vless:// URL parser
│   ├── xray_manager.py    — Xray config generator
│   ├── ip_utils.py        — IP geolocation, ping
│   └── setup_server.py    — web panel (port 8080)
└── etc/
    ├── vless-tproxy.nft   — nftables TPROXY rules
    └── init.d/
        ├── vless-tproxy   — TPROXY init script
        └── tgbot          — bot + web panel init script
```

## Update bot on existing router

```bash
cd /opt/tgbot
wget -q -O bot.py https://raw.githubusercontent.com/didaragaev/routerich-vpn-bot/main/bot/bot.py
/etc/init.d/tgbot restart
```

## Rollback

If something went wrong:

```bash
/etc/init.d/vless-tproxy stop   # disable TPROXY
/etc/init.d/tgbot stop          # stop bot
```

Or hard reset the router (hold reset button 10 seconds) — restores factory defaults.

## Ports

| Port | Service |
|------|---------|
| 10808 | SOCKS5 proxy (Xray) |
| 10809 | HTTP proxy (Xray) |
| 12345 | TPROXY (Xray, internal) |
| 8080 | Web setup panel |

## Compatibility

Tested on:
- RouteRich AX3000 (MT7981B, RouteRich OS 24.10.5)

## License

MIT
