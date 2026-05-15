"""DCF (Discounted Cash Flow) analysis for Brazilian equities."""
from typing import Optional, Dict, List
import pandas as pd
import numpy as np
import streamlit as st

# Brazil constants
BR_CORP_TAX   = 0.34    # IRPJ + CSLL
BR_ERP        = 0.08    # Equity risk premium Brazil (global 5.5% + country risk 2.5%)


# ── yfinance data fetch ───────────────────────────────────────────────────────

@st.cache_data(ttl=86400, show_spinner=False)
def get_financials(ticker: str) -> Dict:
    import yfinance as yf
    try:
        t = yf.Ticker(f"{ticker}.SA")
        return {
            "info":     t.info or {},
            "income":   t.financials,
            "balance":  t.balance_sheet,
            "cashflow": t.cashflow,
        }
    except Exception as e:
        return {"_error": str(e)}


# ── helpers ───────────────────────────────────────────────────────────────────

def _get(df: Optional[pd.DataFrame], key: str, default: float = 0.0) -> float:
    if df is None or df.empty or key not in df.index:
        return default
    for v in df.loc[key]:
        if pd.notna(v) and v != 0:
            return float(v)
    return default


def _hist(df: Optional[pd.DataFrame], key: str) -> List[float]:
    if df is None or df.empty or key not in df.index:
        return []
    return [float(v) for v in df.loc[key] if pd.notna(v) and v != 0]


def _parse_pct(text: str) -> Optional[float]:
    if not text or text in ("—", "-"):
        return None
    try:
        return float(text.strip().replace("%", "").replace(",", ".")) / 100
    except ValueError:
        return None


def _M(v: float) -> str:
    """Format large number as R$ millions/billions."""
    abs_v = abs(v)
    sign = "-" if v < 0 else ""
    if abs_v >= 1e9:
        return f"{sign}R$ {abs_v/1e9:.1f}B"
    if abs_v >= 1e6:
        return f"{sign}R$ {abs_v/1e6:.0f}M"
    return f"{sign}R$ {abs_v:.0f}"


def _brl(v: float) -> str:
    s = f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}" if v >= 0 else f"-R$ {s}"


# ── core DCF computation ──────────────────────────────────────────────────────

