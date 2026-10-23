"""Shared SQLAlchemy models for authentication and conversation storage."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("preferred_locale IN ('pt-BR', 'en')"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str | None] = mapped_column(String(512))
    email: Mapped[str | None] = mapped_column(String(512))
    preferred_locale: Mapped[str] = mapped_column(String(5))


class Identity(Base):
    __tablename__ = "external_identities"
    __table_args__ = (UniqueConstraint("issuer", "subject"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    issuer: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(String(255))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)


class BrowserSession(Base):
    __tablename__ = "sessions"
    secret_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[int] = mapped_column(BigInteger)
    last_used_at: Mapped[int] = mapped_column(BigInteger)
    idle_expires_at: Mapped[int] = mapped_column(BigInteger)
    absolute_expires_at: Mapped[int] = mapped_column(BigInteger)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class LoginTransaction(Base):
    __tablename__ = "oidc_transactions"
    binding_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    state_hash: Mapped[str] = mapped_column(String(64))
    nonce: Mapped[str] = mapped_column(String(64))
    verifier: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[int] = mapped_column(BigInteger, index=True)
    return_to: Mapped[str] = mapped_column(String(512))
    locale: Mapped[str] = mapped_column(String(5))


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_language: Mapped[str | None] = mapped_column(String(255))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


Index(
    "ix_conversations_owner_order",
    Conversation.user_id,
    Conversation.created_at.desc(),
    Conversation.id.desc(),
    postgresql_where=Conversation.deleted_at.is_(None),
)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "sequence"),
        CheckConstraint("sequence > 0"),
        CheckConstraint("role IN ('user', 'assistant')"),
        CheckConstraint(
            "status IN ('streaming', 'completed', 'failed', 'cancelled', 'interrupted')"
        ),
        CheckConstraint(
            "(role = 'user' AND status = 'completed' AND response_language IS NULL "
            "AND language_source IS NULL AND error_code IS NULL) OR "
            "(role = 'assistant' AND detected_language IS NULL)"
        ),
        CheckConstraint(
            "language_source IS NULL OR "
            "language_source IN ('message', 'conversation', 'ui_preference')"
        ),
        CheckConstraint(
            "status NOT IN ('completed', 'streaming') OR error_code IS NULL"
        ),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    sequence: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))
    client_message_id: Mapped[str | None] = mapped_column(String(128))
    detected_language: Mapped[str | None] = mapped_column(String(255))
    response_language: Mapped[str | None] = mapped_column(String(255))
    language_source: Mapped[str | None] = mapped_column(String(16))
    error_code: Mapped[str | None] = mapped_column(String(64))


class MessageAttempt(Base):
    __tablename__ = "message_attempts"
    __table_args__ = (
        UniqueConstraint("conversation_id", "client_message_id"),
        CheckConstraint(
            "state IN ('active', 'completed', 'failed', 'cancelled', 'interrupted')"
        ),
        CheckConstraint("lease_expires_at > created_at"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    client_message_id: Mapped[str] = mapped_column(String(128))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    user_message_id: Mapped[str] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), unique=True
    )
    assistant_message_id: Mapped[str] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), unique=True
    )
    state: Mapped[str] = mapped_column(String(16))
    lease_token: Mapped[str] = mapped_column(String(64))
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


Index(
    "uq_message_attempts_active",
    MessageAttempt.conversation_id,
    unique=True,
    postgresql_where=MessageAttempt.state == "active",
)
