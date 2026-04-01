"""Document handling: .docx read/write with formatting preservation, PDF parsing, PDF export, JD fetching."""

import io
import os
import re
import copy
import html as html_module
import tempfile
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from docx import Document
from docx.shared import Pt, Emu, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml.ns import qn
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


def _strip_markdown(text: str) -> str:
    """Strip all Markdown formatting artifacts from LLM output.

    Removes **, *, __, _ (1-2 char sequences of asterisks/underscores)
    and stray backticks so raw LLM strings never leak into the Word document.
    """
    text = re.sub(r'[*_]{1,2}', '', text)
    text = re.sub(r'`', '', text)
    return text


def parse_rewrite_response(response: str) -> dict[int, str]:
    """Extract {paragraph_index: new_text} from LLM's [P:X] formatted response.

    STRICT regex parser: processes line-by-line. Uses regex to ONLY accept lines
    matching the exact [P:<digits>] pattern. Every other line — including
    Original:, Reason:, Checks:, commentary, explanations, and all other
    LLM chatter — is unconditionally discarded before it can touch the .docx.
    Strips any Markdown syntax from the extracted text.
    """
    _tag_pattern = re.compile(r'^\[P:(\d+)\]\s*(.+)')
    rewrites = {}
    for line in response.split("\n"):
        line = line.strip()
        if not line:
            continue
        m = _tag_pattern.match(line)
        if not m:
            continue
        idx = int(m.group(1))
        text = m.group(2).strip()
        clean = _strip_markdown(text)
        if clean:
            rewrites[idx] = clean
    return rewrites


def _is_skills_or_additional_line(text: str) -> bool:
    """Check if a line belongs to a Skills/Additional section (contains 'Label: value' pattern)."""
    if ":" not in text:
        return False
    prefix = text.split(":", 1)[0].strip().lower()
    skill_labels = {
        "skills", "languages", "tools", "technologies", "certifications",
        "interests", "activities", "awards", "honors", "co-founded",
    }
    return any(label in prefix for label in skill_labels)


def _add_colon_bolded_runs(para, text: str, font_name: str = "Calibri", font_size_pt: float = 10):
    """Add runs to a paragraph with the text before the colon bolded, rest normal weight."""
    colon_idx = text.index(":")
    header_part = text[:colon_idx + 1]
    remaining_part = text[colon_idx + 1:]

    run_bold = para.add_run(header_part)
    run_bold.font.name = font_name
    run_bold.font.size = Pt(font_size_pt)
    run_bold.bold = True

    if remaining_part:
        run_normal = para.add_run(remaining_part)
        run_normal.font.name = font_name
        run_normal.font.size = Pt(font_size_pt)
        run_normal.bold = False


def _count_bullets(doc) -> int:
    """Count experience-style bullets in a python-docx Document."""
    count = 0
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        is_bullet = (
            text.startswith(("•", "-", "–", "▪", "■"))
            or (len(text) > 30 and text[0].isupper() and not text.isupper()
                and not re.search(r'\b(19|20)\d{2}\b', text))
        )
        if is_bullet:
            count += 1
    return count


def _get_section_for_para(para_map: dict, p_idx: int, section_headers: set) -> str:
    """Walk backward through para_map to find which section a paragraph belongs to."""
    result = ""
    for scan_idx in sorted(para_map.keys()):
        if scan_idx > p_idx:
            break
        scan_text = para_map[scan_idx].text.strip()
        if scan_text.upper() == scan_text and scan_text.lower() in section_headers:
            result = scan_text.lower()
    return result


