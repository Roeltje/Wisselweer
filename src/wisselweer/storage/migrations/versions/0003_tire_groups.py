"""tire_group: banden per groep binnen een set

Elke bestaande set krijgt één groep van 4 banden met de DOT-code en aankoopdatum van de set;
daarna verdwijnen `dot_code` en `purchase_date` van `tire_set`. Downgrade zet ze terug uit de
eerste actieve groep (groepen met afwijkende gegevens gaan dan verloren).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-01 10:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def _batch_tire_set():
    """Batch-context voor `tire_set` zonder de tabel opnieuw aan te maken (`recreate="never"`).

    `tire_change` en `tire_group` verwijzen naar `tire_set`, en de verbindingen staan met
    `foreign_keys=ON`: een DROP TABLE van de oorspronkelijke tabel (de standaard "move and copy" van
    batch-mode op SQLite) faalt dan bij het committen zodra er verwijzende rijen zijn. De kolommen
    zijn niet geïndexeerd en komen in geen enkele constraint voor, dus SQLite's eigen
    `ALTER TABLE ... DROP/ADD COLUMN` (vanaf 3.35) volstaat.
    """
    if op.get_bind().dialect.name == "sqlite":
        import sqlite3

        if sqlite3.sqlite_version_info < (3, 35):
            raise RuntimeError("SQLite 3.35 of nieuwer is nodig voor deze migratie")
    return op.batch_alter_table("tire_set", schema=None, recreate="never")


def upgrade() -> None:
    op.create_table(
        "tire_group",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tire_set_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("dot_code", sa.String(length=20), nullable=True),
        sa.Column("purchase_date", sa.Date(), nullable=True),
        sa.Column("brand", sa.String(length=80), nullable=True),
        sa.Column("model", sa.String(length=80), nullable=True),
        sa.Column("has_3pmsf", sa.Boolean(), nullable=True),
        sa.Column("positions", sa.String(length=20), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("removed_on", sa.Date(), nullable=True),
        sa.Column("removed_note", sa.String(length=500), nullable=True),
        sa.CheckConstraint("quantity BETWEEN 1 AND 4", name="ck_tire_group_quantity"),
        sa.ForeignKeyConstraint(["tire_set_id"], ["tire_set.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("tire_group", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_tire_group_tire_set_id"), ["tire_set_id"], unique=False
        )

    # Bestaande data meenemen: één groep van 4 per set.
    op.execute(
        "INSERT INTO tire_group (tire_set_id, quantity, dot_code, purchase_date, created_at) "
        "SELECT id, 4, dot_code, purchase_date, created_at FROM tire_set ORDER BY id"
    )

    with _batch_tire_set() as batch_op:
        batch_op.drop_column("dot_code")
        batch_op.drop_column("purchase_date")


def downgrade() -> None:
    with _batch_tire_set() as batch_op:
        batch_op.add_column(sa.Column("dot_code", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("purchase_date", sa.Date(), nullable=True))

    # Waarden uit de eerste actieve groep (anders de eerste groep) terugzetten.
    for column in ("dot_code", "purchase_date"):
        op.execute(
            f"UPDATE tire_set SET {column} = ("  # noqa: S608 - vaste kolomnamen
            f"SELECT g.{column} FROM tire_group g WHERE g.tire_set_id = tire_set.id "
            "ORDER BY (g.removed_on IS NOT NULL), g.id LIMIT 1)"
        )

    with op.batch_alter_table("tire_group", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_tire_group_tire_set_id"))
    op.drop_table("tire_group")
