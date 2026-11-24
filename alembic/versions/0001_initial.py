"""Initial complete schema for fresh V4 installs.

Revision ID: 0001_initial
Revises:
"""
from alembic import op
from app.db import Base
import app.models
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    # Tables are declared in one authoritative SQLAlchemy metadata registry.
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, checkfirst=True)

def downgrade():
    Base.metadata.drop_all(bind=op.get_bind(), checkfirst=True)
