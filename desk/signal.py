# Copyright (c) 2026. All rights reserved. Proprietary - no license granted.
"""VELDRIN signal generation with dual-timeframe confirmation.

Two-timeframe rule: both 1H AND 4H must agree on direction (MA cross + momentum)
before a signal is generated. One timeframe alone is not enough.

PORT POINT: swap the body of _direction() with BLOUSTAAL V13 logic when ready.
The Signal contract and dual-TF confirmation wrapper stay fixed.
"""
from dataclasses import dataclass
from datetime import datetime

from .intake import PairQuote
from . import config

ATR_LOOKBACK = 14
SL_ATR = 1.5
TP1_R  = 1.0    # partial close level (1R — close 50%)
TP2_R  = 2.0    # tighten trail level (2R)
TP3_R  = 3.0    # lock-hard trail level (3R — remainder runs free)


@dataclass
class ForexSignal:
    pair: str
    direction: str       # LONG / SHORT
    entry: float
    sl: float
    tp1: float           # 1R — close 50% here
    tp2: float           # 2R — tighten trail
    tp3: float           # 3R — lock hard, remainder runs unlimited
    ts: datetime
    tf_1h: str           # 1H bias
    tf_4h: str           # 4H bias
    atr: float

    def key(self) -> str:
        return "%s:%s" % (self.pair, self.direction)

    def pip_mult(self) -> float:
        return 100.0 if "JPY" in self.pair else 10000.0

    def message(self, lots: float, freshness_s: float) -> str:
        pm = self.pip_mult()
        sl_pips  = round(abs(self.entry - self.sl)  * pm, 1)
        tp1_pips = round(abs(self.tp1   - self.entry) * pm, 1)
        tp2_pips = round(abs(self.tp2   - self.entry) * pm, 1)
        tp3_pips = round(abs(self.tp3   - self.entry) * pm, 1)
        return ("VELDRIN SIGNAL\n"
                "Pair: %s\n"
                "Direction: %s\n"
                "Entry: %s\n"
                "SL: %s (%.1f pips)\n"
                "── RUNNER LEVELS ──\n"
                "TP1: %s (%.1f pips) → close 50%%\n"
                "TP2: %s (%.1f pips) → tighten trail\n"
                "TP3: %s (%.1f pips) → lock hard, run free\n"
                "Size: %.2f lots (1%% risk, fixed)\n"
                "1H bias: %s | 4H bias: %s\n"
                "Time: %s NZT\n"
                "Data freshness: %.0fs - PASS"
                % (self.pair, self.direction,
                   self.entry, self.sl, sl_pips,
                   self.tp1, tp1_pips,
                   self.tp2, tp2_pips,
                   self.tp3, tp3_pips,
                   lots,
                   self.tf_1h, self.tf_4h,
                   self.ts.strftime("%Y-%m-%d %H:%M:%S"),
                   freshness_s))


def _atr(closes: list[float]) -> float:
    diffs = [abs(b - a) for a, b in zip(closes[-ATR_LOOKBACK - 1:],
                                         closes[-ATR_LOOKBACK:])]
    return sum(diffs) / len(diffs) if diffs else 0.0


def _direction(closes: list[float]) -> str | None:
    """Simple MA cross bias. PORT POINT: replace with BLOUSTAAL V13 logic."""
    if len(closes) < 50:
        return None
    fast = sum(closes[-10:]) / 10
    slow = sum(closes[-50:]) / 50
    if fast > slow * 1.0003:
        return "LONG"
    if fast < slow * 0.9997:
        return "SHORT"
    return None


def generate(quote: PairQuote) -> ForexSignal | None:
    if len(quote.closes_1h) < 50 or len(quote.closes_4h) < 20:
        return None

    bias_1h = _direction(quote.closes_1h)
    bias_4h = _direction(quote.closes_4h)

    # Both timeframes must agree — dual-TF confirmation rule
    if bias_1h is None or bias_4h is None or bias_1h != bias_4h:
        return None

    atr = _atr(quote.closes_1h)
    if atr <= 0:
        return None

    dp = 3 if "JPY" in quote.pair else 5

    if bias_1h == "LONG":
        entry = quote.ask
        sl    = entry - SL_ATR * atr
        risk  = entry - sl
        tp1   = round(entry + risk * TP1_R, dp)
        tp2   = round(entry + risk * TP2_R, dp)
        tp3   = round(entry + risk * TP3_R, dp)
    else:
        entry = quote.bid
        sl    = entry + SL_ATR * atr
        risk  = sl - entry
        tp1   = round(entry - risk * TP1_R, dp)
        tp2   = round(entry - risk * TP2_R, dp)
        tp3   = round(entry - risk * TP3_R, dp)

    return ForexSignal(pair=quote.pair, direction=bias_1h,
                       entry=round(entry, dp), sl=round(sl, dp),
                       tp1=tp1, tp2=tp2, tp3=tp3,
                       ts=datetime.now(config.NZT),
                       tf_1h=bias_1h, tf_4h=bias_4h, atr=atr)
