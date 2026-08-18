# Leitor de Matrículas Manuscritas

Ferramenta para Windows que transforma fotos ou PDFs das folhas físicas de liberação do cartão mestre em uma planilha XLSX estruturada.

O sistema utiliza OCR com PaddleOCR para reconhecer os dados manuscritos, valida as informações contra bases XLSX e envia automaticamente para revisão manual os casos que não podem ser confirmados com segurança. Todo o núcleo — OCR, parser, validação, evidências, exportação — vive em `src/leitor_matriculas/` e é o mesmo em qualquer interface abaixo; nada é reescrito de uma para outra.

### Duas interfaces, o mesmo núcleo

* **Desktop (Tkinter)** — `python main.py`. A interface original do projeto; congelada desde a Fase 24 (recebe correções, não novas funcionalidades), mas totalmente funcional.
* **Web** (`web/`) — React + Tailwind no navegador, FastAPI por trás, é a interface em desenvolvimento ativo hoje. Pode rodar como servidor local, como app desktop com janela nativa (`python web\desktop_app.py`), ou empacotada como um `.exe` portátil (sem instalar Python/Node) — ver `web/README.md` para todos os modos, incluindo acesso remoto e deploy atrás de um domínio compartilhado. Também suporta descarregar o OCR para um **Worker** separado (ex.: PC Windows do operador atendendo uma VPS), útil quando o servidor principal roda num ambiente pequeno demais para o PaddleOCR — ver a seção "Worker Windows" de `web/README.md`.

```text
FOTO ou PDF
    ↓
Pré-processamento (OpenCV)
    ↓
OCR (PaddleOCR)
    ↓
Parser espacial
    ↓
Data | Hora | Matrícula | Motivo | Responsável
    ↓
Validação
    ↓
CONFIRMADO / REVISÃO
    ↓
Planilha XLSX
```

---

## Dados reconhecidos

A extração principal trabalha somente com os campos existentes na folha:

```text
Data
Hora
Matrícula
Motivo
Responsável
```

### Nome e Setor

**Nome e Setor não são reconhecidos por OCR.**

Esses dados não fazem parte do resultado principal da extração e podem ser obtidos posteriormente a partir da matrícula, por exemplo utilizando `PROCX/XLOOKUP` em outra planilha.

Essa abordagem evita processamento desnecessário e reduz o risco de associar uma pessoa incorreta a uma matrícula.

### Hora

A Hora é um campo **opcional**.

Se Data + Matrícula + Motivo + Responsável forem confirmados, a ausência ou ilegibilidade da Hora não impede a confirmação do registro.

Quando a Hora não puder ser reconhecida com segurança:

```text
Hora = vazia
```

O sistema nunca inventa uma hora.

Isso vale tanto para a Hora **ausente** quanto para a Hora **ilegível**. Nos dois casos o registro pode ser `CONFIRMADO` normalmente.

Uma hora ilegível nunca é escrita na planilha: o texto reconhecido pelo OCR seria indistinguível de uma hora real. Mas ele também não é descartado — fica registrado na coluna `Observação`, para auditoria.

Exemplo fictício:

```text
OCR na coluna HORA:  25:99
Resultado:
    Hora       = (vazia)
    Status     = CONFIRMADO
    Observação = hora ilegível, exportada em branco (texto do OCR: '25:99')
```

Quando a Hora existe e é legível, ela é preservada normalmente.

### Responsável

O campo Responsável representa o gestor que autorizou a liberação.

Algumas folhas podem conter texto adicional após o gestor. Quando o gestor é identificado com segurança, esse texto residual desconhecido é ignorado.

Exemplo fictício:

```text
OCR:
GRX - GESTOR EXEMPLO - TEXTO_RESIDUAL

Resultado:
Responsável = GRX - GESTOR EXEMPLO
```

O sistema não tenta identificar ou corrigir o texto residual.

Nomes compostos e códigos de gestores são preservados.

Exemplos fictícios:

```text
GRX - GESTOR EXEMPLO
GRY - OUTRO GESTOR
GESTOR EXEMPLO
NOME COMPOSTO EXEMPLO
```

