#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在本次构建的上游源码副本中禁用应用内升级检查，不改动上游仓库地址。"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

TEXT_SUFFIXES = {".kt", ".java"}
UPDATE_FILE_RE = re.compile(r"(?i)(update|updater|releasechecker|versionchecker)")
UPDATE_FUNCTION_RE = re.compile(
    r"(?i)(?:"
    r"check\w*(?:update|release|version)|"
    r"(?:fetch|get|load|find|query|request|refresh)\w*(?:latest\w*)?(?:update|release|version)|"
    r"(?:latest|current)\w*(?:release|version)|"
    r"(?:is|has)\w*(?:update|newrelease|newversion)available|"
    r"(?:show|display|present|open)\w*(?:update|release|newversion)|"
    r"update\w*(?:checker|repository|service|manager)"
    r")"
)
FUNCTION_DECL_RE = re.compile(r"\b(?:suspend\s+)?fun\s+([A-Za-z_]\w*)\s*\(")


def skip_literal_or_comment(text: str, index: int) -> int | None:
    """跳过字符串与注释，避免把它们内部的括号误认为 Kotlin 代码结构。"""
    if text.startswith("//", index):
        end = text.find("\n", index)
        return len(text) if end < 0 else end
    if text.startswith("/*", index):
        depth = 1
        cursor = index + 2
        while cursor < len(text) and depth:
            if text.startswith("/*", cursor):
                depth += 1
                cursor += 2
            elif text.startswith("*/", cursor):
                depth -= 1
                cursor += 2
            else:
                cursor += 1
        return cursor
    if text.startswith('"""', index):
        end = text.find('"""', index + 3)
        return len(text) if end < 0 else end + 3
    if text[index] in ('"', "'"):
        quote = text[index]
        cursor = index + 1
        while cursor < len(text):
            if text[cursor] == "\\":
                cursor += 2
                continue
            if text[cursor] == quote:
                return cursor + 1
            cursor += 1
        return len(text)
    return None


def find_matching(text: str, start: int, opening: str, closing: str) -> int | None:
    """查找成对括号的结束位置，同时忽略注释和字符串。"""
    depth = 0
    cursor = start
    while cursor < len(text):
        skipped = skip_literal_or_comment(text, cursor)
        if skipped is not None:
            cursor = skipped
            continue
        if text[cursor] == opening:
            depth += 1
        elif text[cursor] == closing:
            depth -= 1
            if depth == 0:
                return cursor
        cursor += 1
    return None


def find_function_body(text: str, closing_parenthesis: int) -> tuple[int | None, str, bool]:
    """定位函数体并读取返回类型；第三项表示是否为等号表达式函数。"""
    cursor = closing_parenthesis + 1
    round_depth = square_depth = angle_depth = 0
    while cursor < len(text):
        skipped = skip_literal_or_comment(text, cursor)
        if skipped is not None:
            cursor = skipped
            continue
        char = text[cursor]
        if char == "(":
            round_depth += 1
        elif char == ")":
            round_depth = max(0, round_depth - 1)
        elif char == "[":
            square_depth += 1
        elif char == "]":
            square_depth = max(0, square_depth - 1)
        elif char == "<":
            angle_depth += 1
        elif char == ">":
            angle_depth = max(0, angle_depth - 1)
        elif round_depth == square_depth == angle_depth == 0:
            if char == "{":
                header = text[closing_parenthesis + 1:cursor].strip()
                match = re.search(r":\s*([\w.?<> ,]+?)\s*$", header)
                return cursor, match.group(1).strip() if match else "", False
            if char == "=":
                header = text[closing_parenthesis + 1:cursor].strip()
                match = re.search(r":\s*([\w.?<> ,]+?)\s*$", header)
                return cursor, match.group(1).strip() if match else "", True
            if char == ";":
                return None, "", False
            if char == "\n":
                following = text[cursor + 1:cursor + 80].lstrip()
                if following.startswith(("fun ", "private ", "public ", "override ", "@")):
                    return None, "", False
        cursor += 1
    return None, "", False



