def brl(value: float) -> str:
    formatted = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"


def pct(value: float, decimals: int = 1) -> str:
    return f"{value * 100:.{decimals}f}%".replace(".", ",")


def color_risco(val: str) -> str:
    mapping = {
        "Baixo": "background-color: #d4edda; color: #155724",
        "Médio": "background-color: #fff3cd; color: #856404",
        "Alto":  "background-color: #f8d7da; color: #721c24",
    }
    return mapping.get(val, "")


def color_operacao(val: str) -> str:
    mapping = {
        "COMPRAR": "background-color: #d4edda; color: #155724; font-weight: bold",
        "VENDER":  "background-color: #f8d7da; color: #721c24; font-weight: bold",
        "MANTER":  "background-color: #e2e3e5; color: #383d41",
    }
    return mapping.get(val, "")


def nota_stars(nota: int) -> str:
    filled = "★" * nota
    empty  = "☆" * (10 - nota)
    return filled + empty


TRIB_LABEL = {
    "isento_pf":  "Isento PF",
    "jcp_15":     "JCP 15% fonte",
    "fii_isento": "Isento FII*",
}
