"""Minimal MCP (Model Context Protocol) server for outputs of type "mcp".

Implements the stateless subset of the Streamable HTTP transport: each POST
carries one JSON-RPC message and receives a single JSON response. Every MCP
output is exposed as its own server at /mcp/<output name>, offering read-only
tools over that output's filtered indicator list.
"""

import json

import data_output

SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_NAME = "byoint"
SERVER_VERSION = "1.0.0"

DEFAULT_PAGE_SIZE = 500
MAX_PAGE_SIZE = 5000

# JSON-RPC error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

TOOLS = [
    {
        "name": "get_feed_info",
        "description": "Describe this threat-intel feed: name, sources, filters and indicator count.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "list_indicators",
        "description": "List indicator values (IPs, domains, URLs, hashes, ...) in this feed, paginated.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "offset": {"type": "integer", "minimum": 0, "default": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": MAX_PAGE_SIZE, "default": DEFAULT_PAGE_SIZE},
                "contains": {"type": "string", "description": "Optional case-insensitive substring filter."},
            },
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "check_indicators",
        "description": "Check whether one or more values are present in this feed.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "values": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 1000,
                },
            },
            "required": ["values"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
]


def _result(request_id, result):
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id, code, message):
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _tool_result(payload, is_error=False):
    return {
        "content": [{"type": "text", "text": json.dumps(payload, default=str)}],
        "structuredContent": payload,
        "isError": is_error,
    }


def _coerce_int(value, default, minimum, maximum):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def _call_tool(feed, name, arguments):
    entries = [str(e) for e in (feed.get("entries") or [])]

    if name == "get_feed_info":
        return _tool_result({
            "name": feed.get("name"),
            "source_name": feed.get("source_name"),
            "source_filters": feed.get("source_filters") or [],
            "filter_search": feed.get("filter_search"),
            "indicator_count": len(entries),
        })

    if name == "list_indicators":
        contains = str(arguments.get("contains") or "").strip().lower()
        if contains:
            entries = [e for e in entries if contains in e.lower()]
        offset = _coerce_int(arguments.get("offset"), 0, 0, max(len(entries), 0))
        limit = _coerce_int(arguments.get("limit"), DEFAULT_PAGE_SIZE, 1, MAX_PAGE_SIZE)
        page = entries[offset:offset + limit]
        next_offset = offset + len(page)
        return _tool_result({
            "total": len(entries),
            "offset": offset,
            "count": len(page),
            "next_offset": next_offset if next_offset < len(entries) else None,
            "indicators": page,
        })

    if name == "check_indicators":
        values = arguments.get("values")
        if not isinstance(values, list) or not values:
            return _tool_result({"message": "'values' must be a non-empty array of strings."}, is_error=True)
        lookup = {e.strip().lower() for e in entries}
        matches = {str(v): str(v).strip().lower() in lookup for v in values[:1000]}
        return _tool_result({
            "matches": matches,
            "found": [v for v, hit in matches.items() if hit],
        })

    return None


def handle_message(output_name, message):
    """Handle one JSON-RPC message. Returns a response dict, or None for notifications."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not message.get("method"):
        return _error(message.get("id") if isinstance(message, dict) else None, INVALID_REQUEST, "Invalid JSON-RPC request.")

    method = message["method"]
    request_id = message.get("id")
    params = message.get("params") or {}

    # Notifications (no id) never get a response body.
    if "id" not in message:
        return None

    if method == "initialize":
        requested = str(params.get("protocolVersion") or "")
        version = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else SUPPORTED_PROTOCOL_VERSIONS[0]
        return _result(request_id, {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": f"{SERVER_NAME}-{output_name}", "version": SERVER_VERSION},
            "instructions": f"Threat-intel indicator feed '{output_name}' from BYOINT. Tools are read-only.",
        })

    if method == "ping":
        return _result(request_id, {})

    if method == "tools/list":
        return _result(request_id, {"tools": TOOLS})

    if method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return _error(request_id, INVALID_PARAMS, "'arguments' must be an object.")
        if tool_name not in {t["name"] for t in TOOLS}:
            return _error(request_id, INVALID_PARAMS, f"Unknown tool: {tool_name}")

        feed = data_output.output_edl_by_name_cached(output_name)
        if not feed:
            return _result(request_id, _tool_result({"message": f"Feed not available: {output_name}"}, is_error=True))
        return _result(request_id, _call_tool(feed, tool_name, arguments))

    return _error(request_id, METHOD_NOT_FOUND, f"Method not found: {method}")
