"""
Expansão semântica de queries de cargo e órgão — 100% local, sem API.

Estratégia em duas camadas:
  1. Dicionário de expansão por área (cobertura das principais categorias de concursos)
  2. Correspondência fuzzy por similaridade de caracteres (para typos e variações)

Retorna lista de termos para filtragem por substring no vagas.json.
"""

import unicodedata
import logging
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

# ── Dicionário de expansão semântica ─────────────────────────────────────────
# Chave: termos que o usuário pode digitar (normalizados)
# Valor: termos que aparecem em cargos de editais
EXPANSOES: dict[str, list[str]] = {

    # Engenharia / Obras / Construção
    "obras":          ["engenheiro civil", "técnico em edificações", "fiscal de obras",
                       "arquiteto", "técnico de engenharia", "engenheiro", "mestre de obras",
                       "fiscal de obras e posturas", "técnico em construção"],
    "engenharia":     ["engenheiro", "técnico de engenharia", "engenheiro civil",
                       "engenheiro elétrico", "engenheiro mecânico", "engenheiro sanitário",
                       "engenheiro ambiental", "engenheiro agrônomo", "engenheiro de produção"],
    "construcao":     ["engenheiro civil", "técnico em edificações", "arquiteto",
                       "fiscal de obras", "técnico em construção civil"],
    "arquitetura":    ["arquiteto", "arquiteto e urbanista", "urbanista", "engenheiro civil"],
    "eletrica":       ["engenheiro elétrico", "técnico em eletrotécnica", "eletricista",
                       "técnico eletricista", "engenheiro eletricista"],
    "saneamento":     ["engenheiro sanitário", "engenheiro ambiental", "técnico em saneamento",
                       "analista ambiental", "fiscal ambiental"],

    # Saúde
    "saude":          ["médico", "enfermeiro", "técnico em enfermagem", "farmacêutico",
                       "dentista", "fisioterapeuta", "nutricionista", "psicólogo",
                       "auxiliar de enfermagem", "biomédico", "agente de saúde",
                       "assistente de saúde", "fonoaudiólogo", "terapeuta ocupacional"],
    "medico":         ["médico", "clínico geral", "médico generalista", "médico veterinário",
                       "médico do trabalho", "médico perito"],
    "enfermagem":     ["enfermeiro", "técnico em enfermagem", "auxiliar de enfermagem",
                       "enfermeiro plantonista", "enfermeiro obstétrico"],
    "farmacia":       ["farmacêutico", "farmacêutico bioquímico", "técnico em farmácia",
                       "auxiliar de farmácia"],
    "odonto":         ["dentista", "cirurgião dentista", "técnico em saúde bucal",
                       "auxiliar de saúde bucal", "odontólogo"],
    "fisio":          ["fisioterapeuta", "fisioterapeuta respiratório", "técnico em fisioterapia"],
    "nutricao":       ["nutricionista", "técnico em nutrição", "auxiliar de nutrição"],
    "psicologia":     ["psicólogo", "psicólogo clínico", "psicólogo social",
                       "psicólogo organizacional", "neuropsicólogo"],
    "veterinario":    ["médico veterinário", "veterinário", "zootecnista",
                       "técnico em zootecnia", "auxiliar veterinário"],

    # TI / Tecnologia
    "ti":             ["analista de sistemas", "técnico em informática", "analista de TI",
                       "desenvolvedor", "programador", "suporte técnico", "administrador de redes",
                       "técnico de suporte", "analista de tecnologia", "webmaster"],
    "tecnologia":     ["analista de sistemas", "técnico em informática", "analista de TI",
                       "desenvolvedor", "administrador de redes", "engenheiro de software"],
    "informatica":    ["técnico em informática", "analista de sistemas", "programador",
                       "suporte em informática", "técnico de suporte", "analista de TI"],
    "programacao":    ["desenvolvedor", "programador", "analista de sistemas",
                       "engenheiro de software", "analista de desenvolvimento"],
    "sistemas":       ["analista de sistemas", "analista de TI", "técnico em sistemas",
                       "desenvolvedor de sistemas", "administrador de sistemas"],

    # Educação / Ensino
    "professor":      ["professor", "docente", "professor substituto", "professor efetivo",
                       "professor do magistério", "professor de educação básica",
                       "professor municipal", "professor estadual", "regente de classe"],
    "educacao":       ["professor", "pedagogo", "coordenador pedagógico", "orientador educacional",
                       "supervisor escolar", "inspetor escolar", "técnico em assuntos educacionais"],
    "pedagogo":       ["pedagogo", "coordenador pedagógico", "orientador educacional",
                       "técnico em educação", "supervisor escolar"],
    "escola":         ["professor", "diretor escolar", "secretário escolar", "monitor",
                       "auxiliar de biblioteca", "merendeiro", "porteiro escolar"],
    "ensino":         ["professor", "docente", "professor substituto", "instrutor"],

    # Direito / Jurídico
    "direito":        ["advogado", "procurador", "assessor jurídico", "analista jurídico",
                       "assistente jurídico", "defensor público", "promotor", "delegado",
                       "técnico jurídico", "oficial de justiça"],
    "juridico":       ["advogado", "procurador", "assessor jurídico", "analista jurídico",
                       "técnico jurídico", "assistente jurídico", "bacharel em direito"],
    "advogado":       ["advogado", "procurador", "assessor jurídico", "defensor público"],
    "procurador":     ["procurador", "procurador municipal", "procurador jurídico",
                       "advogado público"],
    "delegado":       ["delegado", "delegado de polícia", "escrivão de polícia"],

    # Administrativo / Gestão
    "administrativo": ["assistente administrativo", "técnico administrativo",
                       "analista administrativo", "auxiliar administrativo",
                       "agente administrativo", "secretário"],
    "secretario":     ["secretário", "assistente administrativo", "auxiliar administrativo",
                       "escriturário", "agente de apoio administrativo"],
    "gestao":         ["gestor", "administrador", "analista de gestão", "analista administrativo",
                       "gerente", "coordenador"],
    "rh":             ["analista de recursos humanos", "assistente de recursos humanos",
                       "técnico em recursos humanos", "gestor de pessoas"],
    "recursos humanos": ["analista de recursos humanos", "assistente de recursos humanos",
                         "técnico em recursos humanos", "psicólogo organizacional"],

    # Contabilidade / Finanças
    "contabilidade":  ["contador", "técnico em contabilidade", "analista contábil",
                       "auxiliar contábil", "auditor", "fiscal tributário"],
    "contador":       ["contador", "técnico em contabilidade", "analista contábil",
                       "auditor contábil"],
    "financas":       ["contador", "analista financeiro", "tesoureiro", "técnico em contabilidade",
                       "auditor", "economista"],
    "auditoria":      ["auditor", "auditor fiscal", "técnico de controle interno",
                       "analista de controle interno", "contador"],
    "fiscal":         ["auditor fiscal", "fiscal de tributos", "agente fiscal",
                       "fiscal de rendas", "fiscal de vigilância sanitária",
                       "fiscal de obras", "fiscal ambiental", "agente de fiscalização",
                       "fiscal tributário"],
    "tributo":        ["auditor fiscal", "fiscal de tributos", "analista tributário",
                       "agente fiscal", "fiscal de rendas"],

    # Segurança Pública / Defesa
    "seguranca":      ["guarda municipal", "agente de segurança", "policial", "vigilante",
                       "agente penitenciário", "agente de trânsito", "inspetor de segurança"],
    "policia":        ["policial civil", "policial militar", "delegado", "escrivão",
                       "investigador", "agente de polícia", "perito criminal"],
    "guarda":         ["guarda municipal", "guarda civil", "agente de segurança",
                       "vigilante patrimonial"],
    "penitenciario":  ["agente penitenciário", "agente de execução penal",
                       "agente prisional", "inspetor penitenciário"],
    "transito":       ["agente de trânsito", "fiscal de trânsito", "agente de mobilidade urbana",
                       "controlador de trânsito"],

    # Meio Ambiente
    "ambiental":      ["analista ambiental", "engenheiro ambiental", "fiscal ambiental",
                       "técnico ambiental", "agente ambiental", "biólogo",
                       "engenheiro florestal", "geógrafo"],
    "biologia":       ["biólogo", "biomédico", "analista ambiental", "técnico em biologia",
                       "técnico em meio ambiente"],
    "florestal":      ["engenheiro florestal", "técnico florestal", "analista ambiental",
                       "técnico em meio ambiente", "agente ambiental"],

    # Assistência Social
    "social":         ["assistente social", "técnico em assistência social",
                       "agente social", "educador social", "orientador social",
                       "auxiliar de desenvolvimento social"],
    "assistente social": ["assistente social", "técnico em assistência social",
                          "agente social"],
    "cras":           ["assistente social", "psicólogo", "agente social",
                       "educador social", "auxiliar de desenvolvimento social"],

    # Obras / Serviços Gerais
    "motorista":      ["motorista", "condutor de veículos", "motorista de ônibus",
                       "operador de máquinas", "motorista de ambulância"],
    "operador":       ["operador de máquinas", "operador de equipamentos",
                       "operador de usina", "operador de sistemas"],
    "manutencao":     ["técnico de manutenção", "eletricista", "encanador", "pedreiro",
                       "marceneiro", "serralheiro", "mecânico"],
    "limpeza":        ["gari", "agente de limpeza", "auxiliar de serviços gerais",
                       "zelador", "agente de conservação"],
    "gari":           ["gari", "agente de limpeza pública", "auxiliar de serviços urbanos",
                       "agente de limpeza"],

    # Agropecuária
    "agricultura":    ["engenheiro agrônomo", "técnico agrícola", "zootecnista",
                       "técnico em agropecuária", "extensionista rural"],
    "agronomo":       ["engenheiro agrônomo", "técnico agrícola", "agrônomo",
                       "técnico em agropecuária"],

    # Comunicação / Cultura
    "comunicacao":    ["jornalista", "relações públicas", "assessor de comunicação",
                       "técnico em comunicação", "publicitário", "radialista"],
    "cultura":        ["auxiliar de biblioteca", "bibliotecário", "museólogo",
                       "agente cultural", "técnico em assuntos culturais"],

    # Saúde Animal / Zoonoses
    "zoonoses":       ["agente de zoonoses", "agente de endemias", "médico veterinário",
                       "técnico em zoonoses", "auxiliar de zoonoses"],
    "agente":         ["agente administrativo", "agente comunitário de saúde",
                       "agente de endemias", "agente fiscal", "agente de trânsito",
                       "agente de segurança", "agente cultural"],
}

