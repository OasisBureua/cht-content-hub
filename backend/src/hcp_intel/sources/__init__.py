"""Feed source implementations for HCP Intel.

Each source module exposes:
- ``fetch(subscription, since=None) -> list[FeedItemPayload]``
- ``extract_signals(item) -> list[SignalPayload]``

Sources are looked up by string name (matches `feed_sources.name`).
"""
