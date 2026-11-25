# Batch 5B-4: content identity and selected-source contracts

## Root causes and actual boundaries

The old main UI compared only filenames and disabled its reset when a saved
session ID was selected. Consequently same-name replacement reused old source,
and a new upload could generate from saved-session text. Random library IDs plus
filenames also prevented reliable cross-rerun content reuse. Source text, notes,
SDK chat state and saved-session IDs had no shared selection binding. Loading a
saved record did not reset the existing uploader widget.

The corrected path is:

1. `main_content.render_main_content` obtains the validated current user and
   checks the study state's owner. A principal change clears study data, rotates
   the uploader key and stops before reprocessing a lingering upload.
2. `document_state.snapshot` reads the complete uploaded bytes independently of
   cursor position, preserving that cursor. Each extraction receives a fresh
   BytesIO, never the original mutable upload object. SHA-256 is computed from
   bytes. The snapshot is local to that render; uploaded objects/bytes are not
   retained in the custom extraction cache.
3. The extraction key combines processing version, authenticated owner, byte
   digest and normalized filename suffix (format). The bundle selection combines
   those ordered byte/format identities and owner. Names are display labels,
   never the authority for content identity. Ordering/multiplicity are explicit.
4. Extraction caches contain validated text plus its digest, keyed by the
   extraction identity. The current bundle owns the cache; a real bundle switch
   discards it. Cached text is revalidated and digest checked on reuse. Aliases
   within one render share the same extraction result. No format sniffing or
   cross-format cache equivalence is assumed.
5. The Chroma document ID additionally incorporates the extracted-text digest.
   This keeps a changed but valid OCR transcription from overwriting an earlier
   verified index for the same bytes. Chroma's existing metadata source_hash is
   the extracted-text hash, not the original file-byte hash. These are distinct
   contracts. The revision and IndexReceipt contracts from 5B-3 are preserved.
6. Every render with uploads calls the actual indexer, even for cached extraction.
   It revalidates full persistent revisions before reusing them. Cached receipts
   never bypass readback. Current receipts must match owner and derived document
   ID. Reused indexes retain their original filename metadata; the UI displays
   the current alias. No historical metadata is overwritten merely to rename.
7. Ready source is published only after all required files pass. While processing,
   ready_source is cleared, so interruption cannot authorize old cached success.
   Failures clear dependent state and stop before generation. Retry can reuse
   fully verified vectors written by earlier files without deleting them.

The processing-version constant is a manual cache compatibility boundary. Future
changes to extraction/chunking/index semantics must deliberately bump it when
older cached results should not be reused. It is not an automatically generated
hash of runtime dependencies.

## Selection and dependent state

The state helper is UI independent. `source_selection` is either an upload bundle
or an explicitly loaded saved session. `ready_source` binds the selected identity
to the exact assembled source text. Notes/history bind to that token; chat binds
to both the token and the selected session ID. A saved-session ID also has a
session_source association with that source token. Merely replacing the ID cannot
redirect current source/history to another record, even for the same owner.

Changing upload bytes, format or bundle order clears source, notes, history, SDK
chat, exports, generation labels, index receipts and current saved-session
association. Saved records and vectors are not deleted. Removing the last upload
also deselects its active study state. Identical reruns retain legitimate notes
and SDK context, reuse extraction and reverify indexing. Renaming an otherwise
identical file reuses extraction/indexing; its assembled filename header changes,
so dependent outputs and saved-session association are conservatively invalidated.
Two distinct documents with the same filename have distinct IDs. The same bytes
under different owners/formats have distinct extraction/index identities.

## Saved records and legacy compatibility

Sidebar loading still uses a fresh owner-scoped `database.get_session` call.
Before attempting a load it clears prior study state and rotates the uploader's
widget key. An unavailable/foreign record cannot silently leave the previous
source active. A valid record restores only its source, notes and a copied history,
then initializes chat with that source/history. Reopening fetches fresh persisted
values. New Session resets selection/widget state without deleting records.
Existing explicit Delete behavior retains its ownership checks; clearing UI state
is not a new deletion operation. Existing UUIDs and foreign keys are unchanged.

