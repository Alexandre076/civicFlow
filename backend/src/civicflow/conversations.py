"""Owner-scoped storage primitives. Caller owns transaction/commit and session fence."""

import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, tuple_
from sqlalchemy.orm import Session

from civicflow.models import Conversation, Message, MessageAttempt


class ConversationNotFound(Exception):
    """Unknown, foreign and deleted identifiers deliberately share one result."""


class AttemptConflict(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def utcnow():
    return datetime.now(UTC)


def identifier():
    return secrets.token_urlsafe(24)


@dataclass
class Page:
    items: list
    high_water: object
    next_after: object


class ConversationRepository:
    def __init__(self, db: Session):
        self.db = db

    def _owned(self, user_id, conversation_id, *, lock=False):
        query = select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
            Conversation.deleted_at.is_(None),
        )
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        row = self.db.scalar(query.execution_options(populate_existing=True))
        if row is None:
            raise ConversationNotFound()
        return row

    def create(self, user_id: str):
        now = utcnow()
        row = Conversation(
            id=identifier(), user_id=user_id, created_at=now, updated_at=now
        )
        self.db.add(row)
        self.db.flush()
        return row

    def get(self, user_id: str, conversation_id: str):
        return self._owned(user_id, conversation_id)

    def list_conversations(
        self, user_id: str, *, limit=50, after=None, high_water=None
    ):
        self._limit(limit)
        key = tuple_(Conversation.created_at, Conversation.id)
        query = select(Conversation).where(
            Conversation.user_id == user_id, Conversation.deleted_at.is_(None)
        )
        if high_water is not None:
            query = query.where(key <= high_water)
        if after is not None:
            query = query.where(key < after)
        rows = list(
            self.db.scalars(
                query.execution_options(populate_existing=True)
                .order_by(Conversation.created_at.desc(), Conversation.id.desc())
                .limit(limit + 1)
            )
        )
        if high_water is None and rows:
            high_water = (rows[0].created_at, rows[0].id)
        items = rows[:limit]
        next_after = (items[-1].created_at, items[-1].id) if len(rows) > limit else None
        return Page(items, high_water, next_after)

    def list_messages(
        self, user_id: str, conversation_id: str, *, limit=50, after=0, high_water=None
    ):
        self._limit(limit)
        # Lock keeps ownership/deletion visibility and history in one transaction.
        self._owned(user_id, conversation_id, lock=True)
        if high_water is None:
            high_water = self._sequence(conversation_id)
        rows = list(
            self.db.scalars(
                select(Message)
                .where(
                    Message.conversation_id == conversation_id,
                    Message.sequence > after,
                    Message.sequence <= high_water,
                )
                .execution_options(populate_existing=True)
                .order_by(Message.sequence)
                .limit(limit + 1)
            )
        )
        items = rows[:limit]
        return Page(
            items, high_water, items[-1].sequence if len(rows) > limit else None
        )

    @staticmethod
    def _limit(limit):
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= 100
        ):
            raise ValueError("limit must be between 1 and 100")

    def _sequence(self, conversation_id):
        return self.db.scalar(
            select(func.coalesce(func.max(Message.sequence), 0)).where(
                Message.conversation_id == conversation_id
            )
        )

    @staticmethod
    def _content(content):
        if not isinstance(content, str) or not content.strip() or len(content) > 8000:
            raise ValueError("invalid content")
        content.encode("utf-8")
        if "\x00" in content:
            raise ValueError("invalid content")

    @staticmethod
    def _language(value):
        # Syntactic language-tag boundary; detection/canonicalization belongs to #24.
        if value is not None and not re.fullmatch(
            r"[A-Za-z]{1,8}(?:-[A-Za-z0-9]{1,8})*", value
        ):
            raise ValueError("invalid language tag")
        if value is not None and len(value) > 255:
            raise ValueError("language tag too long")

    def append_user(
        self,
        user_id: str,
        conversation_id: str,
        content: str,
        *,
        detected_language=None,
    ):
        self._content(content)
        self._language(detected_language)
        conversation = self._owned(user_id, conversation_id, lock=True)
        if self.db.scalar(
            select(MessageAttempt.id).where(
                MessageAttempt.conversation_id == conversation_id,
                MessageAttempt.state == "active",
            )
        ):
            raise AttemptConflict("CONVERSATION_BUSY")
        now = utcnow()
        row = Message(
            id=identifier(),
            conversation_id=conversation_id,
            sequence=self._sequence(conversation_id) + 1,
            role="user",
            content=content,
            status="completed",
            created_at=now,
            updated_at=now,
            detected_language=detected_language,
        )
        self.db.add(row)
        self._touch(conversation, now, detected_language)
        self.db.flush()
        return row

    @staticmethod
    def _touch(conversation, now, language=None):
        conversation.updated_at = now
        if language is not None:
            conversation.last_language = language

    def accept_attempt_internal(
        self,
        user_id: str,
        conversation_id: str,
        *,
        content: str,
        client_message_id: str,
        response_language: str,
        language_source: str,
        detected_language=None,
        lease_seconds=60,
    ):
        """Privileged #24 operation; never bind internal metadata from request JSON."""
        self._content(content)
        self._language(detected_language)
        self._language(response_language)
        if response_language is None or language_source not in {
            "message",
            "conversation",
            "ui_preference",
        }:
            raise ValueError("invalid response metadata")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", client_message_id):
            raise ValueError("invalid client_message_id")
        if not 0 < lease_seconds <= 3600:
            raise ValueError("invalid lease duration")
        conversation = self._owned(user_id, conversation_id, lock=True)
        fingerprint = hashlib.sha256(content.encode("utf-8")).hexdigest()
        existing = self.db.scalar(
            select(MessageAttempt)
            .where(
                MessageAttempt.conversation_id == conversation_id,
                MessageAttempt.client_message_id == client_message_id,
            )
            .execution_options(populate_existing=True)
        )
        if existing:
            if existing.request_fingerprint != fingerprint:
                raise AttemptConflict("IDEMPOTENCY_CONFLICT")
            if existing.state == "completed":
                return existing
            raise AttemptConflict(
                "MESSAGE_IN_PROGRESS"
                if existing.state == "active"
                else "ATTEMPT_TERMINAL"
            )
        if self.db.scalar(
            select(MessageAttempt.id).where(
                MessageAttempt.conversation_id == conversation_id,
                MessageAttempt.state == "active",
            )
        ):
            raise AttemptConflict("CONVERSATION_BUSY")
        now = utcnow()
        sequence = self._sequence(conversation_id)
        user = Message(
            id=identifier(),
            conversation_id=conversation_id,
            sequence=sequence + 1,
            role="user",
            content=content,
            status="completed",
            created_at=now,
            updated_at=now,
            client_message_id=client_message_id,
            detected_language=detected_language,
        )
        assistant = Message(
            id=identifier(),
            conversation_id=conversation_id,
            sequence=sequence + 2,
            role="assistant",
            content="",
            status="streaming",
            created_at=now,
            updated_at=now,
            client_message_id=client_message_id,
            response_language=response_language,
            language_source=language_source,
        )
        self.db.add_all([user, assistant])
        self.db.flush()
        attempt = MessageAttempt(
            id=identifier(),
            conversation_id=conversation_id,
            client_message_id=client_message_id,
            request_fingerprint=fingerprint,
            user_message_id=user.id,
            assistant_message_id=assistant.id,
            state="active",
            lease_token=identifier(),
            lease_expires_at=now + timedelta(seconds=lease_seconds),
            created_at=now,
            updated_at=now,
        )
        self.db.add(attempt)
        self._touch(conversation, now, detected_language or response_language)
        self.db.flush()
        return attempt

    def write_assistant_internal(
        self,
        user_id: str,
        conversation_id: str,
        *,
        attempt_id: str,
        lease_token: str,
        content: str,
        status="streaming",
        error_code=None,
    ):
        """Checkpoint/terminal primitive; locks and rechecks deletion and worker lease."""
        if status not in {
            "streaming",
            "completed",
            "failed",
            "cancelled",
            "interrupted",
        }:
            raise ValueError("invalid assistant status")
        content.encode("utf-8")
        if "\x00" in content:
            raise ValueError("invalid content")
        if status in {"streaming", "completed"} and error_code is not None:
            raise ValueError("successful/active message cannot have an error")
        if error_code is not None and not re.fullmatch(
            r"[A-Z][A-Z0-9_]{0,63}", error_code
        ):
            raise ValueError("invalid error code")
        conversation = self._owned(user_id, conversation_id, lock=True)
        attempt = self.db.scalar(
            select(MessageAttempt)
            .where(
                MessageAttempt.id == attempt_id,
                MessageAttempt.conversation_id == conversation_id,
            )
            .execution_options(populate_existing=True)
        )
        now = utcnow()
        if (
            attempt is None
            or attempt.state != "active"
            or attempt.lease_token != lease_token
            or attempt.lease_expires_at <= now
        ):
            raise AttemptConflict("STALE_WORKER")
        message = self.db.get(
            Message, attempt.assistant_message_id, populate_existing=True
        )
        if message.status != "streaming":
            raise AttemptConflict("ATTEMPT_TERMINAL")
        if not content.startswith(message.content):
            raise ValueError("checkpoint must preserve durable prefix")
        message.content, message.status = content, status
        message.error_code, message.updated_at = error_code, now
        attempt.updated_at = now
        if status != "streaming":
            attempt.state = status
            self._touch(conversation, now, message.response_language)
        self.db.flush()
        return message

    def delete(self, user_id: str, conversation_id: str):
        conversation = self._owned(user_id, conversation_id, lock=True)
        self.db.execute(
            delete(MessageAttempt).where(
                MessageAttempt.conversation_id == conversation_id
            )
        )
        self.db.execute(
            delete(Message).where(Message.conversation_id == conversation_id)
        )
        conversation.deleted_at = utcnow()
        conversation.updated_at = conversation.deleted_at
        conversation.last_language = None
        self.db.flush()