Quando o gestor não puder ser identificado com segurança, o registro é enviado para `REVISÃO`.

---

## Arquitetura atual

O núcleo do sistema fica em `src/leitor_matriculas/`, organizado por **responsabilidade**, e é compartilhado por todas as interfaces:

```text
leitor_matriculas/
├── main.py                     ponto de entrada do desktop Tkinter (python main.py)
│
├── src/
│   └── leitor_matriculas/
│       ├── pipeline.py         orquestra OCR → parser → validação para uma folha
│       │                       (usado pelo Tkinter e pelo backend web -- ver abaixo)
│       ├── ocr/                entrada visual
│       │   ├── image_processor.py
│       │   ├── engine.py
│       │   └── pdf_reader.py
│       ├── parsing/            reconstrução dos registros
│       │   ├── registro_parser.py
│       │   ├── tempo_parser.py
│       │   └── contexto_lote.py
│       ├── validacao/          classificação dos registros
│       │   ├── regras.py
│       │   ├── correspondencia_aproximada.py
│       │   ├── recuperacao_matricula.py
│       │   ├── integridade.py
│       │   ├── evidencias.py
│       │   ├── confirmacao.py
│       │   └── explicacao_revisao.py
│       ├── dados/              bases XLSX de apoio
│       │   ├── data_manager.py
│       │   └── registro_correcoes.py
│       ├── exportacao/         geração da saída
│       │   ├── xlsx_exporter.py
│       │   └── csv_exporter.py
│       └── ui/                 interface Tkinter
│           ├── app.py
│           ├── estilos.py
│           ├── mensagens.py
│           └── preferencias.py
│
├── web/                        interface Web (React + FastAPI) -- ver web/README.md
│   ├── backend/                 API que chama o mesmo pipeline.py acima
│   ├── frontend/                React + Tailwind (Vite)
│   └── desktop_app.py           janela nativa (pywebview) sobre o mesmo backend
│
├── worker/                     Worker de OCR remoto (opcional) -- ver web/README.md
│
├── dados/                      bases reais (locais, fora do Git)
│   ├── LEIA-ME.txt
│   ├── Colaboradores.xlsx
│   ├── Gestores.xlsx
│   └── Motivos.xlsx
│
├── entrada/                    fotos/PDFs reais (locais, fora do Git)
├── saida/                      planilhas geradas (locais, fora do Git)
├── teste/                      testes do núcleo e do Tkinter
├── requirements.txt
├── README.md                    este arquivo
└── web/README.md                interface Web, Worker, empacotamento .exe
```

A dependência dentro de `src/leitor_matriculas/` é de mão única — `ocr → parsing → validacao → exportacao`, com `pipeline.py` orquestrando essa cadeia e `ui`/`web/backend` cada um coordenando por cima dela à sua maneira. Nenhum módulo de baixo importa um de cima, o que mantém o grafo acíclico.

O projeto roda direto do diretório, sem instalação via `pip`: `main.py` acrescenta `src/` ao `sys.path` antes de importar o pacote (o backend web faz o equivalente).

---

## Principais módulos