def rebuild_docx(original_bytes: bytes, structure: DocumentStructure, rewrites: dict[int, str]) -> bytes:
    """Rebuild the .docx with rewritten paragraphs, preserving formatting.

    Uses 'first-run absorb' strategy with strict 1-page vertical compression:
    - Forces 1.0" margins on all sides.
    - Font: Calibri 10pt throughout.
    - Line Spacing: Exactly 1.0 (Single).
    - Bullet spacing: space_before=0, space_after=2pt.
    - Section header spacing: space_before=6pt, space_after=2pt.
    - Applies colon-bolding for Additional/Skills section lines.
    - Removes trailing ghost paragraphs.
    """
    doc = Document(io.BytesIO(original_bytes))

    # ── Force 0.5" margins on all sections (matching Default_Resume.docx) ──
    for section in doc.sections:
        section.top_margin = Inches(0.5)
        section.bottom_margin = Inches(0.5)
        section.left_margin = Inches(0.5)
        section.right_margin = Inches(0.5)

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

    section_headers = {"experience", "education", "skills", "additional", "projects",
                       "work experience", "professional experience", "technical skills",
                       "technologies", "certifications", "leadership", "activities",
                       "interests", "summary", "awards", "languages"}

    # ── Strict Vertical Compression: 1-page Ross/HBS style ──
    for p_idx in sorted(para_map.keys()):
        para = para_map[p_idx]
        para_text = para.text.strip()
        pf = para.paragraph_format

        # Force single (1.0) line spacing on all paragraphs
        pf.line_spacing_rule = WD_LINE_SPACING.SINGLE

        # Section headers: space_before=6pt, space_after=2pt
        is_header = (para_text.upper() == para_text and len(para_text) < 40 and para_text)
        if para_text and is_header:
            pf.space_before = Pt(6)
            pf.space_after = Pt(2)
        elif para_text:
            # All other content: space_before=0, space_after=2pt
            pf.space_before = Pt(0)
            pf.space_after = Pt(2)

    # ── Apply rewrites — strip markdown, apply bolding rules ──
    for p_idx, new_text in rewrites.items():
        if p_idx not in para_map:
            continue
        clean_text = re.sub(r'[*_]{1,2}', '', new_text)
        clean_text = re.sub(r'`', '', clean_text)
        para = para_map[p_idx]

        p_section = _get_section_for_para(para_map, p_idx, section_headers)

        # Skills/Additional/Languages lines: bold label before colon, normal weight after
        in_boldable_section = p_section in ("additional", "skills", "technical skills", "languages")
        if ":" in clean_text and (in_boldable_section or _is_skills_or_additional_line(clean_text)):
            parts = clean_text.split(":", 1)
            for r in para.runs:
                r.text = ""
            para.text = ""
            run_bold = para.add_run(parts[0] + ":")
            run_bold.font.name = "Calibri"
            run_bold.font.size = Pt(10)
            run_bold.bold = True
            run_normal = para.add_run(parts[1])
            run_normal.font.name = "Calibri"
            run_normal.font.size = Pt(10)
            run_normal.bold = False
            continue

        runs = para.runs
        if not runs:
            para.text = ""
            run = para.add_run(clean_text)
            run.font.name = "Calibri"
            run.font.size = Pt(10)
        elif len(runs) == 1:
            runs[0].text = clean_text
            runs[0].font.name = "Calibri"
            runs[0].font.size = Pt(10)
        else:
            runs[0].text = clean_text
            runs[0].font.name = "Calibri"
            runs[0].font.size = Pt(10)
            for r in runs[1:]:
                r.text = ""

    # Remove ghost paragraphs at the end of the document
    while doc.paragraphs and not doc.paragraphs[-1].text.strip():
        p_element = doc.paragraphs[-1]._p
        p_element.getparent().remove(p_element)
        if not doc.paragraphs:
            break

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


def parse_txt_resume(text: str) -> DocumentStructure:
    """Parse a plain-text resume into a DocumentStructure.

    Each non-empty line becomes a paragraph. Output will be a new .docx
    via build_docx_from_template.
    """
    structure = DocumentStructure(source_bytes=text.encode("utf-8"))
    idx = 0
    for line in text.split("\n"):
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

    # Force 0.5" margins (matching Default_Resume.docx)
    section = doc.sections[0]
    section.top_margin = Inches(0.5)
    section.bottom_margin = Inches(0.5)
    section.left_margin = Inches(0.5)
    section.right_margin = Inches(0.5)

    for p in structure.paragraphs:
        text = _strip_markdown(rewrites.get(p.index, p.full_text))
        para = doc.add_paragraph()
        para.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
        para.paragraph_format.space_before = Pt(0)
        para.paragraph_format.space_after = Pt(2)
        run = para.add_run(text)
        run.font.name = "Calibri"
        run.font.size = Pt(10)

    output = io.BytesIO()
    doc.save(output)
    return output.getvalue()


