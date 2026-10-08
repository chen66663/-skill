#!/usr/bin/env python3
"""Parse component-list exports from EDA/BOM tools into a stable inventory.

Supported component-list shapes include:

1. Multiline BOM-card records:
       C0402 ! CC0402JRNPO9BN470容值:47pF;精度:±5% ! 47pF ,
               ; CC3
       ,

2. Inline BOM-card records:
       C0402 ! CC0402JRNPO9BN470 ! 47pF ; CC3

3. Delimited BOM tables with headers (CSV/TSV):
       Comment,Designator,Footprint,LCSC Part #
       100nF,"C1,C2",0603,C14663

The parser is intentionally read-only. It normalizes component metadata but
does not claim that a component-list export contains schematic connectivity.
Netlists containing $PACKAGES and $NETS are deliberately handed off to
parse_tel_netlist.py instead of being flattened into component records.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


URL_RE = re.compile(r"https?://[^\s,;]+")
RECORD_RE = re.compile(r"^\s*(?P<footprint>.+?)\s*!\s*(?P<part>.+?)\s*!\s*(?P<value>.*?)\s*,?\s*$")
REFERENCE_LINE_RE = re.compile(r"^\s*;\s*(?P<references>.*?)\s*$")
ATTRIBUTE_RE = re.compile(r"^\s*(?P<key>[^:]+?)\s*:\s*(?P<value>.*?)\s*$")
TEL_SECTION_RE = re.compile(r"^\$[A-Z0-9_]+(?:\s+.*)?$")
RANGE_DESIGNATOR_RE = re.compile(
    r"^(?P<left_prefix>[A-Za-z]+)(?P<left_number>\d+)"
    r"\s*[-~.]{1,2}\s*"
    r"(?:(?P<right_prefix>[A-Za-z]+))?(?P<right_number>\d+)$"
)

ATTRIBUTE_LABELS = (
    r"容值",
    r"阻值",
    r"电感量",
    r"电容",
    r"电阻",
    r"精度",
    r"误差",
    r"容差",
    r"额定\s*电压",
    r"耐压",
    r"工作\s*电压",
    r"额定\s*电流",
    r"额定\s*功率",
    r"功率",
    r"电流",
    r"材质\s*\(\s*温度系数\s*\)",
    r"温度\s*系\s*数",
    r"封装",
    r"品牌",
    r"厂商",
    r"类型",
    r"极性",
    r"频率",
    r"负载\s*电容",
    r"饱和\s*电流",
    r"DCR",
    r"ESR",
    r"VDS",
    r"VGS",
    r"RDS\s*\(?\s*on\s*\)?",
)
ATTRIBUTE_START_RE = re.compile(r"(?=(?:%s)\s*:)" % "|".join(ATTRIBUTE_LABELS))

COLUMN_ALIASES = {
    "designators": {
        "designator",
        "designators",
        "reference",
        "references",
        "refdes",
        "ref",
        "reference designator",
        "reference designators",
        "part reference",
        "part references",
        "位号",
        "位号列表",
        "元件位号",
        "元件序号",
        "元件编号",
        "参考位号",
    },
    "footprint": {
        "footprint",
        "footprints",
        "package",
        "packages",
        "封装",
        "封装/外壳",
    },
    "part_number": {
        "mpn",
        "manufacturer part number",
        "manufacturer part",
        "part number",
        "part",
        "model",
        "libref",
        "lib ref",
        "designation",
        "lcsc part",
        "lcsc part number",
        "lcsc part #",
        "lcsc编号",
        "jlcpcb part #",
        "supplier part",
        "supplier part number",
        "型号",
        "元件型号",
        "规格型号",
        "商品编号",
        "立创编号",
        "立创料号",
    },
    "value": {
        "value",
        "comment",
        "parameter",
        "parameter value",
        "参数",
        "参数值",
        "数值",
        "值",
    },
    "attributes": {
        "attribute",
        "attributes",
        "properties",
        "property",
        "specification",
        "specifications",
        "description",
        "属性",
        "关键属性",
        "规格",
        "描述",
        "说明",
    },
    "datasheet_urls": {
        "datasheet",
        "data sheet",
        "datasheet url",
        "datasheet link",
        "数据手册",
        "手册",
        "手册链接",
    },
    "quantity": {
        "qty",
        "quantity",
        "数量",
        "用量",
    },
}


def normalize_column_label(value: str) -> str:
    value = value.strip().lower()
    value = value.replace("（", "(").replace("）", ")")
    return re.sub(r"[\s_\-/#.()\[\]{}:：]+", "", value)


COLUMN_BY_ALIAS = {
    normalize_column_label(alias): field_name
    for field_name, aliases in COLUMN_ALIASES.items()
    for alias in aliases
}


@dataclass
class ComponentRecord:
    footprint: str
    part_number: str
    value: str
    attributes: List[Tuple[str, str]] = field(default_factory=list)
    datasheet_urls: List[str] = field(default_factory=list)
    designators: List[str] = field(default_factory=list)
    unknown_fields: List[str] = field(default_factory=list)
    source_line: int = 0
    source_text: str = ""


def normalize_key(value: str) -> str:
    value = re.sub(r"\s+", "", value)
    return value.replace("（", "(").replace("）", ")")


def normalize_value(value: str) -> str:
    value = value.strip().strip("'\"")
    value = value.replace("µ", "u").replace("μ", "u")
    return re.sub(r"\s+", "", value).lower()


def parse_part_text(text: str) -> Tuple[str, List[Tuple[str, str]], List[str], List[str]]:
    urls = URL_RE.findall(text)
    without_urls = URL_RE.sub("", text)
    chunks = [chunk.strip() for chunk in without_urls.split(";")]
    chunks = [chunk for chunk in chunks if chunk]
    if not chunks:
        return "", [], urls, []

    first = chunks[0]
    match = ATTRIBUTE_START_RE.search(first)
    if match:
        part_number = first[: match.start()].strip()
        chunks[0] = first[match.start() :]
    else:
        colon = first.find(":")
        if colon > 0:
            part_number = first[:colon].strip()
            chunks[0] = first[colon:]
        else:
            part_number = first.strip()
            chunks[0] = ""

    attributes: List[Tuple[str, str]] = []
    unknown: List[str] = []
    for chunk in chunks:
        if not chunk:
            continue
        attribute = ATTRIBUTE_RE.match(chunk)
        if not attribute:
            unknown.append(chunk)
            continue
        key = normalize_key(attribute.group("key"))
        value = attribute.group("value").strip()
        if key and value:
            attributes.append((key, value))
    return part_number, attributes, urls, unknown


def expand_designator_range(token: str) -> List[str]:
    match = RANGE_DESIGNATOR_RE.match(token)
    if not match:
        return [token]

    left_prefix = match.group("left_prefix")
    right_prefix = match.group("right_prefix") or left_prefix
    if right_prefix.upper() != left_prefix.upper():
        return [token]

    start = int(match.group("left_number"))
    end = int(match.group("right_number"))
    if end < start or end - start > 1000:
        return [token]

    width = max(len(match.group("left_number")), len(match.group("right_number")))
    return [
        "%s%0*d" % (left_prefix, width, number)
        for number in range(start, end + 1)
    ]


def parse_designators(text: str) -> List[str]:
    text = text.strip().strip("'\"")
    text = re.sub(r"(?<=[A-Za-z0-9])\s*[-~]\s*(?=[A-Za-z]?\d)", "-", text)
    designators: List[str] = []
    for token in re.split(r"[\s,;]+", text):
        token = token.strip().strip("'\"")
        if token:
            designators.extend(expand_designator_range(token))
    return designators


def comparable_attribute(record: ComponentRecord, names: Sequence[str]) -> Optional[str]:
    for key, value in record.attributes:
        if key in names:
            return value
    return None


def finalize_record(
    data: Dict[str, object],
    parsed_records: List[ComponentRecord],
    warnings: List[str],
) -> None:
    raw_part = str(data["raw_part"]).strip()
    part_number, attributes, urls, unknown = parse_part_text(raw_part)
    record = ComponentRecord(
        footprint=str(data["footprint"]).strip(),
        part_number=part_number,
        value=str(data["value"]).strip().strip("'\""),
        attributes=attributes,
        datasheet_urls=urls,
        designators=list(data["designators"]),
        unknown_fields=unknown,
        source_line=int(data["source_line"]),
        source_text=str(data["source_text"]),
    )
    validate_record(record, parsed_records, warnings)


def validate_record(
    record: ComponentRecord,
    parsed_records: List[ComponentRecord],
    warnings: List[str],
) -> None:
    parsed_records.append(record)

    line = record.source_line
    if not record.footprint:
        warnings.append("第 %s 行：缺少封装" % line)
    if not record.part_number:
        warnings.append("第 %s 行：缺少型号" % line)
    if not record.designators:
        warnings.append("第 %s 行：缺少位号（例如 ; C1 C2）" % line)
    if record.unknown_fields:
        warnings.append(
            "第 %s 行：未识别字段 %s"
            % (line, "; ".join(record.unknown_fields))
        )

    expected = comparable_attribute(
        record,
        ("容值", "阻值", "电感量", "电容", "电阻"),
    )
    if expected and record.value and normalize_value(expected) != normalize_value(record.value):
        warnings.append(
            "第 %s 行：参数值 `%s` 与属性 `%s` 不一致"
            % (line, record.value, expected)
        )


def has_tel_netlist_sections(text: str) -> bool:
    sections = {
        line.strip().upper()
        for line in text.splitlines()
        if TEL_SECTION_RE.match(line.strip().upper())
    }
    return "$PACKAGES" in sections and "$NETS" in sections


def read_delimited_rows(text: str, delimiter: str) -> List[List[str]]:
    try:
        return list(csv.reader(io.StringIO(text), delimiter=delimiter))
    except csv.Error:
        return []


def detect_delimited_table(
    text: str,
) -> Optional[Tuple[str, List[List[str]], int, Dict[str, List[int]]]]:
    candidates = []
    for delimiter in ("\t", ",", ";", "|"):
        rows = read_delimited_rows(text, delimiter)
        if len(rows) < 2:
            continue

        for header_index, header in enumerate(rows[:10]):
            mapping: Dict[str, List[int]] = {}
            for column_index, value in enumerate(header):
                field_name = COLUMN_BY_ALIAS.get(normalize_column_label(value))
                if field_name:
                    mapping.setdefault(field_name, []).append(column_index)

            fields = set(mapping)
            if len(fields) < 2:
                continue
            if not fields.intersection({"designators", "part_number"}):
                continue

            score = len(fields) * 4
            if "designators" in fields:
                score += 6
            if "part_number" in fields:
                score += 4
            if "footprint" in fields:
                score += 2
            if "value" in fields:
                score += 2
            if delimiter == "\t":
                score += 1
            candidates.append((score, -header_index, delimiter, rows, header_index, mapping))

    if not candidates:
        return None
    _, _, delimiter, rows, header_index, mapping = max(
        candidates,
        key=lambda item: item[0],
    )
    return delimiter, rows, header_index, mapping


def first_cell(row: Sequence[str], indices: Iterable[int]) -> str:
    for index in indices:
        if index < len(row):
            value = row[index].strip()
            if value:
                return value
    return ""


def parse_attribute_text(text: str) -> Tuple[List[Tuple[str, str]], List[str]]:
    attributes: List[Tuple[str, str]] = []
    unknown: List[str] = []
    for chunk in re.split(r"\s*;\s*|\r?\n", text):
        chunk = chunk.strip()
        if not chunk:
            continue
        attribute = ATTRIBUTE_RE.match(chunk)
        if not attribute:
            if ":" in chunk or "：" in chunk:
                unknown.append(chunk)
            continue
        key = normalize_key(attribute.group("key"))
        value = attribute.group("value").strip()
        if key and value:
            attributes.append((key, value))
    return attributes, unknown


def parse_delimited_text(
    text: str,
    table: Tuple[str, List[List[str]], int, Dict[str, List[int]]],
    warnings: List[str],
) -> List[ComponentRecord]:
    delimiter, rows, header_index, mapping = table
    records: List[ComponentRecord] = []

    for row_index, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
        if not any(cell.strip() for cell in row):
            continue

        designator_text = first_cell(row, mapping.get("designators", []))
        footprint = first_cell(row, mapping.get("footprint", []))
        part_text = first_cell(row, mapping.get("part_number", []))
        value = first_cell(row, mapping.get("value", []))
        attribute_text = first_cell(row, mapping.get("attributes", []))
        datasheet_text = first_cell(row, mapping.get("datasheet_urls", []))
        quantity = first_cell(row, mapping.get("quantity", []))

        part_number, part_attributes, part_urls, part_unknown = parse_part_text(part_text)
        attributes, unknown = parse_attribute_text(attribute_text)
        attributes = part_attributes + attributes
        if quantity:
            attributes.append(("数量", quantity))

        datasheet_urls = URL_RE.findall(datasheet_text)
        for url in part_urls + URL_RE.findall(attribute_text):
            if url not in datasheet_urls:
                datasheet_urls.append(url)

        record = ComponentRecord(
            footprint=footprint,
            part_number=part_number,
            value=value.strip().strip("'\""),
            attributes=attributes,
            datasheet_urls=datasheet_urls,
            designators=parse_designators(designator_text),
            unknown_fields=part_unknown + unknown,
            source_line=row_index,
            source_text=delimiter.join(row).strip(),
        )
        validate_record(record, records, warnings)

    return records


def split_card_value(text: str) -> Tuple[str, List[str]]:
    value_text = re.sub(r",\s*$", "", text.strip()).strip()
    if ";" in value_text:
        value, references = value_text.split(";", 1)
        return value.strip().strip("'\""), parse_designators(references)
    return value_text.strip().strip("'\""), []


def parse_card_text(text: str, warnings: List[str]) -> List[ComponentRecord]:
    records: List[ComponentRecord] = []
    current: Optional[Dict[str, object]] = None

    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#") or stripped.startswith("//"):
            continue
        if stripped == ",":
            continue

        record_match = RECORD_RE.match(line)
        if record_match:
            if current is not None:
                finalize_record(current, records, warnings)
            value, inline_designators = split_card_value(record_match.group("value"))
            current = {
                "footprint": record_match.group("footprint"),
                "raw_part": record_match.group("part"),
                "value": value,
                "designators": inline_designators,
                "source_line": line_number,
                "source_text": line.rstrip(),
            }
            continue

        reference_match = REFERENCE_LINE_RE.match(line)
        if current is not None and reference_match:
            current["designators"].extend(
                parse_designators(reference_match.group("references"))
            )
            continue

        if current is not None:
            warnings.append("第 %s 行：当前记录中的未解析内容 `%s`" % (line_number, stripped))
        else:
            warnings.append("第 %s 行：记录外的未解析内容 `%s`" % (line_number, stripped))

    if current is not None:
        finalize_record(current, records, warnings)
    return records


def check_record_consistency(
    records: Sequence[ComponentRecord],
    warnings: List[str],
) -> None:
    designator_lines: Dict[str, List[int]] = {}
    footprint_by_part: Dict[str, str] = {}
    for record in records:
        for designator in record.designators:
            designator_lines.setdefault(designator, []).append(record.source_line)

        if record.part_number:
            previous = footprint_by_part.get(record.part_number)
            if previous is not None and previous != record.footprint:
                warnings.append(
                    "型号 `%s` 同时出现封装 `%s` 和 `%s`"
                    % (record.part_number, previous, record.footprint)
                )
            else:
                footprint_by_part[record.part_number] = record.footprint

    for designator, source_lines in designator_lines.items():
        if len(source_lines) > 1:
            warnings.append(
                "位号 `%s` 重复出现于第 %s 行"
                % (designator, ", ".join(str(line) for line in source_lines))
            )


def detect_export_format(text: str) -> str:
    if has_tel_netlist_sections(text):
        return "tel_netlist"
    if detect_delimited_table(text) is not None:
        return "delimited_table"
    if any(RECORD_RE.match(line) for line in text.splitlines()):
        return "component_card"
    return "unknown"


def parse_text(text: str) -> Tuple[List[ComponentRecord], List[str]]:
    warnings: List[str] = []
    export_format = detect_export_format(text)

    if export_format == "tel_netlist":
        warnings.append(
            "检测到 $PACKAGES/$NETS 网表；请使用 parse_tel_netlist.py 解析网络连接"
        )
        return [], warnings

    if export_format == "delimited_table":
        table = detect_delimited_table(text)
        if table is None:
            return [], ["无法识别分隔表格表头"]
        records = parse_delimited_text(text, table, warnings)
    elif export_format == "component_card":
        records = parse_card_text(text, warnings)
    else:
        return [], [
            "无法识别元件表格式；支持 BOM 卡片（封装 ! 型号 ! 参数 ; 位号）"
            "或带表头的 CSV/TSV 元件表"
        ]

    check_record_consistency(records, warnings)
    return records, warnings


def record_as_row(record: ComponentRecord) -> List[str]:
    attributes = "; ".join("%s=%s" % pair for pair in record.attributes)
    return [
        " ".join(record.designators),
        record.footprint,
        record.part_number,
        record.value,
        attributes,
        " ".join(record.datasheet_urls),
    ]


def print_tsv(records: Sequence[ComponentRecord], warnings: Sequence[str]) -> None:
    headers = ("位号", "封装", "型号", "参数值", "关键属性", "数据手册")
    print("\t".join(headers))
    for record in records:
        print("\t".join(record_as_row(record)))
    for warning in warnings:
        print(warning, file=sys.stderr)


def print_json(
    source: str,
    records: Sequence[ComponentRecord],
    warnings: Sequence[str],
    export_format: str,
) -> None:
    payload = {
        "source": source,
        "format": export_format,
        "record_count": len(records),
        "records": [asdict(record) for record in records],
        "warnings": list(warnings),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def print_lcsc_list(records: Sequence[ComponentRecord]) -> None:
    seen = set()
    for record in records:
        model = record.part_number.strip()
        if model and model not in seen:
            seen.add(model)
            print(model)


def read_source(path: str) -> Tuple[str, str]:
    if path == "-":
        return sys.stdin.read(), "<stdin>"
    source = Path(path)
    return source.read_text(encoding="utf-8-sig"), str(source)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="解析 BOM 卡片和带表头的 CSV/TSV 元件表",
    )
    parser.add_argument("source", help="输入文件；使用 - 从标准输入读取")
    parser.add_argument(
        "--format",
        choices=("tsv", "json", "lcsc"),
        default="tsv",
        help="输出格式；lcsc 输出去重后的型号列表，可交给 lcsc_lookup.py bom",
    )
    args = parser.parse_args()

    try:
        text, source_name = read_source(args.source)
    except OSError as error:
        print("读取失败: %s" % error, file=sys.stderr)
        return 1

    records, warnings = parse_text(text)
    if not records:
        print("没有解析到元件记录", file=sys.stderr)
        for warning in warnings:
            print(warning, file=sys.stderr)
        return 1

    if args.format == "tsv":
        print_tsv(records, warnings)
    elif args.format == "json":
        print_json(source_name, records, warnings, detect_export_format(text))
    else:
        print_lcsc_list(records)
        for warning in warnings:
            print(warning, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
