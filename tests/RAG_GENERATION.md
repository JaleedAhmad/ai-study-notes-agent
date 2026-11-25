# Batch 6A: long-document coverage and generation investigation

Investigation/tests only, against checkpoint
`cd415ace6068339773417694fcab84ad7aa38b51`. Production code is unchanged.
Source references below refer to that checkpoint. No real provider, vector
engine, private document, production record or deployed environment was used.

## Actual active notes pipeline

| Boundary | Actual implementation and consequence |
| --- | --- |
| Upload extraction/index identity | `src/ui/main_content.py:29-124` validates extraction and persistent index receipts before publishing ready source. Owner/content/format identity and source-token guards from Batch 5 remain active. |
| Generation request | `main_content.py:126-148` validates the selected source, constructs the generic tone/focus/length instruction, and calls `route_and_process` with `generate_content` as orchestrator. No chapter-specific query or source coverage requirement is passed. |
| Short routing | `src/core/pipeline_router.py:10,24-44`: <=120000 raw characters goes to one model call with all sanitized source inside user_content delimiters. Threshold is inclusive. No source slicing occurs on this path. |
| Long routing | `pipeline_router.py:48-65`: >120000 raw characters uses the 1000-character/200-overlap splitter, embeds **all** nonempty chunks through Gemini and verifies ephemeral Chroma insertion. This is a second index, separate from upload's persistent user_libraries. The chroma_client argument is ignored. |
| Context selection | `pipeline_router.py:66-74` embeds the generic note instruction and requests n_results=5. Actual similarity scores/order are delegated to Chroma; no explicit metric, chapter coverage, diversity, source-position metadata, reranking or coverage manifest is configured here. Only membership in the indexed chunk strings is checked. |
| Long prompt | `pipeline_router.py:76-90` joins returned chunk strings in returned rank order. No sorting, deduplication, stable citation labels or complete-document coverage validation. It returns the ordinary success tuple and strategy label from the single model result. |
| Model cascade | `src/core/llm_client.py:26-87`: Gemini gemini-2.5-flash -> Groq llama-3.3-70b-versatile -> Hugging Face meta-llama/Meta-Llama-3-70B-Instruct. Each exception advances to the next available provider; each provider receives the **same prompt**, not a reconstructed subset. HF has max_tokens=2048. |
| Output validation | `llm_client.py:44,60,77` returns success on readable response fields without checking nonempty string content, finish reasons, output completeness, grounding or citations. Malformed attribute structures can raise and trigger fallback; readable empty/invalid content does not. |
| Persistence | `main_content.py:150-185` checks the source token, assigns notes and creates chat, then calls database.create_session with the entire selected source and the returned notes. Source identity is protected; source **coverage by the model** and valid notes payload are not established. `src/database/database.py:91-102` still verifies ownership of the returned saved record. No database behavior was changed or queried. |
| Display | `main_content.py:205-218` displays Generated Study Notes and a routing/provider label. It does not show retrieved/required coverage. The app does not literally promise that every chapter was read; it also does not disclose sampled coverage or distinguish partial notes from normal success. |

The exported `STUDY_AGENT_PROMPT` in `src/core/prompts.py:1-24` is **not** used by
the active routed notes path. `src/core/agent.py:26-65` has a separate note helper
(Gemini -> Groq) but the current UI does not call it; importing it or the template
does not make its suggested format the actual generation contract.

## Confirmed coverage and grounding boundaries

The synthetic long fixture is 144 identifiable sections of exactly 900 characters,
129600 total. Its splitter mock supplies those section chunks directly; this is
not a test of installed LangChain splitting. Real production embedding/persistence
verification still executes with raw synthetic vectors and in-memory storage.
The raw fake returns the first five by default; that is **not** asserted to be
actual Chroma similarity behavior. Other tests inject tail, reversed and duplicate
rank results explicitly. No mock completes a missing section for production.

Every fixture section is indexed, but only five reach the model on the default
run: 4500 source characters, about **3.47%**, excluding prompt overhead. Middle
and final markers are absent. Another allowed rank result omits the beginning.
This proves source-delivery gaps for those responses, not which chapters a real
model/ranking would select. More generally, a top-five selection cannot cover
all of a document with more than five distinct required chunks merely because
all were successfully indexed. Real splitter overlap reduces unique coverage;
no production union-of-offsets calculation exists.

Using a generic study-guide instruction as a similarity query is question-oriented
sampling, not a comprehensive summarization procedure. An omitted section's
unique facts are unavailable to a source-grounded model on that invocation. It
might guess or use prior knowledge, but that is not evidence-based coverage.
The present code provides no missing-section accounting or partial-result status.

The router verifies that returned chunk text belongs to the source, so unknown
chunk content, empty retrieval, query failure and incomplete indexing already
block note generation. Those Batch 5 protections pass. However, membership alone
does not ensure complete coverage, unique chunks or original source order.
Page/document headers may survive inside chunks, but they are not a reliable
chunk-level citation/offset manifest. There is no generated-claim verifier.

