"""Multi-format document parser."""

from pathlib import Path


async def parse_file(file_path: str) -> str:
    """Parse a file and return markdown text. Supports PDF, DOCX, MD, TXT, PPTX, XLSX."""
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix in (".md", ".txt", ".markdown", ".rst"):
        return path.read_text(encoding="utf-8", errors="replace")

    if suffix == ".pdf":
        return await _parse_pdf(path)

    if suffix == ".docx":
        return await _parse_docx(path)

    if suffix == ".pptx":
        return await _parse_pptx(path)

    if suffix in (".xlsx", ".xls", ".ods"):
        return await _parse_excel(path)

    raise ValueError(f"Unsupported file format: {suffix}")


async def _parse_pdf(path: Path) -> str:
    try:
        import pdfplumber
        text_parts = []
        with pdfplumber.open(str(path)) as pdf:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text()
                if text:
                    text_parts.append(f"## Page {i + 1}\n\n{text}")
        return "\n\n".join(text_parts) if text_parts else ""
    except ImportError as e:
        raise ImportError("pdfplumber is required: pip install pdfplumber") from e


async def _parse_docx(path: Path) -> str:
    try:
        from docx import Document
        doc = Document(str(path))
        parts = []
        for para in doc.paragraphs:
            if para.style.name.startswith("Heading"):
                level = int(para.style.name.split()[-1]) if para.style.name.split()[-1].isdigit() else 1
                parts.append(f"{'#' * level} {para.text}")
            else:
                parts.append(para.text)
        return "\n\n".join(parts)
    except ImportError as e:
        raise ImportError("python-docx is required: pip install python-docx") from e


async def _parse_pptx(path: Path) -> str:
    try:
        from pptx import Presentation
        prs = Presentation(str(path))
        parts = []
        for i, slide in enumerate(prs.slides):
            slide_parts = [f"## Slide {i + 1}"]
            for shape in slide.shapes:
                if shape.has_text_frame:
                    for para in shape.text_frame.paragraphs:
                        if para.text.strip():
                            slide_parts.append(para.text)
            parts.append("\n".join(slide_parts))
        return "\n\n".join(parts)
    except ImportError as e:
        raise ImportError("python-pptx is required: pip install python-pptx") from e


async def _parse_excel(path: Path) -> str:
    try:
        import openpyxl
        wb = openpyxl.load_workbook(str(path), data_only=True)
        parts = []
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            parts.append(f"## Sheet: {sheet_name}\n")
            rows = []
            for row in ws.iter_rows(values_only=True):
                rows.append(" | ".join(str(cell) if cell is not None else "" for cell in row))
            if len(rows) > 1:
                parts.append(f"| {' | '.join(str(c or '') for c in rows[0])} |")
                parts.append(f"| {' | '.join('---' for _ in rows[0])} |")
                for row in rows[1:]:
                    parts.append(f"| {row} |")
            parts.append("")
        return "\n".join(parts)
    except ImportError as e:
        raise ImportError("openpyxl is required: pip install openpyxl") from e
