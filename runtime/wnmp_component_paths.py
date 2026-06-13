# -*- coding: utf-8 -*-
"""
WNMP Component Paths Module - 组件配置路径统一抽象

P2 阶段：所有 get_*_path 函数正式返回新活跃路径（组件目录下），不再返回旧集中配置路径。
get_legacy_config_paths() 保留旧路径，仅用于升级迁移，不作为运行路径。
get_future_component_config_paths() 已与当前活跃路径一致，避免"future"和"active"含义混乱。

当前活跃路径定义：
  Nginx：bin/nginx/conf/nginx.conf、bin/nginx/conf/site.conf、bin/nginx/conf/vhosts、
         bin/nginx/conf/custom/http、bin/nginx/conf/custom/server
  PHP：bin/php/php.ini、bin/php/php-cgi.ini、bin/php/php.user.ini
  MySQL：bin/mysql/my.ini、bin/mysql/my.user.ini
  Panel 自身配置仍为 config/runtime.ini，不纳入组件配置迁移。

旧集中配置路径（legacy，仅用于迁移）：
  Nginx：config/nginx.conf、config/nginx/site.conf、config/nginx/vhosts、
         config/nginx/custom/http、config/nginx/custom/server
  PHP：config/php/php.ini、config/php/php-cgi.ini、config/php/php.user.ini
  MySQL：config/mysql/my.ini、config/mysql/my.user.ini
"""
import os
import shutil
import logging
from datetime import datetime


# ---- Panel 管理标记机制 ----

# Panel 管理标记常量，用于标识由 Panel 管理的配置文件
PANEL_MANAGED_MARKER = "Managed by WNMP Runtime Panel"


def is_panel_managed_config(path):
    """判断配置文件是否包含 Panel 管理标记。

    Args:
        path: 配置文件绝对路径

    Returns:
        bool: 文件存在且包含 PANEL_MANAGED_MARKER 时返回 True，否则返回 False
    """
    if not os.path.isfile(path):
        return False
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            # 只读取前 4KB，标记应在文件头部
            head = f.read(4096)
        return PANEL_MANAGED_MARKER in head
    except Exception:
        return False


def ensure_panel_managed_header(content, component, source):
    """为配置内容追加 Panel 管理标记。

    如果内容已包含标记，不重复追加。
    只在迁移复制或模板生成时写入目标新配置，不为添加标记而重写用户已有旧配置。

    按组件注释符设计：
    - Nginx 配置使用 # 作为注释符
    - MySQL my.ini 使用 # 作为注释符
    - PHP php.ini/php-cgi.ini 使用 ; 作为注释符

    Args:
        content: 配置文件内容字符串
        component: 组件名（nginx/php/php-cgi/mysql）
        source: 配置来源描述（如 "template" 或 "migration"）

    Returns:
        str: 追加了 Panel 管理标记的配置内容
    """
    # 按组件选择注释符：PHP/php-cgi 使用 ;，Nginx/MySQL 使用 #
    _COMMENT_CHAR = {
        "php": ";",
        "php-cgi": ";",
        "nginx": "#",
        "mysql": "#",
    }
    comment_char = _COMMENT_CHAR.get(component, "#")
    header = "{} {} - {} ({})".format(comment_char, PANEL_MANAGED_MARKER, component, source)
    if PANEL_MANAGED_MARKER in content:
        return content
    return header + "\n" + content


