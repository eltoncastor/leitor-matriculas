# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Comments, docstrings, and CLI/UI output in this codebase are all in Portuguese (pt-BR); match that when editing.

## Commands

```powershell
# Setup (Windows, PowerShell) — Python 3.10.11
python -m venv venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Run the app
python main.py

# Tests (no test runner/framework — each file is a standalone script, run individually)
python teste\teste_ocr.py <foto>              # smoke test against real PaddleOCR; needs a real image
python teste\teste_data_manager.py [matricula]
python teste\teste_registro_parser.py          # synthetic fixtures, no external deps
python teste\teste_pdf_reader.py               # synthetic PDFs
python teste\teste_validacao.py
python teste\teste_tempo_parser.py             # date/time parsing, synthetic, no external deps
python teste\teste_xlsx_exporter.py
python teste\teste_ui_integracao.py            # end-to-end, PaddleOCR mocked
python teste\teste_erro_pagina.py              # a failing PDF page must not abort the batch
python teste\teste_correspondencia_aproximada.py  # fuzzy matching for MOTIVO/RESPONSÁVEL, synthetic
python teste\teste_extracao_fase1.py           # Fase 1 precision fixes: printed-text exclusion, expected-count check, DATA+HORA merge-split
```

There is no lint/format tooling configured. PaddleOCR downloads its models on first run (needs internet once; offline after that).

## Architecture

Desktop Tkinter app that turns photographed/scanned "master card release" sheets into a structured XLSX. Pipeline, implemented as a strict one-way chain of independent modules, orchestrated only by `ui.py`:

```
image_processor (OpenCV preprocessing)
  → ocr_engine (PaddleOCR 3.x → OCRResult: texto + confiança + box)
  → registro_parser (groups OCRResults into table rows by spatial position)
  → validacao (classifies each Registro: CONFIRMADO / REVISAO; validates data/hora via tempo_parser)
  → xlsx_exporter (sorts chronologically, writes the 3-sheet workbook)
```

`pdf_reader.py` and `data_manager.py` feed into this chain independently (PDF→image generator; XLSX reference lookups), and `main.py` just launches `ui.App`.

**Design invariant across every module**: never invent or guess data. Anything that can't be confirmed with certainty is routed to manual review (`REVISAO`) rather than auto-corrected — this shows up repeatedly (conservative bbox-distance cutoffs in `registro_parser.py`, `normalizar_matricula` refusing to touch non-matricula-looking text, `tempo_parser` refusing to guess a missing year, and the fuzzy matching in `correspondencia_aproximada.py` refusing to pick between two similarly-close candidates).

**Fase 1 — precisão da extração das 8 liberações** (see module contracts below for specifics): the sheet is a printed form with a fixed structure of 8 liberação rows × 5 handwritten fields. This phase added, incrementally, on top of the still-generic full-page-OCR + spatial-parser pipeline (Estratégia A from the analysis that preceded it — full template/ROI extraction was deliberately deferred, not adopted):
  - printed text (titles, form code, footer) rejected from ever becoming a fake DATA/HORA value or a phantom registro (`registro_parser.py`: format gate + `linhas_ignoradas`);
  - 8-per-page is used only as a validation signal (`verificar_contagem_posicoes`), never to fabricate or drop a registro;
  - MOTIVO and RESPONSÁVEL get a controlled fuzzy match against their base lists when the exact match fails (`correspondencia_aproximada.py`, wired into `validacao.py`) instead of unconditionally going to REVISAO on any OCR noise;
  - a DATA+HORA pair glued into a single OCR box (a real detector-level artifact, not a parser bug) is split only when both halves independently validate (`tempo_parser.tentar_separar_data_hora_mesclada`, applied in `ui.py`).
  Known residual limitation from this phase: free-text columns (MOTIVO/RESPONSÁVEL) have no format gate the way DATA/HORA do, so a printed fragment can still occasionally land in one of those columns if it's the only candidate in an otherwise-empty footer row; it has never been observed to cause a false CONFIRMADO (the resulting registro still lacks a matrícula), but it is not fully eliminated. See the Fase 1 report for the real-photo evidence.

