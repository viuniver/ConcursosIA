"""
Geocodificador de órgãos públicos via Nominatim (OpenStreetMap).

- Consulta o Nominatim com múltiplas estratégias de query
- Cache em disco: data/geocode_cache.json
- Rate limit: 1 req/s (respeita política do Nominatim)
- Fallback final: centroide da UF (via geocode.py)
"""

import json
import re
import time
import logging
import unicodedata
import threading
from pathlib import Path
from typing import Optional

import requests

from .config import DATA_DIR
from .geocode import UF_CENTROIDES, _jitter

logger = logging.getLogger(__name__)

CACHE_FILE = DATA_DIR / "geocode_cache.json"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_HEADERS = {
    "User-Agent": "ConcursosIA/1.0 (concursos-publicos-brasil; contact@concursosIA.br)",
    "Accept-Language": "pt-BR,pt;q=0.9",
}
RATE_LIMIT_SEC = 1.1   # Nominatim exige >= 1s entre requests
REQUEST_TIMEOUT = 10

# Lock global para serializar chamadas ao Nominatim
_nominatim_lock = threading.Lock()
_last_request_time: float = 0.0


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in texto if unicodedata.category(c) != "Mn").strip()


def _cache_key(orgao: str, uf: str, municipio: str) -> str:
    return _normalizar(f"{orgao}|{uf}|{municipio}")


# ── Cache em disco ────────────────────────────────────────────────────────────

_cache: Optional[dict] = None
_cache_lock = threading.Lock()


def _carregar_cache() -> dict:
    global _cache
    with _cache_lock:
        if _cache is None:
            if CACHE_FILE.exists():
                try:
                    _cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
                except Exception:
                    _cache = {}
            else:
                _cache = {}
        return _cache


