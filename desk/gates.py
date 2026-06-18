# Copyright (c) 2026. All rights reserved. Proprietary - no license granted.
"""VELDRIN greed gates. Hard-coded. No override path. No Telegram command changes these.

Forex-specific rules differ from STAALWAG gold desk:
- 5% daily loss cap (prop-firm standard; forex needs more room than gold)
- Max 2 concurrent positions
- Correlation block: EURUSD + GBPUSD same direction blocked (>0.75 corr)
- No martingale: size is pure function of equity + stop distance
"""
from dataclasses import dataclass
from datetime import datetime

from . import config

RISK_PER_TRADE = 0.01          # 1% per trade
MAX_DAILY_LOSS = 0.02          # 2% daily cap
MAX_CONCURRENT_POSITIONS = 2

# Correlation map: pairs that cannot be open in same direction simultaneously
CORRELATED_PAIRS = {
    frozenset({"EURUSD", "GBPUSD"}): 0.83,   # block same direction
    frozenset({"AUDUSD", "USDCAD"}): -0.73,  # inverse: block opposite direction
    frozenset({"USDCAD", "EURUSD"}): -0.68,  # inverse
}


@dataclass
class GateDecision:
    allowed: bool
    reason: str
    lots: float = 0.0


def _pip_value(pair: str) -> float:
    """USD value of 1 pip per 1 standard lot. Approximate for major pairs."""
    jpy_pairs = {"USDJPY"}
    return 7.0 if pair in jpy_pairs else 10.0


def position_size(equity: float, pair: str, entry: float, sl: float) -> float:
    stop_pips = abs(entry - sl) * (100 if "JPY" in pair else 10000)
    if stop_pips <= 0:
        return 0.0
    risk_usd = equity * RISK_PER_TRADE
    lots = risk_usd / (stop_pips * _pip_value(pair))
    return round(max(lots, 0.0), 2)


def check_correlation(pair: str, direction: str,
                      open_positions: dict[str, str]) -> str | None:
    """Returns blocking reason string if correlation rule violated, else None."""
    for pair_set, corr in CORRELATED_PAIRS.items():
        if pair not in pair_set:
            continue
        other = next(p for p in pair_set if p != pair)
        if other not in open_positions:
            continue
        other_dir = open_positions[other]
        if corr > 0 and direction == other_dir:
            return ("Correlation block: %s and %s corr=%.2f, "
                    "cannot open both %s simultaneously."
                    % (pair, other, corr, direction))
        if corr < 0 and direction != other_dir:
            return ("Inverse correlation block: %s and %s corr=%.2f, "
                    "directions conflict." % (pair, other, corr))
    return None


def check(equity: float, day_start_equity: float,
          open_positions: dict[str, str],
          pair: str, direction: str,
          entry: float, sl: float,
          now: datetime | None = None) -> GateDecision:
    now = now or datetime.now(config.NZT)

    daily_loss = (day_start_equity - equity) / day_start_equity if day_start_equity > 0 else 0.0
    if daily_loss >= MAX_DAILY_LOSS:
        return GateDecision(False,
                            "CIRCUIT BREAKER: daily loss %.2f%% >= %.2f%%. "
                            "Desk halted until next NZT day."
                            % (daily_loss * 100, MAX_DAILY_LOSS * 100))

    if len(open_positions) >= MAX_CONCURRENT_POSITIONS:
        return GateDecision(False,
                            "Max concurrent positions (%d) reached."
                            % MAX_CONCURRENT_POSITIONS)

    corr_block = check_correlation(pair, direction, open_positions)
    if corr_block:
        return GateDecision(False, corr_block)

    lots = position_size(equity, pair, entry, sl)
    if lots <= 0:
        return GateDecision(False, "Position size zero (bad stop distance).")

    return GateDecision(True,
                        "Gates passed: risk %.1f%%, lots %.2f"
                        % (RISK_PER_TRADE * 100, lots), lots)
