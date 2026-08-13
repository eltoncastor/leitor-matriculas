"""
ui/mensagens.py

Tradução de uma falha técnica para a linguagem do operador (Fase 21a).

Motivo de existir: até aqui, quando algo dava errado, o que chegava à tela
era o texto da exceção e mais nada -- "Erro ao abrir imagem" com o
`str(exc)` do OpenCV embaixo. Isso responde "o que o programa viu", que é a
pergunta do programador, e não responde nenhuma das duas perguntas do
operador: **o que aconteceu** e **o que eu faço agora**.

É um módulo separado (e não mais um punhado de f-strings dentro de
`ui/app.py`) pelo mesmo motivo que `validacao/explicacao_revisao.py`
(que morava em `ui/` até a Fase 24c) é: é função PURA sobre texto, não
importa Tkinter, e portanto pode ser verificada sem abrir janela nenhuma.

O detalhe técnico NÃO é escondido -- ele vai no fim da mensagem, rotulado
como tal. Esconder seria trocar um problema (mensagem incompreensível) por
outro pior (impossível de diagnosticar quando o operador liga pedindo
ajuda). O que muda é a ORDEM e o PESO: primeiro o que aconteceu em
português, depois o que fazer, e só então o texto do erro.
"""

# Cada falha é descrita por: o que aconteceu (uma frase, sem jargão) e o
# que o operador pode fazer (passos concretos, na ordem em que valem a
# pena ser tentados). Os textos são deliberadamente específicos deste
# trabalho -- "a folha", "o PDF do mês", "o Excel" --, não genéricos.
FALHAS = {
    "imagem": {
        "titulo": "Não foi possível abrir a foto",
        "explicacao": (
            "O arquivo escolhido não pôde ser lido como imagem, então esta "
            "folha não foi processada."
        ),
        "acoes": [
            "Confira se o arquivo é mesmo uma foto (.jpg, .png ou .webp).",
            "Se a foto veio do celular, tente copiá-la de novo para o computador — "
            "uma cópia interrompida costuma dar exatamente este erro.",
            "Abra a foto no visualizador do Windows: se ela também não abrir lá, "
            "o arquivo está danificado e a folha precisa ser fotografada de novo.",
        ],
    },
    "pdf": {
        "titulo": "Não foi possível abrir o PDF",
        "explicacao": (
            "O arquivo escolhido não pôde ser aberto como PDF, então nenhuma "
            "folha foi processada."
        ),
        "acoes": [
            "Confira se o arquivo é mesmo um PDF e se terminou de ser copiado ou baixado.",
            "Tente abrir o mesmo arquivo no leitor de PDF do computador: "
            "se não abrir lá, ele está danificado.",
            "Se o PDF estiver protegido por senha, salve uma cópia sem senha e use essa cópia.",
        ],
    },
    "ocr": {
        "titulo": "Não foi possível ler o texto das folhas",
        "explicacao": (
            "O leitor de texto (OCR) não pôde ser iniciado ou falhou durante a "
            "leitura, então as folhas não foram reconhecidas."
        ),
        "acoes": [
            "Feche e abra o programa de novo — na primeira execução do dia o leitor "
            "precisa carregar e isso pode falhar se o computador estiver sobrecarregado.",
            "Se for a primeira vez que o programa roda neste computador, ele precisa "
            "de internet uma única vez para baixar o leitor.",
            "Se o erro continuar, avise o responsável pelo sistema com o detalhe técnico abaixo.",
        ],
    },
    "salvar": {
        "titulo": "Não foi possível salvar a planilha",
        "explicacao": (
            "A planilha não foi gravada. Nada do que já foi processado se perdeu — "
            "os registros continuam abertos no programa."
        ),
        "acoes": [
            "Se a planilha já estiver aberta no Excel, feche-a e salve de novo — "
            "esta é de longe a causa mais comum.",
            "Tente salvar em outra pasta (a Área de Trabalho, por exemplo) ou com outro nome.",
            "Confira se há espaço em disco e se você tem permissão para gravar na pasta escolhida.",
        ],
    },
    "inesperado": {
        "titulo": "O processamento foi interrompido",
        "explicacao": (
            "Aconteceu uma falha que o programa não sabia tratar, e o "
            "processamento parou."
        ),
        "acoes": [
            "As folhas já processadas continuam na aba Registros e podem ser "
            "exportadas normalmente em “Gerar planilha”.",
            "Tente processar de novo apenas as folhas que faltaram.",
            "Se o erro se repetir sempre na mesma folha, é provável que o problema "
            "esteja naquele arquivo — separe-o e processe o resto.",
        ],
    },
}

ROTULO_DETALHE = "Detalhe técnico (para quem der suporte):"


