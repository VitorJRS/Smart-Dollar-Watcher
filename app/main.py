import asyncio
import os
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import (
    AppConfig,
    load_config,
    save_config,
    load_alerts_history,
    append_alert_history,
    backup_wa_auth_to_db,
    restore_wa_auth_from_db,
    clear_wa_auth_from_db,
    BASE_DIR,
)
from app.db import is_postgres_enabled
from app.market_data import (
    fetch_spot_quote,
    fetch_historical_ohlc,
    fetch_currencies_overview,
    normalize_currency,
)
from app.analyzer import analyze_dollar
from app.whatsapp_formatter import (
    format_whatsapp_report,
    format_simulation_report,
    format_score_explanation,
    format_indicators_explanation,
    format_history_report,
    format_dca_strategy,
    format_wise_comparison,
    format_trend_report,
    format_config_status,
    format_peso_report,
    format_currencies_overview_report,
    fmt_brl,
    fmt_num,
)

WA_BRIDGE_URL = "http://127.0.0.1:3001"
_bridge_process: Optional[subprocess.Popen] = None
_bridge_last_spawn_ts: float = 0.0
_last_wa_db_backup_ts: float = 0.0
_monitor_task: Optional[asyncio.Task] = None

# Estado de controle anti-spam de alertas automáticos
_ALERT_STATE: Dict[str, Any] = {
    "last_alert_ts": 0.0,
    "last_alert_price": None,
    "last_alert_score": None,
    "prev_check_price": None,
    "last_check_ts": None,
    "last_analysis": None,
}


async def is_wa_bridge_up() -> bool:
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{WA_BRIDGE_URL}/status")
            return r.status_code == 200
    except Exception:
        return False


async def ensure_wa_bridge_started():
    global _bridge_process, _bridge_last_spawn_ts
    if await is_wa_bridge_up():
        return
    now = time.time()
    if now - _bridge_last_spawn_ts < 8.0:
        return
    bridge_dir = BASE_DIR / "whatsapp-bridge"
    index_js = bridge_dir / "index.js"
    if index_js.exists() and (_bridge_process is None or _bridge_process.poll() is not None):
        try:
            # Restaura a sessão do WhatsApp salva no PostgreSQL antes de iniciar o Node Bridge
            restore_wa_auth_from_db()
            _bridge_last_spawn_ts = now
            _bridge_process = subprocess.Popen(
                ["node", "index.js"],
                cwd=str(bridge_dir),
            )
        except Exception as e:
            print(f"[Aviso] Não foi possível iniciar a ponte Node automaticamente: {e}")


async def send_whatsapp_message(message: str, phone: Optional[str] = None) -> Dict[str, Any]:
    cfg = load_config()
    target_phone = phone if phone is not None else cfg.target_phone
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{WA_BRIDGE_URL}/send",
            json={"phone": target_phone, "message": message},
        )
        data = resp.json()
        if resp.status_code != 200 or not data.get("ok"):
            raise RuntimeError(data.get("error", "Erro ao enviar mensagem via WhatsApp."))
        return data


def is_within_market_hours() -> bool:
    now = datetime.now()
    if now.weekday() >= 5:  # Sábado (5) ou Domingo (6)
        return False
    return 8 <= now.hour < 19