**Definitive functional requirement — read-from-sheet vs. derived-from-lookup**: only DATA, HORA, MATRÍCULA, MOTIVO and RESPONSÁVEL (gestor) are handwritten data the OCR is meant to recognize. NOME and SETOR are never read from the sheet — they are always derived by looking up the recognized MATRÍCULA in `Colaboradores.xlsx` (a PROCV/XLOOKUP-style join, in `data_manager.buscar_colaborador`). This is enforced structurally in `registro_parser.py`: `CAMPOS_TODOS` (the fields exposed to callers) excludes `nome`/`setor`, even though the header-detection step still locates those columns' x-position internally (`CABECALHOS_CONHECIDOS` keeps them, `CAMPOS_IGNORADOS_NA_SAIDA` strips them back out after association) — this is not optional plumbing, it's what stops a NOME/SETOR-column text from bleeding into the neighboring MATRÍCULA/MOTIVO column once those two fields stop being "real" destinations. When a matrícula isn't found in the base, `ui.py` shows an explicit `"(não encontrado)"` placeholder for nome/cargo/setor rather than a blank string — an unconfirmed value must never look like "genuinely empty but valid".

**Module contracts** (each is independently testable and deliberately decoupled from its neighbors):
- `image_processor.py` — OpenCV preprocessing (grayscale, denoise, CLAHE, sharpen); never mutates the input image, returns a new one. Adaptive threshold is off by default (destroys thin pen strokes on handwriting).
- `ocr_engine.py` — `OCREngine` ABC wraps PaddleOCR 3.x behind `recognize(image) -> List[OCRResult]`, so the engine could be swapped later. **Written specifically for PaddleOCR's 3.x `predict()` API** (`requirements.txt` pins `paddleocr>=3.7.0,<4.0.0` on purpose) — the 2.x `ocr.ocr()` API has a different constructor and return shape; do not downgrade. Also holds `parece_matricula()`/`normalizar_matricula()`, a conservative heuristic for fixing common handwritten OCR confusions (O↔0, I/l↔1, S↔5, B↔8) — applied only to text that already looks like a matricula, never to names/columns.
- `registro_parser.py` — pure spatial parser: takes the flat `OCRResult` list (unordered) and reconstructs table rows using only bounding-box geometry (vertical-overlap grouping into lines, header-row detection via known column labels in `CABECALHOS_CONHECIDOS` — matched by **substring**, not equality, since the real printed header is a full phrase like "RESPONSÁVEL PELA AUTORIZAÇÃO" that OCR may add noise to, then greedy nearest-column association bounded by `_distancia_maxima_padrao`). Has zero dependency on PaddleOCR — only touches the `OCRResult` dataclass — and does no calendar/database validation itself. A `Registro` is "complete" iff it has a `matricula` field; nothing else is required. Only exposes `matricula`/`gestor`/`motivo`/`data`/`hora` as named fields (see functional requirement above) — `nome`/`setor` text is detected for column geometry only, then always moved to `nao_associados`. **Fase 1 additions**: the DATA/HORA columns have a loose FORMAT gate (`_PARECE_DATA`/`_PARECE_HORA` — structure only, not calendar validity) so printed text without digit-separator-digit structure can never be associated to those columns; a data row that ends up with zero associated fields when a header WAS detected is not turned into a registro at all — it's kept, unmodified, in `ResultadoParser.linhas_ignoradas` (never silently dropped, just kept out of `registros`); `verificar_contagem_posicoes(quantidade_encontrada)` compares against `POSICOES_ESPERADAS_POR_FOLHA = 8` and returns a warning string (or `None`) — purely informational, never used to fabricate or discard a registro.
- `tempo_parser.py` — structured DATA/HORA interpretation (`interpretar_data`/`interpretar_hora`/`interpretar_data_hora`/`validar_data_hora`), independent of everything else. Same "never invent" invariant: a 2-digit year is expanded to 20xx (the digit is genuinely on the page, just abbreviated — not a guess), but a date with **no year at all is rejected**, not defaulted to "this year" — there'd be no way to tell that apart from an actual guess. Impossible dates/times (`date()`/`time()` raising `ValueError`) and unparseable formats both return `None`. **Fase 1 addition**: `tentar_separar_data_hora_mesclada(texto)` handles a real OCR-detector artifact where DATA and HORA get glued into a single box (e.g. `"14.04 26 20:24"`) — it locates loosely-shaped date/hora substrings, reconstructs canonical strings from the digits actually present (never invents a digit), and only returns a split when **both** halves independently pass the same strict `interpretar_data`/`interpretar_hora`; called from `ui.py`, not from `registro_parser.py` (keeps the parser decoupled from date semantics).
- `data_manager.py` — loads the 3 reference workbooks from `dados/` (`Colaboradores.xlsx`, `Gestores.xlsx`, `Motivos.xlsx`) read-only. Column names are matched against configurable candidate-lists (`COLUNAS_CANDIDATAS_*` at the top of the file) rather than hardcoded — **update those lists, not the surrounding logic**, if real spreadsheets use different headers. Never raises to callers: load failures accumulate as strings in `self.avisos` and the corresponding collection stays empty. Matricula is always kept as text (never int/float) to avoid losing leading zeros.
- `correspondencia_aproximada.py` (Fase 1) — controlled, contextual fuzzy matching used **only** for MOTIVO and RESPONSÁVEL against their closed candidate lists (never for matrícula, nome, setor, or open-ended text). `buscar_correspondencia(texto_ocr, candidatos)` normalizes (uppercase, strip accents), scores every candidate with `difflib.SequenceMatcher` (stdlib, no new dependency), and returns one of `EXATA`/`APROXIMADA`/`AMBIGUA`/`SEM_CORRESPONDENCIA`/`SEM_CANDIDATOS`/`VAZIO`. `AMBIGUA` fires whenever the best and second-best candidates are closer than `MARGEM_AMBIGUIDADE_PADRAO` — it never guesses between two similarly-plausible candidates. Thresholds (`LIMIAR_MINIMO_PADRAO = 0.55`, margin `0.08`) were tuned empirically against real `Motivos.xlsx`/`Gestores.xlsx` content and real printed-form noise (see Fase 1 report) — revisit them together if either base changes shape drastically.
- `validacao.py` — classifies a `Registro` as `CONFIRMADO`/`REVISAO` against `DataManager` data. Checks completeness first, then DATA/HORA validity (via `tempo_parser.validar_data_hora` — any value that can't be safely interpreted sends the record to REVISAO), then matrícula lookup/confidence, then gestor and motivo **independently** against the loaded lists (Fase 1: each goes through `correspondencia_aproximada.buscar_correspondencia` — exact match first, controlled fuzzy match second; neither field's failure short-circuits the other, so an accepted motivo correction isn't lost just because gestor still needs review). `CONFIANCA_MINIMA_MATRICULA = 0.80` is the OCR-confidence floor. Missing/unavailable reference data never blocks confirmation by penalizing — it just can't confirm. Returns a `ResultadoValidacao` — a tuple subclass, so `status, observacao = classificar_registro(...)` (the original 2-tuple contract) still works unchanged everywhere — that also exposes `.motivo_confirmado`/`.gestor_confirmado` (the fuzzy-accepted value, or `None` when no correction was needed/possible) for whoever builds the export row.
- `pdf_reader.py` — `iterar_paginas()` is a generator (via PyMuPDF/`fitz`) that renders one page at a time so a ~200-page monthly PDF is never fully loaded into memory. A single page failing to render yields a `PaginaPdf(erro=...)` and the generator continues; only whole-document failures (bad file, zero pages) raise.
- `xlsx_exporter.py` — formatter + sorter: takes a list of already-assembled dicts (built in `ui.py` from `Registro` + `classificar_registro` output), reorders them chronologically by real `data`+`hora` (via `tempo_parser.interpretar_data_hora`, not string comparison — records without a safely-interpretable date/hora go last, preserving their relative order, never dropped), then writes `Liberações` (all rows) / `Revisão` (REVISAO+ERRO rows) / `Resumo` (counts, breakdowns by gestor/motivo, plus a Fase 1 "páginas com contagem divergente do esperado" count) sheets. The first 7 columns of `COLUNAS` are a fixed, mandated order — Data, Hora, Matrícula, Nome, Setor, Motivo, Responsável — with everything else (Cargo, Página, Status, confidences, Observação, raw OCR text) kept after those as audit/technical info. Does no reading or inference beyond that.
- `exporter.py` — a simpler CSV exporter that exists but is **not wired into the UI** currently.
- `ui.py` — the only module allowed to import/coordinate the others. OCR runs on a background `threading.Thread`; results cross back to the main thread exclusively via `queue.Queue` + `self.after(...)` polling — the worker thread must never touch Tkinter widgets directly. Multiple image/PDF selections accumulate into the same in-memory result table until "Limpar resultados" is used. The live results table is independent of the export column order (it leads with Página/Status for quick monitoring during processing) — only the exported XLSX is required to follow the mandated 7-column order. **Fase 1 additions**: `_processar_uma_pagina` runs `_reparar_data_hora_mescladas` on the parsed registros right after `parse_registros` (before validação) to apply the DATA+HORA merge-split; `_adicionar_registros` uses `resultado_classificacao.motivo_confirmado`/`.gestor_confirmado` when building the table row / export dict, falling back to the raw OCR text when no correction applied; a page whose registro count diverges from `registro_parser.verificar_contagem_posicoes` is tracked in `self._avisos_contagem` and surfaced through a dedicated "Avisos de contagem" button (same pattern as "Erros de página").

## Data files

`dados/Colaboradores.xlsx`, `dados/Gestores.xlsx`, `dados/Motivos.xlsx` are user-supplied and not checked in (see `dados/LEIA-ME.txt`). The app runs without them — everything just falls into REVISAO for lack of a way to confirm.
