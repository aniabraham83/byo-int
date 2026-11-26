"""HTTP service that runs custom snippets for BYO-INT in the isolated snippet_runner container.

The app (flask_app, datapull_worker) sends each snippet here instead of running it itself.
This container holds no app secrets, has a read-only filesystem, and has no network route to
MongoDB or Redis, so a snippet that escapes the Python allowlists has little to reach.

API (all requests need `Authorization: Bearer <SNIPPET_RUNNER_TOKEN>`, except /health):
  POST /run     body: the job built by snippet_sandbox.run_snippet
                200: {"ok": true, ...} or {"ok": false, "stage": ..., "error": ..., "output": ...}
  GET  /health  200: {"status": "ok"}

Standard library only.
"""
import hmac
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import snippet_sandbox

_TOKEN = os.environ.get("SNIPPET_RUNNER_TOKEN", "").strip()
_PORT = int(os.getenv("SNIPPET_RUNNER_PORT", "8080"))
_MAX_TIMEOUT_SECONDS = max(1, int(os.getenv("SNIPPET_RUNNER_MAX_TIMEOUT_SECONDS", "300")))
_MAX_CONCURRENCY = max(1, int(os.getenv("SNIPPET_RUNNER_MAX_CONCURRENCY", "4")))
_MAX_REQUEST_BYTES = max(1, int(os.getenv("SNIPPET_RUNNER_MAX_REQUEST_MB", "20"))) * 1024 * 1024
_QUEUE_WAIT_SECONDS = 30
_MIN_TOKEN_LENGTH = 16

_slots = threading.BoundedSemaphore(_MAX_CONCURRENCY)


def _valid_job(job):
    return (
        isinstance(job, dict)
        and job.get("mode") in snippet_sandbox.MODES
        and isinstance(job.get("code"), str)
        and isinstance(job.get("inputs", {}), dict)
        and isinstance(job.get("allowed_imports", []), list)
        and isinstance(job.get("allowed_builtins", []), list)
    )


class _Handler(BaseHTTPRequestHandler):
    server_version = "byoint-snippet-runner"
    sys_version = ""

    def _send(self, status, payload):
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"status": "ok"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/run":
            self._send(404, {"error": "not found"})
            return

        supplied = self.headers.get("Authorization", "").encode("utf-8")
        if not hmac.compare_digest(supplied, f"Bearer {_TOKEN}".encode("utf-8")):
            self._send(401, {"error": "unauthorized"})
            return

        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._send(400, {"error": "invalid Content-Length"})
            return
        if length <= 0 or length > _MAX_REQUEST_BYTES:
            self._send(413, {"error": "request too large or empty"})
            return

        try:
            job = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._send(400, {"error": "invalid JSON"})
            return
        if not _valid_job(job):
            self._send(400, {"error": "invalid job"})
            return

        try:
            requested_timeout = int(job.get("timeout_seconds") or 60)
        except (TypeError, ValueError):
            requested_timeout = 60
        job["timeout_seconds"] = min(max(1, requested_timeout), _MAX_TIMEOUT_SECONDS)

        if not _slots.acquire(timeout=_QUEUE_WAIT_SECONDS):
            self._send(503, {"error": "busy"})
            return
        try:
            response = snippet_sandbox.run_local(job)
        except snippet_sandbox.SnippetError as e:
            response = {"ok": False, "stage": e.stage, "error": e.raw_message, "output": e.output}
        except Exception as e:  # never let one bad job take the server down
            response = {"ok": False, "stage": "runner", "error": f"Snippet runner error: {type(e).__name__}"}
        finally:
            _slots.release()
        self._send(200, response)

    def log_message(self, fmt, *args):
        # One line per request without bodies, so snippet inputs (which can hold secrets) never reach the log.
        print(f"{self.address_string()} {fmt % args}", flush=True)


def main():
    if len(_TOKEN) < _MIN_TOKEN_LENGTH:
        raise SystemExit(f"SNIPPET_RUNNER_TOKEN must be set to at least {_MIN_TOKEN_LENGTH} characters.")
    # Keep the token in this process's environment out of reach of snippet processes (same user).
    snippet_sandbox.protect_process_environ()
    server = ThreadingHTTPServer(("0.0.0.0", _PORT), _Handler)
    server.daemon_threads = True
    print(
        f"Snippet runner listening on port {_PORT} "
        f"(max concurrency {_MAX_CONCURRENCY}, max timeout {_MAX_TIMEOUT_SECONDS}s, "
        f"memory per snippet {snippet_sandbox.MAX_MEMORY_MB} MB)",
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
