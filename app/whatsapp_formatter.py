from datetime import datetime
from typing import Dict, Any
from app.config import AppConfig


def fmt_brl(val: float, decimals: int = 2) -> str:
    """Formata número no padrão brasileiro: R$ 5.156,60 ou R$ 5,0596."""
    formatted = f"{val:,.{decimals}f}"
    formatted = formatted.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"


def fmt_num(val: float, decimals: int = 2) -> str:
    formatted = f"{val:,.{decimals}f}"
    return formatted.replace(",", "X").replace(".", ",").replace("X", ".")


def format_whatsapp_report(
    analysis: Dict[str, Any],
    is_auto_alert: bool = False,
    overview: Dict[str, Dict[str, Any]] | None = None,
) -> str:
    """Formata a mensagem principal do !dolar (ou !euro) e dos alertas automáticos de queda."""
    spot = analysis["spot"]
    sc = analysis["score"]
    ind = analysis["indicators"]
    st = analysis["statistics"]
    tm = analysis["timing"]
    sim = analysis["simulator"]
    reasons = analysis["reasons"]

    cur_code = str(spot.get("currency", "USD")).upper()
    cur_name = spot.get("short_name", "Dólar")
    cur_sym = spot.get("symbol", "US$")
    cur_flag = spot.get("flag", "💵")
    decimals = int(analysis.get("decimals", 4))

    price = float(spot["price"])
    pct = float(spot["pct_change"])
    pct_sign = "+" if pct >= 0 else ""
    now_str = datetime.now().strftime("%d/%m/%Y às %H:%M")

    if is_auto_alert:
        header = f"📉🚨 *ALERTA: {cur_name.upper()} EM QUEDA AGORA!* 🚨📉"
    else:
        header = f"{cur_flag} *RAIO-X DO {cur_name.upper()} AGORA* {cur_flag}"

    opt_global = next((o for o in sim["options"] if o["id"] == "global_account"), sim["options"][0])
    opt_wise = next((o for o in sim["options"] if o["id"] == "wise_live"), sim["options"][0])
    opt_cash = next((o for o in sim["options"] if o["id"] == "cash"), sim["options"][-2])
    opt_card = next((o for o in sim["options"] if o["id"] == "credit_card"), sim["options"][-1])

    usd_amt = float(sim["usd_amount"])
    sav_mean = float(sim["savings_vs_mean30_brl"])
    sav_max = float(sim["savings_vs_max30_brl"])

    if sav_mean >= 0:
        sav_line = f"✅ *Economia hoje:* *{fmt_brl(sav_mean, 2)}* vs média do mês (e *{fmt_brl(sav_max, 2)}* vs topo)"
    else:
        sav_line = f"⚠️ *Acima da média:* *{fmt_brl(abs(sav_mean), 2)}* mais caro que a média de 30d"

    rsi_val = float(ind["rsi14"])
    if rsi_val < 38:
        rsi_tag = "Barato / Sobrevenda 🟢"
    elif rsi_val > 60:
        rsi_tag = "Caro / Sobrecompra 🔴"
    else:
        rsi_tag = "Neutro 🟡"

    pro_lines = "\n".join([f"✅ {r}" for r in reasons["pro"][:4]])
    con_lines = "\n".join([f"⚠️ {r}" for r in reasons["con"][:2]])

    lines = [
        header,
        f"🕒 _{now_str}_",
        "",
        f"🏷️ *{cur_name} Comercial:* *{fmt_brl(price, decimals)}* ({pct_sign}{fmt_num(pct, 2)}%)",
        f"🎯 *Nota de Compra:* *{sc['total']}/100*",
        f"{sc['verdict_emoji']} *{sc['verdict']}*",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "💳 *VALOR FINAL COM TAXAS (VET REAL)*",
        f"• 📱 *Conta Global (Taxa 2% + IOF 3,5%):* *{fmt_brl(opt_global['vet_rate'], decimals)}* _(Taxas: +{fmt_brl(opt_global['tax_per_usd'], decimals)}/{cur_sym})_",
        f"   ↳ R$ 1.000 compram *{cur_sym} {fmt_num(opt_global['usd_per_1000_brl'], 2)}* | {cur_sym} {fmt_num(usd_amt, 0)} = *{fmt_brl(opt_global['total_brl'], 2)}*",
        f"• 🌎 *Wise PIX (API Oficial):* *{fmt_brl(opt_wise['vet_rate'], decimals)}*",
        f"   ↳ R$ 1.000 compram *{cur_sym} {fmt_num(opt_wise['usd_per_1000_brl'], 2)}* | {cur_sym} {fmt_num(usd_amt, 0)} = *{fmt_brl(opt_wise['total_brl'], 2)}*",
        f"• 💵 *Espécie:* {fmt_brl(opt_cash['vet_rate'], decimals)} | 💳 *Cartão:* {fmt_brl(opt_card['vet_rate'], decimals)}",
        sav_line,
        "",
        "📊 *INDICADORES TÉCNICOS & HISTÓRICO*",
        f"• *Últimos 30d:* Mais barato que *{st['cheaper_than_30d_pct']:.0f}%* dos dias (Méd: {fmt_brl(st['mean30'], decimals)})",
        f"• *Últimos 90d:* Mais barato que *{st['cheaper_than_90d_pct']:.0f}%* dos dias (Méd: {fmt_brl(st['mean90'], decimals)})",
        f"• *Mínima 30d:* {fmt_brl(st['min30'], decimals)} | *Máxima 30d:* {fmt_brl(st['max30'], decimals)}",
        f"• *RSI (14):* {fmt_num(rsi_val, 1)} ({rsi_tag})",
        f"• *Bollinger:* {ind['bb_pct_b']:.0f}% da banda (Piso: {fmt_brl(ind['bb_lower'], decimals)})",
        f"• *Z-Score:* {st['zscore30']:+.2f}σ (30d) | {st['zscore90']:+.2f}σ (90d)",
        "",
        "🛡️ *TIMING (ANTI-FACA CAINDO)*",
        f"• *Momento:* *{tm['status']}*",
        f"• *Recomendação:* {tm['advice']}",
    ]

    if pro_lines or con_lines:
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append("🔍 *DESTAQUES DA ANÁLISE*")
        if pro_lines:
            lines.append(pro_lines)
        if con_lines:
            lines.append(con_lines)

    if overview and cur_code == "USD":
        eur_info = overview.get("EUR")
        ars_info = overview.get("ARS")
        if eur_info or ars_info:
            lines.append("━━━━━━━━━━━━━━━━━━━━")
            lines.append("🌍 *OUTRAS MOEDAS AGORA*")
            if eur_info:
                epct = float(eur_info["pct_change"])
                esign = "+" if epct >= 0 else ""
                lines.append(
                    f"• 🇪🇺 *Euro (EUR):* *{fmt_brl(eur_info['price'], 4)}* ({esign}{fmt_num(epct, 2)}%) | Wise: {fmt_brl(eur_info['vet_wise'], 4)}"
                )
            if ars_info:
                apct = float(ars_info["pct_change"])
                asign = "+" if apct >= 0 else ""
                lines.append(
                    f"• 🇦🇷 *Peso Arg (ARS):* *{fmt_brl(ars_info['price'], 4)}* ({asign}{fmt_num(apct, 2)}%) ➔ *R$ 1 = {fmt_num(ars_info['units_per_1_brl'], 0)} ARS* (1.000 ARS = {fmt_brl(ars_info['brl_per_1000_units'], 2)})"
                )

    lines.extend(
        [
            "",
            "💡 _Comandos:_ `!dolar` | `!euro` | `!peso` | `!moedas` | `!score` | `!simular R$ 1000` | `!ajuda`",
        ]
    )

    return "\n".join(lines)


