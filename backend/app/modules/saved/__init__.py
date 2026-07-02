"""Saved articles module: bookmark list per user.

A simple two-column association table (``user_id``, ``article_id``) plus
``saved_at`` timestamp. Idempotent save/unsave through Postgres
``INSERT … ON CONFLICT DO NOTHING``.
"""