Both direct and long prompts label source as untrusted data and remove literal
user_content delimiter strings from it. The instruction itself mentions the
opening tag in prose; tests count actual delimiter lines instead of incorrectly
counting that explanatory mention. This is a deterministic prompt boundary check,
not proof of prompt-injection resistance. The prompts say based on source/snippets
but do not explicitly require source-only evidence, uncertainty for missing facts,
or forbid invented source references. They use one user prompt rather than
separate system/developer roles. No real attack/model evaluation occurred.

## Context limits and provider response behavior

120000 is a raw-character threshold, not a token budget. Query/instruction length,
output reservation, tokenization, Unicode density and each fallback model's
context capacity are not budgeted. There is no explicit token count, generation
budget configuration, continuation policy or per-section generation loop. The
long path typically sends at most five 1000-character splitter outputs, despite
paying to embed all chunks. The direct path can include the full 120000 source
characters plus arbitrarily longer query/prompt overhead.

No actual provider context limits, model availability, prices, automatic SDK/server
truncation or deployment latency were checked. The source contains no input
truncation beyond intentional long-context selection and delimiter sanitization.
It cannot establish whether a particular real request would exceed a model limit.
The notes fallback preserves exactly the supplied prompt after exceptions; thus
it preserves any omissions **already present**, rather than restoring coverage.

Readable empty Gemini text prevents valid Groq fallback. None, whitespace or a
non-text tertiary payload can be returned with success=True. Synthetic Gemini
MAX_TOKENS and OpenAI-compatible length finish reasons are ignored. Their
representations are injected fixtures, not SDK compatibility tests; the current
code reads no finish-reason metadata at all. HF's explicit 2048-token output cap
makes termination handling especially relevant; it does not prove real responses
are always truncated. All-provider exceptions correctly return failure.

UI tests execute the actual source selection, indexer, router, generation hub
(where specified) and save **call boundary**. They demonstrate create_session is
attempted after sampled long generation, empty/whitespace notes or explicitly
truncated generation. The synthetic database spy does not prove what deployed
constraints would accept, or that such records actually exist remotely. Successful
short generation and explicit failure/empty-retrieval denials remain controls.

Chat is a distinct path, not evidence of note-generation coverage. Batch 5B-4
limits upload chat retrieval to selected document IDs; saved chat uses its stored
source. `agent.py:88-101` puts source/security rules in Gemini chat system_instruction.
`agent.py:109-122` builds Groq fallback from history and the latest user message,
without explicitly copying that system instruction. This is a separate context
preservation concern requiring its own tests/workstream, not a claimed fix or
new tested notes failure in this batch.

## Offline contracts and results

Run only `python -I -S -B tests/run_offline.py`.

| Group | New tests | Pass | Ordinary failures |
| --- | ---: | ---: | ---: |
| Coverage/prompt contracts | 17 | 8 | 9 |
| Provider responses/context | 12 | 5 | 7 |
| Actual UI persistence boundary | 8 | 4 | 4 |
| New Batch 6A total | 37 | 17 | 20 |
| Existing baseline | 328 | 308 | 20 OAuth |
| Complete suite | 365 | 325 | 40 |

No skipped/expected-failure cases. Exit 1 preserves ordinary failing assertions.
No unexpected sandbox violations, errors or leftover temporary test workspace.
All existing tests and the harness are unchanged. All paid/network/service methods
are mocked before imports, including global model initialization and dotenv.
Persistent Chroma import-time directory creation remains confined to test temp.

| Contract | Test name suffix in test_rag_generation.py | Source boundary / unmet rule |
| --- | --- | --- |
| RAG-01 | whole_document_generation_requires_every_required_section | router:67-90: all required sections must be delivered or complete generation refused |
| RAG-02 | middle_section_cannot_be_silently_omitted | router:67-90: middle-section coverage |
| RAG-03 | final_section_cannot_be_silently_omitted | router:67-90: final-section coverage |
| RAG-04 | first_section_cannot_be_silently_omitted_when_similarity_returns_tail | router:67-90: first-section coverage for a different allowed rank result |
| RAG-05 | sparse_retrieval_is_not_advertised_as_complete_generation | router:90: refuse ordinary success under unapproved partial-coverage policy |
| RAG-06 | rank_order_cannot_reverse_complete_source_order | router:74: restore source order even when a small source is fully retrieved |
| RAG-07 | duplicate_retrieval_cannot_multiply_same_source_passage | router:74: eliminate exact duplicate retrieved passages |
| RAG-08 | source_only_and_uncertainty_instructions_are_explicit | router:32-39,78-85: explicit grounding instructions (proposed prompt contract) |
| RAG-09 | unknown_explicit_source_reference_cannot_be_returned_as_valid_notes | router:40/86: proposed reference-ID integrity contract, demonstrated with fixture IDs only |
| RAG-10 | empty_gemini_text_uses_valid_existing_fallback | llm:44: empty text must not stop fallback |
| RAG-11 | none_gemini_text_cannot_succeed | llm:44: non-text must fail |
| RAG-12 | whitespace_groq_payload_cannot_succeed | llm:60: whitespace must fail |
| RAG-13 | nontext_hf_payload_cannot_succeed | llm:77: invalid type must fail |
| RAG-14 | gemini_max_tokens_completion_cannot_be_complete_success | llm:44: detect reported truncation |
| RAG-15 | groq_length_completion_cannot_be_complete_success | llm:60: detect reported truncation |
| RAG-16 | hf_length_completion_cannot_be_complete_success | llm:77: detect reported truncation |
| RAG-17 | partial_long_document_notes_are_not_saved_as_complete | UI:150-175: coverage eligibility before saving |
| RAG-18 | success_shaped_empty_notes_are_not_saved | UI:150-175: output eligibility before saving |
| RAG-19 | success_shaped_whitespace_notes_are_not_saved | UI:150-175: output eligibility before saving |
| RAG-20 | actual_truncated_provider_response_is_not_saved | real llm -> router -> UI: truncated-output eligibility before saving |

