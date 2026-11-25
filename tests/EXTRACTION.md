# Extraction contracts — Batches 5A and 5B-1

The historical Batch 5A investigation below describes production commit
`15f13472f4c6dd8e7c6c97dd7461701dcb28d1ca`; its source-line references and failure
counts are the pre-fix evidence. Batch 5A changed tests/documentation only.
The final section records the scoped Batch 5B-1 implementation and current counts.
Neither batch changes OAuth/authentication/database contracts, dependencies or
deployment. Existing OAuth is still insecure and is not approved for production.

## Active pipeline, from actual source

| Boundary | Source | Current behavior |
| --- | --- | --- |
| UI entry | `app.py:45-61`, `src/ui/main_content.py:17-21` | Validated server-held owner, then upload widget. Widget suffix list is pdf/docx/pptx/txt/png/jpg; this is not application content validation. |
| Upload cache | `src/ui/main_content.py:23-35` | Cache identity is filename list only, reset only when no saved session is selected. New contents with the same names are ignored; selected saved sessions suppress reset even with different uploads. |
| Dispatch | `src/utils/extractor.py:9-20,43-73` | Seeks to start, dispatches by lowercased filename suffix. No magic/MIME or decoded-content validation. Helper also supports md/jpeg, absent from widget list. Unsupported suffix returns empty string. |
| Native PDF | `src/utils/extractor.py:20-30` | Concatenates nonempty page text. A zero-page result is empty success-shaped text. Whitespace is not validated. Uses average characters per page, not per-page completeness. |
| Scanned/mixed PDF | `src/utils/extractor.py:30-42` | If average stripped native text is below 50 characters/page, renders the entire PDF with pdf2image, clears native text and OCRs returned images. No returned-page count/coverage check. Otherwise blank/image-only pages may be silently omitted. |
| PDF OCR source format | `src/utils/extractor.py:40` | Appends literal backslash-n sequences and page headers even for empty/error OCR text. Headers alone are not evidence of extracted content. |
| DOCX/PPTX | `src/utils/extractor.py:43-57` | DOCX paragraphs only, not tables; PPTX text-frame shapes only. Table-only DOCX or blank slides can become empty strings. Full layout, figures and other structured-content coverage is not tracked. |
| Plain text | `src/utils/extractor.py:59-63` | UTF-8 with errors=replace; invalid bytes silently change. No empty/whitespace/NUL validation. |
| Image/handwriting | `src/utils/extractor.py:65-70`, `src/core/vision_client.py:9-15` | Image.open, RGB conversion, same vision prompt for images/scans/handwriting. Actual handwriting accuracy was not tested. |
| OCR cascade | `src/core/vision_client.py:20-34,36-70` | Gemini configured as gemini-2.5-flash, then Groq llama-3.2-11b-vision-preview on exception/missing client. Empty/whitespace/non-string Gemini text can stop fallback; Groq content is returned without validation. No Hugging Face OCR branch. Configured model names do not establish live availability. |
| OCR exhaustion | `src/core/vision_client.py:72-76` | Returns an ordinary string beginning `[Error: Vision extraction failed...` rather than a failure signal. Image/PDF callers accept it as content. |
| Extraction exception | `src/utils/extractor.py:75-77` | Logs any ordinary exception and returns empty string. Parser failures, renderer errors, unsupported and empty files cannot be distinguished reliably by the caller. |
| UI ingestion | `src/ui/main_content.py:42-66` | Exception handler only catches exceptions that escape extractor. Otherwise adds document header, calls indexer, commits combined text and unconditionally reports “Library Indexed Successfully”. No content/coverage/index result check. |
| Persistent indexing | `src/core/rag.py:39-75` | Authenticated owner check remains active. Creates/gets collection before content validation, skips whitespace chunks, swallows each embedding error and returns no completion receipt. Empty text causes no vector add, but UI still reports success. OCR error text can reach embedding/add. |
| Generation | `src/ui/main_content.py:68-94`, `src/core/pipeline_router.py:16-41` | Upload presence and button click permit routing without valid source. Header-only combined text is nonempty and reaches direct generation. Router also directly accepts empty/whitespace text. |
| Notes/session saving | `src/ui/main_content.py:87-114` | A successful model result sets notes and initializes chat, then attempts owner-scoped session creation. A synthetic end-to-end test shows header-only text can reach this persistence boundary. No real notes or database rows were written. |
| Saved-session semantics | `src/ui/sidebar.py:22-31,49-65` | Start New Session explicitly clears source/output; history selection owner-scopes the read and restores saved text. Viewing saved notes without a new upload remains legitimate and has a passing control. |

