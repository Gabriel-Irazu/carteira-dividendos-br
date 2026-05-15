import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from config import (
    MONTHLY_INCOME_GOAL, INITIAL_CAPITAL, DRIP_YEARS,
    DIVIDEND_GROWTH_RATE, REBAL_DRIFT_THRESHOLD, JCP_TAX_RATE,
)
from data.portfolio import PORTFOLIO
from utils.calculators import (
    portfolio_weighted_dy, portfolio_effective_dy, monthly_income,
    capital_for_goal, gap_analysis, simulate_drip,
    years_to_reach_goal, compute_rebalancing, income_sensitivity_table,
)
from utils.formatters import brl, pct, color_risco, color_operacao, nota_stars, TRIB_LABEL, style_map
from utils.screener import (
    get_fundamentus_detalhes, get_price_history, add_indicators,
    build_screener_df, build_bloomberg_chart,
    build_detail_html, build_screener_html, BLOOMBERG_CSS,
)

st.set_page_config(
    page_title="Carteira Dividendos BR",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.image("https://img.icons8.com/color/96/money-bag.png", width=60)
    st.title("Parâmetros")

    capital_usuario = st.number_input(
        "Capital disponível (R$)",
        min_value=1_000.0, max_value=10_000_000.0,
        value=float(INITIAL_CAPITAL), step=1_000.0, format="%.0f",
    )
    meta_mensal = st.number_input(
        "Meta de renda mensal (R$)",
        min_value=100.0, max_value=100_000.0,
        value=float(MONTHLY_INCOME_GOAL), step=100.0, format="%.0f",
    )
    aporte_mensal = st.number_input(
        "Aporte mensal adicional (R$)",
        min_value=0.0, max_value=50_000.0,
        value=0.0, step=100.0, format="%.0f",
    )
    anos_simulacao = st.slider("Anos de simulação (DRIP)", 5, 30, DRIP_YEARS)
    cresc_dividendo = st.slider(
        "Crescimento anual dos dividendos (%)",
        1.0, 15.0, DIVIDEND_GROWTH_RATE * 100, step=0.5,
    ) / 100.0
    drift_threshold = st.slider(
        "Gatilho de rebalanceamento (drift %)",
        0.5, 5.0, REBAL_DRIFT_THRESHOLD * 100, step=0.5,
    ) / 100.0

    st.divider()
    st.caption("Dados: mai/2026 — sem API externa")
    st.caption("Este app é educacional. Não constitui recomendação de investimento.")

# ── Pre-compute globals ───────────────────────────────────────────────────────
weighted_dy  = portfolio_weighted_dy(PORTFOLIO)
effective_dy = portfolio_effective_dy(PORTFOLIO)
gap          = gap_analysis(capital_usuario, meta_mensal, weighted_dy)
drip_df      = simulate_drip(
    capital_usuario, weighted_dy, anos_simulacao,
    dividend_growth_rate=cresc_dividendo,
    monthly_additional=aporte_mensal,
)
anos_meta = years_to_reach_goal(drip_df, meta_mensal)

# ── Tabs ─────────────────────────────────────────────────────────────────────
tabs = st.tabs([
    "📋 Blueprint",
    "📊 Projeção de Renda",
    "🔄 DRIP & Meta",
    "🎯 Gap Analysis",
    "🥧 Diversificação",
    "🧾 Tributação",
    "⚖️ Rebalanceamento",
    "📡 Screener",
])

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 — BLUEPRINT
# ═══════════════════════════════════════════════════════════════════════════════
with tabs[0]:
    st.header("Blueprint da Carteira — 18 Ativos Selecionados")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("DY médio ponderado", pct(weighted_dy), help="Yield bruto da carteira")
    col2.metric("DY líquido (após IR JCP)", pct(effective_dy))
    col3.metric("Renda mensal / R$100k", brl(monthly_income(100_000, weighted_dy)))
    col4.metric("Nº de ativos", len(PORTFOLIO))

    st.divider()

    df = pd.DataFrame(PORTFOLIO).sort_values("ranking_defensivo").reset_index(drop=True)
    df["Ranking"] = df["ranking_defensivo"].apply(lambda x: f"#{x}")
    df["Nota ★"]  = df["nota_seguranca"].apply(nota_stars)

    display_cols = {
        "Ranking":          "Ranking",
        "ticker":           "Ticker",
        "nome":             "Nome",
        "setor":            "Setor",
        "tipo":             "Tipo",
        "preco":            "Preço",
        "dy_anual":         "DY Anual",
        "Nota ★":           "Segurança",
        "anos_crescimento": "Anos Cresc.",
        "payout":           "Payout",
        "risco_corte":      "Risco Corte",
        "peso_alvo":        "Peso Alvo",
    }

    disp = df[list(display_cols.keys())].rename(columns=display_cols)
    disp["Preço"]      = disp["Preço"].apply(brl)
    disp["DY Anual"]   = disp["DY Anual"].apply(pct)
    disp["Payout"]     = disp["Payout"].apply(pct)
    disp["Peso Alvo"]  = disp["Peso Alvo"].apply(pct)

    styled = style_map(disp.style, color_risco, subset=["Risco Corte"])
    st.dataframe(styled, use_container_width=True, hide_index=True, height=660)

    st.caption("Ranking: 1 = mais defensivo (WEGE3 com 12 anos de crescimento de dividendos) → 18 = mais agressivo")

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2 — PROJEÇÃO DE RENDA
# ═══════════════════════════════════════════════════════════════════════════════
with tabs[1]:
    st.header("Tabela de Projeção de Renda")
    st.caption(f"DY médio ponderado da carteira: **{pct(weighted_dy)}** | DY líquido: **{pct(effective_dy)}**")

    sens_df = income_sensitivity_table(PORTFOLIO)

    # Compute "anos para meta" per capital level
    anos_lista = []
    for cap in sens_df["Capital"]:
        mini_drip = simulate_drip(cap, weighted_dy, 30, cresc_dividendo, aporte_mensal)
        y = years_to_reach_goal(mini_drip, meta_mensal)
        anos_lista.append(f"{y:.1f} anos" if y else ">30 anos")
    sens_df["Anos p/ Meta*"] = anos_lista

    disp_sens = sens_df.copy()
    disp_sens["Capital"]          = disp_sens["Capital"].apply(brl)
    disp_sens["Renda Bruta/mês"]  = disp_sens["Renda Bruta/mês"].apply(brl)
    disp_sens["Renda Líq/mês"]    = disp_sens["Renda Líq/mês"].apply(brl)
    disp_sens["Renda Bruta/ano"]  = disp_sens["Renda Bruta/ano"].apply(brl)

    st.dataframe(disp_sens, use_container_width=True, hide_index=True)

    st.caption("*Anos para atingir a meta de renda mensal via DRIP + aportes mensais configurados na sidebar.")

    st.divider()
    st.subheader("Capital × Renda Mensal")

    fig = go.Figure()
    fig.add_bar(
        x=sens_df["Capital"],
        y=sens_df["Renda Bruta/mês"],
        name="Renda Bruta",
        marker_color="#2ecc71",
        text=sens_df["Renda Bruta/mês"].apply(brl),
        textposition="outside",
    )
    fig.add_hline(
        y=meta_mensal,
        line_dash="dash", line_color="red",
        annotation_text=f"Meta: {brl(meta_mensal)}/mês",
        annotation_position="top right",
    )
    fig.update_layout(
        xaxis_title="Capital Investido (R$)",
        yaxis_title="Renda Mensal (R$)",
        xaxis=dict(tickformat=",.0f"),
        showlegend=False,
        height=420,
    )
    st.plotly_chart(fig, use_container_width=True)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 3 — DRIP & META
# ═══════════════════════════════════════════════════════════════════════════════
with tabs[2]:
    st.header("Simulação DRIP — Reinvestimento Automático de Dividendos")

    final_portfolio = drip_df["portfolio_value"].iloc[-1]
    final_income    = drip_df["monthly_income"].iloc[-1]
    total_divs      = drip_df["cumulative_dividends"].iloc[-1]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Portfólio final", brl(final_portfolio))
    c2.metric("Renda no último mês", brl(final_income))
    c3.metric("Total de dividendos recebidos", brl(total_divs))
    if anos_meta:
        c4.metric("Anos para atingir a meta", f"{anos_meta:.1f} anos")
    else:
        c4.metric("Anos para atingir a meta", f">{anos_simulacao} anos", delta="Aumente o aporte", delta_color="inverse")

    st.divider()

    # Chart: portfolio value + monthly income
    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(
        x=drip_df["ano"], y=drip_df["portfolio_value"],
        name="Valor do Portfólio", fill="tozeroy",
        line=dict(color="#3498db"), fillcolor="rgba(52,152,219,0.15)",
    ))
    fig2.add_trace(go.Bar(
        x=drip_df["ano"], y=drip_df["monthly_income"],
        name="Renda Mensal", yaxis="y2",
        marker_color="rgba(46,204,113,0.6)",
    ))
    fig2.add_hline(
        y=meta_mensal, yref="y2",
        line_dash="dash", line_color="red",
        annotation_text=f"Meta {brl(meta_mensal)}/mês",
        annotation_position="top right",
    )
    if anos_meta:
        fig2.add_vline(
            x=anos_meta, line_dash="dot", line_color="orange",
            annotation_text=f"Meta atingida: ano {anos_meta:.1f}",
            annotation_position="top left",
        )
    fig2.update_layout(
        yaxis=dict(title="Portfólio (R$)"),
        yaxis2=dict(title="Renda Mensal (R$)", overlaying="y", side="right"),
        xaxis_title="Anos",
        legend=dict(x=0.01, y=0.99),
        height=440,
    )
    st.plotly_chart(fig2, use_container_width=True)

    st.divider()
    st.subheader("Comparativo de Cenários")

    cenarios = [
        ("Pessimista", 0.04),
        ("Base", cresc_dividendo),
        ("Otimista", 0.09),
    ]
    cols = st.columns(3)
    for col, (label, growth) in zip(cols, cenarios):
        df_c = simulate_drip(capital_usuario, weighted_dy, anos_simulacao, growth, aporte_mensal)
        y_c  = years_to_reach_goal(df_c, meta_mensal)
        with col:
            st.markdown(f"**{label}** — crescimento {pct(growth)}/ano")
            st.metric("Portfólio final", brl(df_c["portfolio_value"].iloc[-1]))
            st.metric("Renda final/mês", brl(df_c["monthly_income"].iloc[-1]))
            st.metric("Anos p/ meta", f"{y_c:.1f}" if y_c else f">{anos_simulacao}")

    # Cumulative dividends area chart
    st.divider()
    st.subheader("Dividendos Acumulados ao Longo do Tempo")
    fig3 = px.area(
        drip_df, x="ano", y="cumulative_dividends",
        labels={"ano": "Anos", "cumulative_dividends": "Dividendos Acumulados (R$)"},
        color_discrete_sequence=["#f39c12"],
    )
    fig3.update_layout(height=320)
    st.plotly_chart(fig3, use_container_width=True)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 4 — GAP ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════════
