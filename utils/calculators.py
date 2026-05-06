import pandas as pd
from typing import Optional
from config import JCP_TAX_RATE


def portfolio_weighted_dy(assets: list[dict]) -> float:
    return sum(a["dy_anual"] * a["peso_alvo"] for a in assets)


def effective_dy(asset: dict) -> float:
    """Net DY after tax (JCP portion taxed at 15%)."""
    gross = asset["dy_anual"]
    if asset["tributacao"] == "jcp_15":
        jcp_share = gross * asset["jcp_fracao"]
        net_jcp   = jcp_share * (1 - JCP_TAX_RATE)
        dividend_share = gross * (1 - asset["jcp_fracao"])
        return net_jcp + dividend_share
    return gross


def portfolio_effective_dy(assets: list[dict]) -> float:
    return sum(effective_dy(a) * a["peso_alvo"] for a in assets)


def monthly_income(capital: float, annual_dy: float) -> float:
    return capital * annual_dy / 12


def capital_for_goal(monthly_goal: float, annual_dy: float) -> float:
    if annual_dy <= 0:
        return float("inf")
    return (monthly_goal * 12) / annual_dy


def gap_analysis(capital: float, monthly_goal: float, weighted_dy: float) -> dict:
    current_income = monthly_income(capital, weighted_dy)
    needed         = capital_for_goal(monthly_goal, weighted_dy)
    implied_yield  = (monthly_goal * 12) / capital if capital > 0 else float("inf")
    return {
        "current_monthly_income": current_income,
        "capital_needed":         needed,
        "gap_capital":            needed - capital,
        "gap_multiplier":         needed / capital if capital > 0 else float("inf"),
        "implied_yield_needed":   implied_yield,
    }


def simulate_drip(
    initial_capital: float,
    annual_dy: float,
    years: int,
    dividend_growth_rate: float = 0.065,
    monthly_additional: float   = 0.0,
) -> pd.DataFrame:
    monthly_dy_growth = (1 + dividend_growth_rate) ** (1 / 12) - 1
    current_dy        = annual_dy
    portfolio         = initial_capital
    cumulative_divs   = 0.0
    rows = []

    for m in range(1, years * 12 + 1):
        income           = portfolio * (current_dy / 12)
        cumulative_divs += income
        portfolio       += income + monthly_additional
        current_dy      *= 1 + monthly_dy_growth

        rows.append({
            "mes":                  m,
            "ano":                  round(m / 12, 4),
            "portfolio_value":      portfolio,
            "monthly_income":       income,
            "cumulative_dividends": cumulative_divs,
            "dy_current":           current_dy,
        })

    return pd.DataFrame(rows)


def years_to_reach_goal(drip_df: pd.DataFrame, monthly_goal: float) -> Optional[float]:
    hits = drip_df[drip_df["monthly_income"] >= monthly_goal]
    if hits.empty:
        return None
    return hits.iloc[0]["ano"]


def compute_rebalancing(
    assets: list[dict],
    current_values: dict,
    total: float,
    threshold: float = 0.02,
) -> pd.DataFrame:
    rows = []
    for a in assets:
        ticker      = a["ticker"]
        target_pct  = a["peso_alvo"]
        current_val = current_values.get(ticker, 0.0)
        current_pct = current_val / total if total > 0 else 0.0
        target_val  = total * target_pct
        diff        = target_val - current_val
        drift       = abs(current_pct - target_pct)

        if drift <= threshold:
            operacao = "MANTER"
        elif diff > 0:
            operacao = "COMPRAR"
        else:
            operacao = "VENDER"

        rows.append({
            "Ticker":       ticker,
            "Nome":         a["nome"],
            "Peso Alvo":    target_pct,
            "Peso Atual":   current_pct,
            "Valor Alvo":   target_val,
            "Valor Atual":  current_val,
            "Diferença":    diff,
            "Drift":        drift,
            "Operação":     operacao,
        })

    df = pd.DataFrame(rows)
    df.sort_values("Drift", ascending=False, inplace=True, ignore_index=True)
    return df


def income_sensitivity_table(assets: list[dict]) -> pd.DataFrame:
    weighted_dy = portfolio_weighted_dy(assets)
    eff_dy      = portfolio_effective_dy(assets)
    capitais    = [10_000, 50_000, 100_000, 200_000, 300_000, 500_000, 1_000_000]
    rows = []
    for c in capitais:
        rows.append({
            "Capital":        c,
            "Renda Bruta/mês":  monthly_income(c, weighted_dy),
            "Renda Líq/mês":    monthly_income(c, eff_dy),
            "Renda Bruta/ano":  monthly_income(c, weighted_dy) * 12,
        })
    return pd.DataFrame(rows)
