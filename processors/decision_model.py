"""
decision_model.py — Layer 3 consumer: reads classified signals → produces equity decisions
This is the interface between the regulatory intelligence pipeline and your trading decisions.

Usage:
    from decision_model import DecisionModel
    dm = DecisionModel()
    decisions = dm.run(tickers=["RELIANCE", "INFY"])
    for d in decisions:
        print(d)
"""

import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional
import sys as _sys, os as _os; _sys.path.insert(0, _os.path.dirname(_os.path.dirname(__file__))); from db.regulatory_schema import get_conn

logger = logging.getLogger("decision_model")


# ─────────────────────────────────────────────────────────────────────────────
# 1.  DATA STRUCTURES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class EquityDecision:
    ticker: str
    action: str               # BUY | SELL | HOLD | AVOID | INVESTIGATE
    conviction: str           # HIGH | MEDIUM | LOW
    confidence: float         # 0-1
    primary_driver: str       # event_type that drove the decision
    supporting_signals: int   # count of agreeing signals
    contrary_signals: int     # count of opposing signals
    rationale: str
    risk_flags: list[str]
    generated_at: str

    def to_dict(self):
        return asdict(self)

    def __str__(self):
        flags = " | ".join(self.risk_flags) if self.risk_flags else "—"
        return (
            f"[{self.ticker:12s}] {self.action:12s} | {self.conviction:6s} "
            f"| conf={self.confidence:.2f} | driver={self.primary_driver}\n"
            f"  → {self.rationale}\n"
            f"  ⚠ Risks: {flags}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 2.  SCORING WEIGHTS
# ─────────────────────────────────────────────────────────────────────────────

SEVERITY_WEIGHT = {"CRITICAL": 1.0, "HIGH": 0.75, "MEDIUM": 0.4, "LOW": 0.15}
DIRECTION_SCORE = {"BULLISH": +1, "BEARISH": -1, "NEUTRAL": 0}

# Event types that directly drive action
ACTION_OVERRIDES = {
    "INSOLVENCY":         {"BEARISH": "SELL",  "NEUTRAL": "AVOID"},
    "REGULATORY_PENALTY": {"BEARISH": "SELL",  "NEUTRAL": "AVOID"},
    "INSIDER_TRADE":      {"BEARISH": "SELL",  "BULLISH": "INVESTIGATE"},
    "MERGER_ACQUISITION": {"BULLISH": "BUY",   "BEARISH": "AVOID"},
    "CREDIT_RATING_CHANGE": {"BEARISH": "SELL","BULLISH": "BUY"},
}

RISK_FLAG_RULES = {
    "INSOLVENCY":          "⚠️ Active insolvency proceedings",
    "REGULATORY_PENALTY":  "⚠️ Regulatory enforcement action",
    "INSIDER_TRADE":       "🔍 Insider trading disclosure",
    "MERGER_ACQUISITION":  "ℹ️ M&A event — regulatory uncertainty",
    "CREDIT_RATING_CHANGE":"📉 Credit rating event",
    "MACRO_REGULATORY":    "🏦 Macro/systemic risk signal",
}


# ─────────────────────────────────────────────────────────────────────────────
# 3.  DECISION LOGIC
# ─────────────────────────────────────────────────────────────────────────────

class DecisionModel:
    """
    Reads unconsumed signals from the DB and produces EquityDecision objects.
    """

    def __init__(self, mark_consumed: bool = True):
        self.mark_consumed = mark_consumed

    def _fetch_signals(self, tickers: Optional[list] = None) -> list:
        conn = get_conn()
        if tickers:
            placeholders = ",".join("?" * len(tickers))
            rows = conn.execute(f"""
                SELECT s.*, c.event_type, c.summary, c.keywords
                FROM signals s
                JOIN classified_events c ON c.id = s.source_event_id
                WHERE s.consumed = 0
                  AND (s.valid_until IS NULL OR s.valid_until > CURRENT_TIMESTAMP)
                  AND s.ticker IN ({placeholders})
                ORDER BY s.valid_from DESC
            """, tickers).fetchall()
        else:
            rows = conn.execute("""
                SELECT s.*, c.event_type, c.summary, c.keywords
                FROM signals s
                JOIN classified_events c ON c.id = s.source_event_id
                WHERE s.consumed = 0
                  AND (s.valid_until IS NULL OR s.valid_until > CURRENT_TIMESTAMP)
                ORDER BY s.valid_from DESC
            """).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def _aggregate_ticker(self, ticker: str, signals: list) -> EquityDecision:
        """Aggregate multiple signals for one ticker into a single decision."""
        bull_score = 0.0
        bear_score = 0.0
        risk_flags = []
        event_types = []
        summaries = []

        for sig in signals:
            w = SEVERITY_WEIGHT.get(sig["severity"], 0.2) * sig.get("confidence", 0.5)
            d = DIRECTION_SCORE.get(sig["direction"], 0)
            if d > 0:
                bull_score += w
            elif d < 0:
                bear_score += w

            et = sig.get("event_type", "REGULATORY_FILING")
            event_types.append(et)
            summaries.append(sig.get("rationale") or sig.get("summary", ""))

            if et in RISK_FLAG_RULES:
                flag = RISK_FLAG_RULES[et]
                if flag not in risk_flags:
                    risk_flags.append(flag)

        net = bull_score - bear_score
        total = bull_score + bear_score or 1
        confidence = round(min(abs(net) / total, 1.0), 2)

        # Determine primary driver (most severe event type)
        severity_order = ["INSOLVENCY","REGULATORY_PENALTY","INSIDER_TRADE",
                          "MERGER_ACQUISITION","CREDIT_RATING_CHANGE",
                          "MACRO_REGULATORY","RESULTS_EARNINGS","BOARD_CHANGE",
                          "CORPORATE_ACTION","REGULATORY_FILING"]
        primary_driver = next((et for et in severity_order if et in event_types),
                              event_types[0] if event_types else "UNKNOWN")

        # Action mapping
        if net > 0.6:
            action = "BUY"
        elif net < -0.6:
            action = "SELL"
        elif net < -0.2:
            action = "AVOID"
        elif net > 0.2:
            action = "HOLD"
        else:
            action = "HOLD"

        # Override with specific event rules
        override_dir = "BULLISH" if net > 0 else ("BEARISH" if net < 0 else "NEUTRAL")
        if primary_driver in ACTION_OVERRIDES:
            ov = ACTION_OVERRIDES[primary_driver]
            if override_dir in ov:
                action = ov[override_dir]

        # Conviction
        if confidence >= 0.7:
            conviction = "HIGH"
        elif confidence >= 0.4:
            conviction = "MEDIUM"
        else:
            conviction = "LOW"

        supporting = sum(1 for s in signals if DIRECTION_SCORE.get(s["direction"],0) * (1 if net>=0 else -1) > 0)
        contrary   = len(signals) - supporting

        rationale = summaries[0] if summaries else f"{len(signals)} regulatory signal(s) processed for {ticker}"

        return EquityDecision(
            ticker=ticker,
            action=action,
            conviction=conviction,
            confidence=confidence,
            primary_driver=primary_driver,
            supporting_signals=supporting,
            contrary_signals=contrary,
            rationale=rationale[:200],
            risk_flags=risk_flags,
            generated_at=datetime.utcnow().isoformat() + "Z",
        )

    def run(self, tickers: Optional[list] = None) -> list[EquityDecision]:
        """
        Main entry point. Returns list of EquityDecision objects.
        Pass tickers=None to process all pending signals.
        """
        raw_signals = self._fetch_signals(tickers)
        if not raw_signals:
            logger.info("No unconsumed signals found.")
            return []

        # Group by ticker
        grouped: dict[str, list] = {}
        for sig in raw_signals:
            t = sig["ticker"] or "MARKET"
            grouped.setdefault(t, []).append(sig)

        decisions = []
        for ticker, sigs in grouped.items():
            d = self._aggregate_ticker(ticker, sigs)
            decisions.append(d)

        # Mark signals consumed
        if self.mark_consumed:
            conn = get_conn()
            ids = [s["id"] for s in raw_signals]
            conn.execute(
                f"UPDATE signals SET consumed=1 WHERE id IN ({','.join('?'*len(ids))})",
                ids
            )
            conn.commit()
            conn.close()

        decisions.sort(key=lambda d: (
            {"SELL":0,"AVOID":1,"INVESTIGATE":2,"BUY":3,"HOLD":4}.get(d.action, 5),
            -d.confidence
        ))

        return decisions

    def get_portfolio_view(self, tickers: list) -> dict:
        """
        Non-consuming view of the latest signals for a portfolio of tickers.
        Returns a dict keyed by ticker with signal summary.
        """
        conn = get_conn()
        result = {}
        for ticker in tickers:
            rows = conn.execute("""
                SELECT s.direction, s.severity, s.confidence, s.valid_from,
                       c.event_type, c.summary
                FROM signals s
                JOIN classified_events c ON c.id = s.source_event_id
                WHERE s.ticker = ?
                  AND (s.valid_until IS NULL OR s.valid_until > CURRENT_TIMESTAMP)
                ORDER BY s.valid_from DESC
                LIMIT 5
            """, (ticker,)).fetchall()
            result[ticker] = [dict(r) for r in rows]
        conn.close()
        return result

    def get_critical_alerts(self) -> list:
        """Return all unread CRITICAL signals — for intraday alert system."""
        conn = get_conn()
        rows = conn.execute("""
            SELECT s.ticker, s.direction, s.severity, s.rationale, s.valid_from,
                   c.event_type, c.summary, r.source, r.title
            FROM signals s
            JOIN classified_events c ON c.id = s.source_event_id
            JOIN raw_events r ON r.id = c.raw_event_id
            WHERE s.severity = 'CRITICAL' AND s.consumed = 0
            ORDER BY s.valid_from DESC
        """).fetchall()
        conn.close()
        return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# 4.  CLI TEST
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    dm = DecisionModel(mark_consumed=False)

    print("\n" + "="*70)
    print("  CRITICAL ALERTS")
    print("="*70)
    for alert in dm.get_critical_alerts():
        print(f"  [{alert['ticker']:12s}] {alert['severity']:8s} {alert['direction']:8s} "
              f"| {alert['event_type']}")
        print(f"   {alert['title'][:90]}")
        print()

    print("="*70)
    print("  EQUITY DECISIONS")
    print("="*70)
    decisions = dm.run()
    for d in decisions:
        print(d)
        print()
