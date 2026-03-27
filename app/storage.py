"""
Gerenciamento do storage JSON.

vagas.json          — array de vagas individuais (append-only com deduplicação)
processed_concursos.json — set de IDs de concursos já processados
"""

import json
import logging
from datetime import date
from pathlib import Path
from typing import Optional

from .config import VAGAS_FILE, PROCESSED_FILE, DATA_DIR
from .models import Vaga

logger = logging.getLogger(__name__)

DATA_DIR.mkdir(parents=True, exist_ok=True)


def _ler_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Erro ao ler {path}: {e} — usando default")
    return default


def _escrever_json(path: Path, data) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


# ── Concursos processados ────────────────────────────────────────────────────

def carregar_processados() -> set[str]:
    """Retorna conjunto de IDs de concursos já processados."""
    data = _ler_json(PROCESSED_FILE, [])
    return set(data)


def marcar_processado(concurso_id: str) -> None:
    processados = carregar_processados()
    processados.add(concurso_id)
    _escrever_json(PROCESSED_FILE, sorted(processados))


# ── Vagas ────────────────────────────────────────────────────────────────────

def carregar_vagas() -> list[dict]:
    """Carrega todas as vagas do arquivo JSON."""
    return _ler_json(VAGAS_FILE, [])


def salvar_vagas(vagas: list[Vaga]) -> int:
    """
    Adiciona novas vagas ao arquivo, evitando duplicatas por (concurso_id + cargo).
    Retorna o número de vagas efetivamente adicionadas.
    """
    existentes = carregar_vagas()

    # Índice de deduplicação: (concurso_id, cargo normalizado)
    chaves_existentes: set[tuple[str, str]] = {
        (v.get("concurso_id", ""), v.get("cargo", "").lower().strip())
        for v in existentes
    }

    novas: list[dict] = []
    for vaga in vagas:
        chave = (vaga.concurso_id, vaga.cargo.lower().strip())
        if chave not in chaves_existentes:
            chaves_existentes.add(chave)
            novas.append(vaga.to_dict())

    if novas:
        existentes.extend(novas)
        _escrever_json(VAGAS_FILE, existentes)
        logger.info(f"{len(novas)} novas vagas salvas em {VAGAS_FILE}")
    else:
        logger.info("Nenhuma vaga nova para salvar (todas já existem)")

    return len(novas)


def stats_vagas() -> dict:
    """Retorna estatísticas básicas do arquivo de vagas."""
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