def normalize_nginx_config_paths_for_component_layout(content, root_dir):
    """将旧 Nginx include 路径替换为新组件目录路径。

    P2-A 阻断修复：迁移旧配置到新路径后，旧副本中的 include 链路仍指向
    config/nginx/...，必须归一化到 bin/nginx/conf/...。

    只修改迁移到新路径后的副本内容，不允许修改旧 config/ 下的历史文件。
    对非 Nginx 配置文件不应调用此函数。

    替换规则（兼容正斜杠和反斜杠，兼容相对路径和绝对路径）：
    - config/nginx/mime.types → bin/nginx/conf/mime.types
    - config/nginx/site.conf → bin/nginx/conf/site.conf
    - config/nginx/fastcgi_params → bin/nginx/conf/fastcgi_params
    - config/nginx/custom/http → bin/nginx/conf/custom/http
    - config/nginx/custom/server → bin/nginx/conf/custom/server
    - config/nginx/vhosts → bin/nginx/conf/vhosts
    - {{CONFIG_DIR}}/nginx/... → 对应新路径

    Args:
        content: 配置文件内容字符串
        root_dir: 项目根目录（用于构建绝对路径替换）

    Returns:
        str: 路径归一化后的配置内容
    """
    from runtime.wnmp_path import to_forward_slash

    # 构建替换映射：旧路径片段 → 新路径片段
    # 使用正斜杠形式，替换时同时处理正斜杠和反斜杠
    nginx_conf_dir_new = to_forward_slash(os.path.join(root_dir, "bin", "nginx", "conf"))

    # 相对路径替换映射（正斜杠形式）
    _REL_PATH_REPLACEMENTS = [
        # 旧相对路径 → 新相对路径
        ("config/nginx/mime.types", "bin/nginx/conf/mime.types"),
        ("config/nginx/site.conf", "bin/nginx/conf/site.conf"),
        ("config/nginx/fastcgi_params", "bin/nginx/conf/fastcgi_params"),
        ("config/nginx/custom/http", "bin/nginx/conf/custom/http"),
        ("config/nginx/custom/server", "bin/nginx/conf/custom/server"),
        ("config/nginx/vhosts", "bin/nginx/conf/vhosts"),
    ]

    result = content

    # 替换 {{CONFIG_DIR}}/nginx 模板残留
    config_dir_posix = to_forward_slash(os.path.join(root_dir, "config"))
    result = result.replace("{{CONFIG_DIR}}/nginx", nginx_conf_dir_new)
    result = result.replace("{{CONFIG_DIR}}\\nginx", nginx_conf_dir_new)

    # 替换相对路径（正斜杠和反斜杠两种形式）
    for old_rel, new_rel in _REL_PATH_REPLACEMENTS:
        # 正斜杠形式
        result = result.replace(old_rel, new_rel)
        # 反斜杠形式
        old_backslash = old_rel.replace("/", "\\")
        new_backslash = new_rel.replace("/", "\\")
        result = result.replace(old_backslash, new_backslash)

    # 替换绝对路径形式（C:/xxx/config/nginx/... → C:/xxx/bin/nginx/conf/...）
    config_dir_abs_posix = to_forward_slash(os.path.join(root_dir, "config"))
    bin_conf_dir_abs_posix = nginx_conf_dir_new
    for old_rel, new_rel in _REL_PATH_REPLACEMENTS:
        old_abs_posix = config_dir_abs_posix + "/" + old_rel.replace("config/", "")
        new_abs_posix = bin_conf_dir_abs_posix + "/" + new_rel.replace("bin/nginx/conf/", "")
        result = result.replace(old_abs_posix, new_abs_posix)
        # 反斜杠绝对路径
        old_abs_backslash = old_abs_posix.replace("/", "\\")
        new_abs_backslash = new_abs_posix.replace("/", "\\")
        result = result.replace(old_abs_backslash, new_abs_backslash)

    return result


# ---- 当前活跃路径函数（P2：正式返回新组件目录路径）----

def get_runtime_ini_path(root_dir):
    """返回 Panel 自身配置路径 config/runtime.ini。

    Panel 自身配置不纳入组件配置迁移，始终使用此路径。
    """
    return os.path.join(root_dir, "config", "runtime.ini")


def get_nginx_conf_path(root_dir):
    """返回 Nginx 主配置文件当前活跃路径。

    P2 阶段正式切换为 bin/nginx/conf/nginx.conf。
    """
    return os.path.join(root_dir, "bin", "nginx", "conf", "nginx.conf")


def get_nginx_site_conf_path(root_dir):
    """返回 Nginx 默认站点配置文件当前活跃路径。

    P2 阶段正式切换为 bin/nginx/conf/site.conf。
    """
    return os.path.join(root_dir, "bin", "nginx", "conf", "site.conf")


def get_nginx_vhosts_dir(root_dir):
    """返回 Nginx vhosts 目录当前活跃路径。

    P2 阶段正式切换为 bin/nginx/conf/vhosts。
    """
    return os.path.join(root_dir, "bin", "nginx", "conf", "vhosts")


def get_nginx_custom_http_dir(root_dir):
    """返回 Nginx HTTP 级扩展目录当前活跃路径。

    P2 阶段正式切换为 bin/nginx/conf/custom/http。
    """
    return os.path.join(root_dir, "bin", "nginx", "conf", "custom", "http")


def get_nginx_custom_server_dir(root_dir):
    """返回 Nginx server 级扩展目录当前活跃路径。

    P2 阶段正式切换为 bin/nginx/conf/custom/server。
    """
    return os.path.join(root_dir, "bin", "nginx", "conf", "custom", "server")


