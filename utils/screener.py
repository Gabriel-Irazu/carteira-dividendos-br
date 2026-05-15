from typing import Optional, Dict
import requests
from bs4 import BeautifulSoup
import pandas as pd
import numpy as np
import streamlit as st

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Connection": "keep-alive",
    "Referer": "https://www.fundamentus.com.br/",
}

FUNDAMENTUS_URL = "https://www.fundamentus.com.br/detalhes.php?papel={}"


def _parse_br(text: str) -> Optional[float]:
    if not text:
        return None
    clean = (
        text.strip()
        .replace(".", "")
        .replace(",", ".")
        .replace("%", "")
        .replace("R$", "")
        .strip()
    )
    if clean in ("", "-", "N/A", "?"):
        return None
    try:
        return float(clean)
    except ValueError:
        return None


@st.cache_data(ttl=3600, show_spinner=False)
def get_fundamentus_detalhes(ticker: str) -> Dict[str, str]:
    url = FUNDAMENTUS_URL.format(ticker)
    try:
        r = requests.get(url, headers=_HEADERS, timeout=15)
        soup = BeautifulSoup(r.content.decode("iso-8859-1"), "html.parser")
        data: Dict[str, str] = {}
        for table in soup.find_all("table", class_="w728"):
            for row in table.find_all("tr"):
                cells = row.find_all("td")
                for i in range(0, len(cells) - 1, 2):
                    label = cells[i].get_text(strip=True).strip("?").strip()
                    value = cells[i + 1].get_text(strip=True)
                    if label:
                        data[label] = value
        return data if data else {"_error": "Sem dados retornados"}
    except Exception as e:
        return {"_error": str(e)}


