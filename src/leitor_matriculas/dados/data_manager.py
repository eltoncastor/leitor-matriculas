"""
data_manager.py

Camada responsável por carregar e consultar as bases de apoio em XLSX:

    dados/Colaboradores.xlsx
    dados/Motivos.xlsx
    dados/Gestores.xlsx

`dados/Auxiliares.xlsx` (nomes de Auxiliar de Prevenção de Perdas) pode
existir na pasta, mas NÃO é lido aqui de propósito: o nome do auxiliar,
quando anotado junto ao gestor no campo Responsável, não faz parte do
resultado final (não vai pra planilha) -- ver `correspondencia_aproximada.
resolver_responsavel`, que só usa esse texto residual para não contaminar
a identificação do gestor, e descarta o resto.

IMPORTANTE — leia antes de mexer aqui:

Os arquivos XLSX reais são fornecidos pelo usuário em `dados/`, fora do
controle de versão. NADA aqui é baseado em suposições sobre nomes de
colunas/abas fixos — tudo usa os dicionários `COLUNAS_CANDIDATAS_*` logo
abaixo, que devem ser ajustados (não a lógica ao redor) se um arquivo real
usar cabeçalhos diferentes.

Princípios seguidos neste arquivo:
    - Matrícula é SEMPRE tratada como texto (nunca int/float).
    - Nenhum arquivo ausente ou malformado derruba o programa: os erros são
      guardados em `DataManager.avisos` (lista de strings) para quem chamar
      decidir como mostrar ao usuário (a interface mostra isso na tela).
    - Nada aqui modifica os arquivos .xlsx originais (abertura em modo
      somente leitura).
"""

import os
import unicodedata
from typing import Dict, List, Optional

try:
    import openpyxl
except ImportError:  # pragma: no cover - só acontece se a dependência faltar
    openpyxl = None


# ---------------------------------------------------------------------------
# CONFIGURAÇÃO FLEXÍVEL DE COLUNAS
#
# Como ainda não recebemos os arquivos reais, listamos aqui vários nomes de
# cabeçalho plausíveis para cada campo. A busca por coluna ignora maiúsculas/
# minúsculas e acentos. Quando os XLSX reais chegarem, ajuste estas listas
# (ou adicione o nome exato usado na planilha) em vez de mexer no resto do
# arquivo.
# ---------------------------------------------------------------------------

COLUNAS_CANDIDATAS_COLABORADORES = {
    "matricula": ["matricula", "matrícula", "matricula colaborador", "registro", "re", "codigo", "código", "cod"],
    "nome": ["nome", "nome colaborador", "colaborador", "funcionario", "funcionário"],
    "cargo": ["cargo", "funcao", "função"],
    "setor": ["setor", "departamento", "área", "area"],
}

COLUNAS_CANDIDATAS_MOTIVOS = {
    "motivo": ["motivo", "motivos", "descricao", "descrição", "nome"],
}

COLUNAS_CANDIDATAS_GESTORES = {
    "gestor": ["gestor", "gestores", "nome", "responsavel", "responsável", "supervisor"],
}


# ---------------------------------------------------------------------------
# Helpers de baixo nível
# ---------------------------------------------------------------------------

def _normalizar_cabecalho(texto) -> str:
    """Deixa um cabeçalho pronto para comparação: minúsculo, sem acento, sem espaços nas pontas."""
    if texto is None:
        return ""
    texto = str(texto).strip().lower()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    return texto


def _encontrar_coluna(cabecalhos: List[str], candidatos: List[str]) -> Optional[int]:
    """
    Procura, entre os cabeçalhos de uma planilha, qual coluna (índice,
    começando em 0) corresponde a um dos nomes candidatos. Retorna None se
    não encontrar nenhuma correspondência.
    """
    cabecalhos_normalizados = [_normalizar_cabecalho(c) for c in cabecalhos]
    candidatos_normalizados = [_normalizar_cabecalho(c) for c in candidatos]

    for indice, cabecalho in enumerate(cabecalhos_normalizados):
        if cabecalho in candidatos_normalizados:
            return indice
    return None


