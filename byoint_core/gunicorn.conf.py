# Gunicorn loads ./gunicorn.conf.py automatically (the app runs from /app/byoint_core).
# Command-line options in the Dockerfile still take precedence over anything set here.
import ctypes
import sys


def _protect_master_environ():
    """Mark the gunicorn master non-dumpable so snippet processes (same user) cannot read its
    /proc/<pid>/environ, which holds the app's secrets. Workers forked from it inherit this.
    See snippet_sandbox.protect_process_environ for details.
    """
    if not sys.platform.startswith("linux"):
        return
    try:
        if ctypes.CDLL(None, use_errno=True).prctl(4, 0, 0, 0, 0) != 0:  # PR_SET_DUMPABLE = 4
            print("Warning: prctl(PR_SET_DUMPABLE) failed for gunicorn master")
    except Exception as e:
        print(f"Warning: could not protect gunicorn master environment: {e}")


_protect_master_environ()