# Aliases — termos alternativos que mapeiam para a mesma chave
ALIASES: dict[str, str] = {
    "medico": "medico",
    "medicina": "medico",
    "clinico": "medico",
    "enfermeiro": "enfermagem",
    "farmaceutico": "farmacia",
    "dentista": "odonto",
    "odontologo": "odonto",
    "fisioterapeuta": "fisio",
    "nutricionista": "nutricao",
    "psicologo": "psicologia",
    "vet": "veterinario",
    "informatica": "informatica",
    "computacao": "ti",
    "dev": "programacao",
    "desenvolvedor": "programacao",
    "eng": "engenharia",
    "engenheiro": "engenharia",
    "arq": "arquitetura",
    "arquiteto": "arquitetura",
    "prof": "professor",
    "adm": "administrativo",
    "administracao": "gestao",
    "rhu": "rh",
    "contabil": "contabilidade",
    "financeiro": "financas",
    "auditoria": "auditoria",
    "pm": "policia",
    "pc": "policia",
    "guarda civil": "guarda",
    "meio ambiente": "ambiental",
    "assistencia social": "social",
    "servico social": "social",
    "agronomo": "agronomo",
    "agronomia": "agricultura",
    "jornalismo": "comunicacao",
    "biblioteca": "cultura",
}


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFD", texto.lower().strip())
    return "".join(c for c in texto if unicodedata.category(c) != "Mn")


