"""Reusable DOI metadata, journal abbreviation, and PDF filename helpers.

Stdlib only, so the skill needs no package installed to run. Covered by
``python scripts/edge_download.py -selftest``.

Functions:
    normalize_doi: Strip DOI URL and ``doi:`` prefixes.
    parse_dois: Read a UTF-8 DOI list while preserving order.
    fetch_doi_metadata: Fetch naming metadata from Crossref.
    get_journal_abbreviation: Look a journal name up in the shared index.
    get_nlm_abbreviation: Look an ISSN up in the NLM Catalog.
    get_journal_label: Pick the filename journal token for a record.
    check_journal_metadata: Reject records that cannot be named.
    get_doi_token: Turn a DOI into its filename-safe suffix.
    generate_pdf_filename: Build ``year-journal-title-doi.pdf`` names.
    is_complete_pdf: Check PDF magic bytes and terminal EOF marker.
"""

from __future__ import annotations

import html
import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen


JOURNAL_ABBREVIATIONS = {
    "Acta Materialia": "ACTA-MATER",
    "Advanced Materials": "ADV-MATER",
    "Annual Review of Psychology": "ANNU-REV-PSYCHOL",
    "Applied Physics Letters": "APL",
    "BMC Bioinformatics": "BMC-BIOINFORMATICS",
    "Cell": "CELL",
    "Chemical Society Reviews": "CHEM-SOC-REV",
    "Communications in Mathematical Physics": "COMMUN-MATH-PHYS",
    "Communications of the ACM": "COMMUN-ACM",
    "Computational Materials Science": "COMP-MATER-SCI",
    "Frontiers in Neuroscience": "FRONT-NEUROSCI",
    "IEEE Transactions on Information Theory": "IEEE-TIT",
    "Journal of the American Chemical Society": "JACS",
    "Journal of Physics: Condensed Matter": "JPCM",
    "Nano Letters": "NANO-LETT",
    "Nature": "NATURE",
    "Nucleic Acids Research": "NAR",
    "Physical Review B": "PRB",
    "PLOS ONE": "PLOS-ONE",
    "Proceedings of the National Academy of Sciences": "PNAS",
    "Science": "SCIENCE",
    "Sensors": "SENSORS",
}

NON_ARTICLE_TITLE_PREFIXES = ("snapshot:",)

# Dropped when abbreviating a *full* journal name that no service abbreviates.
JOURNAL_NAME_STOPWORDS = {"a", "an", "and", "for", "in", "of", "on", "the"}

NLM_EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"


def normalize_doi(raw: str) -> str:
    """Return a DOI without URL or ``doi:`` prefixes."""
    value = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", raw.strip(), flags=re.I)
    return re.sub(r"^doi:\s*", "", value, flags=re.I).strip()


def parse_dois(path_file: Path) -> list[str]:
    """Read and de-duplicate the first field of each DOI-list line.

    Args:
        path_file: UTF-8 or UTF-8-with-BOM DOI list.

    Returns:
        DOI values in their first-seen order.
    """
    ldoi = []
    seen = set()
    for line in path_file.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        doi = normalize_doi(line.split()[0])
        if doi and doi not in seen:
            seen.add(doi)
            ldoi.append(doi)
    return ldoi


def fetch_doi_metadata(
        doi: str,
        timeout: int = 20,
        user_agent: str = "p-literature-download/1.0") -> dict[str, Any] | None:
    """Fetch metadata used only for validation and naming.

    Crossref first, because only it carries ``short-container-title``. DOIs it
    does not own (arXiv and other DataCite registrants) fall back to doi.org
    content negotiation, which answers for every registration agency in the
    same Crossref-compatible CSL shape.

    Args:
        doi: DOI value.
        timeout: HTTP timeout in seconds.
        user_agent: User-Agent sent to the metadata services.

    Returns:
        A metadata mapping, or ``None`` when no service answers.
    """
    doi = normalize_doi(doi)
    lsources = [
        ("https://api.crossref.org/works/" + quote(doi, safe=""),
         "application/json"),
        ("https://doi.org/" + quote(doi, safe="/"),
         "application/vnd.citationstyles.csl+json"),
    ]
    for url, accept in lsources:
        request = Request(
            url, headers={"Accept": accept, "User-Agent": user_agent})
        # Retried: a transient Crossref failure would otherwise silently fall
        # through to CSL, which has no short-container-title, and the same DOI
        # would then be named differently from run to run.
        for attempt in range(2):
            try:
                with urlopen(request, timeout=timeout) as response:
                    data = json.load(response)
            except (OSError, ValueError, json.JSONDecodeError):
                time.sleep(2 * attempt)
                continue
            dict_metadata = data.get("message", data) if isinstance(data, dict) else None
            if dict_metadata:
                return dict_metadata
    return None


