"""Minimal arXiv export API client.

We hit ``https://export.arxiv.org/api/query?id_list=…`` and parse the
returned Atom feed. The arxiv Atom schema is stable enough that
hand-rolled XML traversal is simpler than pulling in feedparser.

Tests don't have network access — services accept a custom callable so
fake clients can be plugged in via DI.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any
from xml.etree import ElementTree as ET

import httpx

from app.modules.imports.exceptions import ArxivFetchFailed, ArxivNotFound

ARXIV_BASE = "https://export.arxiv.org/api/query"
ARXIV_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}


async def fetch_arxiv(arxiv_id: str) -> dict[str, Any]:
    """Fetch + parse a single arXiv entry. Returns a flat dict.

    Raises
    ------
    ArxivNotFound: when the API returns no ``<entry>`` element.
    ArxivFetchFailed: on HTTP / parse failure.
    """
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                ARXIV_BASE, params={"id_list": arxiv_id}, timeout=10.0
            )
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise ArxivFetchFailed(str(exc)) from exc

    return parse_arxiv_atom(resp.text, arxiv_id)


def parse_arxiv_atom(xml_text: str, arxiv_id: str) -> dict[str, Any]:
    """Parse an arXiv Atom feed string into a flat metadata dict."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ArxivFetchFailed(f"Could not parse arXiv response: {exc}") from exc

    entry = root.find("atom:entry", ARXIV_NS)
    if entry is None:
        raise ArxivNotFound(arxiv_id)

    # Reject the "empty entry" the export API returns when an id is bogus
    # (it ships an <entry> with only a summary saying "Error").
    title_el = entry.find("atom:title", ARXIV_NS)
    if title_el is None or not (title_el.text or "").strip():
        raise ArxivNotFound(arxiv_id)
    raw_title = (title_el.text or "").strip()
    if raw_title.lower() == "error":
        raise ArxivNotFound(arxiv_id)
    title = " ".join(raw_title.split())

    summary_el = entry.find("atom:summary", ARXIV_NS)
    summary = " ".join((summary_el.text or "").split()) if summary_el is not None else ""

    # Authors.
    authors: list[dict[str, Any]] = []
    for author_el in entry.findall("atom:author", ARXIV_NS):
        name_el = author_el.find("atom:name", ARXIV_NS)
        name = name_el.text.strip() if name_el is not None and name_el.text else ""
        aff_el = author_el.find("arxiv:affiliation", ARXIV_NS)
        aff = aff_el.text.strip() if aff_el is not None and aff_el.text else None
        if name:
            authors.append({"name": name, "affiliation": aff})

    # Categories.
    categories: list[str] = []
    for cat_el in entry.findall("atom:category", ARXIV_NS):
        term = cat_el.attrib.get("term")
        if term:
            categories.append(term)
    primary_el = entry.find("arxiv:primary_category", ARXIV_NS)
    primary = primary_el.attrib.get("term") if primary_el is not None else None
    if primary is None and categories:
        primary = categories[0]

    # Identifier — strip the ``http://arxiv.org/abs/`` prefix.
    id_el = entry.find("atom:id", ARXIV_NS)
    full_id = (id_el.text or "").strip() if id_el is not None else ""
    canonical_id = full_id.rsplit("/", 1)[-1] if full_id else arxiv_id

    # Dates: published + updated.
    published = _parse_atom_date(entry.find("atom:published", ARXIV_NS))
    updated = _parse_atom_date(entry.find("atom:updated", ARXIV_NS))

    # DOI + journal ref live in the arxiv namespace.
    doi_el = entry.find("arxiv:doi", ARXIV_NS)
    doi = doi_el.text.strip() if doi_el is not None and doi_el.text else None
    journal_el = entry.find("arxiv:journal_ref", ARXIV_NS)
    journal_ref = (
        " ".join(journal_el.text.split()) if journal_el is not None and journal_el.text else None
    )

    # PDF link is the ``<link>`` element with title="pdf".
    pdf_url: str | None = None
    source_url: str | None = full_id or None
    for link_el in entry.findall("atom:link", ARXIV_NS):
        if link_el.attrib.get("title") == "pdf":
            pdf_url = link_el.attrib.get("href")
        if link_el.attrib.get("rel") == "alternate":
            source_url = link_el.attrib.get("href", source_url)

    return {
        "id": canonical_id,
        "title": title,
        "authors": authors,
        "summary": summary,
        "categories": categories,
        "primary_category": primary,
        "published": published,
        "updated": updated,
        "doi": doi,
        "journal_ref": journal_ref,
        "pdf_url": pdf_url,
        "source_url": source_url or f"https://arxiv.org/abs/{canonical_id}",
    }


def _parse_atom_date(el: ET.Element | None) -> _dt.datetime | None:
    if el is None or not (el.text or "").strip():
        return None
    text = (el.text or "").strip()
    # Atom dates are RFC 3339, e.g. ``2024-01-23T17:09:32Z``.
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return _dt.datetime.fromisoformat(text)
    except ValueError:
        return None


__all__ = ["ARXIV_BASE", "ARXIV_NS", "fetch_arxiv", "parse_arxiv_atom"]
