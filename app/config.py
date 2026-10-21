import json
from pathlib import Path
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from app.db import is_postgres_enabled, db_get_json, db_set_json, db_delete_key

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = BASE_DIR / "data" / "config.json"
HISTORY_FILE = BASE_DIR / "data" / "alerts_history.json"
WA_AUTH_DIR = BASE_DIR / "whatsapp-bridge" / "auth_info_baileys"

_CONFIG_MEM_CACHE: Optional["AppConfig"] = None
_HISTORY_MEM_CACHE: Optional[List[dict]] = None


class SpreadConfig(BaseModel):
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


FIXED_DEFAULT_TARGET = "bot dolar"


class AppConfig(BaseModel):
    target_phone: str = FIXED_DEFAULT_TARGET  # Destino fixo padrão: grupo "bot dolar"
    min_score_alert: int = 72                 # Score mínimo (0 a 100) para disparar alerta automático
    target_price_brl: Optional[float] = None  # Alerta opcional por preço-alvo direto (ex: 5.00)
    simulation_amount_usd: float = 1000.0     # Valor base para simular
    check_interval_minutes: int = 5           # Intervalo de checagem automática
    cooldown_hours: float = 4.0               # Tempo mínimo entre alertas do mesmo nível (evita spam)
    only_market_hours: bool = False           # Se True, só envia alertas em dias úteis das 08h às 19h
    only_on_drop: bool = True                 # Se True, só envia alerta automático quando o dólar registrar queda
    auto_alert_enabled: bool = True
    spreads: SpreadConfig = SpreadConfig()


def ensure_data_dir():
    (BASE_DIR / "data").mkdir(parents=True, exist_ok=True)


def _normalize_config_dict(data: Dict[str, Any]) -> tuple[AppConfig, bool]:
    changed = False
    spreads_data = data.get("spreads", {})
    if spreads_data.get("global_account_iof_pct") == 1.1:
        data["spreads"] = SpreadConfig().model_dump()
        changed = True
    raw_phone = str(data.get("target_phone") or "").strip()
    # Se estiver vazio ou apontando para o número pessoal antigo, fixa no grupo "bot dolar"
    if not raw_phone or raw_phone in ("5519999831973", "19999831973", "bot de dolar"):
        data["target_phone"] = FIXED_DEFAULT_TARGET
        changed = True
    if "only_on_drop" not in data:
        data["only_on_drop"] = True
        changed = True
    if float(data.get("simulation_amount_usd") or 1000.0) >= 50000.0:
        data["simulation_amount_usd"] = 1000.0
        changed = True
    return AppConfig(**data), changed


def load_config(force_db: bool = False) -> AppConfig:
    global _CONFIG_MEM_CACHE
    ensure_data_dir()

    if _CONFIG_MEM_CACHE is not None and not force_db:
        return _CONFIG_MEM_CACHE.model_copy(deep=True)

    # 1. Tenta carregar do banco PostgreSQL (Render) se configurado
    if is_postgres_enabled():
        db_data = db_get_json("app_config")
        if isinstance(db_data, dict):
            try:
                cfg, changed = _normalize_config_dict(db_data)
                _CONFIG_MEM_CACHE = cfg
                CONFIG_FILE.write_text(
                    json.dumps(cfg.model_dump(), indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                if changed:
                    save_config(cfg)
                return cfg
            except Exception:
                pass

    # 2. Fallback para arquivo local data/config.json
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            cfg, changed = _normalize_config_dict(data)
            _CONFIG_MEM_CACHE = cfg
            if changed or is_postgres_enabled():
                save_config(cfg)
            return cfg
        except Exception:
            pass

    cfg = AppConfig()
    save_config(cfg)
    return cfg


def save_config(cfg: AppConfig) -> AppConfig:
    global _CONFIG_MEM_CACHE
    ensure_data_dir()
    _CONFIG_MEM_CACHE = cfg
    dump_dict = cfg.model_dump()

    CONFIG_FILE.write_text(
        json.dumps(dump_dict, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    if is_postgres_enabled():
        db_set_json("app_config", dump_dict)
    return cfg


def load_alerts_history() -> List[dict]:
    global _HISTORY_MEM_CACHE
    ensure_data_dir()

    if _HISTORY_MEM_CACHE is not None:
        return _HISTORY_MEM_CACHE

    if is_postgres_enabled():
        db_hist = db_get_json("alerts_history")
        if isinstance(db_hist, list):
            _HISTORY_MEM_CACHE = db_hist
            HISTORY_FILE.write_text(
                json.dumps(db_hist, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            return db_hist

    if HISTORY_FILE.exists():
        try:
            hist = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
            _HISTORY_MEM_CACHE = hist
            return hist
        except Exception:
            return []
    return []


def append_alert_history(entry: dict):
    global _HISTORY_MEM_CACHE
    ensure_data_dir()
    history = list(load_alerts_history())
    history.insert(0, entry)
    history = history[:100]
    _HISTORY_MEM_CACHE = history

    HISTORY_FILE.write_text(
        json.dumps(history, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    if is_postgres_enabled():
        db_set_json("alerts_history", history)


def backup_wa_auth_to_db() -> bool:
    """
    Salva os arquivos de sessão do WhatsApp (auth_info_baileys) no PostgreSQL do Render,
    para que o login do WhatsApp não seja perdido quando o container reiniciar!
    """
    if not is_postgres_enabled() or not WA_AUTH_DIR.exists():
        return False
    files_map: Dict[str, str] = {}
    try:
        for file_path in WA_AUTH_DIR.glob("*.json"):
            if file_path.is_file():
                files_map[file_path.name] = file_path.read_text(encoding="utf-8")
        if "creds.json" in files_map:
            return db_set_json("wa_auth_files", files_map)
    except Exception as e:
        print(f"[Database] Aviso ao fazer backup da sessão WhatsApp: {e}")
    return False


def restore_wa_auth_from_db() -> bool:
    """
    Restaura os arquivos de sessão do WhatsApp a partir do PostgreSQL antes de iniciar a ponte Node.
    """
    if not is_postgres_enabled():
        return False
    creds_file = WA_AUTH_DIR / "creds.json"
    if creds_file.exists():
        return True
    try:
        files_map = db_get_json("wa_auth_files")
        if isinstance(files_map, dict) and "creds.json" in files_map:
            WA_AUTH_DIR.mkdir(parents=True, exist_ok=True)
            for fname, content in files_map.items():
                if isinstance(fname, str) and isinstance(content, str) and fname.endswith(".json"):
                    (WA_AUTH_DIR / fname).write_text(content, encoding="utf-8")
            print(f"[Database] Sessão do WhatsApp restaurada do PostgreSQL ({len(files_map)} arquivos)!")
            return True
    except Exception as e:
        print(f"[Database] Aviso ao restaurar sessão WhatsApp: {e}")
    return False


def clear_wa_auth_from_db():
    if is_postgres_enabled():
        db_delete_key("wa_auth_files")
