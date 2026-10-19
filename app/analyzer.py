from typing import Dict, Any, List
import numpy as np
import pandas as pd
from app.config import AppConfig


def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi.fillna(50.0)


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"]
    low = df["low"]
    prev_close = df["close"].shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean().bfill()


def analyze_dollar(df: pd.DataFrame, spot: Dict[str, Any], cfg: AppConfig) -> Dict[str, Any]:
    """
    Executa a análise quantitativa completa de 4 pilares sobre o par USD/BRL.
    Retorna Score de 0 a 100, veredito, detalhamento dos indicadores,
    detector 'Anti-Faca Caindo', recomendação de lotes (DCA) e Simulador VET.
    """
    df = df.copy().reset_index(drop=True)
    close = df["close"]
    price = float(spot["price"])

    # --- 1. INDICADORES TÉCNICOS ---
    df["ema9"] = close.ewm(span=9, adjust=False).mean()
    df["sma20"] = close.rolling(20, min_periods=5).mean()
    df["sma50"] = close.rolling(50, min_periods=10).mean()
    df["sma90"] = close.rolling(90, min_periods=15).mean()

    std20 = close.rolling(20, min_periods=5).std().bfill()
    df["bb_mid"] = df["sma20"]
    df["bb_upper"] = df["bb_mid"] + 2.0 * std20
    df["bb_lower"] = df["bb_mid"] - 2.0 * std20

    df["rsi14"] = compute_rsi(close, 14)
    df["atr14"] = compute_atr(df, 14)

    # MACD (12, 26, 9)
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]

    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else last

    rsi = float(last["rsi14"])
    ema9 = float(last["ema9"])
    sma20 = float(last["sma20"])
    sma50 = float(last["sma50"])
    sma90 = float(last["sma90"])
    bb_upper = float(last["bb_upper"])
    bb_lower = float(last["bb_lower"])
    bb_width = max(bb_upper - bb_lower, 0.0001)
    bb_pct_b = (price - bb_lower) / bb_width  # 0.0 = na banda inferior, 1.0 = na superior

    atr = float(last["atr14"])
    atr_pct = (atr / price) * 100.0

    macd_val = float(last["macd"])
    macd_sig = float(last["macd_signal"])
    macd_hist = float(last["macd_hist"])
    macd_hist_prev = float(prev["macd_hist"])
    macd_hist_slope = macd_hist - macd_hist_prev

    # --- 2. ESTATÍSTICA HISTÓRICA (30d e 90d) ---
    w30 = close.tail(30)
    w90 = close.tail(90)

    mean30 = float(w30.mean())
    std30 = max(float(w30.std()), 0.005)
    min30 = float(w30.min())
    max30 = float(w30.max())
    zscore30 = (price - mean30) / std30
    # Percentil: % de dias em que o fechamento foi menor ou igual ao preço atual
    percentile30 = float((w30 <= price).mean() * 100.0)
    cheaper_than_30d_pct = round(100.0 - percentile30, 1)

    mean90 = float(w90.mean())
    std90 = max(float(w90.std()), 0.005)
    min90 = float(w90.min())
    max90 = float(w90.max())
    zscore90 = (price - mean90) / std90
    percentile90 = float((w90 <= price).mean() * 100.0)
    cheaper_than_90d_pct = round(100.0 - percentile90, 1)

    diff_sma20_pct = ((price - sma20) / sma20) * 100.0
    diff_sma50_pct = ((price - sma50) / sma50) * 100.0
    diff_sma90_pct = ((price - sma90) / sma90) * 100.0

    # --- 3. CÁLCULO DO SCORE DE COMPRA (0 a 100) ---
    # PILAR A: Estatística Histórica (máx 35 pts)
    # 1. Percentil 30d (0 a 12 pts) + Percentil 90d (0 a 10 pts)
    p30_pts = float(np.clip((100.0 - percentile30) / 100.0 * 12.0, 0.0, 12.0))
    p90_pts = float(np.clip((100.0 - percentile90) / 100.0 * 10.0, 0.0, 10.0))
    # 2. Z-Score combinado (0 a 13 pts): Z = 0 -> 4 pts, Z <= -2.0 -> 13 pts, Z >= +1.5 -> 0 pts
    z_combined = 0.6 * zscore30 + 0.4 * zscore90
    z_pts = float(np.clip((1.0 - z_combined) / 3.0 * 13.0, 0.0, 13.0))
    stat_score = round(p30_pts + p90_pts + z_pts, 1)  # 0..35

    # PILAR B: Indicadores Técnicos (máx 35 pts)
    # 1. RSI 14 (0 a 14 pts): RSI <= 28 -> 14 pts, RSI = 50 -> 6 pts, RSI >= 68 -> 0 pts
    rsi_pts = float(np.clip((68.0 - rsi) / 40.0 * 14.0, 0.0, 14.0))
    # 2. Posição nas Bandas de Bollinger %B (0 a 11 pts): %B <= 0 -> 11 pts, %B = 0.5 -> 5 pts, %B >= 1.0 -> 0 pts
    bb_pts = float(np.clip((1.0 - bb_pct_b) * 11.0, 0.0, 11.0))
    # 3. Desconto frente às Médias Móveis SMA20 e SMA50 (0 a 10 pts)
    ma_discount = -(0.6 * diff_sma20_pct + 0.4 * diff_sma50_pct)  # positivo quando preço < médias
    ma_pts = float(np.clip((ma_discount + 1.0) / 4.0 * 10.0, 0.0, 10.0))
    tech_score = round(rsi_pts + bb_pts + ma_pts, 1)  # 0..35

    # PILAR C: Tendência, Volatilidade & Anti-Faca Caindo (máx 20 pts)
    # Verifica proximidade do suporte de 30d/90d e comportamento do momentum (MACD)
    dist_from_min30_atr = (price - min30) / max(atr, 0.01)
    support_pts = float(np.clip((3.0 - dist_from_min30_atr) / 3.0 * 10.0, 0.0, 10.0))

    # Detector "Faca Caindo" vs "Fundo / Estabilização"
    is_falling_knife = (
        price < ema9
        and macd_hist < 0
        and macd_hist_slope < -0.0025
        and float(spot.get("pct_change", 0)) < -0.65
    )
    is_bottoming_out = (
        price < sma20
        and (macd_hist_slope >= 0 or rsi < 35)
        and not is_falling_knife
    )

    if is_bottoming_out:
        momentum_pts = 10.0
        knife_status = "ESTABILIZANDO / FUNDO PROVÁVEL"
        knife_advice = (
            "A pressão vendedora está perdendo força em região descontada. "
            "Excelente momento para entrar com a maior parte do capital (70% a 100%)."
        )
    elif is_falling_knife:
        momentum_pts = 6.0  # Desconta alguns pontos para alertar cautela de curto prazo
        knife_status = "FACA CAINDO (QUEDA FORTE EM CURSO)"
        knife_advice = (
            "O dólar está barato, mas ainda cai com força (momentum negativo acelerando). "
            "Para não comprar cedo demais caso caia mais, faça compra fracionada (DCA): "
            f"compre 50% agora (R$ {price:.4f}) e deixe 50% para buscar R$ {(price - 0.75 * atr):.4f}."
        )
    elif price < sma20:
        momentum_pts = 8.0
        knife_status = "TENDÊNCIA DE BAIXA MODERADA (FAVORÁVEL)"
        knife_advice = (
            "Cotação abaixo da média de 20 dias sem pânico extremo. "
            f"Sugestão: compre 60% agora e 40% se recuar até R$ {(price - 0.5 * atr):.4f}."
        )
    else:
        momentum_pts = float(np.clip(5.0 - diff_sma20_pct * 2.0, 0.0, 6.0))
        knife_status = "ACIMA DA MÉDIA CURTA (AGUARDAR RECUO)"
        knife_advice = (
            f"O dólar está operando acima da média de 20 dias (R$ {sma20:.4f}). "
            "Só compre agora se tiver urgência imediata de viagem."
        )

    trend_score = round(support_pts + momentum_pts, 1)  # 0..20

    # PILAR D: Economia Real no Bolso / Simulador VET (máx 10 pts)
    # Economia percentual em relação ao pico de 30 dias e média de 30 dias
    drop_from_max30_pct = ((max30 - price) / max30) * 100.0
    econ_pts = float(np.clip(drop_from_max30_pct / 4.5 * 10.0, 0.0, 10.0))
    econ_score = round(econ_pts, 1)

    total_score = int(round(np.clip(stat_score + tech_score + trend_score + econ_score, 0, 100)))

    # --- 4. SIMULADOR DE CUSTO EFETIVO TOTAL (VET) ---
    usd_amount = float(cfg.simulation_amount_usd)
    sp = cfg.spreads
    wise_live = spot.get("wise_live") or {}

    def calc_vet(base_rate: float, spread_pct: float, iof_pct: float) -> float:
        return base_rate * (1.0 + spread_pct / 100.0) * (1.0 + iof_pct / 100.0)

    # 1. Conta Global Padrão App (Taxa de conversão 2,0% + Encargos/IOF 3,5% -> idêntico ao print!)
    vet_global = calc_vet(price, sp.global_account_spread_pct, sp.global_account_iof_pct)

    # 2. Wise Oficial via PIX (API Tempo Real da Wise)
    wise_spread = float(wise_live.get("wise_spread_pct", getattr(sp, "wise_spread_pct", 1.22)))
    wise_iof = float(wise_live.get("wise_iof_pct", getattr(sp, "wise_iof_pct", 3.50)))
    vet_wise = float(wise_live.get("wise_vet_rate") or calc_vet(price, wise_spread, wise_iof))

    # 3. Conta Global Investimento (IOF 0,38%)
    inv_spread = getattr(sp, "investment_spread_pct", 1.50)
    vet_invest = calc_vet(price, inv_spread, sp.investment_iof_pct)

    # 4. Espécie e Cartão
    vet_cash = calc_vet(price, sp.cash_spread_pct, sp.cash_iof_pct)
    vet_card = calc_vet(price, sp.credit_card_spread_pct, sp.credit_card_iof_pct)

    vet_global_mean30 = calc_vet(mean30, sp.global_account_spread_pct, sp.global_account_iof_pct)
    vet_global_max30 = calc_vet(max30, sp.global_account_spread_pct, sp.global_account_iof_pct)

    total_brl_global = round(vet_global * usd_amount, 2)
    savings_vs_mean30_brl = round((vet_global_mean30 - vet_global) * usd_amount, 2)
    savings_vs_max30_brl = round((vet_global_max30 - vet_global) * usd_amount, 2)
    savings_global_vs_card_brl = round((vet_card - vet_global) * usd_amount, 2)

    # --- 5. CLASSIFICAÇÃO E RECOMENDAÇÃO FINAL ---
    target_hit = bool(cfg.target_price_brl and price <= cfg.target_price_brl)

    if total_score >= 80:
        verdict = "COMPRA EXCELENTE (OPORTUNIDADE RARA)"
        verdict_level = "strong_buy"
        verdict_emoji = "🟢🔥"
    elif total_score >= cfg.min_score_alert:
        verdict = "BOA COMPRA (COMPENSA COMPRAR)"
        verdict_level = "buy"
        verdict_emoji = "🟢✅"
    elif total_score >= 52:
        verdict = "NEUTRO / COMPRA PARCIAL (SÓ SE PRECISAR)"
        verdict_level = "neutral"
        verdict_emoji = "🟡⚖️"
    else:
        verdict = "CARO / AGUARDAR QUEDA"
        verdict_level = "wait"
        verdict_emoji = "🔴⏳"

    should_alert = (total_score >= cfg.min_score_alert) or target_hit

    # Motivos detalhados a favor e contra
    reasons_pro: List[str] = []
    reasons_con: List[str] = []

    if cheaper_than_30d_pct >= 65:
        reasons_pro.append(f"Mais barato que {cheaper_than_30d_pct:.0f}% dos últimos 30 dias")
    elif cheaper_than_30d_pct < 40:
        reasons_con.append(f"Mais caro que {100 - cheaper_than_30d_pct:.0f}% dos últimos 30 dias")

    if cheaper_than_90d_pct >= 65:
        reasons_pro.append(f"Mais barato que {cheaper_than_90d_pct:.0f}% dos últimos 90 dias")

    if zscore30 <= -1.0:
        reasons_pro.append(f"Z-Score 30d descontado ({zscore30:+.2f} desvios abaixo da média)")
    elif zscore30 >= 0.8:
        reasons_con.append(f"Z-Score 30d elevado ({zscore30:+.2f} desvios acima da média)")

    if rsi <= 35:
        reasons_pro.append(f"RSI(14) em {rsi:.1f} indica forte sobrevenda (preço esticado para baixo)")
    elif rsi <= 45:
        reasons_pro.append(f"RSI(14) em {rsi:.1f} mostra força vendedora predominante (favorável)")
    elif rsi >= 60:
        reasons_con.append(f"RSI(14) em {rsi:.1f} próximo de sobrecompra (evitar comprar no topo)")

    if bb_pct_b <= 0.20:
        reasons_pro.append(f"Preço encostando na Banda Inferior de Bollinger (R$ {bb_lower:.4f})")
    elif bb_pct_b >= 0.80:
        reasons_con.append(f"Preço próximo da Banda Superior de Bollinger (R$ {bb_upper:.4f})")

    if diff_sma20_pct < -0.3:
        reasons_pro.append(f"Abaixo da Média de 20 dias em {abs(diff_sma20_pct):.2f}% (média: R$ {sma20:.4f})")
    else:
        reasons_con.append(f"Acima da Média de 20 dias em {diff_sma20_pct:+.2f}% (média: R$ {sma20:.4f})")

    if savings_vs_mean30_brl > 0:
        reasons_pro.append(
            f"Economia imediata de R$ {savings_vs_mean30_brl:.2f} a cada US$ {usd_amount:,.0f} vs média do mês"
        )

    if target_hit:
        reasons_pro.append(
            f"Atingiu sua meta manual de preço (<= R$ {cfg.target_price_brl:.4f})!"
        )

    # Série histórica para o gráfico no Dashboard (últimos 90 dias)
    chart_df = df.tail(90)
    chart_data = []
    for _, row in chart_df.iterrows():
        chart_data.append(
            {
                "date": row["date"],
                "close": round(float(row["close"]), 4),
                "high": round(float(row["high"]), 4),
                "low": round(float(row["low"]), 4),
                "sma20": round(float(row["sma20"]), 4),
                "sma50": round(float(row["sma50"]), 4),
                "bb_upper": round(float(row["bb_upper"]), 4),
                "bb_lower": round(float(row["bb_lower"]), 4),
                "rsi14": round(float(row["rsi14"]), 1),
            }
        )

    return {
        "spot": spot,
        "score": {
            "total": total_score,
            "min_alert_threshold": cfg.min_score_alert,
            "should_alert": should_alert,
            "target_hit": target_hit,
            "verdict": verdict,
            "verdict_level": verdict_level,
            "verdict_emoji": verdict_emoji,
            "pillars": {
                "statistical": {"score": stat_score, "max": 35},
                "technical": {"score": tech_score, "max": 35},
                "trend_timing": {"score": trend_score, "max": 20},
                "real_economy": {"score": econ_score, "max": 10},
            },
        },
        "indicators": {
            "rsi14": round(rsi, 2),
            "bb_upper": round(bb_upper, 4),
            "bb_mid": round(sma20, 4),
            "bb_lower": round(bb_lower, 4),
            "bb_pct_b": round(bb_pct_b * 100.0, 1),
            "ema9": round(ema9, 4),
            "sma20": round(sma20, 4),
            "sma50": round(sma50, 4),
            "sma90": round(sma90, 4),
            "diff_sma20_pct": round(diff_sma20_pct, 2),
            "diff_sma50_pct": round(diff_sma50_pct, 2),
            "diff_sma90_pct": round(diff_sma90_pct, 2),
            "macd": round(macd_val, 4),
            "macd_signal": round(macd_sig, 4),
            "macd_hist": round(macd_hist, 4),
            "macd_hist_slope": round(macd_hist_slope, 4),
            "atr14": round(atr, 4),
            "atr_pct": round(atr_pct, 2),
        },
        "statistics": {
            "mean30": round(mean30, 4),
            "std30": round(std30, 4),
            "min30": round(min30, 4),
            "max30": round(max30, 4),
            "zscore30": round(zscore30, 2),
            "percentile30": round(percentile30, 1),
            "cheaper_than_30d_pct": cheaper_than_30d_pct,
            "mean90": round(mean90, 4),
            "std90": round(std90, 4),
            "min90": round(min90, 4),
            "max90": round(max90, 4),
            "zscore90": round(zscore90, 2),
            "percentile90": round(percentile90, 1),
            "cheaper_than_90d_pct": cheaper_than_90d_pct,
        },
        "timing": {
            "is_falling_knife": is_falling_knife,
            "is_bottoming_out": is_bottoming_out,
            "status": knife_status,
            "advice": knife_advice,
            "dca_tranche_1_price": round(price, 4),
            "dca_tranche_2_price": round(price - 0.65 * atr, 4),
            "support_30d": round(min30, 4),
            "resistance_30d": round(max30, 4),
        },
        "simulator": {
            "usd_amount": usd_amount,
            "options": [
                {
                    "id": "global_account",
                    "name": "Conta Global App (Taxa 2,0% + Encargos 3,5%)",
                    "spread_pct": sp.global_account_spread_pct,
                    "iof_pct": sp.global_account_iof_pct,
                    "tax_per_usd": round(vet_global - price, 4),
                    "vet_rate": round(vet_global, 4),
                    "total_brl": total_brl_global,
                    "usd_per_1000_brl": round(1000.0 / vet_global, 2),
                    "recommended": True,
                },
                {
                    "id": "wise_live",
                    "name": "Wise Oficial via PIX (API Tempo Real)",
                    "spread_pct": wise_spread,
                    "iof_pct": wise_iof,
                    "tax_per_usd": round(vet_wise - price, 4),
                    "vet_rate": round(vet_wise, 4),
                    "total_brl": round(vet_wise * usd_amount, 2),
                    "usd_per_1000_brl": round(1000.0 / vet_wise, 2),
                    "recommended": True,
                },
                {
                    "id": "global_invest",
                    "name": "Conta Global (Investimento - IOF 0,38%)",
                    "spread_pct": inv_spread,
                    "iof_pct": sp.investment_iof_pct,
                    "tax_per_usd": round(vet_invest - price, 4),
                    "vet_rate": round(vet_invest, 4),
                    "total_brl": round(vet_invest * usd_amount, 2),
                    "usd_per_1000_brl": round(1000.0 / vet_invest, 2),
                    "recommended": False,
                },
                {
                    "id": "cash",
                    "name": "Espécie (Casa de Câmbio)",
                    "spread_pct": sp.cash_spread_pct,
                    "iof_pct": sp.cash_iof_pct,
                    "tax_per_usd": round(vet_cash - price, 4),
                    "vet_rate": round(vet_cash, 4),
                    "total_brl": round(vet_cash * usd_amount, 2),
                    "usd_per_1000_brl": round(1000.0 / vet_cash, 2),
                    "recommended": False,
                },
                {
                    "id": "credit_card",
                    "name": "Cartão de Crédito Tradicional",
                    "spread_pct": sp.credit_card_spread_pct,
                    "iof_pct": sp.credit_card_iof_pct,
                    "tax_per_usd": round(vet_card - price, 4),
                    "vet_rate": round(vet_card, 4),
                    "total_brl": round(vet_card * usd_amount, 2),
                    "usd_per_1000_brl": round(1000.0 / vet_card, 2),
                    "recommended": False,
                },
            ],
            "savings_vs_mean30_brl": savings_vs_mean30_brl,
            "savings_vs_max30_brl": savings_vs_max30_brl,
            "savings_global_vs_card_brl": savings_global_vs_card_brl,
        },
        "reasons": {
            "pro": reasons_pro,
            "con": reasons_con,
        },
        "chart": chart_data,
    }
