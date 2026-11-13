"""
finance_core.py — núcleo de cálculo do app de investimentos.
Funções puras (sem I/O): fáceis de testar e de expor via FastAPI.
"""
from __future__ import annotations
from dataclasses import dataclass
from math import sqrt, log10

# ---------- Valuation ----------
def preco_teto_bazin(dividendos_12m_medios: float, dy_minimo: float = 0.06) -> float:
    """Preço teto = dividendo anual médio por ação / DY mínimo (6%)."""
    return dividendos_12m_medios / dy_minimo if dividendos_12m_medios > 0 else 0.0


def valor_intrinseco_graham(lpa: float, vpa: float) -> float:
    """VI = sqrt(22,5 x LPA x VPA). Inválido se LPA ou VPA <= 0."""
    return sqrt(22.5 * lpa * vpa) if lpa > 0 and vpa > 0 else 0.0


def margem_seguranca(preco: float, valor_justo: float) -> float:
    """% de desconto do preço atual frente ao valor justo (positivo = barato)."""
    return (valor_justo - preco) / valor_justo if valor_justo > 0 else 0.0


def cagr(inicial: float, final: float, anos: int) -> float:
    return (final / inicial) ** (1 / anos) - 1 if inicial > 0 and final > 0 else 0.0

# ---------- Score de risco (0 = baixo, 100 = alto) ----------
RISCO_SETORIAL = {"bancos": 35, "energia": 30, "petroleo": 70, "mineracao": 65,
                  "industria": 40, "varejo": 60, "saneamento": 35}

def score_risco(volatilidade_anual: float, volume_diario_brl: float,
                setor: str, governanca_nivel: str, div_liq_ebitda: float = 0) -> dict:
    """
    Pesos: volatilidade 35%, liquidez 20%, setor 20%, governança 15%, alavancagem 10%.
    governanca_nivel: 'novo_mercado' | 'n2' | 'n1' | 'tradicional'
    """
    vol = min(volatilidade_anual / 0.60, 1) * 100              # 60% a.a. = teto
    liq = max(0, min(100, (7 - log10(max(volume_diario_brl, 1))) * 50))  # R$10M/dia = 0
    setor_s = RISCO_SETORIAL.get(setor, 50)
    gov = {"novo_mercado": 10, "n2": 25, "n1": 45, "tradicional": 70}.get(governanca_nivel, 60)
    alav = min(max(div_liq_ebitda, 0) / 4, 1) * 100
    total = vol * .35 + liq * .20 + setor_s * .20 + gov * .15 + alav * .10
    faixa = "Baixo" if total < 35 else "Médio" if total < 60 else "Alto"
    return {"score": round(total, 1), "faixa": faixa}

# ---------- Suitability & alocação ----------
ALOCACAO_BASE = {  # Ações, FIIs, Renda Fixa, Exterior
    "conservador": {"acoes": 10, "fiis": 15, "renda_fixa": 65, "exterior": 10},
    "moderado":    {"acoes": 30, "fiis": 20, "renda_fixa": 35, "exterior": 15},
    "arrojado":    {"acoes": 45, "fiis": 20, "renda_fixa": 15, "exterior": 20},
}

def perfil_por_questionario(respostas: list[int]) -> str:
    """respostas: notas 1..4 por pergunta (tolerância, horizonte, experiência...)."""
    media = sum(respostas) / len(respostas)
    return "conservador" if media < 2 else "moderado" if media < 3 else "arrojado"

def alocacao_recomendada(perfil: str, objetivo: str) -> dict[str, float]:
    """Ajusta a base conforme objetivo: renda -> +FIIs; crescimento -> +ações."""
    a = dict(ALOCACAO_BASE[perfil])
    ajuste = {"renda": ("fiis", "exterior"), "crescimento": ("acoes", "renda_fixa")}.get(objetivo)
    if ajuste and a[ajuste[1]] >= 5:
        a[ajuste[0]] += 5; a[ajuste[1]] -= 5
    return a

# ---------- Rebalanceamento ----------
def rebalancear(posicoes: dict[str, float], alvo_pct: dict[str, float],
                aporte: float = 0, banda: float = 0.02) -> dict[str, float]:
    """
    posicoes: {classe: valor atual}. Retorna {classe: valor a comprar(+)/vender(-)}.
    Só age se o desvio passar da banda (evita giro desnecessário).
    """
    total = sum(posicoes.values()) + aporte
    ordens = {}
    for classe, pct in alvo_pct.items():
        ideal = total * pct / 100
        atual = posicoes.get(classe, 0)
        ordens[classe] = round(ideal - atual, 2) if abs(ideal - atual) / total > banda else 0.0
    return ordens

# ---------- Dividendos ----------
def aporte_mensal_bola_de_neve(renda_mensal_alvo: float, anos: int,
                               dy_anual: float = 0.07, valorizacao_anual: float = 0.04,
                               patrimonio_inicial: float = 0) -> float:
    """Aporte mensal necessário p/ atingir a renda alvo (dividendos reinvestidos)."""
    patrimonio_alvo = renda_mensal_alvo * 12 / dy_anual
    r = ((1 + dy_anual + valorizacao_anual) ** (1 / 12)) - 1   # retorno total mensal
    n = anos * 12
    fv_inicial = patrimonio_inicial * (1 + r) ** n
    return max(0.0, (patrimonio_alvo - fv_inicial) * r / ((1 + r) ** n - 1))

def payout(dividendos: float, lucro_liquido: float) -> float:
    return dividendos / lucro_liquido if lucro_liquido > 0 else float("inf")

# ---------- Alertas ----------
@dataclass
class Ativo:
    ticker: str; preco: float; dividendos_medios: float
    lpa: float; vpa: float; payout: float; risco: float

def gerar_alertas(a: Ativo) -> list[dict]:
    alertas = []
    teto = preco_teto_bazin(a.dividendos_medios)
    if teto and a.preco <= teto:
        alertas.append({"tipo": "oportunidade", "msg": f"{a.ticker} abaixo do Preço Teto de Bazin (R$ {teto:.2f})"})
    vi = valor_intrinseco_graham(a.lpa, a.vpa)
    if vi and a.preco <= vi * 0.7:
        alertas.append({"tipo": "oportunidade", "msg": f"{a.ticker} com 30%+ de margem sobre Graham (R$ {vi:.2f})"})
    if a.payout > 1:
        alertas.append({"tipo": "perigo", "msg": f"{a.ticker}: payout {a.payout:.0%} — risco de corte de dividendos"})
    if a.risco >= 60:
        alertas.append({"tipo": "perigo", "msg": f"{a.ticker}: score de risco alto ({a.risco})"})
    return alertas


if __name__ == "__main__":
    print(preco_teto_bazin(1.80), valor_intrinseco_graham(4.2, 22.0))
    print(alocacao_recomendada("moderado", "renda"))
    print(round(aporte_mensal_bola_de_neve(5000, 15), 2))
