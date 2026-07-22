"""Monthly digest written by Claude Sonnet, cached per month."""

import json
import os

from sqlalchemy.orm import Session

from app import analytics
from app.models import Insight

SONNET = "claude-sonnet-4-6"


def get_insight(db: Session, month: str, refresh: bool = False) -> dict:
    cached = db.get(Insight, month)
    if cached and not refresh:
        return {"month": month, "content": cached.content, "model": cached.model,
                "created_at": cached.created_at.isoformat(), "cached": True}
    if not refresh:
        # never generate implicitly -- Sonnet calls only on explicit Generate
        return {"month": month, "content": None, "cached": False}

    if not os.environ.get("ANTHROPIC_API_KEY"):
        return {"month": month, "content": None, "error": "ANTHROPIC_API_KEY not set"}

    import anthropic

    stats = analytics.month_stats(db, month)
    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=SONNET,
        max_tokens=2000,
        system=(
            "You are a sharp, friendly personal-finance analyst writing a "
            "monthly digest for a dashboard. Currency is GBP. Be concrete and "
            "numeric: what changed vs last month, what's creeping up, "
            "anomalies, subscription observations, one or two actionable "
            "suggestions. Use short markdown sections with a few bullets. "
            "No preamble, no generic advice."
        ),
        messages=[{
            "role": "user",
            "content": f"Write the digest for {month}. Data:\n"
            + json.dumps(stats, default=str),
        }],
    )
    content = next(b.text for b in resp.content if b.type == "text")
    db.merge(Insight(month=month, content=content, model=SONNET))
    db.commit()
    return {"month": month, "content": content, "model": SONNET, "cached": False}
