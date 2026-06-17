"""
Collector + Analyzer: Concall Transcripts
Source type: Signal (Indicative / qualitative)
NLP-driven sentiment analysis with QoQ delta tracking
"""

import sqlite3
import json
import os
import re
from datetime import datetime
from collections import Counter

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'equity_research.db')

# ─── NLP DICTIONARIES ─────────────────────────────────────────────────────────

POSITIVE_WORDS = {
    'strong': 2, 'robust': 2, 'record': 2, 'outperform': 2, 'beat': 1,
    'growth': 1, 'momentum': 1, 'confident': 2, 'optimistic': 2,
    'improve': 1, 'expand': 1, 'accelerate': 2, 'win': 1, 'gain': 1,
    'opportunity': 1, 'pipeline': 1, 'demand': 1, 'margin expansion': 2,
    'market share': 1, 'guidance raised': 3, 'upgrade': 2, 'ramp': 1,
    'breakthrough': 2, 'ahead of expectations': 3, 'exceed': 2,
    'sustainable': 1, 'resilient': 1, 'dividend': 1, 'buyback': 1,
    'deleveraging': 2, 'debt free': 3, 'cash generation': 2,
}

NEGATIVE_WORDS = {
    'challenging': -2, 'headwind': -2, 'slowdown': -2, 'pressure': -1,
    'miss': -2, 'below expectations': -3, 'decline': -1, 'weak': -2,
    'concern': -1, 'risk': -1, 'uncertainty': -1, 'volatile': -1,
    'margin compression': -3, 'competition': -1, 'delay': -1,
    'cost overrun': -3, 'write-off': -2, 'impairment': -2,
    'guidance cut': -3, 'downgrade': -2, 'loss': -2, 'erosion': -2,
    'debt increase': -2, 'leverage': -1, 'litigation': -1,
    'regulatory': -1, 'disappointed': -2, 'difficult': -1,
    'cautious': -1, 'subdued': -1, 'muted': -1, 'underperform': -2,
}

RED_FLAG_PHRASES = [
    'promoter pledge', 'corporate governance', 'related party',
    'qualified opinion', 'going concern', 'fraud', 'investigation',
    'sebi notice', 'insolvency', 'default', 'npa', 'write-off',
    'management change', 'auditor resignation', 'guidance withdrawn',
    'working capital stress', 'cash flow negative', 'covenant breach',
]

POSITIVE_SIGNAL_PHRASES = [
    'market share gain', 'new client win', 'record order book',
    'guidance raised', 'margin expansion', 'debt reduction',
    'dividend increase', 'buyback', 'capacity utilization',
    'strong demand', 'profitable growth', 'capex completed',
    'new product launch', 'export growth', 'operating leverage',
]

GUIDANCE_BULLISH = ['raised guidance', 'confident of growth', 'accelerating', 'strong demand', 'beat estimates']
GUIDANCE_CAUTIOUS = ['cautious', 'wait and watch', 'subdued demand', 'visibility limited', 'headwinds']


def get_conn():
    return sqlite3.connect(DB_PATH)


