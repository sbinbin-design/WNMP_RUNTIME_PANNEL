"""
WNMP Log Module - logging with UTF-8 encoding
"""
import os
import sys
import logging
from datetime import datetime


def setup_logging(root_dir, log_file_name="runtime.log", safe_mode=False, autostart_mode=False):
    """Setup logging to file and optionally to console.

    Args:
        root_dir: tool root directory
        log_file_name: log file name under logs/runtime/
        safe_mode: if True, console output is English summary only
        autostart_mode: if True, use autostart.log and no console output

    Returns:
        logger instance
    """
    log_dir = os.path.join(root_dir, "logs", "runtime")
    os.makedirs(log_dir, exist_ok=True)

    # 自启动模式使用 autostart.log
    if autostart_mode:
        log_file_name = "autostart.log"

    log_path = os.path.join(log_dir, log_file_name)

    logger = logging.getLogger("wnmp")
    logger.setLevel(logging.DEBUG)

    # Remove existing handlers
    logger.handlers.clear()

    # File handler - always writes full details in Chinese
    try:
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fmt = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s",
                                datefmt="%Y-%m-%d %H:%M:%S")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception:
        pass

    # Console handler - English summary only in safe mode, no console in autostart mode
    if not safe_mode and not autostart_mode:
        try:
            ch = logging.StreamHandler(sys.stdout)
            ch.setLevel(logging.INFO)
            fmt = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s",
                                    datefmt="%Y-%m-%d %H:%M:%S")
            ch.setFormatter(fmt)
            logger.addHandler(ch)
        except Exception:
            pass

    return logger


def log_info(logger, msg):
    if logger:
        logger.info(msg)


def log_warn(logger, msg):
    if logger:
        logger.warning(msg)


def log_error(logger, msg):
    if logger:
        logger.error(msg)


def log_success(logger, msg):
    if logger:
        logger.info(msg)
