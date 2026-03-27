from dataclasses import dataclass, field, asdict
from typing import Optional
from datetime import date
import uuid


@dataclass
class Concurso:
    """Dados básicos de um concurso extraídos da listagem do PCI."""
    orgao: str
    uf: str
    url_pci: str
    vagas_total: int = 0
    salario_max: float = 0.0
    cargos_resumo: str = ""
    nivel: str = ""
    inscricao_inicio: Optional[str] = None
    inscricao_fim: Optional[str] = None
    status: str = "aberto"
    coletado_em: str = ""

    @property
    def id(self) -> str:
        """ID único baseado na URL do PCI (slug)."""
        slug = self.url_pci.rstrip("/").split("/")[-1]
        return slug


@dataclass
class ComposicaoProva:
    disciplina: str
    questoes: int
    peso: float = 1.0


@dataclass
class ConteudoProgramatico:
    conhecimentos_basicos: list[str] = field(default_factory=list)
    conhecimentos_especificos: list[str] = field(default_factory=list)
    legislacao: list[str] = field(default_factory=list)


@dataclass
class Vaga:
    """
    Uma vaga individual dentro de um concurso.
    Cada cargo do concurso gera um objeto Vaga distinto.
    """
    # Identificação
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    concurso_id: str = ""

    # Sobre o órgão/concurso
    orgao: str = ""
    uf: str = ""
    municipio: str = ""
    banca: str = ""
    regime: str = ""  # Estatutário, CLT, Temporário
    url_pci: str = ""
    url_edital: str = ""
    fonte_edital: str = ""  # ibgp, agrobase, acheconcursos, html_noticia, etc.

    # Sobre o cargo
    cargo: str = ""
    codigo_cargo: str = ""
    nivel_escolaridade: str = ""
    requisitos: list[str] = field(default_factory=list)
    atribuicoes: list[str] = field(default_factory=list)

    # Vagas
    vagas_ac: int = 0       # Ampla Concorrência
    vagas_pcd: int = 0      # Pessoas com Deficiência
    vagas_negro: int = 0    # Negros/Pardos
    vagas_total: int = 0
    cadastro_reserva: bool = False

    # Remuneração
    salario_base: float = 0.0
    beneficios: list[str] = field(default_factory=list)
    jornada_horas_semanais: int = 0

    # Inscrição
    inscricao_inicio: Optional[str] = None
    inscricao_fim: Optional[str] = None
    taxa_inscricao: float = 0.0
    local_trabalho: str = ""

    # Provas
    prova_objetiva: bool = True
    prova_discursiva: bool = False
    prova_pratica: bool = False
    prova_titulos: bool = False
    prova_fisica: bool = False
    data_prova: Optional[str] = None
    composicao_prova: list[dict] = field(default_factory=list)
    conteudo_programatico: dict = field(default_factory=dict)

    # Validade
    validade_concurso_anos: int = 2

    # Metadados
    coletado_em: str = ""

    def to_dict(self) -> dict:
        return asdict(self)
