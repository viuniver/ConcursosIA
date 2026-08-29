"""
Migra os dados locais (data/*.json) para o Postgres apontado por DATABASE_URL.

Uso:
    DATABASE_URL=postgres://... python scripts/migrate_json_to_db.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg2.extras

from app.config import DATA_DIR
from app.db import get_conn, init_db


def migrar_vagas() -> None:
    path = DATA_DIR / "vagas.json"
    if not path.exists():
        print("vagas.json não encontrado, pulando.")
        return

    vagas = json.loads(path.read_text(encoding="utf-8"))
    inseridas = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            for v in vagas:
                cargo_norm = str(v.get("cargo", "")).lower().strip()
                cur.execute(
                    "INSERT INTO vagas (id, concurso_id, cargo_normalizado, dados) "
                    "VALUES (%s, %s, %s, %s) "
                    "ON CONFLICT (concurso_id, cargo_normalizado) DO NOTHING",
                    (v.get("id"), v.get("concurso_id", ""), cargo_norm, psycopg2.extras.Json(v)),
                )
                if cur.rowcount:
                    inseridas += 1
    print(f"vagas: {inseridas}/{len(vagas)} inseridas")


def migrar_processados() -> None:
    path = DATA_DIR / "processed_concursos.json"
    if not path.exists():
        print("processed_concursos.json não encontrado, pulando.")
        return

    ids = json.loads(path.read_text(encoding="utf-8"))
    with get_conn() as conn:
        with conn.cursor() as cur:
            for cid in ids:
                cur.execute(
                    "INSERT INTO processed_concursos (id) VALUES (%s) ON CONFLICT (id) DO NOTHING",
                    (cid,),
                )
    print(f"processed_concursos: {len(ids)} processados")


def migrar_geocode_cache() -> None:
    path = DATA_DIR / "geocode_cache.json"
    if not path.exists():
        print("geocode_cache.json não encontrado, pulando.")
        return

    cache = json.loads(path.read_text(encoding="utf-8"))
    with get_conn() as conn:
        with conn.cursor() as cur:
            for key, entry in cache.items():
                cur.execute(
                    "INSERT INTO geocode_cache (chave, lat, lng, fonte) VALUES (%s, %s, %s, %s) "
                    "ON CONFLICT (chave) DO NOTHING",
                    (key, entry["lat"], entry["lng"], entry.get("fonte", "")),
                )
    print(f"geocode_cache: {len(cache)} entradas")


if __name__ == "__main__":
    init_db()
    migrar_vagas()
    migrar_processados()
    migrar_geocode_cache()
    print("Migração concluída.")
