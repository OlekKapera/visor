from __future__ import annotations

import base64
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from appium import webdriver
    from appium.options.android import UiAutomator2Options
    from appium.options.ios import XCUITestOptions
    from appium.webdriver.common.appiumby import AppiumBy
    from selenium.webdriver.common.by import By
except Exception:  # pragma: no cover
    webdriver = None
    UiAutomator2Options = None
    XCUITestOptions = None
    AppiumBy = None
    By = None


DEFAULT_SERVER_URL = "http://127.0.0.1:4723"
DEFAULT_ANDROID_APP = "com.example.app"
DEFAULT_IOS_BUNDLE = "com.example.app"
DEFAULT_ANDROID_DEVICE = "emulator-5554"
DEFAULT_IOS_DEVICE = "iPhone 17 Pro"

# 1x1 transparent PNG
_MINI_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO7Z0x8AAAAASUVORK5CYII="
)

ACCESSIBILITY_ID = getattr(AppiumBy, "ACCESSIBILITY_ID", "accessibility id")
XPATH = getattr(By, "XPATH", "xpath")
ELEMENT_ID = getattr(By, "ID", "id")
ANDROID_UIAUTOMATOR = getattr(AppiumBy, "ANDROID_UIAUTOMATOR", "-android uiautomator")
IOS_PREDICATE = getattr(AppiumBy, "IOS_PREDICATE", "-ios predicate string")
IOS_CLASS_CHAIN = getattr(AppiumBy, "IOS_CLASS_CHAIN", "-ios class chain")


@dataclass
class AdapterCapability:
    platform: str
    commands: List[str]


