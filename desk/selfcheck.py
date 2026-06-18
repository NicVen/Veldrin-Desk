# Copyright (c) 2026. All rights reserved. Proprietary - no license granted.
"""VELDRIN self-check pass. Mandatory before every dispatch.

Checks beyond STAALWAG gold desk:
- Session filter: London/NY hours only
- Spread limit per pair (pips)
- Dual-TF agreement (1H + 4H)
- Anti-flood: pair daily count + total daily count
- Correlation confirmation (handled by gates, flagged here)
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import config
from .intake import PairQuote
from .signal import ForexSignal


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str


@dataclass
class SelfCheckReport:
    results: list[CheckResult] = field(default_factory=list)
    fault: str | None = None

    @property
    def passed(self) -> bool:
        return self.fault is None and all(r.passed for r in self.results)

    def text(self) -> str:
        lines = ["SELF-CHECK REPORT"]
        for r in self.results:
            lines.append("[%s] %s - %s" % ("PASS" if r.passed else "FAIL",
                                            r.name, r.detail))
        if self.fault:
            lines.append("[FAULT] %s" % self.fault)
        lines.append("VERDICT: %s" % ("DISPATCH" if self.passed else "BLOCKED"))
        return "\n".join(lines)


def run(sig: ForexSignal, quote: PairQuote,
        recent_keys: dict[str, datetime],
        pair_day_count: dict[str, int],
        total_day_count: int,
        heartbeats: dict[str, bool],
        now: datetime | None = None) -> SelfCheckReport:
    now = now or datetime.now(config.NZT)
    rep = SelfCheckReport()

    # 1. Heartbeat - dead component = FAULT
    dead = [n for n, alive in heartbeats.items() if not alive]
    if dead:
        rep.fault = "Components missed heartbeat: %s" % ", ".join(dead)
        rep.results.append(CheckResult("heartbeat", False, rep.fault))
        return rep
    rep.results.append(CheckResult("heartbeat", True,
                       "alive: %s" % ", ".join(sorted(heartbeats))))

    # 2. Session filter (London + NY only: 08:00-22:00 UTC)
    utc_hour = now.astimezone(timezone.utc).hour
    in_session = config.SESSION_OPEN_UTC <= utc_hour < config.SESSION_CLOSE_UTC
    rep.results.append(CheckResult("session_filter", in_session,
                       "UTC hour %d, session %d-%d"
                       % (utc_hour, config.SESSION_OPEN_UTC,
                          config.SESSION_CLOSE_UTC)))

    # 3. Data freshness
    age = quote.age_seconds(now)
    rep.results.append(CheckResult("data_freshness",
                       age <= config.DATA_FRESHNESS_MAX_S,
                       "age %.0fs (limit %ds)" % (age, config.DATA_FRESHNESS_MAX_S)))

    # 4. Spread check
    max_spread = config.MAX_SPREAD_PIPS.get(sig.pair, 3.0)
    spread_ok = quote.spread_pips <= max_spread
    rep.results.append(CheckResult("spread",
                       spread_ok,
                       "%.1f pips (limit %.1f pips for %s)"
                       % (quote.spread_pips, max_spread, sig.pair)))

    # 5. Dual-TF confirmation
    tf_ok = sig.tf_1h == sig.tf_4h == sig.direction
    rep.results.append(CheckResult("dual_tf_confirmation", tf_ok,
                       "1H=%s 4H=%s signal=%s"
                       % (sig.tf_1h, sig.tf_4h, sig.direction)))

    # 6. RR check (min 1:2)
    risk = abs(sig.entry - sig.sl)
    reward = abs(sig.tp - sig.entry)
    rr = reward / risk if risk > 0 else 0.0
    rep.results.append(CheckResult("rr_ratio", rr >= config.MIN_RR,
                       "RR %.2f (min %.1f)" % (rr, config.MIN_RR)))

    # 7. Duplicate / lookback guard
    last = recent_keys.get(sig.key())
    if last is not None:
        mins = (now - last).total_seconds() / 60
        dup_ok = mins >= config.DUPLICATE_LOOKBACK_MIN
        detail = "same signal %.0f min ago (min gap %d min)" % (
            mins, config.DUPLICATE_LOOKBACK_MIN)
    else:
        dup_ok, detail = True, "no recent duplicate"
    rep.results.append(CheckResult("duplicate_guard", dup_ok, detail))

    # 8. Anti-flood: pair daily count
    pair_count = pair_day_count.get(sig.pair, 0)
    pair_ok = pair_count < config.MAX_SIGNALS_PER_PAIR_PER_DAY
    rep.results.append(CheckResult("flood_pair",
                       pair_ok,
                       "%s: %d signals today (max %d)"
                       % (sig.pair, pair_count,
                          config.MAX_SIGNALS_PER_PAIR_PER_DAY)))

    # 9. Anti-flood: total daily count
    total_ok = total_day_count < config.MAX_SIGNALS_TOTAL_PER_DAY
    rep.results.append(CheckResult("flood_total",
                       total_ok,
                       "total today: %d (max %d)"
                       % (total_day_count, config.MAX_SIGNALS_TOTAL_PER_DAY)))

    return rep
