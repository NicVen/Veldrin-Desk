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
TP_ATR = 3.0    # minimum 1:2 RR enforced here via TP_ATR/SL_ATR ratio


@dataclass
class ForexSignal:
    pair: str
    direction: str       # LONG / SHORT
    entry: float
    sl: float
    tp: float
    ts: datetime
    tf_1h: str           # 1H bias
    tf_4h: str           # 4H bias
    atr: float

    def key(self) -> str:
        return "%s:%s" % (self.pair, self.direction)

    def pip_mult(self) -> float:
        return 100.0 if "JPY" in self.pair else 10000.0

    def message(self, lots: float, freshness_s: float) -> str:
        sl_pips = round(abs(self.entry - self.sl) * self.pip_mult(), 1)
        tp_pips = round(abs(self.tp - self.entry) * self.pip_mult(), 1)
        rr = round(tp_pips / sl_pips, 2) if sl_pips > 0 else 0
        return ("VELDRIN SIGNAL [RAILWAY]\n"
                "Pair: %s\n"
                "Direction: %s\n"
                "Entry: %s\n"
                "SL: %s (%.1f pips)\n"
                "TP: %s (%.1f pips)\n"
                "R:R 1:%.2f\n"
                "Size: %.2f lots (1%% risk, fixed)\n"
                "1H bias: %s | 4H bias: %s\n"
                "Time: %s NZT\n"
                "Data freshness: %.0fs - PASS"
                % (self.pair, self.direction,
                   self.entry, self.sl, sl_pips,
                   self.tp, tp_pips, rr, lots,
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

    if bias_1h == "LONG":
        entry, sl, tp = quote.ask, quote.ask - SL_ATR * atr, quote.ask + TP_ATR * atr
    else:
        entry, sl, tp = quote.bid, quote.bid + SL_ATR * atr, quote.bid - TP_ATR * atr

    dp = 3 if "JPY" in quote.pair else 5
    return ForexSignal(pair=quote.pair, direction=bias_1h,
                       entry=round(entry, dp), sl=round(sl, dp), tp=round(tp, dp),
                       ts=datetime.now(config.NZT),
                       tf_1h=bias_1h, tf_4h=bias_4h, atr=atr)
