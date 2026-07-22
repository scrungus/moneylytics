"""Aggregation queries.

Spend semantics: everything except Income, Excluded, and Transfer counts as
spend (negative amounts spend, positive refunds net against it). Linked
pairs (refunds) naturally cancel out because both sides are present. The
'Transfer' category is Emma's internal-money-movement bucket -- e.g. cash
coming back from your own savings account -- and belongs in neither income
nor spend. Transfers Emma left as 'General' (rent!) still count as spend.
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

NON_SPEND_CATS = ["Income", "Excluded", "Transfer"]


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
                (EFFECTIVE_CAT.notin_(NON_SPEND_CATS), -Transaction.amount),
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


def categories(db: Session, month: str | None = None, months: int = 12,
               date_from: str | None = None, date_to: str | None = None) -> dict:
    m = month_expr(db)
    q = (
        db.query(m.label("month"), EFFECTIVE_CAT, func.sum(-Transaction.amount).label("spend"))
        .filter(EFFECTIVE_CAT.notin_(NON_SPEND_CATS))
        .group_by(m, EFFECTIVE_CAT)
        .order_by(m)
    )
    by_month: dict[str, dict[str, float]] = defaultdict(dict)
    for r in q:
        by_month[r.month][r.category] = round(float(r.spend or 0), 2)
    all_months = sorted(by_month)[-months:]
    trend = {mo: by_month[mo] for mo in all_months}

    if date_from and date_to:
        rq = (
            db.query(EFFECTIVE_CAT, func.sum(-Transaction.amount).label("spend"))
            .filter(EFFECTIVE_CAT.notin_(NON_SPEND_CATS))
            .filter(Transaction.date >= date.fromisoformat(date_from))
            .filter(Transaction.date <= date.fromisoformat(date_to))
            .group_by(EFFECTIVE_CAT)
        )
        selected = {r.category: round(float(r.spend or 0), 2) for r in rq if (r.spend or 0) > 0}
        return {"trend": trend, "selected_month": f"{date_from} → {date_to}",
                "selected": selected, "range": True}

    selected = trend.get(month) if month else (trend[all_months[-1]] if all_months else {})
    return {"trend": trend, "selected_month": month or (all_months[-1] if all_months else None),
            "selected": selected or {}}


def merchants(db: Session, month: str | None = None, category: str | None = None,
              limit: int = 25, date_from: str | None = None,
              date_to: str | None = None) -> list[dict]:
    m = month_expr(db)
    key = func.lower(func.coalesce(
        func.nullif(Transaction.custom_name, ""),
        func.nullif(Transaction.merchant, ""),
        Transaction.counterparty,
    )).label("merchant")
    q = (
        db.query(key, func.sum(-Transaction.amount).label("spend"),
                 func.count().label("count"))
        .filter(EFFECTIVE_CAT.notin_(NON_SPEND_CATS))
    )
    if date_from and date_to:
        q = q.filter(Transaction.date >= date.fromisoformat(date_from),
                     Transaction.date <= date.fromisoformat(date_to))
    elif month:
        q = q.filter(m == month)
    if category:
        q = q.filter(EFFECTIVE_CAT == category)
    # group by the expression itself: the string "merchant" would resolve to
    # the raw transactions.merchant column, lumping all blank merchants together
    q = q.group_by(key).order_by(func.sum(-Transaction.amount).desc()).limit(limit)
    return [
        {"merchant": r.merchant or "(unknown)",
         "spend": round(float(r.spend or 0), 2), "count": r.count}
        for r in q if (r.spend or 0) > 0
    ]


def transactions(db: Session, month: str | None = None, category: str | None = None,
                 merchant: str | None = None, q: str | None = None,
                 limit: int = 100, offset: int = 0,
                 date_from: str | None = None, date_to: str | None = None) -> dict:
    m = month_expr(db)
    query = db.query(Transaction, EFFECTIVE_CAT)
    if date_from and date_to:
        query = query.filter(Transaction.date >= date.fromisoformat(date_from),
                             Transaction.date <= date.fromisoformat(date_to))
    elif month:
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
        .filter(EFFECTIVE_CAT.notin_(NON_SPEND_CATS))
        .order_by(Transaction.date)
        .all()
    )
    by_merchant: dict[str, list[Transaction]] = defaultdict(list)
    for t in txs:
        k = t.merchant_key
        if k:
            by_merchant[k].append(t)

    # Cluster each merchant's charges by amount (12% or £1 tolerance) so a
    # subscription whose price drifts by pennies stays one entry instead of
    # one entry per distinct amount.
    groups: dict[tuple, list[Transaction]] = {}
    for merchant, items in by_merchant.items():
        clusters: list[list[Transaction]] = []
        for t in sorted(items, key=lambda t: float(t.amount)):
            amt = -float(t.amount)
            for c in clusters:
                mean = sum(-float(x.amount) for x in c) / len(c)
                if abs(amt - mean) <= max(1.0, 0.12 * mean):
                    c.append(t)
                    break
            else:
                clusters.append([t])
        for i, c in enumerate(clusters):
            groups[(merchant, i)] = sorted(c, key=lambda t: t.date)

    subs = []
    today = date.today()
    for (merchant, _), items in groups.items():
        if len(items) < 3:
            continue
        # collapse charges within 3 days (double-rent months, split payments)
        # into one event so they don't destroy the cadence measurement
        dates = []
        for t in items:
            if not dates or (t.date - dates[-1]).days > 3:
                dates.append(t.date)
        if len(dates) < 3:
            continue
        # judge cadence on recent behaviour: old missed/irregular payments
        # shouldn't disqualify something that's been regular for months
        gaps = [(b - a).days for a, b in zip(dates, dates[1:])][-6:]
        avg_gap = sum(gaps) / len(gaps)
        if not (23 <= avg_gap <= 38 or 350 <= avg_gap <= 380 or 5 <= avg_gap <= 9):
            continue
        # subscriptions charge on a rhythm: an in-range *average* gap isn't
        # enough (TfL/Amazon habits pass that), the gaps must also be regular
        spread = (sum((g - avg_gap) ** 2 for g in gaps) / len(gaps)) ** 0.5
        if spread > max(2.5, 0.3 * avg_gap):
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
