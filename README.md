# Leitor de Matrículas Manuscritas

Ferramenta desktop (Windows, Tkinter) para transformar as folhas físicas de
liberação do cartão mestre (foto ou PDF do mês) em uma planilha XLSX
estruturada, com OCR (PaddleOCR), validação contra bases de colaboradores/
gestores/motivos, e revisão manual dos casos duvidosos.

```
FOTO ou PDF → pré-processamento (OpenCV) → OCR (PaddleOCR 3.x)
   → parser espacial (agrupa em registros: Data/Hora/Matrícula/Motivo/Responsável)
   → validação (matrícula, data/hora, gestor, motivo) → consulta a Colaboradores.xlsx (Nome/Setor)
   → tabela + revisão manual → planilha .xlsx ordenada cronologicamente (Liberações/Revisão/Resumo)
```

**Importante**: só DATA, HORA, MATRÍCULA, MOTIVO e RESPONSÁVEL são lidos da
escrita manuscrita da folha. NOME e SETOR nunca são reconhecidos por OCR —
são sempre obtidos consultando a MATRÍCULA reconhecida em
`Colaboradores.xlsx` (um PROCV/XLOOKUP conceitual). Se a matrícula não for
encontrada na base, o registro vai para Revisão e nome/setor aparecem como
`(não encontrado)` — nunca em branco, nunca associados a outra pessoa.

## Estrutura do projeto

```
leitor_matriculas/
├── main.py              # ponto de entrada
├── ui.py                 # interface Tkinter (coordena os módulos abaixo)
├── ocr_engine.py          # PaddleOCR 3.x + normalização de matrícula
├── image_processor.py     # pré-processamento OpenCV
├── pdf_reader.py           # PDF → imagem, página a página
├── registro_parser.py      # agrupa OCR (texto+box) em registros da tabela
├── tempo_parser.py          # interpretação estruturada de data/hora
├── data_manager.py           # leitura de dados/*.xlsx
├── correspondencia_aproximada.py  # fuzzy matching controlado (Motivo/Responsável)
├── validacao.py                # classifica cada registro: CONFIRMADO/REVISAO
├── xlsx_exporter.py             # ordena cronologicamente + gera a planilha final (3 abas)
├── exporter.py                   # exportação CSV (mais simples; não usada pela UI hoje)
├── dados/
│   ├── LEIA-ME.txt
│   ├── Colaboradores.xlsx     # você adiciona
│   ├── Gestores.xlsx          # você adiciona
│   └── Motivos.xlsx           # você adiciona
├── teste/                      # um arquivo de teste por módulo
├── requirements.txt
└── README.md
```

## Instalação (Windows, PowerShell)

