"""
Geocodificação de vagas para o mapa.

Estratégia:
  1. Lookup exato por município (tabela com capitais + municípios frequentes)
  2. Fallback para centroide do estado + jitter para evitar sobreposição
"""

import hashlib
import math
import re
from typing import Optional

# Centroides aproximados de cada UF (lat, lng)
UF_CENTROIDES: dict[str, tuple[float, float]] = {
    "AC": (-9.024,  -70.812),
    "AL": (-9.571,  -36.782),
    "AM": (-3.417,  -65.856),
    "AP": ( 1.410,  -51.770),
    "BA": (-12.580, -41.701),
    "CE": (-5.498,  -39.321),
    "DF": (-15.800, -47.865),
    "ES": (-19.183, -40.309),
    "GO": (-15.827, -49.836),
    "MA": (-4.961,  -45.274),
    "MG": (-18.512, -44.555),
    "MS": (-20.772, -54.785),
    "MT": (-12.682, -56.921),
    "PA": (-3.417,  -52.291),
    "PB": (-7.240,  -36.782),
    "PE": (-8.814,  -36.954),
    "PI": (-7.718,  -42.729),
    "PR": (-24.890, -51.550),
    "RJ": (-22.910, -43.173),
    "RN": (-5.813,  -36.203),
    "RO": (-11.506, -63.581),
    "RR": ( 1.991,  -61.330),
    "RS": (-30.035, -51.218),
    "SC": (-27.242, -50.219),
    "SE": (-10.574, -37.386),
    "SP": (-22.907, -48.446),
    "TO": (-10.175, -48.298),
}

# Municípios: nome normalizado → (lat, lng)
# Inclui todas as capitais + municípios mais populosos por estado
MUNICIPIOS: dict[str, tuple[float, float]] = {
    # Capitais
    "rio branco":          (-9.975,  -67.824),
    "maceio":              (-9.666,  -35.735),
    "macapa":              ( 0.034,  -51.069),
    "manaus":              (-3.119,  -60.021),
    "salvador":            (-12.971, -38.501),
    "fortaleza":           (-3.717,  -38.543),
    "brasilia":            (-15.780, -47.929),
    "vitoria":             (-20.319, -40.337),
    "goiania":             (-16.686, -49.265),
    "sao luis":            (-2.530,  -44.303),
    "belo horizonte":      (-19.917, -43.934),
    "campo grande":        (-20.469, -54.620),
    "cuiaba":              (-15.601, -56.098),
    "belem":               (-1.455,  -48.490),
    "joao pessoa":         (-7.115,  -34.863),
    "recife":              (-8.054,  -34.881),
    "teresina":            (-5.089,  -42.803),
    "curitiba":            (-25.429, -49.271),
    "rio de janeiro":      (-22.906, -43.172),
    "natal":               (-5.795,  -35.209),
    "porto velho":         (-8.760,  -63.900),
    "boa vista":           ( 2.819,  -60.673),
    "porto alegre":        (-30.033, -51.230),
    "florianopolis":       (-27.597, -48.549),
    "aracaju":             (-10.909, -37.044),
    "sao paulo":           (-23.550, -46.633),
    "palmas":              (-10.184, -48.334),

    # SP — maiores municípios
    "campinas":            (-22.905, -47.063),
    "guarulhos":           (-23.453, -46.533),
    "sao bernardo do campo":(-23.694,-46.565),
    "santo andre":         (-23.663, -46.533),
    "osasco":              (-23.533, -46.791),
    "ribeirao preto":      (-21.177, -47.810),
    "sorocaba":            (-23.501, -47.458),
    "sao jose dos campos": (-23.179, -45.886),
    "santos":              (-23.960, -46.334),
    "mogi das cruzes":     (-23.521, -46.185),
    "diadema":             (-23.686, -46.621),
    "jundiai":             (-23.185, -46.884),
    "piracicaba":          (-22.724, -47.649),
    "bauru":               (-22.314, -49.060),
    "indaiatuba":          (-23.090, -47.219),
    "limeira":             (-22.564, -47.401),
    "sao jose do rio preto":(-20.814,-49.379),
    "marilia":             (-22.213, -49.946),
    "franca":              (-20.539, -47.401),

    # MG
    "uberlandia":          (-18.918, -48.277),
    "contagem":            (-19.932, -44.053),
    "juiz de fora":        (-21.764, -43.350),
    "montes claros":       (-16.728, -43.862),
    "uberaba":             (-19.747, -47.931),
    "betim":               (-19.968, -44.198),
    "governador valadares": (-18.854,-41.949),
    "ipatinga":            (-19.468, -42.537),
    "passos":              (-20.718, -46.610),
    "blumenau":            (-26.919, -49.066),

    # RJ
    "nova iguacu":         (-22.759, -43.451),
    "duque de caxias":     (-22.786, -43.312),
    "sao goncalo":         (-22.827, -43.054),
    "niteroi":             (-22.883, -43.104),
    "campos dos goytacazes":(-21.750,-41.330),
    "petropolis":          (-22.505, -43.178),

    # RS
    "caxias do sul":       (-29.168, -51.179),
    "pelotas":             (-31.771, -52.342),
    "canoas":              (-29.917, -51.183),
    "santa maria":         (-29.684, -53.807),
    "novo hamburgo":       (-29.679, -51.131),
    "sao leopoldo":        (-29.760, -51.148),

    # PR
    "londrina":            (-23.310, -51.162),
    "maringa":             (-23.420, -51.933),
    "ponta grossa":        (-25.096, -50.162),
    "cascavel":            (-24.956, -53.456),
    "sao jose dos pinhais":(-25.535,-49.208),
    "foz do iguacu":       (-25.547, -54.588),

    # SC
    "joinville":           (-26.304, -48.847),
    "blumenau":            (-26.919, -49.066),
    "sao jose":            (-27.594, -48.635),
    "chapeco":             (-27.101, -52.614),
    "itajai":              (-26.907, -48.661),

    # BA
    "feira de santana":    (-12.252, -38.967),
    "vitoria da conquista": (-14.866,-40.844),
    "camacari":            (-12.699, -38.324),
    "ilheus":              (-14.789, -39.047),
    "itabuna":             (-14.786, -39.280),

    # PE
    "caruaru":             (-8.276,  -35.976),
    "olinda":              (-7.999,  -34.854),
    "jaboatao dos guararapes":(-8.113,-35.006),
    "paulista":            (-7.940,  -34.863),
    "camarajibe":          (-8.023,  -35.032),

    # CE
    "caucaia":             (-3.737,  -38.658),
    "juazeiro do norte":   (-7.213,  -39.315),
    "sobral":              (-3.689,  -40.350),
    "crato":               (-7.234,  -39.409),

    # GO
    "aparecida de goiania": (-16.823,-49.247),
    "anapolis":            (-16.327, -48.952),
    "rio verde":           (-17.798, -50.928),
    "luziania":            (-16.252, -47.954),

    # MA
    "imperatriz":          (-5.519,  -47.491),
    "timon":               (-5.094,  -42.836),
    "caxias":              (-4.862,  -43.357),

    # PA
    "ananindeua":          (-1.365,  -48.372),
    "santarem":            (-2.444,  -54.708),
    "maraba":              (-5.368,  -49.117),
    "castanhal":           (-1.294,  -47.926),

    # AM
    "parintins":           (-2.627,  -56.736),
    "itacoatiara":         (-3.143,  -58.444),
    "manacapuru":          (-3.299,  -60.621),

    # MT
    "varzea grande":       (-15.647, -56.133),
    "rondonopolis":        (-16.470, -54.636),
    "sinop":               (-11.862, -55.502),

    # MS
    "dourados":            (-22.221, -54.805),
    "tres lagoas":         (-20.786, -51.700),
    "corumba":             (-19.009, -57.650),

    # RN
    "mossoro":             (-5.187,  -37.344),
    "caicara":             (-6.450,  -37.099),
    "parnamirim":          (-5.914,  -35.264),

    # PB
    "campina grande":      (-7.230,  -35.881),
    "santa rita":          (-7.114,  -34.978),
    "bayeux":              (-7.125,  -34.938),

    # AL
    "arapiraca":           (-9.752,  -36.660),
    "palmeira dos indios":  (-9.408, -36.632),

    # SE
    "lagarto":             (-10.914, -37.656),
    "itabaiana":           (-10.686, -37.425),

    # PI
    "parnaiba":            (-2.905,  -41.776),
    "picos":               (-7.077,  -41.467),

    # RO
    "ji-parana":           (-10.886, -61.957),
    "ariquemes":           (-9.912,  -63.037),
    "cacoal":              (-11.439, -61.447),

    # TO
    "araguaina":           (-7.192,  -48.207),
    "gurupi":              (-11.731, -49.069),

    # AP
    "santana":             ( 0.058,  -51.172),
    "laranjal do jari":    (-0.797,  -52.454),

    # AC
    "cruzeiro do sul":     (-7.630,  -72.670),
    "sena madureira":      (-9.066,  -68.658),

    # RR
    "rorainopolis":        ( 0.943,  -60.431),
    "caracarai":           ( 1.825,  -61.128),
}


