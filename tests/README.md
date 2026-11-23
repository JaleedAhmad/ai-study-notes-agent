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
