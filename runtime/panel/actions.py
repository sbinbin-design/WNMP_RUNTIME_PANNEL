# -*- coding: utf-8 -*-
"""
WNMP Panel Actions - Action whitelist and core function dispatch.

ALL actions (environment-level, component-level, autostart) are executed
via subprocess calling: bin/python/python.exe -u runtime/wnmpctl.py <cli_action>
This decouples stdout/stderr from Panel Server, avoiding I/O errors.

No exec/eval. No shell=True. No bat. No system Python. No direct import execution.
"""
import os
import sys
import subprocess
import time
import uuid

# Use centralized path utilities
from runtime.panel.paths import get_root_dir


# ---- timeout config per action (seconds) -----------------------------------
ACTION_TIMEOUT = {
    "start_env": 300,
    "init_env": 300,
    "stop_env": 120,
    "restart_env": 300,
    "start_nginx": 60,
    "stop_nginx": 60,
    "restart_nginx": 60,
    "reload_nginx": 60,
    "start_php": 60,
    "stop_php": 60,
    "restart_php": 60,
    "start_mysql": 120,
    "stop_mysql": 120,
    "restart_mysql": 120,
    "open_site": 10,
    "install_autostart": 60,
    "uninstall_autostart": 60,
    "reset_config": 180,  # 重置配置：含备份+重生成，允许较长超时
}

# ---- CLI action mapping (subprocess) ---------------------------------------
# 所有动作统一通过 bin/python/python.exe -u runtime/wnmpctl.py <cli_action> 子进程执行
# 使用绝对脚本路径，不依赖 -m 和 ._pth
CLI_ACTION_MAP = {
    "start_env": "start",
    "init_env": "init",
    "stop_env": "stop",
    "restart_env": "restart",
    "start_nginx": "start-nginx",
    "stop_nginx": "stop-nginx",
    "restart_nginx": "restart-nginx",
    "reload_nginx": "reload-nginx",
    "start_php": "start-php",
    "stop_php": "stop-php",
    "restart_php": "restart-php",
    "start_mysql": "start-mysql",
    "stop_mysql": "stop-mysql",
    "restart_mysql": "restart-mysql",
    "install_autostart": "install-autostart",
    "uninstall_autostart": "uninstall-autostart",
    "reset_config": "reset-config",  # 重置配置：映射到 wnmpctl.py reset-config --force
}

# 组件级动作列表（未初始化时需要门控拒绝）
_COMPONENT_ACTIONS = [
    "start_nginx", "stop_nginx", "restart_nginx", "reload_nginx",
    "start_php", "stop_php", "restart_php",
    "start_mysql", "stop_mysql", "restart_mysql",
]


def _check_initialized():
    """Check if environment is initialized. Return (initialized, root_dir)."""
    root_dir = get_root_dir()
    from runtime.wnmp_state import is_initialized
    return is_initialized(root_dir), root_dir


def _get_python_exe(root_dir):
    """Get path to project's bundled Python executable."""
    return os.path.join(root_dir, "bin", "python", "python.exe")


def _get_action_log_path(root_dir):
    """Get path to action output log file."""
    return os.path.join(root_dir, "logs", "panel", "action_output.log")


def _ensure_action_log_dir(root_dir):
    """Ensure action log directory exists."""
    log_dir = os.path.join(root_dir, "logs", "panel")
    os.makedirs(log_dir, exist_ok=True)


