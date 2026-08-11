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

O código-fonte fica em `src/leitor_matriculas/`, organizado por **responsabilidade**:

```text
leitor_matriculas/
├── main.py                     ponto de entrada (python main.py)
│
├── src/
│   └── leitor_matriculas/
│       ├── ocr/                entrada visual
│       │   ├── image_processor.py
│       │   ├── engine.py
│       │   └── pdf_reader.py
│       ├── parsing/            reconstrução dos registros
│       │   ├── registro_parser.py
│       │   └── tempo_parser.py
│       ├── validacao/          classificação dos registros
│       │   ├── regras.py
│       │   └── correspondencia_aproximada.py
│       ├── dados/              bases XLSX de apoio
│       │   └── data_manager.py
│       ├── exportacao/         geração da saída
│       │   ├── xlsx_exporter.py
│       │   └── csv_exporter.py
│       └── ui/                 interface Tkinter
│           └── app.py
│
├── dados/                      bases reais (locais, fora do Git)
│   ├── LEIA-ME.txt
│   ├── Colaboradores.xlsx
│   ├── Gestores.xlsx
│   └── Motivos.xlsx
│
├── entrada/                    fotos/PDFs reais (locais, fora do Git)
├── saida/                      planilhas geradas (locais, fora do Git)
├── teste/
├── requirements.txt
└── README.md
```

A dependência é de mão única — `ocr → parsing → validacao → exportacao`, com `ui` por cima de todos. Nenhum módulo de baixo importa um de cima, o que mantém o grafo acíclico.

O projeto roda direto do diretório, sem instalação via `pip`: o `main.py` acrescenta `src/` ao `sys.path` antes de importar o pacote.

---

## Principais módulos

| Módulo                                            | Responsabilidade                                         |
| ------------------------------------------------- | -------------------------------------------------------- |
| `main.py`                                          | Ponto de entrada                                         |
| `ui/app.py`                                        | Interface gráfica Tkinter e coordenação do processamento |
| `ocr/engine.py`                                    | Inicialização e execução do PaddleOCR                    |
| `ocr/image_processor.py`                           | Pré-processamento das imagens                            |
| `ocr/pdf_reader.py`                                | Renderização de PDFs página por página                   |
| `parsing/registro_parser.py`                       | Agrupamento espacial dos elementos OCR em registros      |
| `parsing/tempo_parser.py`                          | Interpretação e validação de Data/Hora                   |
| `dados/data_manager.py`                            | Carregamento das bases XLSX                              |
| `validacao/correspondencia_aproximada.py`          | Correspondência aproximada controlada                    |
| `validacao/regras.py`                              | Classificação dos registros                              |
| `exportacao/xlsx_exporter.py`                      | Geração da planilha XLSX                                 |
| `exportacao/csv_exporter.py`                       | Exportação CSV legada (não ligada à interface)           |

Os caminhos acima são relativos a `src/leitor_matriculas/`.

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

A Hora **não é obrigatória** para confirmação.

### REVISÃO

Registro que contém alguma informação necessária que não pôde ser confirmada com segurança.

Exemplos:

* matrícula ilegível;
* matrícula não encontrada;
* gestor ambíguo;
* motivo não reconhecido;
* data inválida ou incompleta;
* informação insuficiente para confirmação.

O sistema prefere enviar um registro para `REVISÃO` a inventar ou associar uma informação sem evidência suficiente.

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

A suíte atual possui **105 testes sintéticos + integração UI**, todos aprovados no último ciclo de estabilização (Fase 2).

Também foram realizados testes com PaddleOCR real sobre um conjunto de cinco folhas reais.

Resultado:

```text
Esperado: 40 liberações
Encontrado: 40 liberações

40/40 = 100%
```

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
