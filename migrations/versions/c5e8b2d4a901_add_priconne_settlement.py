"""保留原始战绩，新增可空结算依据。"""

from alembic import op
import sqlalchemy as sa

revision = "c5e8b2d4a901"
down_revision = "e828532300c4"
branch_labels = None
depends_on = None


def upgrade(name=""):
    if not name:
        op.add_column("priconne_record", sa.Column("settlement", sa.JSON(), nullable=True))


def downgrade(name=""):
    if not name:
        with op.batch_alter_table("priconne_record") as batch:
            batch.drop_column("settlement")