`src/utils/pdf_reader.py:3-10` is another native PDF helper, but no active production
caller was found by source search. Its behavior must not be substituted for the
active universal extractor. The active long-document route at
`src/core/pipeline_router.py:43-111` embeds/query-selects snippets and may send empty
context after retrieval failure; broader coverage/model routing fixes remain later
work. This batch tests only the empty raw-source eligibility boundary there.

## Correctness invariants and API assumptions

1. Supported, readable, nonempty documents retain their valid text. Legitimate
   text discussing errors remains valid; never blacklist arbitrary “Error” strings.
2. Unsupported/malformed/empty/whitespace-only inputs must have an explicit failure
   signal. These tests propose `ExtractionError(ValueError)` while retaining the
   current string return for success. They require ValueError at extraction/OCR
   failure boundaries, not a new production error class in this batch.
3. OCR tries the next existing provider on invalid/empty primary content, then
   fails explicitly on exhaustion. The provider layer owns this distinction;
   consumers must not guess failures from arbitrary source text prefixes.
4. No content-free document is indexed or made generation-eligible. A filename
   or page header cannot satisfy this invariant. Empty chunks are already skipped
   by RAG; this does not make the ingestion operation successful.
5. Requested document/page coverage must be complete or explicitly rejected as
   incomplete. Do not silently discard parser failures, missing rendered pages,
   mixed scanned pages or OCR outages. Intentionally blank pages versus unreadable
   pages need an approved conservative policy; no real blank-page detector is
   validated here. No table/layout support expansion is implied by rejecting a
   currently unreadable table-only document.
6. UI success requires confirmed extraction and indexing completion. Exceptions,
   partial uploads and zero successful embeddings must not produce success.
7. Changed uploaded bytes invalidate cached source even with the same filename.
   Changing uploads while viewing a saved session must reprocess the new source
   or explicitly block/explain generation, never generate old source silently.
8. Owner UUID validation and all existing legitimate saved-session/password
   operations remain intact. This batch never alters authentication semantics.

The two router-invalid-input tests accept only an explicit ValueError denial or
a failure result, and require that the model is never invoked. Other exception
types surface; a provider invocation still fails the assertion. UI stop/rerun is
modeled as BaseException control flow; only that control signal is caught by the
test render helper. Unexpected exceptions remain test errors.

## Historical Batch 5A failing regression mapping

All cases are in `offline/test_extraction.py`, named with prefix `test_` below.
Failures are ordinary assertions, not xfails, skips or assertions that defects are
correct behavior. Distinct tests exercise overlapping root causes at real source
boundaries; 33 failures do not mean 33 unrelated implementation defects.