def run_python_cli_action(root_dir, cli_action, timeout_sec, panel_result_file=None):
    """Execute wnmpctl CLI action via subprocess.

    Args:
        root_dir: Project root directory (used as cwd).
        cli_action: CLI action name (e.g. start, stop-nginx, install-autostart).
        timeout_sec: Timeout in seconds.
        panel_result_file: Optional temp file path for cross-process password passing.

    Returns:
        (exit_code, timed_out): exit_code from subprocess, timed_out boolean.
    """
    python_exe = _get_python_exe(root_dir)
    if not os.path.isfile(python_exe):
        return -2, False  # -2 = Python not found

    # 使用绝对脚本路径，不依赖 -m 和 ._pth
    wnmpctl_script = os.path.join(root_dir, "runtime", "wnmpctl.py")
    cmd = [python_exe, "-u", wnmpctl_script, cli_action]

    # 仅 Panel 调用 start 时传递 --panel-result-file
    if panel_result_file:
        cmd.extend(["--panel-result-file", panel_result_file])

    _ensure_action_log_dir(root_dir)
    log_path = _get_action_log_path(root_dir)

    # Write action header to log
    started_at = time.strftime("%Y-%m-%d %H:%M:%S")
    sep = "=" * 60
    header = (
        "\n{sep}\n"
        "Action: {cli_action}\n"
        "Command: {cmd}\n"
        "CWD: {cwd}\n"
        "Started: {started_at}\n"
        "{sep}\n"
    ).format(
        sep=sep,
        cli_action=cli_action,
        cmd=" ".join(cmd),
        cwd=root_dir,
        started_at=started_at,
    )

    try:
        with open(log_path, "a", encoding="utf-8", errors="replace") as log_f:
            log_f.write(header)
            log_f.flush()

            proc = subprocess.Popen(
                cmd,
                stdout=log_f,
                stderr=subprocess.STDOUT,  # stderr 合并到 stdout
                cwd=root_dir,
                # 不使用 shell=True，不查找 PATH
            )

            try:
                exit_code = proc.wait(timeout=timeout_sec)
                timed_out = False
            except subprocess.TimeoutExpired:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
                exit_code = -3  # -3 = 超时
                timed_out = True

    except Exception as e:
        # 日志写入失败等异常
        try:
            with open(log_path, "a", encoding="utf-8", errors="replace") as log_f:
                log_f.write("ERROR: Failed to execute action: {}\n".format(str(e)))
        except Exception:
            pass
        return -4, False  # -4 = 执行异常

    # 写入动作结束信息
    finished_at = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(log_path, "a", encoding="utf-8", errors="replace") as log_f:
            log_f.write(
                "Exit code: {}\nTimed out: {}\nFinished: {}\n".format(
                    exit_code, timed_out, finished_at
                )
            )
            if timed_out:
                log_f.write("WARNING: Action timed out after {} seconds\n".format(timeout_sec))
    except Exception:
        pass

    return exit_code, timed_out


# ---- action handlers --------------------------------------------------------

def _do_cli_action(action):
    """通用 CLI 动作执行：通过子进程调用 wnmpctl CLI。

    返回 dict: {"exit_code": int, "panel_result_file": str or None, "message": str}
    """
    initialized, root_dir = _check_initialized()

    # 组件级动作门控：未初始化时拒绝
    if action in _COMPONENT_ACTIONS and not initialized:
        return {"exit_code": -1, "panel_result_file": None, "message": "环境未初始化"}

    # install_autostart 门控：未初始化时拒绝（避免开机自启动在无交互环境下初始化，MySQL 密码无法显示）
    if action == "install_autostart" and not initialized:
        return {"exit_code": -1, "panel_result_file": None,
                "message": "环境尚未初始化，请先初始化 Nginx/PHP/MySQL 后再启用开机自启动"}

    # restart_env 也需要初始化
    if action == "restart_env" and not initialized:
        return {"exit_code": -1, "panel_result_file": None, "message": "环境未初始化"}

    # start_env 需要已初始化环境，未初始化时提示先初始化
    if action == "start_env" and not initialized:
        return {"exit_code": -1, "panel_result_file": None, "message": "环境未初始化，请先初始化环境"}

    # stop_env 未初始化时无需停止
    if action == "stop_env" and not initialized:
        return {"exit_code": 0, "panel_result_file": None, "message": "环境未初始化，无需停止"}

    cli_action = CLI_ACTION_MAP.get(action)
    if not cli_action:
        return {"exit_code": 1, "panel_result_file": None, "message": "未知动作"}

    timeout = ACTION_TIMEOUT.get(action, 120)

    # start_env/init_env 时生成临时结果文件路径，用于跨进程传递 MySQL 初始密码
    panel_result_file = None
    if action in ("start_env", "init_env"):
        try:
            tmp_dir = os.path.join(root_dir, "runtime", "tmp")
            os.makedirs(tmp_dir, exist_ok=True)
            panel_result_file = os.path.join(tmp_dir, "panel-init-result-{}.json".format(uuid.uuid4().hex[:12]))
        except Exception:
            panel_result_file = None

    exit_code, timed_out = run_python_cli_action(root_dir, cli_action, timeout, panel_result_file)
    if timed_out:
        # 超时也保留 panel_result_file，MySQL 密码可能已写入
        return {"exit_code": -3, "panel_result_file": panel_result_file, "message": "动作超时"}
    if exit_code == -2:
        # Python 未找到，无法执行，不保留 panel_result_file
        return {"exit_code": -2, "panel_result_file": None, "message": "Python 未找到"}

    # 正常退出（含非 0 exit_code），保留 panel_result_file
    return {"exit_code": exit_code, "panel_result_file": panel_result_file, "message": ""}


