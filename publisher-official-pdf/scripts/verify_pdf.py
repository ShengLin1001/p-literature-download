#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Unified PDF acceptance check for the publisher-official-pdf pipeline.

A DOI counts as passed only when this verifier accepts the downloaded file:
header/trailer/size, nonzero page count, first-page text is not a
supplementary-materials document, and the extracted DOI or normalized title
matches the requested DOI's Crossref metadata.

Usage:
    python verify_pdf.py <file.pdf> [--doi 10.xxxx/yyyy] [--json]
    python verify_pdf.py <dir> --batch [--json]     # verify every *.pdf
    python verify_pdf.py --selftest
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

SUPPLEMENTARY_MARKERS = (
    "supplementary materials",
    "supplementary information",
    "supporting information",
    "supplementary data",
    "supplemental material",
)


def looks_like_supplementary(text: str) -> bool:
    # A supplementary-only PDF declares itself in its own title/first line,
    # e.g. "Supplementary Materials for ...". Ordinary articles merely *cite*
    # "(Supplementary Information)" mid-text, so a bare substring match
    # false-positives on them. Only match at the start of the extracted text
    # or when the marker directly precedes " for" (the "SM for <title>").
    head = (text or "")[:400].lower()
    for marker in SUPPLEMENTARY_MARKERS:
        if head.lstrip().startswith(marker):
            return True
        if marker + " for" in head:
            return True
    return False

_DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>()\[\]]+")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_pdf(source, max_pages: int = 3):
    """Return (page_count, first_pages_text) from a path or raw bytes.

    Bytes are accepted so a download can be checked before it ever reaches
    disk; the download orchestrator uses that for its advisory identity check.
    Raises on an unreadable file.
    """
    import io

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(source)
                       if isinstance(source, (bytes, bytearray)) else str(source))
    n = len(reader.pages)
    text_parts = []
    for page in reader.pages[:max_pages]:
        try:
            text_parts.append(page.extract_text() or "")
        except Exception:
            text_parts.append("")
    return n, "\n".join(text_parts)


def normalize_text(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def doi_in_text(text: str, doi: str) -> bool:
    for found in _DOI_RE.findall(text or ""):
        if found.rstrip(".,;)").lower() == doi.lower():
            return True
    return False


def title_in_text(text: str, title: str) -> bool:
    """True when a distinctive 6-word window of the title appears in text."""
    words = normalize_text(title).split()
    if len(words) < 4:
        return False
    hay = normalize_text(text)
    for size in (8, 6, 4):
        if len(words) >= size:
            window = " ".join(words[:size])
            if window in hay:
                return True
    return False


def verify_pdf(path_pdf, doi=None, fetch_metadata=True):
    """Verify one PDF. Returns a result dict; result["passed"] is the verdict."""
    path_pdf = Path(path_pdf)
    result = {
        "file": str(path_pdf),
        "doi": doi,
        "passed": False,
        "checks": {},
        "status": "failed",
        "reason": "",
    }
    checks = result["checks"]

    def stop(reason, status="failed"):
        result["reason"] = reason
        result["status"] = status
        return result

    if not path_pdf.is_file():
        return stop("file missing")

    from mymetal.academic.search.literature_download import is_complete_pdf

    checks["complete_pdf"] = bool(is_complete_pdf(path_pdf))
    if not checks["complete_pdf"]:
        return stop("incomplete pdf (header/EOF/size)")

    checks["sha256"] = sha256_of(path_pdf)
    checks["size"] = path_pdf.stat().st_size

    try:
        pages, text = read_pdf(path_pdf)
    except Exception as exc:  # unreadable/encrypted
        return stop("pdf unreadable: %s" % exc)
    checks["pages"] = pages
    if pages <= 0:
        return stop("zero pages")

    low = text.lower()
    checks["not_supplementary"] = not looks_like_supplementary(text)
    if not checks["not_supplementary"]:
        return stop("first page looks like supplementary material", status="rejected_supplementary")

    if doi:
        meta = None
        if fetch_metadata:
            from mymetal.academic.search.literature_download import fetch_doi_metadata
            try:
                meta = fetch_doi_metadata(doi)
            except Exception:
                meta = None
        checks["doi_in_pdf"] = doi_in_text(text, doi)
        title_ok = False
        if meta:
            title = (meta.get("title") or [""])[0]
            title_ok = title_in_text(text, title)
        checks["title_matches"] = title_ok
        if not (checks["doi_in_pdf"] or title_ok):
            return stop("neither DOI nor title found in first pages", status="rejected_mismatch")

    result["passed"] = True
    result["status"] = "downloaded"
    result["reason"] = "ok"
    return result


def selftest():
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        bad = tmp / "bad.pdf"
        bad.write_bytes(b"not a pdf")
        r = verify_pdf(bad, fetch_metadata=False)
        assert not r["passed"] and "incomplete" in r["reason"]
        small = tmp / "small.pdf"
        small.write_bytes(b"%PDF-1.7" + b"0" * 100 + b"%%EOF")
        r = verify_pdf(small, fetch_metadata=False)
        assert not r["passed"]
    print("✅ verify_pdf selftest ok")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("target", nargs="?", help="PDF file or directory (with --batch)")
    ap.add_argument("--doi", help="expected DOI for identity check")
    ap.add_argument("--batch", action="store_true", help="verify all *.pdf in target dir")
    ap.add_argument("--json", action="store_true", help="print JSON results")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        selftest()
        return
    if not args.target:
        ap.error("target required")

    target = Path(args.target)
    results = []
    if args.batch:
        for pdf in sorted(target.glob("*.pdf")):
            results.append(verify_pdf(pdf, doi=args.doi))
    else:
        results.append(verify_pdf(target, doi=args.doi))

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for r in results:
            mark = "✅" if r["passed"] else "❌"
            print("%s %s  %s" % (mark, Path(r["file"]).name, r["reason"]))
    if not all(r["passed"] for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
