"""Docker healthcheck for the datapull worker.

Exits 0 when a worker in this container has written a heartbeat to Redis recently, else 1.
The worker heartbeats between jobs, so the allowed age has to cover the longest job;
override it with WORKER_HEALTHCHECK_MAX_AGE_SECONDS.
"""
import os
import socket
import sys
import time

import all_connects

PREFIX = str(os.getenv('DATAPULL_WORKER_METRICS_PREFIX') or 'datapull:worker:metrics:').strip()
MAX_AGE_SECONDS = int(os.getenv('WORKER_HEALTHCHECK_MAX_AGE_SECONDS', '900'))


def main():
    client = all_connects.get_redis_client(socket_timeout=3, socket_connect_timeout=3)
    if client is None:
        print('redis unreachable')
        return 1

    # Worker ids are "<hostname>-<pid>" unless DATAPULL_WORKER_ID is set.
    worker_id = str(os.getenv('DATAPULL_WORKER_ID') or '').strip()
    pattern = PREFIX + (worker_id or f"{socket.gethostname()}-*")
    now = time.time()
    for key in client.scan_iter(match=pattern, count=100):
        try:
            last = int(client.hget(key, 'last_heartbeat_ts') or 0)
        except (TypeError, ValueError):
            continue
        if now - last <= MAX_AGE_SECONDS:
            print(f'ok: heartbeat {int(now - last)}s ago')
            return 0

    print(f'no heartbeat in the last {MAX_AGE_SECONDS}s')
    return 1


if __name__ == '__main__':
    sys.exit(main())
