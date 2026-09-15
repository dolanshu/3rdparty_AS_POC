# Copyright 2026 the 3rd-party AS POC authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Console process entry point.

M0 delivers the process boundary and the health surface; the operations UI (status bar,
navigation, live message flow, rule highlight, statistics, SVG topology) is built in M3
against the internal API of the AS.
"""

from __future__ import annotations

import argparse
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

__all__ = ["create_app", "main"]

#: Placeholder page served until the M3 console exists. Plain HTML, no libraries.
PLACEHOLDER_PAGE = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>3rd-party AS console</title>
<style>
 body {{ background: #10151c; color: #c8d3de; font-family: monospace; margin: 0; }}
 header {{ padding: 12px 20px; background: #16202b; border-bottom: 1px solid #26323f; }}
 main {{ padding: 20px; }}
 code {{ color: #7fd1ff; }}
</style>
</head>
<body>
<header><strong>3rd-party AS</strong> &mdash; console</header>
<main>
 <h1>Console placeholder</h1>
 <p>The operations console is delivered in <strong>M3</strong>.</p>
 <p>This process already runs separately from the AS, as required by ADR-0002, and
 reaches it through <code>INTERNAL_API_ADDRESS:INTERNAL_API_PORT</code>.</p>
</main>
</body>
</html>
"""


def create_app() -> FastAPI:
    """Create the console application.

    Returns:
        A FastAPI application with the health endpoint and the placeholder page.
    """
    app = FastAPI(title="3rd-party AS console", version="0.1.0")

    @app.get("/healthz")
    def health() -> dict[str, Any]:
        """Report that the console process is alive.

        Returns:
            A minimal health document.
        """
        return {"status": "ok", "component": "console"}

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        """Serve the placeholder page.

        Returns:
            The HTML of the placeholder console.
        """
        return PLACEHOLDER_PAGE

    return app


def main(argv: list[str] | None = None) -> int:
    """Run the console with uvicorn.

    Args:
        argv: Command line arguments; defaults to ``sys.argv``.

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(description="3rd-party AS console")
    parser.add_argument("--address", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8081)
    args = parser.parse_args(argv)

    import uvicorn  # imported lazily: only the console needs it

    uvicorn.run(create_app(), host=args.address, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
