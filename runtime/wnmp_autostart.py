# -*- coding: utf-8 -*-
"""
WNMP AutoStart Module - Windows 计划任务管理
使用 Python 标准库 + schtasks 实现，不依赖第三方包
"""
import os
import subprocess
import ctypes
import re


def is_admin():
    """判断当前用户是否具有管理员权限。"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


def _validate_service_name(name):
    """校验 SERVICE_NAME 是否为安全的计划任务名称。

    允许字母、数字、下划线、中划线、点、空格等安全字符。
    不允许斜杠、反斜杠、引号、管道、重定向等命令特殊字符。
    返回 (ok: bool, reason: str)
    """
    if not name or not name.strip():
        return False, "SERVICE_NAME 不能为空"
    # 禁止包含路径分隔符、引号、命令特殊字符
    forbidden = re.search(r'[\\/"\'|<>&$`;!]', name)
    if forbidden:
        return False, "SERVICE_NAME 包含不允许的字符: {}".format(forbidden.group(0))
    # 允许的字符集：字母、数字、下划线、中划线、点、空格、中文等 Unicode 字母
    if not re.match(r'^[\w\s.\-]+$', name, re.UNICODE):
        return False, "SERVICE_NAME 包含不允许的字符，仅允许字母、数字、下划线、中划线、点、空格"
    return True, ""


def install_autostart(root_dir, cfg, logger):
    r"""安装开机自启动计划任务。

    使用项目内置 Python：python.exe -u "<rootDir>\runtime\wnmpctl.py" start --autostart
    计划任务工作目录设为项目根目录 rootDir。
    优先使用 schtasks /Create /XML 创建（支持 WorkingDirectory），
    PowerShell 不可用时回退到 schtasks 原始方式（不设 Start In）。
    需要管理员权限。
    """
    from runtime.wnmp_log import log_info, log_error, log_warn
    from runtime import wnmp_config

    # 未初始化门控：不允许在未初始化环境下创建自启动任务
    from runtime.wnmp_state import is_initialized
    if not is_initialized(root_dir):
        log_error(logger, "Cannot install auto-start: environment not initialized")
        print("ERROR: 环境尚未初始化，请先初始化 Nginx/PHP/MySQL 后再启用开机自启动")
        return 1

    if not is_admin():
        log_error(logger, "Administrator privileges required to install auto-start")
        print("ERROR: Administrator privileges required.")
        print("Please run this script as Administrator.")
        return 1

    service_name = wnmp_config.get(cfg, "SERVICE_NAME", "WNMPRuntime")
    service_display_name = wnmp_config.get(cfg, "SERVICE_DISPLAY_NAME", "WNMP Runtime Service")

    # SERVICE_NAME 安全校验
    name_ok, name_reason = _validate_service_name(service_name)
    if not name_ok:
        log_error(logger, "SERVICE_NAME validation failed: " + name_reason)
        print("ERROR: " + name_reason)
        return 1

    python_exe = os.path.join(root_dir, "bin", "python", "python.exe")

    # 构建执行命令：使用绝对脚本路径，不依赖 -m 和 ._pth
    wnmpctl_script = os.path.join(root_dir, "runtime", "wnmpctl.py")
    # /TR 格式：python.exe -u "rootDir\runtime\wnmpctl.py" start --autostart
    task_cmd = '"{}" -u "{}" start --autostart'.format(python_exe, wnmpctl_script)

    log_info(logger, "Installing auto-start scheduled task: " + service_name)
    log_info(logger, "Task command: " + task_cmd)
    log_info(logger, "Working directory: " + root_dir)

    # 尝试 XML 方式创建任务（支持 WorkingDirectory）
    if _install_via_xml(service_name, service_display_name, task_cmd, root_dir, logger):
        # 强校验：注册后立即验证任务确实存在且配置完全正确
        verify = autostart_status(root_dir, cfg, logger)
        verify_ok, verify_reason = _verify_autostart_task(verify, root_dir, python_exe, logger)

        if verify_ok:
            _update_auto_start_flag(root_dir, "1")
            # 记录实际安装的任务名到 state.json，用于后续卸载兜底
            _save_autostart_task_name(root_dir, service_name, logger)
            print("Auto-start scheduled task '{}' installed successfully.".format(service_name))
            print("The task will run at system startup (WorkingDirectory: {}).".format(
                verify.get("working_directory", root_dir)))
            log_info(logger, "Auto-start install verified: exists={} enabled={} working_directory={} task_name={}".format(
                verify.get("exists"), verify.get("enabled"), verify.get("working_directory"), service_name))
            return 0
        else:
            # 注册成功但验证失败：记录详细原因，标记为失败，返回 1
            log_error(logger, "Auto-start task registered but verification failed: {}".format(verify_reason))
            log_error(logger, "  verify detail: exists={}, enabled={}, working_directory={}, expected_root_dir={}".format(
                verify.get("exists"), verify.get("enabled"), verify.get("working_directory"), root_dir))
            log_error(logger, "  command={}, arguments={}, state={}, warning={}, error={}".format(
                verify.get("command"), verify.get("arguments"), verify.get("state"),
                verify.get("warning"), verify.get("error")))
            print("ERROR: Task registered but verification failed: {}".format(verify_reason))
            print("See action output log for details.")
            _update_auto_start_flag(root_dir, "0")
            return 1

    # XML 注册失败，不再 fallback 到 schtasks（不支持 WorkingDirectory，不是正式成功路径）
    log_error(logger, "XML task creation failed, auto-start NOT installed")
    print("ERROR: Failed to create auto-start scheduled task (XML registration failed).")
    print("The XML file has been preserved for debugging. Check the logs for details.")
    return 1


def _normalize_path(p):
    """规范化路径用于比较：abspath + normcase + normpath + 去除尾部分隔符。"""
    if not p:
        return ""
    p = os.path.abspath(p)
    p = os.path.normcase(p)
    p = os.path.normpath(p)
    return p.rstrip("\\/")


def _validate_task_definition(info, root_dir, expected_python_exe):
    """校验任务定义是否与当前项目一致（公共函数）。

    install_autostart 的强校验和 autostart_status 的状态判断共用此逻辑，
    避免一处严格一处宽松。

    Args:
        info: dict，包含 command/arguments/working_directory 字段
        root_dir: 项目根目录
        expected_python_exe: 预期的 python.exe 路径

    Returns:
        (ok: bool, reason: str, warning: str)
        ok=True 表示校验通过，reason/warning 为空；
        ok=False 时 reason 包含具体失败类别，warning 包含人类可读提示。
    """
    # working_directory 校验
    wd = info.get("working_directory", "")
    if not wd:
        return False, "working_directory_missing", "任务存在，但 WorkingDirectory 缺失或不属于当前 WNMP Runtime"
    if _normalize_path(wd) != _normalize_path(root_dir):
        return False, "working_directory_mismatch", "任务存在，但 WorkingDirectory 缺失或不属于当前 WNMP Runtime"

    # command 校验
    cmd = info.get("command", "")
    if not cmd:
        return False, "command_missing", "任务存在但 Python 路径不属于当前 WNMP Runtime"
    if _normalize_path(cmd) != _normalize_path(expected_python_exe):
        return False, "command_mismatch", "任务存在但 Python 路径不属于当前 WNMP Runtime"

    # arguments 校验：期望 -u "<rootDir>\runtime\wnmpctl.py" start --autostart
    args = info.get("arguments", "")
    wnmpctl_script = os.path.join(root_dir, "runtime", "wnmpctl.py")
    expected_args = '-u "{}" start --autostart'.format(wnmpctl_script)
    if not args:
        return False, "arguments_missing", "任务存在但启动参数不正确"
    if args.strip() != expected_args:
        # 兼容旧版 -m 参数格式，识别为 invalid
        if "-m runtime.wnmpctl" in args:
            return False, "arguments_legacy_format", "旧任务参数不符合当前版本，请重新启用开机自启动"
        return False, "arguments_mismatch", "任务存在但启动参数不正确"

    return True, "", ""


def _verify_autostart_task(verify, root_dir, expected_python_exe, logger):
    """强校验 autostart 任务是否完全符合预期（install_autostart 使用）。

    基于 _validate_task_definition 公共函数，额外检查 state/exists/enabled。
    只有完全匹配才返回 (True, "")。

    Returns:
        (ok: bool, reason: str) - ok=True 表示验证通过，reason 为空；
        ok=False 时 reason 包含具体失败原因。
    """
    from runtime.wnmp_log import log_warn

    # state 校验：只有 state=enabled 才可能通过验证
    state = verify.get("state", "")
    if state not in ("enabled",):
        return False, "state={} (expected enabled; invalid/error/disabled/not_found all fail)".format(state)

    # exists 校验
    if not verify.get("exists"):
        return False, "exists=false (task not found after registration)"

    # enabled 校验
    if not verify.get("enabled"):
        return False, "enabled=false (task exists but not enabled)"

    # 任务定义校验（公共函数）
    ok, reason, warning = _validate_task_definition(verify, root_dir, expected_python_exe)
    if not ok:
        # 记录详细原因到日志
        log_warn(logger, "Auto-start task definition validation failed: reason={}, detail: command='{}' expected='{}', arguments='{}' expected_args_format='-u \"<rootDir>\\runtime\\wnmpctl.py\" start --autostart', working_directory='{}' expected='{}'".format(
            reason, verify.get("command", ""), expected_python_exe,
            verify.get("arguments", ""), verify.get("working_directory", ""), root_dir))
        return False, "{}: {}".format(reason, warning)

    return True, ""


def _install_via_xml(task_name, display_name, task_cmd, working_dir, logger):
    """通过 ElementTree 生成 XML 任务定义创建计划任务，支持 WorkingDirectory。

    使用 xml.etree.ElementTree 构建 Task XML，自动转义特殊字符。
    生成 XML -> 自检 XML 合法性 -> schtasks /Create /XML -> 注册成功后删除临时 XML。
    返回 True/False。
    """
    from runtime.wnmp_log import log_info, log_error
    import tempfile
    import xml.etree.ElementTree as ET

    python_exe = os.path.join(working_dir, "bin", "python", "python.exe")

    # 使用 ElementTree 构建 XML，自动转义 Command/Arguments/WorkingDirectory 中的特殊字符
    ns = "http://schemas.microsoft.com/windows/2004/02/mit/task"
    ET.register_namespace("", ns)

    task = ET.Element("Task")
    task.set("version", "1.2")
    task.set("xmlns", ns)

    # RegistrationInfo
    reg_info = ET.SubElement(task, "RegistrationInfo")
    ET.SubElement(reg_info, "Description").text = display_name

    # Triggers
    triggers = ET.SubElement(task, "Triggers")
    boot_trigger = ET.SubElement(triggers, "BootTrigger")
    ET.SubElement(boot_trigger, "Enabled").text = "true"

    # Principals - SYSTEM 账户，不写 LogonType（避免 ServiceAccount schema 错误）
    principals = ET.SubElement(task, "Principals")
    principal = ET.SubElement(principals, "Principal")
    principal.set("id", "Author")
    ET.SubElement(principal, "UserId").text = "S-1-5-18"
    ET.SubElement(principal, "RunLevel").text = "HighestAvailable"

    # Settings
    settings = ET.SubElement(task, "Settings")
    ET.SubElement(settings, "MultipleInstancesPolicy").text = "IgnoreNew"
    ET.SubElement(settings, "DisallowStartIfOnBatteries").text = "false"
    ET.SubElement(settings, "StopIfGoingOnBatteries").text = "false"
    ET.SubElement(settings, "AllowHardTerminate").text = "true"
    ET.SubElement(settings, "StartWhenAvailable").text = "false"
    ET.SubElement(settings, "RunOnlyIfNetworkAvailable").text = "false"
    idle_settings = ET.SubElement(settings, "IdleSettings")
    ET.SubElement(idle_settings, "StopOnIdleEnd").text = "false"
    ET.SubElement(idle_settings, "RestartOnIdle").text = "false"
    ET.SubElement(settings, "AllowStartOnDemand").text = "true"
    ET.SubElement(settings, "Enabled").text = "true"
    ET.SubElement(settings, "Hidden").text = "false"
    ET.SubElement(settings, "RunOnlyIfIdle").text = "false"
    ET.SubElement(settings, "WakeToRun").text = "false"
    ET.SubElement(settings, "ExecutionTimeLimit").text = "PT0S"
    ET.SubElement(settings, "Priority").text = "7"

    # Actions
    actions = ET.SubElement(task, "Actions")
    actions.set("Context", "Author")
    exec_elem = ET.SubElement(actions, "Exec")
    ET.SubElement(exec_elem, "Command").text = python_exe
    wnmpctl_script = os.path.join(working_dir, "runtime", "wnmpctl.py")
    ET.SubElement(exec_elem, "Arguments").text = '-u "{}" start --autostart'.format(wnmpctl_script)
    ET.SubElement(exec_elem, "WorkingDirectory").text = working_dir

    xml_path = None
    try:
        # 写入临时 XML 文件（UTF-16 编码，Python 自动写入 BOM，Windows 计划任务兼容格式）
        fd, xml_path = tempfile.mkstemp(suffix=".xml", prefix="wnmp_task_")
        with os.fdopen(fd, "wb") as f:
            tree = ET.ElementTree(task)
            tree.write(f, encoding="utf-16", xml_declaration=True)

        log_info(logger, "Creating task via XML: " + xml_path)
        log_info(logger, "  Command={}".format(python_exe))
        log_info(logger, "  Arguments=-u \"{}\" start --autostart".format(wnmpctl_script))
        log_info(logger, "  WorkingDirectory={}".format(working_dir))

        # 自检 XML 合法性
        try:
            ET.parse(xml_path)
            log_info(logger, "XML self-check passed")
        except ET.ParseError as e:
            log_error(logger, "XML self-check failed: {}".format(str(e)))
            log_error(logger, "XML file preserved for debugging: " + xml_path)
            return False

        result = subprocess.run(
            ["schtasks", "/Create", "/TN", task_name, "/XML", xml_path, "/F"],
            capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=10
        )

        if result.returncode == 0:
            log_info(logger, "Auto-start task created via XML successfully")
            # 注册成功后删除临时 XML
            try:
                os.remove(xml_path)
                xml_path = None
            except Exception:
                pass
            return True
        else:
            log_error(logger, "XML task creation failed: " + (result.stderr.strip() or result.stdout.strip()))
            log_error(logger, "XML file preserved for debugging: " + xml_path)
            return False
    except subprocess.TimeoutExpired:
        log_error(logger, "XML task creation timed out")
        if xml_path:
            log_error(logger, "XML file preserved for debugging: " + xml_path)
        return False
    except Exception as e:
        log_error(logger, "XML task creation exception: " + str(e))
        if xml_path:
            log_error(logger, "XML file preserved for debugging: " + xml_path)
        return False


def uninstall_autostart(root_dir, cfg, logger):
    """卸载开机自启动计划任务。

    删除任务并更新 AUTO_START=0。
    """
    from runtime.wnmp_log import log_info, log_error
    from runtime import wnmp_config

    if not is_admin():
        log_error(logger, "Administrator privileges required to uninstall auto-start")
        print("ERROR: Administrator privileges required.")
        print("Please run this script as Administrator.")
        return 1

    service_name = wnmp_config.get(cfg, "SERVICE_NAME", "WNMPRuntime")

    # SERVICE_NAME 安全校验
    name_ok, name_reason = _validate_service_name(service_name)
    if not name_ok:
        log_error(logger, "SERVICE_NAME validation failed: " + name_reason)
        print("ERROR: " + name_reason)
        return 1

    # 需求十：依次尝试 /TN WNMPRuntime 和 /TN \WNMPRuntime，兼容带前导反斜杠的任务路径
    task_paths = [service_name, "\\" + service_name]
    # 兼容中英文 Windows：任务不存在时的错误信息
    not_found_keywords = ["not found", "找不到", "找不到指定的文件"]

    # 读取上次成功安装的任务名，用于卸载兜底
    saved_task_name = _load_autostart_task_name(root_dir)

    log_info(logger, "Uninstalling auto-start scheduled task: " + service_name)

    # 如果当前 SERVICE_NAME 与上次记录的任务名不同，也尝试删除旧任务名
    extra_paths = []
    if saved_task_name and saved_task_name != service_name:
        log_info(logger, "Also attempting to remove previously recorded task: " + saved_task_name)
        extra_paths = [saved_task_name, "\\" + saved_task_name]

    all_paths = task_paths + extra_paths

    for tp in all_paths:
        cmd = [
            "schtasks", "/Delete",
            "/TN", tp,
            "/F"  # 强制删除，不提示确认
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=10
            )

            if result.returncode == 0:
                # 强校验：删除后验证当前 SERVICE_NAME 任务确实不存在
                verify = autostart_status(root_dir, cfg, logger)
                if not verify.get("exists"):
                    log_info(logger, "Auto-start scheduled task removed and verified")
                    print("Auto-start scheduled task '{}' removed.".format(service_name))
                    _update_auto_start_flag(root_dir, "0")
                    _clear_autostart_task_name(root_dir, logger)
                    return 0
                else:
                    log_error(logger, "Auto-start task delete returned success but task still exists")
                    print("WARNING: Task deletion reported success but task still exists.")
                    _update_auto_start_flag(root_dir, "0")
                    return 1
            else:
                error_msg = result.stderr.strip()
                is_not_found = any(kw in error_msg.lower() for kw in not_found_keywords) if error_msg else False
                if is_not_found:
                    # 当前路径格式找不到任务，尝试下一个路径格式
                    continue
                else:
                    # 权限错误或其他异常
                    log_error(logger, "Failed to uninstall auto-start: " + error_msg)
                    print("ERROR: Failed to uninstall auto-start scheduled task.")
                    print("Details: " + error_msg)
                    return 1
        except subprocess.TimeoutExpired:
            log_error(logger, "Auto-start uninstall timed out")
            print("ERROR: Uninstall operation timed out.")
            return 1
        except Exception as e:
            log_error(logger, "Auto-start uninstall error: " + str(e))
            print("ERROR: " + str(e))
            return 1

    # 所有路径格式都返回"任务不存在"，视为无需删除
    log_info(logger, "Auto-start task not found in any path format, nothing to remove")
    print("Auto-start task not found, nothing to remove.")
    _update_auto_start_flag(root_dir, "0")
    _clear_autostart_task_name(root_dir, logger)
    return 0


def autostart_status(root_dir, cfg, logger):
    """查询自启动计划任务状态。

    返回结构明确区分：任务存在且启用、任务存在但禁用、任务不存在、查询超时、查询失败、配置异常、冲突。
    返回 dict:
        query_ok: bool - 查询本身是否成功（不含解析失败）
        exists: bool - 任务是否存在
        enabled: bool - 任务是否启用（exists=True 且 Settings/Enabled=true 且 working_directory 正确）
        state: str - "enabled"/"disabled"/"not_found"/"invalid"/"error"/"timeout"/"conflict"
        task_name: str - 任务名
        task_path: str - 任务路径（含前导反斜杠）
        message: str - 人类可读状态描述
        command: str - 任务命令
        arguments: str - 任务参数
        working_directory: str - 工作目录
        owned: bool or None - 任务是否属于当前项目（None=无法判断）
        warning: str or None - 警告信息
        error: str or None - 错误信息
    """
    from runtime.wnmp_log import log_info, log_warn
    from runtime import wnmp_config

    service_name = wnmp_config.get(cfg, "SERVICE_NAME", "WNMPRuntime")

    base = {
        "query_ok": False,
        "exists": False,
        "enabled": False,
        "state": "error",
        "task_name": service_name,
        "task_path": "",
        "message": "",
        "command": "",
        "arguments": "",
        "working_directory": "",
        "owned": None,
        "warning": None,
        "error": None,
    }

    # SERVICE_NAME 安全校验
    name_ok, name_reason = _validate_service_name(service_name)
    if not name_ok:
        base["state"] = "error"
        base["message"] = "SERVICE_NAME 无效"
        base["error"] = name_reason
        log_warn(logger, "SERVICE_NAME validation failed in status query: " + name_reason)
        return base

    # 检测 SERVICE_NAME 是否与上次安装的任务名不同
    saved_task_name = _load_autostart_task_name(root_dir)
    if saved_task_name and saved_task_name != service_name:
        base["warning"] = "计划任务名称已变更（{} → {}），请重新启用开机自启动以应用新名称".format(saved_task_name, service_name)
        log_warn(logger, "SERVICE_NAME changed: saved={}, current={}".format(saved_task_name, service_name))

    # 一次 XML 查询获取任务详情（合并 _query_task_exists + _parse_task_xml，避免重复调用 schtasks）
    task_result = _query_task_xml(service_name, logger)

    if not task_result.get("found"):
        # 区分：任务不存在 vs 查询超时 vs 查询失败
        reason = task_result.get("reason", "")
        if reason == "not_found":
            base["query_ok"] = True
            base["state"] = "not_found"
            base["message"] = "未启用"
            log_info(logger, "Auto-start task not found (not enabled)")
            # 明确 not_found 时修正 AUTO_START=0
            _sync_auto_start_flag(root_dir, False, logger)
            return base
        elif reason == "timeout":
            # 查询超时：降级为 WARNING，返回 timeout 状态
            base["state"] = "timeout"
            base["message"] = "检测超时"
            base["error"] = task_result.get("error", "检测超时")
            log_warn(logger, "Auto-start status query timed out")
            # state=timeout 时不修改 AUTO_START 配置
            return base
        else:
            base["state"] = "error"
            base["message"] = "查询失败"
            base["error"] = task_result.get("error", "未知错误")
            log_warn(logger, "Failed to query auto-start status: " + (task_result.get("error") or "unknown"))
            # state=error 时不修改 AUTO_START 配置
            return base

    # 任务存在，从一次查询结果中直接获取详细信息
    base["query_ok"] = True
    base["exists"] = True
    base["task_path"] = task_result.get("task_path", "")
    log_info(logger, "Auto-start task found: {} (path: {})".format(service_name, base["task_path"]))

    xml_info = task_result.get("xml_info")
    if xml_info is not None:
        base["command"] = xml_info.get("command", "")
        base["arguments"] = xml_info.get("arguments", "")
        base["working_directory"] = xml_info.get("working_directory", "")
        base["enabled"] = xml_info.get("task_enabled", True)  # 默认 True，旧任务无此字段
    else:
        # XML 解析失败，不能默认 enabled=True，应标记为 invalid
        base["enabled"] = False
        base["state"] = "invalid"
        base["message"] = "配置异常"
        base["warning"] = "任务存在，但无法解析 XML 或无法确认 WorkingDirectory"
        log_warn(logger, "Auto-start task exists but XML parse failed, cannot confirm configuration")
        # state=invalid 时不修改 AUTO_START 配置
        return base

    # 任务定义校验（使用公共函数，确保 install_autostart 和 autostart_status 逻辑一致）
    python_exe = os.path.join(root_dir, "bin", "python", "python.exe")
    def_ok, def_reason, def_warning = _validate_task_definition(base, root_dir, python_exe)

    if not def_ok:
        base["enabled"] = False
        # 区分 conflict（同名但非本项目）和 invalid（本项目但配置错误）
        if def_reason in ("command_mismatch", "command_missing",
                          "working_directory_mismatch", "working_directory_missing"):
            # command 或 working_directory 不属于当前项目 → conflict
            base["state"] = "conflict"
            base["owned"] = False
            base["message"] = "同名任务冲突"
            base["warning"] = "存在同名计划任务但不属于当前 WNMP Runtime，请检查或更换 SERVICE_NAME"
            log_warn(logger, "Auto-start task conflict: reason={}, task does not belong to current project".format(def_reason))
        else:
            # arguments 不匹配等 → invalid（可能是旧版本任务）
            base["state"] = "invalid"
            base["owned"] = True
            base["message"] = "配置异常"
            base["warning"] = def_warning
            log_warn(logger, "Auto-start task definition invalid: reason={}, command='{}' expected='{}', arguments='{}' expected_args_format='-u \"<rootDir>\\runtime\\wnmpctl.py\" start --autostart', working_directory='{}' expected='{}'".format(
                def_reason, base.get("command", ""), python_exe,
                base.get("arguments", ""), base.get("working_directory", ""), root_dir))
        # state=invalid/conflict 时不修改 AUTO_START 配置
        return base

    # 任务定义校验通过，标记为属于当前项目
    base["owned"] = True

    # 任务定义校验通过，根据 enabled 字段确定最终状态
    if base["enabled"]:
        base["state"] = "enabled"
        base["message"] = "已启用"
        # 明确 enabled 且任务定义校验通过时修正 AUTO_START=1
        _sync_auto_start_flag(root_dir, True, logger)
    else:
        base["state"] = "disabled"
        base["message"] = "已创建但未启用"
        # 明确 disabled 时修正 AUTO_START=0
        _sync_auto_start_flag(root_dir, False, logger)

    return base


def _query_task_xml(service_name, logger):
    """一次 schtasks /Query /TN <task> /XML 查询，同时完成存在性检测和 XML 解析。

    合并原 _query_task_exists + _parse_task_xml，避免对同一任务执行两次 schtasks /XML。
    兼容 SERVICE_NAME 与 \\SERVICE_NAME 两种路径格式。

    Returns:
        dict: {
            found: bool - 任务是否存在
            task_path: str - 成功匹配的任务路径
            reason: str - 未找到时的原因（"not_found"/"timeout"/"error"）
            error: str or None - 错误详情
            xml_info: dict or None - 解析后的任务信息（同 _parse_task_xml 返回格式）
        }
    """
    import xml.etree.ElementTree as ET
    from runtime.wnmp_log import log_info, log_warn

    # 尝试多种任务路径：不带反斜杠、带根路径反斜杠
    task_paths = [service_name, "\\" + service_name]
    not_found_kw = ["not found", "找不到", "找不到指定的文件"]

    for tp in task_paths:
        try:
            result = subprocess.run(
                ["schtasks", "/Query", "/TN", tp, "/XML"],
                capture_output=True, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=10
            )
            if result.returncode == 0:
                # 任务存在，直接解析这份 XML
                xml_info = _parse_xml_text(result.stdout, logger)
                return {
                    "found": True,
                    "task_path": tp,
                    "reason": "",
                    "error": None,
                    "xml_info": xml_info,
                }
            else:
                # 明确任务不存在
                err = result.stderr.strip().lower()
                if any(kw in err for kw in not_found_kw):
                    # 当前路径格式找不到，尝试下一个
                    continue
                else:
                    # 其他错误（权限等），也尝试下一个路径格式
                    log_warn(logger, "schtasks /Query /XML error for {}: {}".format(tp, result.stderr.strip()[:200]))
                    continue
        except subprocess.TimeoutExpired:
            log_warn(logger, "schtasks /Query /XML timed out for task: " + tp)
            return {
                "found": False,
                "task_path": "",
                "reason": "timeout",
                "error": "检测超时",
                "xml_info": None,
            }
        except Exception as e:
            log_warn(logger, "schtasks /Query /XML exception for {}: {}".format(tp, str(e)))
            continue

    # 所有路径格式都明确返回"任务不存在"
    return {
        "found": False,
        "task_path": "",
        "reason": "not_found",
        "error": None,
        "xml_info": None,
    }


def _parse_xml_text(xml_text, logger):
    """从 schtasks /Query /XML 的输出文本中解析任务关键信息（纯解析，不调用 schtasks）。

    返回 dict: {"command": str, "arguments": str, "working_directory": str,
                "task_enabled": bool, "run_level": str, "warning": None}
    解析失败返回 None。
    """
    import xml.etree.ElementTree as ET
    from runtime.wnmp_log import log_info, log_warn

    try:
        # schtasks /XML 输出可能包含多行，找到 XML 部分
        xml_start = xml_text.find("<?xml")
        if xml_start < 0:
            xml_start = xml_text.find("<Task")
        if xml_start < 0:
            log_warn(logger, "No XML content found in schtasks /Query /XML output")
            return None

        xml_text = xml_text[xml_start:]

        root = ET.fromstring(xml_text)
        # 处理命名空间
        ns = ""
        if root.tag.startswith("{"):
            ns = root.tag.split("}")[0] + "}"

        info = {"command": "", "arguments": "", "working_directory": "",
                "task_enabled": True, "run_level": "", "warning": None}

        # 解析 Settings/Enabled（判断任务是否被禁用）
        settings_elem = root.find(".//{}Settings".format(ns))
        if settings_elem is None:
            settings_elem = root.find(".//Settings")
        if settings_elem is not None:
            enabled_elem = settings_elem.find("{}Enabled".format(ns))
            if enabled_elem is None:
                enabled_elem = settings_elem.find("Enabled")
            if enabled_elem is not None and enabled_elem.text:
                info["task_enabled"] = enabled_elem.text.strip().lower() == "true"

        # 解析 Principal/RunLevel
        principal_elem = root.find(".//{}Principals/{}Principal".format(ns, ns))
        if principal_elem is None:
            principal_elem = root.find(".//Principals/Principal")
        if principal_elem is not None:
            rl_elem = principal_elem.find("{}RunLevel".format(ns))
            if rl_elem is None:
                rl_elem = principal_elem.find("RunLevel")
            if rl_elem is not None and rl_elem.text:
                info["run_level"] = rl_elem.text

        # 解析 Actions/Exec
        exec_elem = root.find(".//{}Actions/{}Exec".format(ns, ns))
        if exec_elem is None:
            exec_elem = root.find(".//Actions/Exec")

        if exec_elem is not None:
            cmd_elem = exec_elem.find("{}Command".format(ns))
            if cmd_elem is None:
                cmd_elem = exec_elem.find("Command")
            if cmd_elem is not None and cmd_elem.text:
                info["command"] = cmd_elem.text

            args_elem = exec_elem.find("{}Arguments".format(ns))
            if args_elem is None:
                args_elem = exec_elem.find("Arguments")
            if args_elem is not None and args_elem.text:
                info["arguments"] = args_elem.text

            wd_elem = exec_elem.find("{}WorkingDirectory".format(ns))
            if wd_elem is None:
                wd_elem = exec_elem.find("WorkingDirectory")
            if wd_elem is not None and wd_elem.text:
                info["working_directory"] = wd_elem.text

        log_info(logger, "Task XML parsed: command={} working_directory={} enabled={}".format(
            info["command"][:80], info["working_directory"], info["task_enabled"]))
        return info

    except ET.ParseError as e:
        log_warn(logger, "Task XML parse error: " + str(e))
        return None
    except Exception as e:
        log_warn(logger, "Task XML parse exception: " + str(e))
        return None


def _parse_schtasks_output(output):
    """解析 schtasks /V /FO LIST 输出，提取任务关键信息。"""
    info = {"command": "", "arguments": "", "working_directory": "", "warning": None}
    try:
        for line in output.strip().split("\n"):
            line = line.strip()
            # Task To Run 字段包含命令行
            if line.startswith("Task To Run:"):
                info["command"] = line.split(":", 1)[1].strip()
    except Exception:
        pass
    return info


def _update_auto_start_flag(root_dir, value):
    """更新 runtime.ini 中 AUTO_START 配置项。"""
    config_path = os.path.join(root_dir, "config", "runtime.ini")
    if not os.path.isfile(config_path):
        return

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        updated = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("AUTO_START="):
                lines[i] = "AUTO_START={}\n".format(value)
                updated = True
                break

        if not updated:
            lines.append("AUTO_START={}\n".format(value))

        with open(config_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
    except Exception:
        pass


def _sync_auto_start_flag(root_dir, should_enable, logger):
    """根据明确可信的状态同步 AUTO_START 配置。

    只有在状态明确且可信时才修改 runtime.ini：
        should_enable=True  => AUTO_START=1（仅 state=enabled 时调用）
        should_enable=False => AUTO_START=0（仅 state=not_found/disabled 时调用）
    state=error/invalid 时不调用此函数，避免检测失败把配置写错。
    """
    from runtime import wnmp_config
    from runtime.wnmp_log import log_warn

    config_path = os.path.join(root_dir, "config", "runtime.ini")
    if not os.path.isfile(config_path):
        return

    cfg = wnmp_config.load_config(root_dir)
    auto_start_val = wnmp_config.get(cfg, "AUTO_START", "0")
    expected_val = "1" if should_enable else "0"

    if auto_start_val != expected_val:
        log_warn(logger, "AUTO_START={} but actual state suggests {}, correcting to AUTO_START={}".format(
            auto_start_val, "enabled" if should_enable else "not enabled", expected_val))
        _update_auto_start_flag(root_dir, expected_val)


def _save_autostart_task_name(root_dir, task_name, logger):
    """记录实际安装的计划任务名到 state.json，用于卸载兜底和名称变更检测。"""
    from runtime.wnmp_log import log_info
    try:
        from runtime.wnmp_state import load_state, save_state
        state = load_state(root_dir)
        state["autostart_task_name"] = task_name
        save_state(root_dir, state)
        log_info(logger, "Saved autostart_task_name to state.json: " + task_name)
    except Exception as e:
        from runtime.wnmp_log import log_warn
        log_warn(logger, "Failed to save autostart_task_name: " + str(e))


def _load_autostart_task_name(root_dir):
    """从 state.json 读取上次成功安装的计划任务名。返回 str 或 None。"""
    try:
        from runtime.wnmp_state import load_state
        state = load_state(root_dir)
        return state.get("autostart_task_name")
    except Exception:
        return None


def _clear_autostart_task_name(root_dir, logger):
    """清除 state.json 中的 autostart_task_name 记录（卸载成功后调用）。"""
    try:
        from runtime.wnmp_state import load_state, save_state
        state = load_state(root_dir)
        if "autostart_task_name" in state:
            del state["autostart_task_name"]
            save_state(root_dir, state)
    except Exception:
        pass
