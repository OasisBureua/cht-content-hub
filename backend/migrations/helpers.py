"""Idempotent DDL helpers — baseline 0001 uses ORM create_all (head schema)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def table_exists(name: str) -> bool:
    return name in _inspector().get_table_names()


def column_exists(table: str, column: str) -> bool:
    if not table_exists(table):
        return False
    return column in {c["name"] for c in _inspector().get_columns(table)}


def index_exists(table: str, index: str) -> bool:
    if not table_exists(table):
        return False
    return index in {i["name"] for i in _inspector().get_indexes(table)}