def _normalizar(texto: str) -> str:
    """Remove acentos e converte para minúsculas."""
    import unicodedata
    texto = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in texto if unicodedata.category(c) != "Mn")


def _jitter(lat: float, lng: float, seed: str, raio_graus: float = 0.5) -> tuple[float, float]:
    """
    Aplica deslocamento determinístico pequeno a (lat, lng) baseado em um seed.
    Garante que vagas do mesmo estado não se sobreponham no mapa.
    """
    h = int(hashlib.md5(seed.encode()).hexdigest(), 16)
    # Ângulo e distância pseudo-aleatórios baseados no hash
    angle = (h % 360) * math.pi / 180
    dist = ((h >> 8) % 100) / 100 * raio_graus
    return (
        lat + dist * math.sin(angle),
        lng + dist * math.cos(angle),
    )


def geocodificar(municipio: str, uf: str, seed: str = "") -> tuple[float, float]:
    """
    Retorna (lat, lng) para um município/UF.
    - Tenta lookup exato no municipio
    - Fallback: centroide da UF + jitter determinístico
    """
    if municipio:
        chave = _normalizar(municipio)
        # Remove sufixos comuns
        chave = re.sub(r'\s*[-/]\s*[a-z]{2}$', '', chave)
        if chave in MUNICIPIOS:
            return MUNICIPIOS[chave]

    # Fallback: centroide do estado
    uf_upper = uf.upper().strip()
    base = UF_CENTROIDES.get(uf_upper, (-15.78, -47.93))  # default: Brasília

    # Jitter para separar visualmente vagas do mesmo estado
    if seed:
        return _jitter(base[0], base[1], seed)
    return base
