"""Context budget allocation for chat RAG system.

Budget layout:
  ┌─────────────────────────────────────────────────────┐
  │              max_ctx (100%)                         │
  ├──────┬───────────────┬──────────────────┬───────────┤
  │ idx  │   pages       │  history + sys   │  resp     │
  │  5%  │    50%        │    ~30%          │   15%     │
  └──────┴───────────────┴──────────────────┴───────────┘
"""

DEFAULT_MAX_CTX = 204_800       # chars
RESPONSE_RESERVE_FRAC = 0.15
INDEX_BUDGET_FRAC = 0.05
PAGE_BUDGET_FRAC = 0.5
PER_PAGE_FRAC = 0.3
PER_PAGE_FLOOR = 5_000


def compute_budget(max_ctx: int | None = None) -> dict:
    """Compute character budgets from the LLM's max context window."""
    max_ctx = max_ctx if (max_ctx and max_ctx > 0) else DEFAULT_MAX_CTX

    response_reserve = int(max_ctx * RESPONSE_RESERVE_FRAC)
    index_budget = int(max_ctx * INDEX_BUDGET_FRAC)
    page_budget = int(max_ctx * PAGE_BUDGET_FRAC)

    # Per-page cap: scale with page_budget, floor at PER_PAGE_FLOOR
    max_page_size = min(
        page_budget,
        max(PER_PAGE_FLOOR, int(page_budget * PER_PAGE_FRAC)),
    )

    return {
        "max_ctx": max_ctx,
        "response_reserve": response_reserve,
        "index_budget": index_budget,
        "page_budget": page_budget,
        "max_page_size": max_page_size,
    }