def descrever_falha(categoria: str, detalhe: str = ""):
    """
    Devolve `(titulo, corpo)` prontos para a caixa de diálogo.

    `categoria` desconhecida cai em "inesperado" em vez de estourar: uma
    falha ao DESCREVER uma falha não pode ser pior que a falha original.
    """
    falha = FALHAS.get(categoria) or FALHAS["inesperado"]

    partes = [falha["explicacao"], "", "O que fazer:"]
    partes += [f"  {i}. {acao}" for i, acao in enumerate(falha["acoes"], 1)]

    detalhe = (detalhe or "").strip()
    if detalhe:
        # Uma linha só: o que interessa ao operador já foi dito acima, e o
        # que interessa ao suporte é o texto do erro -- nunca o traceback,
        # que fica no log.
        partes += ["", ROTULO_DETALHE, f"  {detalhe}"]

    return falha["titulo"], "\n".join(partes)


def categoria_da_origem(titulo_tecnico: str) -> str:
    """
    Classifica pelo título que o worker já produzia ("Erro ao abrir o PDF",
    "Erro inesperado processando a imagem"), para o caso de uma origem que
    ainda não declare a própria categoria. Conservador de propósito: o que
    não é reconhecido com clareza vira "inesperado", que é a mensagem que
    não afirma nada de específico.
    """
    texto = (titulo_tecnico or "").lower()
    if "pdf" in texto:
        return "pdf"
    if "imagem" in texto or "imagens" in texto or "foto" in texto:
        return "imagem"
    if "ocr" in texto:
        return "ocr"
    return "inesperado"


# ----------------------------------------------------------------------
# Textos de estado vazio. Ficam aqui, e não espalhados pelo layout, porque
# são a resposta à mesma pergunta ("e agora?") em telas diferentes -- e
# porque uma tela vazia sem texto nenhum é o momento em que o operador
# tem MENOS pistas do que fazer, não mais.
# ----------------------------------------------------------------------
VAZIO_SEM_PROCESSAMENTO = "Nenhum processamento realizado ainda."
VAZIO_TABELA = (
    "Nenhum registro ainda.\n\n"
    "Vá para a aba Início e escolha as fotos das folhas ou o PDF do mês para começar."
)
VAZIO_TABELA_FILTRADA = "Nenhum registro corresponde ao filtro “{filtro}”."
VAZIO_AVISOS = "Nenhum aviso — nada precisa ser conferido no papel até agora."
# Sub-fase 21b: os dois motivos pelos quais a lista de pendências da
# Revisão pode estar vazia são notícias BEM diferentes -- "ainda não
# processei nada" pede uma ação (ir para o Início); "processei e não
# sobrou pendência" é o resultado que se quer. Confundir os dois deixaria
# a boa notícia parecendo um problema.
VAZIO_REVISAO_SEM_PROCESSAMENTO = (
    "Nenhum registro para revisar ainda.\n\n"
    "Vá para a aba Início e processe as folhas — o que precisar de "
    "conferência aparece aqui."
)
VAZIO_REVISAO_TUDO_CONFIRMADO = (
    "Nada pendente de revisão. 🎉\n\n"
    "Todos os registros processados foram confirmados."
)


def resumo_do_resultado(total, confirmados, revisao, erros) -> str:
    """
    Uma frase com o resultado do lote, na linguagem do operador. Usada na
    tela de conclusão e no cartão de "último processamento".
    """
    if not total:
        return VAZIO_SEM_PROCESSAMENTO
    partes = [f"{total} registro(s)", f"{confirmados} confirmado(s)"]
    if revisao:
        partes.append(f"{revisao} para revisar")
    if erros:
        partes.append(f"{erros} folha(s) com erro")
    return " · ".join(partes)


def plural_folhas(quantidade: int) -> str:
    return "1 folha" if quantidade == 1 else f"{quantidade} folhas"


def folhas_selecionadas(quantidade: int) -> str:
    """Concorda em número em vez de despejar "(s)" na tela: "1 folha
    selecionada" / "5 folhas selecionadas"."""
    if quantidade == 1:
        return "1 folha selecionada"
    return f"{quantidade} folhas selecionadas"


def duracao_legivel(segundos: float) -> str:
    """'2 min 14 s' / '48 s' -- tempo DECORRIDO, medido. Nunca previsão."""
    segundos = max(0, int(segundos))
    if segundos < 60:
        return f"{segundos} s"
    minutos, resto = divmod(segundos, 60)
    if minutos < 60:
        return f"{minutos} min {resto:02d} s"
    horas, minutos = divmod(minutos, 60)
    return f"{horas} h {minutos:02d} min"
