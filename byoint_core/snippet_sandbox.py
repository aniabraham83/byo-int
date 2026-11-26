"""Run custom snippets in an isolated, short-lived child process (see snippet_child.py).

Two modes, chosen by environment variables:

- Remote (used by docker-compose): when SNIPPET_RUNNER_URL is set, snippets are sent to the
  separate snippet_runner container (snippet_runner.py). That container has no app secrets, a
  read-only filesystem, and no network route to MongoDB or Redis. If the runner cannot be
  reached, the snippet fails; it never falls back to running inside the app.
- Local (development outside Docker): the child process runs inside this container.

In both modes the child process:
- starts with an empty environment, so no secrets are passed to it;
- only loads the standard library plus what the snippet is allowed to import;
- has CPU, memory, open-file and file-size limits (Linux), and is killed together with anything
  it started when it runs out of time.

This module only uses the standard library, because the snippet_runner image ships it without
the rest of the app.
"""
import json
import os
import signal
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

_CHILD_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snippet_child.py")

TEMPLATE_TIMEOUT_SECONDS = max(1, int(os.getenv("SNIPPET_TEMPLATE_TIMEOUT_SECONDS", "120")))
ENRICHMENT_TIMEOUT_SECONDS = max(1, int(os.getenv("SNIPPET_ENRICHMENT_TIMEOUT_SECONDS", "15")))
MAX_MEMORY_MB = max(0, int(os.getenv("SNIPPET_MAX_MEMORY_MB", "1024")))
MAX_RESPONSE_BYTES = 50 * 1024 * 1024

RUNNER_URL = os.getenv("SNIPPET_RUNNER_URL", "").strip().rstrip("/")
_RUNNER_TOKEN = os.getenv("SNIPPET_RUNNER_TOKEN", "").strip()
# Extra time allowed for the HTTP round trip on top of the snippet's own timeout.
_RUNNER_HTTP_MARGIN_SECONDS = 15

MODES = ("template", "enrichment")

# Only non-secret settings that outbound HTTP may need are passed to the child.
_PASSTHROUGH_ENV = (
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy",
    "REQUESTS_CA_BUNDLE", "SSL_CERT_FILE", "SSL_CERT_DIR", "TZ",
)

_STAGE_PREFIXES = {
    "exec": "Snippet execution error: ",
    "call": "Snippet callable error: ",
}


def protect_process_environ():
    """Mark this process non-dumpable (Linux) so same-user processes cannot read its memory or
    /proc/<pid>/environ. Without this, a snippet that escapes the allowlists could read secrets
    from its parent process. Forked children (gunicorn workers) inherit the setting; exec'd
    snippet processes do not. Safe to call more than once; a no-op on other platforms.
    """
    if not sys.platform.startswith("linux"):
        return False
    try:
        import ctypes
        pr_set_dumpable = 4
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(pr_set_dumpable, 0, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "prctl(PR_SET_DUMPABLE) failed")
        return True
    except Exception as e:
        print(f"Warning: could not protect process environment from snippets: {e}")
        return False


class SnippetError(Exception):
    """A snippet failed, timed out, or hit a resource limit. str(e) is a user-facing message."""

    def __init__(self, message, stage="exec", output=""):
        self.raw_message = str(message)
        super().__init__(_STAGE_PREFIXES.get(stage, "") + self.raw_message)
        self.stage = stage
        self.output = output or ""  # anything the snippet printed before failing


def run_snippet(mode, code, inputs, allowed_imports, allowed_builtins, timeout_seconds):
    """Run a snippet in isolation and return its response.

    mode is "template" or "enrichment". Raises SnippetError on any failure.
    The response always has "output" (anything the snippet printed); a template response has
    "result_list" and "dp_log", and an enrichment response has "has_result" and "result".
    """
    job = {
        "mode": mode,
        "code": code,
        "inputs": inputs or {},
        "allowed_imports": sorted(allowed_imports or []),
        "allowed_builtins": sorted(allowed_builtins or []),
        "timeout_seconds": max(1, int(timeout_seconds)),
    }
    if RUNNER_URL:
        return _run_remote(job)
    return run_local(job)


def _raise_for_failed_response(response):
    if not response.get("ok"):
        raise SnippetError(
            response.get("error") or "Unknown snippet error.",
            stage=response.get("stage") or "exec",
            output=response.get("output"),
        )
    return response


# --- Remote mode: send the job to the snippet_runner container -------------------------------

# Talk to the runner directly, even if HTTP(S)_PROXY is set for outbound traffic.
_RUNNER_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_RUNNER_HTTP_ERRORS = {
    400: "Snippet runner rejected the request as invalid.",
    401: "Snippet runner rejected the request. Check that SNIPPET_RUNNER_TOKEN matches on the app and the runner.",
    413: "Snippet request is too large for the snippet runner.",
    503: "Snippet runner is busy. Try again later, or raise SNIPPET_RUNNER_MAX_CONCURRENCY.",
}


