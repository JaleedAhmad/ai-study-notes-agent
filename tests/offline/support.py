"""Test-only isolation; no third-party dependencies or production imports."""

import contextlib
import importlib
import importlib.util
import os
from pathlib import Path
import sys
import sysconfig
import tempfile
import types
import unittest
from unittest.mock import Mock, patch


class OfflineViolation(RuntimeError):
    """An operation escaped the explicit offline fixtures."""


ACTIVE = None


class Sandbox:
    def __init__(self, repository):
        self.repository = repository.resolve()
        self.stdlib = Path(sysconfig.get_path("stdlib")).resolve()
        self.violations = []
        self.enabled = False

    def block(self, operation):
        self.violations.append(operation)
        raise OfflineViolation(f"Offline sandbox blocked: {operation}")

    def blocked_call(self, operation):
        def blocked(*args, **kwargs):
            self.block(operation)
        return Mock(side_effect=blocked)

    def resolve(self, path, directory_fd=None):
        if isinstance(path, int):
            path = os.readlink(f"/proc/self/fd/{path}")
        path = Path(os.fsdecode(path))
        if directory_fd not in (None, -1) and not path.is_absolute():
            path = Path(os.readlink(f"/proc/self/fd/{directory_fd}")) / path
        return path.resolve()

    def writable(self, path, directory_fd=None):
        if not self.resolve(path, directory_fd).is_relative_to(self.root):
            self.block("filesystem mutation outside temporary workspace")

    def readable(self, path):
        path = self.resolve(path)
        if path.is_relative_to(self.root):
            return
        if path.is_relative_to(self.stdlib):
            return
        if path == self.repository / "app.py":
            return
        if path.suffix in (".py", ".pyc") and any(
            path.is_relative_to(self.repository / folder) for folder in ("src", "tests")
        ):
            return
        self.block("read outside test source, stdlib, or temporary workspace")

    def audit(self, event, args):
        if not self.enabled:
            return
        if event.startswith("socket.") or event in (
            "subprocess.Popen", "os.system", "os.fork", "os.forkpty",
            "os.posix_spawn", "os.exec", "pty.spawn",
        ):
            self.block("network or child-process operation")
        if event == "open":
            path, mode, flags = args
            writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
                isinstance(flags, int) and flags & (
                    os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
                )
            )
            self.writable(path) if writing else self.readable(path)
        elif event in ("os.remove", "os.rmdir", "os.mkdir", "os.chmod"):
            self.writable(args[0], args[-1] if event != "os.mkdir" else args[2])
        elif event in ("os.truncate", "os.utime", "os.chown"):
            self.writable(args[0], args[-1] if event != "os.truncate" else None)
        elif event in ("os.rename", "os.link"):
            self.writable(args[0], args[2])
            self.writable(args[1], args[3])
        elif event == "os.symlink":
            self.block("symlink creation")
        elif event in ("os.listdir", "os.scandir"):
            path = self.resolve(args[0] if args[0] is not None else ".")
            if not (path == self.repository or path.is_relative_to(self.root) or path.is_relative_to(self.stdlib)
                    or any(path.is_relative_to(self.repository / p) for p in ("src", "tests"))):
                self.block("directory access outside offline inputs")
        elif event == "os.chdir":
            self.writable(args[0])
        elif event == "sqlite3.connect":
            if args[0] != ":memory:":
                self.writable(args[0])

    def __enter__(self):
        global ACTIVE
        if ACTIVE is not None:
            raise RuntimeError("Sandbox already active")
        self.previous_cwd = Path.cwd()
        self.previous_tempdir = tempfile.tempdir
        self.workspace = tempfile.TemporaryDirectory(prefix="study-notes-offline-")
        self.root = Path(self.workspace.name).resolve()
        # This is a dedicated process: discard inherited credentials entirely.
        os.environ.clear()
        os.environ.update({
            "HOME": str(self.root), "TMPDIR": str(self.root),
            "TEMP": str(self.root), "TMP": str(self.root),
            "GEMINI_API_KEY": "offline-placeholder",
            "GROQ_API_KEY": "offline-placeholder",
            "HUGGINGFACE_API_KEY": "offline-placeholder",
            "SUPABASE_URL": "https://offline.invalid",
            "SUPABASE_KEY": "offline-placeholder",
            "GITHUB_CLIENT_ID": "offline-placeholder",
            "GITHUB_CLIENT_SECRET": "offline-placeholder",
        })
        tempfile.tempdir = str(self.root)
        os.chdir(self.root)
        sys.path.insert(0, str(self.repository))
        sys.addaudithook(self.audit)
        self.enabled = True
        ACTIVE = self
        return self

    def __exit__(self, *exc):
        global ACTIVE
        try:
            self.workspace.cleanup()
        finally:
            self.enabled = False
            ACTIVE = None
            os.chdir(self.previous_cwd)
            tempfile.tempdir = self.previous_tempdir

    @contextlib.contextmanager
    def expected_block(self):
        start = len(self.violations)
        try:
            yield
        except OfflineViolation:
            if len(self.violations) != start + 1:
                raise AssertionError("Expected exactly one blocked operation")
            del self.violations[start:]
        else:
            raise AssertionError("Unsafe operation was not blocked")

    def dependencies(self):
        """Fake SDKs before production imports; service methods fail by default."""
        modules = {}

        def module(name, **attrs):
            item = types.ModuleType(name)
            item.__path__ = []
            item.__dict__.update(attrs)
            modules[name] = item
            return item

        def provider(*args, **kwargs):
            return types.SimpleNamespace(
                models=types.SimpleNamespace(
                    generate_content=self.blocked_call("unmocked model generation"),
                    embed_content=self.blocked_call("unmocked embedding"),
                    list=self.blocked_call("unmocked model listing")),
                chat=types.SimpleNamespace(completions=types.SimpleNamespace(
                    create=self.blocked_call("unmocked chat completion"))),
                chats=types.SimpleNamespace(create=self.blocked_call("unmocked chat session")),
            )

        module("dotenv", load_dotenv=Mock(return_value=False))
        google = module("google")
        google.genai = module("google.genai", Client=Mock(side_effect=provider))
        google.genai.types = module("google.genai.types")
        google.api_core = module("google.api_core")
        google.api_core.exceptions = module("google.api_core.exceptions", **{
            name: type(name, (Exception,), {}) for name in (
                "ServiceUnavailable", "ResourceExhausted", "DeadlineExceeded", "InternalServerError")
        })
        module("openai", OpenAI=Mock(side_effect=provider))
        module("supabase", Client=object,
               create_client=self.blocked_call("unmocked database client"))
        module("requests", **{name: self.blocked_call("unmocked HTTP request")
                              for name in ("get", "post", "request", "Session")})
        module("bcrypt", **{name: self.blocked_call("unmocked password hashing")
                            for name in ("checkpw", "hashpw", "gensalt")})
        module("streamlit", cache_resource=lambda function: function,
               warning=Mock(), error=Mock())
        module("chromadb", **{name: self.blocked_call("unmocked vector client")
                              for name in ("PersistentClient", "EphemeralClient")})
        module("chromadb.config", Settings=object)
        module("langchain_text_splitters", RecursiveCharacterTextSplitter=
               self.blocked_call("unmocked text splitter"))
        module("docx", Document=self.blocked_call("unmocked DOCX parser"))
        module("pptx", Presentation=self.blocked_call("unmocked PPTX parser"))
        module("pypdf", PdfReader=self.blocked_call("unmocked PDF parser"))
        pil = module("PIL")
        pil.Image = module("PIL.Image", Image=object,
                           open=self.blocked_call("unmocked image parser"))
        module("pdf2image", convert_from_bytes=self.blocked_call("unmocked PDF rendering"))
        module("gtts", gTTS=self.blocked_call("unmocked speech provider"))
        return modules


class OfflineCase(unittest.TestCase):
    def setUp(self):
        if ACTIVE is None:
            self.fail("Use: python -I -S -B tests/run_offline.py")
        self.sandbox = ACTIVE
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.workdir = Path(self.stack.enter_context(
            tempfile.TemporaryDirectory(dir=self.sandbox.root)))
        previous = Path.cwd()
        os.chdir(self.workdir)
        self.stack.callback(os.chdir, previous)
        self.stack.enter_context(patch.object(sys, "path", list(sys.path)))
        # Restore sys.modules after each case, including newly imported app modules.
        self.stack.enter_context(patch.dict(sys.modules, self.sandbox.dependencies()))

    def app(self, name):
        return importlib.import_module(name)

    def legacy(self, filename):
        spec = importlib.util.spec_from_file_location(
            "offline_legacy", self.sandbox.repository / "tests" / filename)
        item = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(item)
        return item