def get_nginx_mime_types_path(root_dir):
    """返回 Nginx mime.types 文件当前活跃路径。

    P2 阶段正式切换为 bin/nginx/conf/mime.types。
    """
    return os.path.join(root_dir, "bin", "nginx", "conf", "mime.types")


def get_nginx_fastcgi_params_path(root_dir):
    """返回 Nginx fastcgi_params 文件当前活跃路径。

    P2 阶段正式切换为 bin/nginx/conf/fastcgi_params。
    """
    return os.path.join(root_dir, "bin", "nginx", "conf", "fastcgi_params")


def get_php_ini_path(root_dir):
    """返回 PHP 主配置文件当前活跃路径。

    P2 阶段正式切换为 bin/php/php.ini。
    """
    return os.path.join(root_dir, "bin", "php", "php.ini")


def get_php_cgi_ini_path(root_dir):
    """返回 PHP-CGI 进程配置文件当前活跃路径。

    P2 阶段正式切换为 bin/php/php-cgi.ini。
    """
    return os.path.join(root_dir, "bin", "php", "php-cgi.ini")


def get_mysql_ini_path(root_dir):
    """返回 MySQL 配置文件当前活跃路径。

    P2 阶段正式切换为 bin/mysql/my.ini。
    """
    return os.path.join(root_dir, "bin", "mysql", "my.ini")


def get_php_user_ini_path(root_dir):
    """返回 PHP 用户自定义配置文件当前活跃路径。

    P2 阶段正式切换为 bin/php/php.user.ini。
    """
    return os.path.join(root_dir, "bin", "php", "php.user.ini")


def get_mysql_user_ini_path(root_dir):
    """返回 MySQL 用户自定义配置文件当前活跃路径。

    P2 阶段正式切换为 bin/mysql/my.user.ini。
    """
    return os.path.join(root_dir, "bin", "mysql", "my.user.ini")


# ---- 备份与模板路径 ----

def get_original_backup_dir(root_dir, component):
    """返回原始配置备份目录路径。

    Args:
        root_dir: 项目根目录
        component: 组件名（nginx/php/mysql）

    Returns:
        str: config/backups/original/<component>/ 绝对路径
    """
    return os.path.join(root_dir, "config", "backups", "original", component)


def get_template_dir(root_dir, component):
    """返回组件模板目录路径。

    P2 阶段模板迁移到 runtime/templates/<component>/。
    模板文件用于首次生成或显式恢复默认配置，不再作为 config 下的运行依赖。

    Args:
        root_dir: 项目根目录
        component: 组件名（nginx/php/mysql）

    Returns:
        str: runtime/templates/<component>/ 绝对路径
    """
    _COMPONENT_TEMPLATE_DIR = {
        "nginx": os.path.join(root_dir, "runtime", "templates", "nginx"),
        "php": os.path.join(root_dir, "runtime", "templates", "php"),
        "mysql": os.path.join(root_dir, "runtime", "templates", "mysql"),
    }
    return _COMPONENT_TEMPLATE_DIR.get(component, "")


# ---- 旧路径定义（仅用于迁移，不作为运行路径）----

def get_legacy_config_paths(component):
    """返回组件旧集中配置路径的相对路径列表。

    仅用于升级迁移和日志记录，不作为运行路径。
    P2 阶段旧路径不再作为活跃路径使用。

    Args:
        component: 组件名（nginx/php/mysql）

    Returns:
        list[str]: 旧配置文件/目录的相对路径列表
    """
    _LEGACY_PATHS = {
        "nginx": [
            "config/nginx.conf",
            "config/nginx/site.conf",
            "config/nginx/vhosts",
            "config/nginx/custom/http",
            "config/nginx/custom/server",
        ],
        "php": [
            "config/php/php.ini",
            "config/php/php-cgi.ini",
            "config/php/php.user.ini",
        ],
        "mysql": [
            "config/mysql/my.ini",
            "config/mysql/my.user.ini",
        ],
    }
    return _LEGACY_PATHS.get(component, [])


def get_future_component_config_paths(component):
    """返回组件当前活跃配置路径的相对路径列表。

    P2 阶段：与当前活跃路径一致，不再区分"future"和"active"。
    保留函数签名以兼容旧调用方。

    Args:
        component: 组件名（nginx/php/mysql）

    Returns:
        list[str]: 当前活跃配置文件/目录的相对路径列表
    """
    _ACTIVE_PATHS = {
        "nginx": [
            "bin/nginx/conf/nginx.conf",
            "bin/nginx/conf/site.conf",
            "bin/nginx/conf/vhosts",
            "bin/nginx/conf/custom/http",
            "bin/nginx/conf/custom/server",
        ],
        "php": [
            "bin/php/php.ini",
            "bin/php/php-cgi.ini",
            "bin/php/php.user.ini",
        ],
        "mysql": [
            "bin/mysql/my.ini",
            "bin/mysql/my.user.ini",
        ],
    }
    return _ACTIVE_PATHS.get(component, [])


