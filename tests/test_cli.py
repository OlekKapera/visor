from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import visor.cli as cli
from framework.adapters import MockAdapter
from framework.validator import parse_and_validate


ROOT = Path(__file__).resolve().parents[1]


def run_cmd(args):
    p = subprocess.run(["python3", "-m", "visor", *args], cwd=ROOT, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


class CliTests(unittest.TestCase):
    def test_validate_ok(self):
        code, out, _ = run_cmd(["validate", "scenarios/checkout-smoke.json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["data"]["valid"])

    def test_cli_accepts_subcommand_format_flag_order(self):
        code, out, _ = run_cmd(["validate", "scenarios/checkout-smoke.json", "--format", "json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "ok")

    def test_action_accepts_subcommand_format_flag_order(self):
        code, out, _ = run_cmd(["wait", "--platform", "android", "--mock", "--ms", "1", "--format", "json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "ok")

    def test_run_ok(self):
        code, out, _ = run_cmd(["run", "scenarios/checkout-smoke.json", "--output", "artifacts-test", "--mock"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["data"]["run"]["status"], "ok")
        self.assertIn("determinism_signature", payload["data"]["run"])

    def test_run_accepts_app_id_flag(self):
        code, out, _ = run_cmd(
            [
                "run",
                "scenarios/checkout-smoke.json",
                "--output",
                "artifacts-test",
                "--mock",
                "--app-id",
                "com.example.custom",
            ]
        )
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "ok")

    def test_assertion_failure_emits_assertion_error(self):
        code, out, _ = run_cmd(["run", "scenarios/assertion-fail-smoke.json", "--output", "artifacts-test", "--mock"])
        self.assertEqual(code, 2)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "fail")
        self.assertEqual(payload["error"]["code"], "ASSERTION_ERROR")
        self.assertEqual(payload["data"]["run"]["status"], "fail")

    def test_screenshot_artifact_is_real_png_not_placeholder(self):
        code, out, _ = run_cmd(["run", "scenarios/checkout-smoke.json", "--output", "artifacts-test", "--mock"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        run = payload["data"]["run"]
        shots = run["artifacts"]
        self.assertGreaterEqual(len(shots), 1)
        first = Path(shots[0])
        self.assertTrue(first.exists())
        magic = first.read_bytes()[:8]
        self.assertEqual(magic, b"\x89PNG\r\n\x1a\n")
        screenshot_step = run["steps"][0]
        self.assertEqual(screenshot_step["details"]["args"]["width"], 1)
        self.assertEqual(screenshot_step["details"]["args"]["height"], 1)

    def test_benchmark_determinism_meets_threshold_in_mock(self):
        code, out, _ = run_cmd(["benchmark", "scenarios/checkout-smoke.json", "--platform", "android", "--mock", "--runs", "5", "--threshold", "95", "--format", "json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertTrue(payload["data"]["pass"])
        self.assertGreaterEqual(payload["data"]["determinismScore"], 95.0)

    def test_report_accepts_positional_path(self):
        code, out, _ = run_cmd(["report", "artifacts-test", "--format", "json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["data"]["path"], "artifacts-test")

    def test_cmd_run_passes_app_id_to_adapter(self):
        parser = cli.build_parser()
        args = parser.parse_args(
            [
                "run",
                "scenarios/checkout-smoke.json",
                "--mock",
                "--output",
                "artifacts-test",
                "--app-id",
                "com.example.custom",
            ]
        )

        with patch("visor.cli.get_adapter") as get_adapter_mock:
            get_adapter_mock.return_value = MockAdapter("android")
            code = cli.cmd_run(args)

        self.assertEqual(code, 0)
        self.assertEqual(get_adapter_mock.call_args.kwargs["app_id"], "com.example.custom")
        self.assertFalse(get_adapter_mock.call_args.kwargs["attach_to_running"])

    def test_cmd_run_passes_attach_flag_to_adapter(self):
        parser = cli.build_parser()
        args = parser.parse_args(
            [
                "run",
                "scenarios/checkout-smoke.json",
                "--mock",
                "--output",
                "artifacts-test",
                "--attach",
            ]
        )

        with patch("visor.cli.get_adapter") as get_adapter_mock:
            get_adapter_mock.return_value = MockAdapter("android")
            code = cli.cmd_run(args)

        self.assertEqual(code, 0)
        self.assertTrue(get_adapter_mock.call_args.kwargs["attach_to_running"])

    def test_wait_command_succeeds_in_mock(self):
        code, out, _ = run_cmd(["wait", "--platform", "android", "--mock", "--ms", "10"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["data"]["args"]["ms"], 10)

    def test_python_module_entrypoint_help_succeeds(self):
        p = subprocess.run(["python3", "-m", "visor", "--help"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0)
        self.assertIn("visor", p.stdout)

    def test_source_command_writes_artifact_in_mock(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmpdir:
            target = Path(tmpdir) / "source.xml"
            code, out, _ = run_cmd(["source", "--platform", "android", "--mock", "--path", str(target)])
            self.assertEqual(code, 0)
            payload = json.loads(out)
            self.assertEqual(payload["status"], "ok")
            self.assertTrue(target.exists())
            self.assertIn(str(target), payload["artifacts"])

    def test_validate_accepts_coordinate_tap_and_wait(self):
        scenario = {
            "meta": {"name": "coords", "version": "1", "platform": "android"},
            "config": {"seed": 42},
            "steps": [
                {"id": "s1", "command": "wait", "args": {"ms": 250}},
                {"id": "s2", "command": "tap", "args": {"x": 0.5, "y": 0.8, "normalized": True}},
            ],
            "assertions": [],
            "output": {"report": ["json"]},
        }
        with tempfile.TemporaryDirectory(dir=ROOT) as tmpdir:
            path = Path(tmpdir) / "scenario.json"
            path.write_text(json.dumps(scenario), encoding="utf-8")
            parsed, issues = parse_and_validate(str(path))
        self.assertIsNotNone(parsed)
        self.assertEqual(issues, [])


if __name__ == "__main__":
    unittest.main()