def find_expression_end(text: str, start: int) -> int | None:
    """查找表达式函数完整表达式的结束位置，支持跨行调用和代码块。"""
    cursor = start
    round_depth = square_depth = brace_depth = angle_depth = 0
    started = False
    while cursor < len(text):
        skipped = skip_literal_or_comment(text, cursor)
        if skipped is not None:
            if text.startswith("//", cursor) and round_depth == square_depth == brace_depth == angle_depth == 0:
                newline = text.find("\n", cursor)
                return len(text) if newline < 0 else newline
            cursor = skipped
            continue
        char = text[cursor]
        if char == "(" : round_depth += 1; started = True
        elif char == ")": round_depth = max(0, round_depth - 1)
        elif char == "[": square_depth += 1; started = True
        elif char == "]": square_depth = max(0, square_depth - 1)
        elif char == "{": brace_depth += 1; started = True
        elif char == "}": brace_depth = max(0, brace_depth - 1)
        elif char == "<": angle_depth += 1; started = True
        elif char == ">": angle_depth = max(0, angle_depth - 1)
        elif not char.isspace(): started = True
        if char == "\n" and started and round_depth == square_depth == brace_depth == angle_depth == 0:
            return cursor
        cursor += 1
    return len(text) if started else None

def default_statement(return_type: str) -> str | None:
    """为可安全中止的函数生成默认返回语句。"""
    kind = re.sub(r"\s+", "", return_type)
    if not kind or kind in ("Unit", "kotlin.Unit"):
        return "return"
    if kind.endswith("?"):
        return "return null"
    if kind in ("Boolean", "kotlin.Boolean"):
        return "return false"
    if kind in ("String", "kotlin.String"):
        return 'return ""'
    if kind in ("Int", "kotlin.Int"):
        return "return 0"
    if kind in ("Long", "kotlin.Long"):
        return "return 0L"
    if kind.startswith(("List<", "MutableList<", "Collection<", "Iterable<")):
        return "return emptyList()"
    if kind.startswith(("Set<", "MutableSet<")):
        return "return emptySet()"
    if kind.startswith(("Map<", "MutableMap<")):
        return "return emptyMap()"
    return None


def default_expression(return_type: str) -> str | None:
    """为单行表达式函数生成兼容的默认值。"""
    statement = default_statement(return_type)
    if statement is None:
        return None
    return "Unit" if statement == "return" else statement.removeprefix("return ")


def is_code_position(text: str, target: int) -> bool:
    """确认正则命中的 fun 关键字不位于注释或字符串中。"""
    cursor = 0
    while cursor < target:
        skipped = skip_literal_or_comment(text, cursor)
        if skipped is not None:
            if skipped > target:
                return False
            cursor = skipped
        else:
            cursor += 1
    return True


