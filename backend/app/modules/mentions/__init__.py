"""Mentions module: polymorphic mention rows + de-duplicated history.

Every article / message / direct message that contains ``@user`` blocks gets
its mentions persisted here for the "/me/mentions" feed and so the
notification worker can flip ``notified_at`` once per row.
"""