# ---- 原始配置备份框架 ----

def backup_original_config_if_needed(root_dir, component, path):
    """备份原始配置文件（如果需要）。

    备份规则：
    - 如果文件不存在，不处理
    - 如果文件存在且已包含 Panel 管理标记，不备份
    - 如果文件存在且没有 Panel 管理标记，复制一份到 config/backups/original/<component>/
    - 备份不得覆盖已有备份文件

    Args:
        root_dir: 项目根目录
        component: 组件名（nginx/php/mysql）
        path: 要备份的配置文件绝对路径

    Returns:
        dict: {"backed_up": bool, "reason": str, "backup_path": str or None}
    """
    # 文件不存在，不处理
    if not os.path.isfile(path):
        return {"backed_up": False, "reason": "file_not_found", "backup_path": None}

    # 已包含 Panel 管理标记，不备份
    if is_panel_managed_config(path):
        return {"backed_up": False, "reason": "already_panel_managed", "backup_path": None}

    # 备份目标目录
    backup_dir = get_original_backup_dir(root_dir, component)
    os.makedirs(backup_dir, exist_ok=True)

    # 备份文件命名：原文件名 + 时间戳 + .bak
    filename = os.path.basename(path)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_filename = "{}.{}.bak".format(filename, timestamp)
    backup_path = os.path.join(backup_dir, backup_filename)

    # 同一秒重复备份时追加序号，避免覆盖已有备份
    seq = 1
    while os.path.isfile(backup_path):
        backup_filename = "{}.{}.{}.bak".format(filename, timestamp, seq)
        backup_path = os.path.join(backup_dir, backup_filename)
        seq += 1

    try:
        shutil.copy2(path, backup_path)
        return {"backed_up": True, "reason": "success", "backup_path": backup_path}
    except Exception as e:
        return {"backed_up": False, "reason": "copy_failed: " + str(e), "backup_path": None}


# ---- 迁移预检查函数 ----

def inspect_component_config_layout(root_dir):
    """检查当前组件配置布局，返回迁移预检查信息。

    该函数仅做检查，不移动、不复制、不覆盖。

    Args:
        root_dir: 项目根目录

    Returns:
        dict: {
            "components": {
                "nginx": {
                    "legacy_paths": [{"rel": str, "abs": str, "exists": bool, "is_panel_managed": bool, "needs_backup": bool}],
                    "active_paths": [{"rel": str, "abs": str, "exists": bool, "conflict": bool}],
                },
                "php": {...},
                "mysql": {...},
            }
        }
    """
    components = ["nginx", "php", "mysql"]
    result = {}

    for component in components:
        legacy_rels = get_legacy_config_paths(component)
        active_rels = get_future_component_config_paths(component)

        legacy_paths = []
        for rel in legacy_rels:
            abs_path = os.path.join(root_dir, rel)
            exists = os.path.isfile(abs_path) or os.path.isdir(abs_path)
            is_managed = is_panel_managed_config(abs_path) if os.path.isfile(abs_path) else False
            needs_backup = exists and os.path.isfile(abs_path) and not is_managed
            legacy_paths.append({
                "rel": rel,
                "abs": os.path.normpath(abs_path),
                "exists": exists,
                "is_panel_managed": is_managed,
                "needs_backup": needs_backup,
            })

        active_paths = []
        for rel in active_rels:
            abs_path = os.path.join(root_dir, rel)
            exists = os.path.isfile(abs_path) or os.path.isdir(abs_path)
            # 冲突：活跃路径已存在且与旧路径不同
            conflict = exists and rel not in legacy_rels
            active_paths.append({
                "rel": rel,
                "abs": os.path.normpath(abs_path),
                "exists": exists,
                "conflict": conflict,
            })

        result[component] = {
            "legacy_paths": legacy_paths,
            "active_paths": active_paths,
        }

    return {"components": result}


# ---- 旧集中配置迁移 ----