```powershell
cd leitor_matriculas
python -m venv venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

A primeira execução do PaddleOCR baixa os modelos (precisa de internet uma
vez; depois funciona offline).

## Bases XLSX (opcional, mas recomendado)

Coloque em `dados/`: `Colaboradores.xlsx`, `Gestores.xlsx`, `Motivos.xlsx`.
O programa funciona sem eles (mostra aviso, e todo registro fica em
REVISÃO por falta de como confirmar a matrícula). Se os cabeçalhos reais
tiverem nomes diferentes dos esperados, ajuste as listas
`COLUNAS_CANDIDATAS_*` no topo de `data_manager.py`.

## Executar

```powershell
python main.py
```

- **Selecionar imagem**: processa uma foto de folha.
- **Selecionar PDF**: processa o PDF do mês inteiro, página por página
  (não carrega todas as páginas na memória de uma vez); uma página que
  falhar ao renderizar não interrompe as demais — fica registrada em
  "Erros de página" e como status `ERRO` na planilha final.
- Resultados de várias seleções se acumulam na mesma tabela — use
  **Limpar resultados** para começar do zero.
- **Abrir revisão**: lista só os registros não confirmados; permite
  corrigir matrícula/gestor/motivo manualmente e confirmar.
- **Gerar XLSX**: salva `Liberações` (tudo), `Revisão` (só os pendentes) e
  `Resumo` (contagens + liberações por gestor/motivo).

## Classificação (validacao.py)

- **CONFIRMADO**: matrícula reconhecida, data e hora interpretáveis com
  segurança, matrícula encontrada em `Colaboradores.xlsx`, confiança do
  OCR ≥ 80%, e — se as respectivas listas estiverem carregadas — gestor e
  motivo batem com `Gestores.xlsx`/`Motivos.xlsx` (exatamente, ou por
  correspondência aproximada controlada — ver abaixo).
- **REVISÃO**: qualquer coisa que não pôde ser confirmada com segurança —
  matrícula não lida, não encontrada na base, confiança baixa, gestor/
  motivo fora da lista, base indisponível, **ou data/hora ilegível,
  impossível, em formato inesperado, vazia, ou sem ano** (ver
  `tempo_parser.py`). Nunca inventa dado — só marca para revisão.
- **ERRO**: página que falhou ao processar (PDF corrompido/página
  ilegível).

Nome e Setor nunca são reconhecidos por OCR — são sempre obtidos
consultando a matrícula em `Colaboradores.xlsx`; quando não encontrados,
aparecem como `(não encontrado)`, nunca em branco.

**Correspondência aproximada (Motivo/Responsável)**: o campo Motivo e o
campo Responsável pela autorização passam primeiro por comparação exata
contra `Motivos.xlsx`/`Gestores.xlsx`; se não bater, o sistema tenta uma
correspondência aproximada controlada (`correspondencia_aproximada.py`) —
só aceita quando a similaridade passa de um limiar E não há ambiguidade
entre os dois candidatos mais parecidos. Ex.: `"neegadho"` reconhece como
`"NEGADO"`; já um texto ambíguo entre dois motivos parecidos (ou dois
gestores com nomes parecidos) vai para revisão em vez de escolher um dos
dois no chute. O texto original do OCR continua disponível na Observação
sempre que uma correção por aproximação foi aplicada.

Nada é descartado silenciosamente: todo registro (inclusive erros de
página) aparece na planilha final, **ordenada cronologicamente por
data+hora reais** (mais antigo primeiro; registros sem data/hora confiável
vão para o final, preservados).

## Testes

```powershell
python teste\teste_ocr.py <foto>              # smoke test do OCR real, via terminal
python teste\teste_data_manager.py [matricula]
python teste\teste_registro_parser.py          # fixtures sintéticas
python teste\teste_pdf_reader.py               # PDFs sintéticos
python teste\teste_validacao.py
python teste\teste_tempo_parser.py             # interpretação de data/hora, fixtures sintéticas
python teste\teste_xlsx_exporter.py            # inclui ordenação cronológica e ordem das colunas
python teste\teste_ui_integracao.py            # fim-a-fim, OCR mockado (precisa de display; roda normal no Windows)
python teste\teste_erro_pagina.py              # página de PDF com falha não trava o lote
python teste\teste_correspondencia_aproximada.py  # fuzzy matching de Motivo/Responsável, fixtures sintéticas
python teste\teste_extracao_fase1.py           # texto impresso, contagem de 8 posições, mesclagem DATA+HORA
```

## O que foi testado e como

- **Módulos isolados** (`data_manager`, `registro_parser`, `pdf_reader`,
  `validacao`, `xlsx_exporter`): testados com fixtures sintéticas —
  passaram.
- **Integração UI completa** (imagem única + PDF de várias páginas +
  classificação + XLSX de 3 abas + correção manual + erro de página):
  testada com **PaddleOCR mockado** (MagicMock) — passou. O parser
  espacial, o pré-processamento OpenCV real e o PyMuPDF real (não
  mockados) rodaram de verdade nesses testes.
- **OCR real (PaddleOCR de verdade, sobre foto real de folha)**: testado
  com `teste.jpg` (foto real de uma folha preenchida) e as bases reais em
  `dados/`. Confirmou, entre outras coisas: reconhecimento correto de
  matrícula/data/hora/motivo/responsável manuscritos; nome/setor
  corretamente derivados via matrícula (nunca lidos da folha); a coluna
  Responsável sendo detectada mesmo com ruído no cabeçalho impresso; texto
  impresso de rodapé (título, código do formulário) não virando registro
  nem valor de campo; separação de um caso real de DATA+HORA mescladas
  numa única caixa de OCR; e correção por aproximação de motivos
  manuscritos com erro de OCR (ex.: "Neegadho" → "NEGADO"). Ver o relatório
  da Fase 1 de precisão da extração para os números completos e as
  limitações residuais encontradas nesse teste real.

## Limitações conhecidas

- Fuzzy matching de gestor/motivo não existe — a comparação com
  `Gestores.xlsx`/`Motivos.xlsx` é exata (ignorando acento/maiúscula). Um
  texto ligeiramente diferente do cadastro vai para revisão em vez de ser
  auto-corrigido — intencional, para nunca "adivinhar" errado.
- A janela de revisão não mostra o recorte da imagem da folha (só o texto
  reconhecido) — manter todas as imagens de um mês inteiro em memória para
  isso não seria viável (~200 páginas).
- "Abrir a pasta do resultado" usa `os.startfile`, que só existe no
  Windows — em outros sistemas essa etapa é ignorada silenciosamente.
- O limiar de confiança mínima da matrícula (80%) é uma constante em
  `validacao.py` (`CONFIANCA_MINIMA_MATRICULA`) — ajuste se, na prática,
  se mostrar alto/baixo demais.
- Threshold de agrupamento espacial (`registro_parser.py`) foi validado com
  fixtures sintéticas; pode precisar de ajuste fino com folhas reais muito
  tortas/rotacionadas.
- O parser ainda é "OCR da página inteira + geometria" (não usa template
  fixo nem recorte por região/campo). MOTIVO e RESPONSÁVEL não têm filtro
  de formato (são texto livre) — diferente de DATA/HORA, que têm — então,
  em casos raros, um fragmento de texto impresso ainda pode ocupar a
  coluna Responsável ou Motivo de uma linha isolada de rodapé sem nenhum
  outro candidato competindo. Nunca foi observado gerar uma confirmação
  falsa (o registro resultante continua sem matrícula), mas não está
  totalmente eliminado. Uma migração para alinhamento de formulário +
  regiões específicas por campo resolveria isso de forma mais definitiva,
  mas foi deliberadamente adiada até medir o ganho das intervenções
  menores primeiro.
