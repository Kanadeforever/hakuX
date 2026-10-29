#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导入 hakuX Android 字符串资源译文，并检查上游文案变化。"""

import argparse
import collections
import html
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


PLACEHOLDER_PATTERN = re.compile(r"%(?:\d+\$)?[sd]")


def write_crlf(path, content):
    """统一以 UTF-8 无 BOM、CRLF 写入文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    path.write_text(content, encoding="utf-8", newline="\r\n")


def read_strings(path):
    """读取 Android 字符串资源，保留 Android 转义符以便检测上游改动。"""
    if not path.exists():
        return {}
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise RuntimeError(f"无法解析 Android 字符串资源 {path}: {exc}") from exc

    values = {}
    for node in root.findall("string"):
        name = node.attrib.get("name")
        if not name or list(node):
            continue
        values[name] = node.text or ""
    return values


def xml_escape(value):
    """转义 XML 文本节点中的保留字符，不改写 Android 的反斜杠转义。"""
    return html.escape(value, quote=False)


def merge_translations(path, translations):
    """按资源 ID 更新或新增译文，同时保留文件中的其他资源和注释。"""
    if path.exists():
        content = path.read_text(encoding="utf-8")
    else:
        content = '<?xml version="1.0" encoding="utf-8"?>\n<resources>\n</resources>\n'

    for name, value in translations.items():
        pattern = re.compile(
            r'(<string\b(?=[^>]*\bname\s*=\s*["\']'
            + re.escape(name)
            + r'["\'])[^>]*>)(.*?)(</string\s*>)',
            re.DOTALL,
        )
        replacement_value = xml_escape(value)
        match = pattern.search(content)
        if match:
            replacement = match.group(1) + replacement_value + match.group(3)
            content = pattern.sub(lambda _m: replacement, content, count=1)
        else:
            entry = f'    <string name="{name}">{replacement_value}</string>\n'
            closing = re.search(r"</resources\s*>", content)
            if not closing:
                raise RuntimeError(f"{path} 缺少 </resources> 结束标签")
            content = content[:closing.start()] + entry + content[closing.start():]

    write_crlf(path, content)


def placeholder_signature(value):
    """取得格式化占位符的多重集合，防止译文漏掉或改变运行时参数。"""
    return collections.Counter(PLACEHOLDER_PATTERN.findall(value))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, help="上游 hakuX 源码根目录")
    parser.add_argument("--dictionary", required=True, help="按资源 ID 组织的 JSON 翻译表")
    parser.add_argument("--report", required=True, help="上游文案变化与导入结果报告")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    dictionary_path = Path(args.dictionary).resolve()
    report_path = Path(args.report).resolve()
    app_main = root / "android/app/src/main"
    default_path = app_main / "res/values/strings.xml"
    translated_path = app_main / "res/values-zh-rCN/strings.xml"

    if not default_path.is_file():
        raise SystemExit(f"找不到上游默认字符串资源：{default_path}")

    document = json.loads(dictionary_path.read_text(encoding="utf-8"))
    if document.get("schema_version") != 1 or not isinstance(document.get("resources"), dict):
        raise SystemExit("翻译文件格式不正确：需要 schema_version=1 和 resources 对象。")

    source_strings = read_strings(default_path)
    existing_zh = read_strings(translated_path)
    imported = {}
    changed_source = []
    missing_ids = []
    invalid_placeholders = []
    unchanged = []
    current_resource_ids = set(source_strings)

    for resource_id, entry in document["resources"].items():
        if not isinstance(entry, dict):
            raise SystemExit(f"资源 {resource_id} 的翻译条目必须是对象。")

        saved_source = entry.get("source")
        translation = entry.get("translation")
        if not isinstance(saved_source, str) or not isinstance(translation, str) or not translation.strip():
            raise SystemExit(f"资源 {resource_id} 缺少 source 或有效的 translation。")

        current_source = source_strings.get(resource_id)
        if current_source is None:
            missing_ids.append(resource_id)
            continue

        # 如果上游调整了同一资源 ID 的英文文案，仍沿用现有译文，
        # 但在报告中记录源文变化，方便人工判断是否需要重译。
        if current_source != saved_source:
            changed_source.append((resource_id, saved_source, current_source, translation))

        if placeholder_signature(current_source) != placeholder_signature(translation):
            invalid_placeholders.append(
                (resource_id, current_source, translation,
                 sorted(placeholder_signature(current_source).items()),
                 sorted(placeholder_signature(translation).items()))
            )
            continue

        imported[resource_id] = translation
        if existing_zh.get(resource_id) == translation:
            unchanged.append(resource_id)

    merge_translations(translated_path, imported)

    report_lines = [
        "## 按资源 ID 导入的简体中文译文",
        "",
        f"- 翻译表资源总数：{len(document['resources'])} 项",
        f"- 本次有效导入：{len(imported)} 项",
        f"- 与现有译文相同：{len(unchanged)} 项",
        f"- 上游文案已变化：{len(changed_source)} 项（仍应用原译文，供人工复核）",
        f"- 上游已不存在的资源 ID：{len(missing_ids)} 项",
        f"- 占位符不匹配、已跳过的译文：{len(invalid_placeholders)} 项",
        "",
        "> 文案变化不会阻止方案 B 的发行。资源 ID 未变化时会继续使用现有译文，并报告源文差异；如果占位符不匹配，为避免运行时格式错误，会跳过该条译文。",
        "",
        "### 上游文案变化（需要复核）",
        "",
    ]

    if changed_source:
        for resource_id, old, current, translation in changed_source:
            report_lines.append(f"- `{resource_id}`")
            report_lines.append(f"  - 翻译表记录的原文：`{old.replace(chr(10), r'\\n')}`")
            report_lines.append(f"  - 当前上游原文：`{current.replace(chr(10), r'\\n')}`")
            report_lines.append(f"  - 当前采用译文：`{translation.replace(chr(10), r'\\n')}`")
    else:
        report_lines.append("- 没有检测到已知资源 ID 的原文变化。")

    report_lines.extend(["", "### 翻译表中已失效的资源 ID", ""])
    report_lines.extend(f"- `{resource_id}`" for resource_id in missing_ids)
    if not missing_ids:
        report_lines.append("- 无")

    report_lines.extend(["", "### 因占位符不匹配而跳过的译文", ""])
    for resource_id, current, translation, source_sig, translation_sig in invalid_placeholders:
        report_lines.append(f"- `{resource_id}`")
        report_lines.append(f"  - 当前原文：`{current.replace(chr(10), r'\\n')}`")
        report_lines.append(f"  - 译文：`{translation.replace(chr(10), r'\\n')}`")
        report_lines.append(f"  - 原文占位符：`{source_sig}`；译文占位符：`{translation_sig}`")
    if not invalid_placeholders:
        report_lines.append("- 无")

    write_crlf(report_path, "\n".join(report_lines) + "\n")

    print(f"已导入资源译文：{len(imported)} 项")
    print(f"上游文案变化：{len(changed_source)} 项")
    print(f"失效资源 ID：{len(missing_ids)} 项")
    print(f"占位符不匹配：{len(invalid_placeholders)} 项")
    print(f"资源导入报告：{report_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"导入简体中文资源失败：{exc}", file=sys.stderr)
        raise
