"""
Orquestrador principal do ConcursosIA.

Uso:
  python -m app.main run      # executa uma coleta agora
  python -m app.main daemon   # inicia scheduler diário (07:00)
  python -m app.main stats    # exibe estatísticas do vagas.json
"""

import sys
import logging
import time
from datetime import date, datetime

import requests
import schedule

from .config import DAILY_RUN_HOUR, DAILY_RUN_MINUTE
from .scraper import buscar_novos_concursos
from .pdf_extractor import obter_texto_edital
from .vacancy_parser import extrair_vagas_com_claude, construir_vagas
from .storage import (
    carregar_processados, marcar_processado, salvar_vagas, stats_vagas
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def executar_coleta() -> None:
    """Executa uma rodada completa de coleta: scraping → PDF → parsing → storage."""
    hoje = date.today()
    logger.info(f"=== Iniciando coleta diária — {hoje} ===")

    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "pt-BR,pt;q=0.9",
    })

    processados = carregar_processados()
    logger.info(f"{len(processados)} concursos já processados anteriormente")

    # 1. Scraping do PCI Concursos
    concursos_com_detalhes = buscar_novos_concursos(session, hoje)
    logger.info(f"Total encontrado no PCI: {len(concursos_com_detalhes)} concursos")

    # 2. Filtra apenas os novos
    novos = [
        (c, d) for c, d in concursos_com_detalhes
        if c.id not in processados
    ]
    logger.info(f"Novos para processar: {len(novos)}")

    if not novos:
        logger.info("Nenhum concurso novo hoje. Coleta finalizada.")
        return

    total_vagas_adicionadas = 0

    for i, (concurso, detalhes) in enumerate(novos, 1):
        logger.info(
            f"[{i}/{len(novos)}] Processando: {concurso.orgao} ({concurso.uf}) "
            f"— banca: {detalhes.get('banca', '?')}"
        )

        # 3. Obtém texto do edital
        texto_edital, fonte = obter_texto_edital(
            concurso_orgao=concurso.orgao,
            concurso_uf=concurso.uf,
            url_edital_pci=detalhes.get("url_edital_pci"),
            url_edital_externo=detalhes.get("url_edital_externo"),
            texto_html_noticia=detalhes.get("texto_resumo", ""),
            session=session,
        )

        if not texto_edital:
            logger.warning(f"  ✗ Sem texto de edital para {concurso.orgao}. Pulando.")
            marcar_processado(concurso.id)
            continue

        logger.info(f"  Texto obtido via: {fonte} ({len(texto_edital)} chars)")

        # 4. Extrai vagas com Claude API
        vagas_raw = extrair_vagas_com_claude(
            texto_edital=texto_edital,
            orgao=concurso.orgao,
            uf=concurso.uf,
            fonte=fonte,
        )

        if not vagas_raw:
            logger.warning(f"  ✗ Claude não extraiu vagas de {concurso.orgao}. Pulando.")
            marcar_processado(concurso.id)
            continue

        # 5. Constrói objetos Vaga
        vagas = construir_vagas(
            vagas_raw=vagas_raw,
            concurso_id=concurso.id,
            orgao=concurso.orgao,
            uf=concurso.uf,
            url_pci=concurso.url_pci,
            url_edital=detalhes.get("url_edital_externo") or detalhes.get("url_edital_pci") or "",
            fonte_edital=fonte,
            banca_detectada=detalhes.get("banca", ""),
            hoje=hoje,
        )

        # 6. Salva no storage
        adicionadas = salvar_vagas(vagas)
        total_vagas_adicionadas += adicionadas
        logger.info(f"  ✓ {adicionadas} vagas novas salvas ({concurso.orgao})")

        # 7. Marca concurso como processado
        marcar_processado(concurso.id)

    logger.info(
        f"=== Coleta finalizada — {total_vagas_adicionadas} vagas adicionadas hoje ==="
    )

    # Exibe estatísticas
    stats = stats_vagas()
    logger.info(
        f"Total acumulado: {stats.get('total_vagas', 0)} vagas "
        f"de {stats.get('total_concursos', 0)} concursos"
    )


def iniciar_daemon() -> None:
    """Inicia o scheduler que executa a coleta diariamente."""
    hora = f"{DAILY_RUN_HOUR:02d}:{DAILY_RUN_MINUTE:02d}"
    logger.info(f"Daemon iniciado. Coleta agendada para {hora} todos os dias.")

    schedule.every().day.at(hora).do(executar_coleta)

    # Executa imediatamente na primeira vez se ainda não rodou hoje
    executar_coleta()

    while True:
        schedule.run_pending()
        time.sleep(60)


def exibir_stats() -> None:
    """Exibe estatísticas do arquivo de vagas."""
    import json
    stats = stats_vagas()
    print(json.dumps(stats, ensure_ascii=False, indent=2))


def main() -> None:
    comando = sys.argv[1] if len(sys.argv) > 1 else "run"

    if comando == "run":
        executar_coleta()
    elif comando == "daemon":
        iniciar_daemon()
    elif comando == "stats":
        exibir_stats()
    else:
        print(f"Uso: python -m app.main [run|daemon|stats]")
        print("  run    — executa uma coleta agora")
        print("  daemon — inicia scheduler diário")
        print("  stats  — exibe estatísticas do vagas.json")
        sys.exit(1)


if __name__ == "__main__":
    main()
