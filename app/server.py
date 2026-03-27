"""
Servidor web Flask — mapa interativo de concursos.

Rotas:
  GET /                    → frontend HTML
  GET /api/vagas           → vagas filtradas com coordenadas (GeoJSON-like)
  GET /api/opcoes          → valores únicos para popular os filtros
  GET /api/stats           → totais para o painel de resumo
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request, send_from_directory

from .geocoder_nominatim import geocodificar_orgao
from .storage import carregar_vagas, stats_vagas

BASE_DIR = Path(__file__).parent.parent
TEMPLATES_DIR = BASE_DIR / "app" / "templates"

app = Flask(__name__, template_folder=str(TEMPLATES_DIR))


# ── helpers ──────────────────────────────────────────────────────────────────

def _normalizar_filtro(v: str) -> str:
    return v.strip().lower()


def _hoje_iso() -> str:
    return date.today().isoformat()


def _match_texto(vaga: dict, campo: str, query: str) -> bool:
    valor = str(vaga.get(campo) or "").lower()
    return query.lower() in valor


def _aplicar_filtros(vagas: list[dict], params: dict) -> list[dict]:
    hoje = _hoje_iso()
    resultado = []

    # Pré-processa listas de multi-select
    ufs = [v.strip().upper() for v in params.get("uf", "").split(",") if v.strip()]
    niveis = [v.strip().lower() for v in params.get("nivel", "").split(",") if v.strip()]
    regimes = [v.strip().lower() for v in params.get("regime", "").split(",") if v.strip()]
    bancas = [v.strip().lower() for v in params.get("banca", "").split(",") if v.strip()]

    cargo_q = params.get("cargo", "").strip().lower()
    orgao_q = params.get("orgao", "").strip().lower()
    salario_min = float(params.get("salario_min") or 0)
    salario_max = float(params.get("salario_max") or 0)
    vagas_min = int(params.get("vagas_min") or 0)
    so_abertas = params.get("so_abertas", "").lower() in ("1", "true", "yes")

    for v in vagas:
        # UF
        if ufs and v.get("uf", "").upper() not in ufs:
            continue

        # Cargo (busca por texto)
        if cargo_q and cargo_q not in str(v.get("cargo") or "").lower():
            continue

        # Órgão
        if orgao_q and orgao_q not in str(v.get("orgao") or "").lower():
            continue

        # Nível de escolaridade
        if niveis:
            nivel_vaga = str(v.get("nivel_escolaridade") or "").lower()
            if not any(n in nivel_vaga for n in niveis):
                continue

        # Regime
        if regimes:
            regime_vaga = str(v.get("regime") or "").lower()
            if not any(r in regime_vaga for r in regimes):
                continue

        # Banca
        if bancas:
            banca_vaga = str(v.get("banca") or "").lower()
            if not any(b in banca_vaga for b in bancas):
                continue

        # Salário mínimo
        sal = float(v.get("salario_base") or 0)
        if salario_min > 0 and sal < salario_min:
            continue
        if salario_max > 0 and sal > salario_max:
            continue

        # Vagas mínimas
        if vagas_min > 0 and int(v.get("vagas_total") or 0) < vagas_min:
            continue

        # Apenas inscrições abertas (data_fim >= hoje)
        if so_abertas:
            fim = v.get("inscricao_fim")
            if fim and fim < hoje:
                continue

        resultado.append(v)

    return resultado


def _enriquecer_com_geo(vagas: list[dict]) -> list[dict]:
    """
    Adiciona lat/lng a cada vaga usando Nominatim (com cache).
    Vagas do mesmo órgão+UF+município reutilizam a mesma coordenada.
    """
    # Cache local por sessão para evitar chamar geocodificar_orgao N vezes
    # para o mesmo órgão dentro de uma única requisição
    coords_cache: dict[str, tuple[float, float]] = {}
    enriquecidas = []

    for v in vagas:
        orgao    = v.get("orgao") or ""
        uf       = v.get("uf") or ""
        municipio = v.get("municipio") or v.get("local_trabalho") or ""
        seed     = v.get("id") or (v.get("concurso_id", "") + v.get("cargo", ""))
        key      = f"{orgao}|{uf}|{municipio}"

        if key not in coords_cache:
            lat, lng, _ = geocodificar_orgao(orgao, uf, municipio, seed)
            coords_cache[key] = (lat, lng)

        lat, lng = coords_cache[key]
        enriquecidas.append({**v, "lat": lat, "lng": lng})

    return enriquecidas


def _valores_unicos(vagas: list[dict], campo: str) -> list[str]:
    valores = set()
    for v in vagas:
        val = v.get(campo)
        if val:
            valores.add(str(val).strip())
    return sorted(valores)


# ── rotas ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(str(TEMPLATES_DIR), "index.html")


@app.route("/api/vagas")
def api_vagas():
    vagas = carregar_vagas()
    filtradas = _aplicar_filtros(vagas, request.args)

    # Paginação simples para não sobrecarregar o browser
    limite = int(request.args.get("limite") or 5000)
    filtradas = filtradas[:limite]

    com_geo = _enriquecer_com_geo(filtradas)

    return jsonify({
        "total": len(com_geo),
        "vagas": com_geo,
    })


@app.route("/api/opcoes")
def api_opcoes():
    """Retorna valores únicos de cada campo para popular os filtros."""
    vagas = carregar_vagas()
    return jsonify({
        "ufs": _valores_unicos(vagas, "uf"),
        "niveis": _valores_unicos(vagas, "nivel_escolaridade"),
        "regimes": _valores_unicos(vagas, "regime"),
        "bancas": _valores_unicos(vagas, "banca"),
        "salario_max": max((float(v.get("salario_base") or 0) for v in vagas), default=0),
    })


@app.route("/api/stats")
def api_stats():
    return jsonify(stats_vagas())


# ── entry point ───────────────────────────────────────────────────────────────

def iniciar_servidor(host: str = "0.0.0.0", port: int = 5000, debug: bool = False):
    app.run(host=host, port=port, debug=debug)
