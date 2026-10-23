"""conversation_persistence"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_language", sa.String(length=255), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_conversations_owner_order",
        "conversations",
        ["user_id", sa.literal_column("created_at DESC"), sa.literal_column("id DESC")],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("conversation_id", sa.String(length=64), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("client_message_id", sa.String(length=128), nullable=True),
        sa.Column("detected_language", sa.String(length=255), nullable=True),
        sa.Column("response_language", sa.String(length=255), nullable=True),
        sa.Column("language_source", sa.String(length=16), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.CheckConstraint(
            "(role = 'user' AND status = 'completed' AND response_language IS NULL AND language_source IS NULL AND error_code IS NULL) OR (role = 'assistant' AND detected_language IS NULL)"
        ),
        sa.CheckConstraint(
            "language_source IS NULL OR language_source IN ('message', 'conversation', 'ui_preference')"
        ),
        sa.CheckConstraint("role IN ('user', 'assistant')"),
        sa.CheckConstraint(
            "status IN ('streaming', 'completed', 'failed', 'cancelled', 'interrupted')"
        ),
        sa.CheckConstraint(
            "status NOT IN ('completed', 'streaming') OR error_code IS NULL"
        ),
        sa.CheckConstraint("sequence > 0"),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conversation_id", "sequence"),
    )
    op.create_table(
        "message_attempts",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("conversation_id", sa.String(length=64), nullable=False),
        sa.Column("client_message_id", sa.String(length=128), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("user_message_id", sa.String(length=64), nullable=False),
        sa.Column("assistant_message_id", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("lease_token", sa.String(length=64), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('active', 'completed', 'failed', 'cancelled', 'interrupted')"
        ),
        sa.CheckConstraint("lease_expires_at > created_at"),
        sa.ForeignKeyConstraint(
            ["assistant_message_id"], ["messages.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_message_id"], ["messages.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assistant_message_id"),
        sa.UniqueConstraint("conversation_id", "client_message_id"),
        sa.UniqueConstraint("user_message_id"),
    )
    op.create_index(
        "uq_message_attempts_active",
        "message_attempts",
        ["conversation_id"],
        unique=True,
        postgresql_where=sa.text("state = 'active'"),
    )


def downgrade():
    op.drop_index(
        "uq_message_attempts_active",
        table_name="message_attempts",
        postgresql_where=sa.text("state = 'active'"),
    )
    op.drop_table("message_attempts")
    op.drop_table("messages")
    op.drop_index(
        "ix_conversations_owner_order",
        table_name="conversations",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_table("conversations")
