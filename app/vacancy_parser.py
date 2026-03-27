"""
Extração de vagas individuais do texto de editais usando Claude API.

Para cada texto de edital (PDF ou HTML), envia ao Claude Haiku com um prompt
estruturado para retornar uma lista de vagas no formato JSON definido em models.py.
"""

import json
import logging
import re
from datetime import date
from typing import Optional

import anthropic

from .config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from .models import Vaga

logger = logging.getLogger(__name__)

# Instância reutilizável do cliente
_client: Optional[anthropic.Anthropic] = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


PROMPT_SISTEMA = """Você é um assistente especializado em extrair dados estruturados de editais de concursos públicos brasileiros.

Dado o texto de um edital (pode ser PDF extraído ou HTML), você deve retornar um JSON com a lista de vagas individuais.

IMPORTANTE:
- Cada cargo do edital deve gerar um objeto separado na lista
- Se o edital tiver 10 cargos diferentes, retorne 10 objetos
- Retorne APENAS o JSON, sem explicações ou markdown
- Se um campo não estiver disponível no texto, use null para strings e 0 para números
- Para listas vazias, use []

Formato de saída (array JSON):
[
  {
    "cargo": "nome exato do cargo",
    "codigo_cargo": "código se houver, ex: 501",
    "nivel_escolaridade": "Fundamental / Médio / Técnico / Superior",
    "requisitos": ["requisito 1", "requisito 2"],
    "atribuicoes": ["atribuição resumida"],
    "vagas_ac": 0,
    "vagas_pcd": 0,
    "vagas_negro": 0,
    "vagas_total": 0,
    "cadastro_reserva": false,
    "salario_base": 0.0,
    "jornada_horas_semanais": 40,
    "regime": "Estatutário",
    "beneficios": [],
    "taxa_inscricao": 0.0,
    "municipio": "",
    "local_trabalho": "",
    "banca": "",
    "inscricao_inicio": null,
    "inscricao_fim": null,
    "data_prova": null,
    "prova_objetiva": true,
    "prova_discursiva": false,
    "prova_pratica": false,
    "prova_titulos": false,
    "prova_fisica": false,
    "composicao_prova": [
      {"disciplina": "Língua Portuguesa", "questoes": 10, "peso": 1.0}
    ],
    "conteudo_programatico": {
      "conhecimentos_basicos": [],
      "conhecimentos_especificos": [],
      "legislacao": []
    },
    "validade_concurso_anos": 2
  }
]

Datas devem estar no formato YYYY-MM-DD."""


def _limpar_json(texto: str) -> str:
    """Remove markdown/prefixos que o modelo pode inserir antes do JSON."""
    texto = texto.strip()
    # Remove blocos ```json ... ```
    texto = re.sub(r'^```(?:json)?\s*', '', texto)
    texto = re.sub(r'\s*```$', '', texto)
    return texto.strip()


def extrair_vagas_com_claude(
    texto_edital: str,
    orgao: str,
    uf: str,
    fonte: str,
) -> list[dict]:
    """
    Chama Claude API para extrair vagas do texto do edital.
    Retorna lista de dicts (formato vaga) ou [] em caso de falha.
    """
    if not ANTHROPIC_API_KEY:
        logger.error("ANTHROPIC_API_KEY não configurada. Configure no .env")
        return []

    if not texto_edital.strip():
        logger.warning(f"Texto do edital vazio para {orgao}/{uf}")
        return []

    # Trunca para o limite do modelo (deixa espaço para o prompt)
    texto_truncado = texto_edital[:50_000]

    prompt_usuario = f"""Órgão: {orgao}
UF: {uf}
Fonte do texto: {fonte}

Texto do edital:
---
{texto_truncado}
---

Extraia todos os cargos/vagas deste edital e retorne o JSON."""

    try:
        client = _get_client()
        resposta = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=8192,
            system=PROMPT_SISTEMA,
            messages=[{"role": "user", "content": prompt_usuario}],
        )
        conteudo = resposta.content[0].text
        conteudo_limpo = _limpar_json(conteudo)

        vagas_raw = json.loads(conteudo_limpo)
        if not isinstance(vagas_raw, list):
            logger.warning(f"Resposta do Claude não é lista: {type(vagas_raw)}")
            return []

        logger.info(f"Claude extraiu {len(vagas_raw)} vagas de {orgao}/{uf}")
        return vagas_raw

    except json.JSONDecodeError as e:
        logger.error(f"JSON inválido retornado pelo Claude para {orgao}/{uf}: {e}")
        return []
    except anthropic.APIError as e:
        logger.error(f"Erro na API do Claude para {orgao}/{uf}: {e}")
        return []


def construir_vagas(
    vagas_raw: list[dict],
    concurso_id: str,
    orgao: str,
    uf: str,
    url_pci: str,
    url_edital: str,
    fonte_edital: str,
    banca_detectada: str,
    hoje: date,
) -> list[Vaga]:
    """
    Converte os dicts extraídos pelo Claude em objetos Vaga completos,
    preenchendo os campos de contexto do concurso.
    """
    vagas: list[Vaga] = []

    for raw in vagas_raw:
        if not isinstance(raw, dict):
            continue

        cargo = raw.get("cargo", "").strip()
        if not cargo:
            continue

        # Garante vagas_total coerente
        vagas_ac = int(raw.get("vagas_ac") or 0)
        vagas_pcd = int(raw.get("vagas_pcd") or 0)
        vagas_negro = int(raw.get("vagas_negro") or 0)
        vagas_total = int(raw.get("vagas_total") or 0)
        if vagas_total == 0:
            vagas_total = vagas_ac + vagas_pcd + vagas_negro

        vaga = Vaga(
            concurso_id=concurso_id,
            orgao=orgao,
            uf=uf,
            municipio=raw.get("municipio") or "",
            banca=raw.get("banca") or banca_detectada,
            regime=raw.get("regime") or "",
            url_pci=url_pci,
            url_edital=url_edital,
            fonte_edital=fonte_edital,

            cargo=cargo,
            codigo_cargo=str(raw.get("codigo_cargo") or ""),
            nivel_escolaridade=raw.get("nivel_escolaridade") or "",
            requisitos=raw.get("requisitos") or [],
            atribuicoes=raw.get("atribuicoes") or [],

            vagas_ac=vagas_ac,
            vagas_pcd=vagas_pcd,
            vagas_negro=vagas_negro,
            vagas_total=vagas_total,
            cadastro_reserva=bool(raw.get("cadastro_reserva")),

            salario_base=float(raw.get("salario_base") or 0),
            beneficios=raw.get("beneficios") or [],
            jornada_horas_semanais=int(raw.get("jornada_horas_semanais") or 0),

            inscricao_inicio=raw.get("inscricao_inicio"),
            inscricao_fim=raw.get("inscricao_fim"),
            taxa_inscricao=float(raw.get("taxa_inscricao") or 0),
            local_trabalho=raw.get("local_trabalho") or "",

            prova_objetiva=bool(raw.get("prova_objetiva", True)),
            prova_discursiva=bool(raw.get("prova_discursiva")),
            prova_pratica=bool(raw.get("prova_pratica")),
            prova_titulos=bool(raw.get("prova_titulos")),
            prova_fisica=bool(raw.get("prova_fisica")),
            data_prova=raw.get("data_prova"),
            composicao_prova=raw.get("composicao_prova") or [],
            conteudo_programatico=raw.get("conteudo_programatico") or {},

            validade_concurso_anos=int(raw.get("validade_concurso_anos") or 2),
            coletado_em=hoje.isoformat(),
        )
        vagas.append(vaga)

    return vagas
