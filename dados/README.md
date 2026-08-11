# Pasta `dados/`

Esta pasta contém as bases XLSX utilizadas pelo sistema para validação e consulta.

```text
dados/
├── Colaboradores.xlsx
├── Gestores.xlsx
└── Motivos.xlsx
```

> **Importante:** os arquivos XLSX reais não devem ser versionados no Git. Eles podem conter dados internos de colaboradores e devem permanecer apenas no ambiente local.

## Bases utilizadas

### `Colaboradores.xlsx`

Base utilizada para validar a matrícula reconhecida pelo OCR.

A matrícula é o campo obrigatório. Nome, cargo e setor são informações complementares e **não são reconhecidos pelo OCR**.

O sistema utiliza a matrícula para localizar posteriormente essas informações na base de colaboradores.

Cabeçalhos candidatos para matrícula:

```text
matricula
matricula colaborador
cod colaborador
codigo
codigo colaborador
registro
num matricula
numero matricula
chapa
num registro
```

Cabeçalhos candidatos para informações complementares:

| Campo | Cabeçalhos candidatos                                           |
| ----- | --------------------------------------------------------------- |
| Nome  | nome, nome colaborador, colaborador, funcionario, nome completo |
| Cargo | cargo, funcao, cargo colaborador                                |
| Setor | setor, departamento, area, setor colaborador                    |

Se a coluna de matrícula não for encontrada, o sistema informa o problema sem travar a aplicação.

## `Gestores.xlsx`

Base utilizada para validar e identificar o responsável pela liberação.

Cabeçalhos candidatos:

```text
gestor
gestores
nome gestor
nome
```

O sistema identifica o gestor a partir do texto manuscrito e não deve incluir textos residuais desconhecidos no resultado.

## `Motivos.xlsx`

Base utilizada para validar e normalizar o motivo da liberação.

Cabeçalhos candidatos:

```text
motivo
motivos
descricao
nome motivo
descricao motivo
```

Quando nenhuma dessas opções for encontrada, a primeira coluna da planilha pode ser utilizada.

## Regras importantes

* Os nomes dos arquivos devem permanecer exatamente como especificados.
* A primeira linha de cada planilha deve conter os cabeçalhos.
* A identificação dos cabeçalhos é tolerante a maiúsculas, acentos e espaços.
* `Colaboradores.xlsx`, `Gestores.xlsx` e `Motivos.xlsx` são bases reais fornecidas pelo usuário.
* `Auxiliares.xlsx` **não é utilizado pelo sistema** e não precisa estar presente.
* O sistema não cria dados fictícios para substituir essas bases.
* Matrículas com zero à esquerda devem ser preservadas corretamente.

## Dados locais

Esta pasta é parte do ambiente local da aplicação. Os arquivos reais são ignorados pelo Git por segurança.

Para utilizar o projeto em outra máquina, copie manualmente as bases reais para esta pasta antes de executar o processamento.

Consulte `data_manager.py` caso seja necessário adaptar os nomes dos cabeçalhos às planilhas utilizadas no ambiente.
