# -*- coding: utf-8 -*-
"""
WNMP Stdio - Safe UTF-8 stdio configuration.

Provides configure_stdio_utf8() to safely configure stdout/stderr
encoding without causing "I/O operation on closed file" errors.
"""
import sys


def configure_stdio_utf8():
    """Safely configure stdout/stderr to use UTF-8 encoding.

    Uses reconfigure() when available (Python 3.7+), which is safe
    even when stdout/stderr have been redirected or wrapped.
    Falls back gracefully if stdout/stderr are closed or unavailable.
    """
    for stream in (sys.stdout, sys.stderr):
        if stream is None:
            continue
        try:
            # reconfigure is the safest way (Python 3.7+)
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, io.UnsupportedOperation, ValueError, OSError):
            # reconfigure not available or stream doesn't support it
            # Don't try to re-wrap the buffer - that causes I/O errors
            pass


# Need io for UnsupportedOperation
import io