| Módulo                                            | Responsabilidade                                         |
| ------------------------------------------------- | -------------------------------------------------------- |
| `main.py`                                          | Ponto de entrada do desktop Tkinter                      |
| `pipeline.py`                                      | Roda OCR → parser → validação para uma folha; usado pelo Tkinter e pelo backend web |
| `ui/app.py`                                        | Interface gráfica (abas Registros/Revisão/Avisos) e coordenação do processamento |
| `ocr/engine.py`                                    | Inicialização e execução do PaddleOCR                    |
| `ocr/image_processor.py`                           | Pré-processamento das imagens                            |
| `ocr/pdf_reader.py`                                | Renderização de PDFs página por página                   |
| `parsing/registro_parser.py`                       | Agrupamento espacial dos elementos OCR em registros      |
| `parsing/tempo_parser.py`                          | Interpretação e validação de Data/Hora                   |
| `parsing/contexto_lote.py`                         | Contexto do lote (ano das datas já lidas)                |
| `dados/data_manager.py`                            | Carregamento das bases XLSX                              |
| `dados/registro_correcoes.py`                      | Registra correções manuais para consulta futura (não influencia decisões automáticas) |
| `validacao/correspondencia_aproximada.py`          | Correspondência aproximada controlada                    |
| `validacao/recuperacao_matricula.py`               | Recuperação da matrícula para dígitos                    |
| `validacao/regras.py`                              | Classificação dos registros                              |
| `validacao/integridade.py`                         | Detecta campo lido pelo OCR e perdido na associação (evita `CONFIRMADO` com dado perdido) |
| `validacao/evidencias.py`                          | Registra por que cada valor foi aceito, corrigido ou recusado (sem pontuação/score) |
| `validacao/confirmacao.py`                         | Decisão de confirmação manual, compartilhada entre Tkinter e Web |
| `validacao/explicacao_revisao.py`                  | Traduz a evidência estruturada para linguagem de operador na aba/tela de Revisão |
| `exportacao/xlsx_exporter.py`                      | Geração da planilha XLSX                                 |
| `exportacao/csv_exporter.py`                       | Exportação CSV legada (não ligada à interface)           |

Os caminhos acima são relativos a `src/leitor_matriculas/`. Os módulos de `web/` e `worker/` estão documentados em `web/README.md`.

---

## Bases de dados

As bases utilizadas pelo sistema ficam em:

```text
dados/
├── Colaboradores.xlsx
├── Gestores.xlsx
└── Motivos.xlsx
```

Esses arquivos contêm dados operacionais e devem ser tratados como **dados locais e sensíveis**.

Eles **não fazem parte do repositório público**.

### Colaboradores.xlsx

Utilizada para validação da matrícula.

O sistema não precisa reconhecer Nome ou Setor por OCR.

A matrícula reconhecida pode ser utilizada posteriormente para obter essas informações em uma base de colaboradores.

### Gestores.xlsx

Contém os gestores e suas possíveis formas de identificação.

Uma mesma pessoa pode possuir diferentes formas válidas de identificação, como:

```text
CÓDIGO - NOME
CÓDIGO
NOME
NOME ABREVIADO
```

Essas formas podem representar aliases ou identificadores alternativos e não necessariamente pessoas diferentes.

### Motivos.xlsx

Contém os motivos válidos utilizados na validação e na correspondência aproximada controlada.

A lista de motivos é **fechada**. Nesta versão do sistema, os únicos motivos válidos são:

```text
HORÁRIO NEGADO
RH
ADM
ARMÁRIOS
FOLGA FIXA
ESQUECEU CRACHÁ
TREINAMENTO
```

O campo `Motivo` de um registro `CONFIRMADO` sempre contém um desses valores — o sistema não cria motivos novos nem exporta ruído de OCR como motivo confirmado.

`NEGADO` e `NEGADA` **não são motivos independentes** nesta versão: quando reconhecidos, são normalizados para `HORÁRIO NEGADO`.

---

## Instalação

Windows + PowerShell (desktop Tkinter — para a interface Web, ver `web/README.md`):

