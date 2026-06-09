# -*- coding: utf-8 -*-
"""
WNMP State Module - manages initialization state in runtime/state.json

记录初始化状态，用于判断是否需要执行首次初始化流程。
"""
import os
import json
from datetime import datetime


def get_state_path(root_dir):
    """Get runtime/state.json path."""
    return os.path.join(root_dir, "runtime", "state.json")


def load_state(root_dir):
    """Load state from runtime/state.json."""
    state_path = get_state_path(root_dir)
    if os.path.isfile(state_path):
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_state(root_dir, state):
    """Save state to runtime/state.json."""
    state_path = get_state_path(root_dir)
    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def is_initialized(root_dir):
    """Check if the environment has been initialized."""
    state = load_state(root_dir)
    return state.get("INITIALIZED", False)


def get_init_phase(root_dir):
    """获取当前初始化阶段。返回 None 或阶段字符串。

    阶段值：preparing_config, mysql_secure_init, starting_php_cgi,
    starting_nginx, verifying_services, completed, failed。
    None 表示未在初始化流程中（已完成或从未开始）。
    """
    state = load_state(root_dir)
    return state.get("INIT_PHASE")


def is_initializing(root_dir):
    """判断是否正在初始化中（INIT_PHASE 存在且非 completed/failed）。"""
    phase = get_init_phase(root_dir)
    return phase is not None and phase not in ("completed", "failed")


