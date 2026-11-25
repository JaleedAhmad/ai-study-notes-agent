"""Launcher contracts with no real server, provider initialization, or sockets."""

from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

from offline.support import OfflineCase


class ServerTests(OfflineCase):
    def setUp(self):
        super().setUp()
        self.runtime = Mock()
        self.constructor = Mock(return_value=self.runtime)
        sys.modules["streamlit"].App = self.constructor
        responses = ModuleType("starlette.responses")
        responses.JSONResponse = Mock(side_effect=lambda data: SimpleNamespace(data=data))
        routing = ModuleType("starlette.routing")
        routing.Route = Mock(side_effect=lambda path, endpoint, **kwargs:
                             SimpleNamespace(path=path, endpoint=endpoint, **kwargs))
        self.stack.enter_context(patch.dict(sys.modules, {
            "starlette": ModuleType("starlette"),
            responses.__name__: responses, routing.__name__: routing,
        }))

    def launcher(self):
        # Read only the allowlisted source, without probing root bytecode caches.
        path = self.sandbox.repository / "server.py"
        module = ModuleType("offline_server")
        module.__file__ = str(path)
        exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
        return module

    def test_root_script_is_the_existing_absolute_application_path(self):
        self.launcher()
        script = Path(self.constructor.call_args.args[0])
        self.assertEqual(script, self.sandbox.repository / "app.py")
        self.assertTrue(script.is_absolute())
        self.assertTrue(script.is_file())
        self.assertNotEqual(script.parent, self.workdir)

    def test_only_custom_route_is_named_get_health(self):
        server = self.launcher()
        routes = self.constructor.call_args.kwargs["routes"]
        self.assertEqual(len(routes), 1)
        self.assertEqual((routes[0].path, routes[0].name, routes[0].methods),
                         ("/health", "health", ["GET"]))
        self.assertIs(routes[0].endpoint, server.health)
        self.assertNotIn(routes[0].path, ("/", "/_stcore/health", "/_stcore/stream"))

    def test_health_has_only_constant_public_liveness_data(self):
        server = self.launcher()
        # Deliberately provide no request attributes or credentials.
        # No event loop: asyncio.run would create a socket pair in this sandbox.
        with self.assertRaises(StopIteration) as completed:
            server.health(object()).send(None)
        response = completed.exception.value
        self.assertEqual(response.data, {"status": "ok"})

    def test_import_constructs_once_without_starting_or_importing_study_ui(self):
        server = self.launcher()
        self.assertIs(server.app, self.runtime)
        self.constructor.assert_called_once()
        self.runtime.run.assert_not_called()
        for name in ("src.ui.auth", "src.database.database", "src.core.llm_client"):
            self.assertNotIn(name, sys.modules)

    def test_launcher_leaves_configuration_and_server_start_to_streamlit_cli(self):
        self.launcher()
        self.constructor.assert_called_once()
        self.assertEqual(set(self.constructor.call_args.kwargs), {"routes"})
        self.runtime.run.assert_not_called()