def _migrate_single_file(legacy_abs, new_abs, component, root_dir, logger=None):
    """迁移单个配置文件：从旧路径复制到新路径。

    迁移规则（非破坏性）：
    1. 旧配置不存在 → 不处理
    2. 旧配置存在且新目标不存在 → 复制旧配置到新目标，补 Panel 管理标记
    3. 旧配置存在且新目标存在但没有 Panel 管理标记 → 先备份新目标原始文件，再复制旧配置到新目标，补标记
    4. 旧配置存在且新目标存在并包含 Panel 管理标记 → 不覆盖，只记录日志

    P2 收口：复制到新目标后，对活跃配置文件（nginx.conf、site.conf、php.ini、
    php-cgi.ini、my.ini）补 Panel 管理标记。mime.types、fastcgi_params 等基础
    include 文件不强制添加标记。

    Args:
        legacy_abs: 旧配置文件绝对路径
        new_abs: 新目标文件绝对路径
        component: 组件名（nginx/php/mysql）
        root_dir: 项目根目录
        logger: 日志记录器

    Returns:
        dict: {"migrated": bool, "reason": str, "backup_path": str or None}
    """
    def _log(msg):
        if logger:
            try:
                from runtime.wnmp_log import log_info, log_warn
                log_info(logger, "[migration] " + msg)
            except Exception:
                pass

    # P2 收口：需要补 Panel 管理标记的活跃配置文件名
    _ACTIVE_CONFIG_FILES = {
        "nginx.conf", "site.conf",
        "php.ini", "php-cgi.ini", "php.user.ini",
        "my.ini", "my.user.ini",
    }

    def _add_panel_marker_if_active(filepath, comp):
        """如果目标是活跃配置文件，补 Panel 管理标记。"""
        basename = os.path.basename(filepath)
        if basename not in _ACTIVE_CONFIG_FILES:
            return
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            if PANEL_MANAGED_MARKER in content:
                return
            new_content = ensure_panel_managed_header(content, comp, "migration")
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(new_content)
            _log("补 Panel 管理标记: {} (component: {})".format(filepath, comp))
        except Exception as e:
            _log("补 Panel 管理标记失败: {}: {}".format(filepath, e))

    def _normalize_nginx_paths_if_needed(filepath, comp):
        """P2-A 阻断修复：对 Nginx 配置文件迁移后的新副本执行 include 路径归一化。"""
        if comp != "nginx":
            return
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            normalized = normalize_nginx_config_paths_for_component_layout(content, root_dir)
            if normalized != content:
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(normalized)
                _log("Nginx include 路径归一化: {}".format(filepath))
        except Exception as e:
            _log("Nginx include 路径归一化失败: {}: {}".format(filepath, e))

    # 旧配置不存在，不处理
    if not os.path.isfile(legacy_abs):
        return {"migrated": False, "reason": "legacy_not_found", "backup_path": None}

    # 新目标不存在，直接复制
    if not os.path.isfile(new_abs):
        os.makedirs(os.path.dirname(new_abs), exist_ok=True)
        try:
            shutil.copy2(legacy_abs, new_abs)
            _log("复制旧配置到新路径: {} -> {}".format(legacy_abs, new_abs))
            # P2-A 阻断修复：先归一化 Nginx include 路径，再补 Panel 管理标记
            _normalize_nginx_paths_if_needed(new_abs, component)
            _add_panel_marker_if_active(new_abs, component)
            return {"migrated": True, "reason": "copied_from_legacy", "backup_path": None}
        except Exception as e:
            _log("复制失败: {} -> {}: {}".format(legacy_abs, new_abs, e))
            return {"migrated": False, "reason": "copy_failed: " + str(e), "backup_path": None}

    # 新目标已存在
    if is_panel_managed_config(new_abs):
        # 新目标已被 Panel 接管，不覆盖
        _log("新目标已被 Panel 管理，跳过覆盖: {}".format(new_abs))
        return {"migrated": False, "reason": "new_target_already_panel_managed", "backup_path": None}

    # 新目标存在但没有 Panel 管理标记，必须先成功备份才能覆盖
    backup_result = backup_original_config_if_needed(root_dir, component, new_abs)
    if not backup_result["backed_up"]:
        # P2-A 最小安全补丁：备份失败时必须中止迁移，不允许覆盖原始文件
        _log("备份失败，接管已中止，保留原始文件: {} (reason: {})".format(
            new_abs, backup_result["reason"]))
        return {"migrated": False, "reason": "backup_failed: " + backup_result["reason"],
                "backup_path": None}

    # 备份成功，允许覆盖
    _log("备份新目标原始文件: {} -> {}".format(new_abs, backup_result["backup_path"]))
    try:
        shutil.copy2(legacy_abs, new_abs)
        _log("备份后复制旧配置到新路径: {} -> {} (backup: {})".format(
            legacy_abs, new_abs, backup_result.get("backup_path")))
        # P2-A 阻断修复：先归一化 Nginx include 路径，再补 Panel 管理标记
        _normalize_nginx_paths_if_needed(new_abs, component)
        _add_panel_marker_if_active(new_abs, component)
        return {"migrated": True, "reason": "backed_up_and_copied", "backup_path": backup_result.get("backup_path")}
    except Exception as e:
        _log("备份后复制失败: {} -> {}: {}".format(legacy_abs, new_abs, e))
        return {"migrated": False, "reason": "copy_failed: " + str(e), "backup_path": backup_result.get("backup_path")}


