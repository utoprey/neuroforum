"""Messages module: LTREE-threaded comments, reply-on-selection, soft delete.

Messages live under articles, form parent/child threads materialised through
a Postgres ``LTREE`` column, and snapshot pre-edit content into
``message_revisions`` mirroring the ``articles`` module.
"""
