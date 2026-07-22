from datetime import date, datetime

from sqlalchemy import Date, DateTime, Numeric, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Transaction(Base):
    __tablename__ = "transactions"

    # Emma's stable transaction hash
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    amount: Mapped[float] = mapped_column(Numeric(12, 2))
    account: Mapped[str] = mapped_column(String(128), default="")
    bank: Mapped[str] = mapped_column(String(128), default="")
    currency: Mapped[str] = mapped_column(String(8), default="GBP")
    category_emma: Mapped[str] = mapped_column(String(64), default="", index=True)
    subcategory: Mapped[str] = mapped_column(String(64), default="")
    type: Mapped[str] = mapped_column(String(32), default="")
    tags: Mapped[str] = mapped_column(String(256), default="")
    counterparty: Mapped[str] = mapped_column(String(256), default="")
    custom_name: Mapped[str] = mapped_column(String(256), default="")
    merchant: Mapped[str] = mapped_column(String(256), default="")
    details: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    linked_id: Mapped[str] = mapped_column(String(64), default="")
    # refinement layers; effective = override > refined > emma
    category_refined: Mapped[str] = mapped_column(String(64), default="")
    category_override: Mapped[str] = mapped_column(String(64), default="")
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    @property
    def merchant_key(self) -> str:
        return (self.custom_name or self.merchant or self.counterparty or "").strip().lower()

    @property
    def category(self) -> str:
        return self.category_override or self.category_refined or self.category_emma


class MerchantRule(Base):
    __tablename__ = "merchant_rules"

    merchant_key: Mapped[str] = mapped_column(String(256), primary_key=True)
    category: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(16), default="manual")  # manual | llm
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Insight(Base):
    __tablename__ = "insights"

    month: Mapped[str] = mapped_column(String(7), primary_key=True)  # YYYY-MM
    content: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SyncState(Base):
    __tablename__ = "sync_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