def _do_open_site(action=None):
    """open_site action - opens browser to default site。

    返回 dict: {"exit_code": int, "panel_result_file": None, "message": str}

    端口检测策略：使用轻量 socket connect 检测 127.0.0.1:HTTP_PORT 和 HTTPS_PORT，
    不依赖进程路径归属查询（避免 SYSTEM 启动时 path=None 导致误判）。
    URL 选择规则：HTTP 优先（自签证书易让用户误以为打不开），HTTPS 兜底。
    """
    initialized, _ = _check_initialized()
    if not initialized:
        return {"exit_code": -1, "panel_result_file": None, "message": "环境未初始化"}
    root_dir = get_root_dir()
    from runtime.wnmp_config import load_config
    cfg = load_config(root_dir)
    from runtime import wnmp_config as wcfg

    # 检查 config_dirty：配置已修改但未应用时，不打开旧配置站点
    from runtime.wnmp_state import is_component_config_dirty
    config_dirty = is_component_config_dirty(root_dir, "nginx")
    if config_dirty:
        return {"exit_code": 1, "panel_result_file": None,
                "message": "Nginx 配置已修改但尚未应用，请先重载或重启后再打开站点"}

    # 从 Nginx 配置解析 HTTP/HTTPS 端口（不写死 80/443，缺省值由 config helper 提供）
    eff = wcfg.get_effective_nginx_listens(root_dir, cfg)
    http_ports = eff["http"]
    https_ports = eff["https"]

    # 轻量 socket connect 检测端口是否开放（超时 500ms，不跑 PowerShell/进程扫描）
    from runtime.wnmp_process import is_port_listening
    open_http_port = None
    for p in http_ports:
        if is_port_listening("127.0.0.1", p, timeout=0.5):
            open_http_port = p
            break

    open_https_port = None
    for p in https_ports:
        if is_port_listening("127.0.0.1", p, timeout=0.5):
            open_https_port = p
            break

    # URL 选择：HTTP 优先（自签证书易让用户误以为打不开），HTTPS 兜底
    url = None
    if open_http_port is not None:
        if open_http_port == 80:
            url = "http://127.0.0.1/"
        else:
            url = "http://127.0.0.1:{}/".format(open_http_port)
    elif open_https_port is not None:
        if open_https_port == 443:
            url = "https://127.0.0.1/"
        else:
            url = "https://127.0.0.1:{}/".format(open_https_port)

    if url is None:
        # HTTP/HTTPS 都未开放，记录实际检测结果到日志
        try:
            _ensure_action_log_dir(root_dir)
            with open(_get_action_log_path(root_dir), "a", encoding="utf-8", errors="replace") as _lf:
                _lf.write("open_site ports http={} open=false https={} open=false\n".format(
                    http_ports, https_ports))
        except Exception:
            pass
        return {"exit_code": 1, "panel_result_file": None,
                "message": "未检测到 Nginx 可用端口，请先启动 Nginx"}

    # 端口已开放，打开浏览器
    try:
        os.startfile(url)
        return {"exit_code": 0, "panel_result_file": None, "message": ""}
    except Exception as e:
        # 端口已开放但浏览器打开失败，提示手动访问
        try:
            _ensure_action_log_dir(root_dir)
            with open(_get_action_log_path(root_dir), "a", encoding="utf-8", errors="replace") as _lf:
                _lf.write("open_site browser failed url={} error={}\n".format(url, str(e)))
        except Exception:
            pass
        return {"exit_code": 1, "panel_result_file": None,
                "message": "端口已开放，但无法打开浏览器，请手动访问 {}".format(url)}


