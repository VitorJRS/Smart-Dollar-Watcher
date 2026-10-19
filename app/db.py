import json
import os
from typing import Any, Optional

_DB_INITIALIZED = False
_DB_UNREACHABLE = False

DEFAULT_RENDER_DB_URL = (
    "postgresql://encurtador_db_trdk_user:"
    "VlLWnraMKQyjRpxXeCu3109eeqdsCKRM@"
    "dpg-db7mvss9v7es73cklaqg-a/encurtador_db_trdk"
)


def get_database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url and os.environ.get("RENDER"):
        url = DEFAULT_RENDER_DB_URL
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    return url


def is_postgres_enabled() -> bool:
    if _DB_UNREACHABLE:
        return False
    return bool(get_database_url())


def _get_conn():
    import psycopg
    url = get_database_url()
    if not url:
        return None
    return psycopg.connect(url, autocommit=True, connect_timeout=5)


def init_db() -> bool:
    global _DB_INITIALIZED, _DB_UNREACHABLE
    if _DB_UNREACHABLE:
        return False
    if _DB_INITIALIZED:
        return True
    if not get_database_url():
        return False
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS smart_dollar_store (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    """
                )
        _DB_INITIALIZED = True
        print("[Database] PostgreSQL conectado e tabela smart_dollar_store pronta!")
        return True
    except Exception as e:
        _DB_UNREACHABLE = True
        print(f"[Database] PostgreSQL indisponível neste ambiente ({e}). Usando JSON local.")
        return False


def db_get_json(key: str) -> Optional[Any]:
    if not is_postgres_enabled() or not init_db():
        return None
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT value FROM smart_dollar_store WHERE key = %s",
                    (key,),
                )
                row = cur.fetchone()
                if row and row[0]:
                    return json.loads(row[0])
    except Exception as e:
        print(f"[Database] Erro ao ler chave '{key}' do PostgreSQL: {e}")
    return None


def db_set_json(key: str, data: Any) -> bool:
    if not is_postgres_enabled() or not init_db():
        return False
    try:
        payload = json.dumps(data, ensure_ascii=False)
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO smart_dollar_store (key, value, updated_at)
                    VALUES (%s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (key) DO UPDATE
                    SET value = EXCLUDED.value,
                        updated_at = CURRENT_TIMESTAMP;
                    """,
                    (key, payload),
                )
        return True
    except Exception as e:
        print(f"[Database] Erro ao salvar chave '{key}' no PostgreSQL: {e}")
        return False


def db_delete_key(key: str) -> bool:
    if not is_postgres_enabled() or not init_db():
        return False
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM smart_dollar_store WHERE key = %s", (key,))
        return True
    except Exception as e:
        print(f"[Database] Erro ao remover chave '{key}' no PostgreSQL: {e}")
        return False

