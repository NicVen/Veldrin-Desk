# Copyright (c) 2026. All rights reserved. Proprietary - no license granted.
"""VELDRIN dispatch. Telegram only. No email, no other channel."""
import truststore
truststore.inject_into_ssl()

import httpx
from . import config


def send(text: str) -> bool:
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        print("[VELDRIN:console] " + text.replace("\n", "\n  "))
        return True
    try:
        r = httpx.post(
            "https://api.telegram.org/bot%s/sendMessage" % config.TELEGRAM_BOT_TOKEN,
            json={"chat_id": config.TELEGRAM_CHAT_ID, "text": text},
            timeout=15)
        ok = r.status_code == 200 and r.json().get("ok", False)
        if not ok:
            print("[VELDRIN:error] %s" % r.text[:200])
        return ok
    except Exception as e:
        print("[VELDRIN:error] %s" % e)
        return False


def send_fault(reason: str) -> bool:
    return send("VELDRIN FAULT [RAILWAY]\n%s\nNo signal this cycle. "
                "Desk continues monitoring." % reason)
