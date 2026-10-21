import time
from datetime import datetime
from typing import Dict, Any, Optional
import httpx
import pandas as pd

CURRENCY_META: Dict[str, Dict[str, Any]] = {
    "USD": {
        "code": "USD",
        "name": "Dólar Comercial",
        "short_name": "Dólar",
        "symbol": "US$",
        "flag": "🇺🇸",
        "awesome_pair": "USD-BRL",
        "awesome_key": "USDBRL",
        "yahoo_ticker": "USDBRL=X",
        "min_valid_price": 1.0,
        "decimals": 4,
        "default_sim_amount": 1000.0,
    },
    "EUR": {
        "code": "EUR",
        "name": "Euro Comercial",
        "short_name": "Euro",
        "symbol": "€",
        "flag": "🇪🇺",
        "awesome_pair": "EUR-BRL",
        "awesome_key": "EURBRL",
        "yahoo_ticker": "EURBRL=X",
        "min_valid_price": 1.0,
        "decimals": 4,
        "default_sim_amount": 1000.0,
    },
    "ARS": {
        "code": "ARS",
        "name": "Peso Argentino",
        "short_name": "Peso Argentino",
        "symbol": "ARS",
        "flag": "🇦🇷",
        "awesome_pair": "ARS-BRL",
        "awesome_key": "ARSBRL",
        "yahoo_ticker": "ARSBRL=X",
        "min_valid_price": 0.0001,
        "decimals": 4,
        "default_sim_amount": 100000.0,
    },
}

_CACHE: Dict[str, Any] = {
    "spot": {},
    "spot_ts": {},
    "wise": {},
    "wise_ts": {},
    "history_df": {},
    "history_ts": {},
    "overview": None,
    "overview_ts": 0.0,
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "application/json",
}


def normalize_currency(currency: Optional[str]) -> str:
    c = (currency or "USD").strip().upper()
    return c if c in CURRENCY_META else "USD"


