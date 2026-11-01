"""Pandas-backed tools: product catalog, stock and order status.

The CSV schemas are not hard-coded. Column names are resolved through
COLUMN_ALIASES, so `products.csv` / `orders.csv` with slightly different
headers (PT or EN) keep working. Adjust the aliases if your files differ.

Scope enforcement is *defence in depth*: the system prompt tells the model the
store sells instruments only, AND `search_products` detects accessory terms
(cables, strings, picks, cases, pedals, amps...) and flags / short-circuits them.
"""
from __future__ import annotations

import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd
from src.config import ORDERS_CSV, PRODUCTS_CSV
from src.tools.text_utils import normalize, tokenize

COLUMN_ALIASES: dict[str, list[str]] = {
    "id": ["product_id", "id", "sku", "codigo", "code", "id_produto"],
    "name": ["name", "product_name", "nome", "produto", "title"],
    "category": ["category", "categoria", "type", "tipo"],
    "price": ["price", "preco", "valor", "unit_price"],
    "stock": ["stock", "estoque", "quantity", "quantidade", "qty", "inventory"],
    "order_id": ["order_id", "id_pedido", "pedido", "order_number", "numero_pedido", "id"],
    "order_product_id": ["product_id", "sku", "id_produto", "produto_id"],
}

# Columns never sent to the LLM (PII minimisation).
SENSITIVE_HINTS = ("email", "phone", "telefone", "celular", "cpf", "cnpj",
                   "address", "endereco", "cep", "zip", "document")

# Stemmed tokens that indicate ACCESSORIES (not sold by the store).
ACCESSORY_TERMS = {
    "cabo", "cable", "corda", "string", "palheta", "pick", "case", "capa", "bag",
    "pedal", "amplificador", "ampli", "amp", "cubo", "afinador", "metronomo",
    "suporte", "estante", "baqueta", "correia", "capotraste", "encordoamento",
}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=8)
def _read_csv_cached(path: str, mtime: float) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _read_csv(path: Path) -> pd.DataFrame:
    """Read a CSV, re-reading automatically when the file changes on disk."""
    if not path.exists():
        raise FileNotFoundError(f"Data file not found: {path}")
    df = _read_csv_cached(str(path), path.stat().st_mtime).copy()
    df.columns = [c.strip() for c in df.columns]
    return df


def _col(df: pd.DataFrame, key: str) -> str | None:
    lowered = {c.lower(): c for c in df.columns}
    for alias in COLUMN_ALIASES[key]:
        if alias in lowered:
            return lowered[alias]
    return None


def _to_float(value: object) -> float:
    s = re.sub(r"[^\d,.\-]", "", str(value))
    if not s:
        return math.nan
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return math.nan


def _catalog() -> pd.DataFrame:
    df = _read_csv(PRODUCTS_CSV)
    df["_hay"] = df.astype(str).agg(" ".join, axis=1).map(normalize)
    price_c, stock_c = _col(df, "price"), _col(df, "stock")
    df["_price"] = df[price_c].map(_to_float) if price_c else math.nan
    df["_stock"] = df[stock_c].map(_to_float) if stock_c else math.nan
    return df


def _public_rows(df: pd.DataFrame) -> list[dict[str, Any]]:
    cols = [c for c in df.columns if not c.startswith("_")]
    return df[cols].to_dict(orient="records")


