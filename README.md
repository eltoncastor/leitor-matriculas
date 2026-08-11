# Leitor de Matrículas Manuscritas

Ferramenta desktop para Windows, desenvolvida em Python/Tkinter, que transforma fotos ou PDFs das folhas físicas de liberação do cartão mestre em uma planilha XLSX estruturada.

O sistema utiliza OCR com PaddleOCR para reconhecer os dados manuscritos, valida as informações contra bases XLSX e envia automaticamente para revisão manual os casos que não podem ser confirmados com segurança.

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

Esses dados não fazem parte do resultado principal da extração e serão obtidos posteriormente a partir da matrícula, por exemplo utilizando `PROCX/XLOOKUP` em outra planilha.

Isso evita processamento desnecessário e reduz o risco de associar uma pessoa incorreta a uma matrícula.

### Hora

A Hora é um campo **opcional**.

Se Data + Matrícula + Motivo + Responsável forem confirmados, a ausência ou ilegibilidade da Hora não impede a confirmação do registro.

Quando a Hora não puder ser reconhecida com segurança:

```text
Hora = vazia
```

O sistema nunca inventa uma hora.

### Responsável

O campo Responsável representa principalmente o **gestor que autorizou a liberação**.

Algumas folhas podem conter texto adicional após o gestor, como o nome de um auxiliar que estava na portaria. Esse texto residual é ignorado.

Exemplo:

```text
GRL - FABIANA - ESLEON
```

Resultado:

```text
Responsável = GRL - FABIANA
```

O sistema não tenta identificar ou corrigir o nome do auxiliar.

Nomes compostos e identificações com código de cargo são preservados.

Exemplos válidos:

```text
GR3 - DIANA
GR4 - ANDRÉ VALENÇA
ANDERSON ABREU
ANDERSON CARLOS
```

Quando o gestor não puder ser identificado com segurança, o registro é enviado para `REVISÃO`.

---

## Arquitetura atual

```text
leitor_matriculas/
├── main.py
├── ui.py
├── ocr_engine.py
├── image_processor.py
├── pdf_reader.py
├── registro_parser.py
├── tempo_parser.py
├── data_manager.py
├── correspondencia_aproximada.py
├── validacao.py
├── xlsx_exporter.py
├── exporter.py
│
├── dados/
│   ├── LEIA-ME.txt
│   ├── Colaboradores.xlsx
│   ├── Gestores.xlsx
│   └── Motivos.xlsx
│
├── teste/
├── requirements.txt
└── README.md
```

A estrutura atual ainda será reorganizada em uma futura fase de refatoração arquitetural. Essa reorganização deverá preservar o comportamento e os testes existentes.

---

## Principais módulos

| Arquivo                         | Responsabilidade                                         |
| ------------------------------- | -------------------------------------------------------- |
| `main.py`                       | Ponto de entrada                                         |
| `ui.py`                         | Interface gráfica Tkinter e coordenação do processamento |
| `ocr_engine.py`                 | Inicialização e execução do PaddleOCR                    |
| `image_processor.py`            | Pré-processamento das imagens                            |
| `pdf_reader.py`                 | Renderização de PDFs página por página                   |
| `registro_parser.py`            | Agrupamento espacial dos elementos OCR em registros      |
| `tempo_parser.py`               | Interpretação e validação de Data/Hora                   |
| `data_manager.py`               | Carregamento das bases XLSX                              |
| `correspondencia_aproximada.py` | Correspondência aproximada controlada                    |
| `validacao.py`                  | Classificação dos registros                              |
| `xlsx_exporter.py`              | Geração da planilha XLSX                                 |
| `exporter.py`                   | Exportação CSV legada                                    |

---

## Bases de dados

As bases utilizadas pelo sistema ficam em:

```text
dados/
├── Colaboradores.xlsx
├── Gestores.xlsx
└── Motivos.xlsx
```

### Colaboradores.xlsx

Utilizada para validação da matrícula.

O sistema não precisa reconhecer Nome ou Setor por OCR.

A matrícula é utilizada posteriormente para obter essas informações.

### Gestores.xlsx

Contém os gestores e suas possíveis formas de identificação.

A base pode conter:

```text
GR3 - DIANA
GR3
DIANA
ANDERSON ABREU
ABREU
A. ABREU
```

Essas entradas não devem necessariamente ser interpretadas como pessoas diferentes. Algumas podem representar aliases, códigos ou formas alternativas de identificação.

### Motivos.xlsx

Contém os motivos válidos utilizados na validação e no fuzzy matching controlado.

---

## Instalação

