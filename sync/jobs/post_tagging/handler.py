"""post_tagging — EventBridge Lambda handler (Phase 1.5 scaffold).

Runs playlist/post tagging cron. Invokes cache_clear on success.
"""

from __future__ import annotations


def handler(event: dict, context) -> dict:
    # TODO CH-03: wire to backend/src/jobs/post_tagging.py
    return {"status": "not_implemented", "job": "post_tagging"}
