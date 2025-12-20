import unittest

from generate_plugin import extract_keywords, render_plugin_source, slug_to_class_name


class GeneratePluginTestCase(unittest.TestCase):
    def test_slug_to_class_name(self) -> None:
        self.assertEqual(slug_to_class_name("charge_point-app"), "ChargePointApp")

    def test_extract_keywords_limit(self) -> None:
        text = "ChargePoint energy Energy station charge station"
        self.assertEqual(extract_keywords(text, limit=3), ["energy", "station", "chargepoint"])

    def test_render_plugin_source_contains_fields(self) -> None:
        source = render_plugin_source("MyAppPlugin", "my_app", "My App", ["charge", "energy"])
        self.assertIn("class MyAppPlugin(ChargingAppPlugin)", source)
        self.assertIn('name = "my_app"', source)
        self.assertIn('"charge"', source)
        self.assertIn("NotImplementedError", source)


if __name__ == "__main__":
    unittest.main()