```powershell
cd leitor_matriculas
python -m venv venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Na primeira execução, o PaddleOCR pode baixar os modelos necessários.

Após os modelos estarem disponíveis, o processamento pode funcionar localmente sem depender de serviços externos.

Também existe um `.exe` portátil da interface Web, que não precisa de Python nem Node instalados — ver "Empacotamento em .exe portátil" em `web/README.md`.

---

## Executar

```powershell
python main.py
```

Isto abre a interface Tkinter, descrita nesta seção. Para a interface Web (navegador, app desktop com janela nativa, ou o `.exe`), ver `web/README.md`.

### Selecionar imagem

Processa uma foto individual de uma folha.

### Selecionar PDF

Processa as páginas do PDF individualmente.

Uma falha em uma página não deve interromper o processamento das demais.

### Revisão

Aba dedicada à correção manual dos registros que não puderam ser confirmados automaticamente.

Ela mostra, lado a lado:

* a **foto da folha** correspondente, com zoom — para conferir o que está escrito no papel sem sair do programa;
* o **motivo** pelo qual aquela linha não pôde ser confirmada;
* os **campos editáveis**: Data, Hora, Matrícula, Motivo e Responsável;
* **Nome e Setor**, obtidos da base pela matrícula (nunca digitados).

Motivo e Responsável são listas alimentadas pelas bases — o valor válido só pode ser um dos cadastrados.

A navegação percorre os pendentes em sequência, na ordem física das folhas.

**Confirmar uma correção não marca o registro como confirmado.** O programa remonta o registro com os valores digitados e roda exatamente a mesma validação do fluxo automático. Se a correção não resolver o problema real, a linha **permanece em revisão**, com a observação atualizada explicando o que ainda falta.

Linhas com `ERRO` não aparecem aqui: uma página que falhou não tem campo algum a corrigir e precisa ser reprocessada.

### Avisos

Reúne os apontamentos que não bloqueiam o processamento: páginas com erro, páginas cuja contagem de liberações divergiu do esperado, linhas sem matrícula identificável e problemas nas bases de dados.

### Gerar XLSX

Gera a planilha final com os registros processados.

A ordem das liberações é preservada de acordo com a ordem encontrada no papel.

---

## Validação

Cada linha da planilha recebe um destes três estados:

### CONFIRMADO

Registro em que os dados necessários puderam ser identificados e validados com segurança.

A confirmação considera:

* Matrícula (presente, só com dígitos e encontrada na base, acima do piso de confiança do OCR);
* Data (presente e interpretável);
* Motivo (presente e reconhecido na lista fechada);
* Responsável (presente e identificado na base de gestores);
* bases de validação disponíveis;
* correspondências aproximadas e normalizações, quando aplicáveis.

A Hora **não é obrigatória** para confirmação.

Motivo e Responsável, ao contrário, **são obrigatórios**: uma coluna em branco não é "vazia e válida" — é uma linha que o OCR não conseguiu ler, e vai para `REVISÃO`. Sem essa regra, o registro sairia `CONFIRMADO` com a célula em branco, indistinguível de um valor conferido.

### REVISÃO

Registro que contém alguma informação necessária que não pôde ser confirmada com segurança.

Exemplos:

* matrícula ilegível, ausente, não encontrada na base ou com duas leituras plausíveis;
* gestor ambíguo, cortado ou irreconhecível;
* motivo não reconhecido ou com evidência insuficiente;
* data inválida, incompleta ou com ano que destoa do restante do lote;
* motivo ou responsável ausentes;
* informação insuficiente para confirmação.

Uma normalização aceita em um campo **não confirma o registro sozinha**: recuperar o motivo não compensa um responsável incerto, e recuperar a data não compensa uma matrícula duvidosa.

O sistema prefere enviar um registro para `REVISÃO` a inventar ou associar uma informação sem evidência suficiente.

### ERRO

Falha de **página inteira**, não de linha: a imagem não abriu, o pré-processamento falhou, o OCR não rodou, a página do PDF não renderizou.

Uma linha `ERRO` não tem campo nenhum de verdade para corrigir, então ela **não aparece na janela de revisão manual** — digitar valores ali seria inventar dados sem nenhuma evidência de OCR por trás. A página precisa ser reprocessada (nova foto ou novo PDF).

Uma página com `ERRO` nunca interrompe o lote: as demais continuam sendo processadas normalmente.

---

## Correspondência aproximada

O fuzzy matching é controlado e utiliza conjuntos fechados de candidatos.

A prioridade é:

```text
1. Correspondência exata
2. Alias conhecido
3. Correspondência aproximada controlada
4. Verificação de ambiguidade
5. REVISÃO quando não houver segurança suficiente
```

O sistema não deve simplesmente escolher o candidato com maior pontuação.

Se dois candidatos forem muito próximos ou houver ambiguidade, o registro vai para `REVISÃO`.

### Responsável

O gestor deve ser identificado antes que qualquer texto residual seja considerado.

Exemplo fictício:

```text
OCR:
GRX - GESTOR EXEMPLO - TEXTO_DESCONHECIDO

