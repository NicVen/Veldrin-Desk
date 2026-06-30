# Copyright (c) 2026. All rights reserved. Proprietary - no license granted.
"""VELDRIN market data intake via Yahoo's chart API.

FREE, no API key, no daily credit cap -> the desk runs 24h and produces
signals as they form (replaces Twelve Data, which capped at 800/day and
put the desk to sleep mid-session).

Fetches hourly history per pair and resamples to 4H (Yahoo has no native
4H interval) so the dual-timeframe (1H + 4H) confirmation rule is intact.
Windows SSL handled by truststore (OS cert store).
"""
import time
from dataclasses import dataclass, field
from datetime import datetime

try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass
import requests

from . import config

_HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=3mo&interval=60m"


@dataclass
class PairQuote:
    pair: str
    bid: float
    ask: float
    ts: datetime
    closes_1h: list[float] = field(default_factory=list)
    closes_4h: list[float] = field(default_factory=list)
    spread_pips: float = 0.0

    def age_seconds(self, now: datetime | None = None) -> float:
        now = now or datetime.now(config.NZT)
        return (now - self.ts).total_seconds()

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2


def _yahoo_symbol(pair: str) -> str:
    return pair[:3] + pair[3:] + "=X"      # EURUSD -> EURUSD=X


def _resample_4h(closes_1h: list[float]) -> list[float]:
    """Group hourly closes into 4-bar buckets; take each bucket's last close."""
    out = []
    for i in range(0, len(closes_1h), 4):
        bucket = closes_1h[i:i + 4]
        if bucket:
            out.append(bucket[-1])
    return out


class VeldrinFeed:

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(_HDR)
        self._cache: dict[str, PairQuote] = {}
        self._last_refresh = 0.0

    def _pip_mult(self, pair: str) -> float:
        return 100.0 if "JPY" in pair else 10000.0

    def _fetch_pair(self, pair: str) -> PairQuote:
        sym = _yahoo_symbol(pair)
        r = self.session.get(_URL.format(sym=sym), timeout=20)
        j = r.json()
        res = j["chart"]["result"][0]
        q = res["indicators"]["quote"][0]
        closes_1h = [c for c in q["close"] if c is not None]
        if len(closes_1h) < 60:
            raise RuntimeError("Yahoo returned insufficient 1h data (%d)" % len(closes_1h))

        closes_4h = _resample_4h(closes_1h)

        mid = closes_1h[-1]
        max_spread = config.MAX_SPREAD_PIPS.get(pair, 3.0)
        spread_price = (max_spread * 0.6) / self._pip_mult(pair)
        bid = round(mid - spread_price / 2, 5)
        ask = round(mid + spread_price / 2, 5)
        spread_pips = round((ask - bid) * self._pip_mult(pair), 1)

        return PairQuote(pair=pair, bid=bid, ask=ask, spread_pips=spread_pips,
                         ts=datetime.now(config.NZT),
                         closes_1h=closes_1h, closes_4h=closes_4h)

    def refresh(self) -> dict[str, PairQuote]:
        """Full refresh of all pairs. Yahoo is free + uncapped; cache ~5 min to be polite."""
        if time.time() - self._last_refresh < 300 and self._cache:
            return self._cache
        for pair in config.PAIRS:
            try:
                self._cache[pair] = self._fetch_pair(pair)
            except Exception as e:
                print("[INTAKE] %s failed: %s" % (pair, e))
        self._last_refresh = time.time()
        return self._cache
