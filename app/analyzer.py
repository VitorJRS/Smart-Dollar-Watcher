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
    Executa a análise quantitativa completa de 4 pilares sobre o par (USD/BRL, EUR/BRL ou ARS/BRL).
    Retorna Score de 0 a 100, veredito, detalhamento dos indicadores,
    detector 'Anti-Faca Caindo', recomendação de lotes (DCA) e Simulador VET.
    """
    df = df.copy().reset_index(drop=True)
    close = df["close"]
    price = float(spot["price"])
    currency = str(spot.get("currency", "USD")).upper()
    decimals = 5 if currency == "ARS" else 4
    default_symbols = {"USD": "US$", "EUR": "€", "ARS": "ARS"}
    default_names = {"USD": "Dólar", "EUR": "Euro", "ARS": "Peso Argentino"}
    cur_symbol = spot.get("symbol") or default_symbols.get(currency, "US$")
    cur_name = spot.get("short_name") or default_names.get(currency, "Dólar")

    def _fmt_brl(val: float, dec: int = decimals) -> str:
        s = f"{val:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"R$ {s}"

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
    bb_width = max(bb_upper - bb_lower, price * 0.0001)
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
    std30 = max(float(w30.std()), price * 0.001)
    min30 = float(w30.min())
    max30 = float(w30.max())
    zscore30 = (price - mean30) / std30
    # Percentil: % de dias em que o fechamento foi menor ou igual ao preço atual
    percentile30 = float((w30 <= price).mean() * 100.0)
    cheaper_than_30d_pct = round(100.0 - percentile30, 1)

    mean90 = float(w90.mean())
    std90 = max(float(w90.std()), price * 0.001)
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
    p30_pts = float(np.clip((100.0 - percentile30) / 100.0 * 12.0, 0.0, 12.0))
    p90_pts = float(np.clip((100.0 - percentile90) / 100.0 * 10.0, 0.0, 10.0))
    z_combined = 0.6 * zscore30 + 0.4 * zscore90
    z_pts = float(np.clip((1.0 - z_combined) / 3.0 * 13.0, 0.0, 13.0))
    stat_score = round(p30_pts + p90_pts + z_pts, 1)  # 0..35

    # PILAR B: Indicadores Técnicos (máx 35 pts)
    rsi_pts = float(np.clip((68.0 - rsi) / 40.0 * 14.0, 0.0, 14.0))
    bb_pts = float(np.clip((1.0 - bb_pct_b) * 11.0, 0.0, 11.0))
    ma_discount = -(0.6 * diff_sma20_pct + 0.4 * diff_sma50_pct)
    ma_pts = float(np.clip((ma_discount + 1.0) / 4.0 * 10.0, 0.0, 10.0))
    tech_score = round(rsi_pts + bb_pts + ma_pts, 1)  # 0..35

    # PILAR C: Tendência, Volatilidade & Anti-Faca Caindo (máx 20 pts)
    dist_from_min30_atr = (price - min30) / max(atr, price * 0.001)
    support_pts = float(np.clip((3.0 - dist_from_min30_atr) / 3.0 * 10.0, 0.0, 10.0))

    # Detector "Faca Caindo" vs "Fundo / Estabilização"
    is_falling_knife = (
        price < ema9
        and macd_hist < 0
        and macd_hist_slope < -(price * 0.0004)
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
            f"A pressão vendedora no {cur_name} está perdendo força em região descontada. "
            "Excelente momento para entrar com a maior parte do capital (70% a 100%)."
        )
    elif is_falling_knife:
        momentum_pts = 6.0
        knife_status = "FACA CAINDO (QUEDA FORTE EM CURSO)"
        knife_advice = (
            f"O {cur_name} está barato, mas ainda cai com força (momentum negativo acelerando). "
            "Para não comprar cedo demais caso caia mais, faça compra fracionada (DCA): "
            f"compre 50% agora ({_fmt_brl(price)}) e deixe 50% para buscar {_fmt_brl(price - 0.75 * atr)}."
        )
    elif price < sma20:
        momentum_pts = 8.0
        knife_status = "TENDÊNCIA DE BAIXA MODERADA (FAVORÁVEL)"
        knife_advice = (
            f"Cotação do {cur_name} abaixo da média de 20 dias sem pânico extremo. "
            f"Sugestão: compre 60% agora e 40% se recuar até {_fmt_brl(price - 0.5 * atr)}."
        )
    else:
        momentum_pts = float(np.clip(5.0 - diff_sma20_pct * 2.0, 0.0, 6.0))
        knife_status = "ACIMA DA MÉDIA CURTA (AGUARDAR RECUO)"
        knife_advice = (
            f"O {cur_name} está operando acima da média de 20 dias ({_fmt_brl(sma20)}). "
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
    if currency == "ARS" and usd_amount == 1000.0:
        usd_amount = 100000.0
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
    target_hit = bool(currency == "USD" and cfg.target_price_brl and price <= cfg.target_price_brl)

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
        reasons_pro.append(f"Preço encostando na Banda Inferior de Bollinger ({_fmt_brl(bb_lower)})")
    elif bb_pct_b >= 0.80:
        reasons_con.append(f"Preço próximo da Banda Superior de Bollinger ({_fmt_brl(bb_upper)})")

    if diff_sma20_pct < -0.3:
        reasons_pro.append(f"Abaixo da Média de 20 dias em {abs(diff_sma20_pct):.2f}% (média: {_fmt_brl(sma20)})")
    else:
        reasons_con.append(f"Acima da Média de 20 dias em {diff_sma20_pct:+.2f}% (média: {_fmt_brl(sma20)})")

    if savings_vs_mean30_brl > 0:
        amt_str = f"{usd_amount:,.0f}".replace(",", ".")
        reasons_pro.append(
            f"Economia imediata de {_fmt_brl(savings_vs_mean30_brl, 2)} a cada {cur_symbol} {amt_str} vs média do mês"
        )

    if target_hit:
        reasons_pro.append(
            f"Atingiu sua meta manual de preço (<= {_fmt_brl(cfg.target_price_brl, 4)})!"
        )

    fine_decimals = 6 if currency == "ARS" else 4

    # Série histórica para o gráfico no Dashboard (últimos 90 dias)
    chart_df = df.tail(90)
    chart_data = []
    for _, row in chart_df.iterrows():
        chart_data.append(
            {
                "date": row["date"],
                "close": round(float(row["close"]), decimals),
                "high": round(float(row["high"]), decimals),
                "low": round(float(row["low"]), decimals),
                "sma20": round(float(row["sma20"]), decimals),
                "sma50": round(float(row["sma50"]), decimals),
                "bb_upper": round(float(row["bb_upper"]), decimals),
                "bb_lower": round(float(row["bb_lower"]), decimals),
                "rsi14": round(float(row["rsi14"]), 1),
            }
        )

    return {
        "currency": currency,
        "decimals": decimals,
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
            "bb_upper": round(bb_upper, decimals),
            "bb_mid": round(sma20, decimals),
            "bb_lower": round(bb_lower, decimals),
            "bb_pct_b": round(bb_pct_b * 100.0, 1),
            "ema9": round(ema9, decimals),
            "sma20": round(sma20, decimals),
            "sma50": round(sma50, decimals),
            "sma90": round(sma90, decimals),
            "diff_sma20_pct": round(diff_sma20_pct, 2),
            "diff_sma50_pct": round(diff_sma50_pct, 2),
            "diff_sma90_pct": round(diff_sma90_pct, 2),
            "macd": round(macd_val, fine_decimals),
            "macd_signal": round(macd_sig, fine_decimals),
            "macd_hist": round(macd_hist, fine_decimals),
            "macd_hist_slope": round(macd_hist_slope, fine_decimals),
            "atr14": round(atr, fine_decimals),
            "atr_pct": round(atr_pct, 2),
        },
        "statistics": {
            "mean30": round(mean30, decimals),
            "std30": round(std30, decimals),
            "min30": round(min30, decimals),
            "max30": round(max30, decimals),
            "zscore30": round(zscore30, 2),
            "percentile30": round(percentile30, 1),
            "cheaper_than_30d_pct": cheaper_than_30d_pct,
            "mean90": round(mean90, decimals),
            "std90": round(std90, decimals),
            "min90": round(min90, decimals),
            "max90": round(max90, decimals),
            "zscore90": round(zscore90, 2),
            "percentile90": round(percentile90, 1),
            "cheaper_than_90d_pct": cheaper_than_90d_pct,
        },
        "timing": {
            "is_falling_knife": is_falling_knife,
            "is_bottoming_out": is_bottoming_out,
            "status": knife_status,
            "advice": knife_advice,
            "dca_tranche_1_price": round(price, decimals),
            "dca_tranche_2_price": round(price - 0.65 * atr, decimals),
            "support_30d": round(min30, decimals),
            "resistance_30d": round(max30, decimals),
        },
        "simulator": {
            "currency": currency,
            "symbol": cur_symbol,
            "usd_amount": usd_amount,
            "options": [
                {
                    "id": "global_account",
                    "name": "Conta Global App (Taxa 2,0% + Encargos 3,5%)",
                    "spread_pct": sp.global_account_spread_pct,
                    "iof_pct": sp.global_account_iof_pct,
                    "tax_per_usd": round(vet_global - price, fine_decimals),
                    "vet_rate": round(vet_global, decimals),
                    "total_brl": total_brl_global,
                    "usd_per_1000_brl": round(1000.0 / vet_global, 2),
                    "recommended": True,
                },
                {
                    "id": "wise_live",
                    "name": "Wise Oficial via PIX (API Tempo Real)",
                    "spread_pct": wise_spread,
                    "iof_pct": wise_iof,
                    "tax_per_usd": round(vet_wise - price, fine_decimals),
                    "vet_rate": round(vet_wise, decimals),
                    "total_brl": round(vet_wise * usd_amount, 2),
                    "usd_per_1000_brl": round(1000.0 / vet_wise, 2),
                    "recommended": True,
                },
                {
                    "id": "global_invest",
                    "name": "Conta Global (Investimento - IOF 0,38%)",
                    "spread_pct": inv_spread,
                    "iof_pct": sp.investment_iof_pct,
                    "tax_per_usd": round(vet_invest - price, fine_decimals),
                    "vet_rate": round(vet_invest, decimals),
                    "total_brl": round(vet_invest * usd_amount, 2),
                    "usd_per_1000_brl": round(1000.0 / vet_invest, 2),
                    "recommended": False,
                },
                {
                    "id": "cash",
                    "name": "Espécie (Casa de Câmbio)",
                    "spread_pct": sp.cash_spread_pct,
                    "iof_pct": sp.cash_iof_pct,
                    "tax_per_usd": round(vet_cash - price, fine_decimals),
                    "vet_rate": round(vet_cash, decimals),
                    "total_brl": round(vet_cash * usd_amount, 2),
                    "usd_per_1000_brl": round(1000.0 / vet_cash, 2),
                    "recommended": False,
                },
                {
                    "id": "credit_card",
                    "name": "Cartão de Crédito Tradicional",
                    "spread_pct": sp.credit_card_spread_pct,
                    "iof_pct": sp.credit_card_iof_pct,
                    "tax_per_usd": round(vet_card - price, fine_decimals),
                    "vet_rate": round(vet_card, decimals),
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