Resultado:
Responsável = GRX - GESTOR EXEMPLO
```

O texto desconhecido é ignorado.

Não existe reconhecimento de informações adicionais de auxiliares no resultado principal.

---

## Normalizações e recuperações de OCR

Além da correspondência aproximada, o sistema desfaz deformações **previsíveis** de OCR manuscrito. Todas seguem o mesmo padrão de evidência:

```text
gerar as leituras plausíveis por uma tabela FECHADA de confusões de OCR
    ↓
perguntar à base (ou ao contexto do lote) quais existem de verdade
    ↓
existe exatamente uma  → aceita
existem duas ou mais   → ambíguo, ninguém escolhe → REVISÃO
não existe nenhuma     → REVISÃO
```

Nenhuma dessas etapas inventa caractere: cada troca vem de uma confusão conhecida, e o resultado ainda passa pela validação normal do campo.

Toda normalização aceita fica registrada na coluna `Observação`, junto com o texto original do OCR — nada é corrigido em silêncio.

### Motivo

Reconhecimento estrutural da família `HORÁRIO NEGADO`: o texto é quebrado em partes, procura-se a que carrega o núcleo (`NEGADO`/`NEGADA`), e as confusões conhecidas são desfeitas (dígito lido no lugar de letra, `n`/`v`/`w`/`m` cursivos, `d` quebrado em dois caracteres).

A aceitação exige **evidência combinada**: similaridade alta sozinha, ou similaridade média mais um segundo critério independente. Em qualquer caso, a evidência da família ainda precisa superar com folga a semelhança com os outros motivos da lista fechada — é essa checagem que impede `RH`, `ADM`, `ARMÁRIOS`, `FOLGA FIXA`, `ESQUECEU CRACHÁ` e `TREINAMENTO` de serem absorvidos indevidamente.

Um texto sem evidência suficiente **não** vira `HORÁRIO NEGADO`: vai para `REVISÃO`.

### Responsável

Quando o código do gestor está legível, ele identifica o gestor sozinho e prevalece sobre o texto secundário — que costuma ser um nome anotado ao lado, ilegível no OCR.

O código é lido pela tabela fechada de confusões e confirmado contra a base de gestores. Se mais de um código cadastrado for leitura plausível, o registro vai para `REVISÃO`.

Uma identificação mais específica presente na base sempre ganha do código isolado.

### Data

Saída sempre em `DD/MM/AA`.

* separadores deformados ou multiplicados são corrigidos quando os dígitos são inequívocos;
* uma caixa em que o OCR colou Data e Hora é separada quando cada metade valida por conta própria;
* datas impossíveis continuam recusadas;
* quando a data não pode ser interpretada com segurança, a célula sai **vazia** e o registro vai para `REVISÃO` — o texto original fica na `Observação`.

### Hora

Saída sempre em `HH:MM`.

Separadores trocados ou apagados pelo OCR são normalizados, e uma hora colada a outro texto na mesma caixa é recuperada quando existe exatamente um trecho com forma de hora e nenhum dígito sobrando fora dele.

Horas impossíveis continuam recusadas e a célula sai vazia — ver a seção *Hora*, acima.

### Matrícula

A matrícula exportada contém **exclusivamente dígitos** (`0-9`). Nunca sai com `+`, `.`, `-`, espaços ou letras.

Os caracteres estranhos não são simplesmente apagados: eles costumam **ser** um dígito lido errado, e removê-los mudaria a matrícula para a de outra pessoa. A leitura correta é escolhida pela existência na base de colaboradores.

Se nenhuma leitura resolver com segurança, a célula sai vazia, o registro vai para `REVISÃO` e a linha é contabilizada no aviso "Linhas sem matrícula" da interface — uma liberação real nunca é descartada.

### Contexto do lote

Fotos e páginas processadas juntas formam um **lote**, e o que uma folha comprova pode resolver outra.

Hoje o contexto guarda apenas o **ano** das datas já lidas. Quando o OCR entrega uma data sem ano (`23.04`) — porque o ano foi escrito pequeno ou ficou cortado na foto —, o ano pode ser completado a partir das outras folhas do mesmo lote.

Isso não é suposição: o ano está escrito, só que em outra página da mesma remessa. A `Observação` registra que o ano veio do contexto, junto com o texto original.

O contexto é conservador:

* só entram datas interpretadas por completo — uma data recuperada por contexto nunca realimenta o contexto;
* é preciso um mínimo de datas confirmadas; uma folha legível não é "o contexto do lote";
* o ano precisa ser predominante com folga. Um lote que de fato atravessa a virada do ano **não elege ano nenhum**, e as datas sem ano continuam em `REVISÃO`;
* o caminho inverso também vale: uma data cujo ano **está escrito** mas destoa do restante do lote vai para `REVISÃO`. O ano não é reescrito — apenas se reconhece que aquela linha precisa ser conferida no papel;
* o contexto é zerado junto com "Limpar resultados" e nunca atravessa dois lotes diferentes.

---

## Ordem dos registros

A ordem das liberações encontrada na folha é preservada.

O sistema não deve ordenar os registros por:

* nome;
* matrícula;
* gestor;
* motivo.

A sequência física das liberações é a referência principal para a saída.

---

## Tratamento de erros

O processamento ocorre em threads para manter a interface responsiva.

Falhas inesperadas durante o processamento de uma imagem são capturadas pelo worker da UI.

Quando o OCR falha:

```text
erro
 ↓
