"""Direct messages module: 1:1 and group conversations with ProseMirror content.

Uniqueness of DM conversations between any pair of users is enforced via
the ``conversations.dm_key`` column (``"{min_uuid}:{max_uuid}"``). Group
conversations have ``dm_key=NULL``.
"""
