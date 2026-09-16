"""
Entrypoint used by run.sh (`python3 -m app`), instead of the more common
`python -m uvicorn app.main:app`. The difference matters on Windows:
uvicorn.run()/asyncio.run() creates the event loop before the app module
is ever imported, so setting an event loop policy inside app/main.py is
too late to have any effect. Doing it here, before uvicorn.run() is even
called, is the only point where it actually takes effect.

Production always runs in a Linux container, where the default loop
already supports what aiomqtt needs -- this block is a no-op there.
"""
from __future__ import annotations

import asyncio
import os
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn  # noqa: E402  (must follow the policy fix above)


def main() -> None:
    port = int(os.environ.get("TM_INGRESS_PORT", "8099"))
    log_level = os.environ.get("TM_UVICORN_LOG_LEVEL", "info")
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, log_level=log_level)


if __name__ == "__main__":
    main()
