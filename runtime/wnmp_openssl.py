# -*- coding: utf-8 -*-
"""
WNMP OpenSSL Module - HTTPS certificate generation and management
Uses Python standard library only, depends on bin/openssl/openssl.exe
"""
import os
import subprocess


def get_cert_paths(root_dir):
    """获取证书文件路径。"""
    cert_dir = os.path.join(root_dir, "config", "certs")
    cert_path = os.path.join(cert_dir, "server.crt")
    key_path = os.path.join(cert_dir, "server.key")
    return cert_dir, cert_path, key_path


def get_openssl_cnf_path(root_dir):
    """获取 openssl.cnf 配置文件路径（位于 tmp 目录）。"""
    return os.path.join(root_dir, "tmp", "openssl-selfsigned.cnf")


def generate_openssl_cnf(root_dir, logger=None):
    """生成 openssl.cnf 配置文件到 tmp 目录。

    Windows 上 OpenSSL 需要此配置文件才能正常生成证书。
    """
    cnf_path = get_openssl_cnf_path(root_dir)
    os.makedirs(os.path.dirname(cnf_path), exist_ok=True)

    cnf_content = """[ req ]
default_bits            = 2048
distinguished_name      = req_distinguished_name
prompt                = no
string_mask           = utf8only
x509_extensions       = v3_ca

[ req_distinguished_name ]
countryName                     = CN
stateOrProvinceName             = State
localityName                    = Local
0.organizationName             = WNMP Runtime
organizationalUnitName           = Runtime
commonName                      = localhost
emailAddress                   =

[ v3_ca ]
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always,issuer
basicConstraints = critical, CA:true
keyUsage = critical, digitalSignature, keyEncipherment
crlDistributionPoints = URI:http://localhost/crl.pem
"""

    with open(cnf_path, "w", encoding="utf-8") as f:
        f.write(cnf_content)

    return cnf_path


def is_cert_valid(cert_path, key_path):
    """检查证书文件是否存在且有效（非空）。

    返回 True 表示有效，False 表示无效或缺失。
    """
    if not os.path.isfile(cert_path) or not os.path.isfile(key_path):
        return False

    cert_size = os.path.getsize(cert_path)
    key_size = os.path.getsize(key_path)

    return cert_size > 0 and key_size > 0


def get_cert_status(root_dir, logger=None):
    """获取证书状态。

    返回 dict: {
        "cert_exists": bool,
        "key_exists": bool,
        "cert_valid": bool,
        "cert_path": str,
        "key_path": str,
        "cert_size": int,
        "key_size": int
    }
    """
    _, cert_path, key_path = get_cert_paths(root_dir)

    result = {
        "cert_exists": os.path.isfile(cert_path),
        "key_exists": os.path.isfile(key_path),
        "cert_valid": is_cert_valid(cert_path, key_path),
        "cert_path": cert_path,
        "key_path": key_path,
        "cert_size": os.path.getsize(cert_path) if os.path.isfile(cert_path) else 0,
        "key_size": os.path.getsize(key_path) if os.path.isfile(key_path) else 0,
    }
    return result


def ensure_self_signed_cert(root_dir, cfg, logger, force=False):
    """检查并生成自签名证书。

    参数:
        root_dir: 工具根目录
        cfg: 配置字典
        logger: 日志记录器
        force: 是否强制重新生成

    返回: (True, "certificate info") 或 (False, "error message")
    """
    from runtime.wnmp_log import log_info, log_warn, log_error

    openssl_exe = os.path.join(root_dir, "bin", "openssl", "openssl.exe")
    cert_dir, cert_path, key_path = get_cert_paths(root_dir)

    if not os.path.isfile(openssl_exe):
        log_warn(logger, "OpenSSL not found: bin/openssl/openssl.exe")
        return False, "OpenSSL not found"

    if not force and is_cert_valid(cert_path, key_path):
        log_info(logger, "Self-signed certificate already exists, skipping generation")
        return True, "Certificate exists: " + cert_path

    if force:
        log_info(logger, "Force regenerating certificate...")
        if os.path.isfile(cert_path):
            try:
                os.remove(cert_path)
            except Exception:
                pass
        if os.path.isfile(key_path):
            try:
                os.remove(key_path)
            except Exception:
                pass

    os.makedirs(cert_dir, exist_ok=True)

    # 生成 openssl.cnf 配置文件
    cnf_path = generate_openssl_cnf(root_dir, logger)
    log_info(logger, "Using OpenSSL config: " + cnf_path)

    log_info(logger, "Generating self-signed certificate...")

    # 设置环境变量 OPENSSL_CONF 并使用 -config 参数
    env = os.environ.copy()
    env["OPENSSL_CONF"] = cnf_path

    cmd = [
        openssl_exe,
        "req",
        "-x509",
        "-nodes",
        "-days", "3650",
        "-newkey", "rsa:2048",
        "-keyout", key_path,
        "-out", cert_path,
        "-config", cnf_path,
        "-subj", "/C=CN/ST=Local/L=Local/O=WNMP Runtime/OU=Runtime/CN=localhost",
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=30,
            env=env
        )

        if result.returncode == 0 and is_cert_valid(cert_path, key_path):
            log_info(logger, "Self-signed certificate generated successfully")
            log_info(logger, "  Certificate: " + cert_path)
            log_info(logger, "  Key: " + key_path)
            return True, "Certificate generated: " + cert_path
        else:
            error_msg = result.stderr.strip() if result.stderr else "Unknown error"
            log_error(logger, "Certificate generation failed: " + error_msg)
            return False, error_msg

    except subprocess.TimeoutExpired:
        log_error(logger, "Certificate generation timeout (30s)")
        return False, "Generation timeout"
    except Exception as e:
        log_error(logger, "Certificate generation error: " + str(e))
        return False, str(e)


