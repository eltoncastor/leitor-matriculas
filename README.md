# Leitor de Matrículas Manuscritas

Sistema para extrair dados manuscritos de fotos ou PDFs de folhas de liberação do cartão mestre e gerar uma planilha XLSX estruturada.

O processamento utiliza **PaddleOCR**, com validação contra bases XLSX locais. Registros que não podem ser confirmados com segurança são encaminhados para **revisão manual**.

O mesmo núcleo de processamento é utilizado pelas interfaces **Desktop** e **Web**. Quando necessário, o OCR pode ser executado por um **Worker Windows** separado.

```text
FOTO/PDF
   ↓
Pré-processamento
   ↓
OCR
   ↓
Parser espacial
   ↓
Data | Hora | Matrícula | Motivo | Responsável
   ↓
Validação
   ↓
CONFIRMADO / REVISÃO
   ↓
XLSX
```

Uma falha no processamento de uma página gera `ERRO` de página e não interrompe o lote.

---

## Interfaces

### Desktop

Interface original em **Tkinter + ttkbootstrap**.

```powershell
python main.py
```

É mantida para correções e manutenção.

### Web

Localizada em `web/`, utiliza **React + Tailwind** no frontend e **FastAPI** no backend.

Pode funcionar:

* no navegador;
* como aplicativo desktop via `pywebview`;
* como `.exe` portátil;
* com OCR local;
* com OCR executado por Worker Windows separado.

### Worker Windows

Processo separado para executar o OCR quando o backend opera em modo servidor.

A arquitetura permite:

```text
Backend / VPS
    ↓
coordenação e Jobs
    ↓
Worker Windows
    ↓
OCR + pipeline
    ↓
resultado
```

O Worker utiliza o mesmo núcleo de processamento do sistema.

Detalhes de Web, Worker, execução remota e empacotamento estão em [`web/README.md`](web/README.md).

---

## Campos reconhecidos

O OCR trabalha somente com:

* **Data**
* **Hora** *(opcional)*
* **Matrícula**
* **Motivo**
* **Responsável**

**Nome e Setor não são extraídos da folha por OCR.** Eles podem ser obtidos posteriormente pela matrícula, usando a base de colaboradores e ferramentas como `PROCX/XLOOKUP`.

### Hora

A Hora é opcional.

Se Data, Matrícula, Motivo e Responsável forem confirmados, a ausência ou ilegibilidade da Hora não impede a confirmação.

Quando não puder ser validada:

```text
Hora = vazia
```

O sistema nunca inventa uma hora. O texto original do OCR permanece registrado em `Observação`.

### Responsável

Representa o gestor que autorizou a liberação.

Quando o gestor é identificado com segurança, texto residual desconhecido é ignorado.

Se o responsável não puder ser identificado com segurança, o registro permanece em `REVISÃO`.

---

## Arquitetura

O núcleo está em `src/leitor_matriculas/` e é compartilhado pelas interfaces.

```text
.
├── main.py
├── src/
│   └── leitor_matriculas/
│       ├── pipeline.py
│       ├── ocr/
│       ├── parsing/
│       ├── validacao/
│       ├── dados/
│       ├── exportacao/
│       └── ui/
├── web/
│   ├── backend/
│   ├── frontend/
│   └── desktop_app.py
├── worker/
├── dados/
├── entrada/
├── saida/
└── teste/
```

O fluxo de execução é:

```text
OCR → Parsing → Validação → Exportação
```

`pipeline.py` coordena o processamento de uma folha.

As interfaces ficam acima do núcleo:

```text
Tkinter ──────┐
              ├──→ pipeline.py
Web Backend ──┘
```

Os módulos são organizados por responsabilidade e mantêm dependências em uma única direção, evitando que camadas inferiores dependam das interfaces.

---

## Estados do processamento

O sistema diferencia **registro** de **página**.

### Registro

**`CONFIRMADO`**

Dados necessários identificados e validados com segurança.

**`REVISÃO`**

Alguma informação necessária não pôde ser confirmada com segurança.

### Página

**`PROCESSADA`**

Processamento concluído, podendo conter registros em revisão.

**`ERRO`**

Falha de processamento da página inteira, como erro de leitura da imagem, pré-processamento, OCR ou renderização do PDF.

