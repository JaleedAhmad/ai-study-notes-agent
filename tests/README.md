# Offline testing

From the repository root, using Python 3.10 or newer:

```sh
python -I -S -B tests/run_offline.py
```

No installation, API keys, runtime dependencies, pytest, or services are required.
`-I` ignores Python environment/path customizations, `-S` disables site packages
and their startup hooks, and `-B` prevents bytecode writes. The runner refuses to
start without these flags. Exit status is 0 for success, 1 for test/isolation/
cleanup failure, and 2 for incorrect invocation. Test discovery is restricted to
`tests/offline`; zero collected tests is a failure.

Batch 3B resolves the 22 original Batch 3A failures. All 68 original cases remain,
with 15 additional hardening tests (83 total). No expected-failure decorators are
used. See [authorization contracts](AUTHORIZATION.md) for the historical source
mapping, current API contracts, fixture changes, and deployment limitations.

Batch 4A adds 36 GitHub OAuth tests: 16 pass and 20 preserve failing security
assertions. The full suite now has 119 tests (99 pass, 20 fail) and exits 1;
all prior 83 tests still pass. See [OAuth investigation](OAUTH.md) for the flow,
failure mapping, isolation limits, and unapproved state/subject migration options.

Batch 4B-1 adds five launcher tests: 124 total, 104 passing and the same 20
ordinary OAuth assertion failures (exit 1). They use fake Streamlit/Starlette
objects to verify the absolute root script, single named GET health route,
constant public response, import isolation and CLI-controlled startup. They do not
simulate a real WebSocket or validate SDK compatibility.

The production launcher is `streamlit run server.py` from the project root.
Streamlit 1.60.0 detects the exported `st.App` and starts its native server using
the existing CLI configuration and environment;
Docker continues to expose port 7860. `/health` is process liveness only, not a
database/provider readiness check. No OAuth routing or authentication changes
are included. `server.py` has an explicit Docker build-context allowlist entry.
Keep the CLI startup: the isolated 1.60.0 check found that calling `App.run()`
without explicit overrides used default host/port rather than Docker's existing
environment options. The CLI launched correctly on the configured port 7860.

An isolated runtime smoke check exercised real Streamlit/Starlette HTTP and
WebSocket handling with copies of the unchanged `app.py` and identity helper,
replacing only UI/provider entry points with synthetic test modules. Root HTML,
custom and built-in health, GET/HEAD/POST behavior, and both logged-out and
authenticated UI branches passed. Reserved route conflicts were also rejected.
This does not verify live SDK operations, browser behavior, or Hugging Face routing.

Batch 4B-2A adds 32 passing design checks: 12 static/lexical checks of the
explicitly non-executable [OAuth storage SQL proposal](../migrations/proposals/4b2a_oauth_storage.sql.md)
and 20 behavioral checks of a separate test-only reference model. The suite has
156 tests: 136 pass and the same 20 current-production OAuth assertions fail
(exit 1). See [migration review and deployment gates](../migrations/README.md).
The model implements intended rules; it is not used by the existing OAuth mocks
and does not prove PostgreSQL ACLs/RLS, concurrency or current application safety.
The sandbox grants read access only to that exact reviewed SQL proposal path;
secret reads, networking, repository writes and subprocesses remain blocked.

Batch 4B-2B validates the corrected proposal in a separate disposable PostgreSQL
16.16 container ([results](../migrations/POSTGRES_VALIDATION.md)). A nil-UUID
default revealed a partial-account commit on failure; the draft now raises to
roll back that case. One static regression brings this offline suite to 157
tests: 137 passing and the same 20 OAuth failures. Real PostgreSQL checks remain
separate; the offline command does not require Docker or contact any database.

Batch 5A adds 48 extraction/ingestion tests: 15 passing controls and 33 ordinary
failing correctness assertions. The complete suite has 205 tests: 152 passing,
20 unchanged OAuth failures and 33 extraction failures (exit 1), with no errors.
See [extraction investigation and source mapping](EXTRACTION.md). Actual extractor,
vision, RAG, routing and UI code runs with synthetic parser/provider/storage
outputs; no real document parsers, OCR services or databases are exercised.

Batch 5B-1 fixes 28 of the 33 extraction assertions using typed errors and shared
content validation, without changing the original 48 assertions. Twenty new checks
bring the suite to 225 tests: 200 pass, 20 known OAuth assertions and five scheduled
coverage/indexing/cache assertions fail (exit 1). See the implemented section of
[extraction contracts](EXTRACTION.md) for current interfaces, scope and limitations.