RAG-09 is **not** proof that a real model fabricated references. The source fixture
declares section_000, the response fixture cites section_999, and the router accepts
it. A future formal citation/result format must be approved before treating this
particular textual syntax as a production API. No regex or mock can generally
prove that free-form natural-language claims are entailed by source text. The
current success flag is not an existing coverage certificate; these red tests
establish the desired complete-study-guide contract rather than retroactively
asserting the old tuple documented such a guarantee.

The top-five characterization test deliberately records current behavior alongside
red completeness contracts; it must be revised when an approved coverage algorithm
replaces sampling. It is not a requirement to keep top-five note generation.
Boundary/valid/denial controls verify complete short context, inclusive raw threshold,
raw-only budgeting, all-chunk insertion, source delimiters, invalid/empty/failed
retrieval denial, exact prompt preservation across fallback and legitimate save.

## Minimum recommended Batch 6B decisions (not implemented)

1. Establish output eligibility first: require a nonempty string and acceptable
   provider completion metadata before success; treat explicit truncation as
   incomplete, not finished notes. Keep existing provider order and exact prompt
   preservation. Validate again at the UI persistence boundary. Define handling
   for unknown/absent finish metadata against actual supported SDK responses.
   No schema change is inherently required. A success boolean alone is inadequate
   for partial/incomplete output. Do not silently save unfinished notes.
2. Until complete coverage exists, the smallest safe option is to fail closed for
   oversized whole-document study guides with a clear reason. Keep similarity
   retrieval for question answering, not the authority for complete notes.
   This adds no API cost and preserves short-document routing; it temporarily
   reduces long-document functionality rather than misrepresenting coverage.
3. To restore comprehensive long-document processing, partition selected source
   in original order into budgeted batches with stable source IDs and offsets.
   Count coverage over required source intervals/sections (accounting for overlap),
   not top-k hits or model-declared IDs. Send every required interval to some batch.
   Preserve document/page/section provenance where available. Reserve instruction
   and output tokens; use verified provider-specific context limits and a common
   safe fallback budget, or reject a provider that cannot fit the same context.
4. Generate bounded section notes, then a budgeted synthesis. If all section notes
   do not fit, use a bounded-fan-in hierarchy instead of silently dropping them.
   Only all successful batch results plus a valid final synthesis authorize final
   persistence. Failed batches must remain incomplete; retry/reuse must bind to
   owner/source/version/batch identity. Initial recovery can be session-local with
   no database migration; durable resumability is a separate design decision.
5. Add explicit source-only/insufficient-evidence prompt rules and preserve the
   existing untrusted-data boundary. If citations are adopted, provide an actual
   source-ID manifest and validate references against it. This verifies reference
   existence, not semantic entailment. Review structured formatting/templates
   only after determining which prompt is actually active.

Direct full-source calls remain a lower-latency alternative **when** the entire
request and output reserve fit every allowed fallback. Merely raising the raw
character threshold is not a verified solution. Coverage-aware batching is more
calls/latency but deterministic source delivery. For N budgeted batches, a simple
plan needs N section calls plus synthesis; a hierarchy adds synthesis levels.
Exact tokens/costs are unmeasured. Reuse validated extraction; embeddings for
whole-document note batching are not inherently necessary. Do not redesign the
already protected indexer to solve a summarization-coverage problem.

Passing all source-delivery checks still cannot prove final notes mention every
important concept. Compression can lose detail at each stage. Use deterministic
fixture facts/references as acceptance aids and later authorized real-model
quality evaluation for semantic accuracy, not claims of quality from mocks.

## Reusable core opportunities, without extraction/refactoring now

- Pure source identity, validation and index completion helpers from Batch 5 are
  already separable; retain their owner/source contracts in any future service.
- Source-manifest construction, ordered batching, token/output budgeting, coverage
  accounting, grounded prompt construction and generation-result validation can
  become UI-independent Python functions with injected provider adapters.
- Provider exception fallback currently preserves a string prompt; retain this
  invariant while normalizing completion status instead of rewriting all SDKs.
- Source-aware result/provenance objects can later support CLI or agent skills.
  Keep Streamlit rendering and Supabase persistence as adapters, not requirements
  of the generation algorithm. Do not copy the unused prompt as though it were
  the active generation policy, and do not package the present sampling behavior.

No Batch 6B implementation, provider calls, dependency changes, commits, branch
changes or deployment occurred. Existing OAuth remains insecure.

## Implemented Batch 6B-1: result validation and temporary eligibility

The preceding investigation is historical evidence at cd415ac. Batch 6B-1 changes
only the active result/eligibility boundaries; ordered batching, semantic grounding,
source-reference verification and hierarchy remain unimplemented.

