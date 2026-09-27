#!/usr/bin/env python3
"""Parse Allegro-style schematic netlists with $PACKAGES and $NETS.

The input is a connectivity netlist, not just a component list. Section order and section aliases may vary. A pin token
such as U22.25 is evidence that designator U22 pin 25 belongs to that net.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


SECTION_RE = re.compile(r"^\s*(?P<section>\$[A-Z0-9_]+)(?:\s*[,;:].*)?$", re.IGNORECASE)
PACKAGE_RE = re.compile(
    r"^\s*(?P<footprint>[^!]+?)\s*!\s*(?P<part>[^!]+?)\s*!\s*(?P<rest>.*?)\s*$"
)
PIN_RE = re.compile(
    r"(?P<designator>[A-Za-z_][A-Za-z0-9_-]*)\s*[.]\s*"
    r"(?P<pin>[A-Za-z0-9_+#-]+)"
)
DESIGNATOR_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")
NET_START_RE = re.compile(r"^\s*(?P<name>[^;:,]+?)\s*(?:;|:|,)(?P<pins>.*)$")

PACKAGE_SECTION_NAMES = {
    "$PACKAGES", "$PACKAGE", "$COMPONENTS", "$COMPONENT", "$PARTS",
    "$DEVICES", "$DEVICE_LIST", "$COMPONENT_LIST",
}
NET_SECTION_NAMES = {
    "$NETS", "$NET", "$NETWORKS", "$CONNECTIONS", "$SIGNALS",
    "$SIGNAL_LIST",
}
IGNORED_SECTION_NAMES = {"$END", "$EOF", "$SCHEDULE", "$A_PROPERTIES"}
SECTION_ALIASES = {}
for _name in PACKAGE_SECTION_NAMES:
    SECTION_ALIASES[_name] = "$PACKAGES"
for _name in NET_SECTION_NAMES:
    SECTION_ALIASES[_name] = "$NETS"
for _name in IGNORED_SECTION_NAMES:
    SECTION_ALIASES[_name] = ""
NON_ELECTRICAL_PREFIXES = {"TP", "FID", "MH", "MTG"}
NON_ELECTRICAL_HINTS = (
    "harwin",
    "standoff",
    "spacer",
    "mounting",
    "fiducial",
    "testpoint",
    "test point",
    "mechanical",
)


@dataclass
class PackageRecord:
    footprint: str
    part_number: str
    value: str
    designators: List[str]
    source_line: int


@dataclass
class PinConnection:
    designator: str
    pin: str
    net: str
    source_line: int


@dataclass
class NetRecord:
    name: str
    pins: List[PinConnection] = field(default_factory=list)
    source_line: int = 0


@dataclass
class Netlist:
    packages: List[PackageRecord]
    nets: List[NetRecord]
    warnings: List[str]
    connectivity_findings: List[str] = field(default_factory=list)

    @property
    def designators(self) -> Dict[str, PackageRecord]:
        result: Dict[str, PackageRecord] = {}
        for package in self.packages:
            for designator in package.designators:
                result[designator] = package
        return result


def clean_token(value: str) -> str:
    return value.strip().strip("'\"")


def split_value_and_designators(text: str) -> Tuple[str, List[str]]:
    if ";" not in text:
        return clean_token(text), []
    value, references = text.split(";", 1)
    designators = [
        token
        for token in DESIGNATOR_RE.findall(references)
        if token.lower() != "value"
    ]
    return clean_token(value), designators


def is_non_electrical_package(package: PackageRecord) -> bool:
    for designator in package.designators:
        match = re.match(r"([A-Za-z]+)", designator)
        if match and match.group(1).upper() in NON_ELECTRICAL_PREFIXES:
            return True

    searchable = "%s %s" % (package.part_number, package.footprint)
    searchable = searchable.lower()
    return any(hint in searchable for hint in NON_ELECTRICAL_HINTS)


def parse_packages(lines: Sequence[Tuple[int, str]], warnings: List[str]) -> List[PackageRecord]:
    records: List[PackageRecord] = []
    current_parts: List[str] = []
    current_line = 0

    def finish() -> None:
        if not current_parts:
            return
        joined = " ".join(current_parts)
        match = PACKAGE_RE.match(joined)
        if not match:
            warnings.append("第 %s 行：$PACKAGES 记录无法解析" % current_line)
            return
        value, designators = split_value_and_designators(match.group("rest"))
        record = PackageRecord(
            footprint=match.group("footprint").strip(),
            part_number=match.group("part").strip(),
            value=value,
            designators=designators,
            source_line=current_line,
        )
        records.append(record)
        if not record.designators:
            warnings.append("第 %s 行：器件 `%s` 缺少位号" % (current_line, record.part_number))

    for line_number, line in lines:
        # A package record starts when the line contains all three card fields.
        # Do not require a specific indentation: JLC/EasyEDA exports vary.
        if line.count("!") >= 2:
            finish()
            current_parts = [line.strip().rstrip(",")]
            current_line = line_number
        elif current_parts:
            current_parts.append(line.strip().rstrip(","))
        elif line.strip():
            warnings.append("第 %s 行：$PACKAGES 中的孤立内容 `%s`" % (line_number, line.strip()))
    finish()
    return records

def parse_nets(lines: Sequence[Tuple[int, str]], warnings: List[str]) -> List[NetRecord]:
    nets: List[NetRecord] = []
    current_name = ""
    current_line = 0
    current_text: List[str] = []

    def finish() -> None:
        if not current_name:
            return
        text = " ".join(current_text)
        pins = [
            PinConnection(match.group("designator"), match.group("pin"), current_name, current_line)
            for match in PIN_RE.finditer(text)
        ]
        leftover = PIN_RE.sub("", text)
        leftover = re.sub(r"[\s,;]+", "", leftover)
        if leftover:
            warnings.append("第 %s 行：网络 `%s` 含无法识别的引脚 `%s`" % (current_line, current_name, leftover))
        unique_pin_count = len({(pin.designator, pin.pin) for pin in pins})
        if unique_pin_count < 2:
            warnings.append(
                "第 %s 行：网络 `%s` 只有 %s 个有效引脚"
                % (current_line, current_name, unique_pin_count)
            )
        nets.append(NetRecord(current_name, pins, current_line))

    for line_number, line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if line[:1].isspace():
            if current_name:
                current_text.append(stripped)
            else:
                warnings.append("第 %s 行：$NETS 中的孤立内容 `%s`" % (line_number, stripped))
            continue

        start = NET_START_RE.match(line)
        if start:
            finish()
            current_name = clean_token(start.group("name"))
            current_line = line_number
            current_text = [start.group("pins")]
            if not current_name:
                warnings.append("第 %s 行：网络名为空" % line_number)
        elif current_name:
            current_text.append(stripped)
        else:
            warnings.append("第 %s 行：$NETS 中的孤立内容 `%s`" % (line_number, stripped))
    finish()
    return nets


def merge_nets(nets: Sequence[NetRecord], findings: List[str]) -> List[NetRecord]:
    merged: Dict[str, NetRecord] = {}
    result: List[NetRecord] = []
    for net in nets:
        previous = merged.get(net.name)
        if previous is None:
            merged[net.name] = net
            result.append(net)
            continue
        previous.pins.extend(net.pins)
        findings.append(
            "网络 `%s` 分成多段（第 %s 行和第 %s 行），已合并"
            % (net.name, previous.source_line, net.source_line)
        )
    return result

def check_consistency(netlist: Netlist) -> None:
    packages = netlist.designators
    seen_designators: Dict[str, int] = {}
    for package in netlist.packages:
        for designator in package.designators:
            if designator in seen_designators:
                netlist.warnings.append(
                    "位号 `%s` 在第 %s 行和第 %s 行重复"
                    % (designator, seen_designators[designator], package.source_line)
                )
            else:
                seen_designators[designator] = package.source_line

    seen_pins: Dict[Tuple[str, str], Tuple[str, int]] = {}
    connected = set()
    undefined_pins = set()
    for net in netlist.nets:
        for pin in net.pins:
            connected.add(pin.designator)
            key = (pin.designator, pin.pin)
            previous = seen_pins.get(key)
            if previous is not None:
                previous_net, previous_line = previous
                if previous_net == net.name:
                    netlist.warnings.append(
                        "引脚 `%s.%s` 在网络 `%s` 内重复出现（第 %s 行和第 %s 行）"
                        % (
                            pin.designator,
                            pin.pin,
                            net.name,
                            previous_line,
                            pin.source_line,
                        )
                    )
                else:
                    netlist.warnings.append(
                        "引脚 `%s.%s` 同时出现在网络 `%s` 和 `%s`"
                        % (pin.designator, pin.pin, previous_net, net.name)
                    )
            else:
                seen_pins[key] = (net.name, pin.source_line)
            if pin.designator not in packages and key not in undefined_pins:
                undefined_pins.add(key)
                netlist.warnings.append(
                    "网络 `%s` 引用了未定义位号 `%s.%s`"
                    % (net.name, pin.designator, pin.pin)
                )

        # A net may intentionally tie several power/ground or multifunction pins
        # of one package together. Report it as a topology item only outside
        # obvious power/ground names, so normal multi-pin grounding is not noise.
        if not re.search(
            r"(GND|VSS|VCC|VDD|VBAT|PWR|POWER|\d+(?:\.\d+)?V)",
            net.name,
            re.IGNORECASE,
        ):
            pins_by_designator: Dict[str, List[str]] = {}
            for pin in net.pins:
                pins_by_designator.setdefault(pin.designator, []).append(pin.pin)
            for designator, pin_numbers in pins_by_designator.items():
                unique_pins = list(dict.fromkeys(pin_numbers))
                if len(unique_pins) > 1:
                    netlist.connectivity_findings.append(
                        "网络 `%s` 连接了同一器件 `%s` 的多个引脚 `%s`；请确认是多功能引脚、内部连接还是误短接"
                        % (net.name, designator, ", ".join(unique_pins))
                    )

    for designator, package in packages.items():
        if designator not in connected:
            if is_non_electrical_package(package):
                continue
            netlist.warnings.append(
                "位号 `%s`（%s）没有出现在任何网络中"
                % (designator, package.part_number)
            )

def parse_text(text: str) -> Netlist:
    warnings: List[str] = []
    sections: Dict[str, List[Tuple[int, str]]] = {}
    section_order: List[str] = []
    section = ""
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        match = SECTION_RE.match(stripped)
        if match:
            section = match.group("section").upper()
            sections.setdefault(section, [])
            if section not in section_order:
                section_order.append(section)
            continue
        if section:
            sections.setdefault(section, []).append((line_number, line.rstrip()))

    package_sections = [
        name for name in section_order
        if SECTION_ALIASES.get(name) == "$PACKAGES"
    ]
    net_sections = [
        name for name in section_order
        if SECTION_ALIASES.get(name) == "$NETS"
    ]
    if not package_sections or not net_sections:
        warnings.append(
            "不是包含器件段（$PACKAGES/$COMPONENTS）和网络段（$NETS/$NETWORKS）的网表"
        )

    packages: List[PackageRecord] = []
    for name in package_sections:
        packages.extend(parse_packages(sections.get(name, []), warnings))

    nets: List[NetRecord] = []
    for name in net_sections:
        nets.extend(parse_nets(sections.get(name, []), warnings))
    connectivity_findings: List[str] = []
    nets = merge_nets(nets, connectivity_findings)

    netlist = Netlist(packages, nets, warnings, connectivity_findings)
    check_consistency(netlist)
    return netlist

def read_source(path: str) -> Tuple[str, str]:
    if path == "-":
        return sys.stdin.read(), "<stdin>"
    source = Path(path)
    return source.read_text(encoding="utf-8-sig"), str(source)


def print_summary(netlist: Netlist) -> None:
    designator_count = sum(len(item.designators) for item in netlist.packages)
    pin_count = sum(len(item.pins) for item in netlist.nets)
    print("packages\t%s" % len(netlist.packages))
    print("designators\t%s" % designator_count)
    print("nets\t%s" % len(netlist.nets))
    print("pins\t%s" % pin_count)
    print("warnings\t%s" % len(netlist.warnings))
    print("connectivity_findings\t%s" % len(netlist.connectivity_findings))
    for warning in netlist.warnings:
        print(warning)
    for finding in netlist.connectivity_findings:
        print(finding)


def print_pins(netlist: Netlist, designator: str) -> None:
    package = netlist.designators.get(designator)
    if package is None:
        print("未找到位号 %s" % designator, file=sys.stderr)
        return
    print("%s\t%s\t%s\t%s" % (designator, package.part_number, package.value, package.footprint))
    rows = []
    for net in netlist.nets:
        for pin in net.pins:
            if pin.designator == designator:
                rows.append((pin.pin, net.name))
    for pin, net in sorted(rows, key=lambda row: row[0]):
        print("%s\t%s" % (pin, net))


def print_net(netlist: Netlist, name: str) -> None:
    matches = [net for net in netlist.nets if net.name == name]
    if not matches:
        print("未找到网络 %s" % name, file=sys.stderr)
        return
    packages = netlist.designators
    for net in matches:
        print(net.name)
        for pin in net.pins:
            package = packages.get(pin.designator)
            model = package.part_number if package else "?"
            print("%s.%s\t%s" % (pin.designator, pin.pin, model))


def print_json(source: str, netlist: Netlist) -> None:
    payload = {
        "source": source,
        "package_count": len(netlist.packages),
        "designator_count": sum(len(item.designators) for item in netlist.packages),
        "net_count": len(netlist.nets),
        "pin_count": sum(len(item.pins) for item in netlist.nets),
        "packages": [asdict(item) for item in netlist.packages],
        "nets": [
            {
                "name": net.name,
                "source_line": net.source_line,
                "pins": ["%s.%s" % (pin.designator, pin.pin) for pin in net.pins],
            }
            for net in netlist.nets
        ],
        "warnings": netlist.warnings,
        "connectivity_findings": netlist.connectivity_findings,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="解析带 $PACKAGES 和 $NETS 的原理图网表")
    parser.add_argument("source", help="输入 .tel 文件；使用 - 从标准输入读取")
    parser.add_argument("--format", choices=("summary", "json"), default="summary")
    parser.add_argument("--pins", help="输出指定位号的引脚网络")
    parser.add_argument("--net", help="输出指定网络上的器件引脚")
    args = parser.parse_args()

    try:
        text, source_name = read_source(args.source)
    except OSError as error:
        print("读取失败: %s" % error, file=sys.stderr)
        return 1

    netlist = parse_text(text)
    if args.pins:
        print_pins(netlist, args.pins)
    elif args.net:
        print_net(netlist, args.net)
    elif args.format == "json":
        print_json(source_name, netlist)
    else:
        print_summary(netlist)
    return 1 if netlist.warnings else 0


if __name__ == "__main__":
    sys.exit(main())