def _celula_para_texto(valor) -> str:
    """
    Converte o valor de uma célula do Excel para texto, de forma segura
    para matrícula (nunca vira int) e sem sobras do tipo "30244.0".

    Limitação importante e conhecida: se a matrícula já foi salva no XLSX
    como número (não como texto), o Excel/openpyxl pode ter descartado
    zeros à esquerda ANTES mesmo de chegarmos aqui — isso é um problema da
    origem dos dados, não algo que o código consiga recuperar sozinho. Essa
    é uma das coisas a verificar na segunda etapa, com o arquivo real em
    mãos (ver seção de zeros à esquerda no README).
    """
    if valor is None:
        return ""
    if isinstance(valor, float):
        if valor.is_integer():
            return str(int(valor))
        return str(valor)
    if isinstance(valor, int):
        return str(valor)
    return str(valor).strip()


def _abrir_planilha(caminho: str, aba: Optional[str] = None):
    """
    Abre um arquivo XLSX em modo somente leitura (nunca modifica o
    arquivo original) e devolve a worksheet a ser usada.

    Levanta FileNotFoundError com mensagem amigável se o arquivo não
    existir, e RuntimeError se o arquivo existir mas não puder ser lido
    (corrompido, formato inesperado, etc.).
    """
    if openpyxl is None:
        raise RuntimeError(
            "A biblioteca 'openpyxl' não está instalada. Rode: pip install -r requirements.txt"
        )

    if not os.path.isfile(caminho):
        raise FileNotFoundError(f"Arquivo não encontrado: {caminho}")

    try:
        workbook = openpyxl.load_workbook(caminho, read_only=True, data_only=True)
    except Exception as exc:
        raise RuntimeError(f"Não foi possível ler o arquivo XLSX '{caminho}': {exc}") from exc

    try:
        return workbook[aba] if aba else workbook.active
    except KeyError as exc:
        raise RuntimeError(f"Aba '{aba}' não encontrada em '{caminho}'.") from exc


def _ler_cabecalho_e_linhas(worksheet):
    """
    Lê a primeira linha como cabeçalho e devolve (cabecalhos, linhas), onde
    `linhas` é um gerador com as linhas seguintes (cada uma como tupla de
    valores). Funciona mesmo se a planilha estiver vazia.
    """
    linhas_iter = worksheet.iter_rows(values_only=True)
    try:
        cabecalhos = next(linhas_iter)
    except StopIteration:
        return [], iter(())

    cabecalhos = ["" if c is None else str(c) for c in cabecalhos]
    return cabecalhos, linhas_iter


# ---------------------------------------------------------------------------
# Leitura de cada base
# ---------------------------------------------------------------------------

