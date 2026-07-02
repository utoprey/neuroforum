"""Reactions module: neuro-themed enum reactions on articles + messages.

Two independent tables (``article_reactions`` / ``message_reactions``) share
the same Postgres enum ``reaction_kind``. Denormalised count maps live in
the parent row's ``reaction_counts JSONB`` column and are kept fresh by
this module's service layer.
"""
