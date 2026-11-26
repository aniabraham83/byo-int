"""Child process that runs one custom snippet for snippet_sandbox.py.

Started as `python -I snippet_child.py` with an empty environment. It reads one JSON request
from stdin and writes one JSON response to stdout. It must only import the standard library,
so it never loads app modules, database clients or secrets.

This is NOT a security boundary on its own: the restricted builtins and import guard can be
escaped. What it adds is process isolation: no app secrets in the environment, no access to
app objects, resource limits, and a parent that can kill it on timeout.
"""
import builtins
import io
import json
import sys

try:
    import resource
except ImportError:  # Windows: limits are not available; the parent's timeout still applies.
    resource = None


# Never hand these to a snippet, even if the configured allowlist names them.
_DENIED_BUILTINS = {
    "eval", "exec", "compile", "open", "input", "breakpoint", "globals", "locals", "vars",
    "getattr", "setattr", "delattr", "memoryview", "help", "exit", "quit", "__import__",
}
_CALLABLE_NAMES = ("run", "execute", "datapull", "main")
_MAX_CAPTURED_OUTPUT = 20000


class _StageError(Exception):
    def __init__(self, stage, message):
        super().__init__(message)
        self.stage = stage


def _set_limit(which, soft, hard=None):
    hard = soft if hard is None else hard
    try:
        _cur_soft, cur_hard = resource.getrlimit(which)
        if cur_hard != resource.RLIM_INFINITY:
            hard = min(hard, cur_hard)
            soft = min(soft, hard)
        resource.setrlimit(which, (soft, hard))
    except (ValueError, OSError):
        pass


def _apply_limits(request):
    if resource is None:
        return
    cpu_seconds = max(1, int(request.get("cpu_seconds") or 60))
    _set_limit(resource.RLIMIT_CPU, cpu_seconds, cpu_seconds + 1)
    memory_mb = int(request.get("max_memory_mb") or 0)
    if memory_mb > 0:
        _set_limit(resource.RLIMIT_AS, memory_mb * 1024 * 1024)
    _set_limit(resource.RLIMIT_NOFILE, 64)
    _set_limit(resource.RLIMIT_FSIZE, 16 * 1024 * 1024)
    _set_limit(resource.RLIMIT_CORE, 0)


def _build_globals(allowed_imports, allowed_builtins):
    allowed_modules = set(allowed_imports or [])

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        root_module = str(name or "").split(".")[0]
        if root_module not in allowed_modules:
            raise ImportError(
                f"Import of module '{root_module}' is not allowed. "
                f"Allowed imports: {sorted(allowed_modules)}"
            )
        return __import__(name, globals, locals, fromlist, level)

    safe_builtins = {
        name: getattr(builtins, name)
        for name in (allowed_builtins or [])
        if isinstance(name, str) and name not in _DENIED_BUILTINS and hasattr(builtins, name)
    }
    safe_builtins["__import__"] = guarded_import
    return {"__builtins__": safe_builtins}


def _describe(exc):
    return f"{type(exc).__name__}: {exc}"


def _run_template(request, exec_globals):
    kwargs = request.get("inputs") or {}
    exec_locals = {"kwargs": dict(kwargs), "template_args": dict(kwargs)}
    for key, value in kwargs.items():
        if isinstance(key, str) and key.isidentifier():
            exec_locals[key] = value

    try:
        exec(request["code"], exec_globals, exec_locals)
    except BaseException as e:
        raise _StageError("exec", _describe(e))

    snippet_callable = None
    for candidate_name in _CALLABLE_NAMES:
        candidate = exec_locals.get(candidate_name) or exec_globals.get(candidate_name)
        if callable(candidate):
            snippet_callable = candidate
            break
    if snippet_callable is None:
        for name, value in exec_locals.items():
            if callable(value) and not name.startswith("__"):
                snippet_callable = value
                break

    try:
        if snippet_callable is not None:
            snippet_result = snippet_callable(**kwargs)
        elif "result" in exec_locals:
            snippet_result = exec_locals.get("result")
        elif "result_list" in exec_locals:
            snippet_result = {"result_list": exec_locals.get("result_list")}
        else:
            raise _StageError(
                "result",
                "Snippet must define a callable (run/execute/datapull/main), set `result`, or set `result_list`",
            )
    except _StageError:
        raise
    except BaseException as e:
        raise _StageError("call", _describe(e))

    dp_log = ""
    result_payload = snippet_result
    if isinstance(snippet_result, tuple) and len(snippet_result) == 2:
        result_payload, dp_log = snippet_result

    result_list = None
    if isinstance(result_payload, dict) and isinstance(result_payload.get("result_list"), list):
        result_list = result_payload.get("result_list")
    elif isinstance(result_payload, list):
        result_list = result_payload
    elif isinstance(exec_locals.get("result_list"), list):
        result_list = exec_locals.get("result_list")

    if result_list is None:
        raise _StageError("result", "Snippet must produce 'result_list' (list)")

    return {"ok": True, "result_list": result_list, "dp_log": str(dp_log or "")}


def _run_enrichment(request, exec_globals):
    exec_locals = dict(request.get("inputs") or {})
    try:
        exec(request["code"], exec_globals, exec_locals)
    except BaseException as e:
        raise _StageError("exec", _describe(e))
    return {"ok": True, "has_result": "result" in exec_locals, "result": exec_locals.get("result")}


_HANDLERS = {"template": _run_template, "enrichment": _run_enrichment}


def main():
    real_stdout = sys.stdout
    captured = io.StringIO()
    try:
        request = json.loads(sys.stdin.read())
        _apply_limits(request)
        handler = _HANDLERS[request.get("mode")]
        exec_globals = _build_globals(request.get("allowed_imports"), request.get("allowed_builtins"))
        sys.stdout = captured
        sys.stderr = captured
        response = handler(request, exec_globals)
    except _StageError as e:
        response = {"ok": False, "stage": e.stage, "error": str(e)}
    except BaseException as e:
        response = {"ok": False, "stage": "exec", "error": _describe(e)}
    finally:
        sys.stdout = real_stdout
        sys.stderr = sys.__stderr__

    response["output"] = captured.getvalue()[-_MAX_CAPTURED_OUTPUT:]
    try:
        text = json.dumps(response, default=str)
    except (TypeError, ValueError) as e:
        text = json.dumps({"ok": False, "stage": "result", "error": f"Snippet result could not be serialized: {e}"})
    real_stdout.write(text)
    real_stdout.flush()


if __name__ == "__main__":
    main()