async def evaluate_and_maybe_alert(force_refresh: bool = False) -> Dict[str, Any]:
    cfg = load_config()
    df = await fetch_historical_ohlc(days=180, force=force_refresh, currency="USD")
    spot = await fetch_spot_quote(force=force_refresh, currency="USD")
    analysis = analyze_dollar(df, spot, cfg)

    current_price = float(spot["price"])
    pct_change = float(spot.get("pct_change", 0.0))
    prev_check_price = _ALERT_STATE.get("prev_check_price")
    _ALERT_STATE["prev_check_price"] = current_price
    _ALERT_STATE["last_check_ts"] = datetime.now().isoformat()
    _ALERT_STATE["last_analysis"] = analysis

    if not cfg.auto_alert_enabled:
        return analysis

    if cfg.only_market_hours and not is_within_market_hours():
        return analysis

    # Verifica se o dólar registrou queda (no dia ou em relação à checagem anterior)
    dropped_vs_prev_check = (
        prev_check_price is not None and (prev_check_price - current_price) >= 0.004
    )
    is_dropping = (pct_change <= -0.05) or dropped_vs_prev_check

    if cfg.only_on_drop and not is_dropping:
        return analysis

    should_alert = analysis["score"]["should_alert"] or (
        cfg.only_on_drop and (pct_change <= -0.20 or (prev_check_price is not None and (prev_check_price - current_price) >= 0.015))
    )
    if not should_alert:
        return analysis

    now_ts = time.time()
    cooldown_sec = cfg.cooldown_hours * 3600.0
    elapsed = now_ts - float(_ALERT_STATE["last_alert_ts"] or 0.0)
    last_price = _ALERT_STATE["last_alert_price"]

    # Envia se:
    # 1) Ainda não enviou alerta ou já passou o cooldown (desde que esteja caindo / abaixo ou igual ao último alerta)
    # 2) OU se o dólar caiu mais pelo menos R$ 0,015 desde o último alerta enviado
    significant_extra_drop = (
        last_price is not None and (last_price - current_price) >= 0.015
    )
    cooldown_ok = elapsed >= cooldown_sec and (
        last_price is None or current_price <= last_price or not cfg.only_on_drop
    )

    if cooldown_ok or significant_extra_drop:
        try:
            wa_status = await get_wa_status_internal()
            if wa_status.get("status") == "connected":
                overview = await fetch_currencies_overview(force=False)
                report_msg = format_whatsapp_report(
                    analysis, is_auto_alert=True, overview=overview
                )
                send_res = await send_whatsapp_message(report_msg)
                _ALERT_STATE["last_alert_ts"] = now_ts
                _ALERT_STATE["last_alert_price"] = current_price
                _ALERT_STATE["last_alert_score"] = analysis["score"]["total"]

                append_alert_history(
                    {
                        "timestamp": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                        "type": "QUEDA AUTO" if cfg.only_on_drop else "AUTO",
                        "price": current_price,
                        "score": analysis["score"]["total"],
                        "verdict": f"Queda ({pct_change:+.2f}%) • {analysis['score']['verdict']}",
                        "target": send_res.get("target", "WhatsApp"),
                    }
                )
        except Exception as e:
            print(f"[Monitor] Aviso ao tentar enviar alerta automático: {e}")

    return analysis


