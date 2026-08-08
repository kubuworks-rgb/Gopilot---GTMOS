"""Every index declared on a model must be created by a migration.

Rather than pattern-match migration source (which silently misses whichever code
shape a migration happens to use), this executes each `upgrade()` against a
recording stub of `alembic.op`. Every call style — literal, helper function, or
loop — is therefore captured, and no database is required.

This is the permanent guard for the index drift diagnosed in the takeover audit.
"""

from __future__ import annotations

import importlib.util
import pathlib
from typing import Any

import pytest
import sqlalchemy as sa

from apps.api.app.db.models import Base


VERSIONS = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions"


class _RecordingOp:
    """Stands in for `alembic.op`, recording schema operations and ignoring the rest."""

    def __init__(self) -> None:
        self.indexes: dict[str, tuple[str, tuple[str, ...], bool]] = {}
        self.columns: dict[str, set[str]] = {}

    def create_index(
        self,
        index_name: str,
        table_name: str,
        columns: list[str],
        unique: bool = False,
        **_: Any,
    ) -> None:
        self.indexes[index_name] = (
            table_name,
            tuple(sorted(str(column) for column in columns)),
            bool(unique),
        )

    def drop_index(self, index_name: str, **_: Any) -> None:
        self.indexes.pop(index_name, None)

    def create_table(self, table_name: str, *elements: Any, **_: Any) -> None:
        self.columns[table_name] = {
            element.name for element in elements if isinstance(element, sa.Column)
        }
        # Inline constraints and indexes count as created too. Postgres backs a
        # UNIQUE constraint with a unique index of the same name, so a model that
        # declares `Index(..., unique=True)` is satisfied by either form.
        for element in elements:
            if isinstance(element, sa.UniqueConstraint) and element.name:
                self.indexes[str(element.name)] = (
                    table_name,
                    tuple(sorted(str(column) for column in element._pending_colargs)),
                    True,
                )
            elif isinstance(element, sa.Index) and element.name:
                self.indexes[str(element.name)] = (
                    table_name,
                    tuple(sorted(str(column) for column in element.expressions)),
                    bool(element.unique),
                )

    def drop_table(self, table_name: str, **_: Any) -> None:
        self.columns.pop(table_name, None)

    def add_column(self, table_name: str, column: Any, **_: Any) -> None:
        self.columns.setdefault(table_name, set()).add(column.name)

    def drop_column(self, table_name: str, column_name: str, **_: Any) -> None:
        self.columns.get(table_name, set()).discard(column_name)

    def rename_table(self, old_name: str, new_name: str, **_: Any) -> None:
        self.columns[new_name] = self.columns.pop(old_name, set())

    def __getattr__(self, _name: str) -> Any:
        # execute, alter_column, create_foreign_key, ... all no-op here.
        def _noop(*_args: Any, **_kwargs: Any) -> None:
            return None

        return _noop


def _migration_modules() -> list[Any]:
    modules = []
    for path in sorted(VERSIONS.glob("[0-9]*.py")):
        spec = importlib.util.spec_from_file_location(f"_mig_{path.stem}", path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules.append(module)
    return modules


def _replayed_schema() -> _RecordingOp:
    recorder = _RecordingOp()
    for module in _migration_modules():
        original = module.op
        module.op = recorder
        try:
            module.upgrade()
        finally:
            module.op = original
    return recorder


def _migrated_indexes() -> dict[str, tuple[str, tuple[str, ...], bool]]:
    return _replayed_schema().indexes


def _model_indexes() -> dict[str, tuple[str, tuple[str, ...], bool]]:
    """Indexes plus unique constraints.

    PostgreSQL backs a UNIQUE constraint with a unique index of the same name, so
    both forms express the same invariant and either satisfies the other.
    """

    declared: dict[str, tuple[str, tuple[str, ...], bool]] = {}
    for table in Base.metadata.sorted_tables:
        for index in table.indexes:
            if index.name:
                declared[str(index.name)] = (
                    table.name,
                    tuple(sorted(column.name for column in index.columns)),
                    bool(index.unique),
                )
        for constraint in table.constraints:
            if isinstance(constraint, sa.UniqueConstraint) and constraint.name:
                declared[str(constraint.name)] = (
                    table.name,
                    tuple(sorted(column.name for column in constraint.columns)),
                    True,
                )
    return declared


def test_migration_chain_is_linear_and_complete() -> None:
    modules = _migration_modules()
    revisions = [module.revision for module in modules]
    parents = [module.down_revision for module in modules]

    assert parents[0] is None, "the first migration must have no parent"
    assert parents[1:] == revisions[:-1], "migrations must form one linear chain"
    assert len(set(revisions)) == len(revisions), "revision ids must be unique"


def test_every_model_index_is_created_by_a_migration() -> None:
    model = _model_indexes()
    migrated = _migrated_indexes()

    missing = sorted(set(model) - set(migrated))
    assert not missing, (
        "indexes declared on models but never migrated: " + ", ".join(missing)
    )


def test_no_migration_creates_an_index_the_models_do_not_declare() -> None:
    model = _model_indexes()
    migrated = _migrated_indexes()

    extra = sorted(set(migrated) - set(model))
    assert not extra, (
        "indexes created by migrations but absent from model metadata: "
        + ", ".join(extra)
    )


@pytest.mark.parametrize("attribute", ["table", "columns", "unique"])
def test_shared_indexes_agree_on_shape(attribute: str) -> None:
    model = _model_indexes()
    migrated = _migrated_indexes()
    position = ["table", "columns", "unique"].index(attribute)

    mismatched = {
        name: (model[name][position], migrated[name][position])
        for name in set(model) & set(migrated)
        if model[name][position] != migrated[name][position]
    }
    assert not mismatched, f"{attribute} disagreements: {mismatched}"


def test_migrations_and_models_agree_on_tables() -> None:
    migrated = set(_replayed_schema().columns)
    model = {table.name for table in Base.metadata.sorted_tables}

    assert not model - migrated, f"tables never migrated: {sorted(model - migrated)}"
    assert not migrated - model, f"tables absent from models: {sorted(migrated - model)}"


def test_migrations_and_models_agree_on_columns() -> None:
    """Guards the `alembic check` gate in CI, which needs a live database to run."""
    migrated = _replayed_schema().columns
    disagreements: dict[str, dict[str, list[str]]] = {}

    for table in Base.metadata.sorted_tables:
        expected = {column.name for column in table.columns}
        actual = migrated.get(table.name, set())
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        if missing or extra:
            disagreements[table.name] = {
                "missing_in_migration": missing,
                "absent_from_model": extra,
            }

    assert not disagreements, f"column drift: {disagreements}"


def test_source_chunk_ordinal_uniqueness_is_enforced_by_the_database() -> None:
    """Enforced since 0002 as a UniqueConstraint, which Postgres backs with an index.

    The models declare it as a unique `Index`; either form satisfies the invariant,
    and migration 0007 deliberately does not recreate it.
    """
    migrated = _migrated_indexes()

    assert "uq_source_chunk_ordinal" in migrated
    table, columns, unique = migrated["uq_source_chunk_ordinal"]
    assert table == "source_chunks"
    assert columns == ("ordinal", "source_document_id")
    assert unique is True