### Result contract and provider adapters

`src/utils/generation_validation.py` is UI/SDK independent. `GenerationError`
messages are safe for display. Non-string, empty/whitespace/BOM-only and NUL
payloads fail, as do reserved application failure strings, sole bracketed error
envelopes and serialized top-level JSON error envelopes. Ordinary notes discussing
errors remain valid. This is not a semantic classifier: arbitrary free-form
refusals/error prose or unsupported factual claims cannot generally be recognized.

`GenerationText` is a str subclass preserving the old tuple interfaces and text
content, with completion_status either reported_finished or unknown. A recognized
STOP/stop finish reason records provider-reported normal termination. Enum names
and qualified string representations are normalized. Any other explicit nonempty
finish reason fails closed, including length/MAX_TOKENS, safety/content filtering,
tool-call termination and unfamiliar statuses. Missing/None/empty completion
metadata is unknown, never silently upgraded to reported_finished. Text length
is not used to infer completion. Normal termination is not factual verification
or proof of semantic coverage.

The Gemini adapter checks response-level errors/status, prompt blocking and the
single candidate's finish reason when supplied. The OpenAI-compatible adapter
checks errors/status, exactly one choice, refusal and finish reason. Malformed
structures trigger existing fallback. The adapters intentionally validate the
SDK object interface used by current callers; arbitrary dictionaries are not a
second supported response API. Unexpected explicit metadata representations may
fail closed until verified against the installed SDK.

`llm_client.generate_content` preserves Gemini -> Groq -> HF ordering and the
exact prompt across retries. Exceptions, invalid payloads, structured provider
errors, refusals and explicit incomplete termination all advance to the next
existing provider. A usable response with missing metadata remains successful
but explicitly unknown for compatibility; it does not trigger speculative retries
solely because optional metadata is absent. Exhaustion returns a safe failure.
Runtime tier logs no longer print private provider exception details.

All three note providers now request a 2048-token output cap: Gemini via
config.max_output_tokens; Groq/HF via max_tokens (HF already used 2048). This bounds
the requested output, not actual tokenizer correctness or semantic completeness.
Responses that report reaching the cap cannot be saved as complete results.
Models, provider order, client initialization, transport timeouts and dependencies
are unchanged. SDK support for these request/metadata representations still
requires isolated real-runtime validation; no real SDK/API was exercised here.

### Full-source eligibility and preserved question answering

Comprehensive generation is the default for route_and_process. It builds the full
sanitized source prompt and requires its **entire UTF-8 representation**, including
instructions/delimiters, to fit an inclusive 8192-byte application limit. This
replaces reliance on the old 120000 raw-character threshold for note eligibility.
Unicode and long instructions cannot bypass the byte check. No source is sliced.
Oversized requests return an explicit false result before generation embeddings,
ephemeral indexing or model invocation; the UI applies the same budget check even
if an injected router would claim success. Upload extraction/persistent indexing
still occur normally, so this does not remove their cost.

8192 bytes is a conservative temporary application policy, **not a verified model
context size, tokenizer count, or guarantee that every configured provider accepts
all such requests**. No provider capacities were looked up or probed. The 2048
output cap provides a bounded requested output but is not an arithmetic token
certificate for the input. Actual provider window/SDK behavior remains unknown;
context-limit errors fail/fallback without input trimming. Only requests with all
selected source included and within this application policy are eligible here.
Sources previously accepted below 120000 characters may now be refused. The safe
UI message requests a smaller document/section, without implying that a section
selection tool has been implemented.

Explicit comprehensive=False retains the existing targeted-question direct/RAG
routing, including the legacy raw-character switch and top-five similarity query.
Its result text is also validated. No similarity ranking, index, chunking or chat
retrieval algorithm was redesigned. Existing interactive chat still uses its
separate selected-document retrieval and agent path; this batch does not claim
to validate that path's provider completion metadata or fallback context.

### UI, saving and legacy behavior

The router validates successful text again, and the UI independently requires
success is True plus a valid payload before assigning notes, initializing chat
or calling create_session. A generation attempt clears current derived notes,
chat/history and exports first, so failed regeneration cannot redisplay an older
result as newly successful. Source identity, ownership, extraction cache and
verified index state remain intact; saved database records are not deleted.
All Batch 5 source-token/save association guards remain active.

Unknown completion is permitted as **unverified** usable text, with an explicit
UI warning. The notes view also distinguishes unknown metadata from reported
normal termination and never calls either factual verification. JSON persistence
keeps text but loses str-subclass attributes; reopened saved notes therefore
truthfully default to unknown. Existing saved notes are not rewritten or rejected
merely for lacking historical provider metadata. No schema migration is needed.
Unknown status can conceal an unreported truncation; this is an explicit remaining
uncertainty, not a claim of verified completeness. Explicit known incompleteness
always blocks success/persistence.

### Regression results and adaptations

Command: `python -I -S -B tests/run_offline.py`.

