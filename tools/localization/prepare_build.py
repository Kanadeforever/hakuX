#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
准备 hakuX 简体中文发行构建。

只为汉化版设置独立应用包名，并生成 Gradle 使用的签名配置。上游 versionCode 与 versionName 保持原样。
签名密钥由 GitHub Actions Secrets 提供，不会写入源码归档或 Git 仓库。
"""

import argparse
import re
import sys
from pathlib import Path


def write_crlf(path, content):
    """统一使用 UTF-8 无 BOM 与 CRLF 写入生成文件。"""
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    path.write_text(normalized, encoding="utf-8", newline="\r\n")


def patch_application_id(path):
    """只为汉化版追加独立包名后缀，不改动上游版本号或版本编码。"""
    text = path.read_text(encoding="utf-8")
    app_pattern = re.compile(
        r'(?m)^(\s*applicationId\s*(?:=\s*)?)(["\'])([^"\']+)(\2)'
    )
    app_match = app_pattern.search(text)
    if not app_match:
        raise RuntimeError(f"{path} 中找不到 applicationId，拒绝猜测包名。")

    current_id = app_match.group(3)
    new_id = current_id if current_id.endswith(".zhcn") else current_id + ".zhcn"
    text = app_pattern.sub(
        lambda match: match.group(1) + match.group(2) + new_id + match.group(4),
        text,
        count=1,
    )
    write_crlf(path, text)
    print(f"包名：{current_id} -> {new_id}")
    print("保留上游 versionCode 和 versionName，不修改应用版本元数据。")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--keystore", required=True)
    parser.add_argument("--keystore-password", required=True)
    parser.add_argument("--key-alias", required=True)
    parser.add_argument("--key-password", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    android_dir = root / "android"
    gradle_files = [
        android_dir / "app/build.gradle.kts",
        android_dir / "app/build.gradle",
    ]
    gradle_file = next((p for p in gradle_files if p.is_file()), None)
    if gradle_file is None:
        raise SystemExit("找不到 android/app/build.gradle.kts 或 build.gradle。")

    patch_application_id(gradle_file)

    # 上游脚本若使用 Windows 专用扩展名，在 Linux NDK 环境中改用 llvm-strip。
    strip_script = root / "tools/native/app-libs.sh"
    if strip_script.is_file():
        content = strip_script.read_text(encoding="utf-8")
        content = content.replace("llvm-strip.exe", "llvm-strip")
        write_crlf(strip_script, content)

    keystore = Path(args.keystore).resolve()
    if not keystore.is_file():
        raise SystemExit(f"找不到 GitHub Secrets 恢复的签名密钥：{keystore}")

    # 同时放置于 Android 根目录与 app 模块目录，兼容两种常见 Gradle 引用方式。
    # 密码来自仓库 Secrets；不在源码中保存，也不写入发行源码附件。
    properties = (
        f"storeFile={keystore}\n"
        f"storePassword={args.keystore_password}\n"
        f"keyAlias={args.key_alias}\n"
        f"keyPassword={args.key_password}\n"
    )
    for path in (
        android_dir / "key.properties",
        android_dir / "app/key.properties",
    ):
        write_crlf(path, properties)

    print("已生成 Gradle 签名配置。")
    print("签名文件由 GitHub Secrets 恢复，不会复制进源码发行包。")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"发行构建准备失败：{exc}", file=sys.stderr)
        raise