def format_score_explanation(analysis: Dict[str, Any], cfg: AppConfig) -> str:
    """Explica detalhadamente o que é o !SCORE e como cada um dos 4 pilares está pontuando agora."""
    spot = analysis["spot"]
    sc = analysis["score"]
    p = sc["pillars"]
    st = analysis["statistics"]
    ind = analysis["indicators"]
    tm = analysis["timing"]

    price = float(spot["price"])

    lines = [
        "🧠 *COMO FUNCIONA O SCORE DE COMPRA (0 a 100)*",
        "",
        f"🏷️ *Dólar Agora:* *{fmt_brl(price, 4)}*",
        f"🎯 *Score Atual:* *{sc['total']}/100* — {sc['verdict_emoji']} *{sc['verdict']}*",
        f"🔔 *Seu Alerta Automático:* Dispara em *>= {cfg.min_score_alert}/100*",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "⚖️ *OS 4 PILARES DA NOTA DE HOJE:*",
        "",
        f"1️⃣ 📐 *Estatística Histórica: {fmt_num(p['statistical']['score'], 1)} / 35 pts*",
        "   _Compara o preço de hoje com os últimos 30 e 90 dias._",
        f"   • Percentil 30d: mais barato que *{st['cheaper_than_30d_pct']:.0f}%* dos dias",
        f"   • Percentil 90d: mais barato que *{st['cheaper_than_90d_pct']:.0f}%* dos dias",
        f"   • Z-Score (desvios da média): *{st['zscore30']:+.2f}σ* (30d) e *{st['zscore90']:+.2f}σ* (90d)",
        "",
        f"2️⃣ 📈 *Indicadores Técnicos: {fmt_num(p['technical']['score'], 1)} / 35 pts*",
        "   _Analisa força relativa, canal de volatilidade e médias._",
        f"   • RSI (14): *{fmt_num(ind['rsi14'], 1)}* (abaixo de 35 = sobrevenda forte)",
        f"   • Bollinger: posição em *{ind['bb_pct_b']:.0f}%* da banda (0% = piso da banda)",
        f"   • Desconto vs Média 20d: *{ind['diff_sma20_pct']:+.2f}%* (SMA20: {fmt_brl(ind['sma20'], 4)})",
        "",
        f"3️⃣ 🛡️ *Timing & Anti-Faca Caindo: {fmt_num(p['trend_timing']['score'], 1)} / 20 pts*",
        "   _Avalia pelo MACD e ATR se a queda já estabilizou no suporte ou se ainda cai livre._",
        f"   • Status atual: *{tm['status']}*",
        f"   • Distância p/ suporte 30d ({fmt_brl(st['min30'], 4)}): *{fmt_brl(price - st['min30'], 4)}*",
        "",
        f"4️⃣ 💰 *Economia Real no Bolso (VET): {fmt_num(p['real_economy']['score'], 1)} / 10 pts*",
        "   _Mede o desconto real já com IOF + Spread frente ao pico do mês._",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "🚦 *TABELA DE REFERÊNCIA DO SCORE:*",
        "• 🔴 *0 a 51 pts:* Caro / Acima da média (Aguardar queda)",
        "• 🟡 *52 a 71 pts:* Neutro / Compra Parcial (Só se precisar no curto prazo)",
        "• 🟢 *72 a 79 pts:* Boa Compra (Desconto estatístico e técnico confirmado)",
        "• 🔥 *80 a 100 pts:* Compra Excelente (Oportunidade rara de fundo)",
        "",
        "⚙️ *Quer mudar a nota mínima do alerta?*",
        "Envie por exemplo: `!score 75` (ou `!score 70`)",
    ]
    return "\n".join(lines)


