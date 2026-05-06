import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

from utils.formatters import brl, pct


def _row_color(operacao: str) -> str:
    if operacao == "COMPRAR":
        return "#d4edda"
    if operacao == "VENDER":
        return "#f8d7da"
    return "#f8f9fa"


def generate_html(
    mes_ref: str,
    portfolio_atual: float,
    renda_mes: float,
    meta_mensal: float,
    weighted_dy: float,
    rebal_df,
    anos_meta,
    anos_simulacao: int,
) -> str:
    pct_meta = (renda_mes / meta_mensal * 100) if meta_mensal > 0 else 0

    # Build rebalancing rows — only actionable items
    actionable = rebal_df[rebal_df["Operação"] != "MANTER"]
    rebal_rows = ""
    for _, row in actionable.iterrows():
        color = _row_color(row["Operação"])
        diff_fmt = f"+{brl(row['Diferença'])}" if row["Diferença"] >= 0 else f"-{brl(abs(row['Diferença']))}"
        rebal_rows += f"""
        <tr style="background:{color}">
            <td style="padding:8px;border:1px solid #dee2e6">{row['Ticker']}</td>
            <td style="padding:8px;border:1px solid #dee2e6">{row['Nome']}</td>
            <td style="padding:8px;border:1px solid #dee2e6;text-align:center"><strong>{row['Operação']}</strong></td>
            <td style="padding:8px;border:1px solid #dee2e6;text-align:right">{pct(row['Peso Alvo'] if isinstance(row['Peso Alvo'], float) else 0)}</td>
            <td style="padding:8px;border:1px solid #dee2e6;text-align:right">{pct(row['Peso Atual'] if isinstance(row['Peso Atual'], float) else 0)}</td>
            <td style="padding:8px;border:1px solid #dee2e6;text-align:right">{diff_fmt}</td>
        </tr>"""

    if not rebal_rows:
        rebal_rows = """
        <tr>
            <td colspan="6" style="padding:12px;text-align:center;color:#155724;background:#d4edda">
                Carteira equilibrada — nenhum rebalanceamento necessário este mês.
            </td>
        </tr>"""

    anos_meta_str = f"{anos_meta:.1f} anos" if anos_meta else f">{anos_simulacao} anos"

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="font-family:Arial,sans-serif;background:#f4f4f4;margin:0;padding:20px">
<div style="max-width:700px;margin:auto;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.1)">

  <!-- Header -->
  <div style="background:linear-gradient(135deg,#1a5276,#2980b9);color:#fff;padding:28px 32px">
    <h1 style="margin:0;font-size:22px">Relatório Mensal — Carteira de Dividendos</h1>
    <p style="margin:6px 0 0;opacity:0.85;font-size:14px">{mes_ref}</p>
  </div>

  <!-- KPIs -->
  <div style="display:flex;gap:0;border-bottom:1px solid #dee2e6">
    <div style="flex:1;padding:20px 24px;border-right:1px solid #dee2e6">
      <div style="font-size:12px;color:#6c757d;text-transform:uppercase;letter-spacing:1px">Portfólio Total</div>
      <div style="font-size:26px;font-weight:bold;color:#1a5276;margin-top:4px">{brl(portfolio_atual)}</div>
    </div>
    <div style="flex:1;padding:20px 24px;border-right:1px solid #dee2e6">
      <div style="font-size:12px;color:#6c757d;text-transform:uppercase;letter-spacing:1px">Renda do Mês</div>
      <div style="font-size:26px;font-weight:bold;color:#27ae60;margin-top:4px">{brl(renda_mes)}</div>
    </div>
    <div style="flex:1;padding:20px 24px;border-right:1px solid #dee2e6">
      <div style="font-size:12px;color:#6c757d;text-transform:uppercase;letter-spacing:1px">% da Meta</div>
      <div style="font-size:26px;font-weight:bold;color:{'#27ae60' if pct_meta>=100 else '#e67e22'};margin-top:4px">{pct_meta:.1f}%</div>
    </div>
    <div style="flex:1;padding:20px 24px">
      <div style="font-size:12px;color:#6c757d;text-transform:uppercase;letter-spacing:1px">DY Carteira</div>
      <div style="font-size:26px;font-weight:bold;color:#8e44ad;margin-top:4px">{pct(weighted_dy)}</div>
    </div>
  </div>

  <!-- Rebalancing -->
  <div style="padding:24px 32px">
    <h2 style="font-size:16px;color:#2c3e50;margin-top:0">Operações de Rebalanceamento</h2>
    <table style="width:100%;border-collapse:collapse;font-size:14px">
      <thead>
        <tr style="background:#2980b9;color:#fff">
          <th style="padding:10px 8px;text-align:left">Ticker</th>
          <th style="padding:10px 8px;text-align:left">Nome</th>
          <th style="padding:10px 8px;text-align:center">Operação</th>
          <th style="padding:10px 8px;text-align:right">Peso Alvo</th>
          <th style="padding:10px 8px;text-align:right">Peso Atual</th>
          <th style="padding:10px 8px;text-align:right">Ajuste</th>
        </tr>
      </thead>
      <tbody>{rebal_rows}</tbody>
    </table>
  </div>

  <!-- DRIP Progress -->
  <div style="padding:0 32px 24px">
    <h2 style="font-size:16px;color:#2c3e50">Progresso DRIP</h2>
    <div style="background:#eaf4fb;border-left:4px solid #2980b9;padding:14px 16px;border-radius:0 4px 4px 0;font-size:14px">
      Pelo ritmo atual de reinvestimento, você deve atingir a meta de <strong>{brl(meta_mensal)}/mês</strong>
      em aproximadamente <strong>{anos_meta_str}</strong>.
    </div>
  </div>

  <!-- Footer -->
  <div style="background:#f8f9fa;padding:16px 32px;font-size:11px;color:#6c757d;border-top:1px solid #dee2e6">
    <strong>Aviso:</strong> Este relatório é gerado automaticamente e tem caráter educacional.
    Não constitui recomendação de investimento. Tributação: dividendos de ações isentos para PF (Lei 9.249/95);
    JCP retido 15% na fonte; FII isento PF se condições Lei 11.033/2004.
    Verifique sempre os dados atualizados na B3 e na sua corretora.
  </div>
</div>
</body>
</html>"""
    return html


def send_email(html: str, subject: str, smtp_config: dict) -> bool:
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = smtp_config["user"]
        msg["To"]      = smtp_config["dest"]
        msg.attach(MIMEText(html, "html", "utf-8"))

        with smtplib.SMTP(smtp_config["host"], int(smtp_config["port"])) as server:
            server.ehlo()
            server.starttls()
            server.login(smtp_config["user"], smtp_config["password"])
            server.sendmail(smtp_config["user"], smtp_config["dest"], msg.as_string())

        return True
    except Exception as e:
        print(f"[email_sender] Erro ao enviar: {e}")
        return False