def _similaridade(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _busca_fuzzy(query_norm: str) -> list[str] | None:
    """
    Encontra a entrada mais próxima no dicionário por similaridade de string.
    Só retorna se a similaridade for >= 0.75 (evita falsos positivos).
    """
    melhor_chave = None
    melhor_score = 0.0

    for chave in EXPANSOES:
        score = _similaridade(query_norm, chave)
        if score > melhor_score:
            melhor_score = score
            melhor_chave = chave

    if melhor_score >= 0.75 and melhor_chave:
        logger.debug(f"Fuzzy match: '{query_norm}' → '{melhor_chave}' ({melhor_score:.2f})")
        return EXPANSOES[melhor_chave]
    return None


def expandir_query_cargo(query: str) -> list[str]:
    """
    Expande um termo de busca em cargos relacionados.

    Ordem de resolução:
      1. Match exato no dicionário
      2. Alias → chave do dicionário
      3. Busca fuzzy (similaridade ≥ 0.75)
      4. Verifica se o termo está contido em alguma chave (substring)
      5. Fallback: retorna só o termo original (busca simples)
    """
    if not query or not query.strip():
        return []

    query = query.strip()
    query_norm = _normalizar(query)

    # 1. Match exato
    if query_norm in EXPANSOES:
        termos = EXPANSOES[query_norm]
        logger.info(f"Expansão exata: '{query}' → {len(termos)} termos")
        return _garantir_original(termos, query)

    # 2. Alias
    chave_alias = ALIASES.get(query_norm)
    if chave_alias and chave_alias in EXPANSOES:
        termos = EXPANSOES[chave_alias]
        logger.info(f"Expansão via alias: '{query}' → '{chave_alias}' → {len(termos)} termos")
        return _garantir_original(termos, query)

    # 3. Fuzzy
    termos_fuzzy = _busca_fuzzy(query_norm)
    if termos_fuzzy:
        logger.info(f"Expansão fuzzy: '{query}' → {len(termos_fuzzy)} termos")
        return _garantir_original(termos_fuzzy, query)

    # 4. Substring: "civil" → acharia "engenheiro civil"
    termos_sub: list[str] = []
    for chave, termos_chave in EXPANSOES.items():
        if query_norm in chave or chave in query_norm:
            termos_sub.extend(termos_chave)
    if termos_sub:
        # Deduplica mantendo ordem
        vistos: set[str] = set()
        unicos = []
        for t in termos_sub:
            if t not in vistos:
                vistos.add(t)
                unicos.append(t)
        logger.info(f"Expansão substring: '{query}' → {len(unicos)} termos")
        return _garantir_original(unicos[:15], query)

    # 5. Fallback
    logger.debug(f"Sem expansão para '{query}' — busca literal")
    return [query.lower()]


def _garantir_original(termos: list[str], query: str) -> list[str]:
    """Garante que o termo original está na lista (para matches exatos também funcionarem)."""
    q = query.lower()
    if q not in termos:
        return [q] + list(termos)
    return list(termos)


# ── Dicionário de expansão semântica de ÓRGÃOS ───────────────────────────────
# Chave: termos que o usuário pode digitar (normalizados)
# Valor: substrings que aparecem em nomes de órgãos nos editais
EXPANSOES_ORGAO: dict[str, list[str]] = {

    # Poder Municipal
    "prefeitura":     ["prefeitura", "câmara municipal", "camara municipal",
                       "municipio", "município"],
    "camara":         ["câmara municipal", "camara municipal", "câmara de vereadores",
                       "legislativo municipal"],
    "municipal":      ["prefeitura", "câmara municipal", "secretaria municipal",
                       "fundo municipal", "autarquia municipal"],

    # Saneamento / Água e Esgoto
    "saae":           ["saae", "saemae", "semae", "saelg", "saec", "saaeb",
                       "serviço autônomo de água", "serviço de abastecimento"],
    "saneamento":     ["saae", "semae", "dae", "saemae", "sanepar", "copasa",
                       "corsan", "sabesp", "caern", "cagepa", "compesa",
                       "saneamento", "água e esgoto", "saaeg", "dmae"],
    "agua":           ["saae", "dae", "semae", "água e esgoto", "abastecimento",
                       "saneamento", "copasa", "sanepar", "sabesp"],
    "dae":            ["dae", "departamento de água", "serviço de água"],

    # Saúde Pública
    "hospital":       ["hospital", "upa", "unidade de pronto", "hmu", "santa casa",
                       "fundação hospitalar", "regional de saúde"],
    "saude":          ["secretaria de saúde", "hospital", "upa", "santa casa",
                       "fundo de saúde", "ses", "sesa", "sesab", "sesac",
                       "fundação de saúde", "hmu", "unidade de saúde"],

    # Educação
    "escola":         ["secretaria de educação", "escola", "seduc", "sme",
                       "fundação de educação", "fundo de educação"],
    "educacao":       ["secretaria de educação", "seduc", "sme", "escola",
                       "fundação educacional", "instituto federal", "ifpr", "ifsp",
                       "ifba", "ifrn", "ifmg", "iff", "cefet"],
    "instituto federal": ["instituto federal", "ifpr", "ifsp", "ifba", "ifrn",
                          "ifmg", "iff", "cefet", "if "],

    # Poder Judiciário / Ministério Público
    "tribunal":       ["tribunal", "tjsp", "tjmg", "tjrj", "tjrs", "tjpr", "tjba",
                       "tjpe", "tjsc", "trt", "tre", "trf", "tse", "stj", "stf",
                       "tribunal de justiça", "tribunal regional"],
    "tj":             ["tribunal de justiça", "tjsp", "tjmg", "tjrj", "tjrs",
                       "tjpr", "tjba", "tjpe", "tjsc", "tjgo", "tjpa"],
    "trt":            ["tribunal regional do trabalho", "trt"],
    "tre":            ["tribunal regional eleitoral", "tre"],
    "mp":             ["ministério público", "mp", "promotoria", "procuradoria",
                       "mpsp", "mprj", "mpmg", "mprs", "mpba"],
    "ministerio publico": ["ministério público", "procuradoria", "mpsp", "mprj",
                           "mpmg", "mprs", "mpba"],

    # Poder Legislativo Estadual/Federal
    "assembleia":     ["assembleia legislativa", "ale", "alerj", "alesp", "alemg",
                       "alers", "alego", "aleba"],
    "senado":         ["senado federal", "senado"],
    "camara federal": ["câmara dos deputados", "camara dos deputados"],

    # Segurança Pública
    "policia":        ["polícia civil", "policia civil", "polícia militar", "policia militar",
                       "ssp", "secretaria de segurança", "dgp", "pcdf", "pmdf"],
    "bombeiro":       ["bombeiro", "corpo de bombeiros", "cbm", "cbmsp", "cbmrj"],
    "detran":         ["detran", "departamento de trânsito", "departamento estadual de trânsito"],

    # Receita / Finanças
    "receita":        ["receita federal", "secretaria da fazenda", "sefaz", "sefin",
                       "fisco", "receita estadual"],
    "fazenda":        ["secretaria da fazenda", "sefaz", "sefin", "fazenda estadual",
                       "receita estadual"],

    # Previdência / INSS
    "inss":           ["inss", "previdência social", "instituto nacional do seguro"],
    "previdencia":    ["inss", "previdência social", "iprev", "ipsm", "funprev",
                       "instituto de previdência"],

    # Meio Ambiente / Agências
    "ibama":          ["ibama", "instituto brasileiro do meio ambiente"],
    "icmbio":         ["icmbio", "instituto chico mendes", "chico mendes"],
    "ambiental":      ["ibama", "icmbio", "secretaria do meio ambiente", "sema",
                       "inea", "feam", "ima", "iema", "agência ambiental"],

    # Agências Reguladoras / Federais
    "aneel":          ["aneel", "agência nacional de energia"],
    "anvisa":         ["anvisa", "agência nacional de vigilância"],
    "antt":           ["antt", "agência nacional de transportes terrestres"],
    "agencia":        ["agência", "aneel", "antt", "anvisa", "ana", "anac",
                       "anp", "antaq", "anatel"],

    # Institutos de Pesquisa
    "ibge":           ["ibge", "instituto brasileiro de geografia"],
    "embrapa":        ["embrapa", "empresa brasileira de pesquisa agropecuária"],
    "fiocruz":        ["fiocruz", "fundação oswaldo cruz"],

    # Bancos / Financeiras
    "banco":          ["banco do brasil", "caixa econômica", "caixa economica",
                       "bndes", "banrisul", "banpará", "banese", "brb", "badesc",
                       "banco central", "bacen"],
    "caixa":          ["caixa econômica federal", "caixa economica federal", "cef"],

    # Energia / Infraestrutura
    "energia":        ["cemig", "ceee", "celpe", "copel", "coelba", "celg",
                       "ceron", "eletroacre", "eletrobrás", "enersul",
                       "companhia de energia", "eletropaulo"],
    "eletrico":       ["cemig", "ceee", "celpe", "copel", "coelba", "celg",
                       "eletrobrás", "companhia de energia"],

    # Transportes
    "metro":          ["metrô", "metro", "companhia do metropolitano", "cbtu"],
    "transporte":     ["detran", "der", "dner", "dnit", "cbtu", "metrô",
                       "secretaria de transportes", "companhia de transportes"],

    # Correios
    "correios":       ["correios", "empresa brasileira de correios", "ecf", "ect"],

    # Habitação / Urbanismo
    "cohab":          ["cohab", "companhia de habitação", "habitação popular",
                       "secretaria de habitação", "cdhu"],

    # Defensoria / OAB
    "defensoria":     ["defensoria pública", "dpge", "dpu", "defensoria",
                       "núcleo de defensoria"],

    # Poder Executivo Estadual
    "governo estadual": ["governo do estado", "secretaria de estado", "gerência",
                         "superintendência estadual"],
    "secretaria":     ["secretaria municipal", "secretaria de estado",
                       "secretaria estadual", "secretaria de saúde",
                       "secretaria de educação", "secretaria de fazenda",
                       "secretaria de segurança"],

    # Consórcios / Autarquias
    "consorcio":      ["consórcio", "consorcio intermunicipal", "cigres", "cisa"],
    "autarquia":      ["autarquia", "saae", "dae", "iprem", "ipremn", "ipsm",
                       "damu", "ipsc"],

    # Fundações
    "fundacao":       ["fundação", "funprev", "fapesb", "fapesp", "fapemig",
                       "fundação hospitalar", "fundação de saúde", "fundação educacional"],
}

# Aliases para órgãos
ALIASES_ORGAO: dict[str, str] = {
    "pref":          "prefeitura",
    "pm":            "prefeitura",
    "cm":            "camara",
    "vereadores":    "camara",
    "agua esgoto":   "saneamento",
    "esgoto":        "saneamento",
    "abastecimento": "agua",
    "hosp":          "hospital",
    "upa":           "hospital",
    "ubs":           "saude",
    "sus":           "saude",
    "escola":        "escola",
    "if":            "instituto federal",
    "cefet":         "instituto federal",
    "tj":            "tj",
    "trf":           "tribunal",
    "tst":           "tribunal",
    "stj":           "tribunal",
    "stf":           "tribunal",
    "mp":            "mp",
    "mpu":           "ministerio publico",
    "pc":            "policia",
    "pm militar":    "policia",
    "ssp":           "policia",
    "cb":            "bombeiro",
    "sefaz":         "fazenda",
    "prev":          "previdencia",
    "iprev":         "previdencia",
    "eletrobras":    "energia",
    "cemig":         "energia",
    "copel":         "energia",
    "ceee":          "energia",
    "cef":           "caixa",
    "bb":            "banco",
    "bacen":         "banco",
    "ct":            "correios",
    "dpge":          "defensoria",
    "dpu":           "defensoria",
    "der":           "transporte",
    "dnit":          "transporte",
    "det":           "detran",
}


def _busca_fuzzy_orgao(query_norm: str) -> list[str] | None:
    """Fuzzy match no dicionário de órgãos (threshold 0.75)."""
    melhor_chave = None
    melhor_score = 0.0
    for chave in EXPANSOES_ORGAO:
        score = _similaridade(query_norm, chave)
        if score > melhor_score:
            melhor_score = score
            melhor_chave = chave
    if melhor_score >= 0.75 and melhor_chave:
        logger.debug(f"Fuzzy orgao: '{query_norm}' → '{melhor_chave}' ({melhor_score:.2f})")
        return EXPANSOES_ORGAO[melhor_chave]
    return None


def expandir_query_orgao(query: str) -> list[str]:
    """
    Expande um termo de busca de órgão em substrings relacionadas.

    Ordem de resolução:
      1. Match exato no dicionário de órgãos
      2. Alias → chave do dicionário
      3. Busca fuzzy (similaridade ≥ 0.75)
      4. Verifica se o termo está contido em alguma chave (substring)
      5. Fallback: retorna só o termo original (busca simples)
    """
    if not query or not query.strip():
        return []

    query = query.strip()
    query_norm = _normalizar(query)

    # 1. Match exato
    if query_norm in EXPANSOES_ORGAO:
        termos = EXPANSOES_ORGAO[query_norm]
        logger.info(f"Expansão orgao exata: '{query}' → {len(termos)} termos")
        return _garantir_original(termos, query)

    # 2. Alias
    chave_alias = ALIASES_ORGAO.get(query_norm)
    if chave_alias and chave_alias in EXPANSOES_ORGAO:
        termos = EXPANSOES_ORGAO[chave_alias]
        logger.info(f"Expansão orgao via alias: '{query}' → '{chave_alias}' → {len(termos)} termos")
        return _garantir_original(termos, query)

    # 3. Fuzzy
    termos_fuzzy = _busca_fuzzy_orgao(query_norm)
    if termos_fuzzy:
        logger.info(f"Expansão orgao fuzzy: '{query}' → {len(termos_fuzzy)} termos")
        return _garantir_original(termos_fuzzy, query)

    # 4. Substring
    termos_sub: list[str] = []
    for chave, termos_chave in EXPANSOES_ORGAO.items():
        if query_norm in chave or chave in query_norm:
            termos_sub.extend(termos_chave)
    if termos_sub:
        vistos: set[str] = set()
        unicos = []
        for t in termos_sub:
            if t not in vistos:
                vistos.add(t)
                unicos.append(t)
        logger.info(f"Expansão orgao substring: '{query}' → {len(unicos)} termos")
        return _garantir_original(unicos[:15], query)

    # 5. Fallback
    logger.debug(f"Sem expansão orgao para '{query}' — busca literal")
    return [query.lower()]
