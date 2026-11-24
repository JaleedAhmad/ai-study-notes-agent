# Batch 5B-3: verified embedding and index completion

## Actual paths and corrected failures

`src/core/rag.py:get_gemini_embedding` still constructs a Gemini SDK client for
each call and requests `gemini-embedding-001`. No provider/fallback order changes.
It now requires exactly one nonempty finite numeric vector in the response.
`chunk_text` retains the 1000-character/200-overlap splitter configuration.
Importing rag still creates `./chroma_db`; the offline sandbox confines that
existing side effect to its temporary workspace. No live imports were used for
manual inspection or validation.

The persistent path is `main_content.render_main_content` -> extraction validation
-> `rag.embed_and_store_document` -> chunking -> Gemini embeddings ->
`user_libraries.add` -> explicit readback -> `IndexReceipt`. Previously individual
embedding errors were printed and skipped; zero vectors returned `None`, partial
vectors could be added, and any matching document row bypassed indexing. The UI
accepted all these outcomes as success. The helper now raises `IndexingError` on
failure and returns a frozen receipt only for a fully verified revision. The UI
requires a receipt matching its user/document before advancing. Failed processing
stops before accepting combined source or allowing the Generate button to run.
A multi-file failure can leave earlier files indexed but cannot report complete
library success; retry verifies/reuses those files and attempts the failed file.

The long-document path in `pipeline_router.route_and_process` previously repeated
the skip-on-error loop in an ephemeral Chroma collection, then called the model
even when indexing or context retrieval failed. It now embeds every required
chunk, verifies insertion, requires a dimension-compatible query vector and
nonempty context drawn from indexed chunks, and only then calls the same model
orchestrator. The temporary collection is deleted in a finally block. Direct
context routing, the 120000-character threshold, splitter settings, retrieval
limit of five, provider order and prompts' instructions remain unchanged. This
is completion validation, not improved document coverage or retrieval ranking.

The persistent query caller is `main_content.render_chat_section`. Its existing
owner predicate remains `where={"user_id": user_id}`. Before returning excerpts,
rag now verifies each candidate's entire revision. Incomplete/legacy revisions
are omitted; storage/query failures still return empty context. Existing chat
behavior for empty retrieval is unchanged: it can use its initialized source
context without library excerpts. No invalid revision text is returned as source.
No claim is made that this fixes all chat grounding/fallback concerns.

## Completion and identity contract

`src/core/indexing.py` has no UI/provider initialization. It validates splitter
outputs, filters only whitespace chunks, rejects zero usable chunks, embeds all
required chunks, checks finite numeric values and consistent nonzero dimensions,
and verifies persistence. A write is successful only when readback contains the
exact requested IDs, documents, metadata and vectors (float32 rounding tolerated).
Readback failures, missing rows and corrupt payloads fail explicitly. No
transactional guarantees are assumed for `collection.add`.

Every write attempt has a fresh UUID revision. IDs are `<revision>_chunk_<n>`;
metadata includes user/document/filename, revision, chunk ordinal/count, raw-source
SHA-256, ordered-chunk SHA-256 and vector dimension. Duplicate detection scopes
reads to both user and document, verifies all expected revision rows and checks
source/chunk hashes and filename. A single existing row is never a completion
receipt. Filtering and identity guards are actual production calls; test fakes
apply only requested predicates and do not supply implicit ownership validation.

A valid existing document ID with changed source, filename or chunk layout is
refused, preserving the existing index. Intentional replacement needs a new
document ID; this batch does not redesign upload IDs or choose active versions.
No existing valid revision is deleted during failed writes. Different users can
use the same document ID without sharing completion receipts.

## Partial writes, retries and legacy rows

All embeddings are prepared before insertion, so a provider failure writes
nothing. On insertion/readback failure, deletion is attempted for only that
attempt's fresh IDs. Cleanup is best effort, without a transaction or durable
cleanup queue. A cleanup exception is reported as unconfirmed cleanup, preserving
the private original cause. Process termination, failed or silent cleanup can
leave orphan rows. Their incomplete revision cannot pass the full count, ID,
ordered-content, metadata and dimension checks used by duplicate detection and
retrieval. Retry uses fresh IDs; no destructive broad document delete is used.
A fully persisted revision whose response was lost can be reused only after full
verification. Hashes verify content consistency, not provider semantic accuracy
or cryptographic authorization against an attacker controlling the vector store.

