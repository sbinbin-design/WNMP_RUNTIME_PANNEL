"""
WNMP Status Module - shows configuration summary, binary existence, and service status
"""
import os


def check_binary(root_dir, rel_path):
    """Check if a binary file exists, return (exists, full_path)."""
    full_path = os.path.join(root_dir, rel_path)
    return os.path.isfile(full_path), full_path


def show_status(root_dir, cfg, logger=None):
    """Display configuration summary, binary existence, and service status."""
    from runtime import wnmp_config
    from runtime.wnmp_path import resolve_path
    from runtime.wnmp_log import log_info

    web_root = resolve_path(root_dir, wnmp_config.get(cfg, "WEB_ROOT"))
    mysql_data_dir = resolve_path(root_dir, wnmp_config.get(cfg, "MYSQL_DATA_DIR"))
    config_dir = os.path.join(root_dir, "config")
    logs_dir = os.path.join(root_dir, "logs")
    pid_dir = os.path.join(root_dir, "runtime", "pids")

    print("=" * 50)
    print("  WNMP Runtime - Status")
    print("=" * 50)
    print()

    print("Configuration (runtime.ini 默认值，实际端口以配置文件为准):")
    print("  WEB_ROOT:          " + web_root)
    print("  HTTP_PORT:         " + wnmp_config.get(cfg, "HTTP_PORT") + " (实际: " + str(wnmp_config.get_effective_nginx_http_port(root_dir, cfg)) + ")")
    print("  HTTPS_PORT:        " + wnmp_config.get(cfg, "HTTPS_PORT") + " (实际: " + str(wnmp_config.get_effective_nginx_https_port(root_dir, cfg)) + ")")
    print("  ENABLE_HTTPS:      " + wnmp_config.get(cfg, "ENABLE_HTTPS") + " (实际: " + ("YES" if wnmp_config.is_effective_nginx_https_enabled(root_dir, cfg) else "NO") + ")")
    php_cgi_host, php_cgi_port = wnmp_config.get_effective_php_cgi_host_port(root_dir, cfg)
    print("  PHP_CGI_HOST:      " + wnmp_config.get(cfg, "PHP_CGI_HOST") + " (实际: " + php_cgi_host + ")")
    print("  PHP_CGI_PORT:      " + wnmp_config.get(cfg, "PHP_CGI_PORT") + " (实际: " + str(php_cgi_port) + ")")
    print("  MYSQL_HOST:        " + wnmp_config.get(cfg, "MYSQL_HOST"))
    print("  MYSQL_PORT:        " + wnmp_config.get(cfg, "MYSQL_PORT") + " (实际: " + str(wnmp_config.get_effective_mysql_port(root_dir, cfg)) + ")")
    print("  MYSQL_DATA_DIR:    " + mysql_data_dir)
    print("  AUTO_OPEN_BROWSER: " + wnmp_config.get(cfg, "AUTO_OPEN_BROWSER"))
    print()

    print("Config Files:")
    print("  runtime.ini:       " + os.path.join(config_dir, "runtime.ini"))
    print("  nginx.conf:        " + os.path.join(config_dir, "nginx.conf"))
    print("  site.conf:         " + os.path.join(config_dir, "nginx", "site.conf"))
    print("  php.ini:           " + os.path.join(config_dir, "php", "php.ini"))
    print("  php-cgi.ini:       " + os.path.join(config_dir, "php", "php-cgi.ini"))
    print("  my.ini:            " + os.path.join(config_dir, "mysql", "my.ini"))
    print()

    print("Log Files:")
    print("  runtime.log:       " + os.path.join(logs_dir, "runtime", "runtime.log"))
    print("  autostart.log:     " + os.path.join(logs_dir, "runtime", "autostart.log"))
    print("  nginx/error.log:   " + os.path.join(logs_dir, "nginx", "error.log"))
    print("  mysql/error.log:   " + os.path.join(logs_dir, "mysql", "error.log"))
    print()
    print("Binary Files:")
    binaries = [
        ("Nginx", "bin/nginx/nginx.exe"),
        ("PHP-CGI", "bin/php/php-cgi.exe"),
        ("PHP CLI", "bin/php/php.exe"),
        ("MySQL", "bin/mysql/bin/mysqld.exe"),
        ("MySQL Admin", "bin/mysql/bin/mysqladmin.exe"),
        ("MySQL Client", "bin/mysql/bin/mysql.exe"),
        ("OpenSSL", "bin/openssl/openssl.exe"),
    ]

    all_found = True
    for name, rel_path in binaries:
        exists, full_path = check_binary(root_dir, rel_path)
        status = "FOUND" if exists else "NOT FOUND"
        if not exists:
            all_found = False
        print("  {:<15} {}  {}".format(name + ":", status, full_path))

    print()

    # Service status
    print("Service Status:")
    try:
        from runtime.wnmp_nginx import get_nginx_status
        from runtime.wnmp_process import is_port_listening, find_processes_by_path
        nginx_st = get_nginx_status(root_dir, cfg, logger)
        nginx_pid_file = os.path.join(pid_dir, "nginx.pid")
        http_port = wnmp_config.get_effective_nginx_http_port(root_dir, cfg)
        https_port_val = wnmp_config.get_effective_nginx_https_port(root_dir, cfg)
        enable_https = wnmp_config.is_effective_nginx_https_enabled(root_dir, cfg)
        http_listening = is_port_listening("127.0.0.1", http_port)
        https_listening = is_port_listening("127.0.0.1", https_port_val) if enable_https and https_port_val else None
        pid_file_exists = os.path.isfile(nginx_pid_file)
        pid_recorded = nginx_st.get("pid")

        print("  Nginx:")
        print("    HTTP: {}:{}".format(http_port, "LISTENING" if http_listening else "FREE"))
        if enable_https and https_port_val:
            print("    HTTPS: {}:{}".format(https_port_val, "LISTENING" if https_listening else "FREE"))
        else:
            print("    HTTPS: DISABLED")
        print("    PID Cache: {}  PID: {}".format(
            "exists" if pid_file_exists else "missing",
            pid_recorded or "N/A"
        ))
        if http_listening and not pid_file_exists:
            residual = find_processes_by_path(root_dir, "nginx.exe", logger)
            if residual:
                print("    NOTE: Port {} in use, PID cache missing, found tool PID: {}".format(http_port, residual))
            else:
                print("    NOTE: Port {} in use, PID cache missing, no tool nginx.exe found (may be another service)".format(http_port))
        if enable_https and https_listening and not pid_file_exists:
            residual_https = find_processes_by_path(root_dir, "nginx.exe", logger)
            if residual_https:
                print("    NOTE: HTTPS {} in use, PID cache missing, found tool PID: {}".format(https_port_val, residual_https))
            else:
                print("    NOTE: HTTPS {} in use, PID cache missing, no tool nginx.exe found (may be another service)".format(https_port_val))

    except Exception as e:
        print("  Nginx:          UNKNOWN (error: {})".format(str(e)))

    try:
        from runtime.wnmp_php import get_php_cgi_status
        from runtime.wnmp_process import is_port_listening, find_processes_by_path
        php_st = get_php_cgi_status(root_dir, cfg, logger)
        php_pid_file = os.path.join(pid_dir, "php-cgi.pid")
        php_cgi_host, php_cgi_port = wnmp_config.get_effective_php_cgi_host_port(root_dir, cfg)

        pid_file_exists = os.path.isfile(php_pid_file)
        port_listening = is_port_listening(php_cgi_host, php_cgi_port)

        status_parts = []
        if php_st["running"]:
            status_parts.append("RUNNING")
        else:
            status_parts.append("STOPPED")

        if port_listening:
            status_parts.append("PORT-LISTENING")
        else:
            status_parts.append("PORT-FREE")

        if pid_file_exists:
            status_parts.append("PID-CACHE")
        else:
            status_parts.append("NO-PID-CACHE")

        if port_listening and not php_st["running"]:
            residual = find_processes_by_path(root_dir, "php-cgi.exe", logger)
            if residual:
                status_parts.append("RESIDUAL-TOOL-PID={}".format(",".join(str(p) for p in residual)))
            else:
                status_parts.append("RESIDUAL-POSSIBLY-OTHER")

        status_str = " ".join(status_parts)
        print("  PHP-CGI:        {}".format(status_str))
        print("    PID Cache: {}  Port: {}  PID: {}".format(
            "exists" if pid_file_exists else "missing",
            "LISTENING" if port_listening else "FREE",
            php_st["pid"] or "N/A"
        ))
    except Exception as e:
        print("  PHP-CGI:        UNKNOWN (error: {})".format(str(e)))

    try:
        from runtime.wnmp_mysql import get_mysql_status
        from runtime.wnmp_process import is_port_listening, find_processes_by_path
        mysql_st = get_mysql_status(root_dir, cfg, logger)
        mysql_pid_file = os.path.join(pid_dir, "mysqld.pid")
        mysql_host = cfg.get("MYSQL_HOST", "127.0.0.1")
        mysql_port = wnmp_config.get_effective_mysql_port(root_dir, cfg)

        pid_file_exists = os.path.isfile(mysql_pid_file)
        port_listening = is_port_listening(mysql_host, mysql_port)

        status_parts = []
        if mysql_st["running"]:
            status_parts.append("RUNNING")
        else:
            status_parts.append("STOPPED")

        if port_listening:
            status_parts.append("PORT-LISTENING")
        else:
            status_parts.append("PORT-FREE")

        if pid_file_exists:
            status_parts.append("PID-CACHE")
        else:
            status_parts.append("NO-PID-CACHE")

        if port_listening and not mysql_st["running"]:
            residual = find_processes_by_path(root_dir, "mysqld.exe", logger)
            if residual:
                status_parts.append("RESIDUAL-TOOL-PID={}".format(",".join(str(p) for p in residual)))
            else:
                status_parts.append("RESIDUAL-POSSIBLY-OTHER")

        status_str = " ".join(status_parts)
        print("  MySQL:          {}".format(status_str))
        print("    PID Cache: {}  Port: {}  PID: {}".format(
            "exists" if pid_file_exists else "missing",
            "LISTENING" if port_listening else "FREE",
            mysql_st["pid"] or "N/A"
        ))
    except Exception as e:
        print("  MySQL:          UNKNOWN (error: {})".format(str(e)))

    print()
    if all_found:
        print("All required binaries found.")
    else:
        print("Some binaries are missing. Please place them in the bin/ directory.")

    # Config placeholder check
    print()
    print("Config Placeholder Check:")
    try:
        from runtime.wnmp_templates import validate_all_configs
        ok, errors = validate_all_configs(root_dir, cfg, logger)
        if ok:
            print("  Placeholders:      PASS - No unexpanded placeholders found")
        else:
            print("  Placeholders:      FAIL - Unexpanded placeholders detected")
            for file_path, matches in errors:
                rel_path = os.path.relpath(file_path, root_dir)
                print("    {} -> {}".format(rel_path, ", ".join(matches)))
    except Exception as e:
        print("  Placeholders:      UNKNOWN (error: {})".format(str(e)))

    # Certificate status
    print()
    print("Certificate Status:")
    try:
        from runtime.wnmp_openssl import get_cert_status
        from runtime import wnmp_config
        cert_st = get_cert_status(root_dir, logger)
        enable_https = wnmp_config.is_effective_nginx_https_enabled(root_dir, cfg)
        auto_gen_cert = wnmp_config.get(cfg, "AUTO_GENERATE_CERT", "1")
        print("  server.crt:    {} ({} bytes)".format(
            "EXISTS" if cert_st["cert_exists"] else "NOT FOUND",
            cert_st["cert_size"]
        ))
        print("  server.key:    {} ({} bytes)".format(
            "EXISTS" if cert_st["key_exists"] else "NOT FOUND",
            cert_st["key_size"]
        ))
        print("  Valid:         {}".format("YES" if cert_st["cert_valid"] else "NO"))
        print("  Path:         {}".format(cert_st["cert_path"]))
        print()
        print("  HTTPS enabled:     {}".format("YES" if enable_https else "NO"))
        print("  AUTO_GENERATE_CERT: {}".format(auto_gen_cert))
        if enable_https:
            print()
            print("  HTTPS is ENABLED (detected from Nginx config ssl listen), Nginx will use this certificate")
        else:
            print()
            print("  HTTPS is NOT enabled (no ssl listen in Nginx config), certificate is pre-generated")
    except Exception as e:
        print("  Certificate status: UNKNOWN (error: {})".format(str(e)))

    # Init state and user config status
    print()
    print("Init & Runtime State:")
    try:
        from runtime.wnmp_state import load_state, is_default_site_initialized, is_initialized
        from runtime.wnmp_path import is_default_web_root, resolve_path
        from runtime import wnmp_config

        state = load_state(root_dir)
        state_path = os.path.join(root_dir, "runtime", "state.json")
        initialized = is_initialized(root_dir)
        print("  INITIALIZED:       {}".format("YES" if initialized else "NO"))
        print("  state.json:        {}".format(state_path))
        print("  INITIALIZED_AT:    {}".format(state.get("INITIALIZED_AT", "N/A")))
        print("  CONFIG_GENERATED:  {}".format("YES" if state.get("CONFIG_GENERATED", False) else "NO"))
        print("  DEFAULT_SITE:      {}".format("YES" if state.get("DEFAULT_SITE_INITIALIZED", False) else "NO"))
        print("  CERT_INITIALIZED:  {}".format("YES" if state.get("CERT_INITIALIZED", False) else "NO"))
        print("  MYSQL_INITIALIZED: {}".format("YES" if state.get("MYSQL_INITIALIZED", False) else "NO"))

        web_root_raw = wnmp_config.get(cfg, "WEB_ROOT")
        web_root = resolve_path(root_dir, web_root_raw)
        is_default = is_default_web_root(root_dir, web_root_raw)
        print("  WEB_ROOT is default: {}".format("YES" if is_default else "NO (" + web_root_raw + ")"))

        # 默认检测页状态
        index_path = os.path.join(web_root, "index.php")
        index_exists = os.path.isfile(index_path)
        print("  Default index.php:   {}".format("EXISTS" if index_exists else "NOT FOUND"))

        # 证书存在性
        cert_path = os.path.join(root_dir, "config", "certs", "server.crt")
        key_path = os.path.join(root_dir, "config", "certs", "server.key")
        print("  server.crt:        {}".format("EXISTS" if os.path.isfile(cert_path) else "NOT FOUND"))
        print("  server.key:        {}".format("EXISTS" if os.path.isfile(key_path) else "NOT FOUND"))

        # MySQL 数据目录是否初始化
        mysql_data_dir = resolve_path(root_dir, wnmp_config.get(cfg, "MYSQL_DATA_DIR"))
        mysql_initialized = os.path.isdir(os.path.join(mysql_data_dir, "mysql"))
        print("  MySQL data dir:    {}".format("INITIALIZED" if mysql_initialized else "NOT INITIALIZED"))

        # root-password.txt 不再持久保存，仅显示历史遗留文件是否存在
        pwd_file = os.path.join(root_dir, "config", "mysql", "root-password.txt")
        if os.path.isfile(pwd_file):
            print("  root-password.txt: EXISTS (legacy, no longer used)")
        # 不再提示 "NOT FOUND"，因为默认不再生成此文件

        # 实际配置文件是否存在
        print()
        print("  Actual Config Files (user-editable):")
        actual_configs = [
            ("config/nginx.conf", os.path.join(root_dir, "config", "nginx.conf")),
            ("config/nginx/site.conf", os.path.join(root_dir, "config", "nginx", "site.conf")),
            ("config/php/php.ini", os.path.join(root_dir, "config", "php", "php.ini")),
            ("config/mysql/my.ini", os.path.join(root_dir, "config", "mysql", "my.ini")),
        ]
        for name, path in actual_configs:
            print("    {}: {}".format(name, "EXISTS" if os.path.isfile(path) else "NOT FOUND"))

        # 模板文件是否存在
        print()
        print("  Template Files (for reset-config):")
        template_files = [
            ("config/nginx/nginx.conf.template", os.path.join(root_dir, "config", "nginx", "nginx.conf.template")),
            ("config/nginx/site.conf.template", os.path.join(root_dir, "config", "nginx", "site.conf.template")),
            ("config/php/php.ini.template", os.path.join(root_dir, "config", "php", "php.ini.template")),
            ("config/mysql/my.ini.template", os.path.join(root_dir, "config", "mysql", "my.ini.template")),
        ]
        for name, path in template_files:
            print("    {}: {}".format(name, "EXISTS" if os.path.isfile(path) else "NOT FOUND"))

        # 用户自定义配置状态
        php_user_ini = os.path.join(root_dir, "config", "php", "php.user.ini")
        my_user_ini = os.path.join(root_dir, "config", "mysql", "my.user.ini")
        nginx_custom_http = os.path.join(root_dir, "config", "nginx", "custom", "http")
        nginx_custom_server = os.path.join(root_dir, "config", "nginx", "custom", "server")

        php_user_exists = os.path.isfile(php_user_ini)
        my_user_exists = os.path.isfile(my_user_ini)
        nginx_custom_http_exists = os.path.isdir(nginx_custom_http)
        nginx_custom_server_exists = os.path.isdir(nginx_custom_server)

        print()
        print("  User Config Files (optional):")
        print("    php.user.ini:        {}".format("EXISTS" if php_user_exists else "NOT FOUND"))
        print("    my.user.ini:         {}".format("EXISTS" if my_user_exists else "NOT FOUND"))
        print("    nginx/custom/http:   {}".format("EXISTS" if nginx_custom_http_exists else "NOT FOUND"))
        print("    nginx/custom/server: {}".format("EXISTS" if nginx_custom_server_exists else "NOT FOUND"))

        if nginx_custom_http_exists:
            http_files = [f for f in os.listdir(nginx_custom_http) if f.endswith(".conf") and not f.endswith(".disabled") and "placeholder" not in f.lower()]
            if http_files:
                print("      http conf files:   {} files: {}".format(len(http_files), ", ".join(http_files)))
        if nginx_custom_server_exists:
            server_files = [f for f in os.listdir(nginx_custom_server) if f.endswith(".conf") and not f.endswith(".disabled") and "placeholder" not in f.lower()]
            if server_files:
                print("      server conf files: {} files: {}".format(len(server_files), ", ".join(server_files)))
    except Exception as e:
        print("  Init & runtime state: UNKNOWN (error: {})".format(str(e)))

    # Nginx Virtual Host Summary
    print()
    print("Nginx Virtual Hosts:")
    try:
        vhosts_dir = os.path.join(root_dir, "config", "nginx", "vhosts")
        vhosts_exists = os.path.isdir(vhosts_dir)
        print("  vhosts/ dir:       {}".format("EXISTS" if vhosts_exists else "NOT FOUND"))

        if vhosts_exists:
            vhost_files = [f for f in os.listdir(vhosts_dir) if f.endswith(".conf") and not f.endswith(".disabled") and "placeholder" not in f.lower()]
            placeholder_exists = os.path.isfile(os.path.join(vhosts_dir, "placeholder.conf"))
            print("  enabled vhosts:    {} files".format(len(vhost_files)))
            if vhost_files:
                print("    files:           {}".format(", ".join(vhost_files)))
            print("  placeholder.conf:  {}".format("EXISTS" if placeholder_exists else "NOT FOUND"))

            # Nginx config test
            from runtime.wnmp_nginx import test_nginx_config
            ok, output = test_nginx_config(root_dir, cfg, logger)
            print("  nginx -t:          {}".format("PASS" if ok else "FAIL"))
            if not ok:
                # 只显示第一行错误
                first_line = output.strip().split("\n")[0]
                print("    error:           {}".format(first_line))
        else:
            print("  enabled vhosts:    N/A")
            print("  nginx -t:          N/A")

        # custom/http and custom/server 存在性
        custom_http_dir = os.path.join(root_dir, "config", "nginx", "custom", "http")
        custom_server_dir = os.path.join(root_dir, "config", "nginx", "custom", "server")
        print("  custom/http/:      {}".format("EXISTS" if os.path.isdir(custom_http_dir) else "NOT FOUND"))
        print("  custom/server/:    {}".format("EXISTS" if os.path.isdir(custom_server_dir) else "NOT FOUND"))
    except Exception as e:
        print("  Nginx virtual hosts: UNKNOWN (error: {})".format(str(e)))

    # System PATH Status
    print()
    print("System PATH Integration:")
    try:
        from runtime.wnmp_env import is_admin, get_tool_paths, get_path_items_status
        from runtime.wnmp_state import is_env_path_configured, load_state, get_env_path_items
        from runtime.wnmp_env import check_path_migration
        from runtime import wnmp_config

        admin = is_admin()
        print("  Admin privileges:  {}".format("YES" if admin else "NO"))

        add_openssl = wnmp_config.get_int(cfg, "ADD_OPENSSL_TO_SYSTEM_PATH", 0) == 1
        tool_paths = get_tool_paths(root_dir, add_openssl)

        status_items = get_path_items_status(root_dir, add_openssl)
        all_in_path = all(in_path for _, in_path in status_items)
        any_in_path = any(in_path for _, in_path in status_items)

        configured = is_env_path_configured(root_dir)
        print("  PATH integrated:   {}".format("ENABLED" if configured else "DISABLED"))

        if any_in_path:
            print("  PHP in PATH:       {}".format("YES" if status_items[0][1] else "NO"))
            print("  MySQL in PATH:     {}".format("YES" if status_items[1][1] else "NO"))
            print("  Nginx in PATH:     {}".format("YES" if status_items[2][1] else "NO"))
        else:
            print("  Tool paths in PATH: NONE")

        state = load_state(root_dir)
        if state.get("ENV_PATH_SKIP_REASON"):
            print("  Skip reason:      {}".format(state.get("ENV_PATH_SKIP_REASON")))

        state_items = get_env_path_items(root_dir)
        if state_items and check_path_migration(root_dir, state_items):
            print()
            print("  WARNING: Tool directory moved. Old paths still in system PATH.")
            print("  Run: bin\\python\\python.exe runtime\\wnmpctl.py install-env (as admin) to update, uninstall-env to remove")
    except Exception as e:
        print("  System PATH status: UNKNOWN (error: {})".format(str(e)))

    # MySQL security status
    print()
    print("MySQL Security Status:")
    try:
        from runtime.wnmp_mysql import get_password_file_path, check_mysql_data_dir_state
        pwd_file = get_password_file_path(root_dir)
        pwd_file_exists = os.path.isfile(pwd_file)
        mysql_data_dir = resolve_path(root_dir, wnmp_config.get(cfg, "MYSQL_DATA_DIR"))
        data_state = check_mysql_data_dir_state(mysql_data_dir)

        state_display = {
            "not_exists": "NOT EXISTS",
            "empty": "EMPTY (not initialized)",
            "initialized": "INITIALIZED",
            "dirty": "DIRTY (incomplete files)",
        }
        print("  MySQL data dir:     {}".format(state_display.get(data_state, data_state)))

        # root-password.txt 不再作为判断条件，已初始化数据目录不需要密码文件
        if data_state == "initialized":
            print("  root password:     managed by MySQL (no local password file)")
        elif os.path.isfile(pwd_file):
            print("  root password file: EXISTS (legacy, no longer used)")

        # 显示 MySQL 登录命令提示（不显示密码明文）
        mysql_host = wnmp_config.get(cfg, "MYSQL_HOST", "127.0.0.1")
        mysql_port = wnmp_config.get_effective_mysql_port(root_dir, cfg)
        print()
        print("  MySQL login command:")
        print("    bin\\mysql\\bin\\mysql.exe --protocol=tcp --host={} --port={} -u root -p".format(mysql_host, mysql_port))
        print("  (Enter root password when prompted)")
    except Exception as e:
        print("  MySQL security status: UNKNOWN (error: {})".format(str(e)))

    return 0
