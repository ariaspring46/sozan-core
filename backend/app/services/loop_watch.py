from __future__ import annotations

import asyncio
import faulthandler
import sys
import threading
import time


def blocked(last_beat: float, now: float, limit: float = 5.0) -> bool:
    return now - last_beat > limit


def start() -> asyncio.Task:
    faulthandler.enable(file=sys.stderr, all_threads=True)
    state = {"beat": time.monotonic(), "dumped": 0.0}

    async def beat() -> None:
        while True:
            state["beat"] = time.monotonic()
            await asyncio.sleep(1)

    def watch() -> None:
        while True:
            time.sleep(5)
            now = time.monotonic()
            if not blocked(state["beat"], now):
                continue
            if now - state["dumped"] < 30:
                continue
            state["dumped"] = now
            sys.stderr.write("sozan-loop-blocked\n")
            faulthandler.dump_traceback(file=sys.stderr, all_threads=True)

    threading.Thread(target=watch, name="sozan-loop-watch", daemon=True).start()
    return asyncio.create_task(beat())
