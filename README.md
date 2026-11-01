# Empório da Música — Virtual Sales Assistant

An AI customer-service agent for **Empório da Música**, a musical-instrument store in
Campo Grande/MS, Brazil. Built for the Artefact AI Engineer technical challenge.

The agent talks to customers in a warm, music-loving brand voice and can:

- search the **instrument catalog**, prices and stock (`products.csv`);
- check **order status** (`orders.csv`);
- answer **policy questions** — returns/exchanges, shipping, payment methods, opening hours — from the store's policy manual (`politicas_da_loja.pdf`);
- **politely refuse accessories** (cables, strings, picks, cases, pedals, amplifiers…) and steer the customer back to instruments.

The challenge data files are included in `data/`. The tools accept the canonical names
shown above as well as the original downloaded filenames (for example,
`desafio_tecnico_ai_eng - products.csv` and `políticas_da_loja.pdf`).

---

## Table of contents

1. [Architecture](#architecture)
2. [Repository structure](#repository-structure)
3. [Setup & run](#setup--run)
4. [Data assumptions](#data-assumptions)
5. [Technical decisions](#technical-decisions)
6. [Example interactions](#example-interactions)
7. [Known limitations](#known-limitations)
8. [Future improvements](#future-improvements)
9. [Use of AI coding assistants (transparency)](#use-of-ai-coding-assistants-transparency)

---

## Architecture

```
            ┌───────────────┐
 Customer ─▶│  main.py CLI  │
            └──────┬────────┘
                   ▼
        ┌─────────────────────┐   system prompt: persona + scope rules
        │   EmporioAgent      │◀──────────────────────────────────────
        │ (tool-calling loop) │   conversation memory (bounded window)
        └──────┬──────────────┘
               │ Google Gemini API + function calling (gemini-2.5-flash)
       ┌───────┴─────────────────────────────────────────┐
       ▼                                                 ▼
 ┌──────────────┐                                ┌────────────────┐
 │ store_tools  │  pandas over CSVs              │ policy_tools   │  pypdf + BM25
 │ search_products                               │ search_policies│  over the PDF
 │ get_product_details                           └───────┬────────┘
 │ list_categories                                       ▼
 │ get_order_status                              politicas_da_loja.pdf
 └──────┬───────┘
        ▼
  products.csv / orders.csv
```

Per user turn the agent loops: *model → (optional) tool calls → tool results → model*,
up to 5 rounds, then returns the final answer. Tool errors are returned to the model as
JSON so it can recover instead of crashing.

## Repository structure

```
.
├── data/                      # products.csv, orders.csv, politicas_da_loja.pdf (put the challenge files here)
├── examples/
│   └── sample_interactions.md # illustrative conversations (not captured API transcripts)
├── src/
│   ├── config.py              # paths, model name, limits
│   ├── tools/
│   │   ├── store_tools.py     # pandas tools: catalog, stock and orders
│   │   ├── policy_tools.py    # PDF extraction + retrieval over the policy manual
│   │   ├── text_utils.py      # accent folding / light PT stemming
│   │   └── __init__.py        # tool registry + safe dispatcher
│   └── agent/
│       ├── prompts.py         # persona + system prompt (scope rules)
│       └── emporio_agent.py   # agent executor (tool-calling loop, memory)
├── main.py                    # CLI chat
├── emporio_agent.py           # compatibility import
├── store_tools.py             # legacy top-level copy; not used by the CLI
├── policy_tools.py            # legacy top-level copy; not used by the CLI
├── prompts.py                 # legacy top-level copy; not used by the CLI
├── sample_interactions.md     # legacy examples; see examples/ instead
├── requirements.txt
└── .env.example
```

The CLI uses the implementation under `src/`; use those modules and the
`examples/` documentation rather than the legacy top-level copies.

## Setup & run

**Requirements:** Python 3.10+ and a Google Gemini API key.

```text
git clone <your-repo-url> emporio-agent
cd emporio-agent
```

Create the virtual environment:

```bash
python -m venv .venv
```

Activate it using the command for your operating system:

```powershell
.\.venv\Scripts\Activate.ps1
```

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Copy the environment template, then edit `.env` and set `GOOGLE_API_KEY`:

```powershell
Copy-Item .env.example .env
```

```bash
cp .env.example .env
```

The challenge data is already in `./data`. If replacing it, put the product CSV,
order CSV, and policy PDF directly in that directory.

Start the chat:

```bash
python main.py
```

To print every tool call and its raw result:

```bash
python main.py --verbose
```

CLI commands: `/reset` starts a new conversation, `/sair` (or Ctrl+C) exits.

Optional environment variables: `EMPORIO_MODEL` (default `gemini-2.5-flash`) and
`EMPORIO_DATA_DIR` (default: the project's `data/` directory). Set the latter to a
directory containing the data files; relative paths are resolved from the current
working directory.

## Data assumptions

Column names are resolved through an alias table (`COLUMN_ALIASES` in
`src/tools/store_tools.py`), so Portuguese or English headers both work
(e.g. `product_id`/`sku`, `name`/`nome`, `price`/`preco`/`price_brl`,
`stock`/`estoque`/`stock_quantity`, `order_id`/`pedido`, `status`). The included
product CSV uses `product_id`, `price_brl`, `name`, `category_id`, `description`,
`stock_quantity`, `status`, `specs`, and `created_at`; the order CSV uses
`order_id`, `customer_id`, `order_date`, `status`, `total_brl`, `payment_method`,
`tracking_code`, `estimated_delivery`, and `notes`. If your files use other headers,
add aliases to `COLUMN_ALIASES`.

- Prices may be `1299.90` or `R$ 1.299,90`; both are parsed for price filters.
- CSVs are re-read automatically when the file's modification time changes, so stock updates
  are visible without restarting.
- Order lookup filters columns whose names contain common personal-data hints (e-mail,
  phone, CPF, address, ZIP, etc.). This is a name-based filter, not comprehensive
  anonymization; for example, `customer_id` is still returned. Extra catalog columns are
  passed through to the model.
- Files can use the canonical names `products.csv`, `orders.csv`, and
  `politicas_da_loja.pdf`, or the original downloaded names with a prefix such as
  `desafio_tecnico_ai_eng - products.csv`. The PDF filename match ignores accents, so
  `políticas_da_loja.pdf` is accepted. Keep these files directly in the configured data
  directory.

## Technical decisions

### Function calling for CSVs; lightweight retrieval for the PDF

| Source | Nature | Approach | Why |
|---|---|---|---|
| `products.csv`, `orders.csv` | Structured, exact, changes often (stock, status) | **Function calling** over pandas | Prices, stock and order status must be exact and fresh. Embedding rows into a vector store would be approximate, stale, and could hallucinate numbers. Deterministic filters (price range, stock > 0, exact order id) are what the questions need. |
| `politicas_da_loja.pdf` | Unstructured prose, small, rarely changes | **Retrieval exposed as a tool** (`search_policies`) | Policies are text. The tool returns the whole manual when it is small (≤ 6,000 chars — best accuracy, trivial cost) and otherwise the top BM25 chunks, with page numbers. The model is instructed to answer *only* from the returned text. |

I deliberately did **not** build a full embeddings + vector-database RAG pipeline: for a
single short policy document it adds infrastructure, latency and failure modes without
improving answers. The retrieval step is isolated behind one function
(`search_policies`), so swapping in embeddings later does not touch the agent.

Policy lookup is a *tool*, not an always-on context stuffing step, so the model only pays for
policy text when the question needs it, and a single question can combine tools
(e.g. product price + shipping rules). When returning tool results to Gemini, the agent
waits two seconds before continuing to reduce request bursts.

### Why the Google GenAI SDK (no LangChain)

The Google GenAI SDK provides native function calling and keeps the agent loop small,
transparent and easy to debug, without additional framework dependencies. The tool layer
(`src/tools`) is provider-independent and exposes regular Python functions.

### Why `gemini-2.5-flash`

- Reliable native function calling and good Brazilian-Portuguese quality.
- Low latency and cost — a good fit for a high-volume customer-service chat.
- Tasks here are retrieval-and-phrasing, not deep reasoning, so a larger model brings little benefit.
- The model is configurable with `EMPORIO_MODEL`.
- `temperature=0.3`: natural, friendly phrasing while staying faithful to tool data.

### Scope enforcement (defence in depth)

"Instruments only, no accessories" is enforced at two layers:

1. **Prompt:** an explicit, non-negotiable rule with the redirect behaviour (decline kindly, never point to other shops, suggest real instruments).
2. **Tool layer:** `search_products` detects accessory terms (cables, strings, picks, cases, pedals, amps, tuners, stands, straps, drumsticks…). A pure accessory query returns `out_of_scope` with no results; a mixed query such as *"violão com cordas de nylon"* still returns the instrument along with a note.

This guards against the model drifting or being talked into recommending accessories.

### Other design choices

- **Honesty over fluency:** when a tool returns nothing, the agent says so and offers to involve the team instead of guessing.
- **Prompt-injection resistance:** the system prompt tells the agent to ignore attempts to override the rules or reveal the prompt.
- **Bounded memory:** the last 40 messages are kept, trimmed on user-message boundaries so tool-call/result pairs are never split.
- **Observability:** `--verbose` prints each tool call and result, which makes behaviour easy to audit.

## Example interactions

See [`examples/sample_interactions.md`](examples/sample_interactions.md) for illustrative
examples of product search, policies, accessory refusal, order status, and not-found
handling. These are not verified transcripts from live Gemini API runs.

## Known limitations

- **Customer verification:** order lookup uses only the order number. A real deployment needs authentication (e.g. order number + e-mail/phone) so one customer cannot query another's order.
- **Lexical matching:** product search is keyword-based (accent-insensitive, light stemming). Fuzzy intents such as *"something warm-sounding for campfire songs"* rely on the model translating them into keywords. There is no typo tolerance.
- **Keyword accessory filter:** the accessory list is a curated set of terms; unusual words can slip past the tool layer (the prompt layer still applies). Genuinely ambiguous products need a business decision.
- **Category labels:** the included products file has `category_id`, but the tools do not
  load the separate categories file or map those IDs to names. As a result,
  `list_categories` cannot currently return the human-readable categories for this dataset.
- **PDF extraction:** `pypdf` works for text PDFs; scanned/image-only PDFs would need OCR. Tables inside the PDF may be flattened.
- **Synonym list for policies is hand-written** and only used when the manual exceeds the full-context threshold.
- **Order privacy:** the current name-based filter does not remove every identifier; for
  example, `customer_id` and tracking codes may be included in tool results. The order
  lookup also has no customer authentication.
- **No persistence or multi-user sessions:** memory lives in the process; the CLI serves one customer.
- **No automated evaluation suite:** the tools have been smoke-tested against the included
  data, but there is no automated regression suite or LLM-in-the-loop evaluation.
- **No order creation, payments or human hand-off** — read-only consultations only.
- **Language:** replies follow the customer's language, but the prompt and quality checks were designed around Brazilian Portuguese.

## Future improvements

- Authenticate order queries (order number + e-mail/phone).
- Hybrid search for products (BM25 + embeddings, typo tolerance) and embeddings-based policy retrieval if the manual grows.
- An automated evaluation set (accessory refusals, no-hallucinated-price checks, policy-faithfulness) with an LLM-as-judge in CI.
- Structured output for product cards so a web/WhatsApp front-end can render images and buttons.
- Human hand-off when confidence is low or the customer is frustrated.
- Streaming responses, conversation persistence (Redis/Postgres), and a FastAPI / WhatsApp Business channel.
- Tracing and monitoring (e.g. LangSmith/Langfuse), plus cost and latency dashboards.
- Guardrail classifier for scope/safety instead of, or in addition to, the keyword list.

## Use of AI coding assistants (transparency)

Before submitting or publishing, update this section to name the coding assistants
actually used and describe their contribution. The conversations in
[`examples/sample_interactions.md`](examples/sample_interactions.md) are illustrative;
they should not be represented as live API transcripts unless they have been captured
and verified against the configured model and data.