with tabs[3]:
    st.header("Gap Analysis — Onde Você Está e Onde Precisa Chegar")

    renda_atual = gap["current_monthly_income"]
    capital_nec = gap["capital_needed"]
    multiplicador = gap["gap_multiplier"]
    yield_necessario = gap["implied_yield_needed"]

    st.markdown(f"""
<div style="background:#fde8e8;border-left:5px solid #c0392b;border-radius:4px;padding:20px 24px;color:#2c2c2c;line-height:1.7">
  <p style="margin:0 0 6px 0;font-size:16px;font-weight:700;color:#922b21">Diagnóstico honesto da sua carteira</p>
  <p style="margin:0 0 12px 0">
    Com <strong>{brl(capital_usuario)}</strong> investidos a um DY de <strong>{pct(weighted_dy)} ao ano</strong>,
    você recebe hoje <strong>{brl(renda_atual)} por mês</strong> em dividendos —
    equivalente a <strong>{pct(renda_atual / meta_mensal)}</strong> da sua meta de {brl(meta_mensal)} por mês.
  </p>
  <p style="margin:0 0 12px 0">
    Para gerar <strong>{brl(meta_mensal)} por mês</strong> com a carteira atual, você precisaria de
    <strong>{brl(capital_nec)}</strong> investidos — ou seja, <strong>{multiplicador:.0f}x</strong> o capital que você tem hoje.
  </p>
  <p style="margin:0">
    Atingir essa renda com apenas {brl(capital_usuario)} exigiria um yield anual de
    <strong>{pct(yield_necessario)}</strong> — algo que não existe no mercado de forma sustentável.
    A boa notícia: com disciplina de aportes e reinvestimento total dos dividendos (DRIP),
    o tempo trabalha a seu favor. Veja a simulação abaixo.
  </p>
</div>
""", unsafe_allow_html=True)

    c1, c2, c3 = st.columns(3)
    c1.metric(
        "Renda atual gerada",
        brl(renda_atual),
        delta=f"-{brl(meta_mensal - renda_atual)}/mês vs meta",
        delta_color="inverse",
    )
    c2.metric(
        "Capital necessário",
        brl(capital_nec),
        delta=f"Faltam {brl(capital_nec - capital_usuario)}",
        delta_color="inverse",
    )
    c3.metric(
        "Multiplicador de capital",
        f"{multiplicador:.0f}x",
        delta="mais capital necessário",
        delta_color="inverse",
    )

    st.divider()

    # Visual gap bar
    fig_gap = go.Figure(go.Bar(
        x=[brl(capital_usuario), brl(capital_nec)],
        y=[capital_usuario, capital_nec],
        marker_color=["#3498db", "#e74c3c"],
        text=[brl(capital_usuario), brl(capital_nec)],
        textposition="outside",
    ))
    fig_gap.update_layout(
        title="Você tem vs. Você precisa",
        yaxis_title="R$",
        height=360,
        showlegend=False,
    )
    st.plotly_chart(fig_gap, use_container_width=True)

    st.divider()
    st.subheader("Como chegar lá via DRIP + Aportes")

    aportes_cenarios = [500, 1_000, 2_000, 3_000, 5_000]
    rows_gap = []
    for ap in aportes_cenarios:
        df_ap = simulate_drip(capital_usuario, weighted_dy, 35, cresc_dividendo, float(ap))
        y_ap  = years_to_reach_goal(df_ap, meta_mensal)
        rows_gap.append({
            "Aporte Mensal":  brl(ap),
            "Anos p/ Meta":   f"{y_ap:.1f} anos" if y_ap else ">35 anos",
            "Portfólio em 20 anos": brl(simulate_drip(capital_usuario, weighted_dy, 20, cresc_dividendo, float(ap))["portfolio_value"].iloc[-1]),
        })
    st.dataframe(pd.DataFrame(rows_gap), hide_index=True, use_container_width=True)
    st.caption(
        f"Premissas: capital inicial {brl(capital_usuario)}, DY {pct(weighted_dy)}, "
        f"crescimento de dividendos {pct(cresc_dividendo)}/ano."
    )

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 5 — DIVERSIFICAÇÃO
# ═══════════════════════════════════════════════════════════════════════════════
with tabs[4]:
    st.header("Diversificação da Carteira")

    df_div = pd.DataFrame(PORTFOLIO)

    col_a, col_b = st.columns(2)

    with col_a:
        setor_df = df_div.groupby("setor")["peso_alvo"].sum().reset_index()
        fig_setor = px.pie(
            setor_df, names="setor", values="peso_alvo",
            title="Por Setor", hole=0.4,
            color_discrete_sequence=px.colors.qualitative.Set2,
        )
        fig_setor.update_traces(textinfo="percent+label")
        st.plotly_chart(fig_setor, use_container_width=True)

    with col_b:
        tipo_df = df_div.groupby("tipo")["peso_alvo"].sum().reset_index()
        tipo_df["tipo"] = tipo_df["tipo"].map({"acao": "Ações", "fii": "FIIs"})
        fig_tipo = px.pie(
            tipo_df, names="tipo", values="peso_alvo",
            title="Ações vs FIIs", hole=0.4,
            color_discrete_sequence=["#3498db", "#e67e22"],
        )
        fig_tipo.update_traces(textinfo="percent+label")
        st.plotly_chart(fig_tipo, use_container_width=True)

    # Horizontal tape chart
    st.subheader("Alocação por Ativo")
    fig_tape = px.bar(
        df_div.sort_values("peso_alvo", ascending=True),
        x="peso_alvo", y="ticker",
        color="setor", orientation="h",
        text=df_div.sort_values("peso_alvo", ascending=True)["peso_alvo"].apply(pct),
        color_discrete_sequence=px.colors.qualitative.Set2,
        labels={"peso_alvo": "Peso Alvo", "ticker": "Ativo"},
    )
    fig_tape.update_layout(height=560, legend=dict(orientation="h", y=-0.2))
    st.plotly_chart(fig_tape, use_container_width=True)

    # Sector stats table
    st.subheader("Estatísticas por Setor")
    setor_stats = (
        df_div.groupby("setor")
        .agg(
            Ativos=("ticker", "count"),
            Peso_Total=("peso_alvo", "sum"),
            DY_Medio=("dy_anual", "mean"),
            Nota_Media=("nota_seguranca", "mean"),
        )
        .reset_index()
    )
    setor_stats["Peso_Total"] = setor_stats["Peso_Total"].apply(pct)
    setor_stats["DY_Medio"]   = setor_stats["DY_Medio"].apply(pct)
    setor_stats["Nota_Media"] = setor_stats["Nota_Media"].apply(lambda x: f"{x:.1f}/10")
    setor_stats.columns = ["Setor", "Nº Ativos", "Peso Total", "DY Médio", "Nota Média"]
    st.dataframe(setor_stats, hide_index=True, use_container_width=True)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 6 — TRIBUTAÇÃO
