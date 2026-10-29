#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
将已审核的简体中文词条应用到上游 hakuX Android 源码。

脚本做三件事：
1. 把词条写入 Android 默认语言与简体中文资源，确保资源 ID 在两种语言下都存在。
2. 将 Compose 中完全匹配词条的 Text("...") 字面量替换为 stringResource(...)。
3. 注册 zh-CN 应用语言，并输出命中与未命中报告。

只处理字典中精确匹配的静态界面文本，不改动游戏数据、协议字段、日志、文件路径或动态字符串。
"""

import argparse
import hashlib
import html
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


# 仅匹配 Compose Text 调用的第一个静态字符串参数。
# 例如 Text("Settings") 或 Text(text = "Settings", ...)。
TEXT_LITERAL_PATTERN = re.compile(
    r'(?P<prefix>\bText\s*\(\s*(?:text\s*=\s*)?)'
    r'(?P<literal>"(?:\\.|[^"\\])*")'
)

# contentDescription 是 Compose 图标等控件常用的可见辅助文本。
DESCRIPTION_PATTERN = re.compile(
    r'(?P<prefix>\bcontentDescription\s*=\s*)'
    r'(?P<literal>"(?:\\.|[^"\\])*")'
)


def decode_kotlin_literal(literal):
    """将简单 Kotlin 字符串字面量还原为文本；无法安全解析时返回 None。"""
    raw = literal[1:-1]
    # 字符串插值或多行语义不在首版自动替换范围内。
    if "$" in raw or "\n" in raw or "\r" in raw:
        return None
    try:
        # 首版词条均为普通英文，不包含 Kotlin 专有转义。
        return json.loads(literal)
    except Exception:
        return None


def resource_name(text, used_names):
    """生成合法且稳定的 Android 字符串资源名称。"""
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    if not slug:
        slug = "text"
    if slug[0].isdigit():
        slug = "text_" + slug
    slug = slug[:42]
    candidate = "ui_" + slug

    # 不同英文词条可能归一化成同一名称，冲突时追加短哈希。
    if candidate in used_names and used_names[candidate] != text:
        suffix = hashlib.sha1(text.encode("utf-8")).hexdigest()[:7]
        candidate = f"{candidate}_{suffix}"
    used_names[candidate] = text
    return candidate


def xml_escape(value):
    """转义 XML 文本节点需要转义的字符。"""
    return html.escape(value, quote=False)


def write_crlf(path, content):
    """统一使用 UTF-8 无 BOM 与 CRLF 写入生成文件。"""
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    path.write_text(normalized, encoding="utf-8", newline="\r\n")


def merge_strings_xml(path, updates, overwrite):
    """
    向 strings.xml 增加或更新指定条目。
    使用定点替换，尽量保留上游文件中已有的注释与排版。
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        content = path.read_text(encoding="utf-8")
    else:
        content = '<?xml version="1.0" encoding="utf-8"?>\n<resources>\n</resources>\n'

    for name, value in updates.items():
        pattern = re.compile(
            r'(<string\b(?=[^>]*\bname\s*=\s*["\']'
            + re.escape(name)
            + r'["\'])[^>]*>)(.*?)(</string\s*>)',
            re.DOTALL,
        )
        match = pattern.search(content)

        if match:
            if overwrite:
                replacement = match.group(1) + xml_escape(value) + match.group(3)
                content = pattern.sub(lambda _m: replacement, content, count=1)
        else:
            entry = f'    <string name="{name}">{xml_escape(value)}</string>\n'
            closing = re.search(r"</resources\s*>", content)
            if not closing:
                raise RuntimeError(f"{path} 缺少 </resources> 结束标签")
            content = content[:closing.start()] + entry + content[closing.start():]

    write_crlf(path, content)


def read_default_strings(path):
    """读取上游默认 strings.xml 中的简单字符串，供精确匹配翻译。"""
    if not path.exists():
        return {}
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        raise RuntimeError(f"无法解析 {path}: {exc}") from exc

    values = {}
    for node in tree.getroot().findall("string"):
        name = node.attrib.get("name")
        if not name or list(node):
            continue
        value = node.text or ""
        if value:
            values[name] = value
    return values


def contains_english_text(value):
    """筛选包含英文字母的文本，避免把纯数字或标点误报为待翻译内容。"""
    return bool(value and re.search(r"[A-Za-z]", value))


def format_report_text(value):
    """把换行和反引号转义成单行文本，避免报告中的代码格式被破坏。"""
    return value.replace("\r", "\\r").replace("\n", "\\n").replace("`", "'")


