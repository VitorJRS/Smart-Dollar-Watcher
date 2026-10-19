import json
import os
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = BASE_DIR / "data" / "config.json"
HISTORY_FILE = BASE_DIR / "data" / "alerts_history.json"


class SpreadConfig(BaseModel):
    # Padrão idêntico ao print (Encargos/IOF 3,5% + Taxa de conversão 2,0%)
    global_account_spread_pct: float = 2.00   # Taxa de conversão padrão Conta Global (2,0%)
    global_account_iof_pct: float = 3.50      # Encargos / IOF vigente (3,5%)
    wise_spread_pct: float = 1.22             # Tarifa média Wise PIX (~1,22%)
    wise_iof_pct: float = 3.50                # IOF remessa Wise (3,5%)
    investment_spread_pct: float = 1.50       # Spread conta investimento (~1,5%)
    investment_iof_pct: float = 0.38          # IOF investimento exterior (0,38%)
    cash_spread_pct: float = 4.20             # Casa de câmbio espécie (~4,2%)
    cash_iof_pct: float = 3.50                # IOF espécie vigente (3,5%)
    credit_card_spread_pct: float = 5.00      # Cartão de crédito tradicional (~5,0%)
    credit_card_iof_pct: float = 3.50         # IOF cartão vigente (3,5%)


class AppConfig(BaseModel):
    target_phone: str = "bot de dolar"        # Nome do grupo (ex: "bot de dolar") ou telefone (ex: 5511999999999)
    min_score_alert: int = 72                 # Score mínimo (0 a 100) para disparar alerta automático
    target_price_brl: Optional[float] = None  # Alerta opcional por preço-alvo direto (ex: 5.00)
    simulation_amount_usd: float = 1000.0     # Valor base para simular
    check_interval_minutes: int = 5           # Intervalo de checagem automática
    cooldown_hours: float = 4.0               # Tempo mínimo entre alertas do mesmo nível (evita spam)
    only_market_hours: bool = False           # Se True, só envia alertas em dias úteis das 08h às 19h
    auto_alert_enabled: bool = True
    spreads: SpreadConfig = SpreadConfig()


def ensure_data_dir():
    (BASE_DIR / "data").mkdir(parents=True, exist_ok=True)


def load_config() -> AppConfig:
    ensure_data_dir()
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            changed = False
            spreads_data = data.get("spreads", {})
            if spreads_data.get("global_account_iof_pct") == 1.1:
                data["spreads"] = SpreadConfig().model_dump()
                changed = True
            if not data.get("target_phone"):
                data["target_phone"] = "bot de dolar"
                changed = True
            cfg = AppConfig(**data)
            if changed:
                save_config(cfg)
            return cfg
        except Exception:
            pass
    cfg = AppConfig()
    save_config(cfg)
    return cfg


def save_config(cfg: AppConfig) -> AppConfig:
    ensure_data_dir()
    CONFIG_FILE.write_text(
        json.dumps(cfg.model_dump(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return cfg


def load_alerts_history() -> List[dict]:
    ensure_data_dir()
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def append_alert_history(entry: dict):
    ensure_data_dir()
    history = load_alerts_history()
    history.insert(0, entry)
    history = history[:100]  # mantém os últimos 100 alertas
    HISTORY_FILE.write_text(
        json.dumps(history, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