def _ler_colaboradores(caminho: str, aba: Optional[str] = None) -> Dict[str, dict]:
    """
    Lê Colaboradores.xlsx e devolve um dicionário:
        { "matricula_como_texto": {"matricula": ..., "nome": ..., "cargo": ..., "setor": ...}, ... }

    A coluna de matrícula é OBRIGATÓRIA (sem ela não há como consultar
    nada); nome/cargo/setor são opcionais — se não forem encontrados,
    ficam como string vazia.
    """
    worksheet = _abrir_planilha(caminho, aba)
    cabecalhos, linhas = _ler_cabecalho_e_linhas(worksheet)

    if not cabecalhos:
        raise ValueError(f"'{caminho}' está vazio (sem cabeçalho).")

    candidatos = COLUNAS_CANDIDATAS_COLABORADORES
    idx_matricula = _encontrar_coluna(cabecalhos, candidatos["matricula"])
    if idx_matricula is None:
        raise ValueError(
            "Coluna de matrícula não encontrada em Colaboradores.xlsx. "
            f"Cabeçalhos encontrados: {cabecalhos}. "
            "Ajuste COLUNAS_CANDIDATAS_COLABORADORES em data_manager.py com o nome real da coluna."
        )

    idx_nome = _encontrar_coluna(cabecalhos, candidatos["nome"])
    idx_cargo = _encontrar_coluna(cabecalhos, candidatos["cargo"])
    idx_setor = _encontrar_coluna(cabecalhos, candidatos["setor"])

    def _valor(linha, idx):
        if idx is None or idx >= len(linha):
            return ""
        return _celula_para_texto(linha[idx])

    colaboradores: Dict[str, dict] = {}
    for linha in linhas:
        if linha is None or all(v is None for v in linha):
            continue  # linha completamente vazia

        matricula = _valor(linha, idx_matricula)
        if not matricula:
            continue  # sem matrícula, não dá para indexar essa linha

        colaboradores[matricula] = {
            "matricula": matricula,
            "nome": _valor(linha, idx_nome),
            "cargo": _valor(linha, idx_cargo),
            "setor": _valor(linha, idx_setor),
        }

    return colaboradores


def _ler_lista_simples(caminho: str, colunas_candidatas: List[str], aba: Optional[str] = None) -> List[str]:
    """
    Lê um XLSX de lista simples (Motivos.xlsx ou Gestores.xlsx) e devolve
    uma lista de textos, na ordem em que aparecem, sem duplicatas e sem
    valores vazios.

    Procura primeiro uma coluna com nome conhecido (`colunas_candidatas`);
    se não achar, usa a primeira coluna (A) — isso cobre tanto uma
    planilha com cabeçalho quanto uma lista "crua" de valores.
    """
    worksheet = _abrir_planilha(caminho, aba)
    cabecalhos, linhas = _ler_cabecalho_e_linhas(worksheet)

    if not cabecalhos:
        return []

    idx_coluna = _encontrar_coluna(cabecalhos, colunas_candidatas)

    valores: List[str] = []
    vistos = set()

    if idx_coluna is not None:
        # Encontramos uma coluna com nome conhecido: cabecalhos[0] era
        # mesmo um cabeçalho, e os valores começam na linha seguinte.
        for linha in linhas:
            if linha is None or idx_coluna >= len(linha):
                continue
            valor = _celula_para_texto(linha[idx_coluna])
            if valor and valor not in vistos:
                vistos.add(valor)
                valores.append(valor)
    else:
        # Nenhuma coluna reconhecida: tratamos a primeira célula de cada
        # linha (incluindo a que tínhamos lido como "cabeçalho") como dado,
        # para o caso de a planilha ser só uma lista sem cabeçalho.
        candidatas = [cabecalhos[0]] if cabecalhos else []
        candidatas += [linha[0] if linha else None for linha in linhas]
        for valor_bruto in candidatas:
            valor = _celula_para_texto(valor_bruto)
            if valor and valor not in vistos:
                vistos.add(valor)
                valores.append(valor)

    return valores


# ---------------------------------------------------------------------------
# DataManager
# ---------------------------------------------------------------------------