def docx_to_pdf(docx_bytes: bytes) -> bytes | None:
    """Convert a .docx to PDF. Tries docx2pdf (Word) first, falls back to mammoth+xhtml2pdf.

    Returns PDF bytes on success, or None if conversion fails.
    """
    # Try docx2pdf (requires Microsoft Word — works locally on Windows/Mac)
    try:
        from docx2pdf import convert as docx2pdf_convert

        with tempfile.TemporaryDirectory() as tmp_dir:
            docx_path = os.path.join(tmp_dir, "resume.docx")
            pdf_path = os.path.join(tmp_dir, "resume.pdf")

            with open(docx_path, "wb") as f:
                f.write(docx_bytes)

            docx2pdf_convert(docx_path, pdf_path)

            with open(pdf_path, "rb") as f:
                return f.read()
    except Exception:
        pass

    # Fallback: mammoth (docx→HTML) + fpdf2 (text→PDF) — pure Python, works everywhere
    try:
        import mammoth
        from fpdf import FPDF
        import html as html_module

        html_result = mammoth.convert_to_html(io.BytesIO(docx_bytes))
        # Strip HTML tags to get plain text, preserving line breaks
        import re
        text = html_result.value
        text = re.sub(r'<br\s*/?>', '\n', text)
        text = re.sub(r'</p>', '\n', text)
        text = re.sub(r'</li>', '\n', text)
        text = re.sub(r'<[^>]+>', '', text)
        text = html_module.unescape(text)

        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=20)
        pdf.add_page()
        pdf.set_font("Helvetica", size=11)

        for line in text.split('\n'):
            line = line.strip()
            if line:
                pdf.multi_cell(0, 6, line)
            else:
                pdf.ln(3)

        return pdf.output()
    except Exception:
        pass

    return None


def load_bundled_references(references_dir: str) -> str:
    """Load all pre-packaged reference files from a directory.

    Reads .pdf and .docx files from the given directory and returns
    their combined text content.
    """
    if not os.path.isdir(references_dir):
        return ""

    ref_texts = []
    for filename in sorted(os.listdir(references_dir)):
        filepath = os.path.join(references_dir, filename)
        if not os.path.isfile(filepath):
            continue

        try:
            with open(filepath, "rb") as f:
                file_bytes = f.read()

            if filename.lower().endswith(".pdf"):
                text = parse_pdf(file_bytes)
                if text:
                    ref_texts.append(f"## {filename}\n{text}")
            elif filename.lower().endswith(".docx"):
                structure = parse_docx(file_bytes)
                text = extract_plain_text(structure)
                if text:
                    ref_texts.append(f"## {filename}\n{text}")
        except Exception:
            continue

    return "\n\n".join(ref_texts)


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


def fetch_jd_from_url(url: str) -> str | None:
    """Fetch job description text from a URL. Returns plain text or None on failure."""
    # Restrict to http/https only to prevent SSRF via file://, ftp://, localhost, etc.
    if not url or not url.lower().startswith(("https://", "http://")):
        return None
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ResumeAnalyzer/1.0"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        # Strip HTML tags, keep text
        text = re.sub(r'<script[^>]*>.*?</script>', '', raw, flags=re.DOTALL)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
        text = re.sub(r'<br\s*/?>', '\n', text)
        text = re.sub(r'</p>', '\n\n', text)
        text = re.sub(r'</div>', '\n', text)
        text = re.sub(r'</li>', '\n', text)
        text = re.sub(r'<[^>]+>', '', text)
        text = html_module.unescape(text)
        # Collapse excessive whitespace
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r' {2,}', ' ', text)
        return text.strip()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Default .docx template — mirrors Default_Resume.docx formatting exactly
# ---------------------------------------------------------------------------