@st.cache_data(ttl=1800, show_spinner=False)
def get_price_history(ticker: str) -> pd.DataFrame:
    import yfinance as yf
    try:
        df = yf.download(f"{ticker}.SA", period="1y", auto_adjust=True, progress=False)
        if df.empty:
            return pd.DataFrame()
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        return df
    except Exception:
        return pd.DataFrame()


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "Close" not in df.columns:
        return df
    close = df["Close"].squeeze()
    df = df.copy()

    # MACD 12/26/9
    ema12        = close.ewm(span=12, adjust=False).mean()
    ema26        = close.ewm(span=26, adjust=False).mean()
    df["MACD"]   = ema12 - ema26
    df["Signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["Hist"]   = df["MACD"] - df["Signal"]

    # RSI 14
    delta        = close.diff()
    gain         = delta.clip(lower=0).ewm(com=13, adjust=False).mean()
    loss         = (-delta.clip(upper=0)).ewm(com=13, adjust=False).mean()
    df["RSI"]    = 100 - (100 / (1 + gain / loss.replace(0, np.nan)))

    # Bollinger Bands 20/2
    sma20        = close.rolling(20).mean()
    std20        = close.rolling(20).std()
    df["BB_Mid"] = sma20
    df["BB_Up"]  = sma20 + 2 * std20
    df["BB_Lo"]  = sma20 - 2 * std20

    return df


def build_screener_df(portfolio: list, fundamentus_data: Optional[Dict[str, dict]] = None) -> pd.DataFrame:
    rows = []
    for a in portfolio:
        t = a["ticker"]
        fd = (fundamentus_data or {}).get(t, {})
        rows.append({
            "Ticker":     t,
            "Nome":       a["nome"],
            "Setor":      a["setor"],
            "Cotação":    _parse_br(fd.get("Cotação", "")) or a["preco"],
            "DY%":        (_parse_br(fd.get("Div. Yield", "")) or a["dy_anual"] * 100),
            "P/L":        _parse_br(fd.get("P/L", "")) or None,
            "P/VP":       _parse_br(fd.get("P/VP", "")) or None,
            "EV/EBITDA":  _parse_br(fd.get("EV/EBITDA", "")) or None,
            "ROE%":       _parse_br(fd.get("ROE", "")) or None,
            "M.Líq%":     _parse_br(fd.get("Margem Líquida", "")) or None,
            "Nota":       a["nota_seguranca"],
            "Risco":      a["risco_corte"],
        })
    return pd.DataFrame(rows)


def build_bloomberg_chart(df: pd.DataFrame, ticker: str):
    from plotly.subplots import make_subplots
    import plotly.graph_objects as go

    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        row_heights=[0.58, 0.24, 0.18],
        vertical_spacing=0.02,
        subplot_titles=("", "MACD (12/26/9)", "RSI (14)"),
    )

    # ── Row 1: Candlestick + Bollinger Bands ─────────────────────────────────
    fig.add_trace(go.Candlestick(
        x=df.index,
        open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
        name="Preço",
        increasing=dict(line_color="#00FF41", fillcolor="#00FF41"),
        decreasing=dict(line_color="#FF4444", fillcolor="#FF4444"),
        showlegend=False,
    ), row=1, col=1)

    for col_name, color, dash in [
        ("BB_Up",  "#4A90D9", "dot"),
        ("BB_Mid", "#888888", "dash"),
        ("BB_Lo",  "#4A90D9", "dot"),
    ]:
        if col_name in df.columns:
            fig.add_trace(go.Scatter(
                x=df.index, y=df[col_name], name=col_name,
                line=dict(color=color, width=1, dash=dash),
                showlegend=False, hoverinfo="skip",
            ), row=1, col=1)

    # ── Row 2: MACD ───────────────────────────────────────────────────────────
    if "Hist" in df.columns:
        hist_colors = ["#00FF41" if v >= 0 else "#FF4444" for v in df["Hist"].fillna(0)]
        fig.add_trace(go.Bar(
            x=df.index, y=df["Hist"], name="Histograma",
            marker_color=hist_colors, showlegend=False,
        ), row=2, col=1)
    if "MACD" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["MACD"], name="MACD",
            line=dict(color="#FF8C00", width=1.5), showlegend=False,
        ), row=2, col=1)
    if "Signal" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["Signal"], name="Signal",
            line=dict(color="#FFFFFF", width=1, dash="dot"), showlegend=False,
        ), row=2, col=1)

    # ── Row 3: RSI ────────────────────────────────────────────────────────────
    if "RSI" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["RSI"], name="RSI",
            line=dict(color="#FFFF00", width=1.5), showlegend=False,
        ), row=3, col=1)
        for level, color in [(70, "#FF4444"), (30, "#00FF41")]:
            fig.add_hline(y=level, line_dash="dot", line_color=color,
                          line_width=1, row=3, col=1)

    _grid = dict(gridcolor="#1A2A3A", zerolinecolor="#1A2A3A",
                 linecolor="#333333", tickcolor="#888888")
    fig.update_layout(
        paper_bgcolor="#000000",
        plot_bgcolor="#050D1A",
        font=dict(family="Courier New, monospace", color="#E0E0E0", size=10),
        title=dict(
            text=f"<b>{ticker}</b> — Histórico 1 Ano",
            font=dict(color="#FF8C00", size=13, family="Courier New"),
        ),
        xaxis_rangeslider_visible=False,
        height=660,
        margin=dict(l=50, r=20, t=40, b=20),
        hovermode="x unified",
        hoverlabel=dict(bgcolor="#050D1A", font_color="#FF8C00",
                        font_family="Courier New"),
    )
    for i in range(1, 4):
        fig.update_xaxes(**_grid, row=i, col=1)
        fig.update_yaxes(**_grid, row=i, col=1)
    fig.update_yaxes(title_text="R$", row=1, col=1,
                     title_font=dict(color="#888"))
    fig.update_yaxes(title_text="MACD", row=2, col=1,
                     title_font=dict(color="#888"))
    fig.update_yaxes(title_text="RSI", row=3, col=1,
                     range=[0, 100], title_font=dict(color="#888"))

    for ann in fig.layout.annotations:
        ann.font.color = "#FF8C00"
        ann.font.family = "Courier New"
        ann.font.size = 10

    return fig