Existing legacy rows lack completion evidence. They remain untouched but cannot
be considered verified retrieval sources or duplicate receipts. Reindexing an
available document creates a verifiable revision alongside them. This entails
embedding cost when run with real services; no automatic bulk reindex is included.
Existing upload caching can bypass reprocessing of old source; Batch 5B-4 must
handle identity/invalidation separately. This batch does not load private data,
rewrite historical rows, or guarantee a cached legacy session has an index.

## Offline checks

Run only:

```text
python -I -S -B tests/run_offline.py
```

The suite executes actual production functions with synthetic splitter/provider
outputs and `offline.fake_vectors.MemoryCollection`. The fake stores raw rows,
implements caller-supplied filters, supports partial insertion and injected errors,
and provides no completion, ownership, transaction, durability or semantic-search
guarantees of its own. Existing upload tests now use raw readback-capable storage
instead of a get mock permanently returning no rows. The vector ownership test's
fixture now creates verified records through the actual indexer for both users;
its original ownership/filter assertions remain unchanged. OAuth and all other
security assertions are preserved.

New tests cover legitimate verified persistence, empty/malformed chunks, invalid
provider structures/vectors, dimensions, partial embeddings, insertion exceptions,
partial writes, missing/corrupt readback, unordered readback, float32 tolerance,
cleanup failure, incomplete duplicate detection, legacy rows, cross-user document
IDs, safe retries, replacement refusal, preservation of existing valid rows,
verified retrieval and generation eligibility. Ephemeral tests require complete
indexing and nonempty verified context before model invocation and check collection
cleanup. Upload tests check absent/mismatched receipts, blocked generation,
partial-write rejection and multi-file retry.

Final suite: **289 tests, 267 passing, 22 ordinary failures, zero errors**.
42 tests were added (37 dedicated indexing/router tests and five UI tests).
EXTRACT-28 now passes. The 20 known OAuth failures and EXTRACT-29/30 (cache and
saved-session source identity) remain ordinary failures. No unexpected sandbox
violations; temporary test workspace removed. No security assertions were
weakened, removed or marked expected-failure.

## Unverified Chroma and runtime behavior

No real Chroma, SDK, database, network or private document integration was run;
no dependencies were installed. Real-version support for get(include=embeddings),
float storage/readback, metadata filters, deletion, persistence/restart, collection
schema compatibility and actual failure semantics still need isolated integration
tests. Existing collection dimensions may reject a new provider vector size;
such writes now fail rather than claiming completion. Receipt/readback is not a
cross-operation transaction or a snapshot: concurrent mutation can invalidate a
revision after verification. No distributed compare-and-swap/uniqueness lock is
introduced; concurrent writers can create multiple complete revisions. No claim
of exactly-once indexing across workers is made.

Readback increases local I/O, memory and latency. Full revision checks are cached
only within one query call. Old orphan/legacy rows can occupy top-five candidate
slots and reduce usable recall; they are not returned, and cleanup/ranking
redesign is deferred. Embeddings remain prepared in memory and no new page/chunk,
API-cost, provider-timeout or global resource budget is introduced. Temporary
collection deletion can itself fail. These limitations do not permit partial
indexes to be declared complete. Real kill/restart and concurrent failure behavior
is not established by the synthetic tests.

## Next scope

Batch 5B-4 should address upload fingerprints (bytes plus relevant processing
identity), same-name replacement, saved-session/upload separation and invalidation
of source/notes/chat/index receipts on document changes. Keep long-document
coverage/ranking and model routing as later work. This batch stops without any
commit or deployment. Existing OAuth remains insecure; development is not a
production release.

## Batch 5B-4 integration

Filename equality is no longer required for duplicate reuse: filenames are display
labels, while owner/content/chunk verification is unchanged. Upload index document
IDs now bind owner, original byte fingerprint, format, processing version and
extracted text, preserving valid prior OCR variants without overwrite. Upload
chat passes an explicit selected-document filter; saved chat does not infer old
vector IDs from filenames. See [document-state contracts](DOCUMENT_STATE.md).
All 5B-3 completion tests pass. Current suite: 328 total, 308 passing, 20 known
OAuth failures. No Chroma engine, model order, schema or deployment change.
