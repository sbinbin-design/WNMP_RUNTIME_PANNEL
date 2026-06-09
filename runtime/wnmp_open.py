"""
WNMP Open Module - opens browser based on config
"""
import os
import subprocess
import sys


def build_open_url(cfg, root_dir=None):
    """Build the default URL based on actual Nginx listen list.

    优先选择 HTTPS ssl listen 的第一个端口；
    如果没有 HTTPS，则选择 HTTP 第一个端口；
    如果只有 HTTPS，就打开 HTTPS；如果只有 HTTP，就打开 HTTP；
    如果没有 listen 且 fallback，按 fallback 默认端口。
    """
    from runtime import wnmp_config

    if root_dir:
        eff = wnmp_config.get_effective_nginx_listens(root_dir, cfg)
        https_ports = eff["https"]
        http_ports = eff["http"]

        if https_ports:
            # 优先 HTTPS
            url = "https://127.0.0.1"
            if https_ports[0] != 443:
                url += ":" + str(https_ports[0])
        elif http_ports:
            # 只有 HTTP
            url = "http://127.0.0.1"
            if http_ports[0] != 80:
                url += ":" + str(http_ports[0])
        else:
            # 无 listen 且 fallback
            url = "http://127.0.0.1"
    else:
        enable_https = wnmp_config.get_int(cfg, "ENABLE_HTTPS", 0) == 1
        http_port = wnmp_config.get_int(cfg, "HTTP_PORT", 80)
        https_port = wnmp_config.get_int(cfg, "HTTPS_PORT", 443)

        if enable_https:
            url = "https://127.0.0.1"
            if https_port != 443:
                url += ":" + str(https_port)
        else:
            url = "http://127.0.0.1"
            if http_port != 80:
                url += ":" + str(http_port)

    url += "/"
    return url


def open_browser(cfg, root_dir=None):
    """Open browser based on ENABLE_HTTPS and actual port config."""
    url = build_open_url(cfg, root_dir)

    try:
        os.startfile(url)
        print("Opening browser: " + url)
        return 0
    except Exception as e:
        print("Failed to open browser: " + str(e))
        return 1
