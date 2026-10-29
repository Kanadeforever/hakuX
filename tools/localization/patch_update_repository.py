#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""将 hakuX Android 应用内升级检查的仓库地址改为汉化发行仓库。

脚本仅扫描 Android 应用源码中的文本文件，并且只修改明确属于升级检查的仓库引用。
普通的项目主页、许可证、致谢等链接不会被无差别替换。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

TEXT_SUFFIXES = {
    ".kt", ".java", ".xml", ".json", ".properties", ".gradle", ".kts",
    ".toml", ".txt",
}

# 这些特征用于识别实际参与升级检查的源文件，而不是仅仅提及上游仓库的普通页面。
UPDATE_MARKERS = (
    "api.github.com",
    "releases/latest",
    "checkforupdates",
    "updatechecker",
    "updater",
    "latestrelease",
    "update_url",
    "updateurl",
    "release.tag_name",
)

OLD_REPO = "rfandango/hakuX"


def normalize_text(path: Path) -> str:
    """读取 UTF-8 文本并统一换行，避免 Windows 换行影响正则匹配。"""
    return path.read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")


def is_update_source(path: Path, content: str) -> bool:
    """只把包含升级检查特征的代码文件当作候选。"""
    lowered_path = path.name.lower()
    lowered_content = content.lower()
    return (
        any(marker in lowered_path for marker in ("update", "updater", "releasechecker"))
        or any(marker in lowered_content for marker in UPDATE_MARKERS)
    )


def patch_file(path: Path, content: str, target_repo: str) -> tuple[str, int]:
    """替换升级 API / 发布下载地址；兼容单独配置仓库所有者的写法。"""
    updated = content
    replacements = 0

    # GitHub API 地址是首要目标，替换仓库名但不触碰其他 GitHub 链接。
    api_pattern = re.compile(
        r"(?i)(https?://api\.github\.com/repos/)" + re.escape(OLD_REPO)
    )
    updated, count = api_pattern.subn(lambda m: m.group(1) + target_repo, updated)
    replacements += count

    # 如果更新器直接使用 GitHub Releases 页面或资产下载地址，也将其切到汉化仓库。
    release_url_pattern = re.compile(
        r"(?i)(https?://github\.com/)" + re.escape(OLD_REPO) + r"(?=/releases(?:/|\b))"
    )
    updated, count = release_url_pattern.subn(lambda m: m.group(1) + target_repo, updated)
    replacements += count

    # 有些实现把 OWNER/REPO 分开配置。只修改升级检查文件中的 owner 常量。
    owner = target_repo.split("/", 1)[0]
    owner_pattern = re.compile(
        r"(?i)(\b(?:GITHUB_OWNER|REPO_OWNER|REPOSITORY_OWNER|OWNER)\s*[:=]\s*[\"'])"
        r"rfandango([\"'])"
    )
    updated, count = owner_pattern.subn(lambda m: m.group(1) + owner + m.group(2), updated)
    replacements += count

    # 更新器可能将仓库 slug 保存为单独的字符串常量。
    # 只替换被引号包围的仓库标识，不替换普通的项目主页链接。
    if is_update_source(path, updated):
        slug_pattern = re.compile(r"([\"'])" + re.escape(OLD_REPO) + r"\1")
        updated, count = slug_pattern.subn(lambda m: m.group(1) + target_repo + m.group(1), updated)
        replacements += count

    return updated, replacements


def has_target_update_reference(path: Path, content: str, target_repo: str) -> bool:
    """判断升级源码是否已经配置为目标仓库，包括分开配置 owner/repo 的写法。"""
    if not is_update_source(path, content):
        return False
    if target_repo in content:
        return True
    owner, repo = target_repo.split("/", 1)
    owner_pattern = re.compile(
        r"(?i)\b(?:GITHUB_OWNER|REPO_OWNER|REPOSITORY_OWNER|OWNER)\s*[:=]\s*[\"']"
        + re.escape(owner) + r"[\"']"
    )
    repo_pattern = re.compile(
        r"(?i)\b(?:GITHUB_REPO|REPO_NAME|REPOSITORY_NAME|REPO)\s*[:=]\s*[\"']"
        + re.escape(repo) + r"[\"']"
    )
    return bool(owner_pattern.search(content) and repo_pattern.search(content))