class DataManager:
    """
    Carrega, na criação do objeto, as três bases de apoio (Colaboradores,
    Motivos, Gestores) a partir da pasta `dados/`, e oferece métodos de
    consulta simples.

    Nunca lança exceção para quem usa a classe: qualquer problema de
    carregamento (arquivo ausente, XLSX corrompido, coluna não encontrada,
    planilha vazia) fica registrado em `self.avisos` (lista de strings),
    para a interface decidir como mostrar isso ao usuário. As listas/
    dicionários correspondentes simplesmente ficam vazios nesse caso.
    """

    def __init__(self, pasta_dados: Optional[str] = None):
        # A pasta `dados/` com os XLSX reais fica na RAIZ do projeto, não
        # dentro do pacote. Este arquivo está em
        #     <raiz>/src/leitor_matriculas/dados/data_manager.py
        # logo a raiz são três níveis acima (dados -> leitor_matriculas ->
        # src -> raiz). Cuidado ao mover este módulo: o caminho depende da
        # profundidade dele dentro do pacote.
        raiz_projeto = os.path.abspath(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
        )
        self.pasta_dados = pasta_dados or os.path.join(raiz_projeto, "dados")

        self.colaboradores: Dict[str, dict] = {}
        self.motivos: List[str] = []
        self.gestores: List[str] = []
        self.avisos: List[str] = []

        self._carregar_colaboradores()
        self._carregar_motivos()
        self._carregar_gestores()

    # -- carregamento ---------------------------------------------------
    def _caminho(self, nome_arquivo: str) -> str:
        return os.path.join(self.pasta_dados, nome_arquivo)

    def _carregar_colaboradores(self):
        caminho = self._caminho("Colaboradores.xlsx")
        try:
            self.colaboradores = _ler_colaboradores(caminho)
            if not self.colaboradores:
                self.avisos.append(f"'{caminho}' foi lido, mas nenhum colaborador foi encontrado nele.")
        except FileNotFoundError:
            self.avisos.append(f"Colaboradores.xlsx não encontrado em: {caminho}")
        except Exception as exc:
            self.avisos.append(f"Não foi possível carregar Colaboradores.xlsx: {exc}")

    def _carregar_motivos(self):
        caminho = self._caminho("Motivos.xlsx")
        try:
            self.motivos = _ler_lista_simples(caminho, COLUNAS_CANDIDATAS_MOTIVOS["motivo"])
            if not self.motivos:
                self.avisos.append(f"'{caminho}' foi lido, mas nenhum motivo foi encontrado nele.")
        except FileNotFoundError:
            self.avisos.append(f"Motivos.xlsx não encontrado em: {caminho}")
        except Exception as exc:
            self.avisos.append(f"Não foi possível carregar Motivos.xlsx: {exc}")

    def _carregar_gestores(self):
        caminho = self._caminho("Gestores.xlsx")
        try:
            self.gestores = _ler_lista_simples(caminho, COLUNAS_CANDIDATAS_GESTORES["gestor"])
            if not self.gestores:
                self.avisos.append(f"'{caminho}' foi lido, mas nenhum gestor foi encontrado nele.")
        except FileNotFoundError:
            self.avisos.append(f"Gestores.xlsx não encontrado em: {caminho}")
        except Exception as exc:
            self.avisos.append(f"Não foi possível carregar Gestores.xlsx: {exc}")

    # -- status -----------------------------------------------------------
    @property
    def colaboradores_disponivel(self) -> bool:
        return bool(self.colaboradores)

    @property
    def motivos_disponivel(self) -> bool:
        return bool(self.motivos)

    @property
    def gestores_disponivel(self) -> bool:
        return bool(self.gestores)

    def resumo_status(self) -> str:
        """Uma linha curta pra mostrar na interface, ex.: 'Colaboradores: 812 | Motivos: 6 | Gestores: 13'."""
        return (
            f"Colaboradores: {len(self.colaboradores)} | "
            f"Motivos: {len(self.motivos)} | "
            f"Gestores: {len(self.gestores)}"
        )

    # -- consultas ----------------------------------------------------------
    def buscar_colaborador(self, matricula: str) -> Optional[dict]:
        """
        Busca um colaborador pela matrícula (texto). Retorna o dicionário
        {"matricula", "nome", "cargo", "setor"} se encontrado, ou None caso
        contrário (matrícula desconhecida NÃO é erro — pode ser colaborador
        novo ainda não cadastrado; cabe à revisão humana decidir).
        """
        if not matricula:
            return None
        return self.colaboradores.get(str(matricula).strip())

    def listar_motivos(self) -> List[str]:
        return list(self.motivos)

    def listar_gestores(self) -> List[str]:
        return list(self.gestores)