def set_init_phase(root_dir, phase):
    """设置初始化阶段，同时写入 state.json。

    phase 值：preparing_config, mysql_secure_init, starting_php_cgi,
    starting_nginx, verifying_services, completed, failed。
    """
    state = load_state(root_dir)
    state["INIT_PHASE"] = phase
    if phase == "completed":
        state["INITIALIZED"] = True
        state["INITIALIZED_AT"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_state(root_dir, state)


def mark_initialized(root_dir):
    """Mark the environment as fully initialized."""
    state = load_state(root_dir)
    state["INITIALIZED"] = True
    state["INITIALIZED_AT"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # 同步设置 init_phase 为 completed
    state["INIT_PHASE"] = "completed"
    save_state(root_dir, state)


# ---- START_PHASE: 普通启动阶段（已初始化环境启动服务时使用，不污染 INIT_PHASE） ----

def get_start_phase(root_dir):
    """获取当前普通启动阶段。返回 None 或阶段字符串。

    阶段值：starting_mysql, starting_php_cgi, starting_nginx,
    verifying_services, completed, failed。
    None 表示未在启动流程中。
    """
    state = load_state(root_dir)
    return state.get("START_PHASE")


def is_starting(root_dir):
    """判断是否正在普通启动中（START_PHASE 存在且非 completed/failed）。"""
    phase = get_start_phase(root_dir)
    return phase is not None and phase not in ("completed", "failed")


def set_start_phase(root_dir, phase):
    """设置普通启动阶段，同时写入 state.json。

    phase 值：starting_mysql, starting_php_cgi, starting_nginx,
    verifying_services, completed, failed。
    """
    state = load_state(root_dir)
    state["START_PHASE"] = phase
    save_state(root_dir, state)


def clear_start_phase(root_dir):
    """清除普通启动阶段（启动完成或失败后清理）。"""
    state = load_state(root_dir)
    state.pop("START_PHASE", None)
    save_state(root_dir, state)


def mark_config_generated(root_dir):
    """Mark config as generated."""
    state = load_state(root_dir)
    state["CONFIG_GENERATED"] = True
    state["CONFIG_GENERATED_AT"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_state(root_dir, state)


def mark_default_site_initialized(root_dir):
    """Mark default site as initialized."""
    state = load_state(root_dir)
    state["DEFAULT_SITE_INITIALIZED"] = True
    save_state(root_dir, state)


def mark_cert_initialized(root_dir):
    """Mark certificate as initialized."""
    state = load_state(root_dir)
    state["CERT_INITIALIZED"] = True
    save_state(root_dir, state)


def mark_mysql_initialized(root_dir):
    """Mark MySQL as initialized."""
    state = load_state(root_dir)
    state["MYSQL_INITIALIZED"] = True
    save_state(root_dir, state)


def mark_env_path_configured(root_dir, configured=True, items=None, reason=None):
    """Mark environment PATH as configured or skipped.

    configured: True = successfully added to PATH, False = skipped/failed
    items: list of paths that were (or should be) in PATH
    reason: if not configured, reason for skipping
    """
    state = load_state(root_dir)
    state["ENV_PATH_CONFIGURED"] = configured
    state["ENV_PATH_CONFIGURED_AT"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if items is not None:
        state["ENV_PATH_ITEMS"] = items
    if reason is not None:
        state["ENV_PATH_SKIP_REASON"] = reason
    save_state(root_dir, state)


def is_env_path_configured(root_dir):
    """Check if ENV PATH has been configured."""
    state = load_state(root_dir)
    return state.get("ENV_PATH_CONFIGURED", False)


def get_env_path_items(root_dir):
    """Get ENV PATH items from state."""
    state = load_state(root_dir)
    return state.get("ENV_PATH_ITEMS", [])


def is_default_site_initialized(root_dir):
    """Check if default site has been initialized."""
    state = load_state(root_dir)
    return state.get("DEFAULT_SITE_INITIALIZED", False)


def is_cert_initialized(root_dir):
    """Check if certificate has been initialized."""
    state = load_state(root_dir)
    return state.get("CERT_INITIALIZED", False)


def is_mysql_initialized(root_dir):
    """Check if MySQL has been initialized."""
    state = load_state(root_dir)
    return state.get("MYSQL_INITIALIZED", False)


def try_backfill_state(root_dir, logger=None):
    """迁移兼容：如果 state.json 不存在但关键文件都已存在，补写初始化状态。

    检测条件：config/nginx.conf、config/nginx/site.conf、config/php/php.ini、
    config/mysql/my.ini 都已存在，且 data/mysql 已初始化。
    不再要求 root-password.txt。
    """
    if is_initialized(root_dir):
        return True

    checks = [
        os.path.join(root_dir, "config", "nginx.conf"),
        os.path.join(root_dir, "config", "nginx", "site.conf"),
        os.path.join(root_dir, "config", "php", "php.ini"),
        os.path.join(root_dir, "config", "mysql", "my.ini"),
    ]
    all_exist = all(os.path.isfile(p) for p in checks)

    mysql_data = os.path.join(root_dir, "data", "mysql")
    data_initialized = os.path.isdir(mysql_data) and (
        os.path.isdir(os.path.join(mysql_data, "mysql")) or
        os.path.isfile(os.path.join(mysql_data, "ibdata1"))
    )

    if all_exist and data_initialized:
        state = {}
        state["INITIALIZED"] = True
        state["INITIALIZED_AT"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        state["CONFIG_GENERATED"] = True
        state["CONFIG_GENERATED_AT"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        state["DEFAULT_SITE_INITIALIZED"] = os.path.isfile(os.path.join(root_dir, "www", "index.php"))
        state["CERT_INITIALIZED"] = os.path.isfile(os.path.join(root_dir, "config", "certs", "server.crt"))
        state["MYSQL_INITIALIZED"] = True
        state["BACKFILLED"] = True
        save_state(root_dir, state)
        if logger:
            from runtime.wnmp_log import log_info
            log_info(logger, "Detected existing environment, backfilled initialization state")
        return True

    return False


def backfill_missing_fields(root_dir, logger=None):
    """兼容旧版 state.json：补写缺失的 MYSQL_INITIALIZED 和 CONFIG_GENERATED 字段。

    对于已有 INITIALIZED=true 但缺少 MYSQL_INITIALIZED 的环境：
    - 若 data/mysql 已初始化，补写 MYSQL_INITIALIZED=true
    - 不再要求 root-password.txt
    对于缺少 CONFIG_GENERATED 的环境：
    - 若 CONFIG_GENERATED_AT 存在，补写 CONFIG_GENERATED=true
    """
    state = load_state(root_dir)
    if not state.get("INITIALIZED", False):
        return

    updated = False

    # 补写 CONFIG_GENERATED
    if "CONFIG_GENERATED" not in state and state.get("CONFIG_GENERATED_AT"):
        state["CONFIG_GENERATED"] = True
        updated = True

    # 补写 MYSQL_INITIALIZED（不再要求 root-password.txt）
    if "MYSQL_INITIALIZED" not in state:
        mysql_data = os.path.join(root_dir, "data", "mysql")
        data_initialized = os.path.isdir(mysql_data) and (
            os.path.isdir(os.path.join(mysql_data, "mysql")) or
            os.path.isfile(os.path.join(mysql_data, "ibdata1"))
        )

        if data_initialized:
            state["MYSQL_INITIALIZED"] = True
            updated = True
            if logger:
                from runtime.wnmp_log import log_info
                log_info(logger, "Backfilled MYSQL_INITIALIZED=true from existing data dir")

    if updated:
        save_state(root_dir, state)


# ---- 组件配置应用状态（desired config vs applied config）--------------------
# 每个组件独立保存，不使用全局 dirty 标志

# 组件配置文件路径定义（相对于 root_dir）
_COMPONENT_CONFIG_FILES = {
    "nginx": [
        "config/nginx.conf",
        "config/nginx/site.conf",
    ],
    "php": [
        "config/php/php-cgi.ini",
    ],
    "mysql": [
        "config/mysql/my.ini",
    ],
}


def _get_component_config_state_path(root_dir, component):
    """获取组件配置状态的存储路径。"""
    return os.path.join(root_dir, "runtime", "config_state", "{}.json".format(component))


def _load_component_config_state(root_dir, component):
    """加载组件配置状态。"""
    path = _get_component_config_state_path(root_dir, component)
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_component_config_state(root_dir, component, state):
    """保存组件配置状态。"""
    path = _get_component_config_state_path(root_dir, component)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def compute_component_config_hash(root_dir, component):
    """计算组件当前磁盘配置文件的哈希值。

    Nginx 额外覆盖 config/nginx/vhosts/*.conf、config/nginx/custom/http/*.conf、
    config/nginx/custom/server/*.conf。只纳入 .conf 文件，排除 .disabled 和非 .conf 文件。
    返回 hex digest 字符串，任一文件不存在或读取失败时返回 None。
    """
    import hashlib
    rel_paths = list(_COMPONENT_CONFIG_FILES.get(component, []))
    # Nginx 额外包含 vhosts、custom/http、custom/server 目录
    if component == "nginx":
        _extra_dirs = [
            ("config/nginx/vhosts", "config/nginx/vhosts/"),
            ("config/nginx/custom/http", "config/nginx/custom/http/"),
            ("config/nginx/custom/server", "config/nginx/custom/server/"),
        ]
        for dir_rel, prefix in _extra_dirs:
            abs_dir = os.path.join(root_dir, dir_rel)
            if os.path.isdir(abs_dir):
                for fname in sorted(os.listdir(abs_dir)):
                    # 只纳入 .conf 文件，排除 .disabled 和非 .conf 文件
                    if fname.endswith(".conf") and not fname.endswith(".disabled"):
                        rel_paths.append(prefix + fname)

    h = hashlib.sha256()
    for rel in rel_paths:
        full = os.path.join(root_dir, rel)
        if not os.path.isfile(full):
            return None
        try:
            with open(full, "rb") as f:
                h.update(f.read())
        except Exception:
            return None
    return h.hexdigest()


def mark_component_config_applied(root_dir, component, config_hash=None, ports=None):
    """标记组件配置已应用：记录 applied_hash、applied_ports、applied_at。

    Args:
        root_dir: 项目根目录
        component: 组件名（nginx/php/mysql）
        config_hash: 已应用的配置哈希，None 时自动计算
        ports: 已应用的端口列表（Nginx 用），如 [80, 443]
    """
    if config_hash is None:
        config_hash = compute_component_config_hash(root_dir, component)
    state = _load_component_config_state(root_dir, component)
    state["applied_hash"] = config_hash
    state["config_dirty"] = False
    state["applied_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if ports is not None:
        state["applied_ports"] = ports
    _save_component_config_state(root_dir, component, state)


def mark_component_config_dirty(root_dir, component):
    """标记组件配置已修改但未应用（dirty）。不影响其它组件。"""
    state = _load_component_config_state(root_dir, component)
    state["config_dirty"] = True
    state["dirty_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _save_component_config_state(root_dir, component, state)


def get_component_config_apply_state(root_dir, component):
    """获取组件配置应用状态。

    Returns:
        dict: {
            "applied_hash": str or None,
            "applied_ports": list or None,  # Nginx 用
            "applied_at": str or None,
            "config_dirty": bool,
            "dirty_at": str or None,
        }
    """
    return _load_component_config_state(root_dir, component)


def is_component_config_dirty(root_dir, component):
    """快速判断组件配置是否 dirty。

    比较 applied_hash 与当前磁盘配置 hash，不一致或显式标记 dirty 时返回 True。
    """
    state = _load_component_config_state(root_dir, component)
    if state.get("config_dirty", False):
        return True
    applied_hash = state.get("applied_hash")
    if not applied_hash:
        # 从未有 applied 记录，不算 dirty（首次启动前）
        return False
    current_hash = compute_component_config_hash(root_dir, component)
    return current_hash != applied_hash
