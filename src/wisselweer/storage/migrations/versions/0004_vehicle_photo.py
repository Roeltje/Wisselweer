"""vehicle_photo: kolom `vehicle.photo` voor één foto per voertuig

Bewaart alleen de bestandsnaam van de foto in `<data_dir>/photos/`. Downgrade verwijdert de
kolom; de bestanden zelf blijven dan als weesbestanden in de map staan.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-01 14:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def _batch_vehicle():
    """Batch-context voor `vehicle` zonder de tabel opnieuw aan te maken (`recreate="never"`).

    Veel tabellen verwijzen naar `vehicle` en de verbindingen staan met `foreign_keys=ON`: een
    DROP TABLE van de oorspronkelijke tabel (de standaard "move and copy" van batch-mode op SQLite)
    faalt dan zodra er verwijzende rijen zijn. De kolom is niet geïndexeerd en komt in geen enkele
    constraint voor, dus SQLite's eigen `ALTER TABLE ... DROP/ADD COLUMN` (vanaf 3.35) volstaat.
    """
    if op.get_bind().dialect.name == "sqlite":
        import sqlite3

        if sqlite3.sqlite_version_info < (3, 35):
            raise RuntimeError("SQLite 3.35 of nieuwer is nodig voor deze migratie")
    return op.batch_alter_table("vehicle", schema=None, recreate="never")


def upgrade() -> None:
    with _batch_vehicle() as batch_op:
        batch_op.add_column(sa.Column("photo", sa.String(length=64), nullable=True))


def downgrade() -> None:
    with _batch_vehicle() as batch_op:
        batch_op.drop_column("photo")
