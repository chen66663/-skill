import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import lcsc_lookup


class LcscLookupTests(unittest.TestCase):
    def test_fetch_cached_reuses_fresh_result(self):
        items = [{"componentModelEn": "PART-A", "stockCount": 10}]
        with tempfile.TemporaryDirectory() as directory:
            cache_path = str(Path(directory) / "cache.json")
            with mock.patch.object(
                lcsc_lookup,
                "fetch",
                return_value=(items, 1),
            ) as fetch:
                first = lcsc_lookup.fetch_cached(
                    "PART-A",
                    20,
                    cache_path=cache_path,
                    cache_ttl=3600,
                )
                second = lcsc_lookup.fetch_cached(
                    "PART-A",
                    20,
                    cache_path=cache_path,
                    cache_ttl=3600,
                )

        self.assertEqual((items, 1), first)
        self.assertEqual((items, 1), second)
        self.assertEqual(1, fetch.call_count)

    def test_no_cache_forces_each_request(self):
        items = [{"componentModelEn": "PART-A", "stockCount": 10}]
        with tempfile.TemporaryDirectory() as directory:
            cache_path = str(Path(directory) / "cache.json")
            with mock.patch.object(
                lcsc_lookup,
                "fetch",
                return_value=(items, 1),
            ) as fetch:
                lcsc_lookup.fetch_cached(
                    "PART-A",
                    20,
                    cache_path=cache_path,
                    cache_ttl=3600,
                    use_cache=False,
                )
                lcsc_lookup.fetch_cached(
                    "PART-A",
                    20,
                    cache_path=cache_path,
                    cache_ttl=3600,
                    use_cache=False,
                )

        self.assertEqual(2, fetch.call_count)

    def test_run_bom_queries_duplicate_models_once(self):
        item = {
            "componentCode": "C1",
            "componentBrandEn": "TEST",
            "componentModelEn": "PART-A",
            "componentSpecificationEn": "0603",
            "stockCount": 10,
            "componentPrices": [],
        }
        queried = []

        def fake_lookup(target, limit, cache_path, cache_ttl, use_cache):
            queried.append(target)
            return {
                "mpn": target,
                "item": item,
                "exact": target == "PART-A",
                "error": None,
            }

        with tempfile.TemporaryDirectory() as directory:
            bom_path = Path(directory) / "bom.txt"
            bom_path.write_text("PART-A\nPART-B\nPART-A\n", encoding="utf-8")
            output = StringIO()
            with mock.patch.object(
                lcsc_lookup,
                "lookup_target",
                side_effect=fake_lookup,
            ):
                with redirect_stdout(output):
                    result = lcsc_lookup.run_bom(
                        str(bom_path),
                        as_json=False,
                        limit=20,
                        jobs=2,
                        cache_path=str(Path(directory) / "cache.json"),
                        cache_ttl=3600,
                        use_cache=True,
                    )

        self.assertEqual(0, result)
        self.assertEqual(["PART-A", "PART-B"], queried)
        self.assertIn("PART-A", output.getvalue())
        self.assertIn("PART-B", output.getvalue())


if __name__ == "__main__":
    unittest.main()
