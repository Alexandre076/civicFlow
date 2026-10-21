# POST streaming contract — v1 (planned)

Design only for [Epic #2](https://github.com/Alexandre076/civicFlow/issues/2).
The application has no streaming implementation today. Follow the DTOs,
limits, ownership and errors in [API contracts](api-contracts.md) and session/
CSRF rules in [authentication](authentication.md). Replies are deterministic
mocks; no LLM, LangGraph, MCP or real municipal protocol is required.

## Request and transport

Use browser `fetch()` POST with credentials, JSON and a readable response body.
Do not use EventSource or WebSockets. A representative request is:

```http
POST /api/v1/conversations/conv_456/messages HTTP/1.1
Content-Type: application/json
Accept: text/event-stream
X-CSRF-Token: <session-bound-token>
Cookie: __Host-civicflow_session=<opaque>

{"content":"Existe um buraco na minha rua.","client_message_id":"client_789"}
```

Validate authentication, CSRF/origin, ownership, limits and idempotency before
committing the accepted turn and returning 200. Pre-stream failures are the
normal JSON errors; check status/content type before parsing SSE.

```http
HTTP/1.1 200 OK
Content-Type: text/event-stream; charset=utf-8
Cache-Control: no-store, no-transform
X-Accel-Buffering: no
```

Disable proxy buffering for this route; `X-Accel-Buffering` is an advisory header
where supported. Do not require HTTP/1-only Connection/Transfer-Encoding headers.
Flush events promptly, optionally sending SSE comment heartbeats (`: keepalive`)
without treating them as text. Exact heartbeat and timeout limits are open for
#24. Use UTF-8 decoding across arbitrary byte chunks, then parse SSE records
separated by blank lines, handling LF/CRLF and multi-line `data` according to the
[SSE wire standard](https://html.spec.whatwg.org/multipage/server-sent-events.html).
Network chunks are not event boundaries. Ignore comments; ignore unknown event
names for forward compatibility. Invalid known payloads terminate local parsing
and trigger history reconciliation, not successful completion.

## Event schemas

Every `data` is one JSON object. All events include `conversation_id`,
`client_message_id`, `message_id` (assistant ID). Required event-specific fields:

| Event | Additional fields | Meaning |
| --- | --- | --- |
| `message.started` | `user_message_id`, `status: "streaming"`, `response_language`, `language_source`, `replayed` (boolean) | Durable pair accepted; IDs bind optimistic UI to history |
| `message.delta` | `content` (string) | Append exactly this incremental text |
| `message.completed` | `message` (full completed assistant Message DTO) | Successful terminal event; replace accumulated text with authoritative DTO |
| `message.error` | `error: {code, retryable}`, `status` (terminal assistant status or null) | Failed terminal event; reconcile persisted history |

`response_language` and `language_source` follow the API metadata contract.
On replay `message.started.status` is `completed` instead of `streaming`.
`message.error.status` is `failed`, `cancelled`, `interrupted`, or null if the
resource is no longer available. Error payloads exclude sensitive diagnostics.
There is at most one terminal event and no events after it. No SSE `id` or
Last-Event-ID resume protocol is provided in v1; idempotent POST/history handle
recovery. A complete new stream emits started, zero or more deltas, then a terminal
event if transport permits. Zero deltas is valid for a completed replay.

```text
event: message.started
data: {"conversation_id":"conv_456","client_message_id":"client_789","message_id":"msg_124","user_message_id":"msg_123","status":"streaming","response_language":"pt-BR","language_source":"message","replayed":false}

event: message.delta
data: {"conversation_id":"conv_456","client_message_id":"client_789","message_id":"msg_124","content":"Entendi. "}

event: message.delta
data: {"conversation_id":"conv_456","client_message_id":"client_789","message_id":"msg_124","content":"Onde fica o buraco?"}

event: message.completed
data: {"conversation_id":"conv_456","client_message_id":"client_789","message_id":"msg_124","message":{"id":"msg_124","conversation_id":"conv_456","sequence":2,"role":"assistant","content":"Entendi. Onde fica o buraco?","created_at":"2026-10-20T16:00:00Z","updated_at":"2026-10-20T16:00:01Z","status":"completed","client_message_id":"client_789","detected_language":null,"response_language":"pt-BR","language_source":"message","error_code":null}}

```

## Durable lifecycle and concurrency

Accept a new turn atomically: lock/serialize the owned conversation, reserve the
idempotency key/fingerprint, insert the completed user message and an empty
`streaming` assistant message with consecutive sequence numbers, select language
metadata, then commit before `message.started`. Failure before this transaction
commits creates neither message. At most one active attempt per conversation;
a different key while busy returns 409 `CONVERSATION_BUSY`.

Persist partial assistant text before emitting corresponding deltas. Batching
is allowed but emitted text must already be durable; history can be ahead of a
client that disconnects. The checkpoint batch size is an implementation choice
for #24. Successful generation atomically commits full content, `completed`
status and attempt result before emitting `message.completed`. A completed
message remains completed even if the final event is lost.

The assistant transitions only from `streaming` to `completed`, `failed`,
`cancelled` or `interrupted`. Terminal messages never silently resume or change
status. Preserve user text and last durable assistant partial on failure.
`failed` means processing error; `cancelled` means an observed client disconnect/
abort; `interrupted` means timeout, worker loss or session expiry/revocation.
The backend cannot reliably distinguish an AbortController cancellation from
network disconnect, so both may appear as `cancelled`. History always exposes
status/error code, including empty partials, rather than a plausible complete reply.

Use a durable worker lease/finite deadline plus reconciliation so crashed workers
cannot leave `streaming` rows forever. Expired leases transition to `interrupted`
with `STREAM_INTERRUPTED`; lease durations and reconciliation scheduling are
open implementation decisions for #24. Fence stale workers from later writes.
Database failures must not result in a false completion event; recover from the
last committed state. Deletion is the exception: the resource becomes inaccessible
and workers stop without recreating it, per [deletion semantics](api-contracts.md#ownership-and-deletion).

## Idempotency and retries

Scope keys by authenticated user and conversation. Bind each key to the exact
validated content and persist its association to both message IDs with a unique
constraint; competing workers must not accept duplicates. Do not expire keys
while the conversation is retained. Authenticate and check ownership even on
replays; a deleted conversation returns 404, never a cached response.

| Same key request | Result |
| --- | --- |
| Different content | 409 `IDEMPOTENCY_CONFLICT`; no writes |
| Same content, active attempt | 409 `MESSAGE_IN_PROGRESS`, `Retry-After` seconds; no second stream/generation |
| Same content, completed attempt | 200 SSE started (`replayed=true`, status `completed`), then completed with stored DTO; no deltas or new records |
| Same content, failed/cancelled/interrupted | 409 `ATTEMPT_TERMINAL`; inspect history; no regeneration |

On an uncertain network result, retain the original key, reconcile paginated
history and, if needed, resend the same body/key. This may accept the turn if
it never committed, return an active conflict, or replay completion. Never
silently generate a new key on a network retry. After an incomplete terminal
attempt, the citizen may explicitly send again with a new key: this creates a
new visible user/assistant pair, preserving the partial prior turn. V1 has no
regenerate-in-place endpoint. Pending/conflict retries use bounded backoff and
Retry-After; validation/authorization/conflict errors do not trigger blind loops.
`retryable` on SSE errors means recovery may be attempted after reconciliation,
not permission to generate a second response with the old key.

## Cancellation, expiry and error recovery

The client uses AbortController to stop a request, marks the local reply pending
reconciliation and reads history when connected. No separate cancellation route
exists. Abort may race with completion: history is authoritative. The server
stops on observed disconnect and persists the terminal partial unless completion
already committed. Stream closure, HTTP 200 and receipt of some deltas are never
proof of completion; require `message.completed` or a completed history DTO.

Revalidate session revocation/expiry during generation before each durable batch
and final commit, also while idle via a bounded timer. A revocation fence prevents
post-logout writes. Exact recheck/idle timeout scheduling is open for #20/#24.
On expiry, stop, persist `interrupted` with `SESSION_EXPIRED`, emit an error if
possible and close. On logout/revocation use `SESSION_REVOKED`. The frontend clears
sensitive state and requests login for either code; after reauthentication it can
read retained history. No transparent unauthenticated continuation is allowed.

Post-200 error example:

```text
event: message.error
data: {"conversation_id":"conv_456","client_message_id":"client_789","message_id":"msg_124","error":{"code":"STREAM_FAILED","retryable":true},"status":"failed"}

```

Post-start codes include `STREAM_FAILED` (processing), `STREAM_INTERRUPTED`
(timeout/worker loss), `CLIENT_DISCONNECTED`, `SESSION_EXPIRED`, `SESSION_REVOKED`,
`CONVERSATION_NOT_FOUND`, `RATE_LIMITED` and `SERVICE_UNAVAILABLE`. Disconnect, session and deletion
codes (`CLIENT_DISCONNECTED`, `SESSION_EXPIRED`, `SESSION_REVOKED`,
`CONVERSATION_NOT_FOUND`) are not
automatically retried; transient processing/availability errors may be recoverable
through explicit resend after history review. `RATE_LIMITED` after initiation uses
`retryable=true` but requires backoff; thresholds remain open for #24.
Persist `CLIENT_DISCONNECTED` for observed disconnect/cancellation,
`STREAM_INTERRUPTED` for lease expiry/timeouts, and the corresponding failure
code for other terminal states. Never emit `message.error` after a committed
completion. Application errors cannot change the already-sent HTTP status. If the connection
or persistence layer fails, even `message.error` may be impossible: close, mark
local content uncertain and reconcile. Unknown error codes use a localized generic
message. Do not show server diagnostics as UI copy or log report content.
