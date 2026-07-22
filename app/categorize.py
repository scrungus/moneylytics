"""Category refinement: merchant rules first, Claude Haiku for the rest.

Emma already categorizes everything; we only refine the vague 'General'
bucket. Each unknown merchant is asked about exactly once -- the answer is
stored as an llm-sourced rule, and manual rules/overrides always win.
"""

import json
import logging
import os

from sqlalchemy.orm import Session

from app.models import MerchantRule, Transaction

log = logging.getLogger("moneylytics.categorize")

HAIKU = "claude-haiku-4-5"

REFINABLE_EMMA_CATEGORIES = {"General", ""}
REFINABLE_TYPES = {"Purchase", "Direct Debit", "Atm"}

CATEGORIES = [
    "Groceries", "Eating Out", "Transport", "Bills", "Shopping",
    "Entertainment", "Housing", "Personal Care", "Health", "Cash",
    "Income", "Investments", "Savings", "Gifts", "Holidays",
    "Education", "Charity", "General", "Excluded",
]

_SCHEMA = {
    "type": "object",
    "properties": {
        "assignments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "merchant": {"type": "string"},
                    "category": {"type": "string", "enum": CATEGORIES},
                },
                "required": ["merchant", "category"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["assignments"],
    "additionalProperties": False,
}


def _apply_rules(db: Session) -> int:
    rules = {r.merchant_key: r.category for r in db.query(MerchantRule).all()}
    if not rules:
        return 0
    n = 0
    for t in db.query(Transaction).all():
        cat = rules.get(t.merchant_key)
        if cat and t.category_refined != cat:
            t.category_refined = cat
            n += 1
    db.commit()
    return n


def _unknown_merchants(db: Session) -> list[str]:
    known = {r.merchant_key for r in db.query(MerchantRule).all()}
    keys = set()
    for t in db.query(Transaction).filter(
        Transaction.category_emma.in_(REFINABLE_EMMA_CATEGORIES),
        Transaction.type.in_(REFINABLE_TYPES),
        Transaction.category_refined == "",
        Transaction.category_override == "",
    ):
        k = t.merchant_key
        if k and k not in known:
            keys.add(k)
    return sorted(keys)


def _ask_haiku(merchants: list[str]) -> dict[str, str]:
    import anthropic

    client = anthropic.Anthropic()
    out: dict[str, str] = {}
    for i in range(0, len(merchants), 50):
        batch = merchants[i : i + 50]
        resp = client.messages.create(
            model=HAIKU,
            max_tokens=4096,
            system=(
                "You categorize UK bank transaction merchants for a personal "
                "finance dashboard. Assign each merchant name the most likely "
                "category. These are merchants Emma (the budgeting app) could "
                "only label 'General'. Use 'General' only when genuinely "
                "ambiguous."
            ),
            output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
            messages=[{
                "role": "user",
                "content": "Categorize these merchants:\n"
                + "\n".join(f"- {m}" for m in batch),
            }],
        )
        text = next(b.text for b in resp.content if b.type == "text")
        for a in json.loads(text)["assignments"]:
            if a["merchant"] in batch:
                out[a["merchant"]] = a["category"]
    return out


def categorize_new(db: Session) -> dict:
    applied = _apply_rules(db)
    unknown = _unknown_merchants(db)
    llm_added = 0
    if unknown and os.environ.get("ANTHROPIC_API_KEY"):
        try:
            assignments = _ask_haiku(unknown)
            for merchant, category in assignments.items():
                db.merge(MerchantRule(merchant_key=merchant, category=category, source="llm"))
            db.commit()
            llm_added = len(assignments)
            if llm_added:
                applied += _apply_rules(db)
        except Exception:
            log.exception("haiku categorization failed; will retry next sync")
    return {"rules_applied": applied, "llm_rules_added": llm_added}