def _migrate_base_file(legacy_abs, new_abs, root_dir, logger=None):
    """迁移 Nginx 基础 include 文件：只补缺失，不覆盖已有。

    P2-A 数据安全收口：mime.types、fastcgi_params 等 Nginx 基础 include 文件，
    不属于必须由 Panel 接管的主配置文件，新路径已存在时不应被覆盖。

    规则：
    - 新路径不存在且旧路径存在 → 复制
    - 新路径已存在 → 保留新路径，跳过复制
    - 不添加 Panel 管理标记

    Args:
        legacy_abs: 旧配置文件绝对路径
        new_abs: 新目标文件绝对路径
        root_dir: 项目根目录
        logger: 日志记录器

    Returns:
        dict: {"migrated": bool, "reason": str}
    """
    def _log(msg):
        if logger:
            try:
                from runtime.wnmp_log import log_info
                log_info(logger, "[migration] " + msg)
            except Exception:
                pass

    # 旧路径不存在，不处理
    if not os.path.isfile(legacy_abs):
        return {"migrated": False, "reason": "legacy_not_found"}

    # 新路径已存在，保留新路径，不覆盖
    if os.path.isfile(new_abs):
        _log("基础文件已存在，跳过复制（保留已有）: {} (旧: {})".format(new_abs, legacy_abs))
        return {"migrated": False, "reason": "new_already_exists"}

    # 新路径不存在，从旧路径复制
    os.makedirs(os.path.dirname(new_abs), exist_ok=True)
    try:
        shutil.copy2(legacy_abs, new_abs)
        _log("复制基础文件: {} -> {}".format(legacy_abs, new_abs))
        return {"migrated": True, "reason": "copied_from_legacy"}
    except Exception as e:
        _log("复制基础文件失败: {} -> {}: {}".format(legacy_abs, new_abs, e))
        return {"migrated": False, "reason": "copy_failed: " + str(e)}


def _migrate_directory(legacy_dir, new_dir, component, root_dir, logger=None):
    """迁移目录中的文件：从旧目录复制缺失文件到新目录。

    P2-A 数据安全收口：vhosts/custom 目录迁移只补缺失，不覆盖已有文件。
    用户在 bin/nginx/conf/vhosts 或 bin/nginx/conf/custom 下修改过的文件，
    不会因为旧 config 目录仍存在而被反复覆盖。

    迁移规则（非破坏性）：
    - 只复制新目录中不存在的文件
    - 同名冲突时：默认保留新文件，不覆盖，不备份后覆盖，只记录冲突日志
    - 不删除旧目录中任何文件

    Args:
        legacy_dir: 旧目录绝对路径
        new_dir: 新目录绝对路径
        component: 组件名
        root_dir: 项目根目录
        logger: 日志记录器

    Returns:
        dict: {"migrated_files": int, "skipped_existing": int, "conflict_skipped": int, "details": list}
    """
    def _log(msg):
        if logger:
            try:
                from runtime.wnmp_log import log_info, log_warn
                log_info(logger, "[migration] " + msg)
            except Exception:
                pass

    result = {"migrated_files": 0, "skipped_existing": 0, "conflict_skipped": 0, "copy_failed": 0, "details": []}

    if not os.path.isdir(legacy_dir):
        return result

    os.makedirs(new_dir, exist_ok=True)

    try:
        for fname in os.listdir(legacy_dir):
            legacy_file = os.path.join(legacy_dir, fname)
            if not os.path.isfile(legacy_file):
                continue

            new_file = os.path.join(new_dir, fname)

            if not os.path.isfile(new_file):
                # 新目录中不存在，直接复制
                try:
                    shutil.copy2(legacy_file, new_file)
                    _log("复制旧目录文件到新目录: {} -> {}".format(legacy_file, new_file))
                    # P2-A 阻断修复：Nginx 目录迁移后对新副本执行 include 路径归一化
                    if component == "nginx":
                        try:
                            with open(new_file, "r", encoding="utf-8", errors="replace") as f:
                                content = f.read()
                            normalized = normalize_nginx_config_paths_for_component_layout(content, root_dir)
                            if normalized != content:
                                with open(new_file, "w", encoding="utf-8") as f:
                                    f.write(normalized)
                                _log("Nginx include 路径归一化: {}".format(new_file))
                        except Exception as ne:
                            _log("Nginx include 路径归一化失败: {}: {}".format(new_file, ne))
                    result["migrated_files"] += 1
                    result["details"].append({
                        "file": fname, "action": "copied",
                        "from": legacy_file, "to": new_file,
                    })
                except Exception as e:
                    _log("复制失败: {} -> {}: {}".format(legacy_file, new_file, e))
                    result["copy_failed"] += 1
                    result["details"].append({
                        "file": fname, "action": "copy_failed",
                        "from": legacy_file, "to": new_file, "error": str(e),
                    })
            else:
                # P2-A 数据安全收口：同名冲突时默认保留新文件，不覆盖
                # 用户在 bin/nginx/conf/vhosts 或 bin/nginx/conf/custom 下修改过的文件，
                # 不会因为旧 config 目录仍存在而被反复覆盖
                _log("同名冲突，保留新文件（不覆盖已有）: {}".format(new_file))
                result["conflict_skipped"] += 1
                result["details"].append({
                    "file": fname, "action": "skipped_existing",
                    "from": legacy_file, "to": new_file,
                })
    except Exception as e:
        _log("遍历旧目录失败: {}: {}".format(legacy_dir, e))

    return result


