"""
Gerenciamento do storage — Postgres.

vagas               — uma linha por vaga individual (deduplicada por concurso_id + cargo)
processed_concursos — IDs de concursos já processados
"""

import logging

import psycopg2.extras

from .db import get_conn
from .models import Vaga

logger = logging.getLogger(__name__)


# ── Concursos processados ────────────────────────────────────────────────────

def carregar_processados() -> set[str]:
    """Retorna conjunto de IDs de concursos já processados."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM processed_concursos")
            return {row[0] for row in cur.fetchall()}


def marcar_processado(concurso_id: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO processed_concursos (id) VALUES (%s) "
                "ON CONFLICT (id) DO NOTHING",
                (concurso_id,),
            )


# ── Vagas ────────────────────────────────────────────────────────────────────

def carregar_vagas() -> list[dict]:
    """Carrega todas as vagas do banco."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT dados FROM vagas ORDER BY criado_em")
            return [row["dados"] for row in cur.fetchall()]


def salvar_vagas(vagas: list[Vaga]) -> int:
    """
    Adiciona novas vagas, evitando duplicatas por (concurso_id + cargo).
    Retorna o número de vagas efetivamente adicionadas.
    """
    if not vagas:
        return 0

    adicionadas = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            for vaga in vagas:
                cargo_norm = vaga.cargo.lower().strip()
                cur.execute(
                    "INSERT INTO vagas (id, concurso_id, cargo_normalizado, dados) "
                    "VALUES (%s, %s, %s, %s) "
                    "ON CONFLICT (concurso_id, cargo_normalizado) DO NOTHING",
                    (vaga.id, vaga.concurso_id, cargo_norm, psycopg2.extras.Json(vaga.to_dict())),
                )
                if cur.rowcount:
                    adicionadas += 1

    if adicionadas:
        logger.info(f"{adicionadas} novas vagas salvas")
    else:
        logger.info("Nenhuma vaga nova para salvar (todas já existem)")

    return adicionadas


def stats_vagas() -> dict:
    """Retorna estatísticas básicas das vagas."""
    vagas = carregar_vagas()
    if not vagas:
        return {"total": 0}

    ufs = {}
    cargos_count = {}
    for v in vagas:
        uf = v.get("uf", "?")
        ufs[uf] = ufs.get(uf, 0) + 1
        cargo = v.get("cargo", "?")
        cargos_count[cargo] = cargos_count.get(cargo, 0) + 1

    top_cargos = sorted(cargos_count.items(), key=lambda x: -x[1])[:10]

    return {
        "total_vagas": len(vagas),
        "total_concursos": len({v.get("concurso_id") for v in vagas}),
        "por_uf": dict(sorted(ufs.items())),
        "top_10_cargos": dict(top_cargos),
    }