**391 tests: 366 passing, 25 ordinary failures, zero errors/skips/expected failures.**
The failures are the same 20 OAuth contracts and five deferred RAG contracts:
RAG-06/07 (ordered, deduplicated complete batching), RAG-08 (stronger grounding
instructions), RAG-09 (reference integrity), and new RAG-21 (comprehensive long
batching availability). Safe refusal mitigates original RAG-01..05 and RAG-17;
it does not implement comprehensive long-source coverage. RAG-10..16 and
RAG-18..20 now pass through actual output validation and persistence guards.
Overall, 16 original red 6A contracts now pass; four remain red and RAG-21 ensures
missing comprehensive functionality cannot be mistaken for implemented batching.

25 new passing tests cover payload types, error envelopes, missing/explicit
metadata, enum forms, serialization, provider error/refusal/structure handling,
exact fallback context, output caps, safe logs, byte-boundary/Unicode budgeting,
independent UI checks, valid short notes, unknown-status warnings and stale-output
invalidation. No provider, database, private document or external service was used.
Zero unexpected sandbox violations; temporary workspace removed.

Adaptations preserve meaningful earlier regressions:

- Batch 5 ephemeral indexing tests now explicitly select targeted-question mode;
  their indexing/denial assertions are unchanged. They still execute the same
  vector path rather than accidentally passing via the new early refusal.
- The legacy cascade success fixtures now supply concrete choice lists and stop
  reasons instead of unconstrained MagicMock response trees. Their original
  assertions remain unchanged; no mock enforces validation itself.
- 6A raw-threshold/top-five characterization checks now verify the byte-policy
  boundary or explicitly exercise targeted retrieval. Empty/failed/unknown-chunk
  retrieval controls also explicitly exercise that path.
- Future ordered/duplicate batching tests force an oversized policy case and
  retain ordinary failing assertions, rather than relying on the obsolete raw
  character cutoff or becoming errors due to no model call after refusal.
- RAG-21 is a new strict availability contract; no existing failure is hidden
  behind skip/xfail or a permissive expected-failure decorator.

No OAuth/security assertions, harness restrictions, authentication, database,
Docker or deployment files changed. No commit, deployment or Batch 6B-2/6B-3
implementation occurred. Existing OAuth remains insecure.

## Implemented Batch 6B-2: ordered comprehensive generation

This supersedes the 6B-1 temporary refusal of oversized comprehensive sources.
Targeted question answering remains an explicit, separate comprehensive=False
path with the original similarity/indexing safeguards. No grounding/reference
feature from Batch 6B-3 is implemented.

### Manifest and source identity

`src/utils/source_manifest.py` builds an immutable, UI/SDK-independent manifest
from the validated selected source, bound to its full SHA-256 and exact Unicode
character/UTF-8 byte lengths. Canonical units contain at most 512 UTF-8 bytes,
prefer an available newline boundary and otherwise split at a code-point boundary.
Units are contiguous from character zero through the final character. The manifest
records offsets, text hashes, required flags and stable ordinal IDs S000000 etc.
IDs are scoped to the manifest's source hash, not global identities or user IDs.
Partitioning is independent of display filename, query and model ranking. Owner
and upload-format/byte identity remain enforced by the Batch 5 selected-source
and index contracts outside the generation algorithm.

All characters remain accounted for, including boundaries and whitespace. A unit
containing only whitespace/BOMs is explicitly non-required and is not sent as an
empty generation call; its offsets/hash remain in the manifest. Nonempty repeated
passages at different source offsets retain distinct IDs. They are not collapsed
by text equality. Empty or all-whitespace whole sources still fail validation.
The 4096-unit hard cap bounds manifest construction; it is not a promise to accept
all sources under roughly 2 MiB, because batch/request limits can reject sooner.

Source batches are packed greedily in manifest order. Every required ID appears
exactly once among source requests; there is no retrieval stage to inject
repeated hits or omit a middle/final passage. JSON transport is reversible and
escapes delimiter characters. Short full-source prompts now use reversible HTML
escaping instead of deleting literal user_content examples. This preserves the
source characters while maintaining an explicit untrusted-data boundary; it does
not prove resistance to model prompt injection.

### Request, output and call budgets

The default GenerationLimits application policy is:

| Limit | Default / hard ceiling |
| --- | --- |
| Prompt string, including instructions and provenance | 8192 UTF-8 bytes |
| Reserved/maximum generated text per request | 8192 UTF-8 bytes |
| Prompt plus output reservation | 16384 application bytes |
| Intermediate summary encoded text | at most 2048 bytes; reduced when instructions require more space |
| Source units | 4096 |
| Required source batches | 64 |
| Generation/cascade invocations | 128 |
| Explicit provider SDK invocation upper bound | 384 (three per cascade invocation) |
| Synthesis rounds | 6 |
| Existing provider requested output cap | 2048 tokens, independently configured |

Prompt bytes and reserved output bytes are separate application allowances, not
conversions to/from provider tokens. SDK message envelopes, HTTP sizes, hidden
system context, actual model context windows and tokenizer behavior are not
certified by these numbers. Output text exceeding its byte reservation fails;
it is never silently truncated. Existing STOP/unknown/incomplete metadata rules
from 6B-1 remain active. Long Unicode source/instructions and JSON escaping count
against the actual encoded prompt size.