def build_docx_from_template(rewrites: dict[int, str], structure: "DocumentStructure") -> bytes:
    """Build a formatted .docx matching Default_Resume.docx style.

    Formatting spec (extracted from Default_Resume.docx):
    - Page: 8.5" x 11", 0.50" margins all sides
    - Name: Calibri 14pt, bold, black, centered
    - Contact: Calibri 9.5pt, black, centered, space_before=2pt
    - Section headers: Calibri 10pt, bold, black, ALL CAPS, bottom border,
      space_before=9pt (114300 EMU), space_after=3pt (38100 EMU)
    - Company: Calibri 10pt, bold, black, tab-aligned location,
      space_before=5pt (63500 EMU)
    - Title: Calibri 10pt, italic, tab-aligned dates,
      space_before=0.5pt (6350 EMU), space_after=1pt (12700 EMU)
    - Bullets: Calibri 10pt, normal, List Paragraph style,
      space_before=1pt (12700 EMU), space_after=1pt (12700 EMU)
    - Additional/Skills: colon-bolded labels
    - Section order: EXPERIENCE → EDUCATION → ADDITIONAL
    """
    doc = Document()

    # Page setup: 8.5" x 11", 0.50" margins (matching Default_Resume.docx)
    section = doc.sections[0]
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)
    section.top_margin = Inches(0.5)
    section.bottom_margin = Inches(0.5)
    section.left_margin = Inches(0.5)
    section.right_margin = Inches(0.5)

    # Helper to classify paragraph roles from the original structure
    def _classify_paragraph(p_info):
        """Heuristic classification of paragraph role for template formatting."""
        text = p_info.full_text.strip()
        style = p_info.style_name.lower() if p_info.style_name else ""
        idx = p_info.index

        if not text:
            return "empty"

        # First paragraph is usually the name
        if idx == 0:
            return "name"

        # Contact line (contains email, phone, linkedin, etc.)
        if any(sig in text.lower() for sig in ["@", "linkedin", "github", "|"]) and idx <= 2:
            return "contact"

        # Section headers: all caps, short, common header names
        section_names = [
            "EXPERIENCE", "EDUCATION", "SKILLS", "ADDITIONAL", "PROJECTS",
            "WORK EXPERIENCE", "PROFESSIONAL EXPERIENCE", "TECHNICAL SKILLS",
            "TECHNOLOGIES", "CERTIFICATIONS", "PUBLICATIONS", "LEADERSHIP",
            "ACTIVITIES", "INTERESTS", "SUMMARY", "OBJECTIVE", "AWARDS",
            "LANGUAGES", "LEADERSHIP & ACTIVITIES",
        ]
        if text == text.upper() and len(text) < 40:
            return "section_header"
        for name in section_names:
            if text.upper().strip() == name:
                return "section_header"

        # Company lines: often all caps or bold, contain date ranges
        if re.search(r'\b(19|20)\d{2}\b', text) and any(c.isupper() for c in text[:10]):
            # Could be company or title line
            if "heading" in style or (p_info.runs and p_info.runs[0].bold):
                return "company"
            if p_info.runs and p_info.runs[0].italic:
                return "title"
            # Heuristic: if mostly uppercase first word, likely company
            first_word = text.split()[0] if text.split() else ""
            if first_word == first_word.upper() and len(first_word) > 1:
                return "company"
            return "title"

        # Bullets: start with bullet char or are indented
        if text.startswith(("•", "-", "–", "▪", "■")):
            return "bullet"
        # Runs with bullet-like content
        if "list" in style:
            return "bullet"

        return "body"

    # Build classified list — strip markdown from all rewritten text
    classified = []
    for p_info in structure.paragraphs:
        text = rewrites.get(p_info.index, p_info.full_text)
        text = _strip_markdown(text)
        role = _classify_paragraph(p_info)
        classified.append((role, text, p_info))

    # Right tab position: page width (8.5") minus 2×0.5" margins = 7.5"
    right_tab_pos = Inches(7.5)
    current_section = ""

    for role, text, p_info in classified:
        if role == "empty":
            continue

        # Track current section for bolding context
        if role == "section_header":
            current_section = text.strip().lower()

        para = doc.add_paragraph()
        # Single line spacing throughout
        para.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE

        if role == "name":
            run = para.add_run(text.upper())
            run.font.name = "Calibri"
            run.font.size = Pt(14)
            run.font.color.rgb = RGBColor(0, 0, 0)
            run.bold = True
            para.alignment = WD_ALIGN_PARAGRAPH.CENTER

        elif role == "contact":
            run = para.add_run(text)
            run.font.name = "Calibri"
            run.font.size = Pt(9.5)
            run.font.color.rgb = RGBColor(0, 0, 0)
            para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            para.paragraph_format.space_before = Emu(25400)  # 2pt

        elif role == "section_header":
            run = para.add_run(text.upper())
            run.font.name = "Calibri"
            run.font.size = Pt(10)
            run.font.color.rgb = RGBColor(0, 0, 0)
            run.bold = True
            pf = para.paragraph_format
            pf.space_before = Emu(114300)   # 9pt
            pf.space_after = Emu(38100)     # 3pt
            # Bottom border (grey line)
            pPr = para._p.get_or_add_pPr()
            pBdr = pPr.makeelement(qn('w:pBdr'), {})
            bottom = pBdr.makeelement(qn('w:bottom'), {
                qn('w:val'): 'single',
                qn('w:sz'): '4',
                qn('w:space'): '1',
                qn('w:color'): '999999',
            })
            pBdr.append(bottom)
            pPr.append(pBdr)

        elif role == "company":
            # Split on tab or multi-space to separate company name from location
            parts = re.split(r'\t|  {2,}', text, maxsplit=1)
            run = para.add_run(parts[0].upper())
            run.font.name = "Calibri"
            run.font.size = Pt(10)
            run.font.color.rgb = RGBColor(0, 0, 0)
            run.bold = True
            if len(parts) > 1:
                pf = para.paragraph_format
                pf.tab_stops.add_tab_stop(right_tab_pos, alignment=WD_ALIGN_PARAGRAPH.RIGHT)
                loc_run = para.add_run("\t" + parts[1])
                loc_run.font.name = "Calibri"
                loc_run.font.size = Pt(10)
                loc_run.font.color.rgb = RGBColor(0, 0, 0)
            pf = para.paragraph_format
            pf.space_before = Emu(63500)    # 5pt

        elif role == "title":
            parts = re.split(r'\t|  {2,}', text, maxsplit=1)
            run = para.add_run(parts[0])
            run.font.name = "Calibri"
            run.font.size = Pt(10)
            run.font.color.rgb = RGBColor(0, 0, 0)
            run.italic = True
            if len(parts) > 1:
                pf = para.paragraph_format
                pf.tab_stops.add_tab_stop(right_tab_pos, alignment=WD_ALIGN_PARAGRAPH.RIGHT)
                date_run = para.add_run("\t" + parts[1])
                date_run.font.name = "Calibri"
                date_run.font.size = Pt(10)
                date_run.font.color.rgb = RGBColor(0, 0, 0)
                date_run.italic = True
            pf = para.paragraph_format
            pf.space_before = Emu(6350)     # 0.5pt
            pf.space_after = Emu(12700)     # 1pt

        elif role == "bullet":
            # Remove leading bullet character and strip any markdown artifacts
            clean = re.sub(r'^[•\-–▪■]\s*', '', text)
            clean = re.sub(r'[*_]{1,2}', '', clean)
            clean = re.sub(r'`', '', clean)
            # Apply colon-bolding if in Additional/Skills/Languages section
            in_boldable = current_section in ("additional", "skills", "technical skills", "languages")
            if ":" in clean and (in_boldable or _is_skills_or_additional_line(clean)):
                _add_colon_bolded_runs(para, clean, font_name="Calibri", font_size_pt=10)
            else:
                run = para.add_run(clean)
                run.font.name = "Calibri"
                run.font.size = Pt(10)
                run.font.color.rgb = RGBColor(0, 0, 0)
            pf = para.paragraph_format
            pf.space_before = Emu(12700)    # 1pt
            pf.space_after = Emu(12700)     # 1pt
            # Use List Paragraph style if available for proper indent
            for s in doc.styles:
                if s.name == 'List Paragraph':
                    para.style = s
                    break

        else:  # body text — apply colon-bolding if in Additional/Skills/Languages section
            in_boldable = current_section in ("additional", "skills", "technical skills", "languages")
            if ":" in text and (in_boldable or _is_skills_or_additional_line(text)):
                parts = text.split(":", 1)
                run_bold = para.add_run(parts[0] + ":")
                run_bold.font.name = "Calibri"
                run_bold.font.size = Pt(10)
                run_bold.font.color.rgb = RGBColor(0, 0, 0)
                run_bold.bold = True
                run_normal = para.add_run(parts[1])
                run_normal.font.name = "Calibri"
                run_normal.font.size = Pt(10)
                run_normal.font.color.rgb = RGBColor(0, 0, 0)
                run_normal.bold = False
            else:
                run = para.add_run(text)
                run.font.name = "Calibri"
                run.font.size = Pt(10)
                run.font.color.rgb = RGBColor(0, 0, 0)
            pf = para.paragraph_format
            pf.space_before = Emu(12700)    # 1pt
            pf.space_after = Emu(12700)     # 1pt

    # Remove ghost paragraphs at the end of the document
    while doc.paragraphs and not doc.paragraphs[-1].text.strip():
        p_element = doc.paragraphs[-1]._p
        p_element.getparent().remove(p_element)
        if not doc.paragraphs:
            break

    output = io.BytesIO()
    doc.save(output)
    return output.getvalue()
