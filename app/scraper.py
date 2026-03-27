"""
Scraper do PCI Concursos.

Fluxo:
1. Busca novos concursos em /ultimas/ (e fallback por região)
2. Para cada concurso, acessa a página da notícia
3. Extrai URL do edital (PDF ou página da banca)
"""

import re
import time
import logging
from datetime import date, datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup

from .config import (
    PCI_BASE_URL, PCI_ULTIMAS_URL, PCI_REGIOES,
    REQUEST_DELAY, REQUEST_TIMEOUT, HEADERS
)
from .models import Concurso

logger = logging.getLogger(__name__)


def _get(url: str, session: requests.Session) -> Optional[BeautifulSoup]:
    """GET com retry e delay. Retorna BeautifulSoup ou None."""
    try:
        time.sleep(REQUEST_DELAY)
        resp = session.get(url, timeout=REQUEST_TIMEOUT, headers=HEADERS)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")
    except requests.RequestException as e:
        logger.warning(f"Falha ao acessar {url}: {e}")
        return None


def _parse_data(texto: str, ano_ref: int) -> Optional[str]:
    """
    Converte datas do PCI para ISO 8601.
    Formatos: '09/04/2026', '11/05 a 10/06/2026', 'Prorrogado até 15/05/2026'
    Retorna a data de fim no formato YYYY-MM-DD.
    """
    texto = texto.strip()
    # Extrai o último padrão DD/MM/AAAA ou DD/MM
    matches = re.findall(r'(\d{2})/(\d{2})(?:/(\d{4}))?', texto)
    if not matches:
        return None
    dia, mes, ano = matches[-1]
    ano = ano if ano else str(ano_ref)
    try:
        return date(int(ano), int(mes), int(dia)).isoformat()
    except ValueError:
        return None


def _parse_salario(texto: str) -> float:
    """Extrai o salário máximo de texto como 'até R$ 10.868,02'."""
    m = re.search(r'R\$\s*([\d.,]+)', texto.replace('\xa0', ' '))
    if not m:
        return 0.0
    val = m.group(1).replace('.', '').replace(',', '.')
    try:
        return float(val)
    except ValueError:
        return 0.0


def _parse_vagas(texto: str) -> int:
    """Extrai número de vagas de texto como '19 vagas'."""
    m = re.search(r'(\d+)\s*vaga', texto, re.I)
    return int(m.group(1)) if m else 0


def _parse_listagem(soup: BeautifulSoup, hoje: date) -> list[Concurso]:
    """
    Extrai concursos de uma página de listagem do PCI.
    O PCI usa blocos <a> com título descritivo seguidos de elementos de detalhe.
    """
    concursos = []
    ano_ref = hoje.year

    # Blocos de concurso: cada notícia é um <li> ou <div> com link /noticias/
    links = soup.find_all("a", href=re.compile(r'/noticias/'))
    seen_urls = set()

    for link in links:
        href = link.get("href", "")
        if not href or href in seen_urls:
            continue
        seen_urls.add(href)

        url = href if href.startswith("http") else PCI_BASE_URL + href
        orgao = link.get_text(strip=True)
        if not orgao or len(orgao) < 3:
            continue

        # Tenta extrair dados do bloco pai (elemento contendo UF, vagas, salário, datas)
        container = link.find_parent()
        texto_container = container.get_text(" ", strip=True) if container else ""

        # UF: 2 letras maiúsculas isoladas
        uf_m = re.search(r'\b([A-Z]{2})\b', texto_container)
        uf = uf_m.group(1) if uf_m else ""

        vagas = _parse_vagas(texto_container)
        salario = _parse_salario(texto_container)
        data_fim = _parse_data(texto_container, ano_ref)

        concurso = Concurso(
            orgao=orgao,
            uf=uf,
            url_pci=url,
            vagas_total=vagas,
            salario_max=salario,
            inscricao_fim=data_fim,
            status="aberto",
            coletado_em=hoje.isoformat(),
        )
        concursos.append(concurso)

    return concursos


