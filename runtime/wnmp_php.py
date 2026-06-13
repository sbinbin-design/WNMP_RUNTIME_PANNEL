# -*- coding: utf-8 -*-
"""
WNMP PHP Module - PHP-CGI 启停控制
使用 Python 标准库实现，不依赖第三方包

启动确认：优先 listener path 精确匹配，path=None 时使用组合确认
  (launched_pid 存活 + 端口已监听 + listener_pid==launched_pid 或进程名匹配 php-cgi.exe)
停止确认：优先 recorded_pid + 进程名匹配，path=None 时允许停止 recorded_pid
"""
import os
import time
from runtime.wnmp_process import (
    write_pid_file, read_pid_file, remove_pid_file,
    is_process_running, kill_process, start_process,
    wait_for_port_open, wait_for_port_close, is_port_listening,
    find_processes_by_path, cleanup_residual_processes,
    terminate_pids, wait_ports_closed, find_port_listener_path,
    get_listening_processes,
    get_process_path, is_system_process, is_current_admin,
    get_process_image_path, get_process_name, get_pid_detail
)
from runtime.wnmp_component_paths import get_php_ini_path


def start_php_cgi(root_dir, cfg, logger):
    """启动 PHP-CGI。基于 listener path 确认启动成功，path=None 时使用组合确认。

    启动前预检端口：如果启动前端口已被占用且无法确认属于当前项目，直接阻断。
    启动后确认逻辑：
      1. listener path 精确匹配 php-cgi.exe → confirmed_by_path
      2. path=None 但 launched_pid 存活 + 端口已监听 + listener_pid==launched_pid
         或进程名匹配 php-cgi.exe → confirmed_by_combination
    """
    from runtime.wnmp_log import log_info, log_error, log_warn
    from runtime.wnmp_config import get_effective_php_cgi_host_port, parse_php_cgi_config
    from runtime.wnmp_process import check_listener_ownership, wait_for_port_listener

    php_cgi_exe = os.path.join(root_dir, "bin", "php", "php-cgi.exe")
    # 路径收敛：通过统一路径模块获取 php.ini 路径
    php_ini = get_php_ini_path(root_dir)
    pid_dir = os.path.join(root_dir, "runtime", "pids")

    # 从 php-cgi.ini 解析 host/port
    php_cgi_host, php_cgi_port = get_effective_php_cgi_host_port(root_dir, cfg)
    cgi_cfg = parse_php_cgi_config(root_dir)
    config_parsed = cgi_cfg is not None

    # 配置解析失败处理
    if not config_parsed:
        log_warn(logger, "无法解析 php-cgi.ini 配置端口，已回退 runtime.ini 默认值 host={}:{}".format(
            php_cgi_host, php_cgi_port))

    log_info(logger, "PHP-CGI 配置解析: host={} port={} config_parsed={}".format(
        php_cgi_host, php_cgi_port, config_parsed))

    # 启动前预检：端口是否已被占用
    precheck_port_open = is_port_listening(php_cgi_host, php_cgi_port)
    if precheck_port_open:
        precheck_ownership = check_listener_ownership(php_cgi_port, php_cgi_exe,
                                                       host=php_cgi_host, root_dir=root_dir,
                                                       timeout=2, logger=logger)
        log_info(logger, "  Precheck: port {}:{} status={} pid={} path={}".format(
            php_cgi_host, php_cgi_port, precheck_ownership["status"],
            precheck_ownership.get("pid"), precheck_ownership.get("path")))
        if precheck_ownership["status"] == "running":
            # 本项目 php-cgi 已在运行，幂等返回
            confirmed_pid = precheck_ownership["pid"]
            write_pid_file(pid_dir, "php-cgi.pid", confirmed_pid)
            log_info(logger, "PHP-CGI already running: PID={}".format(confirmed_pid))
            return True, confirmed_pid
        elif precheck_ownership["status"] in ("external", "unknown"):
            # 端口被外部程序或未知进程占用，阻断启动
            if precheck_ownership["status"] == "external":
                log_error(logger, "Port {}:{} is preoccupied by external process: path={}".format(
                    php_cgi_host, php_cgi_port, precheck_ownership.get("path")))
                return False, "port_preoccupied: 端口 {}:{} 已被外部程序{}占用".format(
                    php_cgi_host, php_cgi_port,
                    " " + precheck_ownership.get("path") if precheck_ownership.get("path") else "")
            else:
                log_error(logger, "Port {}:{} is preoccupied by unknown process".format(
                    php_cgi_host, php_cgi_port))
                return False, "port_preoccupied: 端口 {}:{} 已被未知进程占用，为避免误操作已阻断启动".format(
                    php_cgi_host, php_cgi_port)

    # 启动前清理旧 PID 文件，避免 stale PID 干扰
    remove_pid_file(pid_dir, "php-cgi.pid")

    cmd = [
        php_cgi_exe,
        "-b", "{}:{}".format(php_cgi_host, php_cgi_port),
        "-c", php_ini
    ]

    log_file = os.path.join(root_dir, "logs", "php", "php-cgi.log")
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    log_info(logger, "Starting PHP-CGI on {}:{}...".format(php_cgi_host, php_cgi_port))
    log_info(logger, "  Command: {}".format(" ".join(cmd)))
    proc = start_process(cmd, cwd=root_dir, logger=logger, stdout_file=log_file, stderr_file=log_file)
    if proc is None:
        log_error(logger, "Failed to start PHP-CGI process")
        return False, "Failed to start PHP-CGI process"

    launched_pid = proc.pid

    # 等待端口被本项目 php-cgi.exe 监听
    log_info(logger, "Waiting for PHP-CGI port {}:{} to be confirmed...".format(
        php_cgi_host, php_cgi_port))
    start_time = time.time()
    timeout = 30  # 总等待超时

    confirmed_pid = None
    decision = None
    while time.time() - start_time < timeout:
        ownership = check_listener_ownership(php_cgi_port, php_cgi_exe,
                                              host=php_cgi_host, root_dir=root_dir,
                                              timeout=2, logger=logger)
        log_info(logger, "  Port {}:{} listener: status={} pid={} path={} is_ours={} path_reason={}".format(
            php_cgi_host, php_cgi_port, ownership["status"],
            ownership.get("pid"), ownership.get("path"), ownership.get("is_ours"),
            ownership.get("path_reason")))

        if ownership["status"] == "running":
            confirmed_pid = ownership["pid"]
            decision = "confirmed_by_path"
            break
        elif ownership["status"] == "external":
            log_error(logger, "Port {}:{} is occupied by external process: path={}".format(
                php_cgi_host, php_cgi_port, ownership.get("path")))
            return False, "端口 {}:{} 已被外部程序{}占用".format(
                php_cgi_host, php_cgi_port,
                " " + ownership.get("path") if ownership.get("path") else "，无法确认路径")
        elif ownership["status"] == "unknown":
            # 端口已开放但 path=None，尝试组合确认
            listener_pid = ownership.get("pid")
            if listener_pid is not None:
                # 组合确认：launched_pid 存活 + 端口已监听 + listener_pid==launched_pid 或进程名匹配
                launched_alive = is_process_running(launched_pid) is not False
                pid_match = (listener_pid == launched_pid)
                proc_name = get_process_name(listener_pid, timeout=2)
                proc_name_match = (proc_name and proc_name.lower() == "php-cgi.exe")

                if launched_alive and (pid_match or proc_name_match):
                    confirmed_pid = listener_pid
                    decision = "confirmed_by_combination"
                    log_info(logger, "  Combination confirm: launched_pid={} alive={}, listener_pid={} "
                             "pid_match={} proc_name={} name_match={}".format(
                                 launched_pid, launched_alive, listener_pid,
                                 pid_match, proc_name, proc_name_match))
                    break
            # 组合确认未通过，继续等待
            pass
        # stopped: 端口未开放，继续等待
        time.sleep(0.5)

    if confirmed_pid is not None:
        # 写入 PID 缓存
        write_pid_file(pid_dir, "php-cgi.pid", confirmed_pid)
        log_info(logger, "PHP-CGI started: PID={} decision={}".format(confirmed_pid, decision))
        if decision == "confirmed_by_combination":
            log_info(logger, "  当前系统无法读取监听进程路径，已使用本次启动 PID 与端口监听状态进行确认")
        # 启动成功后清除 config_dirty 标记
        try:
            from runtime.wnmp_state import mark_component_config_applied
            mark_component_config_applied(root_dir, "php")
        except Exception:
            pass
        return True, confirmed_pid

    # 超时：检查是否有端口开放但无法确认归属
    if is_port_listening(php_cgi_host, php_cgi_port):
        log_error(logger, "PHP-CGI port is open but cannot confirm ownership")
        return False, "path_unreadable: 端口已开放但无法确认属于当前 WNMP Runtime"

    log_error(logger, "PHP-CGI failed to start, port {}:{} not listening".format(php_cgi_host, php_cgi_port))
    return False, "PHP-CGI port not listening after start"


