# -*- coding: utf-8 -*-
"""
WNMP Environment Info Module - 环境信息数据源

为首页"环境信息"模块提供统一的后端数据源。只负责数据组装，不涉及
服务启停、配置保存、配置生成等逻辑。

第二阶段新增：安全打开目录能力（open_directory）。
"""
import os
import subprocess
import sys

from runtime.panel.paths import get_root_dir


# ---- 配置路径定义（相对于 root_dir）----

# 编辑白名单 key 映射（复用 config_editor.CONFIG_FILE_MAP 的 key）
_NGINX_MAIN_CONFIG = "config/nginx.conf"
_NGINX_SITE_CONFIG = "config/nginx/site.conf"
_NGINX_VHOSTS_DIR = "config/nginx/vhosts"           # *.conf 完整独立站点目录
_NGINX_CUSTOM_HTTP_DIR = "config/nginx/custom/http"  # HTTP 级扩展目录
_NGINX_CUSTOM_SERVER_DIR = "config/nginx/custom/server"  # 默认站点 server 级扩展目录
_PHP_CONFIG = "config/php/php.ini"
_PHP_CGI_CONFIG = "config/php/php-cgi.ini"
_MYSQL_CONFIG = "config/mysql/my.ini"


# ---- 打开目录白名单（key -> 相对路径）----

_OPEN_DIR_WHITELIST = {
    "nginx_config_dir": "config/nginx",
    "nginx_vhosts_dir": _NGINX_VHOSTS_DIR,
    "nginx_custom_http_dir": _NGINX_CUSTOM_HTTP_DIR,
    "nginx_custom_server_dir": _NGINX_CUSTOM_SERVER_DIR,
    "php_config_dir": "config/php",
    "mysql_config_dir": "config/mysql",
}


# ---- 环境信息定义 ------------------------------------------------------------

def _build_paths(root_dir, rel):
    """根据相对路径构建 {path, abs_path}。"""
    return {
        "path": rel,
        "abs_path": os.path.normpath(os.path.join(root_dir, rel)),
    }


def _file_exists(root_dir, rel):
    """检查文件是否存在。"""
    return os.path.isfile(os.path.join(root_dir, rel))


def _dir_exists(root_dir, rel):
    """检查目录是否存在。"""
    return os.path.isdir(os.path.join(root_dir, rel))


def _get_component_config_status(root_dir, component):
    """获取组件配置状态：applied / pending / unknown。

    复用 wnmp_state.is_component_config_dirty 判断配置是否待生效。
    Nginx 额外考虑 pending_reload（配置已修改但服务仍在运行）。
    """
    try:
        from runtime.wnmp_state import is_component_config_dirty
        dirty = is_component_config_dirty(root_dir, component)
        if dirty:
            return "pending"
        return "applied"
    except Exception:
        return "unknown"


