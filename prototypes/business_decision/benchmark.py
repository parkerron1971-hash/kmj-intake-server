"""Bounded local measurements. No inference provider or cloud access."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import ctypes
import json
import math
import os
from pathlib import Path
import platform
import statistics
import sys
import threading
import time
from urllib.request import Request, urlopen

from .corpus import TEST, context_for
from .evaluate import load_engine
from .server import make_server


def memory_mb():
    if sys.platform == "win32":
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in ("PeakWorkingSetSize", "WorkingSetSize",
                    "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                    "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        kernel = ctypes.windll.kernel32
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        get_info = ctypes.windll.psapi.GetProcessMemoryInfo
        get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        if not get_info(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            raise OSError("Could not measure process memory")
        return {"resident_mb": counters.WorkingSetSize / 1024**2,
                "peak_resident_mb": counters.PeakWorkingSetSize / 1024**2}
    import resource
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_mb = peak / (1024**2 if sys.platform == "darwin" else 1024)
    return {"peak_resident_mb": peak_mb}


def percentiles(values):
    values = sorted(values)
    return {"p50_ms": statistics.median(values),
            "p95_ms": values[max(0, math.ceil(len(values) * .95) - 1)],
            "p99_ms": values[max(0, math.ceil(len(values) * .99) - 1)]}


def run_benchmark(model_path: Path, iterations=10000, http_requests=500) -> dict:
    if not 1 <= iterations <= 100000 or not 1 <= http_requests <= 5000:
        raise ValueError("Keep the prototype benchmark bounded")
    engine = load_engine(model_path)
    rows = [(row["text"], context_for(row["context"])) for row in TEST]
    for message, context in rows:
        engine.decide(message, business_id="demo-salon", context=context)
    timings = []
    start_cpu, start_wall = time.process_time(), time.perf_counter()
    for i in range(iterations):
        message, context = rows[i % len(rows)]
        start = time.perf_counter()
        engine.decide(message, business_id="demo-salon", context=context)
        timings.append((time.perf_counter() - start) * 1000)
    wall, cpu = time.perf_counter() - start_wall, time.process_time() - start_cpu
    direct = {"requests": iterations, "wall_seconds": wall, "cpu_seconds": cpu,
              "cpu_ms_per_decision": cpu * 1000 / iterations,
              "decisions_per_second_serial": iterations / wall, **percentiles(timings)}
    memory_before_http = memory_mb()
    server = make_server(engine, port=0)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    address = "http://127.0.0.1:" + str(server.server_address[1]) + "/decide"

    def request_one(i):
        body = json.dumps({"message": rows[i % len(rows)][0]}).encode()
        start = time.perf_counter()
        try:
            with urlopen(Request(address, data=body, headers={"Content-Type": "application/json"}), timeout=10) as response:
                answer = json.load(response)
                ok = response.status == 200 and answer["route"] in ("routine", "ask", "frontier")
        except Exception:
            ok = False
        return (time.perf_counter() - start) * 1000, ok

    http_results = []
    try:
        for concurrency in (1, 10, 25):
            start = time.perf_counter()
            start_cpu = time.process_time()
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                results = list(pool.map(request_one, range(http_requests)))
            elapsed = time.perf_counter() - start
            http_results.append({"concurrency": concurrency, "requests": http_requests,
                                 "errors": sum(not ok for _, ok in results),
                                 "requests_per_second": http_requests / elapsed,
                                 "wall_seconds": elapsed,
                                 "cpu_seconds_client_and_server": time.process_time() - start_cpu,
                                 **percentiles([latency for latency, _ in results])})
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
    return {"environment": {"os": platform.platform(), "python": platform.python_version(),
                            "logical_cpu_count": os.cpu_count()},
            "artifact_bytes": model_path.stat().st_size, "direct": direct,
            "process_memory_after_warmup": memory_before_http, "process_memory_after_http": memory_mb(),
            "http": http_results, "paid_api_calls": 0, "paid_api_cost_usd": 0,
            "limitations": ["Local Windows/Linux machine, not a Railway capacity benchmark",
                            "HTTP client and demo server share a process/CPU; no real DB or frontier calls",
                            "Short bursts, not a sustained soak test; no guaranteed number of users",
                            "Model cost excludes the rest of the application and idle resource overhead"]}