exceção capturada
 ↓
erro registrado no log
 ↓
mensagem apresentada ao usuário
 ↓
estado "Processando" encerrado
 ↓
botões restaurados
```

A interface não deve permanecer indefinidamente presa em `Processando...`.

O processamento de PDF possui tratamento equivalente para erros de página.

---

## Desempenho

O principal gargalo atual é o OCR do PaddleOCR.

Em testes realizados em CPU:

```text
Renderização PDF       ~0,17 s/página
Pré-processamento      ~0,81 s/página
OCR                    ~36,5 s/página
Parser/validação       ~0,003 s/página
```

O OCR representa aproximadamente 95% do tempo de processamento.

O `enable_mkldnn` permanece desativado devido a uma incompatibilidade reproduzida entre PaddlePaddle/oneDNN no ambiente Windows/CPU utilizado.

Não foram feitas otimizações de velocidade que comprometam a precisão do OCR.

---

## Testes

Não há um único test runner: cada arquivo em `teste/` é um script independente. Exemplos:

```powershell
python teste\teste_ocr.py <foto>
python teste\teste_data_manager.py
python teste\teste_registro_parser.py
python teste\teste_pdf_reader.py
python teste\teste_validacao.py
python teste\teste_tempo_parser.py
python teste\teste_xlsx_exporter.py
python teste\teste_ui_integracao.py
python teste\teste_erro_pagina.py
python teste\teste_correspondencia_aproximada.py
python teste\teste_extracao_fase1.py
python teste\teste_worker_imagem_falha.py
python teste\teste_seguranca_lote.py
python teste\teste_lote_operacional.py
python teste\teste_normalizacao_ocr.py
python teste\teste_normalizacao_motivo_hora.py
python teste\teste_recuperacao_contextual.py
python teste\teste_integridade_captura.py
python teste\teste_pdf_robustez.py
python teste\teste_resolucao_ocr.py
python teste\teste_evidencias.py
python teste\teste_registro_correcoes.py
python teste\teste_alternar_tema.py
python teste\teste_estilos.py
```

Todas as suítes acima estão aprovadas no ciclo atual. Com exceção de `teste_ocr.py`, que exige uma foto real como argumento, nenhuma depende de PaddleOCR ou das planilhas reais — as bases usadas são fixtures sintéticas.

A interface Web e o Worker têm suas próprias suítes, também sem um runner único: `web\backend\testes\*.py` (API, persistência, protocolo de Worker) e `worker\testes\*.py` (cliente HTTP do Worker), além dos testes JS do frontend (`cd web\frontend; npm run test`). Ver `web/README.md` para a lista completa e o que cada um cobre.

`teste_recuperacao_contextual.py` cobre especificamente as normalizações e recuperações descritas acima: família `HORÁRIO NEGADO` e preservação dos outros seis motivos, leitura do código do gestor, contexto do lote (ano completado, ano divergente, lote que atravessa a virada do ano), horas deformadas, matrícula só com dígitos, e a regra de que normalizar um campo não confirma o registro sozinho.

Também foram realizados testes com PaddleOCR real sobre um conjunto de cinco folhas reais.

Resultado estrutural:

```text
Esperado: 40 liberações
Encontrado: 40 liberações

