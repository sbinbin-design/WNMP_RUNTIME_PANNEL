"""
WNMP Path Module - resolve relative/absolute paths to absolute paths
"""
import os


def resolve_path(root_dir, raw_path):
    """Resolve a path value from runtime.ini to an absolute path.

    Handles:
    - ./www, www -> root_dir + www
    - ./data/mysql -> root_dir + data/mysql
    - D:/xxx/www -> absolute path as-is
    - /xxx/www -> absolute path as-is
    """
    if not raw_path:
        return root_dir

    # Normalize backslashes to forward slashes for consistency
    normalized = raw_path.replace("\\", "/")

    # If already absolute (starts with drive letter or /)
    if os.path.isabs(normalized) or (len(normalized) >= 2 and normalized[1] == ":"):
        return os.path.normpath(raw_path)

    # Relative path: resolve against root_dir
    abs_path = os.path.normpath(os.path.join(root_dir, normalized))
    return abs_path


def to_forward_slash(path):
    """Convert path to forward slashes for Nginx config."""
    return path.replace("\\", "/")


def is_default_web_root(root_dir, web_root):
    """Check if web_root resolves to the default www directory under root_dir."""
    resolved = resolve_path(root_dir, web_root)
    default_www = os.path.normpath(os.path.join(root_dir, "www"))
    return os.path.normpath(resolved) == default_www