def _salvar_cache() -> None:
    with _cache_lock:
        if _cache is not None:
            CACHE_FILE.write_text(
                json.dumps(_cache, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )


def _set_cache(key: str, lat: float, lng: float, fonte: str) -> None:
    cache = _carregar_cache()
    with _cache_lock:
        cache[key] = {"lat": lat, "lng": lng, "fonte": fonte}
    _salvar_cache()


def _get_cache(key: str) -> Optional[tuple[float, float]]:
    cache = _carregar_cache()
    entry = cache.get(key)
    if entry:
        return entry["lat"], entry["lng"]
    return None


# ── Extração de cidade do nome do órgão ──────────────────────────────────────

CAPITAIS: dict[str, str] = {
    "AC": "Rio Branco", "AL": "Maceió", "AM": "Manaus", "AP": "Macapá",
    "BA": "Salvador", "CE": "Fortaleza", "DF": "Brasília", "ES": "Vitória",
    "GO": "Goiânia", "MA": "São Luís", "MG": "Belo Horizonte", "MS": "Campo Grande",
    "MT": "Cuiabá", "PA": "Belém", "PB": "João Pessoa", "PE": "Recife",
    "PI": "Teresina", "PR": "Curitiba", "RJ": "Rio de Janeiro", "RN": "Natal",
    "RO": "Porto Velho", "RR": "Boa Vista", "RS": "Porto Alegre",
    "SC": "Florianópolis", "SE": "Aracaju", "SP": "São Paulo", "TO": "Palmas",
}

PALAVRAS_SECRETARIA = {"secretaria", "seap", "seduc", "sead", "semas", "ses", "seplag"}
PALAVRAS_FEDERAL = {"marinha", "correios", "comara", "icmbio", "esf"}


def _limpar_orgao(orgao: str) -> str:
    """Remove sufixos de cargo entre parênteses: 'Prefeitura X (Motorista)' → 'Prefeitura X'."""
    return re.sub(r'\s*\([^)]+\)\s*$', '', orgao).strip()


def _extrair_cidade_do_orgao(orgao: str) -> Optional[str]:
    """
    Tenta extrair o município do nome do órgão.
    Ex: "Prefeitura de Indaiatuba" → "Indaiatuba"
        "DAE - Departamento de Água e Esgoto de Bauru" → "Bauru"
        "SAAE de Passos" → "Passos"
    """
    # Remove sigla inicial: "DAE - Departamento..." → "Departamento..."
    orgao_limpo = re.sub(r'^[A-Z\s/]+\s*[-–]\s*', '', orgao).strip()
    if not orgao_limpo:
        orgao_limpo = orgao

    # Padrões: "de/do/da/dos/das [Cidade]" no final ou antes de "/"
    # Ex: "de Bauru", "de Santo André", "do Rio de Janeiro"
    patterns = [
        r'(?:de|do|da|dos|das)\s+([A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][a-záàâãéêíóôõúç]+(?:\s+(?:de|do|da|dos|das|e)?\s*[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][a-záàâãéêíóôõúç]+){0,4})\s*$',
        r'(?:de|do|da|dos|das)\s+([A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][a-záàâãéêíóôõúç]+(?:\s+[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][a-záàâãéêíóôõúç]+){0,3})\s*[-/,]',
        r'Municipal\s+de\s+([A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][a-záàâãéêíóôõúç]+(?:\s+[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][a-záàâãéêíóôõúç]+){0,3})',
    ]
    for pat in patterns:
        m = re.search(pat, orgao_limpo)
        if m:
            cidade = m.group(1).strip()
            # Filtra falsos positivos (palavras genéricas)
            ignorar = {'serviços', 'agua', 'esgoto', 'saúde', 'educação',
                       'brasil', 'estado', 'municipio', 'gestão', 'desenvolvimento'}
            if _normalizar(cidade) not in ignorar and len(cidade) > 3:
                return cidade
    return None


# ── Consulta ao Nominatim ─────────────────────────────────────────────────────

def _nominatim_query(query: str) -> Optional[tuple[float, float]]:
    """Faz uma query ao Nominatim com rate limit. Retorna (lat, lng) ou None."""
    global _last_request_time

    with _nominatim_lock:
        # Rate limiting
        elapsed = time.time() - _last_request_time
        if elapsed < RATE_LIMIT_SEC:
            time.sleep(RATE_LIMIT_SEC - elapsed)

        try:
            resp = requests.get(
                NOMINATIM_URL,
                params={
                    "q": query,
                    "format": "json",
                    "limit": 1,
                    "countrycodes": "br",
                    "addressdetails": 0,
                },
                headers=NOMINATIM_HEADERS,
                timeout=REQUEST_TIMEOUT,
            )
            _last_request_time = time.time()

            if resp.status_code != 200:
                logger.debug(f"Nominatim {resp.status_code} para: {query}")
                return None

            results = resp.json()
            if results:
                lat = float(results[0]["lat"])
                lng = float(results[0]["lon"])
                logger.debug(f"Nominatim OK: '{query}' → ({lat:.4f}, {lng:.4f})")
                return lat, lng

        except requests.RequestException as e:
            logger.warning(f"Nominatim erro para '{query}': {e}")
            _last_request_time = time.time()

    return None


def _geocodificar_nominatim(orgao: str, uf: str, municipio: str) -> Optional[tuple[float, float]]:
    """
    Tenta geocodificar com múltiplas estratégias de query, do mais específico ao mais geral.
    """
    # 1. Remove sufixos de cargo entre parênteses
    orgao_limpo = _limpar_orgao(orgao)

    cidade = municipio or _extrair_cidade_do_orgao(orgao_limpo) or ""

    # Remove sigla do início: "DAE - Departamento..." → "Departamento..."
    orgao_sem_sigla = re.sub(r'^[A-Z0-9\s/]{2,15}\s*[-–]\s*', '', orgao_limpo).strip() or orgao_limpo

    # Para secretarias/órgãos estaduais sem município, usa capital do estado
    orgao_lower = _normalizar(orgao_limpo)
    if not cidade:
        if any(p in orgao_lower for p in PALAVRAS_SECRETARIA):
            cidade = CAPITAIS.get(uf.upper(), "")
        # ICMBio: tenta extrair a localidade do próprio nome
        # Ex: "Instituto Chico Mendes (Monte Pascoal BA)" → extrai antes do UF abreviado
        elif "chico mendes" in orgao_lower or "icmbio" in orgao_lower:
            m = re.search(r'\(([^)]+?)\s+[A-Z]{2}\)', orgao_limpo)
            if m:
                cidade = m.group(1).strip()
            else:
                cidade = CAPITAIS.get(uf.upper(), "")

    queries = []

    # 1. Só cidade + UF — mais confiável (query curta e limpa)
    if cidade:
        queries.append(f"{cidade}, {uf}, Brasil")
        queries.append(f"Prefeitura de {cidade}, {uf}, Brasil")

    # 2. Órgão sem sigla + cidade + UF
    if cidade and orgao_sem_sigla:
        queries.append(f"{orgao_sem_sigla}, {cidade}, {uf}, Brasil")

    # 3. Órgão limpo (sem cargo entre parênteses) + UF
    if orgao_limpo != orgao:
        queries.append(f"{_limpar_orgao(orgao_sem_sigla)}, {uf}, Brasil")

    # 4. Órgão sem sigla + UF
    queries.append(f"{orgao_sem_sigla}, {uf}, Brasil")

    # 5. Nome original completo + UF
    queries.append(f"{orgao_limpo}, {uf}, Brasil")

    for query in queries:
        coords = _nominatim_query(query)
        if coords:
            return coords

    return None


# ── Ponto de entrada público ──────────────────────────────────────────────────

def geocodificar_orgao(
    orgao: str,
    uf: str,
    municipio: str = "",
    seed: str = "",
    forcar_nominatim: bool = False,
) -> tuple[float, float, str]:
    """
    Retorna (lat, lng, fonte) para um órgão.

    Fontes possíveis:
      'cache'      — resultado já estava em cache
      'nominatim'  — obtido agora via Nominatim
      'uf_centroid'— fallback para centroide da UF
    """
    key = _cache_key(orgao, uf, municipio)

    # 1. Verifica cache
    if not forcar_nominatim:
        cached = _get_cache(key)
        if cached:
            return cached[0], cached[1], "cache"

    # 2. Consulta Nominatim
    coords = _geocodificar_nominatim(orgao, uf, municipio)
    if coords:
        _set_cache(key, coords[0], coords[1], "nominatim")
        return coords[0], coords[1], "nominatim"

    # 3. Fallback: centroide da UF + jitter
    base = UF_CENTROIDES.get(uf.upper(), (-15.78, -47.93))
    lat, lng = _jitter(base[0], base[1], seed or key)
    _set_cache(key, lat, lng, "uf_centroid")
    logger.info(f"Nominatim sem resultado para '{orgao}/{uf}' — usando centroide UF")
    return lat, lng, "uf_centroid"


def pre_geocodificar_vagas(vagas: list[dict], verbose: bool = True) -> dict:
    """
    Geocodifica todos os órgãos únicos de uma lista de vagas.
    Retorna um relatório {nominatim: N, cache: N, uf_centroid: N}.
    """
    # Órgãos únicos (evita chamar Nominatim para o mesmo órgão várias vezes)
    orgaos_unicos: dict[str, dict] = {}
    for v in vagas:
        key = _cache_key(v.get("orgao",""), v.get("uf",""), v.get("municipio",""))
        if key not in orgaos_unicos:
            orgaos_unicos[key] = {
                "orgao": v.get("orgao",""),
                "uf": v.get("uf",""),
                "municipio": v.get("municipio",""),
                "seed": v.get("id",""),
            }

    relatorio = {"nominatim": 0, "cache": 0, "uf_centroid": 0, "total": len(orgaos_unicos)}
    total = len(orgaos_unicos)

    for i, (key, info) in enumerate(orgaos_unicos.items(), 1):
        # Pula se já está em cache
        if _get_cache(key):
            relatorio["cache"] += 1
            if verbose:
                logger.info(f"[{i}/{total}] CACHE — {info['orgao']} ({info['uf']})")
            continue

        if verbose:
            logger.info(f"[{i}/{total}] Nominatim — {info['orgao']} ({info['uf']})")

        _, _, fonte = geocodificar_orgao(
            orgao=info["orgao"],
            uf=info["uf"],
            municipio=info["municipio"],
            seed=info["seed"],
        )
        relatorio[fonte] = relatorio.get(fonte, 0) + 1

    return relatorio
