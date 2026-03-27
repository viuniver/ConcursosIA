"""
Extrator de texto de editais em PDF.

Cascata de fontes (ordem de prioridade):
  1. URL externa da banca organizadora (direta)
  2. URL do PCI arq.pciconcursos.com.br (frequentemente bloqueado)
  3. AcheConcursos (excelente para tabelas de vagas)
  4. Agrobase
  5. Busca Google via site: para banca + órgão
  6. HTML da página da notícia (fallback mínimo)
"""

import re
import io
import time
import logging
import hashlib
from pathlib import Path
from typing import Optional

import requests
import pdfplumber

from .config import (
    HEADERS, REQUEST_DELAY, REQUEST_TIMEOUT,
    PDF_MAX_PAGES, PDF_TEXT_MAX_CHARS, PDFS_DIR
)

logger = logging.getLogger(__name__)


PDFS_DIR.mkdir(parents=True, exist_ok=True)


def _baixar_pdf(url: str, session: requests.Session) -> Optional[bytes]:
    """Tenta baixar o PDF da URL. Retorna bytes ou None."""
    try:
        time.sleep(REQUEST_DELAY)
        resp = session.get(url, timeout=REQUEST_TIMEOUT, headers=HEADERS, stream=True)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        if "pdf" not in content_type.lower() and not url.lower().endswith(".pdf"):
            logger.debug(f"Resposta não é PDF: {content_type} — {url}")
            return None
        return resp.content
    except requests.RequestException as e:
        logger.debug(f"Falha ao baixar PDF {url}: {e}")
        return None


def _extrair_texto_pdf(pdf_bytes: bytes) -> str:
    """Extrai texto de bytes de PDF usando pdfplumber."""
    try:
        texto_paginas = []
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for i, pagina in enumerate(pdf.pages[:PDF_MAX_PAGES]):
                texto = pagina.extract_text() or ""
                if texto.strip():
                    texto_paginas.append(f"--- Página {i+1} ---\n{texto}")
        return "\n\n".join(texto_paginas)[:PDF_TEXT_MAX_CHARS]
    except Exception as e:
        logger.warning(f"Erro ao extrair texto do PDF: {e}")
        return ""


def _cache_path(url: str) -> Path:
    """Retorna caminho de cache local para um PDF."""
    url_hash = hashlib.md5(url.encode()).hexdigest()
    return PDFS_DIR / f"{url_hash}.pdf"


def _pdf_em_cache(url: str) -> Optional[bytes]:
    """Retorna bytes do PDF se já foi baixado antes."""
    path = _cache_path(url)
    if path.exists():
        logger.debug(f"PDF em cache: {path}")
        return path.read_bytes()
    return None


def _salvar_cache(url: str, conteudo: bytes) -> None:
    path = _cache_path(url)
    path.write_bytes(conteudo)


def _tentar_url_pdf(url: str, session: requests.Session) -> Optional[str]:
    """
    Tenta obter texto de um URL de PDF.
    Usa cache local para evitar re-downloads.
    """
    if not url:
        return None

    # Verifica cache
    cached = _pdf_em_cache(url)
    if cached:
        texto = _extrair_texto_pdf(cached)
        if texto.strip():
            return texto

    # Download
    pdf_bytes = _baixar_pdf(url, session)
    if not pdf_bytes:
        return None

    _salvar_cache(url, pdf_bytes)
    texto = _extrair_texto_pdf(pdf_bytes)
    if texto.strip():
        logger.info(f"PDF extraído com sucesso: {url} ({len(texto)} chars)")
        return texto
    return None


def _buscar_pdf_acheconcursos(orgao: str, uf: str, session: requests.Session) -> Optional[str]:
    """
    Tenta encontrar o edital no AcheConcursos.
    Retorna HTML estruturado (não PDF) que contém tabelas de vagas.
    """
    try:
        estados_map = {
            "SP": "sao-paulo", "RJ": "rio-de-janeiro", "MG": "minas-gerais",
            "RS": "rio-grande-do-sul", "PR": "parana", "SC": "santa-catarina",
            "BA": "bahia", "GO": "goias", "PE": "pernambuco", "CE": "ceara",
            "PA": "para", "MA": "maranhao", "MT": "mato-grosso",
            "MS": "mato-grosso-do-sul", "AM": "amazonas", "DF": "distrito-federal",
            "ES": "espirito-santo", "PB": "paraiba", "RN": "rio-grande-do-norte",
            "AL": "alagoas", "PI": "piaui", "SE": "sergipe", "TO": "tocantins",
            "RO": "rondonia", "AC": "acre", "AP": "amapa", "RR": "roraima",
        }
        estado_slug = estados_map.get(uf, uf.lower())

        # Slug do órgão: remove sigla inicial, converte para lowercase-com-hifens
        orgao_limpo = re.sub(r'^[A-Z]+\s*[-–]\s*', '', orgao)
        orgao_slug = re.sub(r'[^a-z0-9\s]', '', orgao_limpo.lower())
        orgao_slug = re.sub(r'\s+', '-', orgao_slug.strip())

        url = f"https://www.acheconcursos.com.br/concursos-{estado_slug}/{orgao_slug}"
        time.sleep(REQUEST_DELAY)
        resp = session.get(url, timeout=REQUEST_TIMEOUT, headers=HEADERS)
        if resp.status_code == 200 and "cargo" in resp.text.lower():
            logger.info(f"AcheConcursos: encontrado {url}")
            return resp.text[:PDF_TEXT_MAX_CHARS]
    except Exception as e:
        logger.debug(f"Falha AcheConcursos para {orgao}/{uf}: {e}")
    return None