def collect_untranslated_compose(root, app_main, translations):
    """扫描 Compose 的静态 Text 与 contentDescription，收集字典未覆盖的英文候选。"""
    candidates = set()

    # 只扫描源码中能静态读取的字面量；动态插值和拼接文本不在此范围内。
    for path in sorted(app_main.rglob("*.kt")):
        original = path.read_text(encoding="utf-8")
        relative_path = path.relative_to(root).as_posix()

        # Text 文本和无障碍描述是两种常见的直接显示文本入口。
        for pattern in (TEXT_LITERAL_PATTERN, DESCRIPTION_PATTERN):
            for match in pattern.finditer(original):
                value = decode_kotlin_literal(match.group("literal"))
                if value is None or value in translations:
                    continue
                if contains_english_text(value):
                    candidates.add((relative_path, value))

    return sorted(candidates)


def collect_untranslated_resources(default_strings, zh_strings, translations):
    """找出默认 Android 字符串中既没有字典译文、也没有现成中文覆盖的英文候选。"""
    candidates = []

    for name, value in default_strings.items():
        # 应用名称是产品标识，且会由 app_name 单独处理，不作为普通 UI 词条报告。
        if name == "app_name":
            continue

        # 字典已提供译文时由正常汉化流程处理；已有不同的中文值也视为已翻译。
        if value in translations:
            continue
        existing_zh = zh_strings.get(name)
        if existing_zh and existing_zh != value:
            continue

        if contains_english_text(value):
            candidates.append((name, value))

    return sorted(candidates)


