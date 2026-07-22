"""Seed the dev database from a local Emma xlsx export.

Usage: EMMA_XLSX=data/emma.xlsx .venv/bin/python scripts/seed_dev.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()
os.environ.setdefault("EMMA_XLSX", "data/emma.xlsx")

from app.db import SessionLocal, init_db
from app.sync import sync

init_db()
db = SessionLocal()
print(sync(db))
db.close()