The planner checks every minimum record and all source-batch groups before any
model invocation. If instruction/provenance overhead leaves insufficient room for
a minimum section or two minimal summaries, it fails safely. Call minimums and
batch limits fail before paid work would begin. Runtime limits are checked again
before every logical call, reserving three possible SDK invocations even if the
first provider succeeds. This is a conservative upper bound, not an observed
provider-attempt count. The existing adapter has at most three explicit SDK calls
per invocation. Hidden SDK transport retries are **not bounded by this counter**;
actual HTTP attempt counts and wall-clock/provider timeouts remain unverified.
Future injected adapters must honor the at-most-three-SDK-invocations contract.
No real paid/network call occurred in this batch.

### Intermediate validation and bounded synthesis

`src/core/comprehensive_generation.py` has no Streamlit, Supabase or SDK
initialization. It accepts generate(prompt), preserving the existing cascade
interface and model order. Source batches run sequentially. Each response must
pass 6B-1 validation and the intermediate byte limit. Failure aborts the attempt;
no successful partial notes result is returned. The host associates each result
with its required source IDs, output hash and completion status. The model does
not certify its own coverage or have to echo all IDs correctly.

Intermediate results are validated for missing, duplicate, reordered or changed
outputs. Synthesis packs all current nodes in source order within the same prompt
budget. If they fit, one final call produces a cohesive guide. If they do not,
bounded intermediate synthesis reduces groups; singleton groups carry forward
without redundant calls. Each merged node retains the exact ordered parent IDs
and complete required-source ancestry. Compact range labels keep prompts bounded;
the retained manifest and graph contain the exact expanded ID tuples.

Intermediate size limits are computed so two worst-case compact records can fit.
Model text exceeding that limit aborts rather than being trimmed. A model may
ignore the requested concision; reliable real-world convergence is not assumed.
The round/call limits still fail closed if synthesis cannot finish. Retries start
a new generation attempt: this batch adds no durable partial-result cache,
background job or resumable paid-call checkpoint.

The final report validates all required source leaves exactly once in order,
known/ordered parents, no orphaned intermediate output, bounded request sizes,
output hashes and final all-source ancestry. Final text must match its recorded
hash and byte count. Explicit truncation or invalid final output fails. Completion
status is aggregated: any unknown intermediate means the final completion status
is unknown, even if the final provider reports STOP. Source coverage and provider
completion are independently exposed. Neither establishes model attention,
semantic completeness, citation integrity or factual accuracy.

### UI, ownership and durable notes compatibility

The comprehensive router now uses the new engine for both direct and batched
requests. It never uses top-five retrieval for complete notes. Generation failures
return a safe GenerationFailure string and false status. The UI separately
requires valid coverage bound to the currently selected source before assigning
notes or saving, preserving the source-token checks before and after generation.
A plausible bare success-shaped string or another document's valid report cannot
authorize persistence. Partial attempts leave notes unset; existing saved rows
and vectors are not deleted.

A versioned notes text envelope retains final text, completion status, manifest
and coverage graph in the existing notes field. The source text is not duplicated
inside the envelope; its existing session pdf_text field is used to verify all
hashes/offsets when loading. Both writing and reading enforce a 2 MiB record cap.
`document_state.restore_saved_session` decodes only after its existing owned-record
check and restores ordinary GenerationText for display/export. The current UI
therefore does not display raw envelope JSON. No schema or UUID/foreign-key change,
bulk migration or historical row rewrite is performed.

Historical plain notes remain readable without invented coverage metadata. New
records preserve the reported/unknown completion status on reopening, unlike the
6B-1 plain-string round trip. Malformed/wrong-source envelopes fail safely. The
reserved prefix AI_STUDY_NOTES_GENERATION_V1 identifies new records; a historical
note coincidentally using that exact prefix would require explicit recovery,
not silent fallback from malformed metadata. External consumers treating new
notes values as raw Markdown must use the decoder. Deployed column-size/grant
compatibility was not inspected; no production database was accessed.

### Tests and adaptations

Command: `python -I -S -B tests/run_offline.py`.

**432 tests: 410 passing, 22 ordinary failures, zero errors/skips/expected failures.**
Failures remain the same 20 OAuth assertions and only RAG-08/09 (stronger grounding
instructions and source-reference integrity). RAG-06/07 and RAG-21 now pass through
ordered full-source processing. Forty-one new tests verify source-character/Unicode
boundaries, stable IDs, whitespace policy, minimum-unit and manifest limits,
first/middle/final delivery, reversible transport, actual request bounds,
intermediate/final failures, summary overflow, bounded hierarchy, runtime model/
provider limits, graph corruption, fallback per batch, persistent round trips,
and UI eligibility after partial or wrong-source results.

Mocks supply raw responses; host coverage accounting and validation run in actual
production code. Chroma is not used for comprehensive generation. The inherited
offline sandbox preinstalls a chromadb module, so dependency-isolation tests assert
its client factories are never called rather than incorrectly asserting the
module name is absent. Fallback tests exercise the actual existing cascade with
mocked SDK endpoints, checking each primary/fallback prompt is identical.

Necessary earlier fixture/contract adaptations are explicit:

- Temporary-refusal tests now require full verified coverage on long success;
  question-retrieval failures cannot determine comprehensive coverage because the
  comprehensive path no longer uses question retrieval. Actual targeted failure
  controls remain in place and still exercise that vector path.