40/40 = 100%
```

Nenhum registro desapareceu ou foi duplicado, a ordem física foi preservada, e nenhuma matrícula, data ou hora saiu fora do formato exigido.

Os dados utilizados nesses testes são locais e não fazem parte do repositório público.

---

## Validação com dados reais

O sistema foi validado com um conjunto real contendo cinco folhas.

Resultado estrutural:

| Página    | Liberações esperadas | Detectadas |
| --------- | -------------------: | ---------: |
| 1         |                    8 |          8 |
| 2         |                    8 |          8 |
| 3         |                    8 |          8 |
| 4         |                    8 |          8 |
| 5         |                    8 |          8 |
| **Total** |               **40** |     **40** |

Uma das páginas inicialmente apresentava apenas cinco registros devido a um problema no agrupamento espacial dos elementos OCR.

O algoritmo de agrupamento foi corrigido e a página passou a detectar corretamente as oito liberações.

Nenhum registro fantasma foi observado após a correção.

> Os arquivos originais utilizados nessa validação não são armazenados no repositório público.

---

## Princípios do sistema

### Nunca inventar dados

O sistema deve preferir `REVISÃO` a uma correção sem evidência suficiente.

### Não confundir OCR com verdade

O texto reconhecido pelo OCR é apenas uma hipótese que precisa ser validada.

### Não reconhecer informações desnecessárias

Nome e Setor não são extraídos da folha.

### Não interpretar texto residual como dado

Depois que o gestor é identificado com segurança, texto adicional desconhecido não deve contaminar o campo Responsável.

### Preservar a ordem da folha

A sequência física das liberações é mantida.

### Falhas devem ser recuperáveis

Uma exceção não deve deixar a interface travada ou impedir o processamento restante.

### Dados reais não devem ser versionados

Bases de colaboradores, gestores, motivos, imagens de documentos e arquivos de saída contendo dados reais devem permanecer fora do repositório público.

---

## Limitações atuais

* O OCR roda em CPU e é relativamente lento.
* Caligrafia muito ilegível pode resultar em `REVISÃO`.
* Uma matrícula parcialmente cortada ou ilegível pode não ser recuperada.
* Gestores parcialmente cortados podem exigir revisão manual.
* A qualidade da fotografia influencia diretamente o OCR.
* O parser ainda trabalha com OCR da página inteira + geometria, sem ROIs fixas por campo.
* O agrupamento espacial foi validado com um conjunto limitado de folhas reais e pode exigir novos ajustes caso surjam formulários ou condições de captura muito diferentes.

### Limitações das recuperações de OCR

As recuperações descritas acima cobrem deformações **previsíveis**. O que fica de fora continua em `REVISÃO` por falta de evidência — o que é o comportamento pretendido, não uma falha:

* **Responsável cortado ou muito deformado** é o maior grupo de revisões: nome cortado na foto, código com letra que não corresponde a nenhum gestor cadastrado, rabisco. O sistema não escolhe o candidato "mais parecido" só porque ele existe.
* **Motivo com evidência de um critério só**: leituras muito corrompidas podem ficar acima do limiar mas sem nenhum critério secundário que as corrobore. Preferiu-se `REVISÃO`.
* **Ano lido errado** não é reescrito, apenas sinalizado. Se um lote tiver muitas datas com o ano mal reconhecido, o contexto do lote é desligado por segurança e as datas sem ano voltam a `REVISÃO`.
* **O contexto do lote é sequencial**: uma folha sem ano processada antes de o lote acumular datas completas suficientes não é recuperada.
* **Motivo e Responsável não têm filtro de formato** como Data e Hora têm, então um fragmento de texto impresso do formulário ainda pode, ocasionalmente, cair em uma dessas colunas.

Aumentar o número de `CONFIRMADO` nunca é objetivo em si. É esperado — e aceitável — que uma melhoria apenas corrija os dados internos das linhas sem mudar o status delas.

### Qualidade da imagem

As folhas reais podem apresentar diferentes níveis de iluminação e tonalidade, inclusive papel reciclado ou mais escuro.

O pré-processamento atual utiliza:

```text
OpenCV
   ↓
