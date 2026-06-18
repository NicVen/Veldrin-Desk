# Copyright (c) 2026. All rights reserved. Proprietary - no license granted.
"""VELDRIN market data intake via Twelve Data.

Fetches 1H and 4H history per pair for dual-timeframe confirmation.
Rate budget: 8 req/min free tier. 6 pairs x 2 timeframes = 12 req per full
refresh. Full refresh capped at every 15 min; cycle uses cached data otherwise.
"""
import time
from dataclasses import dataclass, field
from datetime import datetime

import truststore
truststore.inject_into_ssl()

import httpx

from . import config


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


class VeldrinFeed:

    def __init__(self):
        if not config.TWELVEDATA_API_KEY:
            raise RuntimeError("TWELVEDATA_API_KEY missing.")
        self.client = httpx.Client(timeout=20)
        self._cache: dict[str, PairQuote] = {}
        self._last_refresh = 0.0

    def _get(self, endpoint: str, **params):
        params["apikey"] = config.TWELVEDATA_API_KEY
        r = self.client.get("https://api.twelvedata.com/" + endpoint, params=params)
        data = r.json()
        if isinstance(data, dict) and data.get("status") == "error":
            raise RuntimeError("TwelveData: %s" % data.get("message"))
        return data

    def _pip_mult(self, pair: str) -> float:
        return 100.0 if "JPY" in pair else 10000.0

    def _fetch_pair(self, pair: str) -> PairQuote:
        td_symbol = pair[:3] + "/" + pair[3:]
        price_data = self._get("price", symbol=td_symbol)
        mid = float(price_data["price"])
        # synthesize spread from pair limits
        max_spread = config.MAX_SPREAD_PIPS.get(pair, 3.0)
        spread_price = (max_spread * 0.6) / self._pip_mult(pair)
        bid = round(mid - spread_price / 2, 5)
        ask = round(mid + spread_price / 2, 5)
        spread_pips = round((ask - bid) * self._pip_mult(pair), 1)

        # 1H history
        s1h = self._get("time_series", symbol=td_symbol,
                        interval="1h", outputsize=100)
        closes_1h = [float(v["close"]) for v in reversed(s1h.get("values", []))]
        time.sleep(10)   # 3 req per pair, 6 pairs = 18 req; pace to stay under 8/min

        # 4H history
        s4h = self._get("time_series", symbol=td_symbol,
                        interval="4h", outputsize=50)
        closes_4h = [float(v["close"]) for v in reversed(s4h.get("values", []))]
        time.sleep(10)

        return PairQuote(pair=pair, bid=bid, ask=ask, spread_pips=spread_pips,
                         ts=datetime.now(config.NZT),
                         closes_1h=closes_1h, closes_4h=closes_4h)

    def refresh(self) -> dict[str, PairQuote]:
        """Full refresh of all pairs. Cached for 15 min to respect rate limits."""
        if time.time() - self._last_refresh < 2100 and self._cache:  # 35 min = ~738 req/day
            return self._cache
        for pair in config.PAIRS:
            try:
                self._cache[pair] = self._fetch_pair(pair)
            except Exception as e:
                print("[INTAKE] %s failed: %s" % (pair, e))
        self._last_refresh = time.time()
        return self._cache
