# Conversation storage

Issue #21 extends the existing authentication foundation with `conversations`,
`messages` and `message_attempts`. This is reusable storage only: #23 owns HTTP
routes, public DTOs and signed cursors; #24 owns SSE, generation, lease recovery
and session revalidation. There are no assistant mocks or new HTTP routes yet.

## Schema and migration

`models.py` shares the authentication Base. Alembic revision `0002` follows
`0001`; it only creates the three conversation tables and their indexes.
From `backend/`, with `CIVICFLOW_DATABASE_URL` configured:

```bash
uv sync --locked
uv run alembic upgrade head
uv run alembic current
```

The additive upgrade preserves authentication users, identities and sessions.
`uv run alembic downgrade 0001` removes conversation data only; use it solely
when intentionally discarding that data. Integration tests cover clean install,
upgrade with existing users/sessions and downgrade without changing those records.

New timestamps use PostgreSQL `TIMESTAMP WITH TIME ZONE` and timezone-aware Python
UTC datetimes. Public DTOs in #23 can serialize them with Pydantic to RFC 3339 UTC
(`Z` or `+00:00`). Authentication retains its existing Unix-second columns.
Language metadata uses nullable language tags, independent of UI locales.

A conversation references its user with `ON DELETE RESTRICT`. Messages reference
conversations with `ON DELETE CASCADE`; attempts reference their conversation and
paired messages with `ON DELETE CASCADE`. Deleting a conversation never deletes a
user. Message sequence is positive, unique within a conversation and immutable
through repository operations. That unique B-tree also supports ascending history.
Checks enforce message roles/statuses, completed user messages and role-specific
nullable metadata. Attempts have unique `(conversation_id, client_message_id)`;
paired messages deliberately may share the same client ID. A partial unique
index permits only one `active` attempt per conversation.

## Ownership, transactions and concurrency

`ConversationRepository` takes an explicit authenticated `user_id` on every public
read/write. Callers derive it from the BFF session, never request JSON. Unknown,
foreign and deleted IDs all raise `ConversationNotFound`; #23 maps that to 404.
No raw ID lookup authorizes message or attempt access. Internal assistant/attempt
methods are privileged entry points for #24; never bind their arguments directly
to public request bodies. The ordinary append operation always creates a completed
user message and accepts neither owner overrides, roles, IDs nor statuses.

The repository flushes but never commits. Use a caller-owned `Session.begin()`
transaction, or the shared request database dependency, and roll back on exceptions.
Accepting an attempt flushes a user/assistant pair and its fingerprint/lease record
in one transaction. No success response/event may precede commit. A failed flush
or commit requires rollback of the entire transaction, including both messages.

All writes lock the owned, visible conversation using `SELECT FOR UPDATE` before
reading sequence maxima, attempt state or the deletion fence. PostgreSQL's default
READ COMMITTED isolation serializes concurrent workers; allocate the next sequence
under that lock. Never bypass the repository or commit between lock and writes.
The unique sequence/idempotency/active-attempt constraints provide a second guard.
Operations on different conversations remain independent. Re-locking refreshes ORM
state so a reused session cannot ignore a tombstone or newer terminal state.
History also holds this lock while capturing its high-water and reading the page.

Accepted user turns update `updated_at` and available language metadata. Assistant
checkpoints preserve their durable content prefix without updating the conversation
timestamp. Terminal changes update the conversation timestamp/language and attempt
state atomically. Terminal messages cannot resume or change state.

An attempt persists SHA-256 of exact validated UTF-8 content, both message IDs,
state, random worker lease token, finite lease deadline and timestamps. Same-key
requests with changed content conflict; active/unsuccessful-terminal attempts
conflict; a completed attempt returns its durable record without new writes.
These are persistence outcomes, not replay HTTP/SSE behavior.

Checkpoint/final writes require the matching unexpired lease token and active
state, rechecking under the conversation lock. #24 must implement bounded lease
renewal/reconciliation and interrupt abandoned attempts, with token rotation or
terminal-state fencing under the same lock. No scheduler or recovery worker is
implemented here. #24 must also hold/revalidate its authentication session fence
before each durable batch/final commit (lock session before conversation consistently
with request mutations). The conversation lock alone does not authorize a revoked
session. Persist checkpoints before emitting deltas; commit terminal state before
emitting completion, as required by the streaming contract.

## Pagination

Conversation pages order by immutable `(created_at DESC, id DESC)` and use a partial
owner/order index excluding tombstones. `after` is an exclusive tuple; `high_water`
is the inclusive initial maximum tuple. Message pages order by `sequence ASC`,
with exclusive `after` and inclusive initial maximum sequence. Both return `items`,
`high_water` and `next_after`; page size is 1–100. No offset or recent-only cutoff.
New rows are excluded from an existing traversal, while existing rows show latest
state. #23 must encode/sign and validate cursor ownership/resource/bounds before
passing these internal primitives; they are not browser-facing cursor formats.

## Deletion and retention

Deletion takes the same conversation lock, removes attempts/messages physically
and sets `deleted_at` in one transaction. Only non-content tombstone identifiers,
owner and timestamps remain; language is cleared. Reads and all later writes deny
access. Repeated/foreign/unknown deletes share the same not-found result. IDs are
server-generated; callers cannot recreate a deleted ID. A stale worker must use
`write_assistant_internal`, which locks/rechecks the tombstone before every write;
it must stop on not-found and must never recreate content. A write committed before
deletion is removed by that deletion; a later write is denied.

Production retention, backup expiration and operational-log deletion policies
remain undecided and must be finalized before using real citizen reports. This
transaction does not erase backups immediately and makes no such guarantee.

## Validation

Run backend Ruff and pytest as described in the [backend guide](../backend/README.md).
Set `CIVICFLOW_TEST_DATABASE_URL` to a separate disposable PostgreSQL database; tests
truncate data and perform migration roundtrips. They need no Google credentials,
AI API calls or application server. Concurrency tests use independent PostgreSQL
transactions and threads, rather than SQLite or mocked locks.
