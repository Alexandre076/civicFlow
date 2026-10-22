"""Shared SQLAlchemy foundation for authentication and future conversation migrations."""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    String,
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