def register_locale(root):
    """登记 zh-CN 系统应用语言，并在主清单中引用语言配置。"""
    app_res = root / "android/app/src/main/res"
    locale_file = app_res / "xml/locales_config.xml"
    locale_file.parent.mkdir(parents=True, exist_ok=True)

    if locale_file.exists():
        text = locale_file.read_text(encoding="utf-8")
        existing = set(re.findall(r'android:name\s*=\s*["\']([^"\']+)["\']', text))
        missing = [name for name in ("en", "zh-CN") if name not in existing]
        if missing:
            entries = "".join(
                f'    <locale android:name="{name}" />\n'
                for name in missing
            )
            close = re.search(r"</locale-config\s*>", text)
            if close:
                text = text[:close.start()] + entries + text[close.start():]
            else:
                raise RuntimeError(f"{locale_file} 格式不受支持")
            write_crlf(locale_file, text)
    else:
        write_crlf(
            locale_file,
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<locale-config xmlns:android="http://schemas.android.com/apk/res/android">\n'
            '    <locale android:name="en" />\n'
            '    <locale android:name="zh-CN" />\n'
            '</locale-config>\n',
        )

    manifests = list((root / "android/app/src/main").rglob("AndroidManifest.xml"))
    for manifest in manifests:
        text = manifest.read_text(encoding="utf-8")
        if "android:localeConfig" not in text:
            text, count = re.subn(
                r"<application\b",
                '<application android:localeConfig="@xml/locales_config"',
                text,
                count=1,
            )
            if count:
                write_crlf(manifest, text)

        # 如果清单直接写了应用名称，将其改为资源引用，才能显示中文应用名。
        def fix_label(match):
            value = match.group(2)
            if value.startswith("@"):
                return match.group(0)
            return f'{match.group(1)}@string/app_name{match.group(3)}'

        text = re.sub(
            r'(android:label\s*=\s*)(["\'])(.*?)(\2)',
            lambda m: (
                m.group(1) + m.group(2) + "@string/app_name" + m.group(4)
                if not m.group(3).startswith("@")
                else m.group(0)
            ),
            text,
        )
        write_crlf(manifest, text)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, help="上游 hakuX 源码根目录")
    parser.add_argument("--dictionary", required=True, help="简体中文词条 JSON")
    parser.add_argument("--report", required=True, help="审查报告输出路径")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    dictionary_path = Path(args.dictionary).resolve()
    report_path = Path(args.report).resolve()

    data = json.loads(dictionary_path.read_text(encoding="utf-8"))
    translations = data["translations"]
    app_name = data.get("app_name", {"en": "hakuX", "zh-CN": "hakuX 简体中文版"})

    app_main = root / "android/app/src/main"
    if not app_main.is_dir():
        raise SystemExit(f"找不到 Android 源码目录：{app_main}")

    used_names = {}
    literal_to_key = {
        literal: resource_name(literal, used_names)
        for literal in translations
    }

    matched_literals = set()
    changed_files = []
    replacement_count = 0

    # 在源码被改写前扫描未覆盖的静态文案，报告可见英文但不阻止部分汉化发行。
    untranslated_compose = collect_untranslated_compose(root, app_main, translations)

    kotlin_files = sorted(app_main.rglob("*.kt"))
    for path in kotlin_files:
        original = path.read_text(encoding="utf-8")
        content = original

        def replace_literal(match):
            nonlocal replacement_count
            literal = decode_kotlin_literal(match.group("literal"))
            if literal not in translations:
                return match.group(0)
            key = literal_to_key[literal]
            matched_literals.add(literal)
            replacement_count += 1
            return match.group("prefix") + f"stringResource(R.string.{key})"

        content = TEXT_LITERAL_PATTERN.sub(replace_literal, content)
        content = DESCRIPTION_PATTERN.sub(replace_literal, content)

        if content != original:
            import_line = "import androidx.compose.ui.res.stringResource"
            if import_line not in content:
                package_match = re.search(r"(?m)^package\s+[^\n]+\n", content)
                if not package_match:
                    raise RuntimeError(f"{path} 没有可识别的 package 声明")
                insert_at = package_match.end()
                content = (
                    content[:insert_at]
                    + "\n"
                    + import_line
                    + "\n"
                    + content[insert_at:]
                )
            write_crlf(path, content)
            changed_files.append(str(path.relative_to(root)))

    # 将原本已经使用 Android 资源的界面文字也纳入汉化与审查。
    base_file = app_main / "res/values/strings.xml"
    zh_file = app_main / "res/values-zh-rCN/strings.xml"
    default_strings = read_default_strings(base_file)
    existing_zh_strings = read_default_strings(zh_file)
    existing_resource_translations = {}
    for key, value in default_strings.items():
        if value in translations:
            existing_resource_translations[key] = translations[value]

    # 默认资源中没有字典译文、也没有现成中文覆盖的英文字符串需要人工检查。
    untranslated_resources = collect_untranslated_resources(
        default_strings, existing_zh_strings, translations
    )

    base_updates = {}
    zh_updates = dict(existing_resource_translations)

    for literal in sorted(matched_literals):
        key = literal_to_key[literal]
        base_updates[key] = literal
        zh_updates[key] = translations[literal]

    if "app_name" not in default_strings:
        base_updates["app_name"] = app_name.get("en", "hakuX")
    zh_updates["app_name"] = app_name.get("zh-CN", "hakuX 简体中文版")

    merge_strings_xml(base_file, base_updates, overwrite=False)
    merge_strings_xml(zh_file, zh_updates, overwrite=True)

    register_locale(root)

    total_hits = len(matched_literals) + len(existing_resource_translations)
    unused = sorted(set(translations) - matched_literals - {
        value for value in default_strings.values() if value in translations
    })

    report_lines = [
        "# hakuX 简体中文翻译检查报告",
        "",
        f"- 命中的 Compose 静态文案：{len(matched_literals)} 项",
        f"- 命中的原有字符串资源：{len(existing_resource_translations)} 项",
        f"- 修改的 Kotlin 文件：{len(changed_files)} 个",
        f"- 词条字典总数：{len(translations)} 项",
        f"- 字典中未匹配上游的词条：{len(unused)} 项",
        f"- Compose 未翻译静态文案候选：{len(untranslated_compose)} 项",
        f"- Android 未翻译字符串资源候选：{len(untranslated_resources)} 项",
        "",
        "> 未翻译候选仅供人工审查，不会阻止本次发行。报告范围是可静态识别的 Compose 文案和默认 Android 简单字符串资源；动态拼接、运行时生成、原生 C/C++、自定义绘制等文本不在自动扫描范围内。",
        "",
        "## 本次修改的 Kotlin 文件",
        "",
    ]
    report_lines.extend(f"- `{name}`" for name in changed_files)

    report_lines.extend(["", "## 未翻译的 Compose 静态界面文案候选", ""])
    if untranslated_compose:
        report_lines.extend(
            f"- `{path}`：`{format_report_text(value)}`"
            for path, value in untranslated_compose
        )
    else:
        report_lines.append("- 未发现符合扫描条件的候选文本。")

    report_lines.extend(["", "## 未翻译的 Android 字符串资源候选", ""])
    if untranslated_resources:
        report_lines.extend(
            f"- `{name}`：`{format_report_text(value)}`"
            for name, value in untranslated_resources
        )
    else:
        report_lines.append("- 未发现符合扫描条件的候选资源。")

    report_lines.extend(["", "## 字典中未匹配到上游的词条", ""])
    if unused:
        report_lines.extend(f"- `{value}`" for value in unused)
    else:
        report_lines.append("- 全部字典词条均已匹配到上游源码或默认资源。")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    write_crlf(report_path, "\n".join(report_lines) + "\n")

    print(f"已处理 Compose 文案：{len(matched_literals)} 项")
    print(f"已处理既有资源：{len(existing_resource_translations)} 项")
    print(f"已修改 Kotlin 文件：{len(changed_files)} 个")
    print(f"Compose 未翻译候选：{len(untranslated_compose)} 项")
    print(f"Android 资源未翻译候选：{len(untranslated_resources)} 项")
    print(f"翻译审查报告：{report_path}")

    # 如果没有任何界面文字命中，不允许继续发布纯英文版本。
    if total_hits == 0:
        raise SystemExit(
            "首版词条没有命中上游界面。为防止发布未汉化 APK，构建已停止。"
        )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"汉化处理失败：{exc}", file=sys.stderr)
        raise
