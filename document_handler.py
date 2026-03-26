"""Document handling: .docx read/write with formatting preservation, PDF parsing, PDF export."""

import io
import os
import re
import copy
import tempfile
from dataclasses import dataclass, field
from docx import Document
from docx.shared import Pt, RGBColor
import pdfplumber


@dataclass
class RunInfo:
    text: str
    bold: bool | None = None
    italic: bool | None = None
    underline: bool | None = None
    font_name: str | None = None
    font_size: int | None = None
    font_color_rgb: str | None = None


@dataclass
class ParagraphInfo:
    index: int
    style_name: str
    runs: list[RunInfo] = field(default_factory=list)
    full_text: str = ""
    alignment: int | None = None
    is_in_table: bool = False
    table_coords: tuple[int, int, int] | None = None  # (table_idx, row, col)


@dataclass
class DocumentStructure:
    paragraphs: list[ParagraphInfo] = field(default_factory=list)
    source_bytes: bytes = b""


def _extract_run_info(run) -> RunInfo:
    font = run.font
    color_rgb = None
    if font.color and font.color.rgb:
        color_rgb = str(font.color.rgb)
    return RunInfo(
        text=run.text,
        bold=font.bold,
        italic=font.italic,
        underline=font.underline,
        font_name=font.name,
        font_size=font.size,
        font_color_rgb=color_rgb,
    )


def _extract_paragraph_info(para, index: int, is_table=False, table_coords=None) -> ParagraphInfo:
    runs = [_extract_run_info(r) for r in para.runs]
    return ParagraphInfo(
        index=index,
        style_name=para.style.name if para.style else "Normal",
        runs=runs,
        full_text=para.text,
        alignment=para.alignment,
        is_in_table=is_table,
        table_coords=table_coords,
    )


def parse_docx(file_bytes: bytes) -> DocumentStructure:
    """Parse a .docx file into a DocumentStructure with all paragraphs indexed."""
    doc = Document(io.BytesIO(file_bytes))
    structure = DocumentStructure(source_bytes=file_bytes)
    idx = 0

    # Body paragraphs
    for para in doc.paragraphs:
        info = _extract_paragraph_info(para, idx)
        structure.paragraphs.append(info)
        idx += 1

    # Table paragraphs
    for t_idx, table in enumerate(doc.tables):
        for r_idx, row in enumerate(table.rows):
            for c_idx, cell in enumerate(row.cells):
                for para in cell.paragraphs:
                    info = _extract_paragraph_info(
                        para, idx, is_table=True, table_coords=(t_idx, r_idx, c_idx)
                    )
                    structure.paragraphs.append(info)
                    idx += 1

    return structure


def extract_plain_text(structure: DocumentStructure) -> str:
    """Convert DocumentStructure to plain text with [P:X] markers for each paragraph."""
    lines = []
    for p in structure.paragraphs:
        if p.full_text.strip():
            lines.append(f"[P:{p.index}] {p.full_text}")
    return "\n".join(lines)


def parse_rewrite_response(response: str) -> dict[int, str]:
    """Extract {paragraph_index: new_text} from Claude's [P:X] formatted response."""
    rewrites = {}
    pattern = r'\[P:(\d+)\]\s*(.+?)(?=\[P:\d+\]|\Z)'
    matches = re.findall(pattern, response, re.DOTALL)
    for idx_str, text in matches:
        rewrites[int(idx_str)] = text.strip()
    return rewrites


def rebuild_docx(original_bytes: bytes, structure: DocumentStructure, rewrites: dict[int, str]) -> bytes:
    """Rebuild the .docx with rewritten paragraphs, preserving formatting.

    Uses 'first-run absorb' strategy: puts all new text into the first run
    and clears remaining runs, preserving paragraph and first-run styling.
    """
    doc = Document(io.BytesIO(original_bytes))

    # Build a map from paragraph index to the actual paragraph object in the doc
    para_map = {}
    idx = 0
    for para in doc.paragraphs:
        para_map[idx] = para
        idx += 1
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for para in cell.paragraphs:
                    para_map[idx] = para
                    idx += 1

    # Apply rewrites
    for p_idx, new_text in rewrites.items():
        if p_idx not in para_map:
            continue
        para = para_map[p_idx]
        runs = para.runs
        if not runs:
            # No runs — just set paragraph text directly (loses no formatting since there was none)
            para.text = new_text
        elif len(runs) == 1:
            runs[0].text = new_text
        else:
            # First-run absorb: put all text in first run, clear the rest
            runs[0].text = new_text
            for r in runs[1:]:
                r.text = ""

    output = io.BytesIO()
    doc.save(output)
    return output.getvalue()


def parse_pdf(file_bytes: bytes) -> str:
    """Extract text from a PDF file using pdfplumber."""
    pages = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text()
            if text:
                pages.append(f"--- Page {i + 1} ---\n{text}")
    return "\n\n".join(pages)


def parse_pdf_resume(file_bytes: bytes) -> DocumentStructure:
    """Parse a PDF resume into a DocumentStructure (text-only, no formatting preservation).

    Since PDFs can't be round-tripped with formatting, we create a simple structure
    where each non-empty line becomes a paragraph. The rewrite output will be a new .docx.
    """
    raw_text = ""
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                raw_text += text + "\n"

    structure = DocumentStructure(source_bytes=file_bytes)
    idx = 0
    for line in raw_text.split("\n"):
        if line.strip():
            info = ParagraphInfo(
                index=idx,
                style_name="Normal",
                runs=[RunInfo(text=line.strip())],
                full_text=line.strip(),
            )
            structure.paragraphs.append(info)
            idx += 1

    return structure


def build_docx_from_text(rewrites: dict[int, str], structure: DocumentStructure) -> bytes:
    """Build a new .docx from scratch using the rewritten text mapped onto the original structure.

    Used when the source was a PDF (no .docx to modify). Produces a clean .docx
    with all paragraphs, applying rewrites where available.
    """
    doc = Document()
    for p in structure.paragraphs:
        text = rewrites.get(p.index, p.full_text)
        doc.add_paragraph(text)

    output = io.BytesIO()
    doc.save(output)
    return output.getvalue()


def docx_to_pdf(docx_bytes: bytes) -> bytes | None:
    """Convert a .docx to PDF using Microsoft Word (Windows only).

    Returns PDF bytes on success, or None if conversion fails.
    """
    try:
        from docx2pdf import convert

        with tempfile.TemporaryDirectory() as tmp_dir:
            docx_path = os.path.join(tmp_dir, "resume.docx")
            pdf_path = os.path.join(tmp_dir, "resume.pdf")

            with open(docx_path, "wb") as f:
                f.write(docx_bytes)

            convert(docx_path, pdf_path)

            with open(pdf_path, "rb") as f:
                return f.read()
    except Exception:
        return None


def chunk_reference_material(text: str, max_chars: int = 80000) -> list[str]:
    """Split large reference text into chunks at paragraph boundaries."""
    if len(text) <= max_chars:
        return [text]

    chunks = []
    paragraphs = text.split("\n\n")
    current_chunk = []
    current_len = 0

    for para in paragraphs:
        if current_len + len(para) + 2 > max_chars and current_chunk:
            chunks.append("\n\n".join(current_chunk))
            current_chunk = []
            current_len = 0
        current_chunk.append(para)
        current_len += len(para) + 2

    if current_chunk:
        chunks.append("\n\n".join(current_chunk))

    # Add headers
    total = len(chunks)
    if total > 1:
        chunks = [
            f"[Reference Material Part {i+1}/{total}]\n\n{chunk}"
            for i, chunk in enumerate(chunks)
        ]

    return chunks
