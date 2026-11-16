from __future__ import annotations

from pathlib import Path

from sqlalchemy import Index
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.schema import CreateIndex

from app.models import BoardColumn


def test_default_column_uses_a_partial_unique_index() -> None:
    default_indexes = [
        index
        for index in BoardColumn.__table__.indexes
        if index.name == "uq_board_columns_board_default"
    ]

    assert len(default_indexes) == 1
    index = default_indexes[0]
    assert isinstance(index, Index)
    assert index.unique
    assert [column.name for column in index.columns] == ["board_id"]
    assert str(index.dialect_options["postgresql"]["where"]) == "is_default"
    expected_sql = (
        "CREATE UNIQUE INDEX uq_board_columns_board_default "
        "ON board_columns (board_id) WHERE is_default"
    )
    assert str(CreateIndex(index).compile(dialect=postgresql.dialect())) == expected_sql
    assert str(CreateIndex(index).compile(dialect=sqlite.dialect())) == expected_sql


def test_column_default_migration_replaces_the_legacy_constraint() -> None:
    versions = Path(__file__).parents[1] / "alembic" / "versions"
    column_migration = (versions / "0013_column_default.py").read_text(encoding="utf-8")

    assert "op.create_unique_constraint" not in column_migration
    assert "op.drop_constraint(" in column_migration
    assert "op.drop_index(" in column_migration
    assert 'postgresql_where=sa.text("is_default")' in column_migration
    assert "PARTITION BY board_id" in column_migration