def ensure_https_cert(root_dir, cfg, logger):
    """确保 HTTPS 证书存在（ENABLE_HTTPS=1 时调用）。

    如果证书不存在或 openssl.exe 不可用，返回 False 并回退 HTTP。
    """
    from runtime.wnmp_log import log_info, log_warn, log_error

    cert_dir, cert_path, key_path = get_cert_paths(root_dir)
    openssl_exe = os.path.join(root_dir, "bin", "openssl", "openssl.exe")

    if not os.path.isfile(openssl_exe):
        log_warn(logger, "OpenSSL not found, cannot generate HTTPS certificate")
        return False

    if is_cert_valid(cert_path, key_path):
        log_info(logger, "HTTPS certificate already exists")
        return True

    log_info(logger, "HTTPS certificate not found, generating...")
    ok, msg = ensure_self_signed_cert(root_dir, cfg, logger, force=False)
    return ok


def cmd_cert_status(root_dir, cfg, logger):
    """cert --status 命令处理。"""
    from runtime.wnmp_log import log_info
    from runtime.wnmp_config import is_effective_nginx_https_enabled

    status = get_cert_status(root_dir, logger)
    enable_https = is_effective_nginx_https_enabled(root_dir, cfg)
    auto_gen_cert = cfg.get("AUTO_GENERATE_CERT", "1")

    print("=" * 50)
    print("  WNMP Certificate Status")
    print("=" * 50)
    print()
    print("Certificate Files:")
    print("  server.crt: {} (size: {} bytes)".format(
        "EXISTS" if status["cert_exists"] else "NOT FOUND",
        status["cert_size"]
    ))
    print("  server.key: {} (size: {} bytes)".format(
        "EXISTS" if status["key_exists"] else "NOT FOUND",
        status["key_size"]
    ))
    print("  Valid: {}".format("YES" if status["cert_valid"] else "NO"))
    print()
    print("Certificate Path:")
    print("  {}".format(status["cert_path"]))
    print()
    print("Configuration:")
    print("  HTTPS enabled:      {}".format("YES" if enable_https else "NO"))
    print("  AUTO_GENERATE_CERT:  {}".format(auto_gen_cert))
    print()

    if enable_https:
        print("HTTPS Status:")
        print("  HTTPS is ENABLED (detected from Nginx config ssl listen)")
        print("  Nginx will use this certificate for HTTPS server")
    else:
        print("HTTPS Status:")
        print("  HTTPS is NOT enabled (no ssl listen in Nginx config)")
        print("  Certificate is pre-generated for future use")

    if status["cert_valid"]:
        print()
        print("Certificate is ready for use.")

    return 0


def cmd_cert_generate(root_dir, cfg, logger, force=False):
    """cert [--force] 命令处理。"""
    from runtime.wnmp_log import log_info, log_error

    log_info(logger, "=== WNMP Certificate Generation ===")

    ok, msg = ensure_self_signed_cert(root_dir, cfg, logger, force=force)

    if ok:
        print("Certificate generated successfully: " + msg)
        print("Path: " + get_cert_paths(root_dir)[1])
        return 0
    else:
        log_error(logger, "Certificate generation failed: " + msg)
        print("ERROR: Certificate generation failed: " + msg)
        return 1
