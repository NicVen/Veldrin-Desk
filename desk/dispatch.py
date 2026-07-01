# Copyright (c) 2026. All rights reserved. Proprietary - no license granted.
"""VELDRIN dispatch. Telegram only. No email, no other channel.

Two audiences:
  send_vip(text)    -> paid private channel (full signals + management alerts)
  send_public(text) -> free public channel (teasers only)
send() defaults to VIP so existing calls stay full-fidelity.
Faults are operational noise -> logged to Railway only, never a channel.
"""
import truststore
truststore.inject_into_ssl()

import httpx
from . import config


def _post(chat_id: str, text: str) -> bool:
    if not config.TELEGRAM_BOT_TOKEN or not chat_id:
        print("[VELDRIN:console->%s] %s" % (chat_id or "none", text.replace("\n", "\n  ")))
        return True
    try:
        r = httpx.post(
            "https://api.telegram.org/bot%s/sendMessage" % config.TELEGRAM_BOT_TOKEN,
            json={"chat_id": chat_id, "text": text},
            timeout=15)
        ok = r.status_code == 200 and r.json().get("ok", False)
        if not ok:
            print("[VELDRIN:error] %s" % r.text[:200])
        return ok
    except Exception as e:
        print("[VELDRIN:error] %s" % e)
        return False


def send_vip(text: str) -> bool:
    return _post(config.VIP_CHAT_ID, text)


def send_public(text: str) -> bool:
    if not config.PUBLIC_CHAT_ID:
        return True   # free channel not configured; skip silently
    return _post(config.PUBLIC_CHAT_ID, text)


def send(text: str) -> bool:
    """Back-compat: default channel is VIP."""
    return send_vip(text)


def send_fault(reason: str) -> bool:
    # Faults are operational noise — log to Railway only, never a channel.
    print("[VELDRIN:fault] %s" % reason)
    return True