- Full-source delimiter checks decode reversible transport rather than accepting
  the previous deletion of literal delimiter text.
- UI success fixtures requiring coverage execute the real comprehensive router
  with synthetic model responses. No fake supplies automatic coverage guarantees.
- Saved-note assertions decode the new record and still check selected source,
  original notes content and completion status. Existing ownership assertions
  are unchanged; historical plain-note controls remain valid.

No existing security test was weakened or hidden. Zero unexpected sandbox
violations; temporary test workspace removed. The harness is unchanged.

### Runtime/cost implications and unverified behavior

A short eligible guide still uses one request. A long guide uses one call per
source batch plus final synthesis and, when needed, extra hierarchy calls; up to
three explicit provider invocations may occur for each. This replaces cheap but
incomplete sampling with higher, bounded per-attempt cost/latency. Notes generation
no longer pays for a second ephemeral embedding pass; upload's persistent indexing
is unchanged. All stages are sequential; there is no wall-clock deadline, rate
limiter, cancellation queue or cross-worker resumability added here.

Manifest/graph storage, request planning and retaining intermediate notes increase
memory and saved-record size. Bounds limit these costs but do not replace upload
limits or an isolated real-runtime performance test. No actual provider prices,
model availability, semantic accuracy, tokenizer compatibility, SDK retry behavior,
Streamlit reconnect/browser behavior, Supabase size constraints or deployed Chroma
behavior was validated. Model compression can lose important facts even when
every source character was delivered and every parent summary reached synthesis.
That limitation must not be described as verified factual completeness.

No real services, private documents, credentials, dependencies, commits, branch
changes or deployment actions were used. Batch 6B-3 remains unimplemented; OAuth
remains insecure.

## Implemented Batch 6B-3: grounding, explicit references and note consumers

This completes the remaining RAG-08/09 **instruction and identifier** contracts.
It does not establish semantic entailment, factual accuracy or real-model prompt
injection resistance. Source coverage, completion evidence and reference status
remain independent. No default batch/request/provider budget was raised.

### Grounding and minimum citation contract

`src/utils/source_references.py` supplies UI-independent prompt rules and explicit
reference checks. All comprehensive direct, source-batch and synthesis prompts
require source-only factual claims, preservation of technical details/definitions/
equations, labelled Interpretation for optional explanations, acknowledgement of
unclear/unsupported material, and no invented facts/page numbers/bibliography.
Embedded source instructions cannot override these rules. Tests verify actual
prompt construction and untrusted transport, not that a real model obeys them.

The minimum contract is deliberately optional rather than per-claim citation:

- No citation markers is allowed and explicitly reported as not_provided.
- Every claimed marker outside code must be exactly
  `[source:<64-lowercase-hex-source-SHA256>/Sdddddd]`, with six ordinal digits.
- The complete hash must match the selected manifest. The ID must be a required
  source unit supplied to that request. Whitespace-only/non-required units cannot
  be cited as evidence. Foreign hashes, nonexistent/out-of-batch IDs, missing IDs,
  missing brackets and malformed reserved-marker syntax fail; nothing is repaired.
- Valid repeated references remain in the text. Metadata deduplicates their IDs
  in first-appearance order; repeating a source is not itself a malformed claim.
- Ordinary prose, mathematical notation and normal Markdown links are not parsed
  as citations. The reserved `[source:` namespace is checked; a literal example
  must escape its opening bracket or use inline/fenced code. The lexical masker
  recognizes backtick spans and backtick/tilde fences, not every Markdown dialect.
  Code examples are not source claims. No general prose/bibliography blacklist is
  introduced, and unstructured bibliographic truth is not verified by this parser.

Strict per-claim citation coverage or semantic checking cannot safely be inferred
from free-form model text under the existing budgets. The UI explicitly distinguishes
identifiers_valid, not_provided and historical_unverified. Identifiers_valid says
only that each claimed ID is valid and has appropriate request ancestry; it does
not prove that the accompanying claim is supported. No new status is called
factually_grounded or verified_accuracy.

### Mapping and hierarchical provenance

Real references are scoped to the full source SHA-256, plus the manifest's stable
ordinal IDs. Each unit maps to exact original character offsets (end exclusive),
its text hash and the selected source already stored in pdf_text. They are not
invented PDF page numbers, external URLs or bibliographic identifiers.

Direct prompts retain the entire reversibly escaped source plus an ordered
ID-to-original-offset map. Source-batch records already include IDs, offsets and
actual unit text. Synthesis inputs retain validated note references and exact
host-side source ancestry. A synthesis result may reuse only IDs actually cited
by its input notes, not introduce a new reference merely because that ID falls
inside an ancestor coverage range. Input-range labels are not per-claim evidence.
A reference dropped from intermediate text is not silently resurrected later.
Coverage of all source units still travels independently through the complete
host graph, even when no references are provided.

Every stage validates claimed identifiers before accepting its result; final text
and stored metadata must agree on the exact reference-ID tuple. The persisted
coverage graph validates reference ancestry as well as existing output hashes,
source identity, request sizes and complete source delivery. Invalid references
abort the comprehensive attempt without extra repair/retry calls. The existing
cascade still handles SDK/provider/result failures; it is not rewritten into a
semantic/citation retry agent.