def format_indicators_explanation(analysis: Dict[str, Any]) -> str:
    """Explica de forma didática cada indicador técnico e estatístico com os dados de hoje (!indicadores)."""
    spot = analysis["spot"]
    ind = analysis["indicators"]
    st = analysis["statistics"]
    price = float(spot["price"])

    rsi = float(ind["rsi14"])
    bb_pct = float(ind["bb_pct_b"])
    z30 = float(st["zscore30"])

    lines = [
        "📚 *GUIA DOS INDICADORES (DADOS DE HOJE)*",
        f"🏷️ *Dólar Comercial:* *{fmt_brl(price, 4)}*",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        f"1️⃣ *RSI 14 (Índice de Força Relativa): `{fmt_num(rsi, 1)}`*",
        "• *O que é:* Mede de 0 a 100 a velocidade das altas e quedas recentes.",
        "• *Como ler:* Abaixo de *35* significa que o dólar apanhou demais (sobrevenda = hora de comprar). Acima de *60* significa que subiu rápido demais (caro).",
        f"• *Hoje:* Está em *{fmt_num(rsi, 1)}* ({'Barato/Sobrevenda 🟢' if rsi < 38 else ('Caro/Sobrecompra 🔴' if rsi > 60 else 'Equilibrado/Neutro 🟡')}).",
        "",
        f"2️⃣ *Bandas de Bollinger (20, 2σ): `{bb_pct:.0f}%`*",
        "• *O que é:* Cria um túnel estatístico onde o preço permanece 95% do tempo.",
        f"• *Piso (Banda Inferior):* *{fmt_brl(ind['bb_lower'], 4)}* (Zona de compra forte)",
        f"• *Teto (Banda Superior):* *{fmt_brl(ind['bb_upper'], 4)}* (Zona cara)",
        f"• *Hoje:* O dólar está em *{bb_pct:.0f}%* do túnel (quanto mais perto de 0%, mais descontado).",
        "",
        f"3️⃣ *Z-Score (Desvio Padrão): `{z30:+.2f}σ` (30d) | `{st['zscore90']:+.2f}σ` (90d)*",
        "• *O que é:* Mede quantos desvios-padrão o dólar atual está abaixo ou acima da média.",
        "• *Como ler:* Valores negativos como *-1,0σ* a *-2,0σ* indicam promoção estatística rara.",
        "",
        "4️⃣ *Médias Móveis (Tendência)*",
        f"• *Curta (EMA 9d):* {fmt_brl(ind['ema9'], 4)}",
        f"• *Média (SMA 20d):* {fmt_brl(ind['sma20'], 4)} ({ind['diff_sma20_pct']:+.2f}%)",
        f"• *Longa (SMA 50d):* {fmt_brl(ind['sma50'], 4)} ({ind['diff_sma50_pct']:+.2f}%)",
        f"• *Trimestral (SMA 90d):* {fmt_brl(ind['sma90'], 4)} ({ind['diff_sma90_pct']:+.2f}%)",
        "",
        f"5️⃣ *ATR 14 (Volatilidade Diária): `{fmt_brl(ind['atr14'], 4)}` ({fmt_num(ind['atr_pct'], 2)}%)*",
        "• *O que é:* Quanto o dólar costuma oscilar por dia entre a mínima e a máxima. Usamos o ATR para calcular onde posicionar o seu 2º e 3º lote de compra!",
    ]
    return "\n".join(lines)


def format_history_report(analysis: Dict[str, Any]) -> str:
    """Mostra a análise estatística profunda de 30 e 90 dias (!historico)."""
    spot = analysis["spot"]
    st = analysis["statistics"]
    price = float(spot["price"])

    dist_min30 = price - float(st["min30"])
    dist_max30 = float(st["max30"]) - price

    lines = [
        "📅 *ESTATÍSTICA HISTÓRICA (30 E 90 DIAS)*",
        f"🏷️ *Dólar Hoje:* *{fmt_brl(price, 4)}*",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        "📆 *JANELA DE 30 DIAS (CURTO PRAZO)*",
        f"• *Mais barato que:* *{st['cheaper_than_30d_pct']:.0f}%* dos últimos 30 dias",
        f"• *Média 30d:* {fmt_brl(st['mean30'], 4)} _(Hoje: {fmt_brl(price - st['mean30'], 4)})_",
        f"• *Mínima 30d:* *{fmt_brl(st['min30'], 4)}* _(Faltam {fmt_brl(dist_min30, 4)} p/ mínima)_",
        f"• *Máxima 30d:* *{fmt_brl(st['max30'], 4)}* _(Caiu {fmt_brl(dist_max30, 4)} desde o topo)_",
        f"• *Z-Score 30d:* `{st['zscore30']:+.2f}σ`",
        "",
        "📆 *JANELA DE 90 DIAS (TRIMESTRE)*",
        f"• *Mais barato que:* *{st['cheaper_than_90d_pct']:.0f}%* dos últimos 90 dias",
        f"• *Média 90d:* {fmt_brl(st['mean90'], 4)} _(Hoje: {fmt_brl(price - st['mean90'], 4)})_",
        f"• *Mínima 90d:* *{fmt_brl(st['min90'], 4)}*",
        f"• *Máxima 90d:* *{fmt_brl(st['max90'], 4)}*",
        f"• *Z-Score 90d:* `{st['zscore90']:+.2f}σ`",
        "",
        "💡 *Conclusão Estatística:*",
        (
            f"✅ O preço atual ({fmt_brl(price, 4)}) está mais barato que a maioria dos dias do mês ({st['cheaper_than_30d_pct']:.0f}%) e do trimestre ({st['cheaper_than_90d_pct']:.0f}%)."
            if st["cheaper_than_30d_pct"] >= 50
            else f"⏳ O preço atual ({fmt_brl(price, 4)}) ainda está acima da mediana recente. A média dos últimos 30 dias é {fmt_brl(st['mean30'], 4)}."
        ),
    ]
    return "\n".join(lines)


