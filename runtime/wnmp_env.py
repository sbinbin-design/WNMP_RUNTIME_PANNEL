# -*- coding: utf-8 -*-
"""
WNMP Environment Module - 系统 PATH 管理
使用 Python 标准库实现，不依赖第三方包
"""
import os
import ctypes
from ctypes import wintypes
import winreg
from datetime import datetime


ENV_VAR_KEY = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
HWND_BROADCAST = 0xFFFF
WM_SETTINGCHANGE = 0x1A
SMTO_ABORTIFHUNG = 0x0002


def is_admin():
    """检查当前进程是否有管理员权限。"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def normalize_path(path_str):
    """规范化路径：大写盘符、反斜杠转正斜杠、去除尾部斜杠。"""
    if not path_str:
        return ""
    path_str = path_str.strip().rstrip("/").rstrip("\\")
    if len(path_str) >= 2 and path_str[1] == ":":
        path_str = path_str[0].upper() + path_str[1:]
    return path_str.replace("\\", "/")


def path_equals(p1, p2):
    """比较两个路径是否相同（大小写不敏感、兼容斜杠差异）。"""
    return normalize_path(p1) == normalize_path(p2)


def get_system_path():
    """读取系统 PATH 环境变量。"""
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, ENV_VAR_KEY, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, "Path")
            return value
    except Exception:
        return ""


def set_system_path(new_path):
    """写入系统 PATH 环境变量。

    返回 (success, error_msg)
    注意：必须管理员权限才能调用。
    """
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, ENV_VAR_KEY, 0,
                            winreg.KEY_WRITE | winreg.KEY_READ) as key:
            winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, new_path)
        return True, ""
    except Exception as e:
        return False, str(e)


def send_settingchange_broadcast():
    """广播 WM_SETTINGCHANGE 通知系统环境变量已更改。

    返回 (success, error_msg)
    """
    try:
        SendMessageTimeoutW = ctypes.windll.user32.SendMessageTimeoutW
        SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT,
                                        wintypes.WPARAM, wintypes.LPCWSTR,
                                        wintypes.UINT, wintypes.UINT,
                                        ctypes.POINTER(wintypes.DWORD)]
        SendMessageTimeoutW.restype = wintypes.LPARAM

        result = wintypes.DWORD()
        SendMessageTimeoutW(
            HWND_BROADCAST,
            WM_SETTINGCHANGE,
            0,
            "Environment",
            SMTO_ABORTIFHUNG,
            5000,
            ctypes.byref(result)
        )
        return True, ""
    except Exception as e:
        return False, str(e)


def get_tool_paths(root_dir, add_openssl=False):
    """获取本工具需要加入 PATH 的目录列表。

    返回绝对路径列表，已规范化。
    """
    root_dir_abs = os.path.abspath(root_dir).replace("\\", "/")

    paths = [
        os.path.join(root_dir_abs, "bin", "php"),
        os.path.join(root_dir_abs, "bin", "mysql", "bin"),
        os.path.join(root_dir_abs, "bin", "nginx"),
    ]

    if add_openssl:
        paths.append(os.path.join(root_dir_abs, "bin", "openssl"))

    return [normalize_path(p) for p in paths]


def get_current_path_list():
    """获取当前系统 PATH 列表（已规范化）。"""
    system_path = get_system_path()
    if not system_path:
        return []
    return [normalize_path(p) for p in system_path.split(";") if p.strip()]


def is_path_in_system_path(tool_path):
    """检查某个工具路径是否已存在于系统 PATH。"""
    normalized_tool = normalize_path(tool_path)
    current_list = get_current_path_list()
    return any(path_equals(p, normalized_tool) for p in current_list)


def add_tool_paths_to_system_path(root_dir, add_openssl=False):
    """将工具路径添加到系统 PATH（幂等）。

    返回 (success, added_count, skipped_count, error_msg)
    - 如果没有管理员权限，返回 (False, 0, 0, "requires_admin")
    """
    if not is_admin():
        return False, 0, 0, "requires_admin"

    tool_paths = get_tool_paths(root_dir, add_openssl)
    current_list = get_current_path_list()
    new_entries = []

    for tool_path in tool_paths:
        found = False
        for existing in current_list:
            if path_equals(existing, tool_path):
                found = True
                break
        if not found:
            new_entries.append(tool_path)

    if not new_entries:
        return True, 0, len(tool_paths), ""

    new_path = ";".join(current_list + new_entries)
    ok, err = set_system_path(new_path)
    if not ok:
        return False, 0, 0, err

    send_settingchange_broadcast()

    return True, len(new_entries), len(tool_paths) - len(new_entries), ""


def remove_tool_paths_from_system_path(root_dir, add_openssl=False):
    """从系统 PATH 移除工具路径（幂等，不破坏其它路径）。

    返回 (success, removed_count, error_msg)
    - 如果没有管理员权限，返回 (False, 0, "requires_admin")
    """
    if not is_admin():
        return False, 0, "requires_admin"

    tool_paths = get_tool_paths(root_dir, add_openssl)
    current_list = get_current_path_list()
    new_list = []
    removed_count = 0

    for existing in current_list:
        found = False
        for tool_path in tool_paths:
            if path_equals(existing, tool_path):
                found = True
                break
        if found:
            removed_count += 1
        else:
            new_list.append(existing)

    if removed_count == 0:
        return True, 0, ""

    new_path = ";".join(new_list)
    ok, err = set_system_path(new_path)
    if not ok:
        return False, 0, err

    send_settingchange_broadcast()

    return True, removed_count, ""


def get_path_items_status(root_dir, add_openssl=False):
    """获取本工具各路径在系统 PATH 中的状态。

    返回列表，每项 (path, in_system_path)
    """
    tool_paths = get_tool_paths(root_dir, add_openssl)
    current_list = get_current_path_list()
    result = []

    for tool_path in tool_paths:
        in_path = any(path_equals(existing, tool_path) for existing in current_list)
        result.append((tool_path, in_path))

    return result


def check_path_migration(root_dir, state_path_items=None):
    """检测工具目录是否被移动（路径迁移）。

    如果 state_path_items 中的路径与当前工具路径不一致，返回 True。
    """
    if state_path_items is None:
        return False

    current_tool_paths = set(normalize_path(p) for p in get_tool_paths(root_dir, True))

    for old_path in state_path_items:
        normalized_old = normalize_path(old_path)
        if normalized_old not in current_tool_paths:
            return True

    return False


def format_path_status_summary(root_dir, add_openssl=False):
    """格式化路径状态摘要（用于 status 输出）。"""
    tool_paths = get_tool_paths(root_dir, add_openssl)
    current_list = get_current_path_list()
    lines = []

    for tool_path in tool_paths:
        in_path = any(path_equals(existing, tool_path) for existing in current_list)
        name = os.path.basename(os.path.dirname(tool_path))
        if os.path.basename(tool_path) != "bin":
            name = os.path.basename(tool_path)
        status = "IN PATH" if in_path else "NOT IN PATH"
        lines.append("  {}: {} ({})".format(name, status, tool_path))

    return "\n".join(lines)