Windows + PowerShell:

```powershell
cd leitor_matriculas
python -m venv venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Na primeira execução, o PaddleOCR pode baixar os modelos necessários.

Após os modelos estarem disponíveis, o processamento pode funcionar localmente sem depender de serviços externos.

---

## Executar

```powershell
python main.py
```

### Selecionar imagem

Processa uma foto individual de uma folha.

### Selecionar PDF

Processa as páginas do PDF individualmente.

Uma falha em uma página não deve interromper o processamento das demais.

### Revisão

Exibe registros que não puderam ser confirmados automaticamente.

### Gerar XLSX

Gera a planilha final com os registros processados.

A ordem das liberações é preservada de acordo com a ordem encontrada no papel.

---

## Validação

O sistema trabalha principalmente com dois estados:

### CONFIRMADO

Registro em que os dados necessários puderam ser identificados e validados com segurança.

A confirmação considera principalmente:

* Matrícula;
* Data;
* Motivo;
* Responsável;
* bases de validação disponíveis;
* confiança do OCR;
* correspondências aproximadas quando aplicáveis.

A Hora não é obrigatória para confirmação.

### REVISÃO

Registro que contém alguma informação necessária que não pôde ser confirmada com segurança.

Exemplos:

* matrícula ilegível;
* matrícula não encontrada;
* gestor ambíguo;
* motivo não reconhecido;
* data inválida ou incompleta;
* informação insuficiente para confirmação.

O sistema não inventa dados para evitar uma revisão.

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

Exemplo:

```text
OCR:
GR3 - DIANA - TEXTO_DESCONHECIDO

Resultado:
Responsável = GR3 - DIANA
```

O texto desconhecido é ignorado.

Não existe mais reconhecimento de auxiliar de portaria no resultado.

---

## Ordem dos registros

A ordem das liberações encontrada na folha é preservada.

O sistema não deve ordenar os registros por:

* nome;
* matrícula;
* gestor;
* motivo.

A sequência da folha é a referência principal para a saída.

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

A suíte pode ser executada pelos arquivos individuais em `teste/`.

Exemplos:

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
```

A suíte atual possui **100 testes sintéticos + integração UI**, todos aprovados no último ciclo de estabilização.

Também foram realizados testes com PaddleOCR real sobre um PDF contendo **5 folhas reais**.

Resultado:

```text
Esperado: 40 liberações
Encontrado: 40 liberações

40/40 = 100%
```

---

## Validação com dados reais

O sistema foi validado com um PDF real contendo cinco folhas.

Resultado:

| Página    | Liberações esperadas | Detectadas |
| --------- | -------------------: | ---------: |
| 1         |                    8 |          8 |
| 2         |                    8 |          8 |
| 3         |                    8 |          8 |
| 4         |                    8 |          8 |
| 5         |                    8 |          8 |
| **Total** |               **40** |     **40** |

A página 3 inicialmente apresentava apenas cinco registros devido a um problema no agrupamento espacial dos elementos OCR.

O algoritmo de agrupamento foi corrigido e a página passou a detectar corretamente as oito liberações.

Nenhum registro fantasma foi observado após a correção.

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

---

## Limitações atuais

* O OCR roda em CPU e é relativamente lento.
* Caligrafia muito ilegível pode resultar em `REVISÃO`.
* Uma matrícula parcialmente cortada ou ilegível pode não ser recuperada.
* Gestores parcialmente cortados podem exigir revisão manual.
* A qualidade da fotografia influencia diretamente o OCR.
* O parser ainda trabalha com OCR da página inteira + geometria, sem ROIs fixas por campo.
* O agrupamento espacial foi validado com um conjunto limitado de folhas reais e pode exigir novos ajustes caso surjam formulários ou condições de captura muito diferentes.

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

Testes com folha de tonalidade escura não demonstraram vantagem consistente de abandonar o grayscale atual.

Por isso, nenhuma alteração foi feita apenas para tentar acelerar ou modificar o pré-processamento sem evidência de ganho.

---

## Próximas fases

O MVP atual está em fase de estabilização.

A próxima grande etapa prevista é uma **reorganização arquitetural completa**, sem alteração do comportamento funcional.

Objetivos futuros:

```text
MVP estável
    ↓
reorganização da arquitetura
    ↓
separação clara de responsabilidades
    ↓
estrutura de pastas mais limpa
    ↓
redução de acoplamento
    ↓
testes de regressão
    ↓
nova evolução funcional
```

A refatoração arquitetural deverá preservar os comportamentos já validados e manter a suíte de testes como mecanismo de proteção contra regressões.