def format_dca_strategy(analysis: Dict[str, Any], amount: float, is_brl: bool = False) -> str:
    """Calcula estratégia prática de compra em 3 Lotes (DCA) (!lotes / !dca)."""
    spot = analysis["spot"]
    sc = analysis["score"]
    ind = analysis["indicators"]
    st = analysis["statistics"]
    tm = analysis["timing"]
    sim = analysis["simulator"]

    price = float(spot["price"])
    atr = float(ind["atr14"])
    score_val = int(sc["total"])

    opt_global = next((o for o in sim["options"] if o["id"] == "global_account"), sim["options"][0])
    opt_wise = next((o for o in sim["options"] if o["id"] == "wise_live"), sim["options"][0])
    vet_mult = opt_global["vet_rate"] / price

    # Define os pesos dos 3 lotes com base no Score e no detector Anti-Faca Caindo
    if score_val >= 80 and not tm["is_falling_knife"]:
        w1, w2, w3 = 0.60, 0.25, 0.15
        profile = "AGRESSIVO (Preço muito descontado e estabilizando)"
    elif tm["is_falling_knife"]:
        w1, w2, w3 = 0.35, 0.35, 0.30
        profile = "CAUTELOSO / FACA CAINDO (Queda forte ainda em curso)"
    elif score_val >= 65:
        w1, w2, w3 = 0.50, 0.30, 0.20
        profile = "EQUILIBRADO (Região favorável de acumulação)"
    else:
        w1, w2, w3 = 0.25, 0.40, 0.35
        profile = "DEFENSIVO (Guardar maior parte p/ quedas)"

    target1 = price
    target2 = round(max(price - 0.65 * atr, st["min30"] - 0.01), 4)
    target3 = round(min(price - 1.25 * atr, st["min30"]), 4)

    unit_str = fmt_brl(amount, 2) if is_brl else f"US$ {fmt_num(amount, 2)}"
    val1 = amount * w1
    val2 = amount * w2
    val3 = amount * w3

    def fmt_chunk(v: float) -> str:
        return fmt_brl(v, 2) if is_brl else f"US$ {fmt_num(v, 0)}"

    lines = [
        f"📦 *PLANO DE COMPRA EM 3 LOTES (DCA)*",
        f"💰 *Capital Total:* *{unit_str}*",
        f"🏷️ *Dólar Comercial Agora:* *{fmt_brl(price, 4)}* (Score: *{score_val}/100*)",
        f"🧭 *Perfil Recomendado:* _{profile}_",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        f"1️⃣ *LOTE 1 — Entrada Imediata ({int(w1*100)}%)*",
        f"   • Valor: *{fmt_chunk(val1)}*",
        f"   • Cotação Comercial: *{fmt_brl(target1, 4)}*",
        f"   • VET Conta Global / Wise: *{fmt_brl(target1 * vet_mult, 4)}* / *{fmt_brl(opt_wise['vet_rate'], 4)}*",
        "",
        f"2️⃣ *LOTE 2 — Recuo Moderado ATR ({int(w2*100)}%)*",
        f"   • Valor: *{fmt_chunk(val2)}*",
        f"   • Alvo Comercial: *{fmt_brl(target2, 4)}* _(-{fmt_brl(price - target2, 4)})_",
        f"   • VET Estimado: *{fmt_brl(target2 * vet_mult, 4)}*",
        "",
        f"3️⃣ *LOTE 3 — Fundo / Suporte ({int(w3*100)}%)*",
        f"   • Valor: *{fmt_chunk(val3)}*",
        f"   • Alvo Comercial: *{fmt_brl(target3, 4)}* _(-{fmt_brl(price - target3, 4)})_",
        f"   • VET Estimado: *{fmt_brl(target3 * vet_mult, 4)}*",
        "━━━━━━━━━━━━━━━━━━━━",
        f"🎯 *Dica:* Envie `!meta {fmt_num(target2, 4)}` para o robô te avisar automaticamente assim que o dólar tocar o alvo do *Lote 2*!",
    ]
    return "\n".join(lines)


def format_wise_comparison(analysis: Dict[str, Any]) -> str:
    """Compara detalhadamente Wise Oficial (PIX) vs Conta Global App vs Investimento vs Espécie vs Cartão (!wise / !taxas)."""
    spot = analysis["spot"]
    sim = analysis["simulator"]
    price = float(spot["price"])

    opt_global = next((o for o in sim["options"] if o["id"] == "global_account"), sim["options"][0])
    opt_wise = next((o for o in sim["options"] if o["id"] == "wise_live"), sim["options"][0])
    opt_invest = next((o for o in sim["options"] if o["id"] == "global_invest"), sim["options"][1])
    opt_cash = next((o for o in sim["options"] if o["id"] == "cash"), sim["options"][-2])
    opt_card = next((o for o in sim["options"] if o["id"] == "credit_card"), sim["options"][-1])

    lines = [
        "🌎 *COMPARATIVO REAL DE TAXAS (VET)*",
        f"🏷️ *Dólar Comercial Base:* *{fmt_brl(price, 4)}*",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        "1️⃣ 🌎 *Wise Oficial via PIX (API Tempo Real)*",
        f"   • Taxa Wise ({fmt_num(opt_wise['spread_pct'], 2)}%) + IOF ({fmt_num(opt_wise['iof_pct'], 2)}%): *+{fmt_brl(opt_wise['tax_per_usd'], 4)}/US$*",
        f"   • *VET Final:* *{fmt_brl(opt_wise['vet_rate'], 4)}*",
        f"   • R$ 1.000 = *US$ {fmt_num(1000 / opt_wise['vet_rate'], 2)}* | R$ 5.000 = *US$ {fmt_num(5000 / opt_wise['vet_rate'], 2)}*",
        "",
        "2️⃣ 📱 *Conta Global App (Padrão Nomad/Nubank/Inter)*",
        f"   • Taxa ({fmt_num(opt_global['spread_pct'], 2)}%) + Encargos ({fmt_num(opt_global['iof_pct'], 2)}%): *+{fmt_brl(opt_global['tax_per_usd'], 4)}/US$*",
        f"   • *VET Final:* *{fmt_brl(opt_global['vet_rate'], 4)}*",
        f"   • R$ 1.000 = *US$ {fmt_num(1000 / opt_global['vet_rate'], 2)}* | R$ 5.000 = *US$ {fmt_num(5000 / opt_global['vet_rate'], 2)}*",
        "",
        "3️⃣ 📈 *Conta Global Investimento (IOF 0,38%)*",
        f"   • Taxa ({fmt_num(opt_invest['spread_pct'], 2)}%) + IOF ({fmt_num(opt_invest['iof_pct'], 2)}%): *+{fmt_brl(opt_invest['tax_per_usd'], 4)}/US$*",
        f"   • *VET Final:* *{fmt_brl(opt_invest['vet_rate'], 4)}*",
        f"   • R$ 1.000 = *US$ {fmt_num(1000 / opt_invest['vet_rate'], 2)}* | R$ 5.000 = *US$ {fmt_num(5000 / opt_invest['vet_rate'], 2)}*",
        "",
        "4️⃣ 💵 *Papel Moeda (Casa de Câmbio)*",
        f"   • *VET Final:* *{fmt_brl(opt_cash['vet_rate'], 4)}* ➔ R$ 1.000 = *US$ {fmt_num(1000 / opt_cash['vet_rate'], 2)}*",
        "",
        "5️⃣ 💳 *Cartão de Crédito Tradicional*",
        f"   • *VET Final:* *{fmt_brl(opt_card['vet_rate'], 4)}* ➔ R$ 1.000 = *US$ {fmt_num(1000 / opt_card['vet_rate'], 2)}*",
    ]
    return "\n".join(lines)