| Contract | Test suffix | Boundary/evidence |
| --- | --- | --- |
| EXTRACT-01 | zero_page_pdf_is_explicitly_rejected | extractor:20-42 returns empty text for zero parser pages. |
| EXTRACT-02 | empty_text_is_explicitly_rejected | extractor:59-63 empty bytes accepted. |
| EXTRACT-03 | whitespace_text_is_explicitly_rejected | extractor:59-63 whitespace accepted. |
| EXTRACT-04 | unsupported_file_is_explicitly_rejected | extractor:72-73 silently returns empty text. |
| EXTRACT-05 | malformed_pdf_error_reaches_caller | extractor:21,75-77 swallows synthetic parser error. |
| EXTRACT-06 | malformed_docx_error_reaches_caller | extractor:44,75-77 swallows parser error. |
| EXTRACT-07 | malformed_pptx_error_reaches_caller | extractor:51,75-77 swallows parser error. |
| EXTRACT-08 | malformed_image_error_reaches_caller | extractor:66,75-77 swallows image parser error. |
| EXTRACT-09 | whitespace_pdf_and_no_rendered_pages_is_rejected | extractor:30-42 accepts empty fallback. |
| EXTRACT-10 | table_only_docx_cannot_silently_succeed_empty | extractor:44-48 ignores table-only content and returns empty. |
| EXTRACT-11 | blank_pptx_is_explicitly_rejected | extractor:51-57 blank slides accepted. |
| EXTRACT-12 | invalid_utf8_is_not_silently_replaced | extractor:62 uses replacement decoding. |
| EXTRACT-13 | binary_nul_text_is_not_valid_study_content | extractor:59-63 accepts binary-looking bytes as text by suffix. |
| EXTRACT-14 | mixed_pdf_does_not_skip_image_page_due_to_average | extractor:30 whole-document average hides second page requiring OCR. |
| EXTRACT-15 | partial_pdf_parser_failure_is_not_empty_success | extractor:23-26,75-77 discards already extracted first page on second-page exception. |
| EXTRACT-16 | missing_rendered_page_is_not_complete_success | extractor:35-42 ignores renderer returning fewer pages than requested document. |
| EXTRACT-17 | pdf_with_one_ocr_failure_is_not_complete_success | extractor:39-40 appends OCR failure string beside valid first page. |
| EXTRACT-18 | total_ocr_failure_raises_instead_of_returning_source | vision_client:72-76 error string is a normal result. |
| EXTRACT-19 | empty_primary_ocr_uses_valid_fallback | vision_client:30 empty text returns before Groq. |
| EXTRACT-20 | nonstring_primary_ocr_uses_valid_fallback | vision_client:30 truthy non-text response accepted. |
| EXTRACT-21 | blank_fallback_ocr_is_rejected | vision_client:66 whitespace response accepted. |
| EXTRACT-22 | image_extractor_does_not_return_ocr_error_as_content | extractor:69-70 directly returns real vision helper's error string. |
| EXTRACT-23 | empty_extraction_never_reaches_indexing | main_content:54-60 calls actual RAG helper for empty text. |
| EXTRACT-24 | blank_extraction_does_not_report_library_success | RAG skips whitespace/no vector add, main_content:66 still declares success. |
| EXTRACT-25 | failed_extraction_does_not_enable_generation | main_content:65-84 routes filename headers without content. |
| EXTRACT-26 | real_ocr_failure_does_not_become_an_indexed_document | actual vision failure string reaches actual RAG's add boundary. |
| EXTRACT-27 | partially_extracted_upload_batch_is_not_reported_complete | good first file plus corrupt second file still produces whole-library success. |
| EXTRACT-28 | total_embedding_failure_is_not_reported_complete | rag:66-75 swallows outage; main_content:66 declares success with zero vectors. |
| EXTRACT-29 | same_filename_replacement_does_not_reuse_stale_text | main_content:24-35 checks names only; changed bytes never extracted. |
| EXTRACT-30 | loaded_session_cannot_generate_old_source_for_different_upload | main_content:25 suppresses reset; generation receives saved source for a new upload. Reprocess or explicit block is acceptable. |
| EXTRACT-31 | empty_source_cannot_reach_note_persistence | real extractor/RAG/router path reaches mocked model, chat-init and session-create boundaries with header-only source. |
| EXTRACT-32 | empty_source_does_not_reach_model | pipeline_router:26-41 forwards empty raw input. |
| EXTRACT-33 | whitespace_source_does_not_reach_model | pipeline_router:26-41 forwards whitespace raw input. |

