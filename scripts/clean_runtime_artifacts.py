#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""WNMP Runtime 运行产物清理脚本

用于打包前手动清理运行时产生的临时文件、缓存、日志等产物。
默认只清理运行产物，不会删除用户二进制、配置文件、数据库数据。

用法：
    python scripts/clean_runtime_artifacts.py          # 实际清理
    python scripts/clean_runtime_artifacts.py --dry-run # 仅预览，不删除

安全边界：
    - 不删除 bin/python（内置 Python 运行时）
    - 不删除 bin/nginx、bin/php、bin/mysql（用户放入的二进制目录）
    - 不删除 config/ 下的用户配置文件（仅清理 config/backup/ 下的临时备份）
    - 不删除数据库数据目录
    - 不删除前端资源、默认配置模板、初始化脚本
"""

import os
import sys
import shutil
import argparse


def find_root_dir():
    """定位项目根目录（脚本位于 scripts/ 下，根目录是其父目录）"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(script_dir)
    # 校验：根目录下应有 VERSION 或 runtime/ 目录
    if not os.path.isdir(os.path.join(root, "runtime")):
        print("[ERROR] 无法定位项目根目录，请确保脚本位于 scripts/ 下")
        sys.exit(1)
    return root


def collect_artifacts(root_dir):
    """收集所有需要清理的运行产物路径"""
    items = []

    # 1. __pycache__ 目录（收集目录即可，不单独收集 .pyc，避免重复列出）
    for dirpath, dirnames, filenames in os.walk(root_dir):
        # 跳过 bin/python 目录（内置 Python，其 lib 下有 .pyc 是分发文件）
        if "bin" in dirpath.split(os.sep) and "python" in dirpath.split(os.sep):
            continue
        if "__pycache__" in dirnames:
            items.append(("dir", os.path.join(dirpath, "__pycache__")))

    # 2. logs/ 下的运行日志（保留目录结构）
    logs_dir = os.path.join(root_dir, "logs")
    if os.path.isdir(logs_dir):
        for dirpath, dirnames, filenames in os.walk(logs_dir):
            for fn in filenames:
                if fn.endswith(".log"):
                    items.append(("file", os.path.join(dirpath, fn)))

    # 3. runtime/tmp 目录
    tmp_dir = os.path.join(root_dir, "runtime", "tmp")
    if os.path.isdir(tmp_dir):
        items.append(("dir", tmp_dir))

    # 4. runtime/pids 目录下的 PID 文件
    pids_dir = os.path.join(root_dir, "runtime", "pids")
    if os.path.isdir(pids_dir):
        for fn in os.listdir(pids_dir):
            if fn.endswith(".pid"):
                items.append(("file", os.path.join(pids_dir, fn)))

    # 5. runtime/state.json（运行时状态文件）
    state_file = os.path.join(root_dir, "runtime", "state.json")
    if os.path.isfile(state_file):
        items.append(("file", state_file))

    # 6. config/backup/ 下的临时备份
    backup_dir = os.path.join(root_dir, "config", "backup")
    if os.path.isdir(backup_dir):
        for fn in os.listdir(backup_dir):
            fp = os.path.join(backup_dir, fn)
            if os.path.isfile(fp):
                items.append(("file", fp))

    # 7. panel 临时结果文件
    panel_tmp = os.path.join(root_dir, "runtime", "panel", "tmp")
    if os.path.isdir(panel_tmp):
        items.append(("dir", panel_tmp))

    return items


def clean_artifacts(items, dry_run=False):
    """清理收集到的运行产物"""
    removed = 0
    for kind, path in items:
        if not os.path.exists(path):
            continue
        if dry_run:
            print("  [DRY-RUN] 将删除: {} {}".format(kind, path))
        else:
            try:
                if kind == "dir":
                    shutil.rmtree(path)
                else:
                    os.remove(path)
                print("  [DELETED] {} {}".format(kind, path))
            except Exception as e:
                print("  [ERROR] 删除失败: {} - {}".format(path, e))
                continue
        removed += 1
    return removed


def main():
    parser = argparse.ArgumentParser(description="WNMP Runtime 运行产物清理脚本")
    parser.add_argument("--dry-run", action="store_true",
                        help="仅预览将清理的路径，不实际删除")
    args = parser.parse_args()

    root_dir = find_root_dir()
    print("项目根目录: {}".format(root_dir))
    print("模式: {}".format("--dry-run（预览）" if args.dry_run else "实际清理"))
    print("")

    items = collect_artifacts(root_dir)
    if not items:
        print("未发现需要清理的运行产物。")
        return

    print("发现 {} 项运行产物:".format(len(items)))
    removed = clean_artifacts(items, dry_run=args.dry_run)
    print("")
    if args.dry_run:
        print("预览完成，共 {} 项将被清理。使用不带 --dry-run 参数执行实际清理。".format(removed))
    else:
        print("清理完成，共删除 {} 项。".format(removed))


if __name__ == "__main__":
    main()