def _get_first(value: Any) -> str:
    if isinstance(value, list):
        value = value[0] if value else ""
    return html.unescape(str(value or "")).strip()


def _normalize_journal_name(name: str) -> str:
    return "".join(char.lower() for char in name if char.isalnum())


def get_journal_abbreviation(
        journal: str,
        dict_journal_abbreviations: dict[str, str] | None = None) -> str | None:
    """Resolve a full or already abbreviated journal name.

    Args:
        journal: Journal name from publication metadata.
        dict_journal_abbreviations: Optional replacement/extension index.

    Returns:
        Uppercase filename-safe abbreviation, or ``None`` if unsupported.
    """
    dict_abbreviations = dict(JOURNAL_ABBREVIATIONS)
    if dict_journal_abbreviations:
        dict_abbreviations.update(dict_journal_abbreviations)
    normalized = _normalize_journal_name(journal)
    for name, abbreviation in dict_abbreviations.items():
        if normalized in {
                _normalize_journal_name(name),
                _normalize_journal_name(abbreviation)}:
            return re.sub(r"[^A-Za-z0-9]+", "-", abbreviation).strip("-").upper()
    return None


def _abbreviate_journal_name(name: str, stopwords=JOURNAL_NAME_STOPWORDS) -> str:
    """Turn any journal, short-journal or publisher name into a name token."""
    name = re.sub(r"\s*\([^)]*\)", "", name)     # "Metals (Basel)" -> "Metals"
    ltokens = [
        token for token in re.findall(r"[A-Za-z0-9]+|[㐀-鿿]+", name)
        if token.lower() not in stopwords]
    return "-".join(ltokens).upper()[:40].strip("-")


def _get_nlm_json(url: str, timeout: int) -> dict[str, Any]:
    """GET one E-utilities URL, retrying the resets NCBI hands out under load."""
    for attempt in range(4):
        try:
            with urlopen(Request(url, headers={"User-Agent": "p-literature-download/1.0"}),
                         timeout=timeout) as response:
                return json.load(response)
        except (OSError, ValueError) as exc:
            if attempt == 3:
                # One exception type for callers: "the lookup did not answer".
                raise OSError("NLM lookup failed: " + str(exc)) from exc
            time.sleep(2 + 2 * attempt)
    return {}


def get_nlm_abbreviation(issn: str, timeout: int = 20) -> str:
    """Return the NLM Catalog title abbreviation for an ISSN, or "".

    ``MedlineTA`` is the ISO 4 abbreviation without periods (``Int J Plast``,
    ``Phys Rev Lett``). The catalog covers far more than biomedicine: every
    journal of the first 217-DOI materials batch was found. Unlike Crossref's
    ``short-container-title``, which Elsevier fills with the full title and
    some publishers leave empty, it is uniform.

    Args:
        issn: Print or electronic ISSN.
        timeout: HTTP timeout in seconds.

    Returns:
        The abbreviation, or "" when the catalog has no such ISSN.

    Raises:
        OSError: The service could not be reached; the caller must not guess.
    """
    search = _get_nlm_json(
        NLM_EUTILS + "esearch.fcgi?db=nlmcatalog&retmode=json&tool=p-literature-download"
        + "&term=" + quote(issn + "[issn]"), timeout)
    lid = search.get("esearchresult", {}).get("idlist", [])
    if not lid:
        return ""
    time.sleep(0.4)     # NCBI allows 3 requests/s without an API key
    summary = _get_nlm_json(
        NLM_EUTILS + "esummary.fcgi?db=nlmcatalog&retmode=json&tool=p-literature-download"
        + "&id=" + ",".join(lid[:5]), timeout).get("result", {})
    for uid in summary.get("uids", []):
        abbreviation = (summary.get(uid) or {}).get("medlineta", "")
        if abbreviation:
            return abbreviation
    return ""


