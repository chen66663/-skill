import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.parse_schematic_export import parse_text


class ParseSchematicExportTests(unittest.TestCase):
    def test_parses_component_attributes_and_designators(self):
        text = (
            "C0402 ! CC0402JRNPO9BN470容值:47pF;精度:±5%;"
            "额定电压:50V;材质(温度系数):NP0;https://example.com/part.pdf ! 47pF ,\n"
            "        ; CC3\n"
            ",\n"
        )

        records, warnings = parse_text(text)

        self.assertEqual([], warnings)
        self.assertEqual(1, len(records))
        record = records[0]
        self.assertEqual("C0402", record.footprint)
        self.assertEqual("CC0402JRNPO9BN470", record.part_number)
        self.assertEqual("47pF", record.value)
        self.assertEqual(["CC3"], record.designators)
        self.assertEqual(
            [
                ("容值", "47pF"),
                ("精度", "±5%"),
                ("额定电压", "50V"),
                ("材质(温度系数)", "NP0"),
            ],
            record.attributes,
        )
        self.assertEqual(["https://example.com/part.pdf"], record.datasheet_urls)

    def test_warns_for_value_mismatch_and_duplicate_designator(self):
        text = (
            "C0603 ! PART-A容值:10nF;额定电压:50V ! 1nF ,\n"
            "        ; C1\n"
            ",\n"
            "C0603 ! PART-B容值:100nF;额定电压:50V ! 100nF ,\n"
            "        ; C1\n"
            ",\n"
        )

        records, warnings = parse_text(text)

        self.assertEqual(2, len(records))
        self.assertTrue(any("参数值 `1nF` 与属性 `10nF` 不一致" in item for item in warnings))
        self.assertTrue(any("位号 `C1` 重复出现" in item for item in warnings))

    def test_accepts_spaces_in_temperature_coefficient_label(self):
        text = (
            "C0603 ! PART-C容值:10nF;温度系  数:X7R ! 10nF ,\n"
            "        ; C2 C3\n"
            ",\n"
        )

        records, warnings = parse_text(text)

        self.assertEqual([], warnings)
        self.assertEqual(
            [("容值", "10nF"), ("温度系数", "X7R")],
            records[0].attributes,
        )
        self.assertEqual(["C2", "C3"], records[0].designators)

    def test_parses_inline_card_designators(self):
        text = "C0402 ! PART-D ! '47pF' ; C1 C2 ,\n"

        records, warnings = parse_text(text)

        self.assertEqual([], warnings)
        self.assertEqual(1, len(records))
        self.assertEqual("PART-D", records[0].part_number)
        self.assertEqual("47pF", records[0].value)
        self.assertEqual(["C1", "C2"], records[0].designators)

    def test_expands_designator_ranges(self):
        text = (
            "C0603 ! PART-E ! 100nF ,\n"
            "        ; R1-R3 C5\n"
            ",\n"
        )

        records, warnings = parse_text(text)

        self.assertEqual([], warnings)
        self.assertEqual(["R1", "R2", "R3", "C5"], records[0].designators)

    def test_parses_delimited_bom_table(self):
        text = (
            "Comment,Designator,Footprint,LCSC Part #,Attributes,Datasheet\n"
            "\"100nF\",\"C1,C2\",C0603,C14663,"
            "\"额定电压:50V;材质(温度系数):X7R\",https://example.com/C14663.pdf\n"
        )

        records, warnings = parse_text(text)

        self.assertEqual([], warnings)
        self.assertEqual(1, len(records))
        record = records[0]
        self.assertEqual("C0603", record.footprint)
        self.assertEqual("C14663", record.part_number)
        self.assertEqual("100nF", record.value)
        self.assertEqual(["C1", "C2"], record.designators)
        self.assertEqual(
            [("额定电压", "50V"), ("材质(温度系数)", "X7R")],
            record.attributes,
        )
        self.assertEqual(
            ["https://example.com/C14663.pdf"],
            record.datasheet_urls,
        )

    def test_rejects_tel_netlist_as_component_export(self):
        text = (
            "$PACKAGES\n"
            "C0402 ! PART-F ! 47pF ; C1\n"
            "$NETS\n"
            "GND ; C1.1 C2.1\n"
            "$END\n"
        )

        records, warnings = parse_text(text)

        self.assertEqual([], records)
        self.assertTrue(any("parse_tel_netlist.py" in item for item in warnings))


if __name__ == "__main__":
    unittest.main()
