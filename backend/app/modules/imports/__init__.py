"""Imports module: ingest external references (arXiv, DOI, biorxiv, …).

Level 1 — arXiv metadata: parses the arxiv id, fetches the Atom entry,
builds a ProseMirror summary doc and creates a draft article. The link
is recorded in ``external_sources`` for future Level 2 ingestion
(PDF parsing, figure extraction).
"""