# ═══════════════════════════════════════════════════════════════════════════════
with tabs[5]:
    st.header("Implicações Tributárias — Brasil 2026")

    st.success(
        "**Dividendos de Ações — ISENTOS para Pessoa Física**  \n"
        "Art. 10, Lei 9.249/1995. Não há retenção na fonte nem declaração separada de IR."
    )
    st.warning(
        "**JCP (Juros sobre Capital Próprio) — 15% retido na fonte**  \n"
        "Bancos como Itaú (ITUB4) e Banco do Brasil (BBAS3) pagam parte dos rendimentos como JCP. "
        "O IR é descontado diretamente na fonte. Declare como rendimento exclusivo (Carnê-Leão não necessário)."
    )
    st.info(
        "**Rendimentos de FII — ISENTOS para PF (se condições)**  \n"
        "Condições: (1) FII negociado na B3; (2) mínimo 50 cotistas; (3) cotista tem menos de 10% das cotas.  \n"
        "Todos os FIIs desta carteira atendem as condições. Verifique seu % de participação antes de comprar grande volume."
    )

    st.divider()
    st.subheader("Tributação por Ativo")

    df_trib = pd.DataFrame(PORTFOLIO)
    df_trib["Tributação"] = df_trib["tributacao"].map(TRIB_LABEL)
    df_trib["DY Bruto"]   = df_trib["dy_anual"].apply(pct)
    df_trib["DY Líquido"] = df_trib.apply(
        lambda r: pct(r["dy_anual"] * (1 - JCP_TAX_RATE * r["jcp_fracao"])), axis=1
    )
    df_trib["Obs"] = df_trib.apply(
        lambda r: f"JCP: {pct(r['jcp_fracao'])} dos rendimentos" if r["tributacao"] == "jcp_15" else "—",
        axis=1,
    )
    disp_trib = df_trib[["ticker", "nome", "Tributação", "DY Bruto", "DY Líquido", "Obs"]].rename(columns={
        "ticker": "Ticker", "nome": "Nome",
    })
    st.dataframe(disp_trib, hide_index=True, use_container_width=True)
    st.caption("*FII isento para PF se condições da Lei 11.033/2004 forem atendidas.")

    st.divider()
    st.subheader("DY Bruto vs Líquido por Ativo")
    df_trib2 = pd.DataFrame(PORTFOLIO)
    df_trib2["DY Líquido"] = df_trib2.apply(
        lambda r: r["dy_anual"] * (1 - JCP_TAX_RATE * r["jcp_fracao"]), axis=1
    )
    fig_trib = go.Figure()
    fig_trib.add_bar(name="DY Bruto",   x=df_trib2["ticker"], y=df_trib2["dy_anual"],   marker_color="#3498db")
    fig_trib.add_bar(name="DY Líquido", x=df_trib2["ticker"], y=df_trib2["DY Líquido"], marker_color="#2ecc71")
    fig_trib.update_layout(
        barmode="group", yaxis_tickformat=".1%",
        yaxis_title="Dividend Yield", xaxis_title="Ativo", height=380,
    )
    st.plotly_chart(fig_trib, use_container_width=True)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 7 — REBALANCEAMENTO
