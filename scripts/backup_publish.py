"""Publish a complete same-filesystem temporary file without overwriting.

Hard links are preferred. Windows rename and Linux renameat2(NOREPLACE) are
atomic alternatives; unsupported platforms fail closed, never publish partial
bytes or use a racy exists()+replace().
"""
import ctypes
import errno
import os
import sys


def publish(temporary, destination):
    try:
        os.link(temporary, destination)
        return
    except OSError as exc:
        if exc.errno not in (errno.EPERM, errno.EACCES, errno.ENOTSUP, errno.EOPNOTSUPP, errno.ENOSYS):
            raise
    if os.name == 'nt':
        os.rename(temporary, destination)  # Windows refuses an existing target.
        return
    if sys.platform.startswith('linux'):
        libc = ctypes.CDLL(None, use_errno=True)
        rename = getattr(libc, 'renameat2', None)
        if rename is None:
            raise OSError(errno.ENOTSUP, 'Atomic exclusive rename is unavailable')
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        if rename(-100, os.fsencode(temporary), -100, os.fsencode(destination), 1):
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error), str(destination))
        return
    raise OSError(errno.ENOTSUP, 'Atomic exclusive publication is unavailable')