def has_old_update_reference(path: Path, content: str) -> bool:
    """判断升级端点是否仍指向上游；普通项目主页链接不算升级端点。"""
    if not is_update_source(path, content):
        return False
    if re.search(r"(?i)https?://api\.github\.com/repos/" + re.escape(OLD_REPO), content):
        return True
    if re.search(r"(?i)https?://github\.com/" + re.escape(OLD_REPO) + r"/releases(?:/|\b)", content):
        return True
    if re.search(r"([\"'])" + re.escape(OLD_REPO) + r"\1", content):
        return True
    owner_pattern = re.compile(
        r"(?i)\b(?:GITHUB_OWNER|REPO_OWNER|REPOSITORY_OWNER|OWNER)\s*[:=]\s*[\"']rfandango[\"']"
    )
    return bool(owner_pattern.search(content))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="上游源码根目录")
    parser.add_argument("--repository", required=True, help="汉化发行仓库，格式为 owner/repo")
    parser.add_argument("--report", required=True, help="输出补丁审查报告路径")
    args = parser.parse_args()

    target_repo = args.repository.strip().strip("/")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", target_repo):
        raise SystemExit(f"无效的 GitHub 仓库名称：{args.repository!r}")

    root = Path(args.root).resolve()
    android_root = root / "android"
    source_root = android_root / "app/src/main"
    if not source_root.is_dir():
        raise SystemExit(f"找不到 Android 应用源码目录：{source_root}")

    changed_files: list[str] = []
    already_target_files: list[str] = []

    # 只遍历 Android 应用的资源与源码，不扫描 native 构建目录、依赖或生成产物。
    for path in sorted(source_root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            original = normalize_text(path)
        except (UnicodeDecodeError, OSError):
            continue

        owner_old_pattern = re.compile(
            r"(?i)\b(?:GITHUB_OWNER|REPO_OWNER|REPOSITORY_OWNER|OWNER)\s*[:=]\s*[\"']rfandango[\"']"
        )
        separate_repo_pattern = re.compile(
            r"(?i)\b(?:GITHUB_REPO|REPO_NAME|REPOSITORY_NAME|REPO)\s*[:=]\s*[\"']hakuX[\"']"
        )
        is_separate_old_repo = bool(owner_old_pattern.search(original) and separate_repo_pattern.search(original))
        is_separate_target_repo = has_target_update_reference(path, original, target_repo)
        if OLD_REPO not in original and target_repo not in original and not is_separate_old_repo and not is_separate_target_repo:
            continue
        if not is_update_source(path, original):
            continue

        relative = path.relative_to(root).as_posix()
        if is_separate_target_repo:
            already_target_files.append(relative)

        if OLD_REPO not in original and not is_separate_old_repo:
            continue

        updated, replacements = patch_file(path, original, target_repo)
        if replacements:
            path.write_text(updated, encoding="utf-8", newline="\n")
            changed_files.append(f"{relative}（替换 {replacements} 处）")

    # 重新检查升级相关源码，避免地址仍指向官方仓库却悄悄继续发布。
    remaining: list[str] = []
    for path in sorted(source_root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            content = normalize_text(path)
        except (UnicodeDecodeError, OSError):
            continue
        if has_old_update_reference(path, content):
            remaining.append(path.relative_to(root).as_posix())

    report_path = Path(args.report).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_lines = [
        "# 应用内升级仓库切换报告",
        "",
        f"- 目标仓库：`{target_repo}`",
        f"- 修改文件数：{len(changed_files)}",
        "",
        "## 修改记录",
        "",
    ]
    report_lines.extend(f"- {item}" for item in changed_files)
    if not changed_files:
        report_lines.append("- 本次没有修改文件；检查是否已经指向目标仓库。")
    report_lines.extend(["", "## 已指向目标仓库的候选文件", ""])
    report_lines.extend(f"- `{item}`" for item in already_target_files)
    if not already_target_files:
        report_lines.append("- 未发现已经指向目标仓库的升级源码文件。")
    report_lines.extend(["", "## 仍指向上游的升级源码", ""])
    report_lines.extend(f"- `{item}`" for item in remaining)
    if not remaining:
        report_lines.append("- 未发现残留的上游仓库引用。")
    report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8", newline="\n")

    print(f"[升级检查] 目标仓库：{target_repo}")
    print(f"[升级检查] 修改文件：{len(changed_files)}")
    for item in changed_files:
        print(f"[升级检查] {item}")
    print(f"[升级检查] 审查报告：{report_path}")

    if remaining:
        raise SystemExit(
            "升级检查源码仍含 rfandango/hakuX，拒绝发布以免继续检查官方版本："
            + ", ".join(remaining)
        )
    if not changed_files and not already_target_files:
        raise SystemExit(
            "没有找到可确认的升级检查仓库引用。上游可能更改了更新机制；"
            "请检查 android/app/src/main 下的升级代码后再调整脚本。"
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"升级仓库补丁失败：{exc}", file=sys.stderr)
        raise
