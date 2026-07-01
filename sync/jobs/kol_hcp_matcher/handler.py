"""kol_hcp_matcher — link KOL rows to HCP NPIs."""

from __future__ import annotations

from shared.runtime import configure_logging, install_paths, run_async


async def _run(event: dict) -> dict:
    from sqlalchemy import select

    from database import async_session_maker
    from hcp_intel.kol_hcp_matcher import resolve_and_persist
    from models.kol import KOL

    limit = event.get("limit")
    stats = {
        "processed": 0,
        "auto_locked": 0,
        "needs_review": 0,
        "no_match": 0,
    }

    async with async_session_maker() as db:
        stmt = select(KOL).where(KOL.hcp_match_status == "unresolved").order_by(KOL.name)
        if limit is not None:
            stmt = stmt.limit(int(limit))
        kols = list((await db.execute(stmt)).scalars().all())

        for kol in kols:
            result = await resolve_and_persist(db, kol)
            stats["processed"] += 1
            if result.status == "auto_locked":
                stats["auto_locked"] += 1
            elif result.status == "needs_review":
                stats["needs_review"] += 1
            else:
                stats["no_match"] += 1

        await db.commit()

    return {"status": "ok", "job": "kol_hcp_matcher", **stats}


def handler(event: dict, context) -> dict:
    install_paths()
    configure_logging()
    payload = event or {}
    if "Records" in payload and payload["Records"]:
        import json

        body = payload["Records"][0].get("body", "{}")
        try:
            payload = json.loads(body) if isinstance(body, str) else body
        except json.JSONDecodeError:
            payload = {}
    return run_async(_run(payload))