BLOOMBERG_CSS = """
<style>
.bb-bar {
    background: #FF8C00;
    color: #000000;
    font-family: 'Courier New', Courier, monospace;
    font-size: 14px;
    font-weight: bold;
    letter-spacing: 2px;
    padding: 6px 14px;
    margin-bottom: 10px;
}
.bb-terminal {
    background: #000000;
    border: 1px solid #FF8C00;
    font-family: 'Courier New', Courier, monospace;
    color: #E0E0E0;
    padding: 16px 18px;
    margin-bottom: 12px;
}
.bb-detail-header {
    padding-bottom: 8px;
    border-bottom: 1px solid #FF8C00;
    margin-bottom: 10px;
}
.bb-ticker-tag {
    background: #FF8C00;
    color: #000;
    font-weight: bold;
    font-size: 16px;
    padding: 2px 10px;
    letter-spacing: 1px;
}
.bb-equity-label {
    color: #FF8C00;
    font-size: 15px;
    font-weight: bold;
    letter-spacing: 1px;
}
.bb-price {
    font-size: 30px;
    font-weight: bold;
    color: #FFFFFF;
}
.bb-pos  { color: #00FF41; font-weight: bold; }
.bb-neg  { color: #FF4444; font-weight: bold; }
.bb-meta { color: #888888; font-size: 13px; }
.bb-section-title {
    color: #FF8C00;
    font-size: 12px;
    font-weight: bold;
    letter-spacing: 2px;
    text-transform: uppercase;
    border-bottom: 1px solid #333;
    padding-bottom: 3px;
    margin: 10px 0 6px 0;
}
.bb-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 12px;
}
.bb-metric {
    display: flex;
    justify-content: space-between;
    padding: 3px 0;
    border-bottom: 1px solid #111;
}
.bb-label { color: #888888; font-size: 12px; }
.bb-value { color: #FFFFFF;  font-size: 13px; font-weight: bold; }
.bb-value-pos { color: #00FF41; font-size: 13px; font-weight: bold; }
.bb-value-neg { color: #FF4444; font-size: 13px; font-weight: bold; }
.bb-table {
    width: 100%;
    border-collapse: collapse;
    font-family: 'Courier New', monospace;
    font-size: 13px;
}
.bb-table th {
    background: #FF8C00;
    color: #000000;
    font-weight: bold;
    padding: 6px 10px;
    text-align: left;
    letter-spacing: 1px;
    font-size: 12px;
}
.bb-table td {
    padding: 5px 10px;
    border-bottom: 1px solid #111;
    color: #E0E0E0;
}
.bb-table tr:hover td { background: #0A1A2A; }
.bb-td-ticker { color: #FF8C00 !important; font-weight: bold; cursor: pointer; }
.bb-td-pos    { color: #00FF41 !important; }
.bb-td-neg    { color: #FF4444 !important; }
.bb-td-risco-baixo  { color: #00FF41 !important; }
.bb-td-risco-medio  { color: #FFFF00 !important; }
.bb-td-risco-alto   { color: #FF4444 !important; }
</style>
"""


def _val(v: Optional[float], fmt: str = ".1f", suffix: str = "") -> str:
    if v is None:
        return '<span class="bb-meta">—</span>'
    css = "bb-value-pos" if v > 0 else ("bb-value-neg" if v < 0 else "bb-value")
    return f'<span class="{css}">{v:{fmt}}{suffix}</span>'