def patch_source(path: Path, root: Path) -> tuple[list[str], list[str]]:
    """将可识别的升级检查函数替换为无操作实现。"""
    original = path.read_text(encoding="utf-8-sig")
    edits: list[tuple[int, int, str, str]] = []
    unsupported: list[str] = []
    path_is_updater = bool(UPDATE_FILE_RE.search(path.name))

    for match in FUNCTION_DECL_RE.finditer(original):
        if not is_code_position(original, match.start()):
            continue
        name = match.group(1)
        strongly_related = bool(UPDATE_FUNCTION_RE.search(name))
        related_file_helper = path_is_updater and bool(
            re.search(r"(?i)^(check|fetch|get|load|find|query|request|refresh|latest|show|display|present)", name)
        )
        if not strongly_related and not related_file_helper:
            continue

        open_parenthesis = original.find("(", match.start(1) + len(name))
        close_parenthesis = find_matching(original, open_parenthesis, "(", ")")
        if close_parenthesis is None:
            unsupported.append(f"{name}: 参数列表无法解析")
            continue
        body_start, return_type, expression_body = find_function_body(original, close_parenthesis)
        if body_start is None:
            unsupported.append(f"{name}: 未识别函数体")
            continue

        if expression_body:
            # 完整替换等号后的表达式，包括跨行协程或尾随 lambda，避免残留原检查逻辑。
            expression_end = find_expression_end(original, body_start + 1)
            if expression_end is None:
                unsupported.append(f"{name}: 无法确定表达式函数结束位置")
                continue
            replacement = default_expression(return_type)
            if replacement is None:
                unsupported.append(f"{name}: 不支持的返回类型 {return_type or '(未声明)'}")
                continue
            edits.append((body_start, expression_end, "= " + replacement, name))
        else:
            statement = default_statement(return_type)
            if statement is None:
                unsupported.append(f"{name}: 不支持的返回类型 {return_type or '(未声明)'}")
                continue
            body_end = find_matching(original, body_start, "{", "}")
            if body_end is None:
                unsupported.append(f"{name}: 函数体花括号不匹配")
                continue
            line_start = original.rfind("\n", body_start, body_end) + 1
            indentation = re.match(r"[ \t]*", original[line_start:]).group(0)
            replacement = "{\n" + indentation + "    " + statement + "\n" + indentation + "}"
            edits.append((body_start, body_end + 1, replacement, name))

    # 由后向前替换，避免较早位置的改动影响后续字符偏移。
    unique: dict[tuple[int, int], tuple[str, str]] = {}
    for start, end, replacement, name in edits:
        unique[(start, end)] = (replacement, name)
    ordered = [(start, end, value[0], value[1]) for (start, end), value in unique.items()]
    for start, end, replacement, _name in sorted(ordered, reverse=True):
        original = original[:start] + replacement + original[end:]

    if ordered:
        path.write_text(original.replace("\r\n", "\n").replace("\r", "\n"), encoding="utf-8", newline="\n")
    relative = path.relative_to(root).as_posix()
    changes = [f"{relative}: 已禁用 {name}()" for _, _, _, name in ordered]
    return changes, unsupported


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="本次构建的上游源码根目录")
    parser.add_argument("--report", required=True, help="输出升级提醒屏蔽报告")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    source_root = root / "android/app/src/main"
    if not source_root.is_dir():
        raise SystemExit(f"找不到 Android 应用源码目录：{source_root}")

    changes: list[str] = []
    unsupported: list[str] = []
    candidates: list[str] = []
    for path in sorted(source_root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (UnicodeDecodeError, OSError):
            continue
        has_update_markers = bool(
            UPDATE_FILE_RE.search(path.name)
            or re.search(r"(?i)(check\w*update|fetch\w*release|latest\w*release|updateavailable|newversionavailable)", text)
        )
        if not has_update_markers:
            continue
        candidates.append(path.relative_to(root).as_posix())
        file_changes, file_unsupported = patch_source(path, root)
        changes.extend(file_changes)
        unsupported.extend(f"{path.relative_to(root).as_posix()}: {item}" for item in file_unsupported)

    report = Path(args.report).resolve()
    report.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# 应用内升级提醒屏蔽报告", "",
        "- 本次构建仅禁用应用内升级检查入口；不修改上游仓库地址、应用包名或版本号生成规则。", "",
        "## 已关闭的检查函数", "",
    ]
    lines.extend(f"- {item}" for item in changes)
    if not changes:
        lines.append("- 未识别到可关闭的检查函数。")
    lines.extend(["", "## 升级相关候选文件", ""])
    lines.extend(f"- `{item}`" for item in candidates)
    if not candidates:
        lines.append("- 未发现带有明确升级特征的文件。")
    if unsupported:
        lines.extend(["", "## 未能安全修改的候选函数", ""])
        lines.extend(f"- {item}" for item in unsupported)
    report.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")

    print(f"[升级提醒屏蔽] 已关闭函数：{len(changes)}")
    print(f"[升级提醒屏蔽] 候选文件：{len(candidates)}")
    print(f"[升级提醒屏蔽] 报告：{report}")
    for item in changes:
        print(f"[升级提醒屏蔽] {item}")
    if unsupported:
        for item in unsupported:
            print(f"::error::{item}")
        raise SystemExit("存在未能安全屏蔽的升级相关函数；为避免升级提醒仍然出现，停止构建。")
    if not changes:
        raise SystemExit("未找到可关闭的升级检查函数；为避免误发仍带升级提醒的 APK，停止构建。")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"升级提醒屏蔽失败：{error}", file=sys.stderr)
        raise
