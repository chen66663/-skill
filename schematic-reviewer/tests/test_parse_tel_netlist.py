import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.parse_tel_netlist import parse_text


class ParseTelNetlistTests(unittest.TestCase):
    def test_parses_packages_and_nets(self):
        text = """$PACKAGES
C0402 ! CC0402JRNPO9BN470 ! 47pF ; C1
R0805 ! 0805W8F1002T5E ! '10kΩ' ; R1
LQFP-64 ! STM32F103C8T6 ! '{Value}' ; U1
$A_PROPERTIES
$NETS
NRST ; C1.2 R1.1 U1.7
GND ; C1.1 R1.2 U1.23 ,
        U1.35
$SCHEDULE
$END
"""

        netlist = parse_text(text)

        self.assertEqual([], netlist.warnings)
        self.assertEqual(3, len(netlist.packages))
        self.assertEqual("10kΩ", netlist.packages[1].value)
        self.assertEqual(["U1"], netlist.packages[2].designators)
        self.assertEqual(2, len(netlist.nets))
        self.assertEqual(
            [("C1", "2"), ("R1", "1"), ("U1", "7")],
            [(pin.designator, pin.pin) for pin in netlist.nets[0].pins],
        )
        self.assertEqual(4, len(netlist.nets[1].pins))

    def test_warns_for_unconnected_and_duplicate_pins(self):
        text = """$PACKAGES
R0805 ! PART-A ! 10k ; R1 R2
$NETS
NET1 ; R1.1 R1.1
"""

        netlist = parse_text(text)
        messages = "\n".join(netlist.warnings)

        self.assertIn("引脚 `R1.1` 在网络 `NET1` 内重复出现", messages)
        self.assertIn("位号 `R2`", messages)
        self.assertIn("只有 1 个有效引脚", messages)

    def test_does_not_treat_mechanical_parts_as_unconnected_electrical_parts(self):
        text = """$PACKAGES
SMD_BD5.0-D3.0 ! R30-1000602-Harwin ! '{Value}' ; U10
$NETS
$END
"""

        netlist = parse_text(text)

        self.assertEqual([], netlist.warnings)
    def test_accepts_reordered_alias_sections_and_alphanumeric_pins(self):
        text = """$NETWORKS
GND ; U1.A1 U2.2
$COMPONENTS
BGA-64 ! PART-U1 ! '{Value}' ; U1
SOIC-8 ! PART-U2 ! '{Value}' ; U2
$END
"""

        netlist = parse_text(text)

        self.assertEqual([], netlist.warnings)
        self.assertEqual(2, len(netlist.packages))
        self.assertEqual(1, len(netlist.nets))
        self.assertEqual(
            [("U1", "A1"), ("U2", "2")],
            [(pin.designator, pin.pin) for pin in netlist.nets[0].pins],
        )

    def test_merges_repeated_net_segments_and_reports_same_device_multi_pin(self):
        text = """$PACKAGES
QFN ! PART-U1 ! '{Value}' ; U1
SOIC ! PART-U2 ! '{Value}' ; U2
$NETS
SIG ; U1.1 U1.2
SIG ; U2.1 U2.2
"""

        netlist = parse_text(text)
        messages = "\\n".join(netlist.warnings + netlist.connectivity_findings)

        self.assertEqual(1, len(netlist.nets))
        self.assertEqual(4, len(netlist.nets[0].pins))
        self.assertIn("网络 `SIG` 分成多段", messages)
        self.assertIn("同一器件 `U1` 的多个引脚", messages)
        self.assertIn("同一器件 `U2` 的多个引脚", messages)

    def test_does_not_report_normal_power_net_multi_pin_as_short(self):
        text = """$PACKAGES
QFN ! PART-U1 ! '{Value}' ; U1
$NETS
GND ; U1.1 U1.2
"""

        netlist = parse_text(text)
        messages = "\\n".join(netlist.warnings)

        self.assertNotIn("连接了同一器件", messages)
        self.assertEqual(0, len(netlist.connectivity_findings))


if __name__ == "__main__":
    unittest.main()
