"""
pdf_segmenter.py

Entry point kept for backward compatibility: extract_pdf_questions(pdf_path)
returns the same shape as before (list of dicts with page, column,
item_number, rect, header_text, text), consumed by
pipeline/run_dataset_parsing.py and dataset_parser/latex_extractor.py.

Previously implemented with PyMuPDF (fitz) page.get_text("blocks"), which
(a) discards per-character coordinates -- destroying 2D math structure
(fraction numerators/denominators, integral/sigma limits, radical
extents, and multiline delimiters all got orphaned onto their own lines,
e.g. 202606_MATH_DIF_15's printed
    (가) ∫_p^{p+3}|f(x)|dx ≠ |∫_p^{p+3}f(x)dx|
decoded as six separate stranded lines) and (b) is not installable in
this sandbox at all (no network access to fetch PyMuPDF).

The actual extraction + 2D layout reconstruction now lives in
hwp_layout_reconstructor.py, built on pdfminer.six (which does expose
per-character bounding boxes). This module is intentionally a thin
pass-through so the public contract other pipeline stages depend on
stays put.
"""

from dataset_parser.hwp_layout_reconstructor import extract_pdf_questions

__all__ = ["extract_pdf_questions"]
