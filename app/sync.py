"""Pull the sheet into Postgres/SQLite and categorize new merchants.

The app "hot reloads": any API request older than REFRESH_TTL seconds since
the last sync triggers a background re-pull, so the dashboard tracks the
sheet within a few minutes without a cron job.
"""

import logging
import os
import threading
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app import sheet
from app.categorize import categorize_new
from app.db import SessionLocal
from app.models import SyncState, Transaction

log = logging.getLogger("moneylytics.sync")

REFRESH_TTL = int(os.environ.get("REFRESH_TTL", "300"))

_lock = threading.Lock()
_last_attempt: datetime | None = None


def sync(db: Session) -> dict:
    rows = sheet.fetch_rows()
    existing = {t.id: t for t in db.query(Transaction).all()}
    created = updated = 0
    for r in rows:
        t = existing.get(r["id"])
        if t is None:
            db.add(Transaction(**r))
            created += 1
        else:
            changed = False
            for k, v in r.items():
                if k == "id":
                    continue
                # Emma overwrites its tables frequently; its fields win,
                # but our refinement/override columns are never touched.
                if getattr(t, k) != v:
                    setattr(t, k, v)
                    changed = True
            if changed:
                t.synced_at = datetime.utcnow()
                updated += 1
    db.commit()

    cat_stats = categorize_new(db)

    state = db.get(SyncState, "last_sync") or SyncState(key="last_sync")
    state.value = datetime.now(timezone.utc).isoformat()
    db.merge(state)
    db.commit()
    return {"fetched": len(rows), "created": created, "updated": updated, **cat_stats}


def last_sync(db: Session) -> datetime | None:
    state = db.get(SyncState, "last_sync")
    if state and state.value:
        return datetime.fromisoformat(state.value)
    return None


def _run_background_sync():
    db = SessionLocal()
    try:
        result = sync(db)
        log.info("background sync: %s", result)
    except sheet.SheetNotConfigured:
        pass
    except Exception:
        log.exception("background sync failed")
    finally:
        db.close()
        _lock.release()


def refresh_if_stale(db: Session):
    """Kick off a background sync if data is older than REFRESH_TTL."""
    global _last_attempt
    ls = last_sync(db)
    now = datetime.now(timezone.utc)
    if ls and (now - ls).total_seconds() < REFRESH_TTL:
        return
    if _last_attempt and (now - _last_attempt).total_seconds() < 60:
        return  # don't hammer a failing source
    if not _lock.acquire(blocking=False):
        return  # sync already running
    _last_attempt = now
    threading.Thread(target=_run_background_sync, daemon=True).start()
