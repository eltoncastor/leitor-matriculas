# Pasta `dados/`

Coloque aqui os três arquivos reais, exatamente com estes nomes:

```
dados/
├── Colaboradores.xlsx
├── Motivos.xlsx
└── Gestores.xlsx
```

Esta pasta está vazia de propósito — os arquivos reais ainda não foram
fornecidos ao assistente durante o desenvolvimento, então nenhum dado de
exemplo foi criado (nem nomes, nem matrículas, nem cabeçalhos inventados).

## O que o `data_manager.py` espera de cada arquivo

O `DataManager` procura a coluna certa pelo **nome do cabeçalho na primeira
linha** de cada planilha, comparando de forma tolerante a maiúsculas,
acentos e espaços. Ele tenta, nesta ordem, os seguintes nomes candidatos
(ajustáveis em `data_manager.py`, nas listas `CANDIDATOS_*`):

### `Colaboradores.xlsx`

| Campo | Cabeçalhos candidatos hoje |
|---|---|
| matrícula (obrigatório) | matricula, matricula colaborador, cod colaborador, codigo, codigo colaborador, registro, num matricula, numero matricula, chapa, num registro |
| nome | nome, nome colaborador, colaborador, funcionario, nome completo |
| cargo | cargo, funcao, cargo colaborador |
| setor | setor, departamento, area, setor colaborador |

Se a coluna de matrícula não for encontrada, o carregamento falha com uma
mensagem clara (não trava o programa) — nesse caso, adicione o cabeçalho
real à lista `CANDIDATOS_MATRICULA`.

Nome/cargo/setor são opcionais: se não forem encontrados, o colaborador é
carregado só com a matrícula.

### `Motivos.xlsx`

Coluna candidata: motivo, motivos, descricao, nome motivo, descricao
motivo. Se nenhuma bater, a primeira coluna da planilha é usada.

### `Gestores.xlsx`

Coluna candidata: gestor, gestores, nome gestor, nome. Se nenhuma bater, a
primeira coluna da planilha é usada.

## Depois de colocar os arquivos reais aqui

Quando os três arquivos forem colocados nesta pasta, a segunda etapa
combinada com o usuário é: abrir cada planilha, conferir os cabeçalhos
reais, ajustar as listas `CANDIDATOS_*` em `data_manager.py` se necessário,
e então validar as consultas (`buscar_colaborador`, `listar_motivos`,
`listar_gestores`) com dados de verdade — inclusive testando matrículas com
zero à esquerda.