def _read_journal_cache(path_cache: Path | None) -> dict[str, str]:
    if not path_cache or not Path(path_cache).is_file():
        return {}
    try:
        return json.loads(Path(path_cache).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}


def _write_journal_cache(path_cache: Path | None, dict_cache: dict[str, str]) -> None:
    if not path_cache:
        return
    path_cache = Path(path_cache)
    path_cache.parent.mkdir(parents=True, exist_ok=True)
    path_cache.write_text(
        json.dumps(dict_cache, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8")


def get_journal_label(
        dict_metadata: dict[str, Any],
        dict_journal_abbreviations: dict[str, str] | None = None,
        path_cache: Path | None = None) -> str:
    """Return the journal token used in the filename.

    Order: the curated index (established names such as ``PRB``, ``JACS``),
    then the local cache, then the NLM Catalog by ISSN, then Crossref's
    ``short-container-title``, the full journal name and the publisher (which
    is what names arXiv).

    The cache is what keeps names stable. Filenames are the "already
    downloaded" key, so one journal must always get one label; whatever label
    a journal gets the first time is written to ``path_cache`` and reused.
    For the same reason a network failure at NLM raises instead of falling
    through: the fallback would name the journal differently from the next
    run that does reach NLM.

    Args:
        dict_metadata: Crossref-style publication metadata.
        dict_journal_abbreviations: Optional replacement/extension index.
        path_cache: JSON file mapping ISSN / journal name to label; ``None``
            skips both the cache and the online lookup (offline naming).

    Returns:
        Uppercase filename-safe journal token.

    Raises:
        OSError: NLM could not be reached for an uncached journal.
    """
    journal = _get_first(dict_metadata.get("container-title"))
    abbreviation = get_journal_abbreviation(journal, dict_journal_abbreviations)
    if abbreviation:
        return abbreviation

    lissn = [issn for issn in (dict_metadata.get("ISSN") or []) if issn]
    lkey = lissn or (["name:" + _normalize_journal_name(journal)] if journal else [])
    dict_cache = _read_journal_cache(path_cache)
    for key in lkey:
        if dict_cache.get(key):
            return dict_cache[key]

    label = ""
    if path_cache:
        for issn in lissn:
            label = _abbreviate_journal_name(get_nlm_abbreviation(issn), stopwords=())
            if label:
                break
    # ponytail: a journal NLM does not know is named from Crossref, whose
    # short-container-title can differ between records; the cache pins
    # whichever spelling came first. Add a JOURNAL_ABBREVIATIONS entry to
    # override it.
    for key in ("short-container-title", "container-title", "publisher"):
        if label:
            break
        label = _abbreviate_journal_name(_get_first(dict_metadata.get(key)))
    label = label or "UNKNOWN"

    if path_cache and lkey:
        dict_cache.update({key: label for key in lkey})
        _write_journal_cache(path_cache, dict_cache)
    return label


def get_publication_year(dict_metadata: dict[str, Any]) -> str:
    """Extract the best available four-digit publication year."""
    for key in ("published-print", "published-online", "issued", "created"):
        value = dict_metadata.get(key, {})
        if not isinstance(value, dict):
            continue
        lparts = value.get("date-parts", [[]])
        if lparts and lparts[0]:
            year = str(lparts[0][0])
            if re.fullmatch(r"\d{4}", year):
                return year
    year = str(dict_metadata.get("year", ""))
    return year if re.fullmatch(r"\d{4}", year) else ""


def check_journal_metadata(
        dict_metadata: dict[str, Any] | None,
        dict_journal_abbreviations: dict[str, str] | None = None) -> str | None:
    """Return why a record cannot be named, or ``None`` when it can.

    Deliberately permissive: preprints and journals outside the curated index
    are named from their own metadata, not refused. Only records this pipeline
    must never save (supplementary components, SnapShots) and records with no
    usable naming fields are rejected.
    """
    if not dict_metadata:
        return "metadata unavailable"
    if dict_metadata.get("type") == "component":
        return "supplementary component"
    title = _get_first(dict_metadata.get("title"))
    if any(title.lower().startswith(prefix) for prefix in NON_ARTICLE_TITLE_PREFIXES):
        return "excluded article type"
    if not get_publication_year(dict_metadata):
        return "publication year missing"
    if not title:
        return "title missing"
    return None


def _get_title_prefix(title: str, character_count: int) -> str:
    title = re.sub(r"<[^>]+>", " ", html.unescape(title))
    lparts = []
    remaining = character_count
    for token in re.findall(r"[A-Za-z0-9]+|[\u3400-\u9fff]+", title):
        lparts.append(token[:remaining])
        remaining -= len(lparts[-1])
        if remaining <= 0:
            break
    return "-".join(lparts)


def get_doi_token(doi: str) -> str:
    """Return the filename-safe DOI suffix (``10.1021/jacs.4c17739`` -> ``jacs.4c17739``).

    The registrant prefix is dropped to keep names short; the whole suffix is
    kept, not just its last segment, because ``10.31083/j.jin2206152/pdf``
    would otherwise shrink to ``pdf``. Lowercased, since DOIs are
    case-insensitive and one DOI must always map to one name.
    """
    suffix = normalize_doi(doi).split("/", 1)[-1].lower()
    return re.sub(r'[\\/:*?"<>|\s]+', "_", suffix).strip("._")


def generate_pdf_filename(
        dict_metadata: dict[str, Any],
        title_character_count: int = 10,
        dict_journal_abbreviations: dict[str, str] | None = None,
        doi: str = "",
        path_cache: Path | None = None) -> str:
    """Build ``year-journal-first-ten-title-characters-doi.pdf``.

    The DOI suffix is part of every name. The title prefix alone is not
    unique (``Machine Learning ...`` and ``Machine-Learning-...`` both give
    ``Machine-lea``), and telling two such files apart by reading the PDF
    fails on old scans that print no DOI and OCR badly. With the DOI in the
    name, "is this DOI already downloaded" is a plain path check.

    Args:
        dict_metadata: Crossref-style publication metadata.
        title_character_count: Maximum letters, digits, or Chinese characters.
        dict_journal_abbreviations: Optional replacement/extension index.
        doi: Requested DOI; defaults to the metadata's own ``DOI``.
        path_cache: Journal label cache; see ``get_journal_label``.

    Returns:
        Filename ending in ``.pdf``.

    Raises:
        ValueError: Metadata is unsupported or incomplete.
    """
    reason = check_journal_metadata(dict_metadata, dict_journal_abbreviations)
    if reason:
        raise ValueError(reason)
    title = _get_first(dict_metadata.get("title"))
    title_prefix = _get_title_prefix(title, title_character_count)
    if not title_prefix:
        raise ValueError("title has no filename-safe tokens")
    doi_token = get_doi_token(doi or _get_first(dict_metadata.get("DOI")))
    if not doi_token:
        raise ValueError("DOI missing")
    label = get_journal_label(dict_metadata, dict_journal_abbreviations, path_cache)
    year = get_publication_year(dict_metadata)
    return "-".join([year, label, title_prefix, doi_token]) + ".pdf"


def is_complete_pdf(path_pdf: Path, minimum_size: int = 5000) -> bool:
    """Return whether a PDF has a header, terminal EOF marker, and useful size."""
    try:
        size = path_pdf.stat().st_size
        if size < minimum_size:
            return False
        with path_pdf.open("rb") as file_pdf:
            if file_pdf.read(5) != b"%PDF-":
                return False
            file_pdf.seek(max(0, size - 2048))
            return b"%%EOF" in file_pdf.read()
    except OSError:
        return False