def migrate_component_configs_if_needed(root_dir, logger=None):
    """从旧集中配置迁移到新组件目录。

    迁移必须非破坏性执行：
    - 不删除旧 config/nginx、config/php、config/mysql 下任何文件
    - 只在旧配置存在且新目标不存在时复制
    - 新目标已存在且未被 Panel 管理时先备份再覆盖
    - 新目标已被 Panel 管理时不覆盖
    - 迁移日志清楚说明：旧路径来源、新路径目标、是否备份原始文件、是否跳过覆盖

    Args:
        root_dir: 项目根目录
        logger: 日志记录器

    Returns:
        dict: {"migrated": bool, "components": {component: {details}}}
    """
    def _log(msg):
        if logger:
            try:
                from runtime.wnmp_log import log_info, log_warn
                log_info(logger, "[migration] " + msg)
            except Exception:
                pass

    overall_migrated = False
    components_result = {}

    # ---- Nginx 迁移 ----
    nginx_migrations = []
    # 主配置文件迁移（使用 _migrate_single_file，备份后接管）
    _NGINX_MAIN_FILE_MIGRATIONS = [
        (os.path.join(root_dir, "config", "nginx.conf"), get_nginx_conf_path(root_dir)),
        (os.path.join(root_dir, "config", "nginx", "site.conf"), get_nginx_site_conf_path(root_dir)),
    ]
    for legacy_abs, new_abs in _NGINX_MAIN_FILE_MIGRATIONS:
        result = _migrate_single_file(legacy_abs, new_abs, "nginx", root_dir, logger)
        nginx_migrations.append({
            "from": legacy_abs, "to": new_abs, **result,
        })
        if result["migrated"]:
            overall_migrated = True

    # P2-A 数据安全收口：mime.types 和 fastcgi_params 使用 _migrate_base_file
    # 基础 include 文件只补缺失，不覆盖已有
    _NGINX_BASE_FILE_MIGRATIONS = [
        (os.path.join(root_dir, "config", "nginx", "mime.types"), get_nginx_mime_types_path(root_dir)),
        (os.path.join(root_dir, "config", "nginx", "fastcgi_params"), get_nginx_fastcgi_params_path(root_dir)),
    ]
    for legacy_abs, new_abs in _NGINX_BASE_FILE_MIGRATIONS:
        result = _migrate_base_file(legacy_abs, new_abs, root_dir, logger)
        nginx_migrations.append({
            "from": legacy_abs, "to": new_abs, **result,
        })

    # 目录迁移
    _NGINX_DIR_MIGRATIONS = [
        (os.path.join(root_dir, "config", "nginx", "vhosts"), get_nginx_vhosts_dir(root_dir)),
        (os.path.join(root_dir, "config", "nginx", "custom", "http"), get_nginx_custom_http_dir(root_dir)),
        (os.path.join(root_dir, "config", "nginx", "custom", "server"), get_nginx_custom_server_dir(root_dir)),
    ]
    for legacy_dir, new_dir in _NGINX_DIR_MIGRATIONS:
        result = _migrate_directory(legacy_dir, new_dir, "nginx", root_dir, logger)
        nginx_migrations.append({
            "from": legacy_dir, "to": new_dir, "type": "directory", **result,
        })
        if result["migrated_files"] > 0:
            overall_migrated = True

    components_result["nginx"] = {"migrations": nginx_migrations}

    # ---- PHP 迁移 ----
    php_migrations = []
    _PHP_FILE_MIGRATIONS = [
        (os.path.join(root_dir, "config", "php", "php.ini"), get_php_ini_path(root_dir)),
        (os.path.join(root_dir, "config", "php", "php-cgi.ini"), get_php_cgi_ini_path(root_dir)),
        (os.path.join(root_dir, "config", "php", "php.user.ini"), get_php_user_ini_path(root_dir)),
    ]
    for legacy_abs, new_abs in _PHP_FILE_MIGRATIONS:
        result = _migrate_single_file(legacy_abs, new_abs, "php", root_dir, logger)
        php_migrations.append({
            "from": legacy_abs, "to": new_abs, **result,
        })
        if result["migrated"]:
            overall_migrated = True

    components_result["php"] = {"migrations": php_migrations}

    # ---- MySQL 迁移 ----
    mysql_migrations = []
    _MYSQL_FILE_MIGRATIONS = [
        (os.path.join(root_dir, "config", "mysql", "my.ini"), get_mysql_ini_path(root_dir)),
        (os.path.join(root_dir, "config", "mysql", "my.user.ini"), get_mysql_user_ini_path(root_dir)),
    ]
    for legacy_abs, new_abs in _MYSQL_FILE_MIGRATIONS:
        result = _migrate_single_file(legacy_abs, new_abs, "mysql", root_dir, logger)
        mysql_migrations.append({
            "from": legacy_abs, "to": new_abs, **result,
        })
        if result["migrated"]:
            overall_migrated = True

    components_result["mysql"] = {"migrations": mysql_migrations}

    _log("迁移完成: overall_migrated={}".format(overall_migrated))
    return {"migrated": overall_migrated, "components": components_result}