Prompt instructions and reference maps consume the existing 8192-byte input budget.
The inclusive direct-boundary test now computes the actual prompt, including this
map, instead of ignoring provenance overhead. Synthesis summary planning reserves
worst-case reference-list overhead based on how many canonical markers can fit in
each encoded summary. This prevents reference metadata from silently displacing
notes. No defaults were increased: 8192 prompt bytes, 8192 reserved output bytes,
2048-token provider cap, 64 source batches, 128 logical generation calls, 384
explicit SDK-invocation upper bound, six synthesis rounds and 4096 source units.
Bytes remain an application policy, not provider-token or model-window guarantees.
Additional instructions/citations can produce more batches or safe budget refusals.

### Saved-note compatibility and actual consumers

New notes use an explicit V2 text envelope with reference-contract version 1 and
per-request reference IDs. The existing text column and all user/session UUIDs
remain unchanged. V1 envelopes load with historical_unverified references, while
retaining their original validated source-delivery/completion metadata. Historical
plain text is preserved. Neither historical form is silently upgraded to current
reference validation, and a V1 result cannot authorize a new validated save.
Unknown or corrupt envelope versions fail closed rather than being displayed as
plain study material. The reserved-prefix collision caveat from V1 still applies.

| Actual consumer | Boundary and behavior |
| --- | --- |
| Saved-session load | Owned get_session read -> document_state.restore_saved_session -> load_notes. V1/V2 decode before notes enter the active selected-source state. No record/owner is chosen using model references. |
| Viewing and Markdown download | main_content._selected_notes rechecks selected owner/source token, decodes any serialized cache value, verifies available coverage, and returns only study text. Metadata wrappers are not passed to write/download. |
| PDF export | Same selected-note boundary; generate_pdf also refuses raw wrappers before Markdown/FPDF calls. No unrelated encoding/font changes. |
| Flashcards/Anki | Same boundary; generate_anki_deck refuses wrappers before creating a model client. Only decoded notes enter its existing extraction prompt. Card quality/fallback behavior is not redesigned. |
| Audio/podcast | Same boundary; speech cleanup itself refuses wrappers before regex transformations or gTTS. Podcast playback/download use the existing generated bytes. |
| Chat | Verifies the selected notes record before starting; its model context remains selected pdf_text/history and selected-document retrieval, not serialized notes JSON. Existing invalid-source denials return safely. Chat's separate provider/grounding behavior remains outside this comprehensive-note contract. |
| History listing/database APIs | Listing uses filename/timestamp and does not render raw notes. Storage APIs still return the encoded notes value; external callers must use load_notes with the owned source before plain-text use. |
| Editing | No implemented notes editor or notes-update UI/database path was found. No speculative editing feature or schema migration was added. |

Raw internal wrapper text is also rejected as new model output and before saving;
it cannot become a nested study-guide payload. The plain_notes guard protects
public PDF/flashcard/audio entry points when used outside the UI: callers must decode using the corresponding source first. It
refuses raw/unknown wrappers instead of guessing source identity. This also
prevents speech cleanup from mangling and voicing raw internal envelope fields.
Existing valid plain-text notes remain usable.

### Offline results and limits

Command: `python -I -S -B tests/run_offline.py`.

**472 tests: 452 passing, only the same 20 OAuth failures, zero errors/skips/expected
failures.** RAG-08 and RAG-09 now pass via production prompt/reference validation.
Forty new tests cover valid/fabricated/foreign/missing/out-of-batch IDs,
malformed syntax, duplicate claims, code examples, injection-shaped source,
ancestor-restricted synthesis, exact budget overhead, saved-record versions,
metadata tampering, persistence eligibility and all actual note consumers.

Consumer tests execute real UI/exporter plumbing with synthetic Markdown/PDF,
Anki packaging, SDK and speech boundaries. They inspect the exact text given to
codecs/providers and verify temporary deck/audio files are removed. They do not
prove real codecs render every equation or that generated cards/audio are accurate.
The existing PDF Latin-1/font limitations and speech Markdown transformations are
not fixed or hidden by this envelope-compatibility batch.

All earlier authorization, extraction, indexing and coverage regressions remain.
The only changed earlier boundary test is updated to include actual grounding/map
overhead; its full-source/no-truncation and no-vectorization assertions remain.
Shared UI fixture captures expose real consumer functions for testing; no mock
supplies missing production reference guarantees. No OAuth assertion was edited,
skipped or marked expected-failure. Offline isolation reports zero unexpected
violations and complete temporary-workspace cleanup.

No real model, semantic entailment system, private record, production database,
credential, browser, codec/runtime integration or deployment was used. Normal
provider termination can still accompany inaccurate notes. Identifier validity
can still accompany a claim unsupported by the cited unit. Optional citations may
be absent or compressed away, and natural-language invented bibliography cannot
be exhaustively detected by this reserved-ID protocol. Real-model quality, citation
alignment, prompt injection, tokenizer/window compatibility and UI/runtime behavior
require separately authorized evaluation.

No dependencies, commits, pushes, deployments, branch/schema/authentication changes
or unrelated features were introduced. OAuth remains insecure; do not deploy.