def get_environment_info():
    """组装完整的环境信息数据，返回 dict。

    调用方：panel_server.py GET /api/environment-info
    第二阶段修复：不再自动创建目录，只返回 exists 状态。
    """
    root_dir = get_root_dir()

    # ---- Nginx 模块 ----
    nginx_config_status = _get_component_config_status(root_dir, "nginx")

    nginx_items = [
        {
            "label": "主配置文件",
            "label_en": "Main Config",
            **_build_paths(root_dir, _NGINX_MAIN_CONFIG),
            "kind": "file",
            "exists": _file_exists(root_dir, _NGINX_MAIN_CONFIG),
            "description": "Nginx 全局主配置，包含 worker 进程数、日志路径、PID 路径、include 规则",
            "description_en": "Nginx main config: worker_processes, log paths, pid path, include directives",
            "edit_key": "nginx",
        },
        {
            "label": "默认站点配置",
            "label_en": "Default Site Config",
            **_build_paths(root_dir, _NGINX_SITE_CONFIG),
            "kind": "file",
            "exists": _file_exists(root_dir, _NGINX_SITE_CONFIG),
            "description": "默认站点的 server { ... } 配置，listen 端口、root 目录、PHP 转发规则",
            "description_en": "Default site server { ... } block: listen port, root dir, PHP proxy rules",
            "edit_key": "nginx-site",
        },
        {
            "label": "新增站点目录",
            "label_en": "Virtual Hosts (vhosts)",
            **_build_paths(root_dir, _NGINX_VHOSTS_DIR),
            "kind": "directory",
            "exists": _dir_exists(root_dir, _NGINX_VHOSTS_DIR),
            "description": "独立站点/vhost 目录，每个 .conf 应为完整 server { ... } 块",
            "description_en": "Independent vhost directory; each .conf should be a complete server { ... } block",
            "open_key": "nginx_vhosts_dir",
        },
        {
            "label": "HTTP 级扩展",
            "label_en": "HTTP-level Extensions",
            **_build_paths(root_dir, _NGINX_CUSTOM_HTTP_DIR),
            "kind": "directory",
            "exists": _dir_exists(root_dir, _NGINX_CUSTOM_HTTP_DIR),
            "description": "http {} 级扩展目录，适用于 upstream、map、gzip、log_format 等全局指令",
            "description_en": "http {} level extensions: upstream, map, gzip, log_format, etc.",
            "open_key": "nginx_custom_http_dir",
        },
        {
            "label": "默认站点扩展",
            "label_en": "Server-level Extensions",
            **_build_paths(root_dir, _NGINX_CUSTOM_SERVER_DIR),
            "kind": "directory",
            "exists": _dir_exists(root_dir, _NGINX_CUSTOM_SERVER_DIR),
            "description": "默认站点 server {} 级扩展目录，适用于 location、rewrite、add_header 等片段",
            "description_en": "Default site server {} level extensions: location, rewrite, add_header, etc.",
            "open_key": "nginx_custom_server_dir",
        },
    ]

    nginx_actions = [
        {
            "label": "编辑主配置",
            "label_en": "Edit Main Config",
            "type": "edit_config",
            "edit_key": "nginx",
        },
        {
            "label": "编辑默认站点",
            "label_en": "Edit Default Site",
            "type": "edit_config",
            "edit_key": "nginx-site",
        },
        {
            "label": "打开站点目录",
            "label_en": "Open Site Directory",
            "type": "open_dir",
            "open_key": "nginx_vhosts_dir",
        },
    ]

    nginx_module = {
        "title": "Nginx",
        "status": nginx_config_status,
        "items": nginx_items,
        "actions": nginx_actions,
    }

    # ---- PHP-CGI 模块 ----
    php_config_status = _get_component_config_status(root_dir, "php")

    php_items = [
        {
            "label": "PHP 配置文件",
            "label_en": "PHP Config",
            **_build_paths(root_dir, _PHP_CONFIG),
            "kind": "file",
            "exists": _file_exists(root_dir, _PHP_CONFIG),
            "description": "PHP 主配置文件 php.ini，控制扩展加载、内存限制、错误报告等",
            "description_en": "PHP main config php.ini: extensions, memory_limit, error_reporting, etc.",
            "edit_key": "php",
        },
        {
            "label": "PHP-CGI 进程配置",
            "label_en": "PHP-CGI Process Config",
            **_build_paths(root_dir, _PHP_CGI_CONFIG),
            "kind": "file",
            "exists": _file_exists(root_dir, _PHP_CGI_CONFIG),
            "description": "PHP-CGI 进程配置文件，包含监听地址端口、子进程数、环境变量",
            "description_en": "PHP-CGI process config: listen address/port, children count, environment variables",
            "edit_key": "php-cgi",
        },
    ]

    php_actions = [
        {
            "label": "编辑 PHP 配置",
            "label_en": "Edit PHP Config",
            "type": "edit_config",
            "edit_key": "php",
        },
        {
            "label": "编辑 CGI 配置",
            "label_en": "Edit CGI Config",
            "type": "edit_config",
            "edit_key": "php-cgi",
        },
        {
            "label": "打开配置目录",
            "label_en": "Open Config Directory",
            "type": "open_dir",
            "open_key": "php_config_dir",
        },
    ]

    php_module = {
        "title": "PHP-CGI",
        "status": php_config_status,
        "items": php_items,
        "actions": php_actions,
    }

    # ---- MySQL 模块 ----
    mysql_config_status = _get_component_config_status(root_dir, "mysql")

    mysql_items = [
        {
            "label": "MySQL 主配置文件",
            "label_en": "MySQL Main Config",
            **_build_paths(root_dir, _MYSQL_CONFIG),
            "kind": "file",
            "exists": _file_exists(root_dir, _MYSQL_CONFIG),
            "description": "MySQL 配置文件 my.ini，基于模板生成，包含 [mysqld] 端口数据目录等",
            "description_en": "MySQL config my.ini: [mysqld] port, datadir, etc.",
            "edit_key": "mysql",
        },
    ]

    mysql_actions = [
        {
            "label": "编辑配置",
            "label_en": "Edit Config",
            "type": "edit_config",
            "edit_key": "mysql",
        },
        {
            "label": "打开配置目录",
            "label_en": "Open Config Directory",
            "type": "open_dir",
            "open_key": "mysql_config_dir",
        },
    ]

    mysql_module = {
        "title": "MySQL",
        "status": mysql_config_status,
        "items": mysql_items,
        "actions": mysql_actions,
    }

    # ---- 组装返回 ----
    return {
        "root_dir": root_dir,
        "modules": {
            "nginx": nginx_module,
            "php": php_module,
            "mysql": mysql_module,
        },
    }