def build_detail_html(ticker: str, d: Dict[str, str], asset: dict) -> str:
    def g(key: str) -> str:
        return d.get(key, "—")

    def n(key: str) -> Optional[float]:
        return _parse_br(d.get(key, ""))

    cotacao   = n("Cotação") or asset["preco"]
    empresa   = g("Empresa").upper() or asset["nome"].upper()
    setor     = g("Setor") or asset["setor"]
    subsetor  = g("Subsetor")
    mktcap    = g("Valor de mercado")
    volume    = g("Vol $ méd (2m)")
    min52     = g("Min 52 sem")
    max52     = g("Max 52 sem")

    def metric(label: str, raw_val: str, is_pct: bool = False) -> str:
        v = _parse_br(raw_val)
        fmt_val = f"{v:.2f}{'%' if is_pct else ''}" if v is not None else "—"
        if v is None:
            css = "bb-value"
        elif is_pct and v > 0:
            css = "bb-value-pos"
        elif is_pct and v < 0:
            css = "bb-value-neg"
        else:
            css = "bb-value"
        return (f'<div class="bb-metric">'
                f'<span class="bb-label">{label}</span>'
                f'<span class="{css}">{fmt_val}</span>'
                f'</div>')

    valuation_html = (
        metric("P/L",         g("P/L"))
        + metric("P/VP",        g("P/VP"))
        + metric("P/EBIT",      g("P/EBIT"))
        + metric("EV/EBITDA",   g("EV/EBITDA"))
        + metric("EV/EBIT",     g("EV/EBIT"))
        + metric("P/Ativo",     g("P/Ativos"))
        + metric("Div. Yield",  g("Div. Yield"), is_pct=True)
        + metric("LPA",         g("LPA"))
        + metric("VPA",         g("VPA"))
    )

    rentab_html = (
        metric("ROE",         g("ROE"),           is_pct=True)
        + metric("ROA / ROIC",  g("ROIC"),          is_pct=True)
        + metric("M. Bruta",    g("Margem Bruta"),  is_pct=True)
        + metric("M. EBIT",     g("Margem EBIT"),   is_pct=True)
        + metric("M. Líquida",  g("Margem Líquida"), is_pct=True)
        + metric("EBIT/Ativo",  g("EBIT / Ativo"),  is_pct=True)
        + metric("Cresc. 5a",   g("Cres. Rec (5a)"), is_pct=True)
    )

    endiv_html = (
        metric("Dív. Br./PL",    g("Dív. Bruta/Patrim."))
        + metric("Liq. Corrente", g("Liquidez Corr."))
        + metric("Liq. Seca",     g("Liquidez Seca"))
        + metric("Dív. Líq.",     g("Dívida Líquida"))
        + metric("Patrimônio",    g("Patrim. Líquido"))
        + metric("Ativo Total",   g("Ativo"))
        + metric("Rec. Líq.",     g("Receita Líquida"))
        + metric("Lucro Líq.",    g("Lucro Líquido"))
        + metric("EBIT",          g("EBIT"))
    )

    risco_css = {"Baixo": "bb-pos", "Médio": "bb-value-pos", "Alto": "bb-neg"}.get(
        asset["risco_corte"], "bb-value"
    )

    cotacao_fmt = f"{cotacao:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    subsetor_html = (
        f"<span style='color:#555; margin:0 8px'>|</span>"
        f"<span style='color:#666'>{subsetor}</span>"
        if subsetor and subsetor != "—" else ""
    )

    return (
        f'<div class="bb-terminal">'
        f'<div class="bb-detail-header">'
        f'<div style="margin-bottom:6px">'
        f'<span class="bb-ticker-tag">{ticker}</span>'
        f'<span class="bb-equity-label">&nbsp;&lt;EQUITY&gt;</span>'
        f'<span style="color:#555;margin:0 8px">|</span>'
        f'<span style="color:#FFFFFF;font-weight:bold">{empresa}</span>'
        f'<span style="color:#555;margin:0 8px">|</span>'
        f'<span style="color:#888">{setor}</span>'
        f'{subsetor_html}'
        f'</div>'
        f'<div style="display:flex;align-items:baseline;gap:20px;flex-wrap:wrap">'
        f'<span class="bb-price">R$ {cotacao_fmt}</span>'
        f'<span class="bb-meta">MIN 52s {min52} &nbsp;|&nbsp; MAX 52s {max52}</span>'
        f'<span class="bb-meta">VOL M&#201;D {volume}</span>'
        f'<span class="bb-meta">MKTCAP {mktcap}</span>'
        f'</div>'
        f'<div style="margin-top:6px;font-size:12px;color:#888">'
        f'DY: <span class="bb-pos">{g("Div. Yield")}</span>'
        f'&nbsp;|&nbsp; Nota Seg: <span style="color:#FF8C00">{asset["nota_seguranca"]}/10</span>'
        f'&nbsp;|&nbsp; Risco: <span class="{risco_css}">{asset["risco_corte"]}</span>'
        f'&nbsp;|&nbsp; Payout: {asset["payout"]*100:.0f}%'
        f'&nbsp;|&nbsp; Anos cresc.: {asset["anos_crescimento"]}'
        f'</div>'
        f'</div>'
        f'<div class="bb-grid">'
        f'<div><div class="bb-section-title">VALUATION</div>{valuation_html}</div>'
        f'<div><div class="bb-section-title">RENTABILIDADE</div>{rentab_html}</div>'
        f'<div><div class="bb-section-title">BALAN&#199;O / ENDIVIDAMENTO</div>{endiv_html}</div>'
        f'</div>'
        f'</div>'
    )


