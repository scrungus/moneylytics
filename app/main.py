import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import analytics, insights, sync
from app.db import SessionLocal, init_db
from app.models import MerchantRule, Transaction

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="moneylytics")

STATIC = Path(__file__).parent / "static"


@app.on_event("startup")
def startup():
    os.makedirs("data", exist_ok=True)
    init_db()


def get_db():
    db = SessionLocal()
    try:
        sync.refresh_if_stale(db)
        yield db
    finally:
        db.close()


@app.get("/api/meta")
def meta(db: Session = Depends(get_db)):
    months = analytics.overview(db, months=120)
    ls = sync.last_sync(db)
    cats = sorted({c for (c,) in db.query(analytics.EFFECTIVE_CAT).distinct()})
    return {
        "months": [m["month"] for m in months],
        "categories": cats,
        "transaction_count": db.query(func.count(Transaction.id)).scalar(),
        "last_sync": ls.isoformat() if ls else None,
    }


@app.get("/api/overview")
def overview(months: int = 12, db: Session = Depends(get_db)):
    return analytics.overview(db, months)


@app.get("/api/categories")
def categories(month: str | None = None, months: int = 12, db: Session = Depends(get_db)):
    return analytics.categories(db, month, months)


@app.get("/api/merchants")
def merchants(month: str | None = None, category: str | None = None, limit: int = 25,
              db: Session = Depends(get_db)):
    return analytics.merchants(db, month, category, limit)


@app.get("/api/transactions")
def transactions(month: str | None = None, category: str | None = None,
                 merchant: str | None = None, q: str | None = None,
                 limit: int = 100, offset: int = 0, db: Session = Depends(get_db)):
    return analytics.transactions(db, month, category, merchant, q, limit, offset)


@app.get("/api/subscriptions")
def subscriptions(db: Session = Depends(get_db)):
    return analytics.subscriptions(db)


@app.get("/api/insights/{month}")
def insight(month: str, refresh: bool = False, db: Session = Depends(get_db)):
    return insights.get_insight(db, month, refresh)


class CategoryUpdate(BaseModel):
    category: str
    apply_to_merchant: bool = False


@app.put("/api/transactions/{tx_id}/category")
def set_category(tx_id: str, body: CategoryUpdate, db: Session = Depends(get_db)):
    t = db.get(Transaction, tx_id)
    if not t:
        raise HTTPException(404, "transaction not found")
    t.category_override = body.category
    if body.apply_to_merchant and t.merchant_key:
        db.merge(MerchantRule(merchant_key=t.merchant_key, category=body.category,
                              source="manual"))
        for other in db.query(Transaction).all():
            if other.merchant_key == t.merchant_key and not other.category_override:
                other.category_refined = body.category
    db.commit()
    return {"ok": True}


@app.post("/api/refresh")
def refresh(db: Session = Depends(get_db)):
    try:
        return sync.sync(db)
    except Exception as e:
        raise HTTPException(502, f"sync failed: {e}")


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