The suite imports real application source with test-only SDK modules installed
before import. Dotenv loading is a no-op, the dedicated process discards inherited
environment values, and only synthetic credentials are supplied. Model, HTTP,
database, vector, parser, and speech operations fail unless explicitly mocked.
An audit hook blocks socket/DNS operations and subprocesses, restricts reads to
test/application Python source, the standard library and temporary fixtures, and
restricts writes to the temporary workspace. Unexpected blocked operations fail
the run even if application exception handling swallows the exception.

Every case gets fresh dependency mocks, module state, and a temporary working
directory. Import-time `chroma_db` creation therefore happens in that directory.
Temporary artifacts and the enclosing workspace are removed and cleanup is
checked. Negative safety tests emit synthetic audit events rather than attempting
real secret reads, repository mutations, connections, or child processes. They
therefore remain harmless even if a guard regresses. Actual fixture I/O occurs
only in temporary directories. No real secret contents are inspected.

These are safeguards against accidental Python-side effects, not an OS security
sandbox for malicious code or a guarantee about native extensions. The supported
command excludes installed third-party packages. SDK compatibility, parser
accuracy, RLS, deployment, and real provider behavior require separate authorized
integration tests. The fakes are not substitutes for those checks.

Batch 5B-2 adds 22 passing PDF coverage/UI checks: **247 total, 224 passing,
23 ordinary failures** (the same 20 OAuth failures and three scheduled
index/cache/session failures). Both remaining PDF defects now pass. Single-page
rendering replaces bulk fallback; the original valid scan test checks exact
per-page ranges. See [page policies and limits](EXTRACTION.md#batch-5b-2-page-level-pdf-coverage).
The suite uses synthetic parser/renderer/OCR responses, not real Poppler or APIs.

## Existing tests and scripts

All original files are preserved unchanged:

| File | Offline treatment / reason |
| --- | --- |
| `test_cascade.py` | Its three existing test functions run unchanged after fake SDK installation. Direct import otherwise loads dotenv and initializes clients before patches. |
| `test_extractor.py` | Existing Markdown test runs unchanged. DOCX/PPTX round trips are excluded because real parser packages are absent; mocked parsers would not validate serialization. Import otherwise reaches provider initialization. |
| `test_agent.py` | Excluded: module-level live generation can incur charges; not a unit test. |
| `test_embed.py` | Excluded: module-level dotenv loading, client creation, and remote model listing. |
| `test_genai.py` | Excluded: manual SDK signature diagnostic, needs the actual SDK and lacks test assertions. |
| `test_bug.py` | Excluded: obsolete root-level import and working-directory `test.pdf` dependency. |
| `create_test_pdf.py` | Excluded: manual fixture generator writes `test.pdf` at module scope. |

Do not execute or broadly collect the legacy directory in an offline environment.
`pytest.ini` limits default pytest discovery and disables its cache, but pytest is
not installed or required. Direct pytest execution of offline cases fails closed
with the supported command because it does not establish the sandbox. Do not use
`pytest tests` to override the collection boundary.

Both existing CI workflows are preserved: deployment syncs to Hugging Face and
keep-alive contacts Supabase/HTTP. Neither is an offline test and neither was run.
This batch does not change deployment behavior or make tests a release gate.

## Adding offline cases

Subclass `offline.support.OfflineCase`; import production modules inside a test
with `self.app(...)`, not at collection time. Patch the narrow external operation
under test and use synthetic inputs. Use `self.workdir` or `TemporaryDirectory`
for artifacts. Do not assert that current known defects are correct behavior;
add their regression cases alongside the later remediation batch.

Batch 5B-3 adds 42 passing indexing/router/UI checks: **289 total, 267 passing,
22 ordinary failures** (20 unchanged OAuth failures and two deferred cache/session
failures). EXTRACT-28 now passes. Actual indexing requires complete embedding and
verified Chroma readback; tests use raw partial-write-capable in-memory storage,
not real Chroma or SDK calls. See [completion contracts, retry and legacy limits](INDEXING.md).

Batch 5B-4 adds 39 passing document identity, saved-session, generation and chat
checks: **328 total, 308 passing, only the 20 unchanged OAuth assertions failing**.
Both remaining EXTRACT-29/30 contracts now pass. See [source identity and cache contracts](DOCUMENT_STATE.md)
for legacy handling, test adaptations and unverified real Streamlit/Chroma behavior.