def _alnum(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", normalize(value))


def _digits(value: object) -> str:
    return re.sub(r"\D", "", str(value)).lstrip("0")


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #
def list_categories() -> dict[str, Any]:
    """Instrument categories the store carries, with number of items in stock."""
    df = _catalog()
    cat = _col(df, "category")
    if not cat:
        return {"categories": [], "note": "The catalog has no category column."}
    out = []
    for name, grp in df.groupby(cat):
        in_stock = int((grp["_stock"] > 0).sum()) if grp["_stock"].notna().any() else None
        out.append({"category": name, "products": len(grp), "products_in_stock": in_stock})
    return {"categories": out}


def search_products(
    query: str = "",
    category: str = "",
    min_price: float | None = None,
    max_price: float | None = None,
    in_stock_only: bool = False,
    limit: int = 8,
) -> dict[str, Any]:
    """Search the instrument catalog by free text, category, price range and stock."""
    q_tokens, c_tokens = tokenize(query), tokenize(category)
    accessory_hits = sorted({t for t in q_tokens + c_tokens if t in ACCESSORY_TERMS})
    core = [t for t in q_tokens if t not in ACCESSORY_TERMS]
    core_cat = [t for t in c_tokens if t not in ACCESSORY_TERMS]

    if accessory_hits and not core and not core_cat:
        return {
            "out_of_scope": True,
            "message": (
                "The store sells musical INSTRUMENTS only. It does NOT sell accessories "
                f"(detected: {', '.join(accessory_hits)}). Politely decline and suggest instruments."
            ),
            "results": [],
        }

    df = _catalog()
    notes: list[str] = []
    if accessory_hits:
        notes.append(
            f"Query mentioned accessory terms ({', '.join(accessory_hits)}), which the store "
            "does not sell. Only instruments are returned; if the customer wants the accessory "
            "itself, decline politely."
        )

    cat_c = _col(df, "category")
    if core_cat:
        hay = df[cat_c].map(normalize) if cat_c else df["_hay"]
        df = df[hay.map(lambda h: any(t in h for t in core_cat))]

    if min_price is not None:
        df = df[df["_price"] >= float(min_price)]
    if max_price is not None:
        df = df[df["_price"] <= float(max_price)]
    if in_stock_only:
        df = df[df["_stock"] > 0]

    partial = False
    if core and len(df):
        scores = df["_hay"].map(lambda h: sum(t in h for t in core))
        full = scores == len(core)
        if full.any():
            df, scores = df[full], scores[full]
        else:
            partial = True
            df, scores = df[scores > 0], scores[scores > 0]
        df = df.assign(_score=scores).sort_values(["_score", "_price"], ascending=[False, True])
    else:
        df = df.sort_values("_price")

    if partial:
        notes.append("No exact match; showing partial matches. Say so to the customer.")

    total = len(df)
    shown = df.head(max(1, min(int(limit), 15)))
    return {
        "total_matches": total,
        "returned": len(shown),
        "results": _public_rows(shown),
        "notes": notes,
    }


def get_product_details(product: str) -> dict[str, Any]:
    """Full details (price, stock...) for one product, by id/SKU or by name."""
    df = _catalog()
    id_c = _col(df, "id")
    key = _alnum(product)
    if id_c:
        exact = df[df[id_c].map(_alnum) == key]
        if len(exact):
            return {"results": _public_rows(exact.head(3))}
    tokens = [t for t in tokenize(product) if t not in ACCESSORY_TERMS]
    if tokens:
        hit = df[df["_hay"].map(lambda h: all(t in h for t in tokens))]
        if len(hit):
            return {"results": _public_rows(hit.head(3))}
    return {"results": [], "note": f"No product found for '{product}'."}


def get_order_status(order_id: str) -> dict[str, Any]:
    """Look up an order by its number and return its status (PII removed)."""
    df = _read_csv(ORDERS_CSV)
    id_c = _col(df, "order_id")
    if not id_c:
        return {"error": "orders.csv has no recognizable order id column."}

    key, dig = _alnum(order_id), _digits(order_id)
    match = df[df[id_c].map(_alnum) == key]
    if match.empty and dig:
        match = df[df[id_c].map(_digits) == dig]
    if match.empty:
        return {"found": False, "note": f"No order found for '{order_id}'. Ask the customer to double-check the number."}

    safe_cols = [c for c in df.columns if not any(h in normalize(c) for h in SENSITIVE_HINTS)]
    rows = match[safe_cols].head(5).copy()

    # Optional enrichment: attach the product name when both files share a product id.
    enrichment_note = None
    try:
        pid_c, cat = _col(rows, "order_product_id"), _read_csv(PRODUCTS_CSV)
        cat_id, cat_name = _col(cat, "id"), _col(cat, "name")
        if pid_c and cat_id and cat_name and pid_c != id_c:
            names = dict(zip(cat[cat_id].map(_alnum), cat[cat_name]))
            rows["product_name"] = rows[pid_c].map(lambda v: names.get(_alnum(v), ""))
    except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError, ValueError) as exc:
        enrichment_note = (
            "Order status is available, but product-name enrichment failed "
            f"({type(exc).__name__}: {exc})."
        )

    result = {"found": True, "orders": rows.to_dict(orient="records")}
    if enrichment_note:
        result["enrichment_note"] = enrichment_note
    return result


# --------------------------------------------------------------------------- #
# Registry + tool schemas
# --------------------------------------------------------------------------- #
STORE_TOOLS = {
    "list_categories": list_categories,
    "search_products": search_products,
    "get_product_details": get_product_details,
    "get_order_status": get_order_status,
}

STORE_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_categories",
            "description": "List the instrument categories the store carries. Use for broad questions like 'what do you sell?'.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": (
                "Search the instrument catalog (prices, stock). Use for any question about "
                "available instruments, recommendations, prices or budgets. Pass keywords in "
                "'query' (e.g. 'violão aço', 'teclado 61 teclas')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Free-text keywords (brand, type, model)."},
                    "category": {"type": "string", "description": "Optional category filter, e.g. 'violão'."},
                    "min_price": {"type": "number", "description": "Minimum price in BRL."},
                    "max_price": {"type": "number", "description": "Maximum price in BRL."},
                    "in_stock_only": {"type": "boolean", "description": "Only items currently in stock."},
                    "limit": {"type": "integer", "description": "Max results (default 8, max 15)."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_product_details",
            "description": "Get exact price/stock/details of ONE product by id/SKU or by name.",
            "parameters": {
                "type": "object",
                "properties": {"product": {"type": "string", "description": "Product id/SKU or name."}},
                "required": ["product"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_order_status",
            "description": "Look up the status of an order by order number. Ask the customer for the number if missing.",
            "parameters": {
                "type": "object",
                "properties": {"order_id": {"type": "string", "description": "Order number, e.g. '1001' or 'PED-1001'."}},
                "required": ["order_id"],
            },
        },
    },
]
