"""
Conexão e schema do Postgres.

Usa a variável de ambiente DATABASE_URL (injetada automaticamente pelo
Railway quando um serviço Postgres é anexado ao projeto).
"""

from __future__ import annotations

import logging
from contextlib import contextmanager

import psycopg2
import psycopg2.extras

from .config import DATABASE_URL

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS vagas (
    id TEXT PRIMARY KEY,
    concurso_id TEXT NOT NULL,
    cargo_normalizado TEXT NOT NULL,
    dados JSONB NOT NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (concurso_id, cargo_normalizado)
);

CREATE TABLE IF NOT EXISTS processed_concursos (
    id TEXT PRIMARY KEY,
    processado_em TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS geocode_cache (
    chave TEXT PRIMARY KEY,
    lat DOUBLE PRECISION NOT NULL,
    lng DOUBLE PRECISION NOT NULL,
    fonte TEXT NOT NULL
);
"""


@contextmanager
def get_conn():
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL não configurada. Defina a variável de ambiente "
            "apontando para o Postgres (o Railway injeta isso automaticamente)."
        )
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def get_cursor():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            yield cur


def init_db() -> None:
    """Cria as tabelas caso não existam. Idempotente — seguro chamar sempre."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(_SCHEMA)
    logger.info("Schema do Postgres verificado/criado.")
