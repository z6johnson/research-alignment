import io

import pdfplumber


MAX_TEXT_LENGTH = 60000


def extract_text(file_storage):
    """Extract plain text from an uploaded file (PDF or TXT).

    Args:
        file_storage: Flask FileStorage object from request.files.

    Returns:
        Extracted text as a string.

    Raises:
        ValueError: If file type is unsupported or document is empty/unreadable.
    """
    filename = file_storage.filename or ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext == "pdf":
        text = _extract_pdf(file_storage)
    elif ext == "txt":
        text = _extract_txt(file_storage)
    else:
        raise ValueError(f"Unsupported file type: .{ext}. Please upload a PDF or TXT file.")

    text = text.strip()
    if not text:
        raise ValueError(
            "No readable text found in the document. "
            "If this is a scanned PDF, please use an OCR tool first."
        )

    if len(text) > MAX_TEXT_LENGTH:
        text = text[:MAX_TEXT_LENGTH]

    return text


def _extract_pdf(file_storage):
    """Extract text from a PDF file."""
    raw = file_storage.read()
    pages_text = []
    try:
        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    pages_text.append(page_text)
    except Exception as exc:
        raise ValueError(
            "Could not read the PDF file. It may be corrupted or password-protected."
        ) from exc

    return "\n\n".join(pages_text)


def _extract_txt(file_storage):
    """Extract text from a plain text file."""
    raw = file_storage.read()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")