# ═══════════════════════════════════════════════════════════════════════════════
with tabs[6]:
    st.header("Simulador de Rebalanceamento Mensal")
    st.caption(
        f"Gatilho: drift > **{pct(drift_threshold)}** por ativo. "
        "Ajuste na sidebar. Edite os valores abaixo com sua posição atual."
    )

    # Build default positions (perfect allocation at capital_usuario)
    default_positions = {
        a["ticker"]: round(capital_usuario * a["peso_alvo"], 2)
        for a in PORTFOLIO
    }

    if "current_values" not in st.session_state:
        st.session_state.current_values = default_positions.copy()

    # Editable table
    edit_df = pd.DataFrame([
        {"Ticker": ticker, "Valor Atual (R$)": val}
        for ticker, val in st.session_state.current_values.items()
    ])

    edited = st.data_editor(
        edit_df,
        column_config={
            "Ticker": st.column_config.TextColumn("Ticker", disabled=True),
            "Valor Atual (R$)": st.column_config.NumberColumn(
                "Valor Atual (R$)", min_value=0.0, format="R$ %.2f"
            ),
        },
        hide_index=True,
        use_container_width=True,
        key="rebal_editor",
    )

    # Sync session state
    for _, row in edited.iterrows():
        st.session_state.current_values[row["Ticker"]] = row["Valor Atual (R$)"]

    col_reset, col_spacer = st.columns([1, 5])
    if col_reset.button("Resetar para alocação ideal"):
        st.session_state.current_values = default_positions.copy()
        st.rerun()

    total_atual = sum(st.session_state.current_values.values())
    st.metric("Total do portfólio", brl(total_atual))

    rebal_df = compute_rebalancing(PORTFOLIO, st.session_state.current_values, total_atual, drift_threshold)

    st.divider()
    st.subheader("Operações Sugeridas")

    # Format for display
    disp_rebal = rebal_df.copy()
    disp_rebal["Peso Alvo"]   = disp_rebal["Peso Alvo"].apply(pct)
    disp_rebal["Peso Atual"]  = disp_rebal["Peso Atual"].apply(pct)
    disp_rebal["Drift"]       = disp_rebal["Drift"].apply(pct)
    disp_rebal["Valor Alvo"]  = disp_rebal["Valor Alvo"].apply(brl)
    disp_rebal["Valor Atual"] = disp_rebal["Valor Atual"].apply(brl)
    disp_rebal["Diferença"]   = rebal_df["Diferença"].apply(lambda x: f"+{brl(x)}" if x >= 0 else f"-{brl(abs(x))}")

    styled_rebal = style_map(disp_rebal.style, color_operacao, subset=["Operação"])
    st.dataframe(styled_rebal, hide_index=True, use_container_width=True)

    # Summary
    ops = rebal_df["Operação"].value_counts()
    n_comprar = ops.get("COMPRAR", 0)
    n_vender  = ops.get("VENDER", 0)
    n_manter  = ops.get("MANTER", 0)
    capital_compras = rebal_df[rebal_df["Operação"] == "COMPRAR"]["Diferença"].sum()
    capital_vendas  = abs(rebal_df[rebal_df["Operação"] == "VENDER"]["Diferença"].sum())
    saldo_liquido   = capital_compras - capital_vendas

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Compras", f"{n_comprar} ativos", delta=brl(capital_compras), delta_color="normal")
    c2.metric("Vendas", f"{n_vender} ativos", delta=f"-{brl(capital_vendas)}", delta_color="inverse")
    c3.metric("Manter", f"{n_manter} ativos")
    c4.metric(
        "Caixa necessário",
        brl(max(0, saldo_liquido)),
        delta="aporte extra" if saldo_liquido > 0 else "sobra de caixa",
        delta_color="inverse" if saldo_liquido > 0 else "normal",
    )

    # Drift chart
    st.divider()
    st.subheader("Drift por Ativo")
    fig_drift = px.bar(
        rebal_df.sort_values("Drift", ascending=True),
        x="Drift", y="Ticker", orientation="h",
        color="Operação",
        color_discrete_map={"COMPRAR": "#2ecc71", "VENDER": "#e74c3c", "MANTER": "#95a5a6"},
        labels={"Drift": "Desvio da Alocação Alvo", "Ticker": "Ativo"},
        height=520,
    )
    fig_drift.add_vline(
        x=drift_threshold, line_dash="dash", line_color="orange",
        annotation_text=f"Gatilho {pct(drift_threshold)}", annotation_position="top right",
    )
    fig_drift.update_layout(xaxis_tickformat=".1%")
    st.plotly_chart(fig_drift, use_container_width=True)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 8 — BLOOMBERG SCREENER