def format_trend_report(analysis: Dict[str, Any]) -> str:
    """Analisa tendência e detector de Faca Caindo (!tendencia / !faca)."""
    spot = analysis["spot"]
    ind = analysis["indicators"]
    tm = analysis["timing"]
    price = float(spot["price"])

    lines = [
        "🧭 *RADAR DE TENDÊNCIA & DETECTOR ANTI-FACA CAINDO*",
        f"🏷️ *Dólar Comercial:* *{fmt_brl(price, 4)}*",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        f"🛡️ *Diagnóstico Atual:* *{tm['status']}*",
        f"💬 _{tm['advice']}_",
        "",
        "📏 *POSIÇÃO FRENTE ÀS MÉDIAS MÓVEIS:*",
        f"• *Curto Prazo (EMA 9d - {fmt_brl(ind['ema9'], 4)}):* {'Abaixo (Queda curta) 🟢' if price < ind['ema9'] else 'Acima (Subindo no curto) 🔴'}",
        f"• *Médio Prazo (SMA 20d - {fmt_brl(ind['sma20'], 4)}):* {ind['diff_sma20_pct']:+.2f}% {'(Descontado 🟢)' if ind['diff_sma20_pct'] < 0 else '(Acima da média 🔴)'}",
        f"• *Longo Prazo (SMA 50d - {fmt_brl(ind['sma50'], 4)}):* {ind['diff_sma50_pct']:+.2f}%",
        f"• *Trimestral (SMA 90d - {fmt_brl(ind['sma90'], 4)}):* {ind['diff_sma90_pct']:+.2f}%",
        "",
        "⚡ *MOMENTUM (MACD 12, 26, 9):*",
        f"• *Histograma MACD:* `{ind['macd_hist']:+.4f}`",
        f"• *Inércia (Inclinação):* `{ind['macd_hist_slope']:+.4f}` ({'Força de venda desacelerando / Virando p/ alta' if ind['macd_hist_slope'] >= 0 else 'Pressão de baixa ganhando velocidade'})",
        "",
        "🧱 *SUPORTE E RESISTÊNCIA (30 DIAS):*",
        f"• *Piso / Suporte:* *{fmt_brl(tm['support_30d'], 4)}*",
        f"• *Teto / Resistência:* *{fmt_brl(tm['resistance_30d'], 4)}*",
    ]
    return "\n".join(lines)


def format_config_status(cfg: AppConfig, analysis: Dict[str, Any]) -> str:
    """Mostra as configurações atuais do robô (!config)."""
    st = analysis["statistics"]
    ind = analysis["indicators"]
    meta_str = fmt_brl(cfg.target_price_brl, 4) if cfg.target_price_brl else "Desativada (monitorando pelo Score e Queda)"
    status_str = "🟢 ATIVO" if cfg.auto_alert_enabled else "🔴 PAUSADO"
    drop_str = "🟢 ATIVADO (Só avisa quando cair)" if cfg.only_on_drop else "⚪ Desativado"

    lines = [
        "⚙️ *CONFIGURAÇÕES ATUAIS DO ROBÔ*",
        "━━━━━━━━━━━━━━━━━━━━",
        f"• *Monitoramento Automático:* *{status_str}*",
        f"• *Filtro Só em Queda:* *{drop_str}*",
        f"• *Grupo / Destino dos Alertas:* `{cfg.target_phone or 'bot de dolar'}`",
        f"• *Score Mínimo p/ Alerta:* *{cfg.min_score_alert}/100*",
        f"• *Meta Fixa de Preço:* *{meta_str}*",
        f"• *Valor Base de Simulação:* *US$ {fmt_num(cfg.simulation_amount_usd, 0)}*",
        f"• *Intervalo de Checagem:* a cada *{cfg.check_interval_minutes} min*",
        f"• *Cooldown Anti-Spam:* *{fmt_num(cfg.cooldown_hours, 1)} horas*",
        "",
        "💡 *Sugestões de Metas Técnicas Hoje:*",
        f"• Suporte de 30 dias: `{fmt_brl(st['min30'], 4)}` ➔ envie `!meta {fmt_num(st['min30'], 4)}`",
        f"• Banda Inferior Bollinger: `{fmt_brl(ind['bb_lower'], 4)}` ➔ envie `!meta {fmt_num(ind['bb_lower'], 4)}`",
        "",
        "🔧 *Como alterar pelo WhatsApp:*",
        "• `!score 75` | `!meta 5,00` | `!queda` | `!aqui` | `!pausar` | `!retomar`",
    ]
    return "\n".join(lines)