def _buscar_pdf_ibgp(orgao: str, session: requests.Session) -> Optional[str]:
    """
    Tenta encontrar edital no IBGP via busca na página de concursos.
    """
    try:
        url = "https://www.ibgpconcursos.com.br/concursos-abertos/"
        time.sleep(REQUEST_DELAY)
        resp = session.get(url, timeout=REQUEST_TIMEOUT, headers=HEADERS)
        if resp.status_code != 200:
            return None
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "lxml")

        # Procura link para o concurso específico
        orgao_palavras = set(re.findall(r'\b\w{4,}\b', orgao.lower()))
        for a in soup.find_all("a", href=True):
            texto = a.get_text(strip=True).lower()
            match_count = sum(1 for p in orgao_palavras if p in texto)
            if match_count >= 2:
                href = a["href"]
                if not href.startswith("http"):
                    href = "https://www.ibgpconcursos.com.br" + href
                # Tenta acessar a página do concurso no IBGP para achar PDF
                time.sleep(REQUEST_DELAY)
                resp2 = session.get(href, timeout=REQUEST_TIMEOUT, headers=HEADERS)
                if resp2.status_code == 200:
                    soup2 = BeautifulSoup(resp2.text, "lxml")
                    for a2 in soup2.find_all("a", href=re.compile(r'\.pdf', re.I)):
                        texto_pdf = _tentar_url_pdf(a2["href"], session)
                        if texto_pdf:
                            return texto_pdf
    except Exception as e:
        logger.debug(f"Falha IBGP para {orgao}: {e}")
    return None


def obter_texto_edital(
    concurso_orgao: str,
    concurso_uf: str,
    url_edital_pci: Optional[str],
    url_edital_externo: Optional[str],
    texto_html_noticia: str,
    session: requests.Session,
) -> tuple[str, str]:
    """
    Obtém o texto do edital usando a cascata de fallbacks.

    Retorna (texto_edital, fonte) onde fonte identifica de onde veio o texto.
    """
    # 1. URL externa direta (banca ou portal)
    if url_edital_externo:
        if url_edital_externo.endswith(".pdf"):
            texto = _tentar_url_pdf(url_edital_externo, session)
            if texto:
                return texto, "url_externa_pdf"
        else:
            # Página HTML externa — tenta achar PDF lá dentro
            try:
                time.sleep(REQUEST_DELAY)
                resp = session.get(url_edital_externo, timeout=REQUEST_TIMEOUT, headers=HEADERS)
                if resp.status_code == 200:
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(resp.text, "lxml")
                    for a in soup.find_all("a", href=re.compile(r'\.pdf', re.I)):
                        href = a["href"]
                        if not href.startswith("http"):
                            base = re.match(r'https?://[^/]+', url_edital_externo)
                            href = (base.group(0) if base else "") + href
                        texto = _tentar_url_pdf(href, session)
                        if texto:
                            return texto, "url_externa_pagina"
                    # Se não achou PDF, usa o HTML da página
                    if len(resp.text) > 500:
                        return resp.text[:PDF_TEXT_MAX_CHARS], "url_externa_html"
            except Exception as e:
                logger.debug(f"Falha ao acessar URL externa {url_edital_externo}: {e}")

    # 2. PDF hospedado no PCI (frequentemente bloqueado)
    if url_edital_pci:
        texto = _tentar_url_pdf(url_edital_pci, session)
        if texto:
            return texto, "pci_pdf"

    # 3. AcheConcursos
    texto = _buscar_pdf_acheconcursos(concurso_orgao, concurso_uf, session)
    if texto:
        return texto, "acheconcursos"

    # 4. IBGP
    texto = _buscar_pdf_ibgp(concurso_orgao, session)
    if texto:
        return texto, "ibgp"

    # 5. Fallback mínimo: HTML da notícia do PCI
    if texto_html_noticia and len(texto_html_noticia) > 200:
        return texto_html_noticia, "html_noticia"

    return "", "nenhuma"