Passing controls: UTF-8 text and cursor rewind; Markdown; text containing error
messages; native PDF without OCR; image-only PDF with valid per-page OCR; DOCX
paragraphs; PPTX text frames; image RGB conversion; valid Gemini; Gemini exception
to valid Groq; valid UI extraction/indexing; truly raised extraction error stopping
the existing UI; different filenames re-extracting with no saved session; saved
notes remaining viewable without uploads; valid raw source reaching generation.

## Offline isolation and results

Command: `python -I -S -B tests/run_offline.py`.

| Cases | Passing | Ordinary failures | Errors |
| --- | ---: | ---: | ---: |
| Previous baseline | 137 | 20 known OAuth failures | 0 |
| Batch 5A (48 new) | 15 | 33 extraction/ingestion contracts | 0 |
| Complete suite (205) | 152 | 53 (20 OAuth + 33 extraction) | 0 |

Exit 1 deliberately preserves defect evidence. No expected-failure decorators or
exclusion lists were added. Zero unexpected sandbox violations; temporary workspace
removed. All previous 157 cases remain unchanged. No new dependency installed.

The real universal extractor, vision helper, RAG helper, router and main-content
function execute. Parser/renderer outputs are raw synthetic pages/paragraphs/images;
the renderer honors requested page ranges but does not select missing pages unless
production requests them. OCR endpoint methods are explicitly mocked. Collection
get/add and embedding endpoints are raw mocks with no empty-text/coverage/ownership
validation injected. The real RAG skip/catch behavior executes unchanged.

Most UI cases stop at a mocked generation boundary that returns failure, preventing
unrelated chat/persistence work. One end-to-end case instead runs the real router
with an unconditional synthetic model success, then observes a mocked persistence
call. Neither mock validates the source for production. The real current-user UUID
guard executes; tests never replace it. Unrelated exporter/UI-rendering sections
are stubbed to avoid packages/network/file outputs outside the tested path.

Import-time hazards remain: extractor imports vision -> llm_client -> dotenv and
global provider clients (`src/core/llm_client.py:9-25`), the UI imports another
Gemini client through agent (`src/core/agent.py:15-19`), and RAG creates chroma_db
on import (`src/core/rag.py:13-14`). Existing Sandbox installs SDK/dotenv fakes,
clears inherited environment, blocks network/processes, and confines artifacts to
temporary working directories. No new harness allowances were required.

What is NOT verified: actual PDF/DOCX/PPTX parser grammar or SDK compatibility,
real Poppler rasterization/page counts, image/handwriting/OCR accuracy, actual
model availability, browser upload behavior or real vector/database writes. The
zero-page/fewer-rendered-page cases are defensive dependency-output contracts,
not claims that those libraries routinely produce those responses. The app's
suffix dispatch and swallowing behavior are verified against supplied synthetic
outputs; no real corrupt or private document was opened.

## Smallest proposed Batch 5B fixes — not implemented

1. Keep successful text return values. Introduce typed ExtractionError(ValueError)
   and common string/nonempty validation; reject unsupported types, undecodable
   UTF-8 and binary NUL payloads explicitly. Preserve a parser-error cause privately;
   display a safe error/status to the user. Do not return an empty string for every
   error. Encoding support beyond UTF-8 requires an explicit policy, not silent
   replacement decoding.
2. Validate each existing OCR provider's text result. Blank/malformed primary
   results may use the existing Groq fallback; exhaustion raises instead of becoming
   source text. Do not identify failures by blacklisting arbitrary study text.
3. Assess PDF coverage per page, retain valid native text and request OCR only
   where needed; check rendered coverage and reject unconfirmed partial results.
   Decide how positively identified blank pages are represented. No full parser
   rewrite, new OCR provider or document-layout feature expansion is required.
4. Validate content before headers/indexing and again before generation. Keep
   filename/page headers separate from eligibility. Extend the UI's existing error
   boundary to ingestion/indexing; don't commit source state or show complete
   success on failure. An explicit index completion result or raised failure is
   needed for zero/partial embedding failures; preserve the legitimate already-
   indexed path. Per-document/vector rollback and retry/idempotency need their own
   review, not an assumption that a UI failure undoes previously written vectors.
