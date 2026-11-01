"""Central configuration for the Empório da Música agent."""
from __future__ import annotations

import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.getenv("EMPORIO_DATA_DIR", ROOT_DIR / "data"))

MODEL = os.getenv("EMPORIO_MODEL", "gemini-2.5-flash")
TEMPERATURE = 0.3
MAX_TOOL_ROUNDS = 5       # safety cap on tool-call loops per user turn
MAX_HISTORY_MESSAGES = 40  # conversation window kept in memory

PRODUCTS_CSV = DATA_DIR / "products.csv"
ORDERS_CSV = DATA_DIR / "orders.csv"
POLICIES_PDF = DATA_DIR / "politicas_da_loja.pdf"