class PlatformAdapter(ABC):
    @abstractmethod
    def capability(self) -> AdapterCapability:
        raise NotImplementedError

    @abstractmethod
    def navigate(self, args: Dict) -> Dict:
        raise NotImplementedError

    @abstractmethod
    def tap(self, args: Dict) -> Dict:
        raise NotImplementedError

    @abstractmethod
    def act(self, args: Dict) -> Dict:
        raise NotImplementedError

    @abstractmethod
    def screenshot(self, args: Dict) -> Dict:
        raise NotImplementedError

    @abstractmethod
    def wait(self, args: Dict) -> Dict:
        raise NotImplementedError

    @abstractmethod
    def source(self, args: Dict) -> Dict:
        raise NotImplementedError

    @abstractmethod
    def exists(self, target: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError


def _parse_target(target: str) -> Tuple[str, str]:
    if target.startswith("text="):
        value = target.split("=", 1)[1]
        xpath = (
            f"//*[contains(@text, '{value}') or contains(@content-desc, '{value}') "
            f"or contains(@label, '{value}') or contains(@name, '{value}') or contains(@value, '{value}')]"
        )
        return XPATH, xpath
    if target.startswith("id="):
        value = target.split("=", 1)[1]
        return ELEMENT_ID, value
    if target.startswith("xpath="):
        value = target.split("=", 1)[1]
        return XPATH, value
    if target.startswith("uiautomator="):
        value = target.split("=", 1)[1]
        return ANDROID_UIAUTOMATOR, value
    if target.startswith("predicate="):
        value = target.split("=", 1)[1]
        return IOS_PREDICATE, value
    if target.startswith("classchain="):
        value = target.split("=", 1)[1]
        return IOS_CLASS_CHAIN, value
    if target.startswith("accessibility="):
        value = target.split("=", 1)[1]
        return ACCESSIBILITY_ID, value
    return ACCESSIBILITY_ID, target


def _resolve_tap_mode(args: Dict) -> str:
    has_target = "target" in args and args["target"] is not None
    has_x = "x" in args and args["x"] is not None
    has_y = "y" in args and args["y"] is not None

    if has_target and (has_x or has_y):
        raise ValueError("tap cannot mix target with x/y coordinates")
    if has_target:
        return "target"
    if has_x and has_y:
        return "coordinates"
    if has_x != has_y:
        raise ValueError("tap coordinate mode requires both x and y")
    raise ValueError("tap requires target or x/y coordinates")


def _png_dimensions(path: Path) -> Tuple[int | None, int | None]:
    try:
        with path.open("rb") as f:
            header = f.read(24)
    except OSError:
        return None, None

    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        return None, None
    return int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")


def _env(preferred: str, legacy: str, default: str | None = None) -> str | None:
    return os.getenv(preferred) or os.getenv(legacy) or default


def _env_bool(preferred: str, legacy: str, default: bool = False) -> bool:
    raw = _env(preferred, legacy)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class RealAppiumAdapter(PlatformAdapter):
    def __init__(
        self,
        platform: str,
        server_url: str,
        device: Optional[str] = None,
        app_id: Optional[str] = None,
        attach_to_running: bool = False,
    ) -> None:
        self.platform = platform
        self.server_url = server_url
        self.device = device
        self.app_id = app_id
        self.attach_to_running = attach_to_running
        self.driver = self._create_driver()

    def _create_driver(self):
        if webdriver is None:
            raise RuntimeError("Appium/Selenium dependencies are missing. Install in runtime environment or use --mock.")

        attach_to_running = self.attach_to_running or _env_bool(
            "VISOR_ATTACH_TO_RUNNING",
            "PATF_ATTACH_TO_RUNNING",
            default=False,
        )

        if self.platform == "android":
            options = UiAutomator2Options()
            options.platform_name = "Android"
            options.automation_name = "UiAutomator2"
            options.udid = self.device or _env("VISOR_ANDROID_DEVICE", "PATF_ANDROID_DEVICE", DEFAULT_ANDROID_DEVICE)
            options.app_package = self.app_id or _env("VISOR_ANDROID_APP_PACKAGE", "PATF_ANDROID_APP_PACKAGE", DEFAULT_ANDROID_APP)
            options.app_activity = _env("VISOR_ANDROID_APP_ACTIVITY", "PATF_ANDROID_APP_ACTIVITY", ".MainActivity")
            options.new_command_timeout = 60
            if attach_to_running:
                options.set_capability("noReset", True)
                options.set_capability("fullReset", False)
                options.set_capability("autoLaunch", False)
                options.set_capability("dontStopAppOnReset", True)
            return webdriver.Remote(self.server_url, options=options)

        if self.platform == "ios":
            options = XCUITestOptions()
            options.platform_name = "iOS"
            options.automation_name = "XCUITest"
            options.device_name = self.device or _env("VISOR_IOS_DEVICE", "PATF_IOS_DEVICE", DEFAULT_IOS_DEVICE)
            options.bundle_id = self.app_id or _env("VISOR_IOS_BUNDLE_ID", "PATF_IOS_BUNDLE_ID", DEFAULT_IOS_BUNDLE)
            options.new_command_timeout = 60
            if attach_to_running:
                options.set_capability("noReset", True)
                options.set_capability("fullReset", False)
                options.set_capability("autoLaunch", False)
                options.set_capability("shouldTerminateApp", False)
                options.set_capability("forceAppLaunch", False)
            return webdriver.Remote(self.server_url, options=options)

        raise ValueError(f"Unsupported platform: {self.platform}")

    def capability(self) -> AdapterCapability:
        return AdapterCapability(platform=self.platform, commands=["navigate", "tap", "act", "screenshot", "wait", "source"])

    def navigate(self, args: Dict) -> Dict:
        to = args.get("to", "")
        if to:
            self.driver.get(to)
        return {"action": "navigate", "platform": self.platform, "args": {"to": to}}

    def tap(self, args: Dict) -> Dict:
        if _resolve_tap_mode(args) == "coordinates":
            x, y = self._resolve_coordinates(args)
            self._tap_point(x, y)
            return {
                "action": "tap",
                "platform": self.platform,
                "args": {"x": x, "y": y, "normalized": bool(args.get("normalized", False))},
            }

        target = args["target"]
        by, value = _parse_target(target)
        elem = self.driver.find_element(by, value)
        elem.click()
        return {"action": "tap", "platform": self.platform, "args": {"target": target}}

    def act(self, args: Dict) -> Dict:
        name = args.get("name")
        value = args.get("value", "")
        target = args.get("target")
        if name == "type" and target:
            by, sel = _parse_target(target)
            elem = self.driver.find_element(by, sel)
            elem.clear()
            elem.send_keys(value)
            return {"action": "act", "platform": self.platform, "args": {"name": name, "target": target, "value": value}}
        if name == "back":
            self.driver.back()
            return {"action": "act", "platform": self.platform, "args": {"name": name}}
        raise ValueError("Unsupported act operation; use --name type --target <selector> --value <text> or --name back")

    def screenshot(self, args: Dict) -> Dict:
        label = args.get("label", "capture")
        requested_path = args.get("path")
        file_path = Path(requested_path) if requested_path else Path(f"{label}.png")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        ok = self.driver.get_screenshot_as_file(str(file_path))
        if not ok:
            raise RuntimeError("Appium failed to persist screenshot")
        width, height = _png_dimensions(file_path)
        return {
            "action": "screenshot",
            "platform": self.platform,
            "args": {"label": label, "file": file_path.name, "path": str(file_path), "width": width, "height": height},
        }

    def wait(self, args: Dict) -> Dict:
        ms = int(args.get("ms", 0))
        if ms < 0:
            raise ValueError("wait requires non-negative ms")
        time.sleep(ms / 1000)
        return {"action": "wait", "platform": self.platform, "args": {"ms": ms}}

    def source(self, args: Dict) -> Dict:
        label = args.get("label", "source")
        requested_path = args.get("path")
        file_path = Path(requested_path) if requested_path else Path(f"{label}.xml")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        content = self.driver.page_source
        file_path.write_text(content, encoding="utf-8")
        return {
            "action": "source",
            "platform": self.platform,
            "args": {"label": label, "file": file_path.name, "path": str(file_path), "format": "xml", "bytes": file_path.stat().st_size},
        }

    def exists(self, target: str) -> bool:
        by, value = _parse_target(target)
        return len(self.driver.find_elements(by, value)) > 0

    def _resolve_coordinates(self, args: Dict) -> Tuple[int, int]:
        x = float(args["x"])
        y = float(args["y"])
        if args.get("normalized", False):
            size = self.driver.get_window_size()
            x = x * size["width"]
            y = y * size["height"]
        return round(x), round(y)

    def _tap_point(self, x: int, y: int) -> None:
        if self.platform == "android":
            self.driver.execute_script("mobile: clickGesture", {"x": x, "y": y})
            return
        if self.platform == "ios":
            self.driver.execute_script("mobile: tap", {"x": x, "y": y})
            return
        raise ValueError(f"Coordinate tap is unsupported for platform: {self.platform}")

    def close(self) -> None:
        if self.driver:
            self.driver.quit()


class MockAdapter(PlatformAdapter):
    def __init__(self, platform: str) -> None:
        self.platform = platform

    def capability(self) -> AdapterCapability:
        return AdapterCapability(platform=self.platform, commands=["navigate", "tap", "act", "screenshot", "wait", "source"])

    def navigate(self, args: Dict) -> Dict:
        return {"action": "navigate", "platform": self.platform, "args": args}

    def tap(self, args: Dict) -> Dict:
        _resolve_tap_mode(args)
        return {"action": "tap", "platform": self.platform, "args": args}

    def act(self, args: Dict) -> Dict:
        return {"action": "act", "platform": self.platform, "args": args}

    def screenshot(self, args: Dict) -> Dict:
        label = args.get("label", "capture")
        requested_path = args.get("path")
        file_path = Path(requested_path) if requested_path else Path(f"{label}.png")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(_MINI_PNG)
        width, height = _png_dimensions(file_path)
        return {
            "action": "screenshot",
            "platform": self.platform,
            "args": {"label": label, "file": file_path.name, "path": str(file_path), "width": width, "height": height},
        }

    def wait(self, args: Dict) -> Dict:
        ms = int(args.get("ms", 0))
        if ms < 0:
            raise ValueError("wait requires non-negative ms")
        return {"action": "wait", "platform": self.platform, "args": {"ms": ms}}

    def source(self, args: Dict) -> Dict:
        label = args.get("label", "source")
        requested_path = args.get("path")
        file_path = Path(requested_path) if requested_path else Path(f"{label}.xml")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        content = f'<hierarchy platform="{self.platform}"><node text="mock" /></hierarchy>\n'
        file_path.write_text(content, encoding="utf-8")
        return {
            "action": "source",
            "platform": self.platform,
            "args": {"label": label, "file": file_path.name, "path": str(file_path), "format": "xml", "bytes": file_path.stat().st_size},
        }

    def exists(self, target: str) -> bool:
        lowered = target.lower()
        return "missing" not in lowered and "not_found" not in lowered

    def close(self) -> None:
        return None


def get_adapter(
    platform: str,
    server_url: str = DEFAULT_SERVER_URL,
    device: Optional[str] = None,
    use_mock: bool = False,
    app_id: Optional[str] = None,
    attach_to_running: bool = False,
) -> PlatformAdapter:
    normalized = platform.lower()
    if use_mock:
        return MockAdapter(normalized)
    return RealAppiumAdapter(
        normalized,
        server_url=server_url,
        device=device,
        app_id=app_id,
        attach_to_running=attach_to_running,
    )