async def fetch_wise_live_data(
    force: bool = False, currency: str = "USD"
) -> Optional[Dict[str, Any]]:
    """
    Consulta a API oficial de cotações em tempo real da Wise (gateway/v3/quotes)
    para USD, EUR ou ARS.
    """
    cur = normalize_currency(currency)
    now = time.time()
    cached = _CACHE["wise"].get(cur)
    cached_ts = _CACHE["wise_ts"].get(cur, 0.0)
    if not force and cached and (now - cached_ts < 30):
        return cached

    try:
        async with httpx.AsyncClient(timeout=10.0, headers=HEADERS) as client:
            resp = await client.post(
                "https://wise.com/gateway/v3/quotes/",
                json={
                    "sourceAmount": 1000,
                    "sourceCurrency": "BRL",
                    "targetCurrency": cur,
                    "preferredPayIn": "BANK_TRANSFER",
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                raw_rate = float(data.get("rate", 0))
                if raw_rate > 0:
                    commercial_brl = 1.0 / raw_rate
                    options = data.get("paymentOptions", [])
                    pix_opt = next(
                        (o for o in options if o.get("payIn") in ("PIX", "BANK_TRANSFER")),
                        options[0] if options else {},
                    )
                    target_for_1000_brl = float(pix_opt.get("targetAmount", 0))
                    wise_vet = (
                        1000.0 / target_for_1000_brl
                        if target_for_1000_brl > 0
                        else commercial_brl * 1.0476
                    )
                    items = pix_opt.get("price", {}).get("items", [])
                    wise_fee_brl = 11.69
                    iof_brl = 33.42
                    for it in items:
                        if it.get("type") == "TRANSFERWISE":
                            wise_fee_brl = float(it.get("value", {}).get("amount", wise_fee_brl))
                        elif it.get("type") == "BRL_TAX":
                            iof_brl = float(it.get("value", {}).get("amount", iof_brl))

                    converted_base = max(1000.0 - wise_fee_brl - iof_brl, 900.0)
                    wise_spread_pct = round((wise_fee_brl / converted_base) * 100.0, 2)
                    wise_iof_pct = round((iof_brl / (1000.0 - iof_brl)) * 100.0, 2)

                    decimals = 6 if cur == "ARS" else 4
                    wise_info = {
                        "currency": cur,
                        "commercial_rate": round(commercial_brl, decimals),
                        "wise_vet_rate": round(wise_vet, decimals),
                        "wise_tax_per_usd": round(wise_vet - commercial_brl, decimals),
                        "wise_spread_pct": wise_spread_pct,
                        "wise_iof_pct": wise_iof_pct,
                        "usd_for_1000_brl": round(target_for_1000_brl, 2),
                    }
                    _CACHE["wise"][cur] = wise_info
                    _CACHE["wise_ts"][cur] = now
                    return wise_info
    except Exception:
        pass
    return _CACHE["wise"].get(cur)


async def fetch_spot_quote(
    force: bool = False, currency: str = "USD"
) -> Dict[str, Any]:
    """
    Busca a cotação em tempo real para USD, EUR ou ARS.
    Combina AwesomeAPI + Wise Gateway Live Rate + Yahoo Finance fallback.
    """
    cur = normalize_currency(currency)
    meta_cfg = CURRENCY_META[cur]
    min_valid = meta_cfg["min_valid_price"]
    decimals = 6 if cur == "ARS" else 4

    now = time.time()
    cached = _CACHE["spot"].get(cur)
    cached_ts = _CACHE["spot_ts"].get(cur, 0.0)
    if not force and cached and (now - cached_ts < 25):
        return cached

    wise_live = await fetch_wise_live_data(force=force, currency=cur)

    async with httpx.AsyncClient(timeout=12.0, headers=HEADERS, follow_redirects=True) as client:
        # Fonte 1: AwesomeAPI + Calibração com Wise Live
        try:
            resp = await client.get(
                f"https://economia.awesomeapi.com.br/json/last/{meta_cfg['awesome_pair']}"
            )
            if resp.status_code == 200:
                data = resp.json().get(meta_cfg["awesome_key"], {})
                bid = float(data.get("bid", 0))
                ask = float(data.get("ask", bid))
                high = float(data.get("high", max(bid, ask)))
                low = float(data.get("low", min(bid, ask)))
                pct_change = float(data.get("pctChange", 0.0))
                var_bid = float(data.get("varBid", 0.0))

                effective_commercial = (
                    wise_live["commercial_rate"]
                    if wise_live and wise_live.get("commercial_rate", 0) > min_valid
                    else ask
                )
                if effective_commercial > min_valid:
                    spot = {
                        "currency": cur,
                        "name": meta_cfg["name"],
                        "short_name": meta_cfg["short_name"],
                        "symbol": meta_cfg["symbol"],
                        "flag": meta_cfg["flag"],
                        "price": round(effective_commercial, decimals),
                        "bid": round(bid, decimals),
                        "ask": round(ask, decimals),
                        "high": round(max(high, effective_commercial), decimals),
                        "low": round(min(low, effective_commercial) if low > min_valid else effective_commercial, decimals),
                        "pct_change": round(pct_change, 2),
                        "var_bid": round(var_bid, decimals),
                        "inverse_per_1_brl": round(1.0 / effective_commercial, 2),
                        "brl_per_1000_units": round(effective_commercial * 1000.0, 2),
                        "timestamp": datetime.now().isoformat(),
                        "source": f"Tempo Real (Wise / B3 {cur})",
                        "wise_live": wise_live,
                    }
                    _CACHE["spot"][cur] = spot
                    _CACHE["spot_ts"][cur] = now
                    return spot
        except Exception:
            pass

        # Fonte 2: Yahoo Finance v8 Chart
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{meta_cfg['yahoo_ticker']}?range=5d&interval=15m"
            resp = await client.get(url)
            if resp.status_code == 200:
                result = resp.json()["chart"]["result"][0]
                meta = result.get("meta", {})
                price = float(meta.get("regularMarketPrice", 0))
                if wise_live and wise_live.get("commercial_rate", 0) > min_valid:
                    price = wise_live["commercial_rate"]
                prev_close = float(meta.get("chartPreviousClose", price))
                high = float(meta.get("regularMarketDayHigh", price))
                low = float(meta.get("regularMarketDayLow", price))
                if price > min_valid:
                    var_bid = price - prev_close
                    pct_change = (var_bid / prev_close * 100.0) if prev_close else 0.0
                    spot = {
                        "currency": cur,
                        "name": meta_cfg["name"],
                        "short_name": meta_cfg["short_name"],
                        "symbol": meta_cfg["symbol"],
                        "flag": meta_cfg["flag"],
                        "price": round(price, decimals),
                        "bid": round(price, decimals),
                        "ask": round(price, decimals),
                        "high": round(max(high, price), decimals),
                        "low": round(min(low, price) if low > min_valid else price, decimals),
                        "pct_change": round(pct_change, 2),
                        "var_bid": round(var_bid, decimals),
                        "inverse_per_1_brl": round(1.0 / price, 2),
                        "brl_per_1000_units": round(price * 1000.0, 2),
                        "timestamp": datetime.now().isoformat(),
                        "source": f"Yahoo Finance / Wise {cur}",
                        "wise_live": wise_live,
                    }
                    _CACHE["spot"][cur] = spot
                    _CACHE["spot_ts"][cur] = now
                    return spot
        except Exception:
            pass

    if _CACHE["spot"].get(cur):
        return _CACHE["spot"][cur]

    raise RuntimeError(f"Não foi possível obter a cotação de {cur} nas APIs financeiras.")


async def fetch_currencies_overview(force: bool = False) -> Dict[str, Dict[str, Any]]:
    """
    Retorna um resumo rápido das 3 moedas (USD, EUR, ARS) para o painel e comandos do WhatsApp.
    """
    now = time.time()
    if not force and _CACHE["overview"] and (now - _CACHE["overview_ts"] < 25):
        return _CACHE["overview"]

    result: Dict[str, Dict[str, Any]] = {}
    for code in ("USD", "EUR", "ARS"):
        try:
            spot = await fetch_spot_quote(force=force, currency=code)
            wise_live = spot.get("wise_live") or {}
            price = float(spot["price"])
            vet_global = price * 1.02 * 1.035
            vet_wise = float(wise_live.get("wise_vet_rate") or (price * 1.0122 * 1.035))
            result[code] = {
                "code": code,
                "name": spot["name"],
                "short_name": spot["short_name"],
                "symbol": spot["symbol"],
                "flag": spot["flag"],
                "price": price,
                "pct_change": spot["pct_change"],
                "high": spot["high"],
                "low": spot["low"],
                "vet_global": round(vet_global, 6 if code == "ARS" else 4),
                "vet_wise": round(vet_wise, 6 if code == "ARS" else 4),
                "units_per_1_brl": round(1.0 / price, 2),
                "units_per_1_brl_vet": round(1.0 / vet_wise, 2),
                "brl_per_1000_units": round(price * 1000.0, 2),
                "brl_per_1000_units_vet": round(vet_wise * 1000.0, 2),
            }
        except Exception:
            pass

    if result:
        _CACHE["overview"] = result
        _CACHE["overview_ts"] = now
    return result or (_CACHE["overview"] or {})


async def fetch_historical_ohlc(
    days: int = 180, force: bool = False, currency: str = "USD"
) -> pd.DataFrame:
    """
    Busca candles diários (OHLC) dos últimos `days` dias para USD, EUR ou ARS.
    """
    cur = normalize_currency(currency)
    meta_cfg = CURRENCY_META[cur]
    min_valid = meta_cfg["min_valid_price"]

    now = time.time()
    cached_df = _CACHE["history_df"].get(cur)
    cached_ts = _CACHE["history_ts"].get(cur, 0.0)

    if not force and cached_df is not None and (now - cached_ts < 300):
        df = cached_df.copy()
        spot = await fetch_spot_quote(force=False, currency=cur)
        return _merge_spot_into_df(df, spot)

    df: Optional[pd.DataFrame] = None

    async with httpx.AsyncClient(timeout=15.0, headers=HEADERS, follow_redirects=True) as client:
        # Fonte 1: Yahoo Finance v8 (6 meses de candles diários)
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{meta_cfg['yahoo_ticker']}?range=6mo&interval=1d"
            resp = await client.get(url)
            if resp.status_code == 200:
                res = resp.json()["chart"]["result"][0]
                timestamps = res["timestamp"]
                quote = res["indicators"]["quote"][0]
                rows = []
                for ts, o, h, l, c in zip(
                    timestamps,
                    quote.get("open", []),
                    quote.get("high", []),
                    quote.get("low", []),
                    quote.get("close", []),
                ):
                    if c is not None and float(c) > min_valid:
                        dt = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
                        close_val = float(c)
                        rows.append(
                            {
                                "date": dt,
                                "open": float(o) if (o is not None and float(o) > min_valid) else close_val,
                                "high": float(h) if (h is not None and float(h) > min_valid) else close_val,
                                "low": float(l) if (l is not None and float(l) > min_valid) else close_val,
                                "close": close_val,
                            }
                        )
                if len(rows) >= 25:
                    df = pd.DataFrame(rows).drop_duplicates(subset=["date"], keep="last")
                    df = df.sort_values("date").reset_index(drop=True)
        except Exception:
            pass

        # Fonte 2: AwesomeAPI Daily History
        if df is None or len(df) < 25:
            try:
                url = f"https://economia.awesomeapi.com.br/json/daily/{meta_cfg['awesome_pair']}/{days}"
                resp = await client.get(url)
                if resp.status_code == 200:
                    items = resp.json()
                    rows = []
                    for item in items:
                        ts = int(item.get("timestamp", 0))
                        ask = float(item.get("ask", item.get("bid", 0)))
                        high = float(item.get("high", ask))
                        low = float(item.get("low", ask))
                        var_bid = float(item.get("varBid", 0))
                        open_val = ask - var_bid
                        if ts > 0 and ask > min_valid:
                            dt = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
                            rows.append(
                                {
                                    "date": dt,
                                    "open": open_val if open_val > min_valid else ask,
                                    "high": max(high, ask),
                                    "low": min(low, ask) if low > min_valid else ask,
                                    "close": ask,
                                }
                            )
                    if len(rows) >= 15:
                        df = pd.DataFrame(rows).drop_duplicates(subset=["date"], keep="first")
                        df = df.sort_values("date").reset_index(drop=True)
            except Exception:
                pass

    if df is None or df.empty:
        raise RuntimeError(f"Não foi possível carregar o histórico de cotações {cur}/BRL.")

    _CACHE["history_df"][cur] = df.copy()
    _CACHE["history_ts"][cur] = now

    spot = await fetch_spot_quote(force=force, currency=cur)
    return _merge_spot_into_df(df, spot)


def _merge_spot_into_df(df: pd.DataFrame, spot: Dict[str, Any]) -> pd.DataFrame:
    df = df.copy()
    today_str = datetime.now().strftime("%Y-%m-%d")
    price = float(spot["price"])
    high = float(spot.get("high", price))
    low = float(spot.get("low", price))

    if df.iloc[-1]["date"] == today_str:
        idx = df.index[-1]
        df.loc[idx, "close"] = price
        df.loc[idx, "high"] = max(float(df.loc[idx, "high"]), high, price)
        df.loc[idx, "low"] = min(float(df.loc[idx, "low"]), low, price)
    else:
        prev_close = float(df.iloc[-1]["close"])
        new_row = pd.DataFrame(
            [
                {
                    "date": today_str,
                    "open": prev_close,
                    "high": max(high, price),
                    "low": min(low, price),
                    "close": price,
                }
            ]
        )
        df = pd.concat([df, new_row], ignore_index=True)

    return df
