r"""
Relatório mensal de rebalanceamento — executar via cron/Agendador de Tarefas.

Agendamento Windows (Agendador de Tarefas):
  Programa: python
  Argumentos: "C:\Users\Gabriel\Documents\Python Scripts\Carteira Dividendos\run_monthly.py"
  Disparar: mensalmente, no 1 dia de cada mes as 08:00

Agendamento Linux/Mac (cron):
  0 8 1 * * cd "/path/to/Carteira Dividendos" && python run_monthly.py

Configuracao: crie um arquivo .env (veja .env.example).
Se .env nao existir, roda em modo DRY RUN e salva relatorio_preview.html.
"""

import os
import sys
from datetime import datetime

# Garante que o diretório do script está no path
sys.path.insert(0, os.path.dirname(__file__))

try:
    from dotenv import load_dotenv
    load_dotenv()
    HAS_DOTENV = True
except ImportError:
    HAS_DOTENV = False

from config import MONTHLY_INCOME_GOAL, DIVIDEND_GROWTH_RATE, DRIP_YEARS, REBAL_DRIFT_THRESHOLD
from data.portfolio import PORTFOLIO
from utils.calculators import (
    portfolio_weighted_dy, monthly_income, simulate_drip,
    years_to_reach_goal, compute_rebalancing,
)
from utils.email_sender import generate_html, send_email


def load_current_positions() -> dict:
    """
    Carrega as posições atuais.

    Para uso real: substitua esta função por leitura de CSV, banco de dados,
    ou arquivo JSON com suas posições reais na corretora.

    Formato esperado do CSV (posicoes.csv):
        ticker,valor
        TAEE11,850.00
        BBAS3,720.00
        ...
    """
    csv_path = os.path.join(os.path.dirname(__file__), "posicoes.csv")

    if os.path.exists(csv_path):
        import csv
        positions = {}
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                positions[row["ticker"].strip().upper()] = float(row["valor"])
        print(f"[run_monthly] Posições carregadas de {csv_path}")
        return positions

    # Fallback: alocação perfeita (100% nos pesos alvo)
    total_estimado = float(os.getenv("PORTFOLIO_VALUE", "10000"))
    print(f"[run_monthly] posicoes.csv não encontrado — usando alocação ideal para R${total_estimado:,.0f}")
    return {a["ticker"]: total_estimado * a["peso_alvo"] for a in PORTFOLIO}


def main():
    mes_ref = datetime.now().strftime("%B/%Y").capitalize()
    print(f"\n{'='*60}")
    print(f"  Carteira Dividendos — Relatório {mes_ref}")
    print(f"{'='*60}\n")

    # Dados da carteira
    weighted_dy   = portfolio_weighted_dy(PORTFOLIO)
    current_pos   = load_current_positions()
    total_port    = sum(current_pos.values())
    renda_mes     = monthly_income(total_port, weighted_dy)
    meta_mensal   = float(os.getenv("META_MENSAL", str(MONTHLY_INCOME_GOAL)))
    aporte_mensal = float(os.getenv("APORTE_MENSAL", "0"))

    print(f"  Portfólio total : R$ {total_port:,.2f}")
    print(f"  Renda estimada  : R$ {renda_mes:,.2f}/mês")
    print(f"  Meta mensal     : R$ {meta_mensal:,.2f}/mês")
    print(f"  DY médio        : {weighted_dy*100:.2f}%\n")

    # DRIP — anos para meta
    drip_df   = simulate_drip(total_port, weighted_dy, 35, DIVIDEND_GROWTH_RATE, aporte_mensal)
    anos_meta = years_to_reach_goal(drip_df, meta_mensal)

    # Rebalanceamento
    rebal_df = compute_rebalancing(PORTFOLIO, current_pos, total_port, REBAL_DRIFT_THRESHOLD)
    ops      = rebal_df["Operação"].value_counts()
    print(f"  Rebalanceamento : {ops.get('COMPRAR',0)} compras | {ops.get('VENDER',0)} vendas | {ops.get('MANTER',0)} manter\n")

    # Gerar HTML
    html = generate_html(
        mes_ref        = mes_ref,
        portfolio_atual= total_port,
        renda_mes      = renda_mes,
        meta_mensal    = meta_mensal,
        weighted_dy    = weighted_dy,
        rebal_df       = rebal_df,
        anos_meta      = anos_meta,
        anos_simulacao = DRIP_YEARS,
    )

    # Determinar modo (dry run ou envio real)
    smtp_host = os.getenv("SMTP_HOST", "")
    if not smtp_host:
        print("[run_monthly] SMTP não configurado — modo DRY RUN")
        preview_path = os.path.join(os.path.dirname(__file__), "relatorio_preview.html")
        with open(preview_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"[run_monthly] HTML salvo em: {preview_path}")
        print("[run_monthly] Configure .env para envio real por e-mail.\n")
        return

    smtp_config = {
        "host":     smtp_host,
        "port":     os.getenv("SMTP_PORT", "587"),
        "user":     os.getenv("SMTP_USER", ""),
        "password": os.getenv("SMTP_PASS", ""),
        "dest":     os.getenv("EMAIL_DEST", os.getenv("SMTP_USER", "")),
    }

    subject = f"[Carteira Dividendos] Relatório {mes_ref}"
    ok = send_email(html, subject, smtp_config)
    if ok:
        print(f"[run_monthly] E-mail enviado para {smtp_config['dest']}")
    else:
        print("[run_monthly] Falha no envio — verifique as credenciais SMTP em .env")


if __name__ == "__main__":
    main()
