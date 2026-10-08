#!/usr/bin/env python3
"""schematic-reviewer 双平台构建器。

把 `skills/` 下的单一源渲染成 WorkBuddy / Codex 两套可直接安装的 skill。

用法：
    python build.py                     # 构建全部平台到 dist/
    python build.py --platform codex    # 只构建指定平台
    python build.py --check             # 只校验（不写 dist/）
    python build.py --install workbuddy # 构建并把产物装到该平台的 skills 目录
    python build.py --clean             # 删除 dist/

模板语法（只在 skills/ 下的文本文件里生效）：

    <!-- @if workbuddy --> ... <!-- @endif -->     仅 workbuddy 保留
    <!-- @if codex -->    ... <!-- @endif -->     仅 codex 保留
    <!-- @if workbuddy,codex --> ... <!-- @endif -->  任一命中即保留
    <!-- @else -->                                 分支
    {{PY}}                                         平台变量，取值见 platforms/*.json 的 vars
    {{script:review_export.py}}                    带参占位符，取值见 patterns

说明：
  * 标记可以独占一行，也可以嵌在行内；独占一行时该行会被整行删除，不留空行。
  * `@if` 可以嵌套。
  * 渲染后若仍残留标记或未定义变量，构建直接失败，避免把半成品装到本机。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SKILLS_DIR = ROOT / "skills"
PLATFORMS_DIR = ROOT / "platforms"
DIST_DIR = ROOT / "dist"

# 参与模板渲染的扩展名；其余文件原样拷贝
TEXT_EXTS = {
    ".md", ".txt", ".py", ".json", ".yaml", ".yml",
    ".sh", ".bash", ".cfg", ".ini", ".toml",
}

TOKEN_RE = re.compile(
    r"<!--\s*@(?:"
    r"if\s+(?P<names>[A-Za-z0-9_]+(?:\s*,\s*[A-Za-z0-9_]+)*)"
    r"|(?P<kind>else|endif)"
    r")\s*-->"
)
VAR_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
PATTERN_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*([^{}]*?)\s*\}\}")
LEFTOVER_RE = re.compile(r"<!--\s*@(?:if|else|endif)\b")


class BuildError(Exception):
    pass


def purge(path: Path) -> None:
    """递归删除目录树。

    刻意不用 `shutil.rmtree`：某些受管运行环境会把它劫持成「移入回收站」，
    在无桌面会话时反而失败，导致构建中断。
    """
    if not path.exists():
        return
    for entry in os.scandir(path):
        child = Path(entry.path)
        if entry.is_dir(follow_symlinks=False):
            purge(child)
        else:
            child.unlink()
    path.rmdir()


def render(text: str, platform: str, cfg: dict, where: str,
           collapse_blank: bool = False) -> str:
    """按平台裁剪 @if/@else 块，并替换平台变量。"""
    out: list[str] = []
    pos = 0
    stack: list[list] = []  # 每项是 [是否输出, 条件是否命中]

    def active() -> bool:
        return all(frame[0] for frame in stack)

    for m in TOKEN_RE.finditer(text):
        start, end = m.span()
        line_start = text.rfind("\n", 0, start) + 1
        line_end = text.find("\n", end)
        whole_line = (
            text[line_start:start].strip() == ""
            and (line_end == -1 or text[end:line_end].strip() == "")
        )
        if whole_line:
            seg_end = line_start          # 连同该行的缩进一起丢弃
            end = len(text) if line_end == -1 else line_end + 1
        else:
            seg_end = start
        if active():
            out.append(text[pos:seg_end])
        pos = end

        names, kind = m.group("names"), m.group("kind")
        if kind == "endif":
            if not stack:
                raise BuildError(f"{where}: 多余的 @endif")
            stack.pop()
            continue
        if kind == "else":
            if not stack:
                raise BuildError(f"{where}: 没有对应的 @if")
            frame = stack[-1]
            frame[0] = not frame[1]
            continue
        wanted = [n.strip() for n in names.split(",") if n.strip()]
        hit = platform in wanted
        stack.append([hit, hit])

    if stack:
        raise BuildError(f"{where}: 有 @if 未闭合")
    if active():
        out.append(text[pos:])

    body = "".join(out)
    if collapse_blank:
        # 只在 Markdown 里把整行标记留下的连续空行压回一个空行。
        # 不能对 .py 之类源码做这件事——那会平白改动无关代码的空行。
        body = re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", body)

    variables: dict[str, str] = cfg.get("vars", {})
    patterns: dict[str, list] = cfg.get("patterns", {})
    problems: list[str] = []

    def sub_pattern(match: re.Match) -> str:
        key, arg = match.group(1), match.group(2)
        spec = patterns.get(key)
        if not spec or len(spec) != 2:
            problems.append(f"未定义的占位符 {{{{{key}:...}}}}")
            return match.group(0)
        return f"{spec[0]}{arg}{spec[1]}"

    body = PATTERN_RE.sub(sub_pattern, body)

    def sub_var(match: re.Match) -> str:
        key = match.group(1)
        if key not in variables:
            problems.append(f"未定义的变量 {{{{{key}}}}}")
            return match.group(0)
        return variables[key]

    body = VAR_RE.sub(sub_var, body)
    if problems:
        detail = "；".join(sorted(set(problems)))
        raise BuildError(
            f"{where}: {detail}"
            f"（可用变量：{', '.join(sorted(variables)) or '无'}；"
            f"可用占位符：{', '.join(sorted(patterns)) or '无'}）"
        )
    leftover = LEFTOVER_RE.search(body)
    if leftover:
        raise BuildError(f"{where}: 渲染后仍残留模板标记 {leftover.group(0)!r}")
    return body


def load_platforms(names: list[str] | None) -> list[dict]:
    if not PLATFORMS_DIR.is_dir():
        raise BuildError(f"缺少平台目录：{PLATFORMS_DIR}")
    platforms = []
    for path in sorted(PLATFORMS_DIR.glob("*.json")):
        cfg = json.loads(path.read_text(encoding="utf-8"))
        cfg["_file"] = path
        cfg.setdefault("vars", {})
        cfg.setdefault("patterns", {})
        cfg.setdefault("overlay", "overlay")
        cfg.setdefault("install_dir", "")
        if "name" not in cfg:
            raise BuildError(f"{path}: 缺少 name 字段")
        for key, spec in cfg["patterns"].items():
            if not isinstance(spec, list) or len(spec) != 2:
                raise BuildError(f"{path}: patterns.{key} 必须是 [前缀, 后缀] 二元数组")
        platforms.append(cfg)
    if names:
        wanted = set(names)
        known = {p["name"] for p in platforms}
        unknown = wanted - known
        if unknown:
            raise BuildError(
                f"未知平台 {', '.join(sorted(unknown))}（可用：{', '.join(sorted(known))}）"
            )
        platforms = [p for p in platforms if p["name"] in wanted]
    return platforms


def skill_dirs() -> list[Path]:
    if not SKILLS_DIR.is_dir():
        raise BuildError(f"缺少 skills 目录：{SKILLS_DIR}")
    dirs = [p for p in sorted(SKILLS_DIR.iterdir()) if p.is_dir()]
    if not dirs:
        raise BuildError(f"{SKILLS_DIR} 下没有任何 skill")
    for d in dirs:
        if not (d / "SKILL.md").is_file():
            raise BuildError(f"{d.name}: 缺少 SKILL.md")
    return dirs


def build_platform(platform: dict, target_root: Path) -> list[tuple[str, int]]:
    """把某平台的全部 skill 渲染到 target_root。返回 (skill 名, 文件数) 列表。"""
    name = platform["name"]
    stats: list[tuple[str, int]] = []

    for skill in skill_dirs():
        out_dir = target_root / skill.name
        count = 0
        for src in sorted(skill.rglob("*")):
            if not src.is_file():
                continue
            rel = src.relative_to(skill)
            if "__pycache__" in rel.parts or src.suffix == ".pyc":
                continue
            dst = out_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            where = f"{name}/{skill.name}/{rel.as_posix()}"
            if src.suffix.lower() in TEXT_EXTS:
                text = src.read_text(encoding="utf-8")
                markdown = src.suffix.lower() in {".md", ".txt", ".rst"}
                dst.write_text(
                    render(text, name, platform, where, collapse_blank=markdown),
                    encoding="utf-8", newline="\n",
                )
            else:
                shutil.copy2(src, dst)
            count += 1
        stats.append((skill.name, count))

    overlay = PLATFORMS_DIR / name / platform["overlay"]
    if overlay.is_dir():
        for src in sorted(overlay.rglob("*")):
            if not src.is_file():
                continue
            dst = target_root / src.relative_to(overlay)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    return stats


def write_manifest(target_root: Path, platform: dict, stats: list[tuple[str, int]]) -> None:
    manifest = {
        "platform": platform["name"],
        "display_name": platform.get("display_name", platform["name"]),
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "source": "skills/",
        "vars": platform["vars"],
        "patterns": platform.get("patterns", {}),
        "skills": [{"name": n, "files": c} for n, c in stats],
    }
    (target_root / "BUILD.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def expand(path: str) -> Path:
    return Path(path.replace("~", str(Path.home()), 1))


def install(platform: dict, built_root: Path) -> None:
    raw = platform.get("install_dir", "")
    if not raw:
        raise BuildError(f"平台 {platform['name']} 未配置 install_dir，无法安装")
    target_root = expand(raw)
    target_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for skill in sorted(p for p in built_root.iterdir() if p.is_dir()):
        dst = target_root / skill.name
        if dst.exists():
            backup = target_root / f"{skill.name}.backup-{stamp}"
            dst.rename(backup)
            print(f"  已备份原目录 -> {backup}")
        shutil.copytree(skill, dst)
        print(f"  已安装 {skill.name} -> {dst}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="渲染 schematic-reviewer 的 WorkBuddy / Codex 两套 skill",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--platform", action="append", metavar="NAME",
                        help="只构建指定平台，可重复；默认全部")
    parser.add_argument("--check", action="store_true",
                        help="只校验模板能否渲染，不写 dist/")
    parser.add_argument("--install", metavar="NAME",
                        help="构建后把产物安装到该平台的 skills 目录")
    parser.add_argument("--clean", action="store_true", help="删除 dist/ 后退出")
    args = parser.parse_args(argv)

    if args.clean:
        if DIST_DIR.exists():
            purge(DIST_DIR)
            print(f"已删除 {DIST_DIR}")
        return 0

    try:
        platforms = load_platforms(args.platform)
        if args.check:
            with tempfile.TemporaryDirectory() as tmp:
                for platform in platforms:
                    stats = build_platform(platform, Path(tmp) / platform["name"])
                    total = sum(c for _, c in stats)
                    print(f"[check] {platform['name']}: {total} 个文件渲染通过")
            return 0

        DIST_DIR.mkdir(parents=True, exist_ok=True)
        for platform in platforms:
            target_root = DIST_DIR / platform["name"]
            if target_root.exists():
                purge(target_root)
            stats = build_platform(platform, target_root)
            write_manifest(target_root, platform, stats)
            total = sum(c for _, c in stats)
            print(f"[build] {platform['name']} ({platform.get('display_name', '')}) "
                  f"-> {target_root.relative_to(ROOT)}  共 {total} 个文件")

        if args.install:
            if args.platform and args.install not in args.platform:
                raise BuildError("--install 的平台不在 --platform 列表里")
            chosen = [p for p in load_platforms([args.install])][0]
            print(f"[install] {chosen['name']} -> {chosen['install_dir']}")
            install(chosen, DIST_DIR / chosen["name"])
        return 0
    except BuildError as exc:
        print(f"构建失败：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
