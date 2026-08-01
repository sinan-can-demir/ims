"""Gunicorn hooks for Prometheus multiprocess mode.

Each Gunicorn worker has its own Python process and therefore its own
in-memory metrics registry. PROMETHEUS_MULTIPROC_DIR (set in
docker-compose.prod.yml) redirects those registries to a shared directory of
mmap'd files instead, so a single /metrics scrape can see all workers' data
(merged by app.core.metrics.metrics_response). These two hooks keep that
directory clean: stale files break counters after a restart, and a dead
worker's files must be removed so its state doesn't leak into new workers.
"""

import glob
import os


def on_starting(server):
    multiproc_dir = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
    if not multiproc_dir:
        return
    os.makedirs(multiproc_dir, exist_ok=True)
    for stale_file in glob.glob(os.path.join(multiproc_dir, "*.db")):
        os.remove(stale_file)


def child_exit(server, worker):
    if not os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        return
    from prometheus_client import multiprocess

    multiprocess.mark_process_dead(worker.pid)
