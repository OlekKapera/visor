from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from framework.appium_lifecycle import _inject_server_binding, resolve_appium_command, status_managed_appium, stop_managed_appium


class AppiumLifecycleTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._cwd = Path.cwd()
        os.chdir(self._tmp.name)

    def tearDown(self):
        os.chdir(self._cwd)
        self._tmp.cleanup()

    def test_resolve_command_prefers_cli_override(self):
        with patch.dict(os.environ, {"VISOR_APPIUM_CMD": "appium --base-path /wd/hub"}, clear=False):
            resolved = resolve_appium_command("custom-appium --port 4725")
        self.assertEqual(resolved, "custom-appium --port 4725")

    def test_resolve_command_prefers_env_when_no_override(self):
        with patch.dict(os.environ, {"VISOR_APPIUM_CMD": "appium --port 4725"}, clear=False):
            resolved = resolve_appium_command(None)
        self.assertEqual(resolved, "appium --port 4725")

    def test_resolve_command_auto_detects_npx_before_appium(self):
        with patch.dict(os.environ, {}, clear=True), patch("framework.appium_lifecycle.shutil.which") as which_mock:
            which_mock.side_effect = lambda cmd: "/usr/bin/npx" if cmd == "npx" else "/usr/bin/appium"
            resolved = resolve_appium_command(None)
        self.assertEqual(resolved, "npx appium")

    def test_status_returns_unmanaged_when_no_metadata(self):
        status = status_managed_appium("http://127.0.0.1:4723")
        self.assertFalse(status["managed"])
        self.assertIn(".visor/appium/127.0.0.1_4723.json", status["metadataPath"])

    def test_inject_server_binding_adds_address_and_port_when_missing(self):
        parts = _inject_server_binding(["npx", "appium"], "127.0.0.1", 4725)
        self.assertEqual(parts, ["npx", "appium", "--address", "127.0.0.1", "--port", "4725"])

    def test_inject_server_binding_keeps_existing_address_and_port(self):
        parts = _inject_server_binding(["appium", "--address", "0.0.0.0", "--port", "9999"], "127.0.0.1", 4725)
        self.assertEqual(parts, ["appium", "--address", "0.0.0.0", "--port", "9999"])

    def test_stop_returns_no_managed_process_when_unmanaged(self):
        result = stop_managed_appium("http://127.0.0.1:4723")
        self.assertFalse(result["stopped"])
        self.assertEqual(result["reason"], "no_managed_process")


if __name__ == "__main__":
    unittest.main()