Uma página em `ERRO` não vai para revisão manual e não interrompe o restante do lote.

---

## Validação

### CONFIRMADO

A confirmação exige:

* matrícula presente, somente com dígitos e validada na base;
* data válida;
* motivo reconhecido;
* responsável identificado na base de gestores;
* bases necessárias disponíveis;
* normalizações e correspondências sustentadas por evidência suficiente.

A Hora **não é obrigatória**.

Motivo e Responsável **são obrigatórios**.

### REVISÃO

Exemplos:

* matrícula ilegível, ausente, não encontrada ou ambígua;
* gestor ambíguo ou irreconhecível;
* motivo não reconhecido;
* data inválida ou inconsistente;
* motivo ou responsável ausentes;
* evidência insuficiente.

Uma normalização em um único campo nunca confirma o registro sozinha.

O sistema prefere `REVISÃO` a inventar ou associar dados sem evidência suficiente.

---

## Recuperações e normalizações

O sistema trata apenas deformações previsíveis do OCR.

```text
Leitura OCR
   ↓
Possíveis normalizações
   ↓
Validação contra base/contexto
   ↓
uma possibilidade válida → aceita
mais de uma              → REVISÃO
nenhuma                  → REVISÃO
```

O sistema não escolhe simplesmente o candidato mais parecido quando existe ambiguidade.

Toda normalização aceita fica registrada em `Observação`.

### Motivo

Há tratamento específico para a família `HORÁRIO NEGADO`, com recuperação de deformações conhecidas e comparação contra a lista fechada de motivos.

### Responsável

Códigos e identificações de gestores são validados contra `Gestores.xlsx`.

Ambiguidade leva a `REVISÃO`.

### Data e Hora

Datas são exportadas em `DD/MM/AA`.

Horas válidas são exportadas em `HH:MM`.

Separadores deformados podem ser normalizados quando a leitura for inequívoca.

Valores impossíveis são recusados.

### Matrícula

A matrícula exportada contém exclusivamente dígitos (`0-9`).

Caracteres suspeitos não são simplesmente apagados. Leituras alternativas são verificadas contra `Colaboradores.xlsx`.

Se nenhuma leitura puder ser confirmada, a matrícula permanece vazia e o registro vai para `REVISÃO`.

### Contexto do lote

O lote pode fornecer o **ano** de uma data sem ano quando houver evidência suficiente nas demais páginas.

As regras são conservadoras:

* somente datas completas alimentam o contexto;
* datas recuperadas pelo contexto não o realimentam;
* o ano precisa ser predominante com segurança;
* um lote que atravessa a virada do ano não escolhe automaticamente um ano;
* ano divergente permanece em `REVISÃO`;
* o contexto é reiniciado a cada lote.

---

## Ordem dos registros

A ordem física das liberações na folha é preservada.

O sistema não ordena os registros por nome, matrícula, gestor, motivo ou data.

Isso permite conferir a planilha diretamente contra o documento físico.

---

## Bases de dados

As bases operacionais ficam em `dados/`:

```text
Colaboradores.xlsx
Gestores.xlsx
Motivos.xlsx
```

### Colaboradores.xlsx

Valida matrículas e fornece dados derivados da matrícula, como Nome e Setor.

### Gestores.xlsx

Contém gestores e suas formas válidas de identificação.

### Motivos.xlsx

Contém a lista fechada de motivos:

```text
HORÁRIO NEGADO
RH
ADM
ARMÁRIOS
FOLGA FIXA
ESQUECEU CRACHÁ
TREINAMENTO
```

`NEGADO` e `NEGADA` são normalizados para `HORÁRIO NEGADO`.

As bases reais são locais e não fazem parte do repositório.

---

## Instalação e execução

### Desktop

Windows + PowerShell:

