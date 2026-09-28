"""CPR-10: reports models stay out of the SQLite schema, so CI must still load them."""

from database import Base


def test_reports_metadata_sorted_tables_resolves():
    import models  # noqa: F401 — register reports.* on Base.metadata

    tables = Base.metadata.sorted_tables
    programs = next(t for t in tables if t.schema == "reports" and t.name == "programs")
    fk = next(iter(programs.c.campaign_id.foreign_keys))
    assert fk.column.table.name == "campaigns"