def _fetch_pagina_noticia(url: str, session: requests.Session) -> dict:
    """
    Acessa a página da notícia no PCI e extrai:
    - URL do edital (PDF do PCI ou externo)
    - Nome da banca organizadora
    - Município
    - Detalhes adicionais do texto
    """
    result = {
        "url_edital_pci": None,
        "url_edital_externo": None,
        "banca": "",
        "municipio": "",
        "texto_resumo": "",
    }

    soup = _get(url, session)
    if not soup:
        return result

    texto_pagina = soup.get_text(" ", strip=True)
    result["texto_resumo"] = texto_pagina[:2000]

    # Links de PDF na seção de links
    for a in soup.find_all("a", href=True):
        href = a["href"]
        texto_link = a.get_text(strip=True).upper()

        # PDF hospedado no PCI
        if "arq.pciconcursos.com.br" in href and href.endswith(".pdf"):
            result["url_edital_pci"] = href

        # Links externos que parecem editais
        elif href.endswith(".pdf") and any(
            kw in texto_link for kw in ["EDITAL", "REGULAMENTO", "NORMATIVA"]
        ):
            result["url_edital_externo"] = href

        # Link para site da banca
        elif any(
            banca in href.lower() for banca in [
                "ibgp", "vunesp", "cebraspe", "cespe", "fcc.org", "fgv",
                "consulplan", "fepese", "objetiva", "ibfc", "quadrix",
                "institutoaocp", "fundatec", "acheconcursos", "agrobase"
            ]
        ):
            if not result["url_edital_externo"]:
                result["url_edital_externo"] = href

    # Nome da banca (procura padrões como "Banca: IBGP" ou links com nome de banca)
    bancas_conhecidas = [
        "IBGP", "VUNESP", "CESPE", "CEBRASPE", "FCC", "FGV",
        "CONSULPLAN", "FEPESE", "OBJETIVA", "IBFC", "QUADRIX",
        "AOCP", "FUNDATEC", "IADES"
    ]
    for banca in bancas_conhecidas:
        if banca.lower() in texto_pagina.lower():
            result["banca"] = banca
            break

    # Município (procura "Município de X" ou "Prefeitura de X")
    mun_m = re.search(
        r'(?:Município|Prefeitura|Câmara)\s+(?:Municipal\s+)?de\s+([A-ZÀ-Ú][a-zà-ú]+(?: [A-ZÀ-Ú][a-zà-ú]+)*)',
        texto_pagina
    )
    if mun_m:
        result["municipio"] = mun_m.group(1)

    return result


def buscar_novos_concursos(
    session: requests.Session,
    hoje: Optional[date] = None
) -> list[tuple[Concurso, dict]]:
    """
    Ponto de entrada principal.
    Retorna lista de (Concurso, detalhes_noticia) para todos os concursos
    encontrados hoje em /ultimas/ e páginas regionais.
    """
    if hoje is None:
        hoje = date.today()

    todos: list[Concurso] = []
    seen_ids: set[str] = set()

    # 1. Página /ultimas/ — principal fonte de novidades diárias
    logger.info("Buscando em /ultimas/ ...")
    soup = _get(PCI_ULTIMAS_URL, session)
    if soup:
        novos = _parse_listagem(soup, hoje)
        logger.info(f"  /ultimas/: {len(novos)} concursos encontrados")
        for c in novos:
            if c.id not in seen_ids:
                seen_ids.add(c.id)
                todos.append(c)

    # 2. Fallback: páginas regionais (garante cobertura mesmo se /ultimas/ falhar)
    for regiao in PCI_REGIOES:
        url = f"{PCI_BASE_URL}/concursos/{regiao}/"
        logger.info(f"Buscando em /concursos/{regiao}/ ...")
        soup = _get(url, session)
        if soup:
            regionais = _parse_listagem(soup, hoje)
            novos_count = 0
            for c in regionais:
                if c.id not in seen_ids:
                    seen_ids.add(c.id)
                    todos.append(c)
                    novos_count += 1
            logger.info(f"  /{regiao}/: {novos_count} novos concursos")

    # 3. Para cada concurso, busca detalhes na página da notícia
    resultado: list[tuple[Concurso, dict]] = []
    logger.info(f"Buscando detalhes de {len(todos)} concursos nas páginas de notícia...")
    for i, concurso in enumerate(todos, 1):
        logger.info(f"  [{i}/{len(todos)}] {concurso.orgao} ({concurso.uf})")
        detalhes = _fetch_pagina_noticia(concurso.url_pci, session)
        resultado.append((concurso, detalhes))

    return resultado