5. Invalidate cache using uploaded content identity, not filename alone. For a
   selected historical session, reprocess explicitly or require Start New Session
   before generating against a different upload. Preserve saved-note viewing and
   all ownership checks. No schema/authentication change is needed.

These are several related boundaries, not one catch-all regex or a full rewrite.
If Batch 5B is limited to extraction signaling first, keep the remaining UI,
index-receipt and cache tests red and report them separately. Never suppress them
to claim full remediation. Deeper indexing atomicity, long-document sampling,
deletion/retention and conversation/model fallback remain subsequent workstreams.

## Future reusable core, without refactoring now

- File-like input dispatch and parser adapters can operate on bytes/name and
  injected parsers without Streamlit or Supabase. They currently reach global
  clients transitively through vision; they are not pure/offline services today.
- Content validation, upload fingerprints and page-coverage checks are candidates
  for pure functions with explicit results/errors and no session state.
- OCR orchestration can later accept injected provider interfaces; adapters own
  network/client lifecycle while the core owns validation/fallback policy.
- RAG chunking is a reusable transformation, but currently shares a module with
  Streamlit, persistent storage and import-time directory creation. Separate it
  only after correctness contracts stabilize; do not extract an agent skill from
  the current implicit global/session behavior.

No production fixes or reusable-service extraction were included in Batch 5A.

## Implemented Batch 5B-1

Successful calls still return text strings. Failure now raises the shared
`src.utils.extraction_validation.ExtractionError`, a ValueError subclass with a
safe display message. This small leaf module imports only re; it does not import
Streamlit, Supabase, dotenv, parsers or providers and creates no clients/files.

`validate_extracted_text` returns the original text unchanged after checking type,
non-whitespace content and NUL absence. BOMs do not count as content. Generated
document/page headers, including the old escaped-newline page wrappers, cannot
establish content alone. The exact retired application OCR failure sentinel is
rejected when it is the entire remaining source; quoting it inside an explanatory
study note remains valid. This is not semantic validation or a blacklist of
ordinary error words. It cannot prove a model transcription is accurate or
classify every possible natural-language refusal.

The universal extractor validates every successful format branch. UTF-8 decoding
is now strict; non-UTF-8 documents must be converted or use a separately approved
encoding policy. Unsupported files and empty output raise explicitly. Third-party
parser errors are wrapped with a safe message, preserving their cause privately;
callers must not display chained exceptions. The UI no longer prints the extraction
traceback or provider error details. All new user-facing failure messages are
constant and contain no parser exception or document text.

OCR uses the same Gemini and Groq clients/models/order. Invalid structures,
empty/whitespace/non-text results, metadata-only results and a sole bracketed
`[Error: ...]` provider envelope trigger the existing fallback. Exhaustion raises
ExtractionError, never an error-string source. Text that discusses an error and
also contains real explanatory content remains valid. Parser/image serialization
exceptions also fail explicitly. No provider, pricing policy, timeout policy or
SDK initialization architecture was changed.

PDF OCR validates each returned page's text before adding page headers; generated
headers now contain real newlines. The existing average-density threshold, whole-
PDF rendering and absence of rendered-page coverage checks are deliberately
unchanged. Short text has no new minimum-length requirement; the existing low-
density PDF heuristic can still request OCR, pending the PDF coverage batch.

The active UI validates per-file text before document headers/indexing, catches
extraction failures and stops, and checks cached source before generating. The
router also validates raw input before model/vector operations. Valid loaded
source remains usable; cache identity and saved-session/upload mismatch behavior
are not repaired. The indexer's return contract and exception swallowing are
unchanged. A valid first upload may already have vectors when a later file fails;
this batch stops completion/generation but does not roll those vectors back.

### Regression results

Command: `python -I -S -B tests/run_offline.py`.

