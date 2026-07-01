"""Shared pytest fixtures for contenthub-api."""

from __future__ import annotations

import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

os.environ.setdefault("PUBLIC_API_KEY", "test-public-key")
# In-memory SQLite — no Docker/Postgres required for tests.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import db_types  # noqa: E402, F401 — register SQLite type compilers

from path_setup import install  # noqa: E402

install()

from config import get_settings  # noqa: E402

get_settings.cache_clear()

from database import engine, get_db  # noqa: E402
from hcp_intel.models import HCP, HCPSignal  # noqa: E402
from main import app  # noqa: E402
from models.client import Client  # noqa: E402
from models.kol import KOL, KOLGroup, KOLGroupMember  # noqa: E402
from models.project import Project  # noqa: E402
from models.shoot import Shoot  # noqa: E402
from schema import create_test_schema  # noqa: E402
from utils.kol_public import kol_slug  # noqa: E402

API_KEY = os.environ["PUBLIC_API_KEY"]


@asynccontextmanager
async def _noop_lifespan(_app):
    yield


# Skip main.py create_all during HTTP tests — conftest builds a minimal schema.
app.router.lifespan_context = _noop_lifespan


def api_headers(**extra: str) -> dict[str, str]:
    headers = {"X-API-Key": API_KEY}
    headers.update(extra)
    return headers


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """SlowAPI uses in-memory counters on the shared app — reset between tests."""
    try:
        app.state.limiter._storage.reset()
    except Exception:
        pass
    yield
    try:
        app.state.limiter._storage.reset()
    except Exception:
        pass


@pytest.fixture
async def http_client() -> AsyncIterator[AsyncClient]:
    """HTTP client without DB override — for auth/validation-only tests."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    async with engine.begin() as conn:
        await create_test_schema(conn)

    async with engine.connect() as conn:
        trans = await conn.begin()
        session = AsyncSession(bind=conn, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
async def sample_kol(db_session: AsyncSession) -> KOL:
    kol = KOL(
        slug=kol_slug("Dr. Jane Smith"),
        name="Dr. Jane Smith",
        title="MD",
        specialty="Medical Oncology",
        institution="UCSF",
        region="california",
    )
    db_session.add(kol)
    await db_session.flush()
    return kol


@pytest.fixture
async def kol_with_shoot(db_session: AsyncSession) -> KOL:
    client = Client(name="Test Pharma", slug="test-pharma")
    project = Project(client=client, name="Test Drug", code="TD01")
    kol = KOL(
        slug=kol_slug("Dr. Jason Mouabbi"),
        name="Dr. Jason Mouabbi",
        specialty="Medical Oncology",
        institution="MD Anderson",
        region="texas",
    )
    group = KOLGroup(project=project, name="Mouabbi Group")
    member = KOLGroupMember(kol=kol, kol_group=group)
    shoot = Shoot(
        id="shoot-test-1",
        name="Episode 1",
        project=project,
        kol_group=group,
        shoot_date=datetime.now(timezone.utc) - timedelta(days=14),
        doctors=[],
    )
    db_session.add_all([client, project, kol, group, member, shoot])
    await db_session.flush()
    return kol


@pytest.fixture
async def kol_with_publications(db_session: AsyncSession) -> KOL:
    npi = "1234567890"
    hcp = HCP(npi=npi, first_name="Virginia", last_name="Kaklamani")
    kol = KOL(
        slug=kol_slug("Dr. Virginia Kaklamani"),
        name="Dr. Virginia Kaklamani",
        institution="UT Southwestern",
        region="texas",
        hcp_npi=npi,
    )
    db_session.add_all([hcp, kol])
    await db_session.flush()

    signals = [
        HCPSignal(
            hcp_npi=npi,
            signal_type="publication",
            observed_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
            source="pubmed",
            title="Recent Paper",
            url="https://example.com/recent",
            entities_json={"journal": "JCO", "is_first_author": True},
        ),
        HCPSignal(
            hcp_npi=npi,
            signal_type="publication",
            observed_at=datetime(2023, 1, 1, tzinfo=timezone.utc),
            source="pubmed",
            title="Older Paper",
            url="https://example.com/older",
            entities_json={"journal": "NEJM", "is_last_author": True},
        ),
        HCPSignal(
            hcp_npi=npi,
            signal_type="clinical_trial",
            observed_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            source="clinicaltrials",
            title="Should not appear",
        ),
    ]
    db_session.add_all(signals)
    await db_session.flush()
    return kol