def _run_remote(job):
    if not _RUNNER_TOKEN:
        raise SnippetError("SNIPPET_RUNNER_URL is set but SNIPPET_RUNNER_TOKEN is not.", stage="runner")
    try:
        body = json.dumps(job, default=str).encode("utf-8")
    except (TypeError, ValueError) as e:
        raise SnippetError(f"Snippet inputs could not be serialized: {e}", stage="input")

    request = urllib.request.Request(
        f"{RUNNER_URL}/run",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {_RUNNER_TOKEN}"},
    )
    try:
        with _RUNNER_OPENER.open(request, timeout=job["timeout_seconds"] + _RUNNER_HTTP_MARGIN_SECONDS) as resp:
            raw = resp.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as e:
        raise SnippetError(_RUNNER_HTTP_ERRORS.get(e.code, f"Snippet runner returned HTTP {e.code}."), stage="runner")
    except (urllib.error.URLError, OSError) as e:
        reason = getattr(e, "reason", e)
        raise SnippetError(f"Snippet runner is unavailable ({reason}).", stage="runner")

    if len(raw) > MAX_RESPONSE_BYTES:
        raise SnippetError(f"Snippet output exceeded {MAX_RESPONSE_BYTES // (1024 * 1024)} MB.", stage="result")
    try:
        response = json.loads(raw.decode("utf-8"))
    except ValueError:
        raise SnippetError("Snippet runner returned invalid output.", stage="runner")
    if not isinstance(response, dict):
        raise SnippetError("Snippet runner returned invalid output.", stage="runner")
    return _raise_for_failed_response(response)


# --- Local mode: run the child process in this container --------------------------------------

def _child_env(workdir):
    env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "LANG": "C.UTF-8",
        "HOME": workdir,
        "TMPDIR": workdir,
    }
    if os.name == "nt":
        # Windows needs SYSTEMROOT for networking/crypto to work in the child.
        env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", r"C:\Windows")
    for key in _PASSTHROUGH_ENV:
        if key in os.environ:
            env[key] = os.environ[key]
    return env


def _kill(proc):
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except (ProcessLookupError, PermissionError, OSError):
        pass


def _describe_exit(returncode, stderr):
    if os.name == "posix" and returncode < 0:
        sig = -returncode
        if sig == signal.SIGXCPU:
            return "Snippet exceeded its CPU time limit and was stopped."
        if sig == signal.SIGKILL:
            return "Snippet was killed (it may have exceeded its memory limit)."
        return f"Snippet process was terminated by signal {sig}."
    detail = (stderr or b"").decode("utf-8", "replace").strip()[-500:]
    return f"Snippet process exited with code {returncode}." + (f" {detail}" if detail else "")


def run_local(job):
    """Run a job (as built by run_snippet) in a child process in this container.

    Used directly in local mode and by snippet_runner.py inside the runner container.
    """
    mode = job.get("mode")
    if mode not in MODES:
        raise SnippetError(f"Unknown snippet mode: {mode!r}.", stage="input")
    if not isinstance(job.get("code"), str) or not job["code"].strip():
        raise SnippetError("Snippet code is required.", stage="input")
    timeout_seconds = max(1, int(job.get("timeout_seconds") or TEMPLATE_TIMEOUT_SECONDS))

    request = {
        "mode": mode,
        "code": job["code"],
        "inputs": job.get("inputs") or {},
        "allowed_imports": list(job.get("allowed_imports") or []),
        "allowed_builtins": list(job.get("allowed_builtins") or []),
        "cpu_seconds": timeout_seconds,
        "max_memory_mb": MAX_MEMORY_MB,
    }
    try:
        payload = json.dumps(request, default=str).encode("utf-8")
    except (TypeError, ValueError) as e:
        raise SnippetError(f"Snippet inputs could not be serialized: {e}", stage="input")

    with tempfile.TemporaryDirectory(prefix="byoint-snippet-") as workdir:
        popen_kwargs = {
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "cwd": workdir,
            "env": _child_env(workdir),
        }
        if os.name == "posix":
            popen_kwargs["start_new_session"] = True  # own process group, so we can kill it all

        proc = subprocess.Popen([sys.executable, "-I", _CHILD_SCRIPT], **popen_kwargs)
        try:
            stdout, stderr = proc.communicate(payload, timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            _kill(proc)
            proc.communicate()
            raise SnippetError(f"Snippet timed out after {timeout_seconds} seconds and was stopped.", stage="timeout")
        finally:
            # Also stop anything the snippet may have started in the background.
            if os.name == "posix":
                _kill(proc)

    if len(stdout) > MAX_RESPONSE_BYTES:
        raise SnippetError(f"Snippet output exceeded {MAX_RESPONSE_BYTES // (1024 * 1024)} MB.", stage="result")
    if proc.returncode != 0 or not stdout:
        raise SnippetError(_describe_exit(proc.returncode, stderr), stage="process")

    try:
        response = json.loads(stdout.decode("utf-8"))
    except ValueError:
        raise SnippetError("Snippet process returned invalid output.", stage="process")
    return _raise_for_failed_response(response)