def analyze_transcript(text: str) -> dict:
    """
    Perform NLP analysis on a concall transcript.
    Returns sentiment score, key topics, flags.
    """
    if not text:
        return {}

    text_lower = text.lower()
    words = re.findall(r'\b\w+\b', text_lower)
    word_count = len(words)

    # Score computation
    raw_score = 0
    for phrase, weight in POSITIVE_WORDS.items():
        count = text_lower.count(phrase)
        raw_score += count * weight
    for phrase, weight in NEGATIVE_WORDS.items():
        count = text_lower.count(phrase)
        raw_score += count * weight  # weight is already negative

    # Normalize to -1.0 to +1.0 range
    max_possible = word_count * 0.05
    normalized = max(-1.0, min(1.0, raw_score / max(max_possible, 1)))

    # Sentiment label
    if normalized >= 0.15:
        label = 'positive'
    elif normalized <= -0.15:
        label = 'negative'
    else:
        label = 'neutral'

    # Detect red flags
    red_flags = [p for p in RED_FLAG_PHRASES if p in text_lower]

    # Detect positive signals
    pos_signals = [p for p in POSITIVE_SIGNAL_PHRASES if p in text_lower]

    # Guidance tone
    bullish_hits = sum(1 for p in GUIDANCE_BULLISH if p in text_lower)
    cautious_hits = sum(1 for p in GUIDANCE_CAUTIOUS if p in text_lower)
    if bullish_hits > cautious_hits:
        guidance_tone = 'bullish'
    elif cautious_hits > bullish_hits:
        guidance_tone = 'cautious'
    else:
        guidance_tone = 'neutral'

    # Key topics (most frequent meaningful bigrams)
    bigrams = [f"{words[i]} {words[i+1]}" for i in range(len(words)-1)
               if len(words[i]) > 3 and len(words[i+1]) > 3]
    top_topics = [b for b, _ in Counter(bigrams).most_common(15)
                  if not b.startswith(('that ', 'this ', 'with '))][:10]

    # Management confidence (sentence-level positive/negative ratio)
    sentences = re.split(r'[.!?]', text)
    pos_sents = sum(1 for s in sentences if any(p in s.lower() for p in list(POSITIVE_WORDS)[:10]))
    neg_sents = sum(1 for s in sentences if any(p in s.lower() for p in list(NEGATIVE_WORDS)[:10]))
    confidence = pos_sents / max(pos_sents + neg_sents, 1)

    return {
        'sentiment_score': round(normalized, 3),
        'sentiment_label': label,
        'word_count': word_count,
        'key_topics': top_topics,
        'red_flags': red_flags,
        'positive_signals': pos_signals,
        'guidance_tone': guidance_tone,
        'mgmt_confidence_score': round(confidence, 3),
    }


def store_transcript(conn, ticker: str, call_date: str, fiscal_period: str,
                     transcript_text: str, url: str = None) -> int:
    """Store raw transcript and return its ID."""
    cur = conn.execute("""
        INSERT OR REPLACE INTO concall_transcripts
        (ticker, call_date, fiscal_period, transcript_text, transcript_url, word_count, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
    """, (ticker, call_date, fiscal_period, transcript_text, url,
          len(transcript_text.split())))
    conn.commit()
    return cur.lastrowid


def run_nlp_analysis(conn, ticker: str, fiscal_period: str):
    """Run NLP on stored transcript and compare with prior quarter."""
    # Fetch current transcript
    cur = conn.execute("""
        SELECT id, transcript_text FROM concall_transcripts
        WHERE ticker = ? AND fiscal_period = ?
    """, (ticker, fiscal_period))
    row = cur.fetchone()
    if not row:
        return None

    transcript_id, text = row
    analysis = analyze_transcript(text)

    # Fetch prior period score for delta
    cur2 = conn.execute("""
        SELECT sentiment_score FROM concall_nlp_analysis
        WHERE ticker = ? AND fiscal_period != ?
        ORDER BY fiscal_period DESC LIMIT 1
    """, (ticker, fiscal_period))
    prior = cur2.fetchone()
    prev_score = prior[0] if prior else None
    delta = round(analysis['sentiment_score'] - prev_score, 3) if prev_score is not None else None

    conn.execute("""
        INSERT OR REPLACE INTO concall_nlp_analysis
        (transcript_id, ticker, fiscal_period, sentiment_score, sentiment_label,
         prev_period_score, score_delta, key_topics, mgmt_confidence_score,
         guidance_tone, red_flags, positive_signals, analysed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
    """, (
        transcript_id, ticker, fiscal_period,
        analysis['sentiment_score'], analysis['sentiment_label'],
        prev_score, delta,
        json.dumps(analysis['key_topics']),
        analysis['mgmt_confidence_score'],
        analysis['guidance_tone'],
        json.dumps(analysis['red_flags']),
        json.dumps(analysis['positive_signals']),
    ))
    conn.commit()

    delta_str = f"{delta:+.3f}" if delta is not None else "N/A (first call)"
    print(f"    📊 {ticker} {fiscal_period}: {analysis['sentiment_label']} "
          f"(score={analysis['sentiment_score']}, Δ={delta_str})")
    if analysis['red_flags']:
        print(f"    🚩 Red flags: {', '.join(analysis['red_flags'])}")
    return analysis