def format_peso_report(analysis: Dict[str, Any]) -> str:
    """Formata um Raio-X completo e prático para o Peso Argentino (ARS) (!peso / !ars)."""
    spot = analysis["spot"]
    sc = analysis["score"]
    ind = analysis["indicators"]
    st = analysis["statistics"]
    tm = analysis["timing"]
    sim = analysis["simulator"]

    price = float(spot["price"])
    pct = float(spot["pct_change"])
    pct_sign = "+" if pct >= 0 else ""
    now_str = datetime.now().strftime("%d/%m/%Y às %H:%M")

    opt_global = next((o for o in sim["options"] if o["id"] == "global_account"), sim["options"][0])
    opt_wise = next((o for o in sim["options"] if o["id"] == "wise_live"), sim["options"][0])

    vet_wise = float(opt_wise["vet_rate"])
    vet_global = float(opt_global["vet_rate"])

    ars_per_1_brl_com = 1.0 / price if price > 0 else 0
    ars_per_1_brl_wise = 1.0 / vet_wise if vet_wise > 0 else 0
    ars_per_100_brl_wise = 100.0 / vet_wise if vet_wise > 0 else 0
    ars_per_1000_brl_wise = 1000.0 / vet_wise if vet_wise > 0 else 0

    brl_1000_ars_com = price * 1000.0
    brl_10000_ars_wise = vet_wise * 10000.0
    brl_100000_ars_wise = vet_wise * 100000.0

    rsi_val = float(ind["rsi14"])
    rsi_tag = "Barato / Sobrevenda 🟢" if rsi_val < 38 else ("Caro / Sobrecompra 🔴" if rsi_val > 60 else "Neutro 🟡")

    lines = [
        "🇦🇷 *RAIO-X DO PESO ARGENTINO (ARS) AGORA* 🇦🇷",
        f"🕒 _{now_str}_",
        "",
        f"🏷️ *Cotação Unitária (1 ARS):* *{fmt_brl(price, 4)}* ({pct_sign}{fmt_num(pct, 2)}%)",
        f"📦 *Lote de 1.000 ARS (Comercial):* *{fmt_brl(brl_1000_ars_com, 2)}*",
        f"🎯 *Nota de Compra:* *{sc['total']}/100* — {sc['verdict_emoji']} *{sc['verdict']}*",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "🔄 *CONVERSÃO PRÁTICA (QUANTO VALE SEU REAL)*",
        f"• *R$ 1,00 Comercial:* vale *{fmt_num(ars_per_1_brl_com, 1)} ARS*",
        f"• *R$ 1,00 c/ Taxas (Wise):* vale *{fmt_num(ars_per_1_brl_wise, 1)} ARS*",
        f"• *R$ 100,00 na Wise:* compram *{fmt_num(ars_per_100_brl_wise, 0)} ARS*",
        f"• *R$ 1.000,00 na Wise:* compram *{fmt_num(ars_per_1000_brl_wise, 0)} ARS*",
        "",
        "💳 *QUANTO CUSTA COMPRAR PESOS (JÁ COM IOF + TAXAS)*",
        f"• *10.000 ARS:* *{fmt_brl(brl_10000_ars_wise, 2)}* (Wise) | *{fmt_brl(vet_global * 10000, 2)}* (Conta Global)",
        f"• *100.000 ARS:* *{fmt_brl(brl_100000_ars_wise, 2)}* (Wise) | *{fmt_brl(vet_global * 100000, 2)}* (Conta Global)",
        "",
        "📊 *HISTÓRICO E INDICADORES (ARS/BRL)*",
        f"• *Últimos 30d:* Mais barato que *{st['cheaper_than_30d_pct']:.0f}%* dos dias",
        f"• *Mínima 30d (1.000 ARS):* {fmt_brl(st['min30'] * 1000, 2)} | *Máxima 30d:* {fmt_brl(st['max30'] * 1000, 2)}",
        f"• *RSI (14):* {fmt_num(rsi_val, 1)} ({rsi_tag})",
        f"• *Bollinger:* {ind['bb_pct_b']:.0f}% da banda",
        f"• *Recomendação:* {tm['advice']}",
        "",
        "💡 _Comandos:_ `!dolar` | `!euro` | `!peso` | `!moedas`",
    ]
    return "\n".join(lines)


def format_currencies_overview_report(overview: Dict[str, Dict[str, Any]]) -> str:
    """Formata o painel comparativo das 3 moedas (!moedas / !cambio)."""
    now_str = datetime.now().strftime("%d/%m/%Y às %H:%M")
    usd = overview.get("USD", {})
    eur = overview.get("EUR", {})
    ars = overview.get("ARS", {})

    lines = [
        "🌍 *PAINEL DE MOEDAS EM TEMPO REAL* 🌍",
        f"🕒 _{now_str}_",
        "━━━━━━━━━━━━━━━━━━━━",
    ]

    if usd:
        upct = float(usd.get("pct_change", 0))
        usign = "+" if upct >= 0 else ""
        uarrow = "📉" if upct < 0 else "📈"
        lines.extend(
            [
                f"🇺🇸 *DÓLAR COMERCIAL (USD)* {uarrow}",
                f"• *Comercial:* *{fmt_brl(usd['price'], 4)}* ({usign}{fmt_num(upct, 2)}%)",
                f"• *VET Wise / Global:* *{fmt_brl(usd['vet_wise'], 4)}* / *{fmt_brl(usd['vet_global'], 4)}*",
                f"• *R$ 1.000 compram:* *US$ {fmt_num(1000.0 / usd['vet_wise'], 2)}* (Wise)",
                "",
            ]
        )

    if eur:
        epct = float(eur.get("pct_change", 0))
        esign = "+" if epct >= 0 else ""
        earrow = "📉" if epct < 0 else "📈"
        lines.extend(
            [
                f"🇪🇺 *EURO COMERCIAL (EUR)* {earrow}",
                f"• *Comercial:* *{fmt_brl(eur['price'], 4)}* ({esign}{fmt_num(epct, 2)}%)",
                f"• *VET Wise / Global:* *{fmt_brl(eur['vet_wise'], 4)}* / *{fmt_brl(eur['vet_global'], 4)}*",
                f"• *R$ 1.000 compram:* *€ {fmt_num(1000.0 / eur['vet_wise'], 2)}* (Wise)",
                "",
            ]
        )

    if ars:
        apct = float(ars.get("pct_change", 0))
        asign = "+" if apct >= 0 else ""
        aarrow = "📉" if apct < 0 else "📈"
        lines.extend(
            [
                f"🇦🇷 *PESO ARGENTINO (ARS)* {aarrow}",
                f"• *Comercial (1 ARS):* *{fmt_brl(ars['price'], 4)}* ({asign}{fmt_num(apct, 2)}%)",
                f"• *Lote 1.000 ARS:* *{fmt_brl(ars['brl_per_1000_units'], 2)}* (Comercial) | *{fmt_brl(ars['brl_per_1000_units_vet'], 2)}* (Wise)",
                f"• *R$ 1,00 vale:* *{fmt_num(ars['units_per_1_brl'], 1)} ARS* (Comercial) | *{fmt_num(ars['units_per_1_brl_vet'], 1)} ARS* (Wise)",
                f"• *R$ 1.000 compram:* *{fmt_num(1000.0 * ars['units_per_1_brl_vet'], 0)} ARS* (Wise)",
                "",
            ]
        )

    lines.extend(
        [
            "━━━━━━━━━━━━━━━━━━━━",
            "💡 _Para ver o Raio-X completo de cada moeda, envie:_ `!dolar`, `!euro` ou `!peso`",
        ]
    )
    return "\n".join(lines)


