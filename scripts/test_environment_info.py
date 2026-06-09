# -*- coding: utf-8 -*-
"""
环境信息模块自测脚本

验证 environment_info 数据源在当前项目根目录下的返回正确性。
只做轻量检查，不启动服务、不修改配置、不写文件。
"""
import os
import sys
import json

# 确保项目根目录在 sys.path
_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.normpath(os.path.join(_script_dir, ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from runtime.panel.environment_info import get_environment_info


def run_tests():
    """执行所有测试，返回 (passed, failed) 计数。"""
    passed = 0
    failed = 0

    def check(condition, msg):
        nonlocal passed, failed
        if condition:
            passed += 1
            print("  [PASS] " + msg)
        else:
            failed += 1
            print("  [FAIL] " + msg)

    info = get_environment_info()
    root_dir = info.get("root_dir", "")

    print("Root dir: " + root_dir)
    print()

    # ---- Test 1: 路径不硬编码 C:\WNMP ----
    print("--- Test 1: 路径不硬编码 ---")
    check(
        "C:\\WNMP" not in root_dir.upper() and "C:/WNMP" not in root_dir.upper(),
        "root_dir 不包含 C:\\WNMP（动态检测）"
    )

    # ---- Test 2: 模块结构完整 ----
    print("\n--- Test 2: 模块结构 ---")
    modules = info.get("modules", {})
    check("nginx" in modules, "包含 nginx 模块")
    check("php" in modules, "包含 php 模块")
    check("mysql" in modules, "包含 mysql 模块")

    # ---- Test 3: Nginx 路径正确 ----
    print("\n--- Test 3: Nginx 路径 ---")
    nginx = modules.get("nginx", {})
    check(nginx.get("title") == "Nginx", "Nginx title = Nginx")
    check(nginx.get("status") in ("applied", "pending", "unknown"),
          "Nginx status 为 applied/pending/unknown")

    items = nginx.get("items", [])
    check(len(items) == 5, "Nginx items 数量 = 5")
    # 收集各 item 的 label
    labels = {it["label"]: it for it in items}

    main_cfg = labels.get("主配置文件")
    check(main_cfg is not None, "包含 主配置文件")
    if main_cfg:
        check(main_cfg["path"] == "config/nginx.conf", "主配置文件 path = config/nginx.conf")
        check(main_cfg["kind"] == "file", "主配置文件 kind = file")
        check(main_cfg["edit_key"] == "nginx", "主配置文件 edit_key = nginx")
        # 绝对路径应该包含 root_dir
        check(main_cfg["abs_path"].startswith(root_dir), "主配置文件 abs_path 以 root_dir 开头")

    site_cfg = labels.get("默认站点配置")
    check(site_cfg is not None, "包含 默认站点配置")
    if site_cfg:
        check(site_cfg["path"] == "config/nginx/site.conf", "默认站点配置 path")
        check(site_cfg["edit_key"] == "nginx-site", "默认站点配置 edit_key = nginx-site")

    vhosts = labels.get("新增站点目录")
    check(vhosts is not None, "包含 新增站点目录")
    if vhosts:
        check(vhosts["path"] == "config/nginx/vhosts", "新增站点目录 path")
        check(vhosts["kind"] == "directory", "新增站点目录 kind = directory")
        check(vhosts["open_key"] == "nginx_vhosts_dir", "新增站点目录 open_key")
        check("完整 server { ... }" in vhosts["description"],
              "vhosts description 提示完整 server { ... } 块")

    http_ext = labels.get("HTTP 级扩展")
    check(http_ext is not None, "包含 HTTP 级扩展")
    if http_ext:
        check(http_ext["path"] == "config/nginx/custom/http", "HTTP 级扩展 path")
        check(http_ext["open_key"] == "nginx_custom_http_dir", "HTTP 级扩展 open_key")
        check("upstream" in http_ext["description"].lower() or "http" in http_ext["description"].lower(),
              "HTTP 级扩展 description 提示 upstream/map/gzip")

    srv_ext = labels.get("默认站点扩展")
    check(srv_ext is not None, "包含 默认站点扩展")
    if srv_ext:
        check(srv_ext["path"] == "config/nginx/custom/server", "默认站点扩展 path")
        check(srv_ext["open_key"] == "nginx_custom_server_dir", "默认站点扩展 open_key")
        check("location" in srv_ext["description"].lower() or "server" in srv_ext["description"].lower(),
              "server 扩展 description 提示 location/rewrite/add_header")

    # ---- Test 4: Nginx actions ----
    print("\n--- Test 4: Nginx actions ---")
    actions = nginx.get("actions", [])
    check(len(actions) >= 2, "Nginx actions 数量 >= 2")
    action_types = {a["type"]: a for a in actions}
    check("edit_config" in action_types, "包含 edit_config 类型 action")
    check("open_dir" in action_types, "包含 open_dir 类型 action")

    # ---- Test 5: PHP 同时包含 php.ini 和 php-cgi.ini ----
    print("\n--- Test 5: PHP-CGI 路径 ---")
    php = modules.get("php", {})
    check(php.get("title") == "PHP-CGI", "PHP-CGI title")
    check(php.get("status") in ("applied", "pending", "unknown"), "PHP-CGI status")

    php_items = php.get("items", [])
    check(len(php_items) == 2, "PHP items 数量 = 2")
    php_labels = {it["label"]: it for it in php_items}

    php_cfg = php_labels.get("PHP 配置文件")
    check(php_cfg is not None, "包含 PHP 配置文件")
    if php_cfg:
        check(php_cfg["path"] == "config/php/php.ini", "PHP 配置 path")
        check(php_cfg["edit_key"] == "php", "PHP 配置 edit_key = php")

    cgi_cfg = php_labels.get("PHP-CGI 进程配置")
    check(cgi_cfg is not None, "包含 PHP-CGI 进程配置")
    if cgi_cfg:
        check(cgi_cfg["path"] == "config/php/php-cgi.ini", "PHP-CGI 进程配置 path")
        check(cgi_cfg["edit_key"] == "php-cgi", "PHP-CGI 进程配置 edit_key = php-cgi")

    # ---- Test 6: MySQL 包含 my.ini ----
    print("\n--- Test 6: MySQL 路径 ---")
    mysql = modules.get("mysql", {})
    check(mysql.get("title") == "MySQL", "MySQL title")
    mysql_items = mysql.get("items", [])
    check(len(mysql_items) == 1, "MySQL items 数量 = 1")
    if mysql_items:
        my = mysql_items[0]
        check(my["label"] == "MySQL 主配置文件", "MySQL 主配置文件 label")
        check(my["path"] == "config/mysql/my.ini", "MySQL 主配置文件 path")
        check(my["edit_key"] == "mysql", "MySQL 主配置文件 edit_key = mysql")

    # ---- Test 7: edit_key 都在现有配置编辑白名单中 ----
    print("\n--- Test 7: edit_key 白名单验证 ---")
    from runtime.panel.config_editor import VALID_CONFIG_NAMES
    all_items = []
    for mod_key in ("nginx", "php", "mysql"):
        all_items.extend(modules[mod_key].get("items", []))

    for item in all_items:
        ek = item.get("edit_key")
        if ek:
            check(ek in VALID_CONFIG_NAMES,
                  "edit_key '{}' 在白名单中".format(ek))

    # ---- Test 8: open_key 白名单验证 ----
    print("\n--- Test 8: open_key 白名单验证 ---")
    from runtime.panel.environment_info import _OPEN_DIR_WHITELIST
    all_actions = []
    for mod_key in ("nginx", "php", "mysql"):
        all_actions.extend(modules[mod_key].get("actions", []))

    for action in all_actions:
        ok = action.get("open_key")
        if ok:
            check(ok in _OPEN_DIR_WHITELIST,
                  "open_key '{}' 在白名单中".format(ok))

    # ---- Test 9: 所有 item 都有必要字段 ----
    print("\n--- Test 9: Item 字段完整性 ---")
    required_fields = {"label", "path", "abs_path", "kind", "description"}
    for item in all_items:
        missing = required_fields - set(item.keys())
        check(len(missing) == 0,
              "Item '{}' 字段完整 (缺少: {})".format(item.get("label", "?"), missing))

    # ---- Test 10: 路径一致性 ----
    print("\n--- Test 10: 路径一致性 ---")
    for item in all_items:
        ap = item.get("abs_path", "")
        rp = item.get("path", "")
        expected = os.path.normpath(os.path.join(root_dir, rp))
        check(ap == expected,
              "abs_path 正确: {} -> {}".format(rp, ap))

    # ---- Test 11: open_directory 安全检查 ----
    print("\n--- Test 11: open_directory 安全边界 ---")
    from runtime.panel.environment_info import open_directory

    # 空 key 应失败
    result = open_directory("")
    check(not result["success"], "空 open_key 返回失败")

    # 不存在的 key 应失败
    result = open_directory("nonexistent_dir")
    check(not result["success"], "无效 open_key 返回失败")

    # 合法 key：Windows 下应成功，非 Windows 下应返回"仅支持 Windows 系统"
    is_windows = sys.platform == "win32"
    for key in ("nginx_config_dir", "php_config_dir", "mysql_config_dir"):
        result = open_directory(key)
        if is_windows:
            check(result["success"], "合法 open_key '{}' 成功（Windows）".format(key))
        else:
            check(not result["success"] and "Windows" in result.get("message", ""),
                  "合法 open_key '{}' 非 Windows 返回预期提示".format(key))

    # ---- Summary ----
    print("\n" + "=" * 60)
    total = passed + failed
    print("Total: {} tests, {} passed, {} failed".format(total, passed, failed))
    if failed == 0:
        print("ALL TESTS PASSED!")
    else:
        print("SOME TESTS FAILED!")
    print("=" * 60)

    return passed, failed


if __name__ == "__main__":
    p, f = run_tests()
    sys.exit(0 if f == 0 else 1)