# ─── SAMPLE TRANSCRIPT DATA ──────────────────────────────────────────────────

SAMPLE_TRANSCRIPTS = [
    {
        "ticker": "TCS",
        "call_date": "2025-10-11",
        "fiscal_period": "Q2FY26",
        "text": """
            Good evening everyone. We delivered a strong performance this quarter with record revenue
            of 61,000 crores. Our growth momentum is robust across all verticals. We are confident
            about the pipeline and demand environment. BFSI continues to be resilient with margin expansion.
            The management is optimistic about accelerating growth in Q3. We have won significant new clients
            and our order book is at an all-time high. We are seeing market share gain in Europe and North America.
            Capital return to shareholders continues - we declared a dividend and buyback.
            No major headwinds visible at this point. Demand environment remains strong.
            Our guidance remains positive and we are confident of profitable growth going forward.
        """
    },
    {
        "ticker": "TCS",
        "call_date": "2025-07-11",
        "fiscal_period": "Q1FY26",
        "text": """
            We delivered reasonable performance this quarter. Revenue grew 4% YoY but we did face
            some headwinds in discretionary spending. Demand environment is somewhat subdued in Europe.
            We are cautious about near-term outlook given macro uncertainty. Some deal delays observed.
            However our pipeline remains healthy. Margins were under pressure due to wage hikes.
            We remain resilient and confident of recovery in H2. The management is monitoring
            challenging conditions in BFSI vertical but sees improvement ahead.
        """
    },
    {
        "ticker": "RELIANCE",
        "call_date": "2025-10-20",
        "fiscal_period": "Q2FY26",
        "text": """
            Reliance delivered record consolidated revenue this quarter. Jio's growth momentum is
            exceptional with strong subscriber additions. Retail segment continues to expand aggressively.
            O2C business faced some margin compression due to weak refining margins globally.
            However, management is confident about new energy business ramp-up. Capex completed
            on schedule for new projects. Strong cash generation continues. Debt reduction on track.
            Green energy pipeline is strong with several breakthrough projects.
            Guidance raised for new energy segment. Operating leverage expected in H2.
        """
    },
    {
        "ticker": "HDFC",
        "call_date": "2025-10-18",
        "fiscal_period": "Q2FY26",
        "text": """
            HDFC Bank delivered stable performance. NIM under pressure due to deposit competition.
            Credit growth robust at 16% YoY. Asset quality remains strong with NPA at multi-year lows.
            Management is confident about margin recovery. CASA ratio improved showing resilient
            liability franchise. Retail loans showing strong demand particularly in home loans.
            Fee income growth strong. Technology investments continuing for market share gain.
            No concerns on asset quality. Dividend maintained. Capital adequacy comfortable.
            Cautious on wholesale segment given current rate environment.
        """
    },
]


def seed_sample_data():
    conn = get_conn()
    for t in SAMPLE_TRANSCRIPTS:
        store_transcript(conn, t['ticker'], t['call_date'],
                         t['fiscal_period'], t['text'].strip())
    # Run NLP in chronological order for each ticker to get delta
    for ticker in ['TCS', 'RELIANCE', 'HDFC']:
        rows = conn.execute("""
            SELECT fiscal_period FROM concall_transcripts
            WHERE ticker = ? ORDER BY call_date
        """, (ticker,)).fetchall()
        for (period,) in rows:
            run_nlp_analysis(conn, ticker, period)
    conn.close()
    print(f"  🌱 Concall NLP analysis complete for {len(SAMPLE_TRANSCRIPTS)} calls")


if __name__ == '__main__':
    seed_sample_data()
