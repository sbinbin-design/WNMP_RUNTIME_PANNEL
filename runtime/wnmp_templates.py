# -*- coding: utf-8 -*-
"""
WNMP Templates Module - generates config files from templates

模板与用户配置分离原则：
- templates（config/nginx/nginx.conf.template 等）只用于首次生成或显式恢复默认
- config/ 下的实际文件（nginx.conf、site.conf、php.ini、php-cgi.ini、my.ini）是用户配置
- 首次初始化时：文件不存在才从模板生成；文件已存在则跳过并记录日志
- start/restart 不得调用配置生成函数，只读取已有配置
"""
import os
import re


def read_template(root_dir, template_name):
    """Read a template file from config/ directory."""
    template_path = os.path.join(root_dir, "config", template_name)
    if not os.path.isfile(template_path):
        return None
    with open(template_path, "r", encoding="utf-8-sig") as f:
        return f.read()


def replace_variables(template, variables):
    """Replace {{KEY}} placeholders in template with values."""
    result = template
    for key, value in variables.items():
        result = result.replace("{{" + key + "}}", str(value))
    return result


def write_config(output_path, content):
    """Write config file with UTF-8 encoding."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)


def validate_no_placeholders(file_path, content, logger=None):
    """检查生成后的配置文件是否仍包含未替换的占位符 {{...}}。

    返回 (True, None) 或 (False, unexpanded_list)
    """
    pattern = re.compile(r'\{\{[^}]+\}\}')
    matches = pattern.findall(content)
    if matches:
        if logger:
            from runtime.wnmp_log import log_error
            log_error(logger, "Config file has unexpanded placeholders: {} -> {}".format(
                file_path, ", ".join(matches)))
        return False, matches
    return True, None


def validate_all_configs(root_dir, cfg, logger=None):
    """验证所有生成后的配置文件是否仍包含未替换的占位符。

    返回 (True, None) 或 (False, [(file_path, unexpanded_list), ...])
    """
    from runtime.wnmp_log import log_error, log_info

    config_files = [
        os.path.join(root_dir, "config", "nginx.conf"),
        os.path.join(root_dir, "config", "nginx", "site.conf"),
        os.path.join(root_dir, "config", "php", "php.ini"),
        os.path.join(root_dir, "config", "php", "php-cgi.ini"),
        os.path.join(root_dir, "config", "mysql", "my.ini"),
    ]

    errors = []
    for file_path in config_files:
        if os.path.isfile(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            ok, matches = validate_no_placeholders(file_path, content, logger)
            if not ok:
                errors.append((file_path, matches))

    if errors:
        log_error(logger, "Config placeholder validation failed:")
        for file_path, matches in errors:
            log_error(logger, "  {} -> {}".format(file_path, ", ".join(matches)))
        return False, errors

    log_info(logger, "All config placeholders validated successfully")
    return True, None


def generate_nginx_config(root_dir, cfg, logger=None):
    """Generate config/nginx.conf from template, include custom/*.conf if exists.

    首次初始化时：文件不存在才生成；文件已存在则跳过并记录日志。
    """
    from runtime.wnmp_path import to_forward_slash

    output_path = os.path.join(root_dir, "config", "nginx.conf")
    # 已存在的用户配置不得被覆盖
    if os.path.isfile(output_path):
        if logger:
            from runtime.wnmp_log import log_info
            log_info(logger, "配置文件已存在，跳过生成: " + output_path)
        return True, output_path

    logs_dir = to_forward_slash(os.path.join(root_dir, "logs"))
    runtime_dir = to_forward_slash(os.path.join(root_dir, "runtime"))
    config_dir = to_forward_slash(os.path.join(root_dir, "config"))
    nginx_temp_dir = to_forward_slash(os.path.join(root_dir, "temp"))

    template = read_template(root_dir, "nginx/nginx.conf.template")
    if template is None:
        return False, "Nginx config template not found"

    variables = {
        "LOGS_DIR": logs_dir,
        "RUNTIME_DIR": runtime_dir,
        "CONFIG_DIR": config_dir,
        "NGINX_TEMP_DIR": nginx_temp_dir,
    }

    content = replace_variables(template, variables)
    write_config(output_path, content)

    ok, _ = validate_no_placeholders(output_path, content)
    if not ok:
        return False, "nginx.conf has unexpanded placeholders"
    return True, output_path


def remove_https_block(content, enable_https):
    """移除模板中的 HTTPS server 块（#HTTPS_SERVER_START# 到 #HTTPS_SERVER_END#）。

    如果 enable_https=0，移除整个 HTTPS 块和标记行。
    如果 enable_https=1，保留内容但移除标记行。
    """
    start_marker = "#HTTPS_SERVER_START#"
    end_marker = "#HTTPS_SERVER_END#"

    start_idx = content.find(start_marker)
    end_idx = content.find(end_marker)

    if start_idx == -1 or end_idx == -1:
        return content

    if enable_https == 0:
        return content[:start_idx] + content[end_idx + len(end_marker):]
    else:
        https_block = content[start_idx:end_idx + len(end_marker)]
        https_content = https_block.replace(start_marker, "").replace(end_marker, "").strip()
        return content[:start_idx] + "\n" + https_content + "\n" + content[end_idx + len(end_marker):]


def validate_site_config_https(content, enable_https, logger=None):
    """验证 site.conf 中 HTTPS 配置的一致性。

    enable_https=0 时，不应出现 SSL 相关内容。
    enable_https=1 时，证书路径应为绝对路径。
    """
    from runtime.wnmp_log import log_error

    ssl_keywords = ["listen 443 ssl", "ssl_certificate", "ssl_certificate_key", "server.crt", "server.key"]

    if enable_https == 0:
        found_ssl = []
        for keyword in ssl_keywords:
            if keyword in content:
                found_ssl.append(keyword)

        if found_ssl:
            if logger:
                log_error(logger, "Config validation failed: ENABLE_HTTPS=0 but SSL content found: {}".format(
                    ", ".join(found_ssl)))
            return False, found_ssl
        return True, None

    else:
        cert_path = re.search(r'ssl_certificate\s+([^;]+);', content)
        key_path = re.search(r'ssl_certificate_key\s+([^;]+);', content)

        if cert_path:
            path = cert_path.group(1).strip()
            if path.startswith("{{") or path.startswith("./") or (len(path) > 1 and path[1] != ":"):
                if logger:
                    log_error(logger, "Config validation failed: CERT_PATH is not absolute: " + path)
                return False, ["CERT_PATH not absolute: " + path]

        if key_path:
            path = key_path.group(1).strip()
            if path.startswith("{{") or path.startswith("./") or (len(path) > 1 and path[1] != ":"):
                if logger:
                    log_error(logger, "Config validation failed: KEY_PATH is not absolute: " + path)
                return False, ["KEY_PATH not absolute: " + path]

        return True, None


def generate_site_config(root_dir, cfg, logger=None):
    """Generate config/nginx/site.conf from template.

    首次初始化时：文件不存在才生成；文件已存在则跳过并记录日志。
    """
    from runtime.wnmp_path import resolve_path, to_forward_slash
    from runtime import wnmp_config
    from runtime.wnmp_log import log_error

    output_path = os.path.join(root_dir, "config", "nginx", "site.conf")
    # 已存在的用户配置不得被覆盖
    if os.path.isfile(output_path):
        if logger:
            from runtime.wnmp_log import log_info
            log_info(logger, "配置文件已存在，跳过生成: " + output_path)
        return True, output_path

    web_root_raw = wnmp_config.get(cfg, "WEB_ROOT")
    web_root = to_forward_slash(resolve_path(root_dir, web_root_raw))
    config_dir = to_forward_slash(os.path.join(root_dir, "config"))
    php_cgi_host = wnmp_config.get(cfg, "PHP_CGI_HOST")
    php_cgi_port = wnmp_config.get(cfg, "PHP_CGI_PORT")
    http_port = wnmp_config.get_int(cfg, "HTTP_PORT", 80)
    https_port = wnmp_config.get_int(cfg, "HTTPS_PORT", 443)
    enable_https = wnmp_config.get_int(cfg, "ENABLE_HTTPS", 0)

    template = read_template(root_dir, "nginx/site.conf.template")
    if template is None:
        return False, "Site config template not found"

    cert_path = to_forward_slash(os.path.join(root_dir, "config", "certs", "server.crt"))
    key_path = to_forward_slash(os.path.join(root_dir, "config", "certs", "server.key"))

    variables = {
        "WEB_ROOT": web_root,
        "WEB_ROOT_POSIX": web_root,
        "CONFIG_DIR": config_dir,
        "PHP_CGI_HOST": php_cgi_host,
        "PHP_CGI_PORT": php_cgi_port,
        "HTTP_PORT": str(http_port),
        "HTTPS_PORT": str(https_port),
        "ENABLE_HTTPS": str(enable_https),
        "CERT_PATH": cert_path,
        "KEY_PATH": key_path,
    }

    content = replace_variables(template, variables)

    content = remove_https_block(content, enable_https)

    ok, _ = validate_no_placeholders("site.conf", content, None)
    if not ok:
        return False, "site.conf has unexpanded placeholders"

    ok, errors = validate_site_config_https(content, enable_https, None)
    if not ok:
        return False, "site.conf HTTPS validation failed: " + ", ".join(errors)

    output_path = os.path.join(root_dir, "config", "nginx", "site.conf")
    write_config(output_path, content)
    return True, output_path


def _append_user_config(output_path, user_config_path, logger=None):
    """将用户自定义配置追加到生成的配置文件末尾。

    如果用户配置文件存在，读取并追加到生成文件。
    """
    if not os.path.isfile(user_config_path):
        return True

    try:
        with open(user_config_path, "r", encoding="utf-8") as f:
            user_content = f.read().strip()
        if user_content:
            with open(output_path, "a", encoding="utf-8") as f:
                f.write("\n\n; --- User custom configuration (from {}) ---\n".format(
                    os.path.basename(user_config_path)))
                f.write(user_content)
                f.write("\n")
            if logger:
                from runtime.wnmp_log import log_info
                log_info(logger, "Appended user config: " + user_config_path)
        return True
    except Exception as e:
        if logger:
            from runtime.wnmp_log import log_warn
            log_warn(logger, "Failed to append user config {}: {}".format(user_config_path, str(e)))
        return False


def generate_php_config(root_dir, cfg, logger=None):
    """Generate config/php/php.ini from template, append php.user.ini if exists.

    首次初始化时：文件不存在才生成；文件已存在则跳过并记录日志。
    """
    from runtime.wnmp_path import to_forward_slash
    from runtime import wnmp_config

    output_path = os.path.join(root_dir, "config", "php", "php.ini")
    # 已存在的用户配置不得被覆盖
    if os.path.isfile(output_path):
        if logger:
            from runtime.wnmp_log import log_info
            log_info(logger, "配置文件已存在，跳过生成: " + output_path)
        return True, output_path

    php_ext_dir = to_forward_slash(os.path.join(root_dir, "bin", "php", "ext"))
    logs_dir = to_forward_slash(os.path.join(root_dir, "logs"))
    mysql_host = wnmp_config.get(cfg, "MYSQL_HOST")
    mysql_port = wnmp_config.get(cfg, "MYSQL_PORT")

    template = read_template(root_dir, "php/php.ini.template")
    if template is None:
        return False, "PHP config template not found"

    variables = {
        "PHP_EXT_DIR": php_ext_dir,
        "LOGS_DIR": logs_dir,
        "MYSQL_HOST": mysql_host,
        "MYSQL_PORT": mysql_port,
    }

    content = replace_variables(template, variables)
    output_path = os.path.join(root_dir, "config", "php", "php.ini")
    write_config(output_path, content)

    # 追加用户自定义 PHP 配置
    user_config_path = os.path.join(root_dir, "config", "php", "php.user.ini")
    _append_user_config(output_path, user_config_path, logger)

    ok, _ = validate_no_placeholders(output_path, content)
    if not ok:
        return False, "php.ini has unexpanded placeholders"
    return True, output_path


def generate_mysql_config(root_dir, cfg, logger=None):
    """Generate config/mysql/my.ini from template, append my.user.ini if exists.

    首次初始化时：文件不存在才生成；文件已存在则跳过并记录日志。
    """
    from runtime.wnmp_path import resolve_path, to_forward_slash
    from runtime import wnmp_config

    output_path = os.path.join(root_dir, "config", "mysql", "my.ini")
    # 已存在的用户配置不得被覆盖
    if os.path.isfile(output_path):
        if logger:
            from runtime.wnmp_log import log_info
            log_info(logger, "配置文件已存在，跳过生成: " + output_path)
        return True, output_path

    bin_dir = to_forward_slash(os.path.join(root_dir, "bin"))
    mysql_basedir = to_forward_slash(os.path.join(root_dir, "bin", "mysql"))
    mysql_data_dir = to_forward_slash(resolve_path(root_dir, wnmp_config.get(cfg, "MYSQL_DATA_DIR")))
    tmp_dir = to_forward_slash(os.path.join(root_dir, "tmp"))
    logs_dir = to_forward_slash(os.path.join(root_dir, "logs"))
    mysql_host = wnmp_config.get(cfg, "MYSQL_HOST")
    mysql_port = wnmp_config.get(cfg, "MYSQL_PORT")

    template = read_template(root_dir, "mysql/my.ini.template")
    if template is None:
        return False, "MySQL config template not found"

    variables = {
        "BIN_DIR": bin_dir,
        "MYSQL_BASEDIR": mysql_basedir,
        "MYSQL_DATA_DIR": mysql_data_dir,
        "MYSQL_DATADIR": mysql_data_dir,
        "TMP_DIR": tmp_dir,
        "LOGS_DIR": logs_dir,
        "MYSQL_HOST": mysql_host,
        "MYSQL_PORT": mysql_port,
    }

    content = replace_variables(template, variables)
    output_path = os.path.join(root_dir, "config", "mysql", "my.ini")
    write_config(output_path, content)

    # 追加用户自定义 MySQL 配置
    user_config_path = os.path.join(root_dir, "config", "mysql", "my.user.ini")
    _append_user_config(output_path, user_config_path, logger)

    ok, _ = validate_no_placeholders(output_path, content)
    if not ok:
        return False, "my.ini has unexpanded placeholders"
    return True, output_path


def generate_php_cgi_config(root_dir, cfg, logger=None):
    """Generate config/php/php-cgi.ini from template.

    php-cgi.ini 保存 PHP-CGI 运行参数（host/port/children），与 php.ini 分离。
    php.ini 控制 PHP 运行时行为，php-cgi.ini 控制 PHP-CGI 进程启动参数。
    首次初始化时：文件不存在才生成；文件已存在则跳过并记录日志。
    """
    from runtime import wnmp_config

    output_path = os.path.join(root_dir, "config", "php", "php-cgi.ini")
    # 已存在的用户配置不得被覆盖
    if os.path.isfile(output_path):
        if logger:
            from runtime.wnmp_log import log_info
            log_info(logger, "配置文件已存在，跳过生成: " + output_path)
        return True, output_path

    php_cgi_host = wnmp_config.get(cfg, "PHP_CGI_HOST", "127.0.0.1")
    php_cgi_port = wnmp_config.get(cfg, "PHP_CGI_PORT", "9000")
    php_cgi_children = wnmp_config.get(cfg, "PHP_CGI_CHILDREN", "5")

    content = "; PHP-CGI 运行配置（与 php.ini 分离）\n"
    content += "; php.ini 控制 PHP 运行时行为，php-cgi.ini 控制 PHP-CGI 进程启动参数\n"
    content += "; 修改后需重启 PHP-CGI 组件生效\n"
    content += "; 此文件由首次初始化从 runtime.ini 默认值生成，后续由用户维护\n"
    content += "\n"
    content += "[php-cgi]\n"
    content += "host={}\n".format(php_cgi_host)
    content += "port={}\n".format(php_cgi_port)
    content += "children={}\n".format(php_cgi_children)
    content += "\n"

    write_config(output_path, content)
    if logger:
        from runtime.wnmp_log import log_info
        log_info(logger, "Generated PHP-CGI runtime config: " + output_path)
    return True, output_path


def generate_all_configs(root_dir, cfg, logger=None):
    """Generate all config files.

    首次初始化时：文件不存在才从模板生成；文件已存在则跳过并记录日志。
    任一配置文件生成失败或包含未替换占位符，立即返回 False。
    """
    from runtime.wnmp_log import log_info, log_error, log_success

    results = []

    ok, result = generate_nginx_config(root_dir, cfg, logger)
    if ok:
        log_info(logger, "Nginx main config: " + result)
        results.append(("nginx.conf", True))
    else:
        log_error(logger, "Failed to generate Nginx config: " + result)
        results.append(("nginx.conf", False))
        return False

    ok, result = generate_site_config(root_dir, cfg, logger)
    if ok:
        log_info(logger, "Nginx site config: " + result)
        results.append(("site.conf", True))
    else:
        log_error(logger, "Failed to generate site config: " + result)
        results.append(("site.conf", False))
        return False

    ok, result = generate_php_config(root_dir, cfg, logger)
    if ok:
        log_info(logger, "PHP config: " + result)
        results.append(("php.ini", True))
    else:
        log_error(logger, "Failed to generate PHP config: " + result)
        results.append(("php.ini", False))
        return False

    ok, result = generate_php_cgi_config(root_dir, cfg, logger)
    if ok:
        log_info(logger, "PHP-CGI runtime config: " + result)
        results.append(("php-cgi.ini", True))
    else:
        log_error(logger, "Failed to generate PHP-CGI config: " + result)
        results.append(("php-cgi.ini", False))
        return False

    ok, result = generate_mysql_config(root_dir, cfg, logger)
    if ok:
        log_info(logger, "MySQL config: " + result)
        results.append(("my.ini", True))
    else:
        log_error(logger, "Failed to generate MySQL config: " + result)
        results.append(("my.ini", False))
        return False

    log_success(logger, "All config files generated successfully")
    return True
