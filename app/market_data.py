import time
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
import httpx
import pandas as pd

_CACHE: Dict[str, Any] = {
    "spot": None,
    "spot_ts": 0.0,
    "wise": None,
    "wise_ts": 0.0,
    "history_df": None,
    "history_ts": 0.0,
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "application/json",
}


async def fetch_wise_live_data(force: bool = False) -> Optional[Dict[str, Any]]:
    """
    Consulta a API oficial de cotações em tempo real da Wise (gateway/v3/quotes).
    Retorna a cotação comercial exata usada pelas contas globais e as taxas reais via PIX.
    """
    now = time.time()
    if not force and _CACHE["wise"] and (now - _CACHE["wise_ts"] < 30):
        return _CACHE["wise"]

    try:
        async with httpx.AsyncClient(timeout=10.0, headers=HEADERS) as client:
            resp = await client.post(
                "https://wise.com/gateway/v3/quotes/",
                json={
                    "sourceAmount": 1000,
                    "sourceCurrency": "BRL",
                    "targetCurrency": "USD",
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
                    target_usd_for_1000_brl = float(pix_opt.get("targetAmount", 0))
                    wise_vet = (
                        1000.0 / target_usd_for_1000_brl
                        if target_usd_for_1000_brl > 0
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

                    # Calcula os percentuais efetivos da Wise API
                    converted_base = max(1000.0 - wise_fee_brl - iof_brl, 900.0)
                    wise_spread_pct = round((wise_fee_brl / converted_base) * 100.0, 2)
                    wise_iof_pct = round((iof_brl / (1000.0 - iof_brl)) * 100.0, 2)

                    wise_info = {
                        "commercial_rate": round(commercial_brl, 4),
                        "wise_vet_rate": round(wise_vet, 4),
                        "wise_tax_per_usd": round(wise_vet - commercial_brl, 4),
                        "wise_spread_pct": wise_spread_pct,
                        "wise_iof_pct": wise_iof_pct,
                        "usd_for_1000_brl": round(target_usd_for_1000_brl, 2),
                    }
                    _CACHE["wise"] = wise_info
                    _CACHE["wise_ts"] = now
                    return wise_info
    except Exception:
        pass
    return _CACHE.get("wise")


async def fetch_spot_quote(force: bool = False) -> Dict[str, Any]:
    """
    Busca a cotação em tempo real do Dólar Comercial (USD/BRL).
    Combina AwesomeAPI (Ask/Venda) + Wise Gateway Live Rate para bater exatamente com os apps de câmbio.
    """
    now = time.time()
    if not force and _CACHE["spot"] and (now - _CACHE["spot_ts"] < 25):
        return _CACHE["spot"]

    wise_live = await fetch_wise_live_data(force=force)

    async with httpx.AsyncClient(timeout=12.0, headers=HEADERS, follow_redirects=True) as client:
        # Fonte 1: AwesomeAPI + Calibração com cotação de venda (ask) / Wise
        try:
            resp = await client.get("https://economia.awesomeapi.com.br/json/last/USD-BRL")
            if resp.status_code == 200:
                data = resp.json().get("USDBRL", {})
                bid = float(data.get("bid", 0))
                ask = float(data.get("ask", bid))
                high = float(data.get("high", max(bid, ask)))
                low = float(data.get("low", min(bid, ask)))
                pct_change = float(data.get("pctChange", 0.0))
                var_bid = float(data.get("varBid", 0.0))

                # Se a API da Wise respondeu em tempo real, usa a taxa comercial exata das fintechs
                effective_commercial = (
                    wise_live["commercial_rate"]
                    if wise_live and wise_live.get("commercial_rate", 0) > 1.0
                    else ask
                )
                if effective_commercial > 1.0:
                    spot = {
                        "price": round(effective_commercial, 4),
                        "bid": round(bid, 4),
                        "ask": round(ask, 4),
                        "high": round(max(high, effective_commercial), 4),
                        "low": round(min(low, effective_commercial), 4),
                        "pct_change": round(pct_change, 2),
                        "var_bid": round(var_bid, 4),
                        "timestamp": datetime.now().isoformat(),
                        "source": "Tempo Real (Wise / B3 Comercial)",
                        "wise_live": wise_live,
                    }
                    _CACHE["spot"] = spot
                    _CACHE["spot_ts"] = now
                    return spot
        except Exception:
            pass

        # Fonte 2: Yahoo Finance v8 Chart (Tempo Real USDBRL=X)
        try:
            url = "https://query1.finance.yahoo.com/v8/finance/chart/USDBRL=X?range=5d&interval=15m"
            resp = await client.get(url)
            if resp.status_code == 200:
                result = resp.json()["chart"]["result"][0]
                meta = result.get("meta", {})
                price = float(meta.get("regularMarketPrice", 0))
                if wise_live and wise_live.get("commercial_rate", 0) > 1.0:
                    price = wise_live["commercial_rate"]
                prev_close = float(meta.get("chartPreviousClose", price))
                high = float(meta.get("regularMarketDayHigh", price))
                low = float(meta.get("regularMarketDayLow", price))
                if price > 1.0:
                    var_bid = price - prev_close
                    pct_change = (var_bid / prev_close * 100.0) if prev_close else 0.0
                    spot = {
                        "price": round(price, 4),
                        "bid": round(price, 4),
                        "ask": round(price + 0.0020, 4),
                        "high": round(high, 4),
                        "low": round(low, 4),
                        "pct_change": round(pct_change, 2),
                        "var_bid": round(var_bid, 4),
                        "timestamp": datetime.now().isoformat(),
                        "source": "Yahoo Finance / Wise Live",
                        "wise_live": wise_live,
                    }
                    _CACHE["spot"] = spot
                    _CACHE["spot_ts"] = now
                    return spot
        except Exception:
            pass

    if _CACHE["spot"]:
        return _CACHE["spot"]

    raise RuntimeError("Não foi possível obter a cotação do dólar nas APIs financeiras.")


async def fetch_historical_ohlc(days: int = 180, force: bool = False) -> pd.DataFrame:
    """
    Busca candles diários (OHLC) dos últimos `days` dias.
    """
    now = time.time()
    if (
        not force
        and _CACHE["history_df"] is not None
        and (now - _CACHE["history_ts"] < 300)
    ):
        df = _CACHE["history_df"].copy()
        spot = await fetch_spot_quote(force=False)
        return _merge_spot_into_df(df, spot)

    df: Optional[pd.DataFrame] = None

    async with httpx.AsyncClient(timeout=15.0, headers=HEADERS, follow_redirects=True) as client:
        # Fonte 1: Yahoo Finance v8 (6 meses de candles diários completos)
        try:
            url = "https://query1.finance.yahoo.com/v8/finance/chart/USDBRL=X?range=6mo&interval=1d"
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
                    if c is not None and float(c) > 1.0:
                        dt = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
                        close_val = float(c)
                        rows.append(
                            {
                                "date": dt,
                                "open": float(o) if o is not None else close_val,
                                "high": float(h) if h is not None else close_val,
                                "low": float(l) if l is not None else close_val,
                                "close": close_val,
                            }
                        )
                if len(rows) >= 35:
                    df = pd.DataFrame(rows).drop_duplicates(subset=["date"], keep="last")
                    df = df.sort_values("date").reset_index(drop=True)
        except Exception:
            pass

        # Fonte 2: AwesomeAPI Daily History
        if df is None or len(df) < 35:
            try:
                url = f"https://economia.awesomeapi.com.br/json/daily/USD-BRL/{days}"
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
                        if ts > 0 and ask > 1.0:
                            dt = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
                            rows.append(
                                {
                                    "date": dt,
                                    "open": open_val if open_val > 1.0 else ask,
                                    "high": max(high, ask),
                                    "low": min(low, ask) if low > 1.0 else ask,
                                    "close": ask,
                                }
                            )
                    if len(rows) >= 25:
                        df = pd.DataFrame(rows).drop_duplicates(subset=["date"], keep="first")
                        df = df.sort_values("date").reset_index(drop=True)
            except Exception:
                pass

    if df is None or df.empty:
        raise RuntimeError("Não foi possível carregar o histórico de cotações USD/BRL.")

    _CACHE["history_df"] = df.copy()
    _CACHE["history_ts"] = now

    spot = await fetch_spot_quote(force=force)
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