def stop_php_cgi(root_dir, cfg, logger):
    """停止 PHP-CGI。优先使用 recorded_pid + 进程名匹配，path=None 时也允许停止。

    停止安全边界：
      - 允许停止 recorded_pid（进程名匹配 php-cgi.exe）
      - 允许停止 listener path 精确匹配 php-cgi.exe 的进程
      - path=None 且不是 recorded_pid 的未知 listener，禁止 kill
      - 外部进程不允许 kill
    """
    from runtime.wnmp_log import log_info, log_error, log_warn
    from runtime.wnmp_config import get_effective_php_cgi_host_port

    # 权限上下文日志
    current_admin = is_current_admin()
    log_info(logger, "Permission context: current_process_is_admin={}".format(current_admin))

    pid_dir = os.path.join(root_dir, "runtime", "pids")
    php_cgi_exe = os.path.join(root_dir, "bin", "php", "php-cgi.exe")
    # 从 php-cgi.ini 解析 host/port
    php_cgi_host, php_cgi_port = get_effective_php_cgi_host_port(root_dir, cfg)

    stopped_pids = []
    recorded_pid = read_pid_file(pid_dir, "php-cgi.pid")

    # 步骤 0：查询配置端口所有 listener PID/path/local_address
    log_info(logger, "Querying {}:{} listeners...".format(php_cgi_host, php_cgi_port))
    listeners = get_listening_processes(php_cgi_port, host=php_cgi_host, root_dir=root_dir,
                                        logger=logger, expected_path=php_cgi_exe)
    # 记录所有 listener 信息
    for ln in listeners:
        ln_pid = ln.get("pid")
        ln_path = ln.get("path")
        ln_addr = ln.get("local_address", "?")
        ln_is_expected = ln.get("is_expected")
        ln_is_in_root = ln.get("is_in_root")
        ln_owner = "unknown"
        if ln_pid:
            ln_owner = "SYSTEM" if is_system_process(ln_pid) else "user"
        log_info(logger, "  Listener: PID={} local={} path={} is_expected={} is_in_root={} owner={}".format(
            ln_pid, ln_addr, ln_path, ln_is_expected, ln_is_in_root, ln_owner))

    # 遍历所有 listener，优先选择 is_expected=True 的 PID
    expected_listener = None
    in_root_listener = None  # 在 rootDir 下但不是目标 exe
    external_listener = None
    unknown_listener = None

    for ln in listeners:
        if ln.get("is_expected") is True:
            expected_listener = ln
            break  # 找到精确匹配，优先使用
        elif ln.get("is_in_root") is True and ln.get("is_expected") is False:
            in_root_listener = ln
        elif ln.get("is_expected") is False:
            external_listener = ln
        elif ln.get("is_expected") is None:
            unknown_listener = ln

    # 确定要停止的目标 listener
    target_listener = expected_listener or in_root_listener
    listener_pid = target_listener.get("pid") if target_listener else None
    listener_path = target_listener.get("path") if target_listener else None
    listener_is_expected = target_listener.get("is_expected") if target_listener else None

    # 如果端口被外部程序占用，不能误杀
    if external_listener and not expected_listener and not in_root_listener:
        log_warn(logger, "Port {}:{} is occupied by external process: path={}".format(
            php_cgi_host, php_cgi_port, external_listener.get("path")))
        return False, "external"

    # 如果只有 unknown listener（path=None），检查是否为 recorded_pid
    if unknown_listener and not expected_listener and not in_root_listener:
        unknown_pid = unknown_listener.get("pid")
        if unknown_pid and recorded_pid and unknown_pid == recorded_pid:
            # unknown listener 是 recorded_pid，允许停止
            proc_name = get_process_name(unknown_pid, timeout=2)
            if proc_name and proc_name.lower() == "php-cgi.exe":
                log_info(logger, "  Unknown listener PID={} matches recorded_pid and process name php-cgi.exe, allowing stop".format(
                    unknown_pid))
                target_listener = unknown_listener
                listener_pid = unknown_pid
                listener_is_expected = None  # path=None 但进程名匹配
            else:
                log_warn(logger, "Port {}:{} has unknown listener PID={} but process name '{}' does not match php-cgi.exe".format(
                    php_cgi_host, php_cgi_port, unknown_pid, proc_name))
                return False, "unknown_external_listener: 端口被未知进程占用，为避免误杀已跳过操作"
        else:
            # path=None 且不是 recorded_pid 的未知 listener，禁止 kill
            log_warn(logger, "Port {}:{} has unknown listener PID={} (recorded_pid={}), cannot confirm ownership".format(
                php_cgi_host, php_cgi_port, unknown_pid, recorded_pid))
            return False, "unknown_external_listener: 端口被未知进程占用，为避免误杀已跳过操作"

    # 记录目标进程权限信息
    listener_owner = "unknown"
    if listener_pid:
        listener_is_sys = is_system_process(listener_pid)
        listener_owner = "SYSTEM" if listener_is_sys else "user"
    log_info(logger, "Permission context: target_pid={} target_path={} target_owner={} current_admin={}".format(
        listener_pid, listener_path, listener_owner, current_admin))

    # SYSTEM 进程提前返回
    if listener_is_expected is True and listener_pid and listener_owner == "SYSTEM" and not current_admin:
        msg = "该组件由 SYSTEM/高权限启动，停止需要以管理员权限运行 WNMPPanel.exe"
        log_info(logger, "Permission denied: " + msg)
        return False, msg

    # 主路径：listener PID 优先停止（is_expected=True 表示本项目 php-cgi.exe）
    if listener_is_expected is True and listener_pid:
        log_info(logger, "  Port {}:{} listener is project php-cgi PID={}, terminating...".format(
            php_cgi_host, php_cgi_port, listener_pid))
        kill_process(listener_pid, timeout=10, logger=logger)
        stopped_pids.append(listener_pid)
        # 修正 pid 文件（如果 listener PID 与 pid 文件不一致）
        if recorded_pid and recorded_pid != listener_pid:
            log_info(logger, "  Listener PID {} differs from pid file PID {}, updating pid file".format(
                listener_pid, recorded_pid))
            write_pid_file(pid_dir, "php-cgi.pid", listener_pid)
    elif listener_pid and listener_is_expected is None and recorded_pid and listener_pid == recorded_pid:
        # path=None 但 PID 匹配 recorded_pid 且进程名匹配，允许停止
        log_info(logger, "  Port {}:{} listener PID={} matches recorded_pid (path=None, confirmed by combination), terminating...".format(
            php_cgi_host, php_cgi_port, listener_pid))
        kill_process(listener_pid, timeout=10, logger=logger)
        stopped_pids.append(listener_pid)

    # 步骤 1：按 PID 文件终止（辅助路径，处理 listener 未覆盖的子进程）
    if recorded_pid and is_process_running(recorded_pid) is not False:
        if recorded_pid not in stopped_pids:
            # 验证 recorded_pid 的进程名
            proc_name = get_process_name(recorded_pid, timeout=2)
            if proc_name and proc_name.lower() == "php-cgi.exe":
                log_info(logger, "Stopping PHP-CGI via recorded PID {} (process name confirmed)...".format(recorded_pid))
                kill_process(recorded_pid, timeout=10, logger=logger)
                stopped_pids.append(recorded_pid)
            else:
                log_warn(logger, "Recorded PID {} process name '{}' does not match php-cgi.exe, skipping".format(
                    recorded_pid, proc_name))

    # 步骤 2：等待端口释放
    if wait_for_port_close(php_cgi_host, php_cgi_port, timeout=8, logger=logger):
        log_info(logger, "PHP-CGI stopped successfully: port released")
        remove_pid_file(pid_dir, "php-cgi.pid")
        return True, stopped_pids

    # 步骤 3：端口仍开放，优先快速扫描本项目 php-cgi.exe 进程并终止
    log_warn(logger, "Recorded PID stop did not release port, finding project PHP-CGI processes...")
    # 优先使用快速扫描（WinAPI+tasklist），避免 PowerShell 慢兜底
    from runtime.wnmp_process import find_processes_by_executable_path
    tool_pids = find_processes_by_executable_path(php_cgi_exe, timeout=2, logger=logger, fast_mode=True)
    if not tool_pids:
        # 快速扫描无结果，使用完整路径扫描（含 PowerShell 兜底）
        tool_pids = find_processes_by_path(root_dir, "php-cgi.exe", logger)
    if tool_pids:
        log_info(logger, "  Found {} project PHP-CGI processes: {}".format(len(tool_pids), tool_pids))
        terminated, failed = terminate_pids(tool_pids, timeout=10, tree=True, logger=logger)
        stopped_pids.extend(tool_pids)
        log_info(logger, "  Terminated: {}, failed: {}".format(terminated, failed))

    # 步骤 4：终止后等待端口释放
    if wait_for_port_close(php_cgi_host, php_cgi_port, timeout=10, logger=logger):
        log_info(logger, "PHP-CGI stopped successfully: port released via path fallback")
        remove_pid_file(pid_dir, "php-cgi.pid")
        return True, stopped_pids

    # 步骤 5：端口仍开放，识别所有监听进程归属
    if is_port_listening(php_cgi_host, php_cgi_port):
        listeners = get_listening_processes(php_cgi_port, host=php_cgi_host, root_dir=root_dir,
                                            logger=logger, expected_path=php_cgi_exe)
        details = []
        system_hint = False
        for ln in listeners:
            ln_pid = ln.get("pid")
            ln_addr = ln.get("local_address", "?")
            ln_path = ln.get("path") or "unknown"
            if ln.get("is_expected") is True:
                detail = "local={} (project php-cgi PID={} path={}".format(ln_addr, ln_pid, ln_path)
                if ln_pid and is_system_process(ln_pid):
                    detail += ", SYSTEM process"
                    system_hint = True
                detail += ")"
                details.append(detail)
            elif ln.get("is_expected") is False:
                if ln.get("is_in_root") is True:
                    details.append("local={} (non-target PID={} path={})".format(ln_addr, ln_pid, ln_path))
                else:
                    details.append("local={} (external PID={} path={})".format(ln_addr, ln_pid, ln_path))
            else:
                details.append("local={} (PID={} path={}, cannot confirm ownership)".format(
                    ln_addr, ln_pid or "?", ln_path))
        msg = "port {}:{} still occupied: ".format(php_cgi_host, php_cgi_port) + "; ".join(details)
        if system_hint:
            msg += " | 该组件由 SYSTEM/高权限启动，停止需要以管理员权限运行 WNMPPanel.exe"
        log_error(logger, "Failed to stop PHP-CGI: " + msg)
        return False, msg

    log_info(logger, "PHP-CGI stopped (port not in use)")
    remove_pid_file(pid_dir, "php-cgi.pid")
    return True, stopped_pids


def get_php_cgi_status(root_dir, cfg, logger):
    """获取 PHP-CGI 运行状态。

    复用 panel/status.py 的 get_component_status 统一状态语义，
    CLI 和 Panel 不再得出不同结论。
    """
    try:
        from runtime.panel.status import get_component_status
        st = get_component_status("php", cfg)
        return {
            "running": st.get("running", False),
            "pid": st.get("listener_pid") or st.get("pid"),
            "port_listening": st.get("port_open", False),
            "state": st.get("state", "unknown"),
        }
    except Exception:
        # 回退到旧逻辑（兼容异常场景）
        from runtime.wnmp_config import get_effective_php_cgi_host_port
        pid_dir = os.path.join(root_dir, "runtime", "pids")
        pid = read_pid_file(pid_dir, "php-cgi.pid")
        running = is_process_running(pid) if pid else False
        if running is None:
            running = True
        php_cgi_host, php_cgi_port = get_effective_php_cgi_host_port(root_dir, cfg)
        port_listening = is_port_listening(php_cgi_host, php_cgi_port)
        return {"running": running, "pid": pid, "port_listening": port_listening}
