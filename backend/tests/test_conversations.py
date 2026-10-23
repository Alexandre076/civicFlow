"""PostgreSQL storage integration tests, including independent concurrent sessions."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from civicflow.conversations import (
    MAX_ASSISTANT_CONTENT_BYTES,
    AttemptConflict,
    ConversationNotFound,
    ConversationRepository,
    utcnow,
)
from civicflow.models import BrowserSession, Conversation, Message, MessageAttempt, User


@pytest.fixture
def engine(auth_database):
    engine = create_engine(auth_database)
    with Session(engine) as db, db.begin():
        db.add_all(
            [User(id=name, preferred_locale="en") for name in ("owner", "other")]
        )
    yield engine
    engine.dispose()


def create(engine):
    with Session(engine) as db, db.begin():
        return ConversationRepository(db).create("owner").id


def accept(repo, cid, key="key", **kwargs):
    return repo.accept_attempt_internal(
        "owner",
        cid,
        content="Olá, rua com buraco",
        client_message_id=key,
        response_language="pt-BR",
        language_source="message",
        **kwargs,
    )


def test_restart_and_pagination(engine):
    cid = create(engine)
    with Session(engine) as db, db.begin():
        repo = ConversationRepository(db)
        repo.append_user("owner", cid, "one", detected_language="fr-CA")
        repo.append_user("owner", cid, "two")
        first = repo.list_messages("owner", cid, limit=1)
        assert first.high_water == 2 and first.next_after == 1
        repo.append_user("owner", cid, "three")
        second = repo.list_messages(
            "owner", cid, after=first.next_after, high_water=first.high_water
        )
        assert [m.content for m in second.items] == ["two"]
        assert repo.get("owner", cid).last_language is None
        assert first.items[0].detected_language == "fr-CA"
        assert first.items[0].created_at.utcoffset() == timedelta(0)
    engine.dispose()
    with Session(engine) as db, db.begin():
        assert [
            m.sequence
            for m in ConversationRepository(db).list_messages("owner", cid).items
        ] == [1, 2, 3]
        assert db.scalar(select(func.count()).select_from(MessageAttempt)) == 0


def test_conversation_keys(engine):
    with Session(engine) as db, db.begin():
        repo = ConversationRepository(db)
        rows = [repo.create("owner") for _ in range(4)]
        stamp = utcnow()
        for row in rows:
            row.created_at = stamp
        db.flush()
        expected = sorted([r.id for r in rows], reverse=True)
        page = repo.list_conversations("owner", limit=2)
        repo.create("owner")
        following = repo.list_conversations(
            "owner",
            after=(page.items[-1].created_at, page.items[-1].id),
            high_water=page.high_water,
        )
        assert [r.id for r in page.items + following.items] == expected
        assert repo.list_conversations("other").items == []


@pytest.mark.parametrize(
    "operation", ["get", "messages", "append", "accept", "write", "delete"]
)
def test_owner_isolation(engine, operation):
    cid = create(engine)
    with Session(engine) as db, db.begin():
        repo = ConversationRepository(db)
        for target in (cid, "unknown"):
            with pytest.raises(ConversationNotFound):
                if operation == "get":
                    repo.get("other", target)
                elif operation == "messages":
                    repo.list_messages("other", target)
                elif operation == "append":
                    repo.append_user("other", target, "text")
                elif operation == "accept":
                    repo.accept_attempt_internal(
                        "other",
                        target,
                        content="text",
                        client_message_id="key",
                        response_language="en",
                        language_source="message",
                    )
                elif operation == "write":
                    repo.write_assistant_internal(
                        "other",
                        target,
                        attempt_id="a",
                        lease_token="token",
                        content="text",
                    )
                else:
                    repo.delete("other", target)


def test_attempt_lifecycle_deletion_and_fence(engine):
    cid = create(engine)
    with Session(engine) as db, db.begin():
        repo = ConversationRepository(db)
        a = accept(repo, cid)
        aid, token = a.id, a.lease_token
        baseline = repo.get("owner", cid).updated_at
        repo.write_assistant_internal(
            "owner", cid, attempt_id=aid, lease_token=token, content="partial"
        )
        assert repo.get("owner", cid).updated_at == baseline
        assert [
            m.client_message_id for m in repo.list_messages("owner", cid).items
        ] == ["key", "key"]
        for key, code in [
            ("key", "MESSAGE_IN_PROGRESS"),
            ("different", "CONVERSATION_BUSY"),
        ]:
            with pytest.raises(AttemptConflict, match=code):
                accept(repo, cid, key)
        with pytest.raises(AttemptConflict, match="IDEMPOTENCY_CONFLICT"):
            repo.accept_attempt_internal(
                "owner",
                cid,
                content="changed",
                client_message_id="key",
                response_language="en",
                language_source="message",
            )
        repo.write_assistant_internal(
            "owner",
            cid,
            attempt_id=aid,
            lease_token=token,
            content="partial finished",
            status="completed",
        )
        assert repo.get("owner", cid).updated_at > baseline
        assert accept(repo, cid).id == aid
        with pytest.raises(AttemptConflict):
            repo.write_assistant_internal(
                "owner",
                cid,
                attempt_id=aid,
                lease_token=token,
                content="partial finished again",
            )
        accept(repo, cid, "next")
        repo.delete("owner", cid)
    with Session(engine) as db, db.begin():
        repo = ConversationRepository(db)
        for action in (
            lambda: repo.get("owner", cid),
            lambda: repo.delete("owner", cid),
            lambda: accept(repo, cid),
            lambda: repo.append_user("owner", cid, "stale"),
            lambda: repo.write_assistant_internal(
                "owner", cid, attempt_id=aid, lease_token=token, content="stale"
            ),
        ):
            with pytest.raises(ConversationNotFound):
                action()
        assert repo.list_conversations("owner").items == []
        assert db.scalar(select(func.count()).select_from(Message)) == 0
        assert db.scalar(select(func.count()).select_from(MessageAttempt)) == 0
        assert db.get(User, "owner") is not None
        tombstone = db.get(Conversation, cid)
        assert tombstone.deleted_at is not None and tombstone.last_language is None


@pytest.mark.parametrize("status", ["failed", "cancelled", "interrupted"])
def test_terminal_partials(engine, status):
    cid = create(engine)
    with Session(engine) as db, db.begin():
        repo = ConversationRepository(db)
        a = accept(repo, cid)
        result = repo.write_assistant_internal(
            "owner",
            cid,
            attempt_id=a.id,
            lease_token=a.lease_token,
            content="partial",
            status=status,
            error_code="STREAM_FAILED",
        )
        assert result.status == a.state == status
        assert result.content == "partial"
        with pytest.raises(AttemptConflict, match="ATTEMPT_TERMINAL"):
            accept(repo, cid)


def test_lease_and_rollback(engine):
    cid = create(engine)
    with pytest.raises(RuntimeError):
        with Session(engine) as db, db.begin():
            accept(ConversationRepository(db), cid)
            raise RuntimeError()
    with Session(engine) as db, db.begin():
        repo = ConversationRepository(db)
        assert repo.list_messages("owner", cid).items == []
        a = accept(repo, cid)
        a.created_at = utcnow() - timedelta(seconds=120)
        a.lease_expires_at = utcnow() - timedelta(seconds=1)
        db.flush()
        with pytest.raises(AttemptConflict, match="STALE_WORKER"):
            repo.write_assistant_internal(
                "owner",
                cid,
                attempt_id=a.id,
                lease_token=a.lease_token,
                content="stale",
            )


@pytest.mark.parametrize("attempts", [False, True])
def test_concurrent_workers(engine, attempts):
    cid = create(engine)
    barrier = Barrier(4)

    def worker(index):
        barrier.wait(timeout=10)
        try:
            with Session(engine) as db, db.begin():
                repo = ConversationRepository(db)
                if attempts:
                    accept(repo, cid, str(index))
                else:
                    repo.append_user("owner", cid, str(index))
            return "ok"
        except AttemptConflict as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(worker, range(4)))
    with Session(engine) as db, db.begin():
        rows = ConversationRepository(db).list_messages("owner", cid).items
        if attempts:
            assert results.count("ok") == 1
            assert results.count("CONVERSATION_BUSY") == 3
            assert [r.sequence for r in rows] == [1, 2]
        else:
            assert results == ["ok"] * 4
            assert [r.sequence for r in rows] == [1, 2, 3, 4]


@pytest.mark.parametrize(
    "invalid",
    [
        dict(sequence=0),
        dict(role="system"),
        dict(status="invalid"),
        dict(status="streaming"),
        dict(response_language="en"),
        dict(language_source="invalid"),
    ],
)
def test_database_message_constraints(engine, invalid):
    cid = create(engine)
    values = dict(
        id="invalid",
        conversation_id=cid,
        sequence=1,
        role="user",
        content="text",
        status="completed",
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    values.update(invalid)
    with pytest.raises(IntegrityError):
        with Session(engine) as db, db.begin():
            db.add(Message(**values))
            db.flush()


def test_unique_sequence_and_cascade(engine):
    cid = create(engine)
    with Session(engine) as db, db.begin():
        ConversationRepository(db).append_user("owner", cid, "text")
    with pytest.raises(IntegrityError):
        with Session(engine) as db, db.begin():
            db.add(
                Message(
                    id="duplicate",
                    conversation_id=cid,
                    sequence=1,
                    role="user",
                    content="text",
                    status="completed",
                    created_at=utcnow(),
                    updated_at=utcnow(),
                )
            )
            db.flush()
    with Session(engine) as db, db.begin():
        db.execute(text("DELETE FROM conversations WHERE id=:id"), {"id": cid})
        assert db.scalar(select(func.count()).select_from(Message)) == 0
        assert db.get(User, "owner") is not None


def test_migration_preserves_auth(auth_database):
    config = Config("alembic.ini")
    command.downgrade(config, "base")
    command.upgrade(config, "0001")
    engine = create_engine(auth_database)
    try:
        with Session(engine) as db, db.begin():
            db.add(User(id="preserved", preferred_locale="en"))
            db.flush()
            db.add(
                BrowserSession(
                    secret_hash="hash",
                    user_id="preserved",
                    csrf_token="csrf",
                    created_at=1,
                    last_used_at=1,
                    idle_expires_at=2,
                    absolute_expires_at=3,
                    revoked=False,
                )
            )
        command.upgrade(config, "head")
        with Session(engine) as db:
            assert db.get(User, "preserved").preferred_locale == "en"
            assert db.get(BrowserSession, "hash").csrf_token == "csrf"
        assert {"messages", "conversations", "message_attempts"} <= set(
            inspect(engine).get_table_names()
        )
        command.downgrade(config, "0001")
        with Session(engine) as db:
            assert db.get(User, "preserved") is not None
            assert db.get(BrowserSession, "hash") is not None
        command.upgrade(config, "head")
    finally:
        engine.dispose()


def test_concurrent_same_key(engine):
    cid = create(engine)
    barrier = Barrier(2)

    def worker(_):
        barrier.wait(timeout=10)
        try:
            with Session(engine) as db, db.begin():
                accept(ConversationRepository(db), cid)
            return "accepted"
        except AttemptConflict as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(worker, range(2))) == ["MESSAGE_IN_PROGRESS", "accepted"]
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(MessageAttempt)) == 1
        assert db.scalar(select(func.count()).select_from(Message)) == 2


def test_delete_serializes_against_acceptance(engine):
    cid = create(engine)
    barrier = Barrier(2)

    def deleting():
        with Session(engine) as db, db.begin():
            repo = ConversationRepository(db)
            repo._owned("owner", cid, lock=True)
            barrier.wait(timeout=10)
            repo.delete("owner", cid)

    def accepting():
        barrier.wait(timeout=10)
        with Session(engine) as db, db.begin():
            with pytest.raises(ConversationNotFound):
                accept(ConversationRepository(db), cid)

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(deleting), pool.submit(accepting)
        a.result(timeout=15)
        b.result(timeout=15)
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(Message)) == 0
        assert db.scalar(select(func.count()).select_from(MessageAttempt)) == 0


def test_stale_identity_map_cannot_bypass_delete(engine):
    cid = create(engine)
    with Session(engine, expire_on_commit=False) as stale:
        repo = ConversationRepository(stale)
        old = repo.get("owner", cid)
        stale.commit()
        with Session(engine) as db, db.begin():
            ConversationRepository(db).delete("owner", cid)
        assert old.deleted_at is None
        with pytest.raises(ConversationNotFound):
            repo.append_user("owner", cid, "stale")
        stale.rollback()


def test_database_failure_rolls_back_pair(engine):
    cid = create(engine)
    with pytest.raises(IntegrityError):
        with Session(engine) as db, db.begin():
            accept(ConversationRepository(db), cid)
            db.add(User(id="owner", preferred_locale="en"))
            db.flush()
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(Message)) == 0
        assert db.scalar(select(func.count()).select_from(MessageAttempt)) == 0


def test_attempt_database_uniqueness(engine):
    cid = create(engine)
    with Session(engine) as db, db.begin():
        original = accept(ConversationRepository(db), cid)
        first_id = original.id
    # Both constraints must hold even for writers bypassing the repository lock.
    for duplicate_key in (False, True):
        with pytest.raises(IntegrityError):
            with Session(engine) as db, db.begin():
                original = db.get(MessageAttempt, first_id)
                if duplicate_key:
                    original.state = "completed"
                    db.flush()
                stamp = utcnow()
                for index, role in enumerate(("user", "assistant"), 3):
                    db.add(
                        Message(
                            id=f"extra{index}",
                            conversation_id=cid,
                            sequence=index,
                            role=role,
                            content="",
                            status="completed",
                            created_at=stamp,
                            updated_at=stamp,
                        )
                    )
                db.flush()
                db.add(
                    MessageAttempt(
                        id="duplicate",
                        conversation_id=cid,
                        client_message_id="key" if duplicate_key else "different",
                        request_fingerprint="a" * 64,
                        user_message_id="extra3",
                        assistant_message_id="extra4",
                        state="active",
                        lease_token="token",
                        lease_expires_at=stamp + timedelta(seconds=60),
                        created_at=stamp,
                        updated_at=stamp,
                    )
                )
                db.flush()


def test_reused_session_reads_current_history(engine):
    cid = create(engine)
    with Session(engine) as db, db.begin():
        a = accept(ConversationRepository(db), cid)
        aid, token = a.id, a.lease_token
    with Session(engine, expire_on_commit=False) as stale:
        repo = ConversationRepository(stale)
        message = repo.list_messages("owner", cid).items[-1]
        assert message.status == "streaming"
        stale.commit()
        with Session(engine) as db, db.begin():
            ConversationRepository(db).write_assistant_internal(
                "owner",
                cid,
                attempt_id=aid,
                lease_token=token,
                content="done",
                status="completed",
            )
        assert repo.list_messages("owner", cid).items[-1].status == "completed"
        assert accept(repo, cid).state == "completed"
        stale.rollback()


@pytest.mark.parametrize("content", ["", "   ", "x" * 8001, "bad\x00text", "\ud800"])
def test_invalid_content_does_not_accept_turn(engine, content):
    cid = create(engine)
    with Session(engine) as db, db.begin():
        repo = ConversationRepository(db)
        with pytest.raises(ValueError):
            repo.append_user("owner", cid, content)
        assert repo.list_messages("owner", cid).items == []


def test_last_language_uses_selected_response_language(engine):
    cid = create(engine)
    with Session(engine) as db, db.begin():
        repo = ConversationRepository(db)
        accept(repo, cid, detected_language="fr-CA")
    with Session(engine) as db, db.begin():
        repo = ConversationRepository(db)
        assert repo.get("owner", cid).last_language == "pt-BR"
        user, assistant = repo.list_messages("owner", cid).items
        assert user.detected_language == "fr-CA"
        assert assistant.response_language == "pt-BR"


def test_standalone_user_append_preserves_selected_language(engine):
    cid = create(engine)
    with Session(engine) as db, db.begin():
        repo = ConversationRepository(db)
        attempt = accept(repo, cid)
        repo.write_assistant_internal(
            "owner",
            cid,
            attempt_id=attempt.id,
            lease_token=attempt.lease_token,
            content="done",
            status="completed",
        )
        repo.append_user("owner", cid, "Bonjour", detected_language="fr-CA")
    with Session(engine) as db:
        assert ConversationRepository(db).get("owner", cid).last_language == "pt-BR"


@pytest.mark.parametrize(
    "status", ["streaming", "completed", "failed", "cancelled", "interrupted"]
)
@pytest.mark.parametrize(
    "byte_length", [MAX_ASSISTANT_CONTENT_BYTES - 1, MAX_ASSISTANT_CONTENT_BYTES]
)
def test_assistant_content_byte_boundary(engine, status, byte_length):
    cid = create(engine)
    # Four-byte characters verify the limit measures encoded bytes, not code points.
    content = "😀" * (byte_length // 4) + "x" * (byte_length % 4)
    assert len(content.encode("utf-8")) == byte_length
    with Session(engine) as db, db.begin():
        repo = ConversationRepository(db)
        attempt = accept(repo, cid)
        repo.write_assistant_internal(
            "owner",
            cid,
            attempt_id=attempt.id,
            lease_token=attempt.lease_token,
            content=content,
            status=status,
        )
    with Session(engine) as db, db.begin():
        message = ConversationRepository(db).list_messages("owner", cid).items[-1]
        assert message.content == content
        assert message.status == status


@pytest.mark.parametrize(
    "status", ["streaming", "completed", "failed", "cancelled", "interrupted"]
)
@pytest.mark.parametrize("multibyte", [False, True])
def test_oversize_assistant_content_preserves_checkpoint(engine, status, multibyte):
    cid = create(engine)
    suffix = (
        "😀" * (MAX_ASSISTANT_CONTENT_BYTES // 4)
        if multibyte
        else "x" * MAX_ASSISTANT_CONTENT_BYTES
    )
    content = "x" + suffix
    assert len(content.encode("utf-8")) == MAX_ASSISTANT_CONTENT_BYTES + 1
    with Session(engine) as db, db.begin():
        repo = ConversationRepository(db)
        attempt = accept(repo, cid)
        aid, token = attempt.id, attempt.lease_token
        repo.write_assistant_internal(
            "owner",
            cid,
            attempt_id=aid,
            lease_token=token,
            content="x",
        )
        before = repo.get("owner", cid).updated_at
        checkpoint_time = attempt.updated_at
    # Catch validation inside the transaction and commit to verify no mutation leaks.
    with Session(engine) as db, db.begin():
        with pytest.raises(
            ValueError, match="assistant content exceeds UTF-8 byte limit"
        ):
            ConversationRepository(db).write_assistant_internal(
                "owner",
                cid,
                attempt_id=aid,
                lease_token=token,
                content=content,
                status=status,
            )
    with Session(engine) as db, db.begin():
        repo = ConversationRepository(db)
        message = repo.list_messages("owner", cid).items[-1]
        assert message.content == "x" and message.status == "streaming"
        assert message.updated_at == checkpoint_time
        assert repo.get("owner", cid).updated_at == before
        attempt = db.get(MessageAttempt, aid)
        assert attempt.state == "active" and attempt.updated_at == checkpoint_time


def test_completed_attempt_replay_reuses_pair_without_new_rows(engine):
    cid = create(engine)
    with Session(engine) as db, db.begin():
        repo = ConversationRepository(db)
        attempt = accept(repo, cid)
        original_ids = (
            attempt.id,
            attempt.user_message_id,
            attempt.assistant_message_id,
        )
        repo.write_assistant_internal(
            "owner",
            cid,
            attempt_id=attempt.id,
            lease_token=attempt.lease_token,
            content="Original response",
            status="completed",
        )
        completed_at = attempt.updated_at
        conversation_updated_at = repo.get("owner", cid).updated_at
    with Session(engine) as db, db.begin():
        repo = ConversationRepository(db)
        replay = accept(repo, cid)
        assert (
            replay.id,
            replay.user_message_id,
            replay.assistant_message_id,
        ) == original_ids
        assert replay.state == "completed" and replay.updated_at == completed_at
        assert repo.get("owner", cid).updated_at == conversation_updated_at
        messages = repo.list_messages("owner", cid).items
        assert [message.id for message in messages] == list(original_ids[1:])
        assert messages[-1].content == "Original response"
        assert db.scalar(select(func.count()).select_from(Message)) == 2
        assert db.scalar(select(func.count()).select_from(MessageAttempt)) == 1