# ---- 安全打开目录 ------------------------------------------------------------

def open_directory(open_key):
    """根据白名单 open_key 安全打开目录。

    安全边界：
    - 只接受 open_key，不接受任意路径
    - open_key 必须在白名单 _OPEN_DIR_WHITELIST 中
    - 目录不存在时只允许创建白名单中的固定配置目录
    - 仅 Windows 下调用 explorer 打开目录
    - 不打开文件，只打开目录
    - 不影响 Nginx/PHP/MySQL 服务进程

    返回 dict: {"success": bool, "message": str}
    """
    if not open_key or open_key not in _OPEN_DIR_WHITELIST:
        return {"success": False, "message": "无效的目录标识"}

    root_dir = get_root_dir()
    rel_path = _OPEN_DIR_WHITELIST[open_key]
    abs_path = os.path.normpath(os.path.join(root_dir, rel_path))

    # 安全检查：使用 os.path.commonpath 确保目标目录位于 root_dir 下
    # 避免 startswith 前缀误判（如 C:\WNMP 与 C:\WNMP2）
    try:
        common = os.path.commonpath([abs_path, os.path.normpath(root_dir)])
        if common != os.path.normpath(root_dir):
            return {"success": False, "message": "目录路径不在项目根目录下"}
    except ValueError:
        # 不同驱动器或无法比较时拒绝
        return {"success": False, "message": "目录路径不在项目根目录下"}

    # 目录不存在时，仅允许创建白名单中的固定配置目录
    if not os.path.isdir(abs_path):
        try:
            os.makedirs(abs_path, exist_ok=True)
        except Exception as e:
            return {"success": False, "message": "目录创建失败: " + str(e)}

    # 仅 Windows 下调用 explorer 打开目录
    if sys.platform != "win32":
        return {"success": False, "message": "打开目录仅支持 Windows 系统"}

    try:
        subprocess.Popen(["explorer", abs_path], close_fds=True)
        return {"success": True, "message": "目录已打开"}
    except Exception as e:
        return {"success": False, "message": "目录打开失败: " + str(e)}
