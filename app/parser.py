"""CT-200-focused PDF parser. Heuristics are explicit and unknown structure is not silently guessed."""
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
import fitz

NUMBERED = re.compile(r"^\s*(\d+(?:\.\d+){0,5})[.)]?\s+(.+?)\s*$")
BULLET = re.compile(r"^\s*(?:[•●▪◦‣*-]|\d+[.)])\s+(.+)$")

@dataclass
class ParsedNode:
    heading: str
    level: int
    body_text: str = ""
    parent_index: int | None = None
    order_index: int = 0
    node_type: str = "section"
    logical_key: str = ""
    content_hash: str = ""
    children: list[int] = field(default_factory=list)

def sha256_text(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

def _is_heading(line: str):
    """Return (heading, level) for clear numbered or short all-caps headings."""
    clean = re.sub(r"\s+", " ", line).strip()
    if not clean or len(clean) > 120:
        return None
    match = NUMBERED.match(clean)
    if match:
        number, title = match.groups()
        title = title.strip()
        if title.startswith("|"):
            return None
        # In this manual, numbered clinical classification entries use a colon
        # (for example, "1. Normal: systolic < 120 ..."). These are list items,
        # not document headings. Keep them in the parent section body.
        if re.match(r"^\d+[.)]\s+", clean) and number.isdigit() and ":" in title:
            return None
        # A single-level numbered instruction such as "1. Do not immerse the device."
        # is ambiguous with a numbered heading. Conservatively keep sentence-like
        # numbered lines as body/list content instead of inventing a new section.
        if re.match(r"^\d+[.)]\s+", clean) and number.isdigit() and re.search(r"[.!?]$", title):
            return None
        return (f"{number} {title}", number.count(".") + 1)
    letters = [c for c in clean if c.isalpha()]
    if len(clean) <= 70 and len(letters) >= 4 and not re.search(r"[|\d]", clean) and sum(c.isupper() for c in letters) / len(letters) >= 0.85:
        return (clean, 1)
    return None

def extract_pdf_text(path: str | Path) -> str:
    """Extract text from a text-based PDF. Scanned PDFs need OCR and fail clearly."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")
    pages = []
    with fitz.open(path) as doc:
        for page in doc:
            page_text = page.get_text("text", sort=True).strip()
            # OCR fallback for image-only/scanned pages. PyMuPDF delegates to Tesseract;
            # Tesseract must be installed on the machine for this branch to work.
            if len(re.sub(r"\s", "", page_text)) < 15:
                try:
                    ocr_page = page.get_textpage_ocr(language="eng", dpi=300, full=True)
                    ocr_text = page.get_text("text", textpage=ocr_page, sort=True).strip()
                    if len(re.sub(r"\s", "", ocr_text)) > len(re.sub(r"\s", "", page_text)):
                        page_text = ocr_text
                except Exception as exc:
                    if not page_text:
                        raise ValueError("A scanned/image-only page was detected, but OCR failed. Install Tesseract OCR and ensure English language data is available. Original error: " + str(exc)) from exc
            pages.append(page_text)
    text = "\n".join(pages).strip()
    if len(re.sub(r"\s", "", text)) < 30:
        raise ValueError("Very little text could be extracted, even after attempting OCR. Check PDF quality and Tesseract installation.")
    return text

def parse_text(text: str) -> list[ParsedNode]:
    """Reconstruct a best-effort tree from headings and content lines.

    Same-title headings remain distinct nodes. Numbering determines depth where present;
    unnumbered all-caps headings are level 1. Unclear lines remain body text.
    """
    nodes: list[ParsedNode] = []
    stack: list[int] = []
    body_lines: list[str] = []
    last_node: int | None = None

    def flush_body():
        nonlocal body_lines
        if last_node is not None and body_lines:
            addition = "\n".join(body_lines).strip()
            if addition:
                existing = nodes[last_node].body_text
                nodes[last_node].body_text = (existing + "\n" + addition).strip() if existing else addition
        body_lines = []

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            if body_lines and body_lines[-1] != "": body_lines.append("")
            continue
        heading = _is_heading(line)
        if heading:
            flush_body()
            title, level = heading
            # Cap depth to prevent malformed numbering from producing huge gaps.
            level = max(1, min(level, 6))
            while stack and nodes[stack[-1]].level >= level:
                stack.pop()
            parent_index = stack[-1] if stack else None
            node = ParsedNode(heading=title, level=level, parent_index=parent_index,
                              order_index=len(nodes), node_type="section")
            nodes.append(node)
            current = len(nodes) - 1
            if parent_index is not None:
                nodes[parent_index].children.append(current)
            stack.append(current)
            last_node = current
        else:
            # Preserve lists and table-like rows as body text; don't invent a tree level.
            body_lines.append(line)
    flush_body()

    # Documents without detectable headings still retain their content under an explicit root.
    if not nodes:
        nodes = [ParsedNode(heading="Extracted document", level=1, body_text=text.strip(), order_index=0)]

    # Logical keys include ancestry and occurrence number, preserving duplicate headings in separate branches.
    occurrences: dict[str, int] = {}
    for i, node in enumerate(nodes):
        ancestry = []
        p = node.parent_index
        while p is not None:
            ancestry.append(nodes[p].heading)
            p = nodes[p].parent_index
        base = "/".join(list(reversed(ancestry)) + [node.heading])
        # Include occurrence count to keep duplicate headings distinct under the same parent.
        occurrences[base] = occurrences.get(base, 0) + 1
        node.logical_key = f"{base}#{occurrences[base]}"
        node.content_hash = sha256_text(node.heading + "\n" + node.body_text)
    return nodes

def parse_pdf(path: str | Path) -> list[ParsedNode]:
    return parse_text(extract_pdf_text(path))