| Cases | Passing | Ordinary failures | Errors |
| --- | ---: | ---: | ---: |
| Pre-5A baseline (157) | 137 | 20 unchanged OAuth failures | 0 |
| Original 5A extraction cases (48) | 43 | 5 scheduled defects | 0 |
| Added 5B-1 checks (20) | 20 | 0 | 0 |
| Complete suite (225) | 200 | 25 | 0 |

28 of the original 33 extraction assertions now pass: EXTRACT-01–13, 15, 17–27
and 31–33. None of the original 48 assertions was deleted, weakened or marked
expected-failure. The original valid-document controls all still pass.

Remaining ordinary failures, preserved as evidence:

- EXTRACT-14: mixed-PDF scanned page skipped by document-average threshold.
- EXTRACT-16: fewer rendered pages accepted without a coverage check.
- EXTRACT-28: total embedding failure still reported as indexed success.
- EXTRACT-29: same-filename changed bytes still reuse cached source.
- EXTRACT-30: a selected session can still generate valid-but-stale source for a
  different upload. Only known invalid source is blocked by this batch.

The 20 new checks cover the independent validation module, one-character text/
DOCX/PPTX/OCR pages, StringIO and invalid read results, metadata-only and cached
header-only source, safe parser/provider diagnostics, malformed OCR structures,
missing providers and error envelopes. Synthetic responses remain raw mocks;
they do not enforce validation for production. All assertions still execute the
actual processing functions under the unchanged offline isolation harness.

Exit 1 preserves the 25 unmet contracts. No unexpected sandbox violations, test
errors or leftover temporary workspace. No real provider, parser integration,
browser, database or vector-store operation was exercised, and no dependency was
installed. Real codec/model accuracy and live deployment behavior remain unverified.

### Next proposed batch

Keep Batch 5B-2 focused on PDF page coverage: retain valid native page text,
identify pages needing OCR without a document-wide average, validate rendered
page counts/ranges and make incomplete coverage explicit. Agree a conservative
blank-page policy and verify it offline. Do not add providers or change authentication.
Index completion receipts, partial-index retries/cleanup, cache fingerprints and
saved-session/upload identity remain later scheduled work; no such fixes are
included here. No Batch 5B-2/5B-3 implementation or reusable-service extraction
has begun, and nothing has been committed or deployed.


## Batch 5B-2: page-level PDF coverage

The page processor in `src/utils/extractor.py` replaces the document-wide average
and whole-document OCR replacement. Every parsed page is considered in source
order. Any non-whitespace native text is retained (including one-character study
notes); length alone no longer triggers OCR. Native text must pass the existing
validation contract. A native parser/structure error rejects the document rather
than discarding a page or silently substituting a partial result.

Pages without usable native text require OCR unless structurally blank. Pages
with XObject resources (images **or forms**), inline-image/Do/sh operations, or
annotations also require OCR, even if native text exists. This is conservative:
unused inherited resources and non-text annotations may trigger unnecessary OCR.
A full-page OCR result supplements native text; exact repeated lines, ignoring
surrounding whitespace, are omitted from the OCR supplement. Native text remains
verbatim. Different OCR line wrapping/spelling can still duplicate information;
fuzzy removal risks deleting additional material and is deliberately avoided.
Native-only PDFs now also receive original page-number headers. The successful
return interface is still one string; no caller needs a new result object.

### Blank pages and incomplete coverage

A page may be omitted as structurally blank only if `get_contents()` is available,
the content stream is absent or its parsed operations are empty, and there are no
annotation/XObject/inline-image/Do/sh indications. Unknown structure, whitespace
native extraction, painted/white scanned pages, empty OCR, or a missing image is
**not** proof of intentional blankness. Such pages require valid OCR or reject
the document. Consequently a visually blank scan may be refused. Blank pages do
not contribute headers or study text, and original page numbering is retained
across them. An entirely blank PDF still fails the no-content contract.