def compute_dcf(
    ticker: str,
    asset: dict,
    financials: Dict,
    fund_data: Dict,
    rf: float,
    growth_y1_y3: float = 0.08,
    growth_y4_y5: float = 0.05,
    terminal_growth: float = 0.03,
    exit_multiple: float = 12.0,
    wacc_override: Optional[float] = None,
) -> Dict:
    if "_error" in financials:
        return {"_error": financials["_error"]}

    info     = financials.get("info", {})
    income   = financials.get("income")
    balance  = financials.get("balance")
    cashflow = financials.get("cashflow")

    # ── Revenue ───────────────────────────────────────────────────────────────
    rev_hist = _hist(income, "Total Revenue")
    if not rev_hist:
        rev_hist = _hist(income, "Operating Revenue")
    if not rev_hist:
        return {"_error": "Dados de receita não disponíveis no yfinance para este ativo."}

    revenue_base = rev_hist[0]
    years_avail  = len(rev_hist)
    if years_avail >= 2:
        hist_cagr = (rev_hist[0] / rev_hist[-1]) ** (1 / (years_avail - 1)) - 1
    else:
        hist_cagr = growth_y1_y3

    # ── EBIT margin ───────────────────────────────────────────────────────────
    ebit_hist = _hist(income, "EBIT")
    if not ebit_hist:
        ebit_hist = _hist(income, "Operating Income")
    if ebit_hist:
        margins    = [e / r for e, r in zip(ebit_hist, rev_hist) if r > 0]
        ebit_margin = float(np.mean(margins[:min(3, len(margins))]))
    else:
        ebit_margin = _parse_pct(fund_data.get("Margem EBIT", "")) or 0.20
    ebit_margin = max(0.01, min(ebit_margin, 0.95))

    # ── D&A and CapEx ─────────────────────────────────────────────────────────
    da    = _get(income, "Reconciled Depreciation")
    if da == 0:
        da = _get(cashflow, "Depreciation And Amortization")
    capex = abs(_get(cashflow, "Capital Expenditure"))
    if capex == 0:
        capex = abs(_get(cashflow, "Capital Expenditures"))

    da_pct    = da / revenue_base    if (revenue_base and da)    else 0.04
    capex_pct = capex / revenue_base if (revenue_base and capex) else 0.06

    # ── Net debt ──────────────────────────────────────────────────────────────
    net_debt = _get(balance, "Net Debt")
    if net_debt == 0:
        total_debt = _get(balance, "Total Debt") or _get(balance, "Long Term Debt")
        cash       = _get(balance, "Cash And Cash Equivalents")
        if cash == 0:
            cash = _get(balance, "Cash Cash Equivalents And Short Term Investments")
        net_debt = total_debt - cash

    # ── Shares outstanding ────────────────────────────────────────────────────
    shares = float(info.get("sharesOutstanding", 0) or
                   _get(income, "Diluted Average Shares") or
                   _get(income, "Basic Average Shares"))
    if shares == 0:
        market_cap = float(info.get("marketCap", 0) or 1)
        shares = market_cap / asset["preco"] if asset["preco"] > 0 else 1

    # ── WACC ──────────────────────────────────────────────────────────────────
    beta = float(info.get("beta") or 1.0)
    beta = max(0.3, min(beta, 3.0))
    ke   = rf + beta * BR_ERP

    total_debt_val = _get(balance, "Total Debt") or _get(balance, "Long Term Debt")
    interest_exp   = abs(_get(income, "Interest Expense Non Operating") or
                         _get(income, "Interest Expense"))
    kd = (interest_exp / total_debt_val) if (total_debt_val > 0 and interest_exp > 0) else (rf + 0.025)
    kd = max(0.05, min(kd, 0.30))

    market_cap = float(info.get("marketCap") or shares * asset["preco"])
    total_cap  = market_cap + max(total_debt_val, 0)
    we = market_cap / total_cap if total_cap > 0 else 0.7
    wd = max(total_debt_val, 0) / total_cap if total_cap > 0 else 0.3

    wacc = wacc_override if wacc_override else (ke * we + kd * (1 - BR_CORP_TAX) * wd)
    wacc = max(0.07, min(wacc, 0.40))

    # ── 5-year FCF projections ────────────────────────────────────────────────
    projections = []
    revenue = revenue_base
    for y in range(1, 6):
        g       = growth_y1_y3 if y <= 3 else growth_y4_y5
        revenue = revenue * (1 + g)
        ebit    = revenue * ebit_margin
        nopat   = ebit * (1 - BR_CORP_TAX)
        da_val  = revenue * da_pct
        cap_val = revenue * capex_pct
        fcf     = nopat + da_val - cap_val
        projections.append({
            "Ano": f"Y+{y}",
            "Receita": revenue,
            "Cresc": g,
            "EBIT": ebit,
            "Margem EBIT": ebit_margin,
            "NOPAT": nopat,
            "D&A": da_val,
            "CapEx": cap_val,
            "FCF": fcf,
        })

    # ── Terminal value ────────────────────────────────────────────────────────
    fcf_last    = projections[-1]["FCF"]
    ebitda_last = projections[-1]["EBIT"] + projections[-1]["D&A"]

    if wacc > terminal_growth:
        tv_perp = fcf_last * (1 + terminal_growth) / (wacc - terminal_growth)
    else:
        tv_perp = fcf_last * 25

    tv_exit = ebitda_last * exit_multiple

    disc5     = (1 + wacc) ** 5
    pv_fcfs   = sum(p["FCF"] / (1 + wacc) ** i for i, p in enumerate(projections, 1))
    pv_tv_perp = tv_perp / disc5
    pv_tv_exit = tv_exit / disc5

    ev_perp = pv_fcfs + pv_tv_perp
    ev_exit = pv_fcfs + pv_tv_exit
    eq_perp = ev_perp - net_debt
    eq_exit = ev_exit - net_debt

    price_perp = eq_perp / shares if shares > 0 else 0
    price_exit = eq_exit / shares if shares > 0 else 0
    fair_value  = (price_perp + price_exit) / 2

    cur = asset["preco"]
    up_perp = (price_perp / cur - 1) if cur > 0 else 0
    up_exit = (price_exit / cur - 1) if cur > 0 else 0
    up_avg  = (fair_value / cur - 1)  if cur > 0 else 0

    if up_avg > 0.15:
        verdict, vcls, vemoji = "SUBAVALIADA",    "bb-pos", "▲"
    elif up_avg < -0.15:
        verdict, vcls, vemoji = "SOBREAVALIADA",  "bb-neg", "▼"
    else:
        verdict, vcls, vemoji = "BEM PRECIFICADA","bb-value","="

    # ── Sensitivity: WACC × terminal growth (perpetuity) ─────────────────────
    wacc_range = [wacc + d for d in (-0.02, -0.01, 0, 0.01, 0.02)]
    g_range    = [0.01, 0.02, terminal_growth, 0.04, 0.05]

    sens = []
    for w in wacc_range:
        row = []
        for g in g_range:
            if w > g:
                tv  = fcf_last * (1 + g) / (w - g)
                pv  = sum(p["FCF"] / (1 + w) ** i for i, p in enumerate(projections, 1))
                eq  = (pv + tv / (1 + w) ** 5) - net_debt
                row.append(eq / shares if shares > 0 else None)
            else:
                row.append(None)
        sens.append(row)

    # ── Key risks ─────────────────────────────────────────────────────────────
    risks = _risks(asset, growth_y1_y3, wacc, ebit_margin, hist_cagr)

    return {
        "ticker": ticker, "cur": cur,
        "revenue_base": revenue_base, "hist_cagr": hist_cagr,
        "ebit_margin": ebit_margin, "da_pct": da_pct, "capex_pct": capex_pct,
        "beta": beta, "ke": ke, "kd": kd, "we": we, "wd": wd, "wacc": wacc,
        "net_debt": net_debt, "shares": shares,
        "projections": projections,
        "tv_perp": tv_perp, "tv_exit": tv_exit,
        "pv_fcfs": pv_fcfs, "pv_tv_perp": pv_tv_perp, "pv_tv_exit": pv_tv_exit,
        "ev_perp": ev_perp, "ev_exit": ev_exit,
        "price_perp": price_perp, "price_exit": price_exit, "fair_value": fair_value,
        "up_perp": up_perp, "up_exit": up_exit, "up_avg": up_avg,
        "verdict": verdict, "vcls": vcls, "vemoji": vemoji,
        "wacc_range": wacc_range, "g_range": g_range, "sens": sens,
        "growth_y1_y3": growth_y1_y3, "growth_y4_y5": growth_y4_y5,
        "terminal_growth": terminal_growth, "exit_multiple": exit_multiple,
        "risks": risks,
    }