def build_screener_html(df: pd.DataFrame, selected: str) -> str:
    def _risco_css(v: str) -> str:
        return {"Baixo": "bb-td-risco-baixo", "Médio": "bb-td-risco-medio",
                "Alto": "bb-td-risco-alto"}.get(v, "")

    def _fmt(v, fmt=".1f", suffix=""):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return '<span style="color:#444">—</span>'
        val = f"{v:{fmt}}{suffix}"
        if isinstance(v, float) and v < 0:
            return f'<span class="bb-td-neg">{val}</span>'
        return val

    rows = ""
    for _, r in df.iterrows():
        sel_style = "background:#0A1A2A;" if r["Ticker"] == selected else ""
        rows += f"""
        <tr style="{sel_style}">
          <td class="bb-td-ticker">{r['Ticker']}</td>
          <td>{r['Nome'][:22]}</td>
          <td style="color:#888">{r['Setor'][:18]}</td>
          <td style="text-align:right">{_fmt(r.get('Cotação'), '.2f')}</td>
          <td style="text-align:right" class="bb-td-pos">{_fmt(r.get('DY%'), '.1f', '%')}</td>
          <td style="text-align:right">{_fmt(r.get('P/L'), '.1f', 'x')}</td>
          <td style="text-align:right">{_fmt(r.get('P/VP'), '.2f', 'x')}</td>
          <td style="text-align:right">{_fmt(r.get('EV/EBITDA'), '.1f', 'x')}</td>
          <td style="text-align:right">{_fmt(r.get('ROE%'), '.1f', '%')}</td>
          <td style="text-align:right">{_fmt(r.get('M.Líq%'), '.1f', '%')}</td>
          <td style="text-align:right">{r['Nota']}/10</td>
          <td class="{_risco_css(r['Risco'])}">{r['Risco']}</td>
        </tr>"""

    return f"""
<div style="overflow-x:auto; background:#000">
<table class="bb-table">
  <thead>
    <tr>
      <th>TICKER</th><th>NOME</th><th>SETOR</th>
      <th style="text-align:right">COTAÇÃO</th>
      <th style="text-align:right">DY%</th>
      <th style="text-align:right">P/L</th>
      <th style="text-align:right">P/VP</th>
      <th style="text-align:right">EV/EBITDA</th>
      <th style="text-align:right">ROE%</th>
      <th style="text-align:right">M.LÍQ%</th>
      <th style="text-align:right">NOTA</th>
      <th>RISCO</th>
    </tr>
  </thead>
  <tbody>{rows}</tbody>
</table>
</div>"""
