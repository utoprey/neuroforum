"""Articles module: ``articles`` + immutable ``article_revisions`` snapshots.

Content is stored as ProseMirror JSON validated by the shared
``app.modules.content`` schemas. ``content_tsv`` is left as a deferred
column on the ORM side — production uses a GENERATED ALWAYS AS column,
populated in the first Alembic migration.
"""
