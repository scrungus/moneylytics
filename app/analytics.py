"""Aggregation queries.

Spend semantics: everything except Income and Excluded counts as spend
(negative amounts spend, positive refunds net against it). Linked pairs
(internal transfers, refunds) naturally cancel out because both sides are
present. Transfers to your own external accounts (e.g. savings) show up as
spend until recategorized -- override them to 'Savings' or 'Excluded' once
and the rule sticks.
"""

from collections import defaultdict
from datetime import date

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models import Transaction

EFFECTIVE_CAT = case(
    (Transaction.category_override != "", Transaction.category_override),
    (Transaction.category_refined != "", Transaction.category_refined),
    else_=Transaction.category_emma,
).label("category")

def month_expr(db: Session):
    if db.bind.dialect.name == "sqlite":
        return func.strftime("%Y-%m", Transaction.date)
    return func.to_char(Transaction.date, "YYYY-MM")


def overview(db: Session, months: int = 12) -> list[dict]:
    m = month_expr(db)
    q = (
        db.query(
            m.label("month"),
            func.sum(case((EFFECTIVE_CAT == "Income", Transaction.amount), else_=0)).label("income"),
            func.sum(case(
                (EFFECTIVE_CAT.notin_(["Income", "Excluded"]), -Transaction.amount),
                else_=0,
            )).label("spend"),
        )
        .group_by("month")
        .order_by(m.desc())
        .limit(months)
    )
    rows = [
        {"month": r.month, "income": round(float(r.income or 0), 2),
         "spend": round(float(r.spend or 0), 2),
         "net": round(float(r.income or 0) - float(r.spend or 0), 2)}
        for r in q
    ]
    return list(reversed(rows))


def categories(db: Session, month: str | None = None, months: int = 12) -> dict:
    m = month_expr(db)
    q = (
        db.query(m.label("month"), EFFECTIVE_CAT, func.sum(-Transaction.amount).label("spend"))
        .filter(EFFECTIVE_CAT.notin_(["Income", "Excluded"]))
        .group_by("month", "category")
        .order_by(m)
    )
    by_month: dict[str, dict[str, float]] = defaultdict(dict)
    for r in q:
        by_month[r.month][r.category] = round(float(r.spend or 0), 2)
    all_months = sorted(by_month)[-months:]
    trend = {mo: by_month[mo] for mo in all_months}
    selected = trend.get(month) if month else (trend[all_months[-1]] if all_months else {})
    return {"trend": trend, "selected_month": month or (all_months[-1] if all_months else None),
            "selected": selected or {}}


def merchants(db: Session, month: str | None = None, category: str | None = None,
              limit: int = 25) -> list[dict]:
    m = month_expr(db)
    key = func.lower(func.coalesce(
        func.nullif(Transaction.custom_name, ""),
        func.nullif(Transaction.merchant, ""),
        Transaction.counterparty,
    )).label("merchant")
    q = (
        db.query(key, func.sum(-Transaction.amount).label("spend"),
                 func.count().label("count"))
        .filter(EFFECTIVE_CAT.notin_(["Income", "Excluded"]))
    )
    if month:
        q = q.filter(m == month)
    if category:
        q = q.filter(EFFECTIVE_CAT == category)
    q = q.group_by("merchant").order_by(func.sum(-Transaction.amount).desc()).limit(limit)
    return [
        {"merchant": r.merchant or "(unknown)",
         "spend": round(float(r.spend or 0), 2), "count": r.count}
        for r in q if (r.spend or 0) > 0
    ]


def transactions(db: Session, month: str | None = None, category: str | None = None,
                 merchant: str | None = None, q: str | None = None,
                 limit: int = 100, offset: int = 0) -> dict:
    m = month_expr(db)
    query = db.query(Transaction, EFFECTIVE_CAT)
    if month:
        query = query.filter(m == month)
    if category:
        query = query.filter(EFFECTIVE_CAT == category)
    if merchant:
        query = query.filter(func.lower(func.coalesce(
            func.nullif(Transaction.custom_name, ""),
            func.nullif(Transaction.merchant, ""),
            Transaction.counterparty,
        )) == merchant.lower())
    if q:
        like = f"%{q.lower()}%"
        query = query.filter(
            func.lower(Transaction.counterparty).like(like)
            | func.lower(Transaction.merchant).like(like)
            | func.lower(Transaction.notes).like(like)
            | func.lower(Transaction.custom_name).like(like)
        )
    total = query.count()
    rows = query.order_by(Transaction.date.desc()).offset(offset).limit(limit).all()
    return {
        "total": total,
        "items": [
            {
                "id": t.id, "date": t.date.isoformat(), "amount": float(t.amount),
                "account": t.account, "bank": t.bank,
                "category": cat, "category_emma": t.category_emma,
                "overridden": bool(t.category_override),
                "type": t.type, "merchant": t.merchant_key or t.counterparty.lower(),
                "display_name": t.custom_name or t.merchant or t.counterparty,
                "notes": t.notes,
            }
            for t, cat in rows
        ],
    }


def subscriptions(db: Session) -> list[dict]:
    """Detect recurring payments: same merchant, similar amount, regular cadence."""
    txs = (
        db.query(Transaction)
        .filter(Transaction.amount < 0)
        .filter(EFFECTIVE_CAT.notin_(["Income", "Excluded"]))
        .order_by(Transaction.date)
        .all()
    )
    groups: dict[tuple, list[Transaction]] = defaultdict(list)
    for t in txs:
        k = t.merchant_key
        if not k:
            continue
        groups[(k, round(float(t.amount)))].append(t)

    subs = []
    today = date.today()
    for (merchant, _), items in groups.items():
        if len(items) < 3:
            continue
        dates = [t.date for t in items]
        gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
        avg_gap = sum(gaps) / len(gaps)
        if not (23 <= avg_gap <= 38 or 350 <= avg_gap <= 380 or 5 <= avg_gap <= 9):
            continue
        cadence = "weekly" if avg_gap < 10 else ("monthly" if avg_gap < 40 else "yearly")
        amount = -float(items[-1].amount)
        active = (today - dates[-1]).days <= avg_gap * 2
        subs.append({
            "merchant": merchant, "amount": round(amount, 2), "cadence": cadence,
            "count": len(items), "last_paid": dates[-1].isoformat(),
            "active": active,
            "monthly_cost": round(amount if cadence == "monthly"
                                  else amount * 4.33 if cadence == "weekly"
                                  else amount / 12, 2),
        })
    subs.sort(key=lambda s: (-s["active"], -s["monthly_cost"]))
    return subs


def month_stats(db: Session, month: str) -> dict:
    """Compact stats bundle for the LLM insight prompt."""
    cats = categories(db, month=month, months=13)
    trend = cats["trend"]
    months_sorted = sorted(trend)
    prev = None
    if month in months_sorted:
        i = months_sorted.index(month)
        prev = months_sorted[i - 1] if i > 0 else None
    ov = {r["month"]: r for r in overview(db, months=13)}
    return {
        "month": month,
        "totals": ov.get(month, {}),
        "prev_totals": ov.get(prev, {}) if prev else {},
        "categories": trend.get(month, {}),
        "prev_categories": trend.get(prev, {}) if prev else {},
        "top_merchants": merchants(db, month=month, limit=15),
        "subscriptions": [s for s in subscriptions(db) if s["active"]],
    }
