"""Example developer endpoints for the notebook demos.

This is the "developer's own server" that midsphere calls:

- ``POST /tool``  — a custom tool. The backend forwards the agent's tool call
  here (``{tool, arguments, run_id, ...}``); we return ``{"result": ...}``.
- ``GET  /brief`` — a knowledge source. A ``connected_source`` knowledge base
  points here; the backend fetches it for ``search_knowledge``.

It's intentionally trivial and unauthenticated — it exists only so the notebook
can show a real round-trip. ``dev-up.sh`` runs it behind a cloudflared tunnel so
the cloud sandbox/backend can reach it.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = 9099

# A knowledge document with facts the model could not otherwise know — proof of
# grounding when the agent repeats them back.
BRIEF = (
    "INTERNAL PROJECT BRIEF\n"
    "The internal project codename is BLUE-FALCON-9.\n"
    "The classified launch window is the 15th of Marpril 2031.\n"
    "The lead engineer is Zyx Quor, reachable in bunker 7.\n"
    "The fallback model is codenamed TORTOISE.\n"
)


class Handler(BaseHTTPRequestHandler):
    def _send(self, body: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802  (http.server naming)
        length = int(self.headers.get("content-length", 0))
        raw = self.rfile.read(length).decode("utf-8", "replace")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {}
        args = data.get("arguments") if isinstance(data, dict) else {}
        name = args.get("name", "unknown") if isinstance(args, dict) else "unknown"
        self._send(
            json.dumps(
                {"result": f"The secret vault number for '{name}' is 42777-ZULU."}
            ).encode(),
            "application/json",
        )

    def do_GET(self) -> None:  # noqa: N802
        self._send(BRIEF.encode(), "text/plain")

    def log_message(self, *_: object) -> None:  # silence per-request logging
        return


if __name__ == "__main__":
    print(f"example endpoints on :{PORT}  (POST /tool, GET /brief)", flush=True)
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