def _do_reset_config(action):
    """reset_config action - 重置组件配置文件，通过 Python CLI 执行 wnmpctl.py reset-config --force。

    前端已有二次确认。后端不调用 bat，不自动重启服务，不污染 PHP/MySQL 状态。
    不删除数据库数据、不删除网站目录、不重置面板配置 runtime.ini。
    wnmpctl.py reset-config --force 内部会先备份再覆盖，生成失败自动回滚。
    成功后标记 Nginx/PHP/MySQL config_dirty，提示用户需重载/重启。
    """
    initialized, root_dir = _check_initialized()
    # 重置配置需要已初始化的环境（需要 config 目录和模板）
    if not initialized:
        return {"exit_code": -1, "panel_result_file": None,
                "message": "环境未初始化，无法重置配置"}

    python_exe = _get_python_exe(root_dir)
    if not os.path.isfile(python_exe):
        return {"exit_code": -2, "panel_result_file": None, "message": "Python 未找到"}

    wnmpctl_script = os.path.join(root_dir, "runtime", "wnmpctl.py")
    # 传递 --force 跳过 CLI 交互确认（前端已做二次确认）
    cmd = [python_exe, "-u", wnmpctl_script, "reset-config", "--force"]

    _ensure_action_log_dir(root_dir)
    log_path = _get_action_log_path(root_dir)
    started_at = time.strftime("%Y-%m-%d %H:%M:%S")
    sep = "=" * 60
    # 日志 Action 名称统一为 reset-config（不含 --force），便于错误提取匹配
    header = (
        "\n{sep}\n"
        "Action: reset-config\n"
        "Command: {cmd}\n"
        "CWD: {cwd}\n"
        "Started: {started_at}\n"
        "{sep}\n"
    ).format(sep=sep, cmd=" ".join(cmd), cwd=root_dir, started_at=started_at)

    timeout = ACTION_TIMEOUT.get(action, 180)

    try:
        with open(log_path, "a", encoding="utf-8", errors="replace") as log_f:
            log_f.write(header)
            log_f.flush()

            proc = subprocess.Popen(
                cmd,
                stdout=log_f,
                stderr=subprocess.STDOUT,
                cwd=root_dir,
            )

            try:
                exit_code = proc.wait(timeout=timeout)
                timed_out = False
            except subprocess.TimeoutExpired:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
                exit_code = -3
                timed_out = True

    except Exception as e:
        try:
            with open(log_path, "a", encoding="utf-8", errors="replace") as log_f:
                log_f.write("ERROR: Failed to execute reset_config: {}\n".format(str(e)))
        except Exception:
            pass
        return {"exit_code": -4, "panel_result_file": None,
                "message": "重置配置执行异常: " + str(e)}

    if timed_out:
        return {"exit_code": -3, "panel_result_file": None, "message": "重置配置超时"}
    if exit_code == 0:
        # 成功时从日志提取备份目录信息
        success_msg = "组件配置已重置，可能需要重载或重启对应组件后生效"
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as lf:
                lines = lf.readlines()
            for line in lines:
                if "备份目录：" in line or "backup_dir" in line.lower():
                    # 提取包含备份目录的行
                    success_msg = line.strip()
                    break
                if "组件配置已重置" in line:
                    success_msg = line.strip()
                    break
        except Exception:
            pass
        return {"exit_code": 0, "panel_result_file": None,
                "message": success_msg}

    # 失败时从日志提取具体错误信息，不返回笼统提示
    error_msg = _extract_last_action_error(log_path, "reset-config")
    if error_msg:
        return {"exit_code": exit_code, "panel_result_file": None,
                "message": "重置配置失败: " + error_msg}
    return {"exit_code": exit_code, "panel_result_file": None,
            "message": "重置配置失败（退出码 {}），请查看动作输出日志".format(exit_code)}


