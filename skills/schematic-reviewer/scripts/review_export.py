#!/usr/bin/env python3
"""One-shot preflight for EDA/BOM component-list exports.

The command parses the export, deduplicates part numbers, queries LCSC/JLC in
parallel, and reports only records that need attention.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

try:
    from .lcsc_lookup import (
        DEFAULT_CACHE_PATH,
        DEFAULT_CACHE_TTL,
        brand,
        component_code,
        first_price,
        lookup_target,
        package,
    )
    from .parse_schematic_export import (
        ComponentRecord,
        parse_text,
        read_source,
    )
except ImportError:
    from lcsc_lookup import (
        DEFAULT_CACHE_PATH,
        DEFAULT_CACHE_TTL,
        brand,
        component_code,
        first_price,
        lookup_target,
        package,
    )
    from parse_schematic_export import (
        ComponentRecord,
        parse_text,
        read_source,
    )


PACKAGE_TOKEN_RE = re.compile(
    r"(?:"
    r"0201|0402|0603|0805|1206|1210|1812|2010|2512|"
    r"SOT-?\d+(?:-\d+)?|SOD-?\d+(?:-\d+)?|"
    r"LQFP-?\d+|QFN-?\d+|DFN-?\d+|SOIC-?\d+|"
    r"SSOP-?\d+|TSSOP-?\d+|DIP-?\d+|TO-?\d+(?:-\d+)?"
    r")"
)


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    input_labels: Tuple[str, ...]
    api_labels: Tuple[str, ...]
    critical_kinds: Tuple[str, ...] = ()


FIELD_SPECS = (
    FieldSpec(
        "capacitance",
        "容值",
        ("容值", "电容"),
        ("capacitance",),
        ("capacitor",),
    ),
    FieldSpec(
        "resistance",
        "阻值",
        ("阻值", "电阻"),
        ("resistance", "resistance value"),
        ("resistor",),
    ),
    FieldSpec(
        "inductance",
        "电感量",
        ("电感量", "电感"),
        ("inductance",),
        ("inductor",),
    ),
    FieldSpec(
        "tolerance",
        "精度",
        ("精度", "误差", "容差"),
        ("tolerance",),
        ("resistor", "crystal"),
    ),
    FieldSpec(
        "voltage",
        "额定电压",
        ("额定电压", "耐压", "工作电压"),
        (
            "voltage rating",
            "rated voltage",
            "working voltage",
            "withstanding voltage",
            "reverse voltage",
            "breakdown voltage",
            "vrrm",
        ),
        ("capacitor", "diode", "tvs"),
    ),
    FieldSpec(
        "temperature_coefficient",
        "温度系数",
        ("材质(温度系数)", "材质（温度系数）", "温度系数"),
        ("temperature coefficient", "dielectric"),
        ("capacitor",),
    ),
    FieldSpec(
        "power",
        "额定功率",
        ("额定功率", "功率"),
        ("power rating", "rated power", "power dissipation"),
        ("resistor",),
    ),
    FieldSpec(
        "current",
        "额定电流",
        ("额定电流", "电流"),
        (
            "current rating",
            "rated current",
            "continuous drain current",
            "forward current",
            "output current",
        ),
        ("diode", "mos"),
    ),
    FieldSpec(
        "saturation_current",
        "饱和电流",
        ("饱和电流",),
        ("saturation current",),
        ("inductor",),
    ),
    FieldSpec(
        "dcr",
        "DCR",
        ("DCR",),
        ("dc resistance", "dcr"),
        ("inductor",),
    ),
    FieldSpec(
        "esr",
        "ESR",
        ("ESR",),
        ("equivalent series resistance", "esr"),
    ),
    FieldSpec(
        "vds",
        "VDS",
        ("VDS",),
        ("drain source voltage", "vds"),
        ("mos",),
    ),
    FieldSpec(
        "vgs",
        "VGS",
        ("VGS",),
        ("gate source voltage", "vgs"),
        ("mos",),
    ),
    FieldSpec(
        "rds_on",
        "RDS(on)",
        ("RDS(on)", "RDS（on）"),
        ("drain source resistance", "rds(on)", "rds on"),
        ("mos",),
    ),
    FieldSpec(
        "frequency",
        "频率",
        ("频率",),
        ("frequency",),
        ("crystal",),
    ),
    FieldSpec(
        "load_capacitance",
        "负载电容",
        ("负载电容",),
        ("load capacitance",),
        ("crystal",),
    ),
)

FIELD_BY_INPUT_LABEL = {
    re.sub(r"[\s_\-()\[\]/（）]+", "", label).lower(): spec
    for spec in FIELD_SPECS
    for label in spec.input_labels
}

REFERENCE_KIND = {
    "C": "capacitor",
    "R": "resistor",
    "L": "inductor",
    "FB": "inductor",
    "D": "diode",
    "TV": "tvs",
    "Z": "tvs",
    "Q": "mos",
    "M": "mos",
    "U": "ic",
    "IC": "ic",
    "Y": "crystal",
    "X": "crystal",
    "XTAL": "crystal",
}

UNIT_FACTORS = {
    "v": ("voltage", 1.0),
    "mv": ("voltage", 1e-3),
    "a": ("current", 1.0),
    "ma": ("current", 1e-3),
    "ua": ("current", 1e-6),
    "f": ("capacitance", 1.0),
    "mf": ("capacitance", 1e-3),
    "uf": ("capacitance", 1e-6),
    "nf": ("capacitance", 1e-9),
    "pf": ("capacitance", 1e-12),
    "h": ("inductance", 1.0),
    "mh": ("inductance", 1e-3),
    "uh": ("inductance", 1e-6),
    "nh": ("inductance", 1e-9),
    "w": ("power", 1.0),
    "mw": ("power", 1e-3),
    "ohm": ("resistance", 1.0),
    "kohm": ("resistance", 1e3),
    "milliohm": ("resistance", 1e-3),
    "megaohm": ("resistance", 1e6),
    "hz": ("frequency", 1.0),
    "khz": ("frequency", 1e3),
    "mhz": ("frequency", 1e6),
    "ghz": ("frequency", 1e9),
}


@dataclass
class ReviewIssue:
    code: str
    message: str
    severity: str = "warning"

    def as_dict(self) -> Dict[str, str]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
        }


@dataclass
class ModelReview:
    mpn: str
    designators: List[str]
    kind: str
    item: Optional[Dict[str, object]]
    exact: bool
    issues: List[ReviewIssue] = field(default_factory=list)

    @property
    def status(self) -> str:
        if not self.issues:
            return "pass"
        if any(issue.severity == "error" for issue in self.issues):
            return "error"
        return "review"

    def as_dict(self) -> Dict[str, object]:
        item = self.item or {}
        return {
            "mpn": self.mpn,
            "designators": list(self.designators),
            "kind": self.kind,
            "status": self.status,
            "exact_match": self.exact,
            "component_code": component_code(item) if item else None,
            "brand": brand(item) if item else None,
            "package": package(item) if item else None,
            "stock": int(item.get("stockCount") or 0) if item else None,
            "unit_price": first_price(item) if item else None,
            "issues": [issue.as_dict() for issue in self.issues],
        }


def normalize_label(value: str) -> str:
    return re.sub(r"[\s_\-()\[\]/（）]+", "", str(value)).lower()


def normalize_mpn(value: str) -> str:
    return re.sub(r"\s+", "", str(value)).upper()


def add_issue(issues: List[ReviewIssue], issue: ReviewIssue) -> None:
    key = (issue.severity, issue.code, issue.message)
    if all(
        (existing.severity, existing.code, existing.message) != key
        for existing in issues
    ):
        issues.append(issue)


def reference_prefix(designator: str) -> str:
    match = re.match(r"([A-Za-z]+)", designator.strip())
    return match.group(1).upper() if match else ""


def canonical_package(value: str) -> str:
    text = str(value or "").strip().upper()
    text = re.sub(r"[\s_]+", "", text)
    text = re.sub(r"\((?:METRIC|公制).*?\)", "", text)
    text = re.sub(r"\[(?:METRIC|公制).*?\]", "", text)
    if re.fullmatch(r"C\d{4}", text):
        text = text[1:]
    match = PACKAGE_TOKEN_RE.search(text)
    if match:
        return match.group(0)
    return re.sub(r"[^A-Z0-9]+", "", text)


def packages_compatible(expected: str, actual: str) -> bool:
    expected_token = canonical_package(expected)
    actual_token = canonical_package(actual)
    if not expected_token or not actual_token:
        return True
    return expected_token == actual_token


def classify_kind(records: Sequence[ComponentRecord]) -> str:
    prefixes = []
    for record in records:
        for designator in record.designators:
            prefix = reference_prefix(designator)
            if prefix and prefix not in prefixes:
                prefixes.append(prefix)

    if len(prefixes) == 1:
        return REFERENCE_KIND.get(prefixes[0], "unknown")

    footprints = [canonical_package(record.footprint) for record in records]
    if footprints and all(re.fullmatch(r"\d{4}", item or "") for item in footprints):
        return "capacitor"
    return "unknown"


def normalize_value(value: str) -> str:
    text = str(value).strip().strip("'\"")
    text = (
        text.replace("MΩ", "megaohm")
        .replace("mΩ", "milliohm")
        .replace("MOhm", "megaohm")
        .replace("mOhm", "milliohm")
    )
    text = text.lower()
    text = (
        text.replace("μ", "u")
        .replace("µ", "u")
        .replace("Ω", "ohm")
        .replace("ω", "ohm")
        .replace("±", "+/-")
        .replace("＋/－", "+/-")
        .replace("＋", "+")
        .replace("－", "-")
    )
    text = text.replace("volts", "v").replace("volt", "v").replace("vdc", "v")
    return re.sub(r"\s+", "", text)


def canonical_quantity(value: str) -> Optional[Tuple[str, float]]:
    text = normalize_value(value)
    match = re.fullmatch(
        r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?)([a-z]+)",
        text,
    )
    if not match:
        return None
    unit = match.group(2)
    unit_info = UNIT_FACTORS.get(unit)
    if not unit_info:
        return None
    dimension, factor = unit_info
    return dimension, float(match.group(1)) * factor


def values_equivalent(expected: str, actual: str) -> bool:
    left = normalize_value(expected)
    right = normalize_value(actual)
    if left == right:
        return True

    if {left, right} <= {"np0", "c0g"}:
        return True

    percent_left = left.startswith("+/-") and left.endswith("%")
    percent_right = right.startswith("+/-") and right.endswith("%")
    if percent_left or percent_right:
        if left.replace("+/-", "") == right.replace("+/-", ""):
            return True

    expected_quantity = canonical_quantity(left)
    actual_quantity = canonical_quantity(right)
    if expected_quantity and actual_quantity:
        if expected_quantity[0] != actual_quantity[0]:
            return False
        difference = abs(expected_quantity[1] - actual_quantity[1])
        scale = max(abs(expected_quantity[1]), abs(actual_quantity[1]), 1.0)
        return difference / scale < 1e-9

    return False


def find_field_spec(label: str) -> Optional[FieldSpec]:
    return FIELD_BY_INPUT_LABEL.get(normalize_label(label))


def find_api_attribute(
    item: Dict[str, object],
    spec: FieldSpec,
) -> Optional[Tuple[str, str]]:
    aliases = [normalize_label(alias) for alias in spec.api_labels]
    candidates = []
    for attribute in item.get("attributes") or []:
        name = str(attribute.get("attribute_name_en") or "")
        value = str(attribute.get("attribute_value_name") or "")
        actual = normalize_label(name)
        if not actual or not value or value == "-":
            continue
        for alias in aliases:
            if actual == alias:
                score = 1000 + len(alias)
            elif alias in actual:
                score = len(alias)
            else:
                continue
            candidates.append((score, name, value))
    if not candidates:
        return None
    _, name, value = max(candidates, key=lambda row: row[0])
    return name, value


def describe_contains(item: Dict[str, object], value: str) -> bool:
    expected = normalize_value(value)
    describe = normalize_value(str(item.get("describe") or ""))
    return bool(expected and expected in describe)


def check_parameters(
    records: Sequence[ComponentRecord],
    item: Dict[str, object],
    kind: str,
) -> List[ReviewIssue]:
    issues: List[ReviewIssue] = []
    exported_values: Dict[str, List[str]] = {}

    for record in records:
        for label, value in record.attributes:
            spec = find_field_spec(label)
            if spec is None:
                continue
            exported_values.setdefault(spec.key, []).append(value)

    for spec in FIELD_SPECS:
        values = exported_values.get(spec.key, [])
        if not values:
            if kind in spec.critical_kinds:
                add_issue(
                    issues,
                    ReviewIssue(
                        "missing_export_parameter",
                        "导出信息缺少%s，无法自动核验" % spec.label,
                    ),
                )
            continue

        distinct_values = []
        for value in values:
            if not any(
                values_equivalent(value, existing)
                for existing in distinct_values
            ):
                distinct_values.append(value)
        if len(distinct_values) > 1:
            add_issue(
                issues,
                ReviewIssue(
                    "parameter_conflict",
                    "同一型号的%s不一致: %s"
                    % (spec.label, ", ".join(values)),
                    "error",
                ),
            )

        expected = values[0]
        actual = find_api_attribute(item, spec)
        if actual is None:
            if describe_contains(item, expected):
                continue
            add_issue(
                issues,
                ReviewIssue(
                    "unverified_parameter",
                    "%s无法核实: 导出=%s" % (spec.label, expected),
                ),
            )
            continue

        actual_name, actual_value = actual
        if not values_equivalent(expected, actual_value):
            add_issue(
                issues,
                ReviewIssue(
                    "parameter_mismatch",
                    "%s冲突: 导出=%s，接口%s=%s"
                    % (spec.label, expected, actual_name, actual_value),
                    "error",
                ),
            )
    return issues


def build_model_reviews(
    records: Sequence[ComponentRecord],
    limit: int,
    jobs: int,
    cache_path: str,
    cache_ttl: int,
    use_cache: bool,
    lookup_fn: Optional[Callable[..., Dict[str, object]]] = None,
) -> List[ModelReview]:
    groups: Dict[str, Dict[str, object]] = {}
    order: List[str] = []

    for record in records:
        mpn = record.part_number.strip()
        if not mpn:
            continue
        key = normalize_mpn(mpn)
        if key not in groups:
            groups[key] = {"mpn": mpn, "records": [], "designators": []}
            order.append(key)
        group = groups[key]
        group["records"].append(record)
        for designator in record.designators:
            if designator not in group["designators"]:
                group["designators"].append(designator)

    if not order:
        return []

    unique_mpns = [str(groups[key]["mpn"]) for key in order]
    if lookup_fn is None:
        lookup_fn = lookup_target
    worker_count = max(1, min(jobs, len(unique_mpns)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as pool:
        lookup_results = list(pool.map(
            lambda mpn: lookup_fn(
                mpn,
                limit=limit,
                cache_path=cache_path,
                cache_ttl=cache_ttl,
                use_cache=use_cache,
            ),
            unique_mpns,
        ))
    lookup_by_key = {
        normalize_mpn(str(result.get("mpn") or mpn)): result
        for mpn, result in zip(unique_mpns, lookup_results)
    }

    reviews: List[ModelReview] = []
    for key in order:
        group = groups[key]
        group_records = group["records"]
        result = lookup_by_key[key]
        item = result.get("item") if isinstance(result.get("item"), dict) else None
        exact = bool(result.get("exact"))
        issues: List[ReviewIssue] = []
        kind = classify_kind(group_records)

        error = result.get("error")
        if error:
            add_issue(
                issues,
                ReviewIssue("lookup_error", "接口查询失败: %s" % error, "error"),
            )
        elif not exact:
            add_issue(
                issues,
                ReviewIssue(
                    "no_exact_match",
                    "接口没有精确匹配型号，需要人工确认",
                    "error",
                ),
            )

        if item is not None and exact and not error:
            stock = int(item.get("stockCount") or 0)
            if stock <= 0:
                add_issue(
                    issues,
                    ReviewIssue("out_of_stock", "无现货，需要替代型号", "error"),
                )

            actual_package = package(item)
            for expected_package in {
                record.footprint for record in group_records if record.footprint
            }:
                if not packages_compatible(expected_package, actual_package):
                    add_issue(
                        issues,
                        ReviewIssue(
                            "package_mismatch",
                            "封装冲突: 导出=%s，接口=%s"
                            % (expected_package, actual_package),
                            "error",
                        ),
                    )

            for issue in check_parameters(group_records, item, kind):
                add_issue(issues, issue)

        reviews.append(ModelReview(
            mpn=str(group["mpn"]),
            designators=list(group["designators"]),
            kind=kind,
            item=item,
            exact=exact,
            issues=issues,
        ))

    return reviews


def run_review(
    source_name: str,
    text: str,
    limit: int,
    jobs: int,
    cache_path: str,
    cache_ttl: int,
    use_cache: bool,
    lookup_fn: Optional[Callable[..., Dict[str, object]]] = None,
) -> Dict[str, object]:
    records, parse_warnings = parse_text(text)
    reviews = build_model_reviews(
        records,
        limit=limit,
        jobs=jobs,
        cache_path=cache_path,
        cache_ttl=cache_ttl,
        use_cache=use_cache,
        lookup_fn=lookup_fn,
    )
    issue_count = len(parse_warnings) + sum(
        len(review.issues) for review in reviews
    )
    return {
        "source": source_name,
        "record_count": len(records),
        "model_count": len(reviews),
        "issue_count": issue_count,
        "parse_warnings": list(parse_warnings),
        "models": [review.as_dict() for review in reviews],
    }


def print_human(payload: Dict[str, object], verbose: bool) -> None:
    print(
        "预检: %s 条记录 -> %s 个型号，发现 %s 个问题"
        % (
            payload["record_count"],
            payload["model_count"],
            payload["issue_count"],
        )
    )

    parse_warnings = payload.get("parse_warnings") or []
    if parse_warnings:
        print("")
        print("[解析]")
        for warning in parse_warnings:
            print("- %s" % warning)

    models = payload.get("models") or []
    problem_models = [review for review in models if review["issues"]]
    for review in problem_models:
        refs = " ".join(review["designators"])
        suffix = " (%s)" % refs if refs else ""
        print("")
        print("[%s] %s%s" % (review["kind"], review["mpn"], suffix))
        for issue in review["issues"]:
            print("- %s" % issue["message"])

    if verbose:
        passed = [review for review in models if not review["issues"]]
        if passed:
            print("")
            print("[通过]")
            for review in passed:
                refs = " ".join(review["designators"])
                detail = " ".join(
                    item
                    for item in (
                        review.get("component_code"),
                        review.get("package"),
                        "库存=%s" % review.get("stock")
                        if review.get("stock") is not None
                        else None,
                    )
                    if item
                )
                print(
                    "- %s%s%s"
                    % (
                        review["mpn"],
                        " (%s)" % refs if refs else "",
                        "  %s" % detail if detail else "",
                    )
                )

    if not parse_warnings and not problem_models:
        print("未发现可自动识别的问题。")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="一次完成 EDA/BOM 导出解析、去重、立创批量核验与问题筛选",
    )
    parser.add_argument("source", help="导出文件；使用 - 从标准输入读取")
    parser.add_argument("--jobs", type=int, default=6, help="并发查询数，默认 6")
    parser.add_argument("--limit", type=int, default=20, help="每个型号候选条数")
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="忽略本地缓存并重新请求接口",
    )
    parser.add_argument(
        "--cache-ttl",
        type=int,
        default=DEFAULT_CACHE_TTL,
        help="缓存有效期（秒），默认 86400",
    )
    parser.add_argument(
        "--cache-file",
        default=str(DEFAULT_CACHE_PATH),
        help="缓存文件路径",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="同时输出通过项",
    )
    args = parser.parse_args()

    try:
        text, source_name = read_source(args.source)
    except OSError as error:
        print("读取失败: %s" % error, file=sys.stderr)
        return 1

    payload = run_review(
        source_name,
        text,
        limit=args.limit,
        jobs=args.jobs,
        cache_path=args.cache_file,
        cache_ttl=args.cache_ttl,
        use_cache=not args.no_cache,
    )
    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_human(payload, verbose=args.verbose)
    return 0 if payload["issue_count"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
