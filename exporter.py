"""
exporter.py

Exportação dos resultados reconhecidos para um arquivo CSV.

Importante: a matrícula (e qualquer texto reconhecido) é sempre gravada
como TEXTO, nunca como número, para não perder zeros à esquerda.

A estrutura de colunas foi ampliada para representar conceitualmente uma
liberação (matrícula, nome, cargo, setor, data, hora, gestor, motivo), já
preparando o CSV para quando o agrupamento por linha/coluna da folha for
implementado. Por enquanto, cada linha do CSV ainda corresponde a UM trecho
de texto reconhecido pelo OCR (não a uma liberação completa já montada) —
os campos que dependem de identificação de coluna/linha (data, hora, gestor,
motivo) ficam vazios até essa próxima etapa existir. `nome`, `cargo` e
`setor` já são preenchidos quando o texto reconhecido parece uma matrícula
e ela é encontrada em Colaboradores.xlsx (ver ui.py / data_manager.py).
"""

import csv
from typing import List, Dict

CSV_FIELDNAMES = [
    "arquivo",
    "matricula",
    "nome",
    "cargo",
    "setor",
    "data",
    "hora",
    "gestor",
    "motivo",
    "confianca_ocr",
    "texto_ocr_original",
    "box",
]


def export_to_csv(records: List[Dict], path: str) -> None:
    """
    Salva os registros reconhecidos em um arquivo CSV.

    Cada item de `records` pode conter as chaves (todas opcionais, exceto
    onde indicado):
        arquivo, matricula, nome, cargo, setor, data, hora, gestor, motivo,
        confianca_ocr, texto_ocr_original, box

    `box`, se presente, é gravado como texto "x1,y1,x2,y2" — é apenas
    informação de posição para uso futuro (agrupar textos por linha/coluna
    da tabela), não é usado neste MVP.

    Args:
        records: lista de resultados a exportar.
        path: caminho do arquivo .csv de destino.
    """
    if not records:
        raise ValueError("Nenhum registro para salvar.")

    # newline="" evita linhas em branco extras no Windows
    # utf-8-sig garante que o LibreOffice/Excel abram acentos corretamente
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        for record in records:
            box = record.get("box")
            box_str = ",".join(str(v) for v in box) if box else ""

            writer.writerow(
                {
                    "arquivo": record.get("arquivo", ""),
                    # Forçamos string em tudo que pode ter zero à esquerda
                    # (matrícula em primeiro lugar) para nunca virar número.
                    "matricula": str(record.get("matricula", "") or ""),
                    "nome": str(record.get("nome", "") or ""),
                    "cargo": str(record.get("cargo", "") or ""),
                    "setor": str(record.get("setor", "") or ""),
                    "data": str(record.get("data", "") or ""),
                    "hora": str(record.get("hora", "") or ""),
                    "gestor": str(record.get("gestor", "") or ""),
                    "motivo": str(record.get("motivo", "") or ""),
                    "confianca_ocr": record.get("confianca_ocr", ""),
                    "texto_ocr_original": str(record.get("texto_ocr_original", "")),
                    "box": box_str,
                }
            )
