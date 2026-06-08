"""Multi-format document parser with image extraction."""

import hashlib
from pathlib import Path


async def parse_file(file_path: str, *, media_dir: str | None = None) -> tuple[str, list[dict]]:
    """Parse a file and return (markdown_text, extracted_images).

    Supports PDF, DOCX, MD, TXT, PPTX, XLSX.

    Args:
        file_path: Path to the source file
        media_dir: Directory to save extracted images. If None, images are not extracted.

    Returns:
        Tuple of (content_text, list of {filename, data, width, height})
    """
    path = Path(file_path)
    suffix = path.suffix.lower()
    images: list[dict] = []

    if suffix in (".md", ".txt", ".markdown", ".rst"):
        return path.read_text(encoding="utf-8", errors="replace"), images

    if suffix == ".pdf":
        content, images = await _parse_pdf(path, media_dir=media_dir)
        return content, images

    if suffix == ".docx":
        content, images = await _parse_docx(path, media_dir=media_dir)
        return content, images

    if suffix == ".pptx":
        content, images = await _parse_pptx(path, media_dir=media_dir)
        return content, images

    if suffix in (".xlsx", ".xls", ".ods"):
        return await _parse_excel(path), images

    raise ValueError(f"Unsupported file format: {suffix}")


def _save_image(data: bytes, media_dir: str | None, prefix: str) -> dict | None:
    """Save image data to media directory and return metadata."""
    if not media_dir or not data:
        return None

    media_path = Path(media_dir)
    media_path.mkdir(parents=True, exist_ok=True)

    # Generate filename from content hash
    ext = "png"
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        ext = "png"
    elif data[:2] == b'\xff\xd8':
        ext = "jpg"
    elif data[:4] == b'GIF8':
        ext = "gif"
    elif data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        ext = "webp"

    hash_name = hashlib.md5(data).hexdigest()[:12]
    filename = f"{prefix}_{hash_name}.{ext}"
    filepath = media_path / filename

    if not filepath.exists():
        filepath.write_bytes(data)

    return {"filename": filename, "size": len(data)}


async def _parse_pdf(path: Path, *, media_dir: str | None = None) -> tuple[str, list[dict]]:
    """Parse PDF and extract images."""
    try:
        import pdfplumber
    except ImportError as e:
        raise ImportError("pdfplumber is required: pip install pdfplumber") from e

    text_parts = []
    images = []
    prefix = path.stem[:20].replace(" ", "_")

    with pdfplumber.open(str(path)) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text()
            if text:
                text_parts.append(f"## Page {i + 1}\n\n{text}")

            # Extract images from page
            if media_dir and page.images:
                for _img_idx, _img in enumerate(page.images):
                    try:
                        # pdfplumber images have bbox, need to extract actual image data
                        # For now, we note the image exists
                        pass
                    except Exception:
                        continue

    # Try PyMuPDF for better image extraction
    if media_dir:
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(str(path))
            for page_idx in range(len(doc)):
                page = doc[page_idx]
                img_list = page.get_images(full=True)
                for _img_idx, img_info in enumerate(img_list):
                    xref = img_info[0]
                    try:
                        base_image = doc.extract_image(xref)
                        if base_image:
                            img_data = base_image["image"]
                            result = _save_image(img_data, media_dir, f"{prefix}_p{page_idx}")
                            if result:
                                # Insert image reference into text
                                img_ref = f"\n\n![{result['filename']}](/api/media/{result['filename']})\n\n"
                                # Add after the page text
                                for j, part in enumerate(text_parts):
                                    if part.startswith(f"## Page {page_idx + 1}"):
                                        text_parts[j] = part + img_ref
                                        break
                                images.append(result)
                    except Exception:
                        continue
            doc.close()
        except ImportError:
            pass  # PyMuPDF not available, skip image extraction

    content = "\n\n".join(text_parts) if text_parts else ""
    return content, images


async def _parse_docx(path: Path, *, media_dir: str | None = None) -> tuple[str, list[dict]]:
    """Parse DOCX and extract images."""
    try:
        from docx import Document
    except ImportError as e:
        raise ImportError("python-docx is required: pip install python-docx") from e

    doc = Document(str(path))
    parts = []
    images = []
    prefix = path.stem[:20].replace(" ", "_")

    # Extract images from document relationships
    if media_dir:
        for rel in doc.part.rels.values():
            if "image" in rel.reltype:
                try:
                    img_data = rel.target_part.blob
                    result = _save_image(img_data, media_dir, prefix)
                    if result:
                        images.append(result)
                except Exception:
                    continue

    for para in doc.paragraphs:
        if para.style.name.startswith("Heading"):
            level = int(para.style.name.split()[-1]) if para.style.name.split()[-1].isdigit() else 1
            parts.append(f"{'#' * level} {para.text}")
        else:
            parts.append(para.text)

    # Add image references at the end
    if images:
        parts.append("\n\n## Images\n")
        for img in images:
            parts.append(f"![{img['filename']}](/api/media/{img['filename']})")

    return "\n\n".join(parts), images


async def _parse_pptx(path: Path, *, media_dir: str | None = None) -> tuple[str, list[dict]]:
    """Parse PPTX and extract images."""
    try:
        from pptx import Presentation
    except ImportError as e:
        raise ImportError("python-pptx is required: pip install python-pptx") from e

    prs = Presentation(str(path))
    parts = []
    images = []
    prefix = path.stem[:20].replace(" ", "_")

    for i, slide in enumerate(prs.slides):
        slide_parts = [f"## Slide {i + 1}"]
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    if para.text.strip():
                        slide_parts.append(para.text)

            # Extract images from shapes
            if media_dir and shape.shape_type == 13:  # MSO_SHAPE_TYPE.PICTURE
                try:
                    image = shape.image
                    img_data = image.blob
                    result = _save_image(img_data, media_dir, f"{prefix}_s{i}")
                    if result:
                        slide_parts.append(f"\n![{result['filename']}](/api/media/{result['filename']})")
                        images.append(result)
                except Exception:
                    continue

        parts.append("\n".join(slide_parts))

    return "\n\n".join(parts), images


async def _parse_excel(path: Path) -> str:
    """Parse Excel file to markdown tables."""
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
