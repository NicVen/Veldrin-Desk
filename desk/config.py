# Copyright (c) 2026. All rights reserved. Proprietary - no license granted.
"""VELDRIN configuration. Forex major pairs signal desk."""
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env", override=True)

NZT = ZoneInfo("Pacific/Auckland")

PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF"]

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
# VIP = full signals + management alerts (paid, private). PUBLIC = free teasers.
# Back-compat: if VIP_CHAT_ID unset, fall back to TELEGRAM_CHAT_ID.
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
VIP_CHAT_ID    = os.getenv("VIP_CHAT_ID", TELEGRAM_CHAT_ID)
PUBLIC_CHAT_ID = os.getenv("PUBLIC_CHAT_ID", "")   # empty = no free teasers posted
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY", "")
CYCLE_SECONDS = int(os.getenv("CYCLE_SECONDS", "300"))   # 5 min cycles
DESK_LABEL = os.getenv("DESK_LABEL", "VELDRIN")
STYLE = os.getenv("STYLE", "Intraday")   # trade horizon shown on signals (1H+4H confirmation)
LEDGER_PATH = Path(os.getenv("LEDGER_PATH", "/tmp/veldrin.db"))

# Self-check thresholds
DATA_FRESHNESS_MAX_S = 300
DUPLICATE_LOOKBACK_MIN = 30        # min gap between same-pair signals
MIN_RR = 2.0                       # minimum reward:risk (institutional standard)

# Spread limits (pips)
MAX_SPREAD_PIPS = {
    "EURUSD": 2.0, "GBPUSD": 2.0, "USDJPY": 2.0,
    "AUDUSD": 3.0, "USDCAD": 3.0, "USDCHF": 3.0,
}

# Session filter: London + NY only (UTC hours)
SESSION_OPEN_UTC = 8     # 08:00 UTC London open
SESSION_CLOSE_UTC = 22   # 22:00 UTC NY close

# Anti-flood
MAX_SIGNALS_PER_PAIR_PER_DAY = 3
MAX_SIGNALS_TOTAL_PER_DAY = 8