def _risks(asset, growth, wacc, margin, hist_cagr):
    r = []
    if growth > hist_cagr + 0.03:
        r.append(f"Crescimento projetado ({growth*100:.0f}%aa) supera CAGR hist. ({hist_cagr*100:.0f}%aa) — revisar premissa")
    if wacc < 0.10:
        r.append("WACC abaixo de 10% — modelo sensível a alta de juros (Selic)")
    if margin > 0.45:
        r.append(f"Margem EBIT de {margin*100:.0f}% é elevada; compressão reduziria o valor substancialmente")
    if asset["risco_corte"] in ("Médio", "Alto"):
        r.append(f"Risco de corte de dividendo classificado como '{asset['risco_corte']}'")
    if asset["tipo"] == "fii":
        r.append("FIIs distribuem ≥95% do lucro; modelo DCF é indicativo — prefira NAV como referência principal")
    r.append("Risco regulatório/fiscal: reformas tributárias brasileiras podem impactar margens")
    r.append("Dados trimestrais do yfinance podem não refletir o exercício fiscal completo mais recente")
    return r[:6]


# ── HTML rendering ────────────────────────────────────────────────────────────

def build_dcf_html(r: Dict) -> str:
    """Build Bloomberg-style DCF HTML. All lines compact (no 4-space indent)."""

    def _pct(v: float) -> str:
        return f"{v*100:.1f}%"

    def _val_cell(p: float, cur: float) -> str:
        if p is None:
            return '<td style="text-align:right;color:#444">—</td>'
        diff = (p / cur - 1) if cur > 0 else 0
        if diff > 0.15:
            css = "color:#00FF41"
        elif diff < -0.15:
            css = "color:#FF4444"
        else:
            css = "color:#FFFF00"
        return f'<td style="text-align:right;{css};font-weight:bold">{_brl(p)}</td>'

    # ── Section: Assumptions ─────────────────────────────────────────────────
    s_premissas = (
        '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:10px">'
        + _kpi("Receita Base", _M(r["revenue_base"]))
        + _kpi("CAGR Hist.", _pct(r["hist_cagr"]))
        + _kpi("Margem EBIT", _pct(r["ebit_margin"]))
        + _kpi("D&amp;A / Rec.", _pct(r["da_pct"]))
        + _kpi("CapEx / Rec.", _pct(r["capex_pct"]))
        + _kpi("Dívida Líq.", _M(r["net_debt"]))
        + _kpi("Ações (mi)", f"{r['shares']/1e6:.0f}M")
        + _kpi("Beta", f"{r['beta']:.2f}")
        + '</div>'
    )

    # ── Section: WACC breakdown ───────────────────────────────────────────────
    s_wacc = (
        '<div style="display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin-bottom:10px">'
        + _kpi("Ke (CAPM)", _pct(r["ke"]))
        + _kpi("Kd (líq. IR)", _pct(r["kd"] * (1 - BR_CORP_TAX)))
        + _kpi("E / (D+E)", _pct(r["we"]))
        + _kpi("D / (D+E)", _pct(r["wd"]))
        + _kpi("WACC", _pct(r["wacc"]), highlight=True)
        + '</div>'
    )

    # ── Section: Projections table ────────────────────────────────────────────
    proj_rows = ""
    for p in r["projections"]:
        proj_rows += (
            f'<tr>'
            f'<td style="color:#FF8C00;font-weight:bold">{p["Ano"]}</td>'
            f'<td style="text-align:right">{_M(p["Receita"])}</td>'
            f'<td style="text-align:right;color:#00FF41">+{_pct(p["Cresc"])}</td>'
            f'<td style="text-align:right">{_M(p["EBIT"])}</td>'
            f'<td style="text-align:right;color:#888">{_pct(p["Margem EBIT"])}</td>'
            f'<td style="text-align:right">{_M(p["D&A"])}</td>'
            f'<td style="text-align:right;color:#FF4444">({_M(p["CapEx"])})</td>'
            f'<td style="text-align:right;color:#00FF41;font-weight:bold">{_M(p["FCF"])}</td>'
            f'</tr>'
        )
    s_proj = (
        '<div style="overflow-x:auto">'
        '<table class="bb-table">'
        '<thead><tr>'
        '<th>ANO</th><th style="text-align:right">RECEITA</th>'
        '<th style="text-align:right">CRESC</th>'
        '<th style="text-align:right">EBIT</th>'
        '<th style="text-align:right">MARG EBIT</th>'
        '<th style="text-align:right">D&amp;A</th>'
        '<th style="text-align:right">CAPEX</th>'
        '<th style="text-align:right">FCF</th>'
        '</tr></thead>'
        f'<tbody>{proj_rows}</tbody>'
        '</table></div>'
    )

    # ── Section: Valuation bridge ─────────────────────────────────────────────
    def _bridge_row(label, val, bold=False, color="#E0E0E0"):
        fw = "bold" if bold else "normal"
        return (
            f'<div style="display:flex;justify-content:space-between;'
            f'padding:3px 0;border-bottom:1px solid #111">'
            f'<span style="color:#888;font-size:13px">{label}</span>'
            f'<span style="color:{color};font-weight:{fw};font-size:13px">{val}</span>'
            f'</div>'
        )

    s_bridge = (
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">'
        '<div>'
        '<div class="bb-section-title">MÉTODO PERPETUIDADE (Gordon)</div>'
        + _bridge_row("PV dos FCFs (5a)", _M(r["pv_fcfs"]))
        + _bridge_row(f"Valor Terminal (g={_pct(r['terminal_growth'])})", _M(r["tv_perp"]))
        + _bridge_row("PV Valor Terminal", _M(r["pv_tv_perp"]))
        + _bridge_row("Enterprise Value", _M(r["ev_perp"]), bold=True, color="#FFFFFF")
        + _bridge_row("(-) Dívida Líquida", _M(r["net_debt"]), color="#FF8888")
        + _bridge_row("Equity Value", _M(r["ev_perp"] - r["net_debt"]), bold=True)
        + _bridge_row("Valor por Ação", _brl(r["price_perp"]), bold=True, color="#FF8C00")
        + f'<div style="margin-top:6px;text-align:center">'
        + _updown_badge(r["up_perp"])
        + '</div></div>'
        '<div>'
        '<div class="bb-section-title">MÉTODO EXIT MULTIPLE</div>'
        + _bridge_row("PV dos FCFs (5a)", _M(r["pv_fcfs"]))
        + _bridge_row(f"Valor Terminal (EV/EBITDA {r['exit_multiple']:.0f}x)", _M(r["tv_exit"]))
        + _bridge_row("PV Valor Terminal", _M(r["pv_tv_exit"]))
        + _bridge_row("Enterprise Value", _M(r["ev_exit"]), bold=True, color="#FFFFFF")
        + _bridge_row("(-) Dívida Líquida", _M(r["net_debt"]), color="#FF8888")
        + _bridge_row("Equity Value", _M(r["ev_exit"] - r["net_debt"]), bold=True)
        + _bridge_row("Valor por Ação", _brl(r["price_exit"]), bold=True, color="#FF8C00")
        + f'<div style="margin-top:6px;text-align:center">'
        + _updown_badge(r["up_exit"])
        + '</div></div>'
        '</div>'
    )

    # ── Section: Sensitivity table ────────────────────────────────────────────
    g_headers = "".join(
        f'<th style="text-align:right">g={_pct(g)}</th>'
        for g in r["g_range"]
    )
    sens_rows = ""
    for i, w in enumerate(r["wacc_range"]):
        marker = " ◀" if abs(w - r["wacc"]) < 0.001 else ""
        sens_rows += f'<tr><td style="color:#FF8C00;white-space:nowrap">WACC {_pct(w)}{marker}</td>'
        for p in r["sens"][i]:
            sens_rows += _val_cell(p, r["cur"])
        sens_rows += "</tr>"

    s_sens = (
        '<div style="overflow-x:auto">'
        '<table class="bb-table">'
        f'<thead><tr><th>WACC \\ g</th>{g_headers}</tr></thead>'
        f'<tbody>{sens_rows}</tbody>'
        '</table>'
        '<div style="font-size:12px;color:#555;margin-top:4px">'
        '&#9646; Verde: &gt;15% upside | Amarelo: ±15% | Vermelho: &gt;15% downside'
        '</div></div>'
    )

    # ── Section: Verdict ──────────────────────────────────────────────────────
    up_avg_pct = _pct(abs(r["up_avg"]))
    direction  = "abaixo" if r["up_avg"] > 0 else "acima"
    s_verdict = (
        f'<div style="border:2px solid #FF8C00;padding:14px;margin-bottom:10px;text-align:center">'
        f'<div style="font-size:13px;color:#888;letter-spacing:2px;margin-bottom:6px">CONCLUSÃO DCF</div>'
        f'<div style="font-size:24px;font-weight:bold" class="{r["vcls"]}">'
        f'{r["vemoji"]} {r["verdict"]}</div>'
        f'<div style="margin-top:8px;font-size:14px;color:#E0E0E0">'
        f'Preço atual: <strong style="color:#FFFFFF">{_brl(r["cur"])}</strong>'
        f'&nbsp;|&nbsp;'
        f'Valor justo médio: <strong style="color:#FF8C00">{_brl(r["fair_value"])}</strong>'
        f'&nbsp;|&nbsp;'
        f'Ação está {up_avg_pct} {direction} do valor estimado'
        f'</div></div>'
    )

    # ── Section: Risks ────────────────────────────────────────────────────────
    risk_items = "".join(
        f'<li style="margin-bottom:4px;color:#CCCCCC">{rk}</li>'
        for rk in r["risks"]
    )
    s_risks = (
        f'<ul style="margin:0;padding-left:18px;font-size:13px;font-family:Courier New">'
        f'{risk_items}</ul>'
    )

    # ── Assemble ──────────────────────────────────────────────────────────────
    def _section(title, content):
        return (
            f'<div class="bb-section-title">{title}</div>'
            f'<div style="margin-bottom:14px">{content}</div>'
        )

    return (
        '<div class="bb-terminal">'
        + _section("PREMISSAS &amp; DADOS HISTÓRICOS", s_premissas)
        + _section("WACC — CUSTO MÉDIO PONDERADO DE CAPITAL", s_wacc)
        + _section("PROJEÇÃO DE RECEITA E FREE CASH FLOW (5 ANOS)", s_proj)
        + _section("CÁLCULO DO VALOR INTRÍNSECO", s_bridge)
        + _section("SENSIBILIDADE — VALOR POR AÇÃO (PERPETUIDADE × WACC)", s_sens)
        + _section("CONCLUSÃO", s_verdict)
        + _section("PRINCIPAIS RISCOS AO MODELO", s_risks)
        + '</div>'
    )


def _kpi(label: str, value: str, highlight: bool = False) -> str:
    color = "#FF8C00" if highlight else "#FFFFFF"
    return (
        f'<div style="background:#0A1020;padding:8px;border:1px solid #1A2A3A">'
        f'<div style="font-size:11px;color:#888;letter-spacing:1px;text-transform:uppercase">{label}</div>'
        f'<div style="font-size:16px;font-weight:bold;color:{color};margin-top:2px">{value}</div>'
        f'</div>'
    )


def _updown_badge(pct_val: float) -> str:
    sign  = "+" if pct_val >= 0 else ""
    color = "#00FF41" if pct_val >= 0 else "#FF4444"
    label = "vs preço atual"
    return (
        f'<span style="background:{color};color:#000;font-weight:bold;'
        f'padding:4px 12px;font-size:14px;font-family:Courier New">'
        f'{sign}{pct_val*100:.1f}% {label}</span>'
    )
