"""Dramatiq actors for background tasks (video processing, GC, etc).

Each actor is registered with the default broker on import. The broker
itself is wired up by ``app.main`` (or a dedicated worker entry point)
before any actor is sent.

This package's __init__ imports every submodule so that running
``dramatiq app.workers`` discovers all actors via the broker registry.
"""

from __future__ import annotations

import os

import dramatiq
from dramatiq.brokers.rabbitmq import RabbitmqBroker
from dramatiq.brokers.stub import StubBroker

# Wire up a broker before importing actor modules — dramatiq actors
# register against whatever broker is current at import time.
_rabbit_url = os.environ.get("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/")
if os.environ.get("DRAMATIQ_STUB_BROKER") == "1":
    dramatiq.set_broker(StubBroker())
else:
    dramatiq.set_broker(RabbitmqBroker(url=_rabbit_url))

# Importing each module registers its @dramatiq.actor decorators.
from app.workers import ai_proposals, attachments  # noqa: E402,F401

__all__ = ["ai_proposals", "attachments"]
