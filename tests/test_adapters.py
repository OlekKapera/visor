from __future__ import annotations

import unittest

from framework.adapters import ACCESSIBILITY_ID, _parse_target, _resolve_tap_mode


class AdapterSelectorTests(unittest.TestCase):
    def test_parse_target_uses_accessibility_id_for_plain_selector(self):
        by, value = _parse_target("Increment")
        self.assertEqual(by, ACCESSIBILITY_ID)
        self.assertEqual(value, "Increment")

    def test_parse_target_uses_xpath_for_text_selector(self):
        by, value = _parse_target("text=1")
        self.assertEqual(by, "xpath")
        self.assertIn("contains(@text, '1')", value)
        self.assertIn("contains(@content-desc, '1')", value)

    def test_parse_target_supports_android_uiautomator(self):
        by, value = _parse_target('uiautomator=new UiSelector().text("OK")')
        self.assertEqual(by, "-android uiautomator")
        self.assertIn('text("OK")', value)

    def test_resolve_tap_mode_requires_complete_coordinates(self):
        with self.assertRaises(ValueError):
            _resolve_tap_mode({"x": 10})

    def test_resolve_tap_mode_rejects_mixed_target_and_coordinates(self):
        with self.assertRaises(ValueError):
            _resolve_tap_mode({"target": "foo", "x": 1, "y": 2})


if __name__ == "__main__":
    unittest.main()
