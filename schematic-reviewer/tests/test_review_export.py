import json
import unittest
from pathlib import Path

import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.review_export import run_review, values_equivalent


def item(
    model,
    package="0603",
    stock=100,
    attributes=None,
):
    return {
        "componentCode": "C123",
        "componentBrandEn": "TEST",
        "componentModelEn": model,
        "componentSpecificationEn": package,
        "stockCount": stock,
        "componentPrices": [{"productPrice": 0.01}],
        "attributes": attributes or [],
        "describe": "",
    }


def lookup(model, **kwargs):
    return {
        "mpn": model,
        "item": item(model),
        "exact": True,
        "error": None,
    }


class ReviewExportTests(unittest.TestCase):
    def test_equivalent_values_handle_np0_units_and_tolerance(self):
        self.assertTrue(values_equivalent("0.1uF", "100nF"))
        self.assertTrue(values_equivalent("4700pF", "4.7nF"))
        self.assertTrue(values_equivalent("NP0", "C0G"))
        self.assertTrue(values_equivalent("±10%", "10%"))
        self.assertTrue(values_equivalent("1MΩ", "1MOhm"))
        self.assertFalse(values_equivalent("1MΩ", "1mΩ"))
        self.assertFalse(values_equivalent("25V", "50V"))

    def test_clean_export_passes(self):
        text = (
            "C0402 ! CC0402JRNPO9BN470容值:47pF;精度:±5%;"
            "额定电压:50V;材质(温度系数):NP0 ! 47pF ,\n"
            "        ; C1\n"
            ",\n"
        )

        def exact_lookup(model, **kwargs):
            return {
                "mpn": model,
                "item": item(
                    model,
                    package="0402",
                    attributes=[
                        {
                            "attribute_name_en": "Capacitance",
                            "attribute_value_name": "47pF",
                        },
                        {
                            "attribute_name_en": "Tolerance",
                            "attribute_value_name": "±5%",
                        },
                        {
                            "attribute_name_en": "Voltage Rating",
                            "attribute_value_name": "50V",
                        },
                        {
                            "attribute_name_en": "Temperature Coefficient",
                            "attribute_value_name": "NP0",
                        },
                    ],
                ),
                "exact": True,
                "error": None,
            }

        payload = run_review(
            "export.txt",
            text,
            limit=20,
            jobs=2,
            cache_path="cache.json",
            cache_ttl=3600,
            use_cache=False,
            lookup_fn=exact_lookup,
        )

        self.assertEqual(0, payload["issue_count"])
        self.assertEqual(1, payload["model_count"])
        self.assertEqual("pass", payload["models"][0]["status"])
        json.dumps(payload, ensure_ascii=False)

    def test_reports_stock_package_and_parameter_mismatch(self):
        text = (
            "C0603 ! PART-A容值:100nF;额定电压:25V;"
            "材质(温度系数):X7R ! 100nF ,\n"
            "        ; C1\n"
            ",\n"
        )

        def mismatched_lookup(model, **kwargs):
            return {
                "mpn": model,
                "item": item(
                    model,
                    package="0402",
                    stock=0,
                    attributes=[
                        {
                            "attribute_name_en": "Capacitance",
                            "attribute_value_name": "100nF",
                        },
                        {
                            "attribute_name_en": "Voltage Rating",
                            "attribute_value_name": "50V",
                        },
                        {
                            "attribute_name_en": "Temperature Coefficient",
                            "attribute_value_name": "X7R",
                        },
                    ],
                ),
                "exact": True,
                "error": None,
            }

        payload = run_review(
            "export.txt",
            text,
            limit=20,
            jobs=2,
            cache_path="cache.json",
            cache_ttl=3600,
            use_cache=False,
            lookup_fn=mismatched_lookup,
        )

        codes = {
            issue["code"]
            for issue in payload["models"][0]["issues"]
        }
        self.assertEqual(
            {
                "out_of_stock",
                "package_mismatch",
                "parameter_mismatch",
            },
            codes,
        )
        self.assertEqual(3, payload["issue_count"])

    def test_no_exact_match_does_not_claim_parameter_match(self):
        text = (
            "C0603 ! PART-X容值:100nF;额定电压:50V ! 100nF ,\n"
            "        ; C1\n"
            ",\n"
        )

        def approximate_lookup(model, **kwargs):
            return {
                "mpn": model,
                "item": item("PART-OTHER"),
                "exact": False,
                "error": None,
            }

        payload = run_review(
            "export.txt",
            text,
            limit=20,
            jobs=2,
            cache_path="cache.json",
            cache_ttl=3600,
            use_cache=False,
            lookup_fn=approximate_lookup,
        )

        self.assertEqual(1, payload["issue_count"])
        self.assertEqual(
            "no_exact_match",
            payload["models"][0]["issues"][0]["code"],
        )

    def test_reports_critical_values_missing_from_export(self):
        text = (
            "C0603 ! PART-C容值:100nF ! 100nF ,\n"
            "        ; C1\n"
            ",\n"
        )

        payload = run_review(
            "export.txt",
            text,
            limit=20,
            jobs=2,
            cache_path="cache.json",
            cache_ttl=3600,
            use_cache=False,
            lookup_fn=lookup,
        )

        messages = [
            issue["message"]
            for issue in payload["models"][0]["issues"]
        ]
        self.assertTrue(any("缺少额定电压" in message for message in messages))
        self.assertTrue(any("缺少温度系数" in message for message in messages))

    def test_delimited_table_enters_review_pipeline(self):
        text = (
            "Comment,Designator,Footprint,LCSC Part #,Attributes\n"
            "\"100nF\",\"C1,C2\",0603,C14663,"
            "\"容值:100nF;额定电压:50V;材质(温度系数):X7R\"\n"
        )

        def exact_lookup(model, **kwargs):
            return {
                "mpn": model,
                "item": item(
                    model,
                    attributes=[
                        {
                            "attribute_name_en": "Capacitance",
                            "attribute_value_name": "100nF",
                        },
                        {
                            "attribute_name_en": "Voltage Rating",
                            "attribute_value_name": "50V",
                        },
                        {
                            "attribute_name_en": "Temperature Coefficient",
                            "attribute_value_name": "X7R",
                        },
                    ],
                ),
                "exact": True,
                "error": None,
            }

        payload = run_review(
            "export.csv",
            text,
            limit=20,
            jobs=2,
            cache_path="cache.json",
            cache_ttl=3600,
            use_cache=False,
            lookup_fn=exact_lookup,
        )

        self.assertEqual(0, payload["issue_count"])
        self.assertEqual(1, payload["record_count"])
        self.assertEqual(1, payload["model_count"])
        self.assertEqual(["C1", "C2"], payload["models"][0]["designators"])


if __name__ == "__main__":
    unittest.main()