grayscale
   ↓
redução de ruído
   ↓
CLAHE
   ↓
nitidez
```

Testes com folhas de tonalidade escura não demonstraram vantagem consistente de abandonar o grayscale atual.

Por isso, nenhuma alteração foi feita apenas para tentar acelerar ou modificar o pré-processamento sem evidência de ganho.

---

## Segurança dos dados

O projeto pode trabalhar com informações pessoais e operacionais presentes nas folhas e nas bases XLSX.

Por isso:

* arquivos reais de colaboradores não devem ser enviados ao repositório público;
* imagens reais de documentos não devem ser versionadas;
* PDFs reais não devem ser versionados;
* planilhas de entrada e saída contendo dados reais não devem ser versionadas;
* logs contendo informações sensíveis devem permanecer fora do repositório;
* exemplos presentes na documentação devem utilizar dados fictícios;
* o arquivo `.gitignore` deve impedir o versionamento acidental de arquivos locais.

O repositório contém apenas o código, testes e documentação necessários ao desenvolvimento do sistema.

---

## Evolução do projeto

A reorganização arquitetural já foi concluída: o código está separado por responsabilidade em `src/leitor_matriculas/`, com dependência de mão única e grafo acíclico, sem alteração de comportamento funcional.

Percurso até aqui, em ordem:

```text
MVP estável
    ↓
reorganização da arquitetura
    ↓
preparação para operação em lote real
    ↓
recuperação contextual de OCR
    ↓
motor de evidências + revisão inteligente
    ↓
performance e aprendizado com correções humanas (medidos; poucas adoções — ver abaixo)
    ↓
revolução de UX/UI e redesign visual (interface Tkinter)
    ↓
Web MVP (React + FastAPI, mesmo núcleo do Tkinter)
    ↓
empacotamento em .exe portátil
    ↓
OCR Worker distribuído (VPS + Worker Windows) — em andamento
```

Cada evolução preserva os comportamentos já validados contra o mesmo conjunto de folhas reais e mantém a suíte de testes como mecanismo de proteção contra regressões. Boa parte do que foi **investigado e propositalmente não adotado** (extração por ROI/template, confirmação automática por contexto de lote, redução de limiares de correspondência aproximada, aprendizado automático a partir de correções manuais, paralelismo de OCR) tem tanto peso na arquitetura atual quanto o que foi adotado — cada decisão veio de medição contra fotos reais, não de preferência. O histórico completo, fase a fase, com os números que sustentaram cada decisão, está na skill `.claude/skills/historico-do-projeto/` deste repositório (para quem usa Claude Code) ou em `CLAUDE.md`/`saida/*.md`.

Direções em andamento ou possíveis a partir daqui, sem compromisso de prazo:

* concluir a distribuição do OCR Worker (frontend adaptado ao modelo de fila/Job, deploy da VPS documentado);
* desempenho do OCR em si (GPU ou modelo mais rápido), únicas alternativas que restaram depois de medir que o entorno do OCR (paralelismo, cache, I/O) não tem folga real para otimizar;
* ampliação das recuperações contextuais, sempre com o mesmo critério: precisão antes de cobertura.
