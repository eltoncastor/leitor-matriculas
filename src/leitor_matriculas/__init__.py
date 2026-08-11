"""
Pacote do Leitor de Matrículas.

O código é organizado por RESPONSABILIDADE, na mesma ordem do pipeline:

    ocr/         pré-processamento de imagem, motor de OCR e leitura de PDF
    parsing/     reconstrução espacial dos registros e interpretação de data/hora
    validacao/   classificação CONFIRMADO/REVISAO e correspondência aproximada
    dados/       carregamento das bases XLSX de apoio (pasta dados/ na raiz)
    exportacao/  geração da planilha final
    ui/          interface Tkinter -- único módulo que coordena os demais

A dependência é de mão única (ocr -> parsing -> validacao -> exportacao,
com ui por cima de todos): nenhum módulo de baixo importa um de cima, o
que mantém o grafo acíclico.
"""
