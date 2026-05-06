# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run the dashboard
streamlit run app.py --browser.gatherUsageStats false

# Run the monthly rebalancing report (dry-run if .env is absent — saves relatorio_preview.html)
python run_monthly.py
```

## Architecture

Two entrypoints over a shared data/utils layer:

- **`app.py`** — Streamlit dashboard with 7 tabs: Blueprint, Projeção de Renda, DRIP & Meta, Gap Analysis, Diversificação, Tributação, Rebalanceamento. All sidebar inputs (capital, meta mensal, aporte, anos de simulação, crescimento de dividendos, drift threshold) drive reactive recomputation via Streamlit session state.
- **`run_monthly.py`** — standalone script that loads positions, computes rebalancing, generates an HTML email via `utils/email_sender.py`, and sends via SMTP. Falls back to saving `relatorio_preview.html` when `.env` is absent.

**Data flow:**
1. `data/portfolio.py` — single source of truth: list of 18 asset dicts (12 ações + 6 FIIs). Asserts `sum(peso_alvo) == 1.0` on import. All fields are hardcoded (mai/2026); no API calls.
2. `config.py` — global constants (capital inicial, meta mensal, Selic, IPCA, JCP tax rate, DRIP years, rebalancing drift threshold).
3. `utils/calculators.py` — pure functions: `portfolio_weighted_dy`, `effective_dy` (applies 15% JCP tax), `gap_analysis`, `simulate_drip` (monthly DRIP loop), `years_to_reach_goal`, `compute_rebalancing` (drift-threshold logic), `income_sensitivity_table`.
4. `utils/formatters.py` — `brl()`, `pct()`, Pandas `.style.map()` color helpers (`color_risco`, `color_operacao`), `TRIB_LABEL` dict.

## Key constraints

- **Python 3.9** — use `Optional[X]` from `typing`, not `X | None`.
- **`posicoes.csv`** (optional, not committed) — two-column CSV (`ticker,valor`) loaded by `run_monthly.py` for real portfolio positions; falls back to ideal allocation if absent.
- **`.env`** (not committed) — SMTP credentials; see `.env.example`. Also accepts `PORTFOLIO_VALUE`, `META_MENSAL`, `APORTE_MENSAL` overrides.
- Alert boxes in `app.py` use `st.markdown(..., unsafe_allow_html=True)` with raw HTML instead of `st.error()` — avoids markdown parser breaking on `/` in "por mês" and `%` in yield strings.