# ═══════════════════════════════════════════════════════════════════════════════
with tabs[7]:
    from datetime import datetime

    st.markdown(BLOOMBERG_CSS, unsafe_allow_html=True)

    now_str = datetime.now().strftime("%d %b %Y  %H:%M").upper()
    st.markdown(
        f'<div class="bb-bar">BLOOMBERG EQUITY SCREENER &nbsp;|&nbsp; '
        f'BRASIL &nbsp;|&nbsp; {len(PORTFOLIO)} ATIVOS &nbsp;|&nbsp; {now_str}</div>',
        unsafe_allow_html=True,
    )

    # ── Session state ──────────────────────────────────────────────────────────
    if "bb_fund_data" not in st.session_state:
        st.session_state.bb_fund_data = {}          # ticker → fundamentus dict
    if "bb_selected" not in st.session_state:
        st.session_state.bb_selected = PORTFOLIO[0]["ticker"]

    # ── Controls bar ───────────────────────────────────────────────────────────
    col_btn, col_sel, col_info = st.columns([2, 3, 3])

    with col_btn:
        load_btn = st.button(
            "⚡ Carregar dados Fundamentus",
            help="Busca P/L, P/VP, ROE, margens e mais para os 18 ativos (cache 1h)",
        )

    tickers_list = [a["ticker"] for a in PORTFOLIO]
    with col_sel:
        selected_ticker = st.selectbox(
            "Selecionar ativo para análise detalhada:",
            tickers_list,
            index=tickers_list.index(st.session_state.bb_selected),
            key="bb_sel_box",
        )
        st.session_state.bb_selected = selected_ticker

    loaded_count = len(st.session_state.bb_fund_data)
    with col_info:
        if loaded_count == 0:
            st.markdown(
                '<span style="color:#888; font-family:Courier New; font-size:11px">'
                '⚠ Dados Fundamentus não carregados — mostrando carteira local</span>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f'<span style="color:#00FF41; font-family:Courier New; font-size:11px">'
                f'✔ {loaded_count}/{len(PORTFOLIO)} ativos carregados do Fundamentus</span>',
                unsafe_allow_html=True,
            )

    # ── Load fundamentus data ──────────────────────────────────────────────────
    if load_btn:
        progress = st.progress(0, text="Conectando ao Fundamentus...")
        for idx, a in enumerate(PORTFOLIO):
            t = a["ticker"]
            progress.progress(
                (idx + 1) / len(PORTFOLIO),
                text=f"Buscando {t}... ({idx+1}/{len(PORTFOLIO)})",
            )
            if t not in st.session_state.bb_fund_data:
                st.session_state.bb_fund_data[t] = get_fundamentus_detalhes(t)
        progress.empty()
        st.rerun()

    # ── Screener table ─────────────────────────────────────────────────────────
    screener_df = build_screener_df(PORTFOLIO, st.session_state.bb_fund_data or None)
    st.markdown(
        build_screener_html(screener_df, st.session_state.bb_selected),
        unsafe_allow_html=True,
    )
    st.caption("Clique no ticker desejado no seletor acima para ver a análise detalhada.")

    st.divider()

    # ── Detail view ────────────────────────────────────────────────────────────
    asset_obj = next((a for a in PORTFOLIO if a["ticker"] == selected_ticker), PORTFOLIO[0])
    fund_data = st.session_state.bb_fund_data.get(selected_ticker, {})

    if "_error" in fund_data:
        st.warning(f"Erro ao buscar dados do Fundamentus para {selected_ticker}: {fund_data['_error']}")
        fund_data = {}

    if fund_data:
        st.markdown(
            build_detail_html(selected_ticker, fund_data, asset_obj),
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f'<div class="bb-terminal" style="padding:16px">'
            f'<span style="color:#888; font-family:Courier New; font-size:11px">'
            f'Carregue os dados do Fundamentus para ver os indicadores detalhados de '
            f'<strong style="color:#FF8C00">{selected_ticker}</strong>.'
            f'</span></div>',
            unsafe_allow_html=True,
        )

    # ── Price chart ────────────────────────────────────────────────────────────
    st.markdown(
        f'<div class="bb-bar" style="margin-top:12px">'
        f'HISTÓRICO DE COTAÇÃO &nbsp;|&nbsp; {selected_ticker} &nbsp;|&nbsp; 1 ANO &nbsp;|&nbsp; '
        f'MACD · RSI · BOLLINGER</div>',
        unsafe_allow_html=True,
    )

    with st.spinner(f"Buscando histórico de {selected_ticker}..."):
        hist_df = get_price_history(selected_ticker)

    if hist_df.empty:
        st.markdown(
            '<span style="color:#FF4444; font-family:Courier New; font-size:11px">'
            '⚠ Histórico de preços não disponível para este ativo.</span>',
            unsafe_allow_html=True,
        )
    else:
        hist_df = add_indicators(hist_df)
        fig_bb = build_bloomberg_chart(hist_df, selected_ticker)
        st.plotly_chart(fig_bb, use_container_width=True)