def format_update_release_note(overview: Dict[str, Dict[str, Any]]) -> str:
    """Formata a Nota Oficial de Atualização 2.0 e Novos Comandos para envio no WhatsApp."""
    usd = overview.get("USD", {})
    eur = overview.get("EUR", {})
    ars = overview.get("ARS", {})

    u_price = fmt_brl(float(usd.get("price", 0)), 4) if usd else "--"
    u_wise = fmt_brl(float(usd.get("vet_wise", 0)), 4) if usd else "--"
    e_price = fmt_brl(float(eur.get("price", 0)), 4) if eur else "--"
    e_wise = fmt_brl(float(eur.get("vet_wise", 0)), 4) if eur else "--"
    a_price = fmt_brl(float(ars.get("price", 0)), 4) if ars else "--"
    a_per_brl = fmt_num(float(ars.get("units_per_1_brl", 0)), 0) if ars else "--"
    a_1000 = fmt_brl(float(ars.get("brl_per_1000_units", 0)), 2) if ars else "--"

    lines = [
        "🚀 *NOTA DE ATUALIZAÇÃO — SMART DOLLAR BOT 2.0* 🚀",
        "━━━━━━━━━━━━━━━━━━━━",
        "O robô acabou de receber grandes melhorias! Confira as novidades já ativas:",
        "",
        "1️⃣ 🌍 *EURO (EUR) E PESO ARGENTINO (ARS) AO VIVO*",
        f"• 🇺🇸 *Dólar Comercial:* *{u_price}* _(Wise: {u_wise})_",
        f"• 🇪🇺 *Euro Comercial:* *{e_price}* _(Wise: {e_wise})_",
        f"• 🇦🇷 *Peso Argentino:* *{a_price}* ➔ *R$ 1,00 = {a_per_brl} ARS* _(1.000 ARS = {a_1000})_",
        "",
        "2️⃣ 📉 *ALERTA AUTOMÁTICO INTELIGENTE (SÓ EM QUEDA)*",
        "• Agora o monitoramento automático foi calibrado para *avisar somente quando o dólar registrar uma queda real*!",
        "• Se o dólar estiver subindo ou parado, ele não manda mensagem repetida.",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "🆕 *NOVOS COMANDOS DISPONÍVEIS NO GRUPO:*",
        "• `!euro` ou `!eur` ➔ Raio-X completo do *Euro* (Cotação, Wise, Conta Global, RSI, Bollinger e Score 0-100)",
        "• `!peso` ou `!ars` ➔ Raio-X do *Peso Argentino* (Quanto vale R$ 1 em Pesos, custo de 10.000 e 100.000 ARS com taxas e indicadores)",
        "• `!moedas` ou `!cambio` ➔ Painel comparando *Dólar, Euro e Peso Argentino* lado a lado",
        "• `!queda` ➔ Verifica ou ativa o filtro de avisar somente nas quedas",
        "",
        "📋 *TODOS OS COMANDOS DO BOT:*",
        "• *Cotações:* `!dolar` | `!euro` | `!peso` | `!moedas` | `!wise`",
        "• *Simulação:* `!simular 1000` | `!simular R$ 1000` | `!lotes 1000`",
        "• *Análise:* `!score` | `!indicadores` | `!historico` | `!tendencia`",
        "• *Controle:* `!meta` | `!queda` | `!config` | `!pausar` | `!retomar` | `!ajuda`",
        "",
        "💡 _Teste agora mesmo mandando_ `!moedas`, `!euro` _ou_ `!peso` _aqui no grupo!_",
    ]
    return "\n".join(lines)