Each required OCR page requests exactly its original one-based page range and
requires exactly one returned image. Missing or extra images, invalid OCR output,
provider exhaustion, native-parser errors or structure-parser errors reject the
entire document. No partial string is returned. The safe exception identifies the
page number without source content or diagnostics; the UI displays this typed
ExtractionError message and never its private cause. The existing generic message
remains for unexpected exceptions. UI regression checks show failed PDFs reach
neither indexing nor generation, while complete mixed PDFs reach the unchanged
index boundary. This is not a library-wide rollback: prior files may already have
vectors, and existing cache reuse can bypass re-extraction until its own batch.

Structural coverage does **not** prove OCR semantic completeness, reading order
inside a page, or diagram/formula accuracy. Native text can itself be incomplete
or corrupted but syntactically valid. Vector-only graphics alongside native text
without the listed indicators are not comprehensively classified. A provider may
omit information while returning plausible text. No page-coverage certificate is
stored or inferred merely from successful OCR or another page's text.

### Resource policy and remaining integration risks

Rendering is sequential, one required page at a time, with a longest-edge size of
1600 pixels (aspect ratio retained), one Poppler worker and a 60-second Poppler
render timeout. Rendered images are closed in a finally block before advancing.
PDF bytes are loaded lazily once, only if OCR is needed. Native-only PDFs avoid
rendering/provider calls. No new dependencies or provider-routing changes.

These bounds do not limit parser memory, the full PDF byte buffer, accumulated
text, total page count, total document duration, provider latency or total API
cost. Repeated single-page Poppler calls incur startup/metadata overhead. There
is no new overall OCR deadline or cancellation mechanism. Small print may be
less legible at the raster bound. A practical page/upload budget, provider
timeouts and real synthetic PDF/Poppler/OCR integration tests still need separate
approval/evidence; they were not silently introduced as document-size rejection.

### Validation

Command: `python -I -S -B tests/run_offline.py`.

- Complete suite: **247 tests, 224 passing, 23 ordinary failures, zero errors**.
- The 20 OAuth failures are unchanged; no assertions are weakened or hidden.
- EXTRACT-14 (mixed PDF omission) and EXTRACT-16 (missing renders) now pass.
- All PDF extraction assertions pass, including original valid-document controls.
- 22 new tests pass: short native pages, alternating coverage/order, same-page
  image/native merging, exact deduplication, annotations/forms/inline images,
  structural blanks and all-blank rejection, unknown/painted pages, extra/missing
  renders, render timeouts, invalid native output, OCR and structure failures,
  image release and rendering bounds, and UI safe failure/success boundaries.
- One existing legitimate scanned-PDF test now checks two exact single-page
  render requests instead of one bulk render call. Its content and OCR-count
  assertions remain intact; this reflects the intentionally changed contract.
- Remaining extraction-related failures are EXTRACT-28 (index completion),
  EXTRACT-29 (same-filename cache identity) and EXTRACT-30 (stale saved-session
  source). Their implementations and assertions remain unchanged.
- Zero unexpected sandbox violations; temporary test workspace removed.

These are orchestration tests with synthetic page objects and raw renderer/OCR
outputs. No real PDF parser, Poppler execution, provider, database, browser,
private document or external service was exercised. Actual codec compatibility,
OCR accuracy and resource limits are unverified. OAuth remains insecure; this is
not release approval. Batch 5B-2 stops here, uncommitted and undeployed.

## Batch 5B-3 follow-up

EXTRACT-28 now passes with verified index receipts and stopped generation after
index failure. The suite is 289 tests: 267 passing, 20 known OAuth failures and
only EXTRACT-29/30 still failing. See [index completion contracts](INDEXING.md) for
partial-write, retry, legacy-data and Chroma integration limitations. PDF and
extraction implementations and their assertions are unchanged in this batch.

## Batch 5B-4 follow-up

Both EXTRACT-29/30 now pass through owner-bound byte fingerprints and explicit
saved/upload selection. The suite is 328 tests: 308 passing and only the same
20 OAuth failures. See [document-state contracts](DOCUMENT_STATE.md). Extraction,
PDF coverage and indexing security assertions remain covered; no providers ran.