```powershell
cd leitor_matriculas
python -m venv venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

Na primeira execução, o PaddleOCR pode baixar os modelos necessários.

### Web e Worker

A execução do backend, frontend, Worker e o empacotamento em `.exe` estão documentados em [`web/README.md`](web/README.md).

---

## Operação

Na interface Desktop:

**Selecionar imagem**
Processa uma foto individual.

**Selecionar PDF**
Processa as páginas individualmente. Uma falha não interrompe o lote.

**Revisão**
Permite corrigir registros pendentes. A correção passa pela mesma validação do fluxo automático; se o problema persistir, o registro permanece em `REVISÃO`.

**Avisos**
Reúne ocorrências não bloqueantes, como erros de página, divergência de quantidade, linhas sem matrícula e problemas nas bases.

**Gerar XLSX**
Exporta a planilha final preservando a ordem física das liberações.

---

## Tratamento de erros

O processamento é executado de forma assíncrona para manter a interface responsiva.

Falhas inesperadas são:

1. capturadas;
2. registradas;
3. apresentadas ao usuário;
4. encerradas sem deixar a interface presa em `Processando...`.

No processamento de PDFs, a falha de uma página é isolada das demais.

---

## Testes

Os testes do núcleo estão em `teste/`.

Exemplos:

```powershell
python teste\teste_ocr.py <foto>
python teste\teste_data_manager.py
python teste\teste_registro_parser.py
python teste\teste_validacao.py
python teste\teste_tempo_parser.py
python teste\teste_xlsx_exporter.py
python teste\teste_recuperacao_contextual.py
python teste\teste_integridade_captura.py
```

`teste_ocr.py` requer uma imagem real e PaddleOCR.

Os testes Web, Worker e frontend possuem suítes próprias. Consulte [`web/README.md`](web/README.md) para os detalhes.

---

## Validação de referência

O sistema foi validado com cinco folhas reais contendo **40 liberações esperadas**:

| Página    | Esperadas | Detectadas |
| --------- | --------: | ---------: |
| 1         |         8 |          8 |
| 2         |         8 |          8 |
| 3         |         8 |          8 |
| 4         |         8 |          8 |
| 5         |         8 |          8 |
| **Total** |    **40** |     **40** |

Nesse conjunto específico:

* todas as 40 liberações foram detectadas;
* nenhum registro desapareceu;
* nenhum registro duplicado foi observado;
* a ordem física foi preservada;
* os formatos de saída foram mantidos.

Esse resultado é uma **validação estrutural desse conjunto de folhas**, não uma taxa geral de acurácia do OCR.

Durante o desenvolvimento, uma página apresentou cinco registros devido a um problema no agrupamento espacial. O algoritmo foi corrigido e passou a detectar as oito liberações sem gerar registros fantasmas.

---

## Desempenho

O principal gargalo é o OCR.

Benchmark de referência em CPU:

```text
Renderização PDF       ~0,17 s/página
Pré-processamento       ~0,81 s/página
OCR                    ~36,5 s/página
Parser/validação        ~0,003 s/página
```

O `enable_mkldnn` permanece desativado devido à incompatibilidade reproduzida no ambiente Windows/CPU utilizado nos testes.

---

## Limitações

* OCR em CPU pode ser lento.
* Caligrafia muito ilegível pode exigir revisão manual.
* Matrículas ou gestores parcialmente cortados podem não ser recuperados.
* A qualidade da fotografia influencia diretamente o OCR.
* O parser utiliza OCR da página inteira e geometria, sem ROIs fixas por campo.
* O agrupamento espacial foi validado com um conjunto limitado de folhas reais.
* As recuperações cobrem apenas deformações previsíveis.
* Fragmentos de texto impresso podem ocasionalmente cair em colunas de Motivo ou Responsável.

O objetivo não é maximizar a quantidade de `CONFIRMADO`, e sim aumentar a confiabilidade sem introduzir confirmações indevidas.

---

## Segurança dos dados

O projeto pode trabalhar com informações pessoais e operacionais.

Por isso:

* bases reais não são versionadas;
* imagens e PDFs reais não são versionados;
* planilhas com dados reais não são versionadas;
* logs sensíveis permanecem fora do repositório;
* exemplos da documentação utilizam dados fictícios;
* o `.gitignore` exclui arquivos locais sensíveis do fluxo normal de versionamento.

---

## Documentação relacionada

* [`web/README.md`](web/README.md) — Web, backend, Worker e empacotamento.
* `CLAUDE.md` — regras e contratos para desenvolvimento.
* `dados/LEIA-ME.txt` — informações sobre as bases locais.

O histórico detalhado das fases e decisões de engenharia é mantido separadamente da documentação principal do projeto.