def format_simulation_report(
    analysis: Dict[str, Any],
    amount: float,
    is_brl_input: bool = False,
) -> str:
    """
    Formata uma resposta dedicada para o comando !simular.
    Mostra tanto o padrão exato do app (Taxa 2,0% + Encargos 3,5%) quanto a API oficial da Wise.
    """
    spot = analysis["spot"]
    sc = analysis["score"]
    st = analysis["statistics"]
    tm = analysis["timing"]
    sim = analysis["simulator"]

    price = float(spot["price"])
    now_str = datetime.now().strftime("%d/%m/%Y às %H:%M")

    opt_global = next((o for o in sim["options"] if o["id"] == "global_account"), sim["options"][0])
    opt_wise = next((o for o in sim["options"] if o["id"] == "wise_live"), sim["options"][0])
    opt_invest = next((o for o in sim["options"] if o["id"] == "global_invest"), sim["options"][1])
    opt_cash = next((o for o in sim["options"] if o["id"] == "cash"), sim["options"][-2])
    opt_card = next((o for o in sim["options"] if o["id"] == "credit_card"), sim["options"][-1])

    if is_brl_input:
        brl_budget = amount
        usd_global = brl_budget / opt_global["vet_rate"]
        usd_wise = brl_budget / opt_wise["vet_rate"]
        usd_invest = brl_budget / opt_invest["vet_rate"]
        usd_cash = brl_budget / opt_cash["vet_rate"]
        usd_card = brl_budget / opt_card["vet_rate"]

        vet_mean30 = st["mean30"] * (1 + opt_global["spread_pct"] / 100) * (1 + opt_global["iof_pct"] / 100)
        usd_mean30 = brl_budget / vet_mean30
        diff_usd = usd_global - usd_mean30

        lines = [
            f"🧮 *SIMULADOR DE CÂMBIO ({fmt_brl(brl_budget, 2)})*",
            f"🕒 _{now_str}_",
            "",
            f"🏷️ *Dólar Comercial:* *{fmt_brl(price, 4)}*",
            f"📊 *Score Atual:* *{sc['total']}/100* — {sc['verdict_emoji']} _{sc['verdict']}_",
            "",
            "━━━━━━━━━━━━━━━━━━━━",
            f"💵 *QUANTOS DÓLARES VOCÊ ADICIONA COM {fmt_brl(brl_budget, 2)}?*",
            "",
            f"1️⃣ 📱 *Conta Global App (Encargos 3,5% + Taxa 2,0%)*",
            f"   • Taxas por dólar: *+{fmt_brl(opt_global['tax_per_usd'], 4)}*",
            f"   • Valor total (VET): *{fmt_brl(opt_global['vet_rate'], 4)}*",
            f"   • Você adiciona: *US$ {fmt_num(usd_global, 2)}*",
            "",
            f"2️⃣ 🌎 *Wise Oficial via PIX (API Tempo Real)*",
            f"   • Taxas por dólar: *+{fmt_brl(opt_wise['tax_per_usd'], 4)}*",
            f"   • Valor total (VET): *{fmt_brl(opt_wise['vet_rate'], 4)}*",
            f"   • Você adiciona: *US$ {fmt_num(usd_wise, 2)}*",
            "",
            f"3️⃣ 📈 *Conta Global Investimento (IOF 0,38%)*",
            f"   • Valor total (VET): {fmt_brl(opt_invest['vet_rate'], 4)} ➔ *US$ {fmt_num(usd_invest, 2)}*",
            "",
            f"4️⃣ 💵 *Espécie (Câmbio):* {fmt_brl(opt_cash['vet_rate'], 4)} ➔ *US$ {fmt_num(usd_cash, 2)}*",
            f"5️⃣ 💳 *Cartão de Crédito:* {fmt_brl(opt_card['vet_rate'], 4)} ➔ *US$ {fmt_num(usd_card, 2)}*",
            "━━━━━━━━━━━━━━━━━━━━",
            f"💰 *Ganho vs Média 30d:* {'+' if diff_usd >= 0 else ''}{fmt_num(diff_usd, 2)} dólares comprando hoje!",
            f"🛡️ *Estratégia:* {tm['advice']}",
        ]
        return "\n".join(lines)

    usd_amt = amount
    sav_mean = float(sim["savings_vs_mean30_brl"])
    sav_max = float(sim["savings_vs_max30_brl"])
    sav_card = float(sim["savings_global_vs_card_brl"])

    lines = [
        f"🧮 *SIMULADOR REAL: US$ {fmt_num(usd_amt, 2)}*",
        f"🕒 _{now_str}_",
        "",
        f"🏷️ *Dólar Comercial:* *{fmt_brl(price, 4)}*",
        f"📊 *Score Atual:* *{sc['total']}/100* — {sc['verdict_emoji']} _{sc['verdict']}_",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        f"💳 *CUSTO TOTAL PARA COMPRAR US$ {fmt_num(usd_amt, 0)} HOJE*",
        "",
        f"1️⃣ 📱 *Conta Global App (Encargos 3,5% + Taxa 2,0%)*",
        f"   • Taxas por dólar: *+{fmt_brl(opt_global['tax_per_usd'], 4)}*",
        f"   • Valor total (VET): *{fmt_brl(opt_global['vet_rate'], 4)}*",
        f"   • Total a pagar: *{fmt_brl(opt_global['total_brl'], 2)}*",
        f"   • _(Com R$ 1.000,00 você adiciona *US$ {fmt_num(opt_global['usd_per_1000_brl'], 2)}*)_",
        "",
        f"2️⃣ 🌎 *Wise Oficial via PIX (API Tempo Real)*",
        f"   • Spread {fmt_num(opt_wise['spread_pct'], 2)}% + IOF {fmt_num(opt_wise['iof_pct'], 2)}%",
        f"   • Valor total (VET): *{fmt_brl(opt_wise['vet_rate'], 4)}*",
        f"   • Total a pagar: *{fmt_brl(opt_wise['total_brl'], 2)}*",
        f"   • _(Com R$ 1.000,00 você adiciona *US$ {fmt_num(opt_wise['usd_per_1000_brl'], 2)}*)_",
        "",
        f"3️⃣ 📈 *Conta Global Investimento (IOF 0,38%)*",
        f"   • Valor total (VET): *{fmt_brl(opt_invest['vet_rate'], 4)}* ➔ *{fmt_brl(opt_invest['total_brl'], 2)}*",
        "",
        f"4️⃣ 💵 *Espécie (Câmbio):* *{fmt_brl(opt_cash['vet_rate'], 4)}* ➔ *{fmt_brl(opt_cash['total_brl'], 2)}*",
        f"5️⃣ 💳 *Cartão de Crédito:* *{fmt_brl(opt_card['vet_rate'], 4)}* ➔ *{fmt_brl(opt_card['total_brl'], 2)}*",
        "━━━━━━━━━━━━━━━━━━━━",
        "💰 *RESUMO DE ECONOMIA NO BOLSO*",
        f"• *Vs Média de 30 dias:* {'Economia de *' + fmt_brl(sav_mean, 2) + '* 🟢' if sav_mean >= 0 else fmt_brl(abs(sav_mean), 2) + ' mais caro que a média 🔴'}",
        f"• *Vs Topo de 30 dias:* Economia de *{fmt_brl(sav_max, 2)}*",
        f"• *Conta Global vs Cartão:* Economia de *{fmt_brl(sav_card, 2)}*",
        "",
        "💡 _Para simular R$ 1.000 igual ao seu print, envie:_ `!simular R$ 1000`",
    ]

    return "\n".join(lines)
