"""Forward signed sandbox tool/knowledge proxy requests.

The sandbox posts a ``ToolProxyRequest`` or ``KnowledgeSearchRequest`` to the
run's callback URL, HMAC-signed in the ``X-Midsphere-Signature`` header (key =
the run's ``callback_auth`` hex, the same channel as callback batches). We
verify it, then either forward a developer-tool call to its
``execution_endpoint`` or run knowledge retrieval — keeping the developer's
endpoint off the sandbox (no SSRF surface there).

Response shapes match the sandbox contracts:
- tool:      ``{"result": <str|json>}`` or ``{"error": <str>}``
- knowledge: ``{"chunks": [{"knowledge_id", "knowledge_name", "text", "score"}]}``
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

import httpx

from apps.core.exceptions import NotFound
from apps.knowledge.models import Knowledge
from apps.runs.models.records import RunManifestRecord
from apps.runs.models.run import Run
from apps.tools.models import Tool


class InvalidProxy(Exception):
    """A proxy request that fails parsing or signature verification."""


_TIMEOUT = 30.0
_MAX_CHUNK_CHARS = 1200
_MIN_TERM_LEN = 3


def handle_proxy_request(raw_body: bytes, signature: str) -> dict[str, Any]:
    """Verify a signed proxy request and dispatch tool vs. knowledge search."""
    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise InvalidProxy("Malformed proxy body.") from exc
    run = _run_for(body.get("run_id"))
    _verify_signature(raw_body, signature, run)
    if "tool" in body:
        return _proxy_tool(run, body)
    if "query" in body:
        return _search_knowledge(run, body)
    raise InvalidProxy("Unknown proxy request type.")


def _run_for(run_uid: Any) -> Run:
    try:
        return Run.objects.select_related("workspace").get(run_uid=run_uid)
    except (Run.DoesNotExist, ValueError, TypeError) as exc:
        raise NotFound("Run not found for proxy request.") from exc


def _verify_signature(raw_body: bytes, signature: str, run: Run) -> None:
    record = RunManifestRecord.objects.filter(run=run).order_by("-created_at").first()
    if record is None:
        raise InvalidProxy("No manifest record for run.")
    key = record.decrypt_callback_auth().hex().encode()
    expected = hmac.new(key, raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature or ""):
        raise InvalidProxy("Proxy signature verification failed.")


# -- tool proxy ---------------------------------------------------------------


def _proxy_tool(run: Run, body: dict[str, Any]) -> dict[str, Any]:
    tool = Tool.objects.filter(
        workspace_id=run.workspace_id, name=body.get("tool", ""), is_active=True
    ).first()
    if tool is None or not tool.execution_endpoint:
        return {"error": f"tool '{body.get('tool')}' is not available for this run"}
    return _forward_tool(tool, run, body)


def _forward_tool(tool: Tool, run: Run, body: dict[str, Any]) -> dict[str, Any]:
    forwarded = {
        "tool": tool.name,
        "arguments": body.get("arguments", {}),
        "run_id": str(run.run_uid),
        "end_user_id": body.get("end_user_id"),
        "conversation_id": body.get("conversation_id"),
        "call_id": body.get("call_id"),
    }
    try:
        resp = httpx.post(tool.execution_endpoint, json=forwarded, timeout=_TIMEOUT)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        return {"error": f"tool endpoint error: {exc}"}
    return {"result": _result_payload(resp)}


def _result_payload(resp: httpx.Response) -> Any:
    try:
        data = resp.json()
    except ValueError:
        return resp.text
    if isinstance(data, dict):
        return data.get("result", data)
    return data


# -- knowledge search (naive keyword retrieval; no vector index yet) ----------


def _search_knowledge(run: Run, body: dict[str, Any]) -> dict[str, Any]:
    ids = body.get("knowledge_ids") or []
    query = str(body.get("query", ""))
    top_k = max(1, int(body.get("top_k", 5)))
    kbs = Knowledge.objects.filter(workspace_id=run.workspace_id, pk__in=ids, is_active=True)
    chunks: list[dict[str, Any]] = []
    for kb in kbs:
        chunks.extend(_kb_chunks(kb, query))
    chunks.sort(key=lambda c: c["score"], reverse=True)
    return {"chunks": chunks[:top_k]}


def _kb_chunks(kb: Knowledge, query: str) -> list[dict[str, Any]]:
    terms = {t.lower() for t in query.split() if len(t) >= _MIN_TERM_LEN}
    out: list[dict[str, Any]] = []
    for para in _paragraphs(_kb_text(kb)):
        score = float(sum(para.lower().count(term) for term in terms))
        if score > 0 or not terms:
            out.append(
                {
                    "knowledge_id": kb.pk,
                    "knowledge_name": kb.name,
                    "text": para[:_MAX_CHUNK_CHARS],
                    "score": score,
                }
            )
    return out


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in text.replace("\r", "").split("\n") if p.strip()]


def _kb_text(kb: Knowledge) -> str:
    if kb.source_endpoint:
        return _fetch_text(kb.source_endpoint)
    if kb.file:
        return _file_text(kb.file)
    return kb.description or ""


def _fetch_text(url: str) -> str:
    try:
        return httpx.get(url, timeout=15.0, follow_redirects=True).text
    except httpx.HTTPError:
        return ""


def _file_text(field: Any) -> str:
    try:
        with field.open("rb") as fh:
            return fh.read().decode("utf-8", "replace")
    except OSError:
        return ""
