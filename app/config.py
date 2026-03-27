import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Paths
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
VAGAS_FILE = DATA_DIR / "vagas.json"
PROCESSED_FILE = DATA_DIR / "processed_concursos.json"
PDFS_DIR = DATA_DIR / "pdfs"

# API
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = "claude-haiku-4-5-20251001"  # Haiku para custo-benefício no parsing em escala

# PCI Concursos
PCI_BASE_URL = "https://www.pciconcursos.com.br"
PCI_ULTIMAS_URL = "https://www.pciconcursos.com.br/ultimas/"
PCI_REGIOES = [
    "sudeste", "sul", "nordeste", "norte", "centrooeste", "nacional"
]
PCI_ESTADOS = [
    "acre", "alagoas", "amapa", "amazonas", "bahia", "ceara",
    "distrito-federal", "espirito-santo", "goias", "maranhao",
    "mato-grosso", "mato-grosso-do-sul", "minas-gerais", "para",
    "paraiba", "parana", "pernambuco", "piaui", "rio-de-janeiro",
    "rio-grande-do-norte", "rio-grande-do-sul", "rondonia", "roraima",
    "santa-catarina", "sao-paulo", "sergipe", "tocantins"
]

# HTTP
REQUEST_DELAY = 1.5  # segundos entre requests
REQUEST_TIMEOUT = 30
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9",
}

# PDF
PDF_MAX_PAGES = 80
PDF_TEXT_MAX_CHARS = 60_000  # ~15k tokens para o Claude

# Scheduler
DAILY_RUN_HOUR = 7   # 07:00 local time
DAILY_RUN_MINUTE = 0
