# -*- coding: utf-8 -*-
"""轻量测试脚本：验证 wnmp_autostart 核心逻辑

测试内容：
1. _validate_service_name 安全校验
2. _normalize_path 路径比较（Windows 下断言大小写无关，非 Windows 跳过）
3. autostart_status 返回结构验证（仅 Windows，非 Windows 跳过）
4. autostart_task_name 持久化
"""
import sys
import os
import platform

# 添加项目根目录到 sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, root_dir)

from runtime.wnmp_autostart import _validate_service_name, _normalize_path

passed = 0
failed = 0
skipped = 0
IS_WINDOWS = platform.system() == "Windows"


def test(name, condition, detail=""):
    global passed, failed
    if condition:
        print("  [PASS] {}".format(name))
        passed += 1
    else:
        print("  [FAIL] {} {}".format(name, detail))
        failed += 1


def skip(name, reason=""):
    global skipped
    print("  [SKIP] {} {}".format(name, reason))
    skipped += 1


print("=== wnmp_autostart Core Logic Tests ===\n")
print("Platform: {} | IS_WINDOWS={}\n".format(platform.system(), IS_WINDOWS))

# --- _validate_service_name ---
print("1. SERVICE_NAME validation:")

ok, reason = _validate_service_name("WNMPRuntime")
test("Default name WNMPRuntime", ok)

ok, reason = _validate_service_name("DacatRuntime")
test("Custom name DacatRuntime", ok)

ok, reason = _validate_service_name("My-Service.v2")
test("Name with hyphen and dot", ok)

ok, reason = _validate_service_name("Test Service")
test("Name with space", ok)

ok, reason = _validate_service_name("")
test("Empty name rejected", not ok)

ok, reason = _validate_service_name("Bad\\Name")
test("Backslash rejected", not ok)

ok, reason = _validate_service_name('Bad"Name')
test("Quote rejected", not ok)

ok, reason = _validate_service_name("Bad/Name")
test("Forward slash rejected", not ok)

ok, reason = _validate_service_name("Bad|Name")
test("Pipe rejected", not ok)

ok, reason = _validate_service_name("\\Folder\\TaskName")
test("Path-style name rejected", not ok)

ok, reason = _validate_service_name("Name;rm")
test("Semicolon rejected", not ok)

# --- _normalize_path ---
print("\n2. Path normalization:")

# 空路径在所有平台行为一致
test("Empty path returns empty", _normalize_path("") == "")

# 尾部分隔符去除在所有平台行为一致
test("Trailing separator stripped",
     _normalize_path("test" + os.sep + "path" + os.sep) == _normalize_path("test" + os.sep + "path"))

# Windows 特有：盘符大小写无关 + 路径分隔符归一
if IS_WINDOWS:
    test("Windows path case insensitive",
         _normalize_path("C:\\test\\path") == _normalize_path("c:\\TEST\\PATH"))
else:
    # 非 Windows：normcase 不做大小写转换，跳过盘符大小写断言
    skip("Windows path case insensitive", "(non-Windows platform)")

# --- autostart_status on current system ---
print("\n3. Current system autostart_status (real query):")
if IS_WINDOWS:
    try:
        from runtime.wnmp_config import load_config
        from runtime.wnmp_log import setup_logging
        from runtime.wnmp_autostart import autostart_status

        cfg = load_config(root_dir)
        logger = setup_logging(root_dir)
        result = autostart_status(root_dir, cfg, logger)

        test("Returns dict with required keys",
             all(k in result for k in ["query_ok", "exists", "enabled", "state",
                                        "task_name", "message", "owned"]))

        valid_states = {"enabled", "disabled", "not_found", "invalid", "error", "timeout", "conflict"}
        test("State is valid: {}".format(result["state"]),
             result["state"] in valid_states)

        test("owned field present (None or bool)",
             result["owned"] is None or isinstance(result["owned"], bool))

        print("  Current state: {} message: {} owned: {}".format(
            result["state"], result["message"], result["owned"]))
    except Exception as e:
        test("autostart_status on current system", False, str(e))
else:
    skip("Real schtasks query", "(non-Windows platform)")

# --- _load_autostart_task_name / _save_autostart_task_name ---
print("\n4. autostart_task_name persistence:")
try:
    from runtime.wnmp_autostart import _save_autostart_task_name, _load_autostart_task_name, _clear_autostart_task_name
    from runtime.wnmp_log import setup_logging
    logger = setup_logging(root_dir)

    # 保存
    _save_autostart_task_name(root_dir, "TestTask", logger)
    loaded = _load_autostart_task_name(root_dir)
    test("Save and load task name", loaded == "TestTask")

    # 清除
    _clear_autostart_task_name(root_dir, logger)
    loaded = _load_autostart_task_name(root_dir)
    test("Clear task name", loaded is None)
except Exception as e:
    test("autostart_task_name persistence", False, str(e))

# --- Summary ---
print("\n=== Results: {} passed, {} failed, {} skipped ===".format(passed, failed, skipped))
sys.exit(1 if failed > 0 else 0)