def migrate_templates_to_runtime(root_dir, logger=None):
    """将模板文件从旧 config 目录迁移到 runtime/templates/ 对应组件目录。

    迁移规则：
    - 如果 runtime/templates/<component>/ 下模板已存在，不覆盖
    - 只复制缺失的模板文件
    - 不删除旧 config 目录下的模板文件

    Args:
        root_dir: 项目根目录
        logger: 日志记录器

    Returns:
        dict: {"migrated": bool, "details": list}
    """
    def _log(msg):
        if logger:
            try:
                from runtime.wnmp_log import log_info
                log_info(logger, "[template-migration] " + msg)
            except Exception:
                pass

    migrated = False
    details = []

    _TEMPLATE_MIGRATIONS = [
        # (旧路径相对, 新路径相对)
        ("config/nginx/nginx.conf.template", "runtime/templates/nginx/nginx.conf.template"),
        ("config/nginx/site.conf.template", "runtime/templates/nginx/site.conf.template"),
        ("config/php/php.ini.template", "runtime/templates/php/php.ini.template"),
        ("config/mysql/my.ini.template", "runtime/templates/mysql/my.ini.template"),
    ]

    for legacy_rel, new_rel in _TEMPLATE_MIGRATIONS:
        legacy_abs = os.path.join(root_dir, legacy_rel)
        new_abs = os.path.join(root_dir, new_rel)

        if not os.path.isfile(legacy_abs):
            details.append({"from": legacy_rel, "to": new_rel, "action": "skipped_legacy_not_found"})
            continue

        if os.path.isfile(new_abs):
            details.append({"from": legacy_rel, "to": new_rel, "action": "skipped_new_exists"})
            continue

        os.makedirs(os.path.dirname(new_abs), exist_ok=True)
        try:
            shutil.copy2(legacy_abs, new_abs)
            _log("模板迁移: {} -> {}".format(legacy_rel, new_rel))
            migrated = True
            details.append({"from": legacy_rel, "to": new_rel, "action": "copied"})
        except Exception as e:
            _log("模板迁移失败: {} -> {}: {}".format(legacy_rel, new_rel, e))
            details.append({"from": legacy_rel, "to": new_rel, "action": "failed", "error": str(e)})

    return {"migrated": migrated, "details": details}