Saved rows do not contain original uploaded bytes or their fingerprints. Their
identity therefore uses authenticated owner, owned session ID and SHA-256 of the
stored extracted text. No byte fingerprint is fabricated or backfilled from a
filename. No schema change is required. An unbound pre-upgrade in-memory session
must be reopened; an old filename-only upload cache is reprocessed. Saved text
still must satisfy basic extraction validation, but cannot retroactively prove
old PDF page coverage or extraction fidelity without original documents.

## Generation, chat and persistence

Generation validates the ready selection before routing, rechecks it after the
model response and before saving, and passes the captured source to create_session.
Notes are tagged with the source token. The returned saved ID is associated with
that token before chat/history persistence can use it. Authentication and existing
owner checks are unchanged. Session creation is not made transactional/idempotent
with model generation by this batch; repeated explicit Generate clicks can still
create new saved sessions.

Chat refuses unbound/mismatched source or notes. A stale SDK object is rebuilt;
history from another token is discarded. Source/session changes during a reply
prevent that answer from being displayed/appended/saved to the new session. The
original user question may already have been saved to its original owned session.

Upload chat retrieval now passes only the current receipt document IDs along with
the existing owner filter. Ranking, top-five selection and vector validation are
unchanged. Saved sessions have no trustworthy mapping to old vector IDs, so chat
uses their initialized stored-source context and history; it does not search the
whole library or guess indexes by filename. The optional rag API default remains
library-scoped for existing non-UI callers. Empty explicit selection makes no
vector/provider call. Existing model fallback/context limitations remain outside
this batch.

## Offline evidence and test adaptations

Run `python -I -S -B tests/run_offline.py`.

Result: **328 tests, 308 passing, 20 unchanged ordinary OAuth failures, zero errors**.
Both original EXTRACT-29 (same-name changed bytes) and EXTRACT-30 (saved/upload
mismatch) pass without changes to their assertions. The 39 added tests exercise
byte/hash/cursor contracts, format/version/owner distinctions, same-content
reruns, renamed aliases, duplicate names, per-render aliases, re-extraction
variation, failed processing/readback, corrupt cache, stale receipts, interruptions,
source switches, persistence and chat boundaries, and actual sidebar reopening.

Raw parser/provider outputs and the partial-write-capable vector fake remain
isolated. The vector fake only applies caller-supplied filters, now including
$in; it does not infer identity, authorize owners, or validate completion. Saved
sidebar tests use the existing synthetic database fake and actual production
ownership filtering. No actual database or provider is called.

The existing header-only cache case now requires re-extraction of actual uploaded
bytes rather than asserting the deliberately deferred filename-cache behavior.
It asserts that only freshly valid source reaches generation. Separate invalid
cache tests verify fail-closed handling. The valid saved-notes control initializes
an explicitly owned saved selection instead of unbound legacy state; its viewing
assertions are retained. UI fixture setup was separated from test methods for
reuse without duplicate discovery. No OAuth/security assertion was changed or
marked expected-failure. All PDF/extraction/indexing contracts remain covered.

## Integration and performance limits

HTTP/browser Streamlit behavior was not tested. Rotating uploader keys and local
rerun/interruption handling are verified at the Python-call level only; actual
widget resets, session cleanup, reconnects and multi-tab behavior need isolated
browser validation. No cross-worker state sharing, transaction or cross-operation
Chroma snapshot is claimed. Real Chroma support for the owner-plus-document $in
filter and restart/deletion/readback behavior needs isolated integration testing.

Every uploaded byte is hashed on each rerun. Snapshot/BytesIO processing can add
transient memory proportional to upload size, while Streamlit retains its own
upload buffers. Cache stores current extraction strings and assembled source,
not a persistent archive of original bytes. Text hashes add linear work; full
index readback adds I/O/memory. No new upload-size budget or dependencies are added.
A cold re-extraction may use paid OCR/embedding in normal application operation;
none occurred here. Different valid OCR output can leave multiple preserved
index revisions, while selected-document filtering limits chat to the current one.

No remote database, private document, real credential, provider or deployed
application was accessed. Existing insecure OAuth is unchanged. This batch is
uncommitted and does not authorize deployment or later implementation work.
