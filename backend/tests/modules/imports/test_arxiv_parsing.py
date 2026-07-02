"""arXiv id parsing + Atom-feed parsing — no DB / network required."""

from __future__ import annotations

import pytest

from app.modules.imports.arxiv_client import parse_arxiv_atom
from app.modules.imports.exceptions import ArxivNotFound, InvalidArxivId
from app.modules.imports.service import ImportService

# ---------------------------------------------------------------------------
# parse_arxiv_id
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "expected_id", "expected_version"),
    [
        ("2401.12345", "2401.12345", None),
        ("2401.12345v2", "2401.12345", "v2"),
        ("https://arxiv.org/abs/2401.12345", "2401.12345", None),
        ("https://arxiv.org/abs/2401.12345v3", "2401.12345", "v3"),
        ("https://arxiv.org/pdf/2401.12345", "2401.12345", None),
        ("https://arxiv.org/pdf/2401.12345v1.pdf", "2401.12345", "v1"),
        ("hep-th/9901001", "hep-th/9901001", None),
        ("https://arxiv.org/abs/math.AG/0703001v2", "math.AG/0703001", "v2"),
    ],
)
def test_parse_arxiv_id(
    source: str, expected_id: str, expected_version: str | None
) -> None:
    parsed_id, version = ImportService.parse_arxiv_id(source)
    assert parsed_id == expected_id
    assert version == expected_version


def test_parse_arxiv_id_rejects_garbage() -> None:
    with pytest.raises(InvalidArxivId):
        ImportService.parse_arxiv_id("totally not arxiv")


# ---------------------------------------------------------------------------
# parse_arxiv_atom
# ---------------------------------------------------------------------------


_SAMPLE_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2401.12345v2</id>
    <title>A great paper on the brain</title>
    <summary>
      We present a novel approach to understanding cortical dynamics
      via deep state-space models.
    </summary>
    <author>
      <name>Ada Lovelace</name>
      <arxiv:affiliation>Cambridge</arxiv:affiliation>
    </author>
    <author>
      <name>Alan Turing</name>
    </author>
    <category term="q-bio.NC" />
    <category term="cs.LG" />
    <arxiv:primary_category term="q-bio.NC" />
    <published>2024-01-23T17:09:32Z</published>
    <updated>2024-02-01T12:00:00Z</updated>
    <arxiv:doi>10.1234/example</arxiv:doi>
    <arxiv:journal_ref>Nature Neuroscience 27, 555-560 (2024)</arxiv:journal_ref>
    <link rel="alternate" type="text/html" href="http://arxiv.org/abs/2401.12345v2" />
    <link title="pdf" rel="related" type="application/pdf"
          href="http://arxiv.org/pdf/2401.12345v2" />
  </entry>
</feed>
"""


def test_parse_arxiv_atom_happy_path() -> None:
    meta = parse_arxiv_atom(_SAMPLE_ATOM, "2401.12345")
    assert meta["id"] == "2401.12345v2"
    assert meta["title"] == "A great paper on the brain"
    assert "deep state-space models" in meta["summary"]
    assert [a["name"] for a in meta["authors"]] == ["Ada Lovelace", "Alan Turing"]
    assert meta["authors"][0]["affiliation"] == "Cambridge"
    assert meta["categories"] == ["q-bio.NC", "cs.LG"]
    assert meta["primary_category"] == "q-bio.NC"
    assert meta["doi"] == "10.1234/example"
    assert meta["pdf_url"] == "http://arxiv.org/pdf/2401.12345v2"
    assert meta["source_url"] == "http://arxiv.org/abs/2401.12345v2"
    assert meta["published"] is not None
    assert meta["updated"] is not None


_EMPTY_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
</feed>
"""


def test_parse_arxiv_atom_missing_entry() -> None:
    with pytest.raises(ArxivNotFound):
        parse_arxiv_atom(_EMPTY_FEED, "9999.99999")


_ERROR_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/api/errors#bad_id</id>
    <title>Error</title>
    <summary>incorrect id format</summary>
  </entry>
</feed>
"""


def test_parse_arxiv_atom_error_entry() -> None:
    with pytest.raises(ArxivNotFound):
        parse_arxiv_atom(_ERROR_FEED, "bogus")
