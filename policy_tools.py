"""Policy lookup over `politicas_da_loja.pdf`.

Strategy (deliberately lightweight, no vector DB):
  * Extract text per page with pypdf and split it into overlapping chunks.
  * If the whole manual is small, return it entirely (best accuracy, tiny cost).
  * Otherwise rank chunks with BM25 over accent-folded, lightly stemmed tokens,
    with a small PT synonym expansion (frete ~ entrega ~ envio, troca ~ devolução...).
"""
from __future__ import annotations

import math
from collections import Counter
from functools import lru_cache
from typing import Any

from src.config import POLICIES_PDF
from src.tools.text_utils import stem, tokenize

FULL_CONTEXT_CHAR_LIMIT = 6000
CHUNK_CHARS = 600
OVERLAP_LINES = 2

SYNONYMS = {
    "frete": ["entrega", "envio", "prazo", "transportadora", "correios"],
    "entrega": ["frete", "envio", "prazo"],
    "troca": ["devolucao", "arrependimento", "reembolso", "defeito", "garantia"],
    "devolucao": ["troca", "arrependimento", "reembolso", "estorno"],
    "reembolso": ["devolucao", "estorno"],
    "pagamento": ["parcelamento", "cartao", "pix", "boleto", "credito", "debito", "parcela"],
    "parcelar": ["parcelamento", "parcela", "cartao", "credito"],
    "horario": ["funcionamento", "atendimento", "aberto", "abre", "fecha", "sabado", "domingo"],
    "aberto": ["horario", "funcionamento", "atendimento"],
    "garantia": ["defeito", "assistencia", "troca"],
}


def _split_page(text: str) -> list[str]:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    chunks, buf = [], []
    for ln in lines:
        buf.append(ln)
        if sum(len(x) + 1 for x in buf) >= CHUNK_CHARS:
            chunks.append("\n".join(buf))
            buf = buf[-OVERLAP_LINES:]
    if buf and (not chunks or len(buf) > OVERLAP_LINES):
        chunks.append("\n".join(buf))
    return chunks


@lru_cache(maxsize=2)
def _load(path: str, mtime: float) -> list[dict[str, Any]]:
    from pypdf import PdfReader

    reader = PdfReader(path)
    chunks: list[dict[str, Any]] = []
    for page_no, page in enumerate(reader.pages, start=1):
        for piece in _split_page(page.extract_text() or ""):
            chunks.append({"page": page_no, "text": piece, "tokens": tokenize(piece)})
    return chunks


def _chunks() -> list[dict[str, Any]]:
    if not POLICIES_PDF.exists():
        raise FileNotFoundError(f"Policy PDF not found: {POLICIES_PDF}")
    chunks = _load(str(POLICIES_PDF), POLICIES_PDF.stat().st_mtime)
    if not chunks:
        raise ValueError("No text could be extracted from the PDF (scanned image? OCR needed).")
    return chunks


def _expand(query: str) -> list[str]:
    base = tokenize(query)
    extra = []
    for t in base:
        for key, syns in SYNONYMS.items():
            if t == stem(key):
                extra += [stem(s) for s in syns]
    return base + extra


def _bm25(q_tokens: list[str], docs: list[list[str]], k1: float = 1.5, b: float = 0.75) -> list[float]:
    n = len(docs)
    avgdl = (sum(len(d) for d in docs) / n) or 1.0
    df: Counter[str] = Counter()
    for d in docs:
        df.update(set(d))
    scores = []
    for d in docs:
        tf, dl, s = Counter(d), len(d), 0.0
        for q in set(q_tokens):
            if q in tf:
                idf = math.log(1 + (n - df[q] + 0.5) / (df[q] + 0.5))
                s += idf * tf[q] * (k1 + 1) / (tf[q] + k1 * (1 - b + b * dl / avgdl))
        scores.append(s)
    return scores


def search_policies(question: str, top_k: int = 3) -> dict[str, Any]:
    """Return the passages of the store policy manual most relevant to a question."""
    chunks = _chunks()
    total_chars = sum(len(c["text"]) for c in chunks)

    if total_chars <= FULL_CONTEXT_CHAR_LIMIT:
        return {
            "source": "politicas_da_loja.pdf",
            "mode": "full_document",
            "passages": [{"page": c["page"], "text": c["text"]} for c in chunks],
        }

    scores = _bm25(_expand(question), [c["tokens"] for c in chunks])
    ranked = sorted(zip(scores, chunks), key=lambda x: x[0], reverse=True)
    top = [(s, c) for s, c in ranked[: max(1, min(int(top_k), 6))] if s > 0]
    if not top:
        return {
            "source": "politicas_da_loja.pdf",
            "passages": [],
            "note": "Nothing relevant found in the policy manual. Do not guess; offer to connect the customer with the team.",
        }
    return {
        "source": "politicas_da_loja.pdf",
        "mode": "retrieval",
        "passages": [{"page": c["page"], "score": round(s, 2), "text": c["text"]} for s, c in top],
    }


POLICY_TOOLS = {"search_policies": search_policies}

POLICY_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_policies",
            "description": (
                "Search the store policy manual (PDF): exchange/return rules, shipping/freight, "
                "payment methods, opening hours and other store rules. Use BEFORE answering any "
                "policy question; answer only from the returned text."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "The policy question, in the customer's words."},
                    "top_k": {"type": "integer", "description": "Passages to return (default 3)."},
                },
                "required": ["question"],
            },
        },
    },
]
