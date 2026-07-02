"""Forum module: ``sections`` and ``topics`` — the discussion taxonomy.

Two ratified data-model decisions live here:

- ``sections`` is a flat catalogue with manual ``position`` ordering.
- ``topics`` belong to a section, can be pinned/locked by moderators, and
  expose a ``UNIQUE(section_id, slug)`` so URLs stay stable.
"""