def _extract_last_action_error(log_path, action_name):
    """从动作日志中提取最近一次指定 action 的关键错误行。

    返回拼接的错误摘要字符串，最多 6 行 1200 字符；无错误时返回空字符串。
    """
    if not os.path.isfile(log_path):
        return ""
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as lf:
            all_lines = lf.readlines()
        # 定位最近一次匹配的 Action 行
        action_start = -1
        for i in range(len(all_lines) - 1, -1, -1):
            stripped_line = all_lines[i].strip()
            if stripped_line.startswith("Action:"):
                logged_action = stripped_line[len("Action:"):].strip()
                # 匹配：完全相同或以 action_name 开头（兼容 reset-config --force 等）
                if logged_action == action_name or logged_action.startswith(action_name + " "):
                    action_start = i
                break
        if action_start < 0:
            return ""
        action_lines = all_lines[action_start:]
        _ERROR_KEYWORDS = [
            "ERROR:", "[ERROR]", "failed", "失败", "缺失", "越界",
            "cannot", "invalid", "被占用",
        ]
        error_lines = []
        for line in action_lines:
            stripped = line.strip()
            if not stripped:
                continue
            low = stripped.lower()
            if stripped.startswith("=") or stripped.startswith("Action:") or stripped.startswith("Command:") or stripped.startswith("CWD:") or stripped.startswith("Started:") or stripped.startswith("Exit code:") or stripped.startswith("Timed out:") or stripped.startswith("Finished:") or stripped.startswith("WARNING:"):
                continue
            for kw in _ERROR_KEYWORDS:
                if kw.lower() in low:
                    error_lines.append(stripped)
                    break
        if not error_lines:
            return ""
        # 去掉 "ERROR: " 前缀
        result_lines = []
        for l in error_lines[:6]:
            if l.startswith("ERROR: "):
                result_lines.append(l[7:])
            else:
                result_lines.append(l)
        cli_error = "\n".join(result_lines)
        if len(cli_error) > 1200:
            cli_error = cli_error[:1200] + "..."
        return cli_error
    except Exception:
        return ""


# ---- whitelist --------------------------------------------------------------

ACTIONS = {
    "start_env":    _do_cli_action,
    "init_env":     _do_cli_action,   # 初始化动作别名
    "stop_env":     _do_cli_action,
    "restart_env":  _do_cli_action,
    "start_nginx":  _do_cli_action,
    "stop_nginx":   _do_cli_action,
    "restart_nginx": _do_cli_action,
    "reload_nginx":  _do_cli_action,
    "start_php":    _do_cli_action,
    "stop_php":     _do_cli_action,
    "restart_php":  _do_cli_action,
    "start_mysql":  _do_cli_action,
    "stop_mysql":   _do_cli_action,
    "restart_mysql": _do_cli_action,
    "open_site":    _do_open_site,
    "install_autostart": _do_cli_action,
    "uninstall_autostart": _do_cli_action,
    "reset_config": _do_reset_config,  # 重置配置：专用 handler，传递 --force
}


def is_valid_action(action):
    """Return True if action is in whitelist."""
    return action in ACTIONS


def execute_action(action):
    """Execute white-listed action, return result dict.

    返回: {"exit_code": int, "panel_result_file": str or None, "message": str}
    panel_result_file 仅在 start_env/init_env 时可能有值，用于跨进程传递 MySQL 初始密码。
    """
    handler = ACTIONS.get(action)
    if handler is None:
        return {"exit_code": 1, "panel_result_file": None, "message": "未知动作"}
    return handler(action)
