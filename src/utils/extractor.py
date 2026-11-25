import docx
import pptx
from pypdf import PdfReader
from PIL import Image
from pdf2image import convert_from_bytes
from ..core.vision_client import extract_text_from_image
from .extraction_validation import ExtractionError, validate_extracted_text


def _pdf_page_evidence(page):
    """Conservative structural evidence; never infer blankness from OCR silence.

    XObjects (including forms), inline images and annotations may contain material
    absent from native text. Unknown structure is not evidence of a blank page.
    """
    get_contents = getattr(page, "get_contents", None)
    contents = get_contents() if get_contents is not None else None
    getter = getattr(page, "get", None)
    annotations = getter("/Annots") if getter is not None else None
    resources = getter("/Resources", {}) if getter is not None else {}
    if hasattr(resources, "get_object"):
        resources = resources.get_object()
    xobjects = resources.get("/XObject") if resources else None
    operations = getattr(contents, "operations", None)
    visual = bool(annotations or xobjects) or (
        operations is not None and any(
            operator in (b"INLINE IMAGE", b"Do", b"sh") for _, operator in operations
        )
    )
    blank = get_contents is not None and not visual and (
        contents is None or operations == []
    )
    return blank, visual


def _merge_pdf_text(native, ocr):
    """Retain native text verbatim; omit exact repeated OCR lines only.

    No fuzzy matching: differing transcription may contain additional material.
    """
    if not native:
        return ocr
    native_lines = {line.strip() for line in native.splitlines() if line.strip()}
    extra = [line for line in ocr.splitlines() if line.strip() not in native_lines]
    return native + ("\n" + "\n".join(extra) if any(line.strip() for line in extra) else "")


def _extract_pdf(uploaded_file):
    reader = PdfReader(uploaded_file)
    parts = []
    pdf_bytes = None
    for number, page in enumerate(reader.pages, 1):
        images = []
        try:
            native = page.extract_text()
            if native is not None and not isinstance(native, str):
                raise ExtractionError("Invalid PDF text response.")
            native = native or ""
            # Empty native output needs OCR unless structure proves blankness.
            has_native = bool(native.replace("\ufeff", "").strip())
            if has_native:
                validate_extracted_text(native)
            blank, visual = _pdf_page_evidence(page)
            if not has_native and blank:
                continue
            text = native
            if not has_native or visual:
                if pdf_bytes is None:
                    uploaded_file.seek(0)
                    pdf_bytes = uploaded_file.read()
                # One page per call bounds live raster memory and makes missing
                # renders attributable. Poppler timeout does not bound OCR time.
                images = convert_from_bytes(
                    pdf_bytes, first_page=number, last_page=number,
                    size=1600, thread_count=1, timeout=60,
                )
                if len(images) != 1:
                    raise ExtractionError("A required PDF page could not be rendered.")
                ocr = validate_extracted_text(extract_text_from_image(images[0]))
                text = _merge_pdf_text(native if has_native else "", ocr)
            parts.append(f"\n--- Page {number} ---\n{validate_extracted_text(text)}\n")
        except Exception as error:
            raise ExtractionError(
                f"PDF page {number} could not be fully extracted. No complete document was accepted."
            ) from error
        finally:
            for image in images:
                close = getattr(image, "close", None)
                if close is not None:
                    close()
    return validate_extracted_text("".join(parts))


def extract_universal_text(uploaded_file):
    """
    Extracts text from uploaded files universally supporting PDF, DOCX, PPTX, TXT, and MD.
    Expects a Streamlit UploadedFile or file-like object with a `.name` attribute.
    Returns usable text or raises ExtractionError; never returns failure strings.
    """
    try:
        filename = uploaded_file.name.lower()
        
        if hasattr(uploaded_file, "seek"):
            uploaded_file.seek(0)
            
        if filename.endswith(".pdf"):
            return _extract_pdf(uploaded_file)
        elif filename.endswith(".docx"):
            doc = docx.Document(uploaded_file)
            text = ""
            for paragraph in doc.paragraphs:
                text += paragraph.text + "\n"
            return validate_extracted_text(text)
            
        elif filename.endswith(".pptx"):
            prs = pptx.Presentation(uploaded_file)
            text = ""
            for slide in prs.slides:
                for shape in slide.shapes:
                    if hasattr(shape, "has_text_frame") and shape.has_text_frame:
                        text += shape.text + "\n"
            return validate_extracted_text(text)
            
        elif filename.endswith(".txt") or filename.endswith(".md"):
            content = uploaded_file.read()
            if isinstance(content, bytes):
                content = content.decode("utf-8")
            return validate_extracted_text(content)
            
        elif filename.endswith((".png", ".jpg", ".jpeg")):
            img = Image.open(uploaded_file)
            if img.mode != "RGB":
                img = img.convert("RGB")
            text = extract_text_from_image(img)
            return validate_extracted_text(text)
            
        else:
            raise ExtractionError("Unsupported document type.")
            
    except ExtractionError:
        raise
    except Exception as e:
        raise ExtractionError("Unable to extract usable text from this file.") from e
