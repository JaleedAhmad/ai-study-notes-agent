"""Side-effect-free extraction contracts, independent of UI and providers."""

import re


class ExtractionError(ValueError):
    """A file or OCR response did not produce usable study text.

    Messages are safe for display; callers must not expose chained parser errors.
    """


_GENERATED_HEADER = re.compile(
    r"^[ \t]*--- (?:Document: [^\r\n]*|Page [0-9]+) ---[ \t]*\r?$",
    re.MULTILINE,
)
_LEGACY_PAGE_HEADER = re.compile(r"(?:\\n)*--- Page [0-9]+ ---(?:\\n)*")
_LEGACY_OCR_FAILURE = (
    "[Error: Vision extraction failed. All OCR endpoints are currently unreachable.]"
)


def validate_extracted_text(text):
    """Return the original text, or raise without including source contents.

    Generated wrappers cannot establish content. The exact retired application
    OCR failure sentinel is reserved; ordinary error words/messages are allowed.
    This checks usability, not semantic accuracy or document/page coverage.
    """
    if not isinstance(text, str) or "\x00" in text:
        raise ExtractionError("The document did not contain usable text.")
    content = _GENERATED_HEADER.sub("", _LEGACY_PAGE_HEADER.sub("", text))
    content = content.replace("\ufeff", "").strip()
    if re.fullmatch(r"(?:\\n)*" + re.escape(_LEGACY_OCR_FAILURE) + r"(?:\\n)*", content):
        raise ExtractionError("Image text extraction failed. Please try again.")
    if not content:
        raise ExtractionError("The document did not contain usable text.")
    return text