async def background_monitor_loop():
    await asyncio.sleep(3)
    while True:
        try:
            await ensure_wa_bridge_started()
            await evaluate_and_maybe_alert(force_refresh=True)
        except Exception as e:
            print(f"[Monitor Loop] Erro na checagem: {e}")

        cfg = load_config()
        wait_seconds = max(int(cfg.check_interval_minutes * 60), 60)
        await asyncio.sleep(wait_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _monitor_task, _bridge_process
    await ensure_wa_bridge_started()
    _monitor_task = asyncio.create_task(background_monitor_loop())
    yield
    if _monitor_task:
        _monitor_task.cancel()
    if _bridge_process and _bridge_process.poll() is None:
        _bridge_process.terminate()


app = FastAPI(
    title="Smart Dollar Watcher - Motor Quantitativo & Bot WhatsApp",
    lifespan=lifespan,
)

STATIC_DIR = BASE_DIR / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


_WA_STATUS_CACHE: Dict[str, Any] = {
    "status": None,
    "user_phone": None,
    "user_name": None,
}


def _read_disk_wa_creds() -> Optional[Dict[str, Any]]:
    import json
    creds_path = BASE_DIR / "whatsapp-bridge" / "auth_info_baileys" / "creds.json"
    if creds_path.exists():
        try:
            raw = json.loads(creds_path.read_text(encoding="utf-8"))
            me = raw.get("me") or {}
            jid = me.get("id", "")
            if jid:
                bare = jid.split(":")[0].split("@")[0]
                return {
                    "status": "connected",
                    "qr_data_url": None,
                    "user_phone": bare,
                    "user_name": me.get("name"),
                }
        except Exception:
            pass
    return None


async def get_wa_status_internal() -> Dict[str, Any]:
    global _last_wa_db_backup_ts
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{WA_BRIDGE_URL}/status")
            if r.status_code == 200:
                data = r.json()
                if data.get("status") == "connected":
                    _WA_STATUS_CACHE["status"] = "connected"
                    _WA_STATUS_CACHE["user_phone"] = data.get("user_phone")
                    _WA_STATUS_CACHE["user_name"] = data.get("user_name")
                    now = time.time()
                    if now - _last_wa_db_backup_ts > 180.0:
                        _last_wa_db_backup_ts = now
                        backup_wa_auth_to_db()
                    return data
                if data.get("status") == "qr_ready":
                    _WA_STATUS_CACHE["status"] = "qr_ready"
                    return data
                # Se estiver oscilando ("connecting"), usa o cache de sessão conectada
                if _WA_STATUS_CACHE.get("status") == "connected":
                    return {
                        "status": "connected",
                        "qr_data_url": None,
                        "user_phone": _WA_STATUS_CACHE.get("user_phone"),
                        "user_name": _WA_STATUS_CACHE.get("user_name"),
                    }
                disk_cached = _read_disk_wa_creds()
                if disk_cached:
                    return disk_cached
                return data
    except Exception:
        pass

    if _WA_STATUS_CACHE.get("status") == "connected":
        return {
            "status": "connected",
            "qr_data_url": None,
            "user_phone": _WA_STATUS_CACHE.get("user_phone"),
            "user_name": _WA_STATUS_CACHE.get("user_name"),
        }

    disk_cached = _read_disk_wa_creds()
    if disk_cached:
        return disk_cached

    return {
        "status": "bridge_offline",
        "qr_data_url": None,
        "user_phone": None,
        "user_name": None,
    }


@app.get("/")
async def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/health")
async def health_check():
    await ensure_wa_bridge_started()
    return {
        "status": "ok",
        "database": "PostgreSQL" if is_postgres_enabled() else "Local JSON",
        "last_check_ts": _ALERT_STATE.get("last_check_ts"),
    }


@app.post("/api/internal/wa-backup")
async def api_internal_wa_backup():
    global _last_wa_db_backup_ts
    _last_wa_db_backup_ts = time.time()
    backup_wa_auth_to_db()
    return {"ok": True}


@app.get("/api/analysis")
async def api_get_analysis(
    force: bool = False,
    usd_amount: Optional[float] = None,
    currency: str = "USD",
):
    cur = normalize_currency(currency)
    cfg = load_config()
    if usd_amount is not None and usd_amount > 0:
        cfg.simulation_amount_usd = usd_amount
    df = await fetch_historical_ohlc(days=180, force=force, currency=cur)
    spot = await fetch_spot_quote(force=force, currency=cur)
    analysis = analyze_dollar(df, spot, cfg)
    currencies = await fetch_currencies_overview(force=force)
    if cur == "USD":
        _ALERT_STATE["last_analysis"] = analysis
    _ALERT_STATE["last_check_ts"] = datetime.now().isoformat()
    return {
        "currency": cur,
        "analysis": analysis,
        "currencies": currencies,
        "config": cfg.model_dump(),
        "history": load_alerts_history()[:15],
        "database": "PostgreSQL (Render)" if is_postgres_enabled() else "Local JSON",
        "last_check_ts": _ALERT_STATE["last_check_ts"],
    }


@app.get("/api/config")
async def api_get_config():
    return load_config().model_dump()


@app.post("/api/config")
async def api_save_config(new_cfg: AppConfig):
    saved = save_config(new_cfg)
    return {"ok": True, "config": saved.model_dump()}


@app.get("/api/whatsapp/status")
async def api_wa_status():
    await ensure_wa_bridge_started()
    return await get_wa_status_internal()


@app.get("/api/whatsapp/groups")
async def api_wa_groups():
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(f"{WA_BRIDGE_URL}/groups")
            if r.status_code == 200:
                return r.json()
    except Exception:
        pass
    return {"ok": False, "groups": []}


@app.post("/api/whatsapp/logout")
async def api_wa_logout():
    _WA_STATUS_CACHE["status"] = None
    _WA_STATUS_CACHE["user_phone"] = None
    _WA_STATUS_CACHE["user_name"] = None
    clear_wa_auth_from_db()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.post(f"{WA_BRIDGE_URL}/logout")
            return r.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class TestAlertRequest(BaseModel):
    phone: Optional[str] = None
    currency: Optional[str] = "USD"


@app.post("/api/whatsapp/send-now")
async def api_wa_send_now(req: TestAlertRequest):
    cur = normalize_currency(req.currency)
    cfg = load_config()
    df = await fetch_historical_ohlc(days=180, force=False, currency=cur)
    spot = await fetch_spot_quote(force=True, currency=cur)
    analysis = analyze_dollar(df, spot, cfg)
    if cur == "ARS":
        msg = format_peso_report(analysis)
    else:
        overview = await fetch_currencies_overview(force=False) if cur == "USD" else None
        msg = format_whatsapp_report(analysis, is_auto_alert=False, overview=overview)
    try:
        res = await send_whatsapp_message(msg, phone=req.phone)
        append_alert_history(
            {
                "timestamp": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                "type": f"MANUAL ({cur})",
                "price": spot["price"],
                "score": analysis["score"]["total"],
                "verdict": analysis["score"]["verdict"],
                "target": res.get("target", "WhatsApp"),
            }
        )
        return {"ok": True, "target": res.get("target")}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


def parse_smart_number(raw: str) -> float:
    """
    Converte números digitados em formato BR ou US:
    - '1.000' -> 1000.0
    - '1.500,50' -> 1500.50
    - '5,45' -> 5.45
    - '5.45' -> 5.45
    """
    import re
    cleaned = re.sub(r"[^\d.,]", "", raw or "")
    if not cleaned:
        raise ValueError("Número vazio")
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        parts = cleaned.split(",")
        if len(parts) == 2 and len(parts[1]) == 3 and float(parts[0]) < 100:
            cleaned = cleaned.replace(",", "")
        else:
            cleaned = cleaned.replace(",", ".")
    elif "." in cleaned:
        parts = cleaned.split(".")
        if len(parts) > 2 or (len(parts) == 2 and len(parts[1]) == 3):
            cleaned = cleaned.replace(".", "")
    return float(cleaned)


class WhatsAppCommandPayload(BaseModel):
    command: str
    sender: str


@app.post("/api/whatsapp/command")
async def api_wa_command(payload: WhatsAppCommandPayload):
    text_raw = payload.command.strip()
    parts = text_raw.split()
    if not parts:
        return {"reply": None}

    cmd = parts[0].lower()
    rest_str = " ".join(parts[1:]).strip()

    cfg = load_config()

    # 1. !aqui / !fixar / !grupo -> Define o grupo ou chat atual como destino
    if cmd in ("!aqui", "!fixar", "!grupo"):
        target_val = rest_str if rest_str else payload.sender
        cfg.target_phone = target_val
        save_config(cfg)
        return {
            "reply": (
                "✅ *Destino dos alertas configurado com sucesso!*\n\n"
                f"• *Grupo/Chat:* `{target_val}`\n"
                "Todos os alertas automáticos de queda do dólar e testes do painel serão enviados para cá!"
            )
        }

    # 2. !dolar / !agora / !cotacao -> Raio-X Completo do Dólar + Resumo Euro e Peso
    if cmd in ("!dolar", "!dólar", "!agora", "!cotacao", "!cotação", "!status"):
        df = await fetch_historical_ohlc(days=180, force=True, currency="USD")
        spot = await fetch_spot_quote(force=True, currency="USD")
        analysis = analyze_dollar(df, spot, cfg)
        overview = await fetch_currencies_overview(force=False)
        return {"reply": format_whatsapp_report(analysis, is_auto_alert=False, overview=overview)}

    # 2b. !euro / !eur -> Raio-X Completo do Euro (EUR/BRL)
    if cmd in ("!euro", "!eur", "!euros"):
        df = await fetch_historical_ohlc(days=180, force=True, currency="EUR")
        spot = await fetch_spot_quote(force=True, currency="EUR")
        analysis = analyze_dollar(df, spot, cfg)
        return {"reply": format_whatsapp_report(analysis, is_auto_alert=False)}

    # 2c. !peso / !ars / !argentina -> Raio-X Completo do Peso Argentino (ARS/BRL)
    if cmd in ("!peso", "!pesos", "!ars", "!argentina", "!arg"):
        df = await fetch_historical_ohlc(days=180, force=True, currency="ARS")
        spot = await fetch_spot_quote(force=True, currency="ARS")
        analysis = analyze_dollar(df, spot, cfg)
        return {"reply": format_peso_report(analysis)}

    # 2d. !moedas / !cambio -> Comparativo rápido Dólar + Euro + Peso Argentino
    if cmd in ("!moedas", "!moeda", "!cambio", "!câmbio"):
        overview = await fetch_currencies_overview(force=True)
        return {"reply": format_currencies_overview_report(overview)}

    # 3. !score -> Sem argumento explica o Score e os 4 pilares; com número altera o gatilho
    if cmd in ("!score", "!nota", "!explicar"):
        df = await fetch_historical_ohlc(days=180, force=False)
        spot = await fetch_spot_quote(force=True)
        analysis = analyze_dollar(df, spot, cfg)
        if not rest_str:
            return {"reply": format_score_explanation(analysis, cfg)}
        try:
            val = int(round(parse_smart_number(rest_str)))
            val = max(30, min(95, val))
            cfg.min_score_alert = val
            save_config(cfg)
            return {
                "reply": (
                    f"📊 *Score mínimo de alerta atualizado para {val}/100!*\n\n"
                    f"• *Score de Agora:* *{analysis['score']['total']}/100* ({analysis['score']['verdict']})\n"
                    "💡 _Dica:_ Envie apenas `!score` (sem número) para ver a explicação detalhada dos 4 pilares!"
                )
            }
        except Exception:
            return {"reply": format_score_explanation(analysis, cfg)}

    # 4. !indicadores / !tecnico / !metodo -> Explica RSI, Bollinger, Z-Score, Médias e ATR
    if cmd in ("!indicadores", "!indicador", "!tecnico", "!técnico", "!metodo", "!método"):
        df = await fetch_historical_ohlc(days=180, force=False)
        spot = await fetch_spot_quote(force=True)
        analysis = analyze_dollar(df, spot, cfg)
        return {"reply": format_indicators_explanation(analysis)}

    # 5. !historico / !estatistica / !30d / !90d -> Estatística de 30 e 90 dias
    if cmd in ("!historico", "!histórico", "!estatistica", "!estatística", "!30d", "!90d"):
        df = await fetch_historical_ohlc(days=180, force=False)
        spot = await fetch_spot_quote(force=True)
        analysis = analyze_dollar(df, spot, cfg)
        return {"reply": format_history_report(analysis)}

    # 6. !lotes / !dca / !estrategia -> Estratégia de Compra Fracionada em 3 Lotes
    if cmd in ("!lotes", "!lote", "!dca", "!estrategia", "!estratégia"):
        lower_rest = rest_str.lower()
        is_brl = any(k in lower_rest for k in ("r$", "brl", "reais", "real"))
        try:
            amt = parse_smart_number(rest_str) if rest_str else float(cfg.simulation_amount_usd)
        except Exception:
            amt = float(cfg.simulation_amount_usd)
        amt = max(amt, 50.0)
        df = await fetch_historical_ohlc(days=180, force=False)
        spot = await fetch_spot_quote(force=True)
        analysis = analyze_dollar(df, spot, cfg)
        return {"reply": format_dca_strategy(analysis, amount=amt, is_brl=is_brl)}

    # 7. !wise / !taxas / !comparar -> Comparativo Wise API vs Conta Global vs Investimento vs Espécie
    if cmd in ("!wise", "!nomad", "!taxas", "!comparar", "!spread", "!iof"):
        df = await fetch_historical_ohlc(days=180, force=False)
        spot = await fetch_spot_quote(force=True)
        analysis = analyze_dollar(df, spot, cfg)
        return {"reply": format_wise_comparison(analysis)}

    # 8. !tendencia / !faca -> Diagnóstico de tendência e Detector Anti-Faca Caindo
    if cmd in ("!tendencia", "!tendência", "!faca", "!timing", "!suporte"):
        df = await fetch_historical_ohlc(days=180, force=False)
        spot = await fetch_spot_quote(force=True)
        analysis = analyze_dollar(df, spot, cfg)
        return {"reply": format_trend_report(analysis)}

    # 9. !simular -> Simulador completo em USD ou BRL
    if cmd in ("!simular", "!simula", "!simulacao", "!simulação", "!calcular", "!calc"):
        lower_rest = rest_str.lower()
        is_brl = any(k in lower_rest for k in ("r$", "brl", "reais", "real"))
        try:
            amt = parse_smart_number(rest_str) if rest_str else float(cfg.simulation_amount_usd)
        except Exception:
            amt = float(cfg.simulation_amount_usd)

        amt = max(amt, 10.0)
        cfg.simulation_amount_usd = amt if not is_brl else cfg.simulation_amount_usd
        df = await fetch_historical_ohlc(days=180, force=False)
        spot = await fetch_spot_quote(force=True)
        analysis = analyze_dollar(df, spot, cfg)
        return {
            "reply": format_simulation_report(
                analysis, amount=amt, is_brl_input=is_brl
            )
        }

    # 10. !meta -> Sem argumento mostra sugestões de meta; com argumento define meta de preço
    if cmd in ("!meta", "!alvo"):
        df = await fetch_historical_ohlc(days=180, force=False)
        spot = await fetch_spot_quote(force=True)
        analysis = analyze_dollar(df, spot, cfg)
        st = analysis["statistics"]
        ind = analysis["indicators"]

        if not rest_str:
            atual_meta = fmt_brl(cfg.target_price_brl, 4) if cfg.target_price_brl else "Nenhuma"
            return {
                "reply": (
                    "🎯 *ALERTA DE PREÇO-ALVO (!META)*\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    f"• *Sua Meta Atual:* *{atual_meta}*\n"
                    f"• *Dólar Agora:* *{fmt_brl(spot['price'], 4)}*\n\n"
                    "📐 *Sugestões Técnicas para sua Meta:*\n"
                    f"• Suporte de 30 dias: *{fmt_brl(st['min30'], 4)}*\n"
                    f"• Piso de Bollinger: *{fmt_brl(ind['bb_lower'], 4)}*\n"
                    f"• Recuo de 1 ATR: *{fmt_brl(spot['price'] - ind['atr14'], 4)}*\n\n"
                    "💡 *Como configurar:*\n"
                    f"Envie `!meta {fmt_num(st['min30'], 2)}` para ativar ou `!meta off` para desativar."
                )
            }
        if rest_str.lower() in ("off", "0", "nenhuma", "desativar"):
            cfg.target_price_brl = None
            save_config(cfg)
            return {
                "reply": (
                    "🎯 *Meta fixa desativada!*\n"
                    f"O robô continuará monitorando pelo *Score Quantitativo (>= {cfg.min_score_alert}/100)*."
                )
            }
        try:
            val = parse_smart_number(rest_str)
            cfg.target_price_brl = val
            save_config(cfg)
            return {
                "reply": (
                    "🎯 *Meta de preço configurada com sucesso!*\n\n"
                    f"• *Alvo:* *{fmt_brl(val, 4)}* ou menos\n"
                    "Assim que o dólar comercial atingir esse valor, você receberá um alerta imediato aqui no WhatsApp!"
                )
            }
        except Exception:
            return {
                "reply": "⚠️ *Formato inválido.*\nEnvie por exemplo: `!meta 5,00` ou `!meta off` para desativar."
            }

    # 10b. !queda -> Ativa/desativa filtro de avisar somente quando o dólar registrar queda
    if cmd in ("!queda", "!quedas"):
        if rest_str.lower() in ("off", "nao", "não", "desativar"):
            cfg.only_on_drop = False
        else:
            cfg.only_on_drop = True
        save_config(cfg)
        state_txt = "🟢 ATIVADO (Só avisa quando o dólar cair!)" if cfg.only_on_drop else "⚪ DESATIVADO"
        return {
            "reply": (
                f"📉 *Filtro de Alerta em Queda: {state_txt}*\n\n"
                "O robô só enviará mensagens automáticas quando o dólar registrar queda real!"
            )
        }

    # 11. !config / !painel -> Mostra todas as configurações atuais
    if cmd in ("!config", "!configuracao", "!configuração", "!painel", "!regras"):
        df = await fetch_historical_ohlc(days=180, force=False)
        spot = await fetch_spot_quote(force=False)
        analysis = analyze_dollar(df, spot, cfg)
        return {"reply": format_config_status(cfg, analysis)}

    # 12. !pausar / !retomar -> Liga ou desliga os alertas automáticos
    if cmd in ("!pausar", "!parar", "!desligar", "!mute"):
        cfg.auto_alert_enabled = False
        save_config(cfg)
        return {
            "reply": (
                "⏸️ *Alertas automáticos PAUSADOS!*\n"
                "Você ainda pode usar todos os comandos manuais (`!dolar`, `!euro`, `!peso`, `!simular`, etc.).\n"
                "Para reativar os alertas automáticos, envie `!retomar`."
            )
        }

    if cmd in ("!retomar", "!ligar", "!ativar", "!continuar"):
        cfg.auto_alert_enabled = True
        save_config(cfg)
        return {
            "reply": (
                "▶️ *Alertas automáticos REATIVADOS!*\n"
                f"Monitorando o dólar a cada *{cfg.check_interval_minutes} min* (Alerta somente em queda / Score >= *{cfg.min_score_alert}/100*)."
            )
        }

    # 13. !ajuda / !comandos / !menu -> Lista completa de comandos
    if cmd in ("!ajuda", "!help", "!comandos", "!menu"):
        help_text = (
            "🤖 *CENTRAL DE COMANDOS — SMART DOLLAR BOT*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "💵 *Cotações & Raio-X (Dólar, Euro e Peso):*\n"
            "• `!dolar` ou `!agora` ➔ Raio-X completo do Dólar + resumo das moedas\n"
            "• `!euro` ou `!eur` ➔ Raio-X completo do Euro (EUR/BRL)\n"
            "• `!peso` ou `!ars` ➔ Raio-X do Peso Argentino (R$ 1 em Pesos + 1.000 ARS)\n"
            "• `!moedas` ou `!cambio` ➔ Painel comparando Dólar, Euro e Peso lado a lado\n"
            "• `!wise` ou `!taxas` ➔ Comparativo Wise PIX vs Conta Global vs Espécie vs Cartão\n\n"
            "🧠 *Entenda a Análise (Método Completo):*\n"
            "• `!score` ➔ Explica como funciona a nota de 0 a 100 e mostra os 4 pilares hoje\n"
            "• `!indicadores` ➔ Explica RSI, Bollinger, Z-Score, Médias e ATR de hoje\n"
            "• `!historico` ➔ Estatística completa dos últimos 30 e 90 dias\n"
            "• `!tendencia` ou `!faca` ➔ Detector Anti-Faca Caindo, MACD e Suportes\n\n"
            "🧮 *Simuladores & Estratégia:*\n"
            "• `!simular 1000` ➔ Quanto custa comprar US$ 1.000 hoje\n"
            "• `!simular R$ 1000` ➔ Quantos dólares você compra com R$ 1.000\n"
            "• `!lotes 1000` ou `!dca` ➔ Plano de compra dividida em 3 lotes\n\n"
            "⚙️ *Configurar Alertas pelo Zap:*\n"
            "• `!queda` ➔ Garante alertas automáticos só quando o dólar cair\n"
            "• `!score 75` ➔ Muda a nota mínima do alerta automático\n"
            "• `!meta` ou `!meta 5,00` ➔ Sugere ou define um alerta de preço fixo\n"
            "• `!aqui` ou `!fixar` ➔ Fixa este grupo como destino dos alertas\n"
            "• `!config` ➔ Mostra as configurações atuais do robô\n"
            "• `!pausar` / `!retomar` ➔ Pausa ou reativa os alertas automáticos"
        )
        return {"reply": help_text}

    return {
        "reply": (
            f"❓ Comando `{cmd}` não reconhecido.\n"
            "Envie `!ajuda` para ver todos os comandos (`!dolar`, `!euro`, `!peso`, `!moedas`, `!simular`, `!score`, etc.)."
        )
    }
