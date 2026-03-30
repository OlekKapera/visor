from __future__ import annotations

import json
import os
import shlex
import shutil
import signal
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse


DEFAULT_STARTUP_TIMEOUT_SECONDS = 20.0


@dataclass
class ServerAddress:
    server_url: str
    host: str
    port: int


def _parse_server(server_url: str) -> ServerAddress:
    parsed = urlparse(server_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 4723
    return ServerAddress(server_url=server_url, host=host, port=port)


def is_appium_reachable(server_url: str, timeout: float = 1.0) -> bool:
    address = _parse_server(server_url)
    try:
        with socket.create_connection((address.host, address.port), timeout=timeout):
            return True
    except OSError:
        return False


def _state_dir() -> Path:
    root = Path.cwd() / ".visor" / "appium"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _slug(server_url: str) -> str:
    address = _parse_server(server_url)
    safe_host = address.host.replace(":", "_")
    return f"{safe_host}_{address.port}"


def _meta_path(server_url: str) -> Path:
    return _state_dir() / f"{_slug(server_url)}.json"


def _log_path(server_url: str) -> Path:
    return _state_dir() / f"{_slug(server_url)}.log"


def _pid_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read_meta(server_url: str) -> Optional[Dict[str, Any]]:
    path = _meta_path(server_url)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_meta(server_url: str, meta: Dict[str, Any]) -> Path:
    path = _meta_path(server_url)
    path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return path


def _cleanup_meta(server_url: str) -> None:
    path = _meta_path(server_url)
    if path.exists():
        path.unlink()


def resolve_appium_command(override_cmd: str | None = None) -> str:
    if override_cmd and override_cmd.strip():
        return override_cmd.strip()

    env_cmd = os.getenv("VISOR_APPIUM_CMD", "").strip()
    if env_cmd:
        return env_cmd

    if shutil.which("npx"):
        return "npx appium"
    if shutil.which("appium"):
        return "appium"

    raise RuntimeError(
        "Unable to find Appium launcher. Install Appium (`npm i -g appium`) "
        "or set VISOR_APPIUM_CMD / --appium-cmd."
    )


def _inject_server_binding(cmd_parts: list[str], host: str, port: int) -> list[str]:
    has_port = "--port" in cmd_parts or "-p" in cmd_parts
    has_address = "--address" in cmd_parts or "-a" in cmd_parts

    with_binding = list(cmd_parts)
    if not has_address:
        with_binding.extend(["--address", host])
    if not has_port:
        with_binding.extend(["--port", str(port)])
    return with_binding


def status_managed_appium(server_url: str) -> Dict[str, Any]:
    reachable = is_appium_reachable(server_url)
    meta = _read_meta(server_url)

    if not meta:
        return {
            "serverUrl": server_url,
            "reachable": reachable,
            "managed": False,
            "pid": None,
            "command": None,
            "metadataPath": str(_meta_path(server_url)),
            "logPath": str(_log_path(server_url)),
        }

    pid = int(meta.get("pid", -1))
    alive = _pid_exists(pid)
    if not alive:
        _cleanup_meta(server_url)
        return {
            "serverUrl": server_url,
            "reachable": reachable,
            "managed": False,
            "pid": None,
            "command": None,
            "metadataPath": str(_meta_path(server_url)),
            "logPath": str(_log_path(server_url)),
        }

    return {
        "serverUrl": server_url,
        "reachable": reachable,
        "managed": True,
        "pid": pid,
        "command": meta.get("command"),
        "metadataPath": str(_meta_path(server_url)),
        "logPath": str(_log_path(server_url)),
    }


def start_managed_appium(
    server_url: str,
    appium_cmd: str | None = None,
    startup_timeout_s: float = DEFAULT_STARTUP_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
    existing_status = status_managed_appium(server_url)
    if existing_status["reachable"]:
        existing_status["alreadyRunning"] = True
        existing_status["started"] = False
        return existing_status

    resolved_cmd = resolve_appium_command(appium_cmd)
    server = _parse_server(server_url)
    cmd_parts = _inject_server_binding(shlex.split(resolved_cmd), server.host, server.port)
    if not cmd_parts:
        raise RuntimeError("Appium command is empty after parsing.")

    log_path = _log_path(server_url)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    with log_path.open("ab") as log_file:
        process = subprocess.Popen(
            cmd_parts,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=(os.name != "nt"),
            close_fds=True,
        )

    meta = {
        "pid": process.pid,
        "command": resolved_cmd,
        "serverUrl": server_url,
        "startedAt": time.time(),
    }
    meta_path = _write_meta(server_url, meta)

    deadline = time.time() + max(0.1, startup_timeout_s)
    while time.time() < deadline:
        if is_appium_reachable(server_url):
            return {
                "serverUrl": server_url,
                "reachable": True,
                "managed": True,
                "pid": process.pid,
                "command": resolved_cmd,
                "metadataPath": str(meta_path),
                "logPath": str(log_path),
                "started": True,
                "alreadyRunning": False,
            }
        if process.poll() is not None:
            _cleanup_meta(server_url)
            raise RuntimeError(
                f"Appium exited before becoming ready (exit code {process.returncode}). "
                f"See log at {log_path}"
            )
        time.sleep(0.25)

    if process.poll() is not None:
        _cleanup_meta(server_url)
        raise RuntimeError(
            f"Appium exited before becoming ready (exit code {process.returncode}). "
            f"See log at {log_path}"
        )

    try:
        process.terminate()
        process.wait(timeout=2)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass
    _cleanup_meta(server_url)
    raise RuntimeError(
        f"Appium did not become reachable within {startup_timeout_s:.1f}s. "
        f"See log at {log_path}"
    )


def _terminate_pid(pid: int, force: bool) -> None:
    if os.name == "nt":
        sig = signal.SIGTERM
        if force and hasattr(signal, "SIGKILL"):
            sig = signal.SIGKILL
        os.kill(pid, sig)
        return

    if force:
        os.killpg(pid, signal.SIGKILL)
    else:
        os.killpg(pid, signal.SIGTERM)


def stop_managed_appium(server_url: str, force: bool = False, timeout_s: float = 5.0) -> Dict[str, Any]:
    meta = _read_meta(server_url)
    if not meta:
        return {
            "serverUrl": server_url,
            "stopped": False,
            "managed": False,
            "reason": "no_managed_process",
            "reachable": is_appium_reachable(server_url),
            "metadataPath": str(_meta_path(server_url)),
            "logPath": str(_log_path(server_url)),
        }

    pid = int(meta.get("pid", -1))
    if not _pid_exists(pid):
        _cleanup_meta(server_url)
        return {
            "serverUrl": server_url,
            "stopped": False,
            "managed": False,
            "reason": "stale_metadata",
            "reachable": is_appium_reachable(server_url),
            "pid": pid,
            "metadataPath": str(_meta_path(server_url)),
            "logPath": str(_log_path(server_url)),
        }

    _terminate_pid(pid, force=force)
    deadline = time.time() + max(0.1, timeout_s)
    while time.time() < deadline:
        if not _pid_exists(pid):
            _cleanup_meta(server_url)
            return {
                "serverUrl": server_url,
                "stopped": True,
                "managed": True,
                "pid": pid,
                "reachable": is_appium_reachable(server_url),
                "metadataPath": str(_meta_path(server_url)),
                "logPath": str(_log_path(server_url)),
            }
        time.sleep(0.1)

    raise RuntimeError(
        f"Failed to stop managed Appium process {pid} within {timeout_s:.1f}s. "
        f"Retry with --force."
    )
