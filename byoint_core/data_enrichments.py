from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime, timezone
import json
import os
import ipaddress
import socket
import sys
import re
import base64

import all_connects
import snippet_sandbox


ENRICH_TYPES = ("builtin", "custom", "connector", "mcp")

# Fixed allowlists for custom enrichment snippets (they run in an isolated child process).
_ENRICHMENT_SNIPPET_ALLOWED_IMPORTS = ("requests", "datetime", "json", "re")
_ENRICHMENT_SNIPPET_ALLOWED_BUILTINS = (
	"str", "len", "print", "repr", "format", "ord", "chr", "enumerate", "range",
	"int", "float", "bool", "list", "dict", "set", "tuple",
	"min", "max", "sum", "sorted", "all", "any", "isinstance", "type",
	"Exception", "ValueError", "TypeError",
)
ENRICH_TYPES_ERROR = "enrich_type must be one of 'builtin', 'custom', 'connector', or 'mcp'."

def _normalize_connector_config(raw_config):
	"""Validate and normalize connector enrichment configuration."""
	if raw_config is None:
		return None, None
	if not isinstance(raw_config, dict):
		return None, "connector_config must be a JSON object."

	provider_kind = str(raw_config.get("provider_kind") or "").strip().lower()
	if provider_kind not in ("http", "db"):
		return None, "connector_config.provider_kind must be either 'http' or 'db'."

	normalized = {
		"provider_kind": provider_kind,
		"secret_ref": str(raw_config.get("secret_ref") or "").strip() or None,
		"timeout_seconds": int(raw_config.get("timeout_seconds", 10) or 10),
		"retry_count": int(raw_config.get("retry_count", 0) or 0),
		"verify_ssl": bool(raw_config.get("verify_ssl", True)),
		"enabled": bool(raw_config.get("enabled", True)),
	}

	request_template = raw_config.get("request_template")
	if request_template is not None and not isinstance(request_template, dict):
		return None, "connector_config.request_template must be a JSON object when provided."
	normalized["request_template"] = request_template if isinstance(request_template, dict) else {}

	response_mapping = raw_config.get("response_mapping")
	if response_mapping is not None and not isinstance(response_mapping, dict):
		return None, "connector_config.response_mapping must be a JSON object when provided."
	normalized["response_mapping"] = response_mapping if isinstance(response_mapping, dict) else {}

	if provider_kind == "http":
		url_template = str((normalized["request_template"] or {}).get("url_template") or "").strip()
		if not url_template:
			return None, "connector_config.request_template.url_template is required for http connectors."
	if provider_kind == "db":
		db_template, db_err = _normalize_db_request_template(normalized["request_template"])
		if db_err:
			return None, db_err
		normalized["request_template"] = db_template

	normalized["timeout_seconds"] = max(1, min(normalized["timeout_seconds"], 120))
	normalized["retry_count"] = max(0, min(normalized["retry_count"], 5))

	return normalized, None


DB_ENGINE_DEFAULT_PORTS = {
	"postgresql": 5432,
	"mysql": 3306,
	"mssql": 1433,
	"oracle": 1521,
	"mongodb": 27017,
}
DB_RESULT_MODES = ("first_row", "all_rows")
DB_MAX_ROW_LIMIT = 1000


def _normalize_db_request_template(raw_template):
	"""Validate the request_template of a db connector (a read-only lookup run per indicator)."""
	template = raw_template if isinstance(raw_template, dict) else {}
	prefix = "connector_config.request_template"

	db_engine = str(template.get("db_engine") or "").strip().lower()
	if db_engine not in DB_ENGINE_DEFAULT_PORTS:
		return None, f"{prefix}.db_engine must be one of {', '.join(DB_ENGINE_DEFAULT_PORTS)}."

	try:
		db_port = int(template.get("db_port") or DB_ENGINE_DEFAULT_PORTS[db_engine])
	except (TypeError, ValueError):
		return None, f"{prefix}.db_port must be a number."

	try:
		row_limit = int(template.get("row_limit") or 100)
	except (TypeError, ValueError):
		return None, f"{prefix}.row_limit must be a number."

	result_mode = str(template.get("result_mode") or "first_row").strip().lower()
	if result_mode not in DB_RESULT_MODES:
		return None, f"{prefix}.result_mode must be 'first_row' or 'all_rows'."

	normalized = {
		"db_engine": db_engine,
		"db_host": str(template.get("db_host") or "").strip(),
		"db_port": db_port,
		"db_name": str(template.get("db_name") or "").strip(),
		"db_user": str(template.get("db_user") or "").strip(),
		"db_password_secret_ref": str(template.get("db_password_secret_ref") or "").strip(),
		"query_template": str(template.get("query_template") or "").strip(),
		"result_mode": result_mode,
		"row_limit": max(1, min(row_limit, DB_MAX_ROW_LIMIT)),
	}
	if db_engine == "mongodb":
		normalized["db_collection"] = str(template.get("db_collection") or "").strip()
		normalized["db_auth_source"] = str(template.get("db_auth_source") or "").strip()

	for field in ("db_host", "db_name", "db_user", "db_password_secret_ref", "query_template"):
		if not normalized[field]:
			return None, f"{prefix}.{field} is required for db connectors."
	if db_engine == "mongodb":
		if not normalized["db_collection"]:
			return None, f"{prefix}.db_collection is required for mongodb connectors."
		try:
			query_spec = json.loads(normalized["query_template"])
		except json.JSONDecodeError as e:
			return None, f"{prefix}.query_template must be a JSON filter object or aggregation pipeline array: {e}"
		if not isinstance(query_spec, (dict, list)):
			return None, f"{prefix}.query_template must be a JSON filter object or aggregation pipeline array."
	elif "{{" in normalized["query_template"]:
		# Indicator values come from external feeds; splicing them into SQL text would allow injection.
		bind_hint = ":value" if db_engine == "oracle" else "%(value)s"
		return None, f"{prefix}.query_template must use bound parameters (e.g. {bind_hint}) instead of {{{{...}}}} placeholders."

	return normalized, None


def _db_value_to_json(value):
	"""Convert driver-specific column values into JSON/BSON-safe values."""
	from decimal import Decimal
	from datetime import date, time
	import uuid

	if value is None or isinstance(value, (str, bool, int, float)):
		return value
	if isinstance(value, Decimal):
		return int(value) if value == value.to_integral_value() else float(value)
	if isinstance(value, (datetime, date, time)):
		return value.isoformat()
	if isinstance(value, (bytes, bytearray, memoryview)):
		return bytes(value).hex()
	if isinstance(value, uuid.UUID):
		return str(value)
	if isinstance(value, dict):
		return {str(k): _db_value_to_json(v) for k, v in value.items()}
	if isinstance(value, (list, tuple, set)):
		return [_db_value_to_json(v) for v in value]
	return str(value)


def _run_sql_lookup(db_template, password, bind_params, timeout_seconds, fetch_limit):
	"""Open a connection, run one bound read-only query, and return rows as dicts. Never commits."""
	engine = db_template["db_engine"]
	host = db_template["db_host"]
	port = db_template["db_port"]
	db_name = db_template["db_name"]
	user = db_template["db_user"]
	query = db_template["query_template"]

	if engine == "postgresql":
		import psycopg2
		connection = psycopg2.connect(host=host, port=port, dbname=db_name, user=user, password=password, connect_timeout=timeout_seconds, options=f"-c statement_timeout={timeout_seconds * 1000}")
		connection.set_session(readonly=True)
	elif engine == "mysql":
		import pymysql
		connection = pymysql.connect(host=host, port=port, user=user, password=password, database=db_name, connect_timeout=timeout_seconds, read_timeout=timeout_seconds, write_timeout=timeout_seconds)
	elif engine == "mssql":
		import pymssql
		connection = pymssql.connect(server=host, port=port, user=user, password=password, database=db_name, login_timeout=timeout_seconds, timeout=timeout_seconds)
	elif engine == "oracle":
		import oracledb
		connection = oracledb.connect(user=user, password=password, dsn=oracledb.makedsn(host, port, service_name=db_name), tcp_connect_timeout=timeout_seconds)
		connection.call_timeout = timeout_seconds * 1000
		# oracledb rejects bind values that the statement does not reference.
		bind_params = {k: v for k, v in bind_params.items() if re.search(rf":{k}\b", query)}
	else:
		raise ValueError(f"unsupported SQL engine '{engine}'")

	try:
		cursor = connection.cursor()
		try:
			cursor.execute(query, bind_params)
			if not cursor.description:
				return []
			columns = [str(col[0]) for col in cursor.description]
			return [dict(zip(columns, row)) for row in cursor.fetchmany(fetch_limit)]
		finally:
			cursor.close()
	finally:
		try:
			connection.rollback()
		except Exception:
			pass
		connection.close()


def _run_mongodb_lookup(db_template, password, context, timeout_seconds, fetch_limit):
	import pymongo
	from urllib.parse import quote_plus

	# Placeholders are rendered inside parsed JSON string values, so indicator data cannot alter the query structure.
	query_spec = _render_template_value(json.loads(db_template["query_template"]), context)
	timeout_ms = timeout_seconds * 1000
	auth_source = db_template.get("db_auth_source") or db_template["db_name"]
	client = pymongo.MongoClient(
		f"mongodb://{quote_plus(db_template['db_user'])}:{quote_plus(password)}@{db_template['db_host']}:{db_template['db_port']}/{db_template['db_name']}?authSource={quote_plus(auth_source)}",
		serverSelectionTimeoutMS=timeout_ms,
		connectTimeoutMS=timeout_ms,
		socketTimeoutMS=timeout_ms,
	)
	try:
		collection = client[db_template["db_name"]][db_template["db_collection"]]
		if isinstance(query_spec, list):
			cursor = collection.aggregate(query_spec + [{"$limit": fetch_limit}], maxTimeMS=timeout_ms)
		else:
			cursor = collection.find(query_spec, max_time_ms=timeout_ms).limit(fetch_limit)
		rows = []
		for doc in cursor:
			if "_id" in doc:
				doc["_id"] = str(doc["_id"])
			rows.append(doc)
		return rows
	finally:
		client.close()


def _execute_db_connector(indicator, connector_config):
	db_template = connector_config.get("request_template") or {}
	context = {
		"value": str((indicator or {}).get("value") or ""),
		"type": str((indicator or {}).get("type") or ""),
		"dtype": str((indicator or {}).get("type") or ""),
	}

	password = _resolve_secret(db_template.get("db_password_secret_ref"))
	if not password:
		return None, f"DB password secret '{db_template.get('db_password_secret_ref')}' could not be resolved."

	timeout_seconds = int(connector_config.get("timeout_seconds", 10) or 10)
	first_row_only = db_template.get("result_mode") == "first_row"
	fetch_limit = 1 if first_row_only else int(db_template.get("row_limit") or 100)

	last_error = None
	for _attempt in range(max(1, int(connector_config.get("retry_count", 0) or 0) + 1)):
		try:
			if db_template["db_engine"] == "mongodb":
				rows = _run_mongodb_lookup(db_template, password, context, timeout_seconds, fetch_limit)
			else:
				rows = _run_sql_lookup(db_template, password, {"value": context["value"], "type": context["type"]}, timeout_seconds, fetch_limit)
			rows = _db_value_to_json(rows)
			return {
				"payload": (rows[0] if rows else None) if first_row_only else rows,
				"row_count": len(rows),
				"request": {
					"db_engine": db_template["db_engine"],
					"db_host": db_template["db_host"],
					"db_port": db_template["db_port"],
					"db_name": db_template["db_name"],
					"result_mode": db_template.get("result_mode"),
					"bind_params": {"value": context["value"], "type": context["type"]},
				},
			}, None
		except ImportError as e:
			return None, f"Database driver for '{db_template.get('db_engine')}' is not installed: {e}"
		except Exception as e:
			last_error = str(e)

	return None, last_error or "DB connector execution failed."


def _normalize_mcp_config(raw_config):
	"""Validate and normalize MCP tool enrichment configuration."""
	if raw_config is None:
		return None, None
	if not isinstance(raw_config, dict):
		return None, "mcp_config must be a JSON object."

	mcp_url = str(raw_config.get("mcp_url") or "").strip()
	if not mcp_url:
		return None, "mcp_config.mcp_url is required for mcp enrichments."
	tool_name = str(raw_config.get("tool_name") or "").strip()
	if not tool_name:
		return None, "mcp_config.tool_name is required for mcp enrichments."

	tool_arguments = raw_config.get("tool_arguments")
	if isinstance(tool_arguments, str):
		try:
			tool_arguments = json.loads(tool_arguments) if tool_arguments.strip() else {}
		except json.JSONDecodeError as e:
			return None, f"mcp_config.tool_arguments is not valid JSON: {e}"
	if tool_arguments is None:
		tool_arguments = {}
	if not isinstance(tool_arguments, dict):
		return None, "mcp_config.tool_arguments must be a JSON object."

	response_mapping = raw_config.get("response_mapping")
	if response_mapping is not None and not isinstance(response_mapping, dict):
		return None, "mcp_config.response_mapping must be a JSON object when provided."

	normalized = {
		"mcp_url": mcp_url,
		"tool_name": tool_name,
		"tool_arguments": tool_arguments,
		"auth_secret_ref": str(raw_config.get("auth_secret_ref") or "").strip() or None,
		"timeout_seconds": max(1, min(int(raw_config.get("timeout_seconds", 30) or 30), 120)),
		"retry_count": max(0, min(int(raw_config.get("retry_count", 0) or 0), 5)),
		"verify_ssl": bool(raw_config.get("verify_ssl", True)),
		"response_mapping": response_mapping if isinstance(response_mapping, dict) else {},
	}
	return normalized, None


def _resolve_secret(secret_name):
	"""Resolve a secret name to its actual value from the datapull_secrets collection."""
	try:
		if not secret_name:
			return None
		
		mongo_client, _ = all_connects.connect_mongodb()
		config_db = mongo_client["byoint_core_config"]
		secrets_col = config_db["datapull_secrets"]
		
		# Find by secret_ref (unique identifier)
		secret_doc = secrets_col.find_one({"secret_ref": str(secret_name).strip()})
		if not secret_doc:
			# Fall back to searching by name
			secret_doc = secrets_col.find_one({"name": str(secret_name).strip()})
		
		if not secret_doc:
			print(f"Secret '{secret_name}' not found in datapull_secrets collection")
			return None
		
		# Decrypt the secret value
		from all_connects import _decrypt_datapull_secret_value
		secret_value = _decrypt_datapull_secret_value(secret_doc)
		return secret_value
	except Exception as e:
		print(f"Error resolving secret '{secret_name}': {e}")
		return None
	finally:
		if 'mongo_client' in locals() and mongo_client:
			mongo_client.close()


def _render_template_string(template_text, context, resolve_secrets=False):
	template_text = str(template_text or "")
	context = context if isinstance(context, dict) else {}

	def _replace(match):
		key = str(match.group(1) or "").strip()
		
		# Handle {{secret:name}} placeholders
		if resolve_secrets and key.startswith("secret:"):
			secret_name = key[7:].strip()  # Remove "secret:" prefix
			secret_value = _resolve_secret(secret_name)
			return str(secret_value or "")
		
		# Handle standard {{key}} placeholders
		return str(context.get(key, ""))

	return re.sub(r"\{\{\s*([a-zA-Z0-9_\-:\.]+)\s*\}\}", _replace, template_text)


def _render_template_value(value, context, resolve_secrets=False):
	if isinstance(value, str):
		return _render_template_string(value, context, resolve_secrets=resolve_secrets)
	if isinstance(value, dict):
		return {k: _render_template_value(v, context, resolve_secrets=resolve_secrets) for k, v in value.items()}
	if isinstance(value, list):
		return [_render_template_value(v, context, resolve_secrets=resolve_secrets) for v in value]
	return value


def _extract_by_path(payload, path_text):
	if path_text is None:
		return None

	path_text = str(path_text or "").strip()
	if not path_text:
		return None
	if path_text.startswith("$."):
		path_text = path_text[2:]

	parts = [p for p in path_text.split(".") if p]
	cur = payload
	for part in parts:
		if isinstance(cur, dict):
			if part not in cur:
				return None
			cur = cur.get(part)
			continue
		if isinstance(cur, list):
			try:
				idx = int(part)
			except Exception:
				return None
			if idx < 0 or idx >= len(cur):
				return None
			cur = cur[idx]
			continue
		return None

	return cur


def _execute_http_connector(indicator, connector_config):
	try:
		import requests
	except Exception as e:
		return None, f"requests library is required for HTTP connector execution: {e}"

	connector_config = connector_config if isinstance(connector_config, dict) else {}
	request_template = connector_config.get("request_template") if isinstance(connector_config.get("request_template"), dict) else {}

	context = {
		"value": str((indicator or {}).get("value") or ""),
		"type": str((indicator or {}).get("type") or ""),
		"dtype": str((indicator or {}).get("type") or ""),
	}

	method = str(request_template.get("method") or "GET").strip().upper()
	url = _render_template_value(request_template.get("url_template"), context, resolve_secrets=True)
	if not str(url or "").strip():
		return None, "connector request url is empty after template rendering."

	headers = _render_template_value(request_template.get("headers_template") if isinstance(request_template.get("headers_template"), dict) else {}, context, resolve_secrets=True)
	params = _render_template_value(request_template.get("query_template") if isinstance(request_template.get("query_template"), dict) else {}, context, resolve_secrets=True)
	body_template = request_template.get("body_template")
	body = _render_template_value(body_template, context, resolve_secrets=True) if body_template is not None else None

	# Handle Basic auth: combine username + password
	basic_username = request_template.get("basic_username")
	basic_auth = None
	if basic_username:
		# Resolve password from Authorization header value after template rendering.
		# Expected UI shape is "Basic {{secret:...}}", which becomes "Basic <password>".
		auth_header = str(headers.get("Authorization") or "").strip()
		password = None

		if auth_header.lower().startswith("basic "):
			auth_value = auth_header[6:].strip()
			if auth_value:
				try:
					decoded = base64.b64decode(auth_value).decode("utf-8")
					if ":" in decoded:
						decoded_username, decoded_password = decoded.split(":", 1)
						if decoded_username:
							basic_username = decoded_username
						password = decoded_password
				except Exception:
					# Not base64; treat rendered value as plaintext password.
					password = auth_value

		if password:
			basic_auth = (str(basic_username), str(password))
			headers.pop("Authorization", None)
		else:
			headers.pop("Authorization", None)

	timeout_seconds = int(connector_config.get("timeout_seconds", 10) or 10)
	retry_count = int(connector_config.get("retry_count", 0) or 0)
	verify_ssl = bool(connector_config.get("verify_ssl", True))
	max_attempts = max(1, retry_count + 1)

	last_error = None
	for _attempt in range(max_attempts):
		try:
			request_kwargs = {
				"method": method,
				"url": url,
				"headers": headers,
				"params": params,
				"timeout": timeout_seconds,
				"verify": verify_ssl,
			}
			if basic_auth is not None:
				request_kwargs["auth"] = basic_auth
			if method in ("POST", "PUT", "PATCH", "DELETE") and body is not None:
				if isinstance(body, (dict, list)):
					request_kwargs["json"] = body
				else:
					request_kwargs["data"] = str(body)
			response = requests.request(**request_kwargs)

			if response.status_code < 200 or response.status_code >= 300:
				last_error = f"HTTP {response.status_code}: {response.text[:500]}"
				continue

			try:
				payload = response.json()
			except Exception:
				payload = {
					"text": response.text
				}

			return {
				"status_code": response.status_code,
				"payload": payload,
				"request": {
					"method": method,
					"url": url,
					"headers": headers,
					"params": params,
					"verify_ssl": verify_ssl,
				}
			}, None
		except Exception as e:
			last_error = str(e)

	return None, last_error or "HTTP connector execution failed."


def _map_payload_to_fields(payload, output_fields, response_mapping):
	"""Map each output field to its response path; fields without a path receive the whole payload."""
	mapped_result = {}
	for field_name in output_fields:
		path_text = response_mapping.get(field_name)
		if path_text:
			mapped_result[field_name] = _extract_by_path(payload, path_text)
		else:
			mapped_result[field_name] = payload
	return mapped_result


MCP_ENRICHMENT_MAX_RESPONSE_BYTES = 10 * 1024 * 1024


def _mcp_tool_result_to_payload(tool_result):
	"""Turn an MCP tools/call result into a JSON-like payload for response mapping."""
	if tool_result.get("structuredContent") is not None:
		return tool_result.get("structuredContent")

	items = []
	for item in tool_result.get("content") or []:
		if not isinstance(item, dict):
			continue
		if item.get("type") == "text":
			text = str(item.get("text") or "")
		elif item.get("type") == "resource" and isinstance(item.get("resource"), dict):
			text = str(item["resource"].get("text") or "")
		else:
			continue
		try:
			items.append(json.loads(text))
		except (json.JSONDecodeError, ValueError):
			items.append(text)
	if len(items) == 1:
		return items[0]
	return items


def _execute_mcp_tool_call(indicator, mcp_config):
	"""Run initialize -> tools/call against an MCP Streamable HTTP server for one indicator."""
	import requests
	# Imported lazily: datapull imports this module at load time.
	from datapull import MCP_PROTOCOL_VERSION, _mcp_parse_jsonrpc_response

	context = {
		"value": str((indicator or {}).get("value") or ""),
		"type": str((indicator or {}).get("type") or ""),
		"dtype": str((indicator or {}).get("type") or ""),
	}
	mcp_url = mcp_config.get("mcp_url")
	tool_name = mcp_config.get("tool_name")
	arguments = _render_template_value(mcp_config.get("tool_arguments") or {}, context, resolve_secrets=True)
	timeout_seconds = mcp_config.get("timeout_seconds", 30)
	verify_ssl = mcp_config.get("verify_ssl", True)

	headers = {
		"Accept": "application/json, text/event-stream",
		"Content-Type": "application/json",
	}
	if mcp_config.get("auth_secret_ref"):
		auth_token = _resolve_secret(mcp_config.get("auth_secret_ref"))
		if not auth_token:
			return None, f"MCP auth secret '{mcp_config.get('auth_secret_ref')}' could not be resolved."
		headers["Authorization"] = f"Bearer {auth_token}"

	def _post(message):
		return requests.post(mcp_url, json=message, headers=headers, timeout=timeout_seconds, verify=verify_ssl, stream=True)

	last_error = None
	for _attempt in range(max(1, int(mcp_config.get("retry_count", 0) or 0) + 1)):
		headers.pop("Mcp-Session-Id", None)
		headers.pop("MCP-Protocol-Version", None)
		try:
			init_response = _post({
				"jsonrpc": "2.0",
				"id": 1,
				"method": "initialize",
				"params": {
					"protocolVersion": MCP_PROTOCOL_VERSION,
					"capabilities": {},
					"clientInfo": {"name": "byoint-enrichment", "version": "1.0"},
				},
			})
			init_response.raise_for_status()
			session_id = init_response.headers.get("Mcp-Session-Id")
			init_result = _mcp_parse_jsonrpc_response(init_response, 1, MCP_ENRICHMENT_MAX_RESPONSE_BYTES)
			if session_id:
				headers["Mcp-Session-Id"] = session_id
			headers["MCP-Protocol-Version"] = str(init_result.get("protocolVersion") or MCP_PROTOCOL_VERSION)

			_post({"jsonrpc": "2.0", "method": "notifications/initialized"}).close()

			call_response = _post({
				"jsonrpc": "2.0",
				"id": 2,
				"method": "tools/call",
				"params": {"name": tool_name, "arguments": arguments},
			})
			call_response.raise_for_status()
			tool_result = _mcp_parse_jsonrpc_response(call_response, 2, MCP_ENRICHMENT_MAX_RESPONSE_BYTES)

			if session_id:
				try:
					requests.delete(mcp_url, headers=headers, timeout=timeout_seconds, verify=verify_ssl).close()
				except Exception:
					pass

			payload = _mcp_tool_result_to_payload(tool_result)
			if tool_result.get("isError"):
				# Tool-level errors are deterministic; retrying will not help.
				return None, f"MCP tool '{tool_name}' returned an error: {str(payload)[:500]}"

			server_info = init_result.get("serverInfo") or {}
			return {
				"payload": payload,
				"request": {
					"mcp_url": mcp_url,
					"tool_name": tool_name,
					"arguments": arguments,
					"server": f"{server_info.get('name') or ''} {server_info.get('version') or ''}".strip(),
					"protocol_version": headers["MCP-Protocol-Version"],
				},
			}, None
		except requests.exceptions.HTTPError as e:
			last_error = f"HTTP {e.response.status_code}: {e.response.text[:500]}"
		except Exception as e:
			last_error = str(e)

	return None, last_error or "MCP tool call failed."


def _execute_mcp_enrichment(indicator, enrichment_config):
	mcp_config, mcp_err = _normalize_mcp_config(enrichment_config.get("mcp_config"))
	if mcp_err:
		return None, mcp_err
	if not mcp_config:
		return None, "mcp_config is required for mcp enrichment."

	mcp_result, call_err = _execute_mcp_tool_call(indicator, mcp_config)
	if call_err:
		return None, call_err

	output_fields = enrichment_config.get("enrich_output_fields", [])
	return {
		"result": _map_payload_to_fields((mcp_result or {}).get("payload"), output_fields, mcp_config.get("response_mapping") or {}),
		"meta": {
			"request": (mcp_result or {}).get("request"),
			"raw_payload": (mcp_result or {}).get("payload"),
		}
	}, None


def test_mcp_enrichment(value=None, dtype=None, mcp_config=None, enrich_output_fields=None):
	"""Preview an MCP tool enrichment and mapped results without persisting indicator data."""
	indicator = {
		"value": str(value or "").strip(),
		"type": str(dtype or "").strip(),
	}
	output_fields = [str(field).strip() for field in (enrich_output_fields or []) if str(field).strip()]
	if not indicator["value"]:
		return None, "value is required."
	if not output_fields:
		return None, "enrich_output_fields must include at least one field."

	result, err = _execute_mcp_enrichment(indicator, {
		"enrich_type": "mcp",
		"enrich_output_fields": output_fields,
		"mcp_config": mcp_config,
	})
	if err:
		return None, err

	return {
		"mapped_result": (result or {}).get("result") if isinstance((result or {}).get("result"), dict) else {},
		"meta": (result or {}).get("meta") if isinstance((result or {}).get("meta"), dict) else {},
	}, None


def _execute_connector_enrichment(indicator, enrichment_config):
	connector_config, connector_err = _normalize_connector_config(enrichment_config.get("connector_config"))
	if connector_err:
		return None, connector_err
	if not connector_config:
		return None, "connector_config is required for connector enrichment."

	provider_kind = str(connector_config.get("provider_kind") or "").strip().lower()
	output_fields = enrichment_config.get("enrich_output_fields", [])
	response_mapping = connector_config.get("response_mapping") if isinstance(connector_config.get("response_mapping"), dict) else {}

	if provider_kind == "db":
		db_result, db_err = _execute_db_connector(indicator, connector_config)
		if db_err:
			return None, db_err
		return {
			"result": _map_payload_to_fields((db_result or {}).get("payload"), output_fields, response_mapping),
			"meta": {
				"provider_kind": provider_kind,
				"row_count": (db_result or {}).get("row_count"),
				"request": (db_result or {}).get("request"),
				"raw_payload": (db_result or {}).get("payload"),
			}
		}, None

	if provider_kind != "http":
		return None, f"connector provider '{provider_kind}' is not implemented yet."

	http_result, http_err = _execute_http_connector(indicator, connector_config)
	if http_err:
		return None, http_err

	payload = (http_result or {}).get("payload")

	return {
		"result": _map_payload_to_fields(payload, output_fields, response_mapping),
		"meta": {
			"provider_kind": provider_kind,
			"status_code": (http_result or {}).get("status_code"),
			"request": (http_result or {}).get("request"),
		}
	}, None


def test_connector_enrichment(value=None, dtype=None, connector_config=None, enrich_output_fields=None):
	"""Preview connector execution and mapped results without persisting indicator data."""
	indicator = {
		"value": str(value or "").strip(),
		"type": str(dtype or "").strip(),
	}
	output_fields = [str(field).strip() for field in (enrich_output_fields or []) if str(field).strip()]
	if not indicator["value"]:
		return None, "value is required."
	if not output_fields:
		return None, "enrich_output_fields must include at least one field."

	enrichment_config = {
		"enrich_type": "connector",
		"enrich_output_fields": output_fields,
		"connector_config": connector_config,
	}

	result, err = _execute_connector_enrichment(indicator, enrichment_config)
	if err:
		return None, err

	return {
		"mapped_result": (result or {}).get("result") if isinstance((result or {}).get("result"), dict) else {},
		"meta": (result or {}).get("meta") if isinstance((result or {}).get("meta"), dict) else {},
	}, None


def ipv4_find_networktype(ipv4):
	try:
		address = ipaddress.IPv4Address(str(ipv4).strip())
	except Exception:
		return None

	if address.is_private:
		return "private"
	return "public"


DNS_LOOKUP_TIMEOUT_SECONDS = 5
# getaddrinfo has no timeout of its own, so lookups run on a shared pool and are abandoned after the timeout.
_dns_lookup_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="dns-lookup")


def domain_resolve_ipv4(domain, timeout_seconds=DNS_LOOKUP_TIMEOUT_SECONDS):
	normalized = str(domain or "").strip().rstrip(".").lower()
	if not normalized:
		return None

	try:
		future = _dns_lookup_executor.submit(socket.getaddrinfo, normalized, None, socket.AF_INET, socket.SOCK_STREAM)
		results = future.result(timeout=timeout_seconds)
	except FuturesTimeoutError:
		print(f"DNS lookup timed out after {timeout_seconds}s: {normalized}")
		return None
	except Exception:
		return None

	addresses = sorted({result[4][0] for result in results}, key=lambda ip: ipaddress.IPv4Address(ip))
	return addresses or None


def _demo_ipv4_determine_networktype():
	sample_values = [
		"10.1.2.3",
		"172.16.5.10",
		"192.168.1.1",
		"8.8.8.8",
		"1.1.1.1",
		"not-an-ip",
	]

	return [
		{
			"value": sample,
			"network_type": ipv4_find_networktype(sample),
		}
		for sample in sample_values
	]


def get_enrichments(enabled_only=True, selected_enrichment_names=None):
	"""Fetch enrichment configs from byoint_core_config.data_enrichments."""
	try:
		mongo_client, _ = all_connects.connect_mongodb()
		db = mongo_client["byoint_core_config"]
		enrichments_col = db["data_enrichments"]

		query = {}
		if enabled_only:
			query["enabled"] = True
		if isinstance(selected_enrichment_names, list) and selected_enrichment_names:
			normalized_names = [str(name).strip() for name in selected_enrichment_names if str(name).strip()]
			if normalized_names:
				query["enrich_name"] = {"$in": normalized_names}

		enrichments = list(enrichments_col.find(query))
		mongo_client.close()
		return enrichments
	except Exception as e:
		print(f"Error fetching enrichments: {e}")
		return []


def list_data_enrichments():
	try:
		mongo_client, _ = all_connects.connect_mongodb()
		db = mongo_client["byoint_core_config"]
		enrichments_col = db["data_enrichments"]

		out = []
		for doc in enrichments_col.find({}):
			out.append({
				"enrich_name": doc.get("enrich_name"),
				"enrich_data_type": doc.get("enrich_data_type"),
				"enrich_type": doc.get("enrich_type"),
				"enrich_description": doc.get("enrich_description"),
				"info": doc.get("info") or "",
				"enrich_mapping_function": doc.get("enrich_mapping_function"),
				"snippet_code": doc.get("snippet_code") or doc.get("python_snippet"),
				"connector_config": doc.get("connector_config") if isinstance(doc.get("connector_config"), dict) else None,
				"mcp_config": doc.get("mcp_config") if isinstance(doc.get("mcp_config"), dict) else None,
				"enrich_output_fields": doc.get("enrich_output_fields") if isinstance(doc.get("enrich_output_fields"), list) else [],
				"enabled": bool(doc.get("enabled", False)),
				"created_at": doc.get("created_at").isoformat() if doc.get("created_at") else None,
				"updated_at": doc.get("updated_at").isoformat() if doc.get("updated_at") else None
			})

		mongo_client.close()
		return out, None
	except Exception as e:
		print(e)
		return [], str(e)


def create_data_enrichment(enrich_name=None, enrich_data_type=None, enrich_type=None, enrich_description=None, enrich_mapping_function=None, snippet_code=None, connector_config=None, enrich_output_fields=None, enabled=False, info=None, mcp_config=None):
	try:
		normalized_name = str(enrich_name or "").strip()
		normalized_data_type = str(enrich_data_type or "").strip()
		normalized_enrich_type = str(enrich_type or "builtin").strip().lower()
		normalized_mapping = str(enrich_mapping_function or "").strip()
		normalized_snippet = str(snippet_code or "").strip()
		normalized_connector_config, connector_err = _normalize_connector_config(connector_config)
		if connector_err:
			return None, connector_err
		normalized_mcp_config, mcp_err = _normalize_mcp_config(mcp_config)
		if mcp_err:
			return None, mcp_err

		if not normalized_name or not normalized_data_type:
			return None, "enrich_name and enrich_data_type are required."
		if normalized_enrich_type not in ENRICH_TYPES:
			return None, ENRICH_TYPES_ERROR
		if normalized_enrich_type == "mcp" and not isinstance(normalized_mcp_config, dict):
			return None, "mcp_config is required for mcp enrichments."
		if normalized_enrich_type == "builtin" and not normalized_mapping:
			return None, "enrich_mapping_function is required for builtin enrichments."
		if normalized_enrich_type == "custom" and not normalized_snippet:
			return None, "snippet_code is required for custom enrichments."
		if normalized_enrich_type == "connector" and not isinstance(normalized_connector_config, dict):
			return None, "connector_config is required for connector enrichments."

		output_fields = []
		if isinstance(enrich_output_fields, list):
			output_fields = [str(field).strip() for field in enrich_output_fields if str(field).strip()]

		mongo_client, _ = all_connects.connect_mongodb()
		db = mongo_client["byoint_core_config"]
		enrichments_col = db["data_enrichments"]
		enrichments_col.create_index("enrich_name", unique=True)

		if enrichments_col.find_one({"enrich_name": normalized_name}):
			mongo_client.close()
			return None, "Enrichment name already exists."

		now = datetime.now(timezone.utc)
		doc = {
			"enrich_name": normalized_name,
			"enrich_data_type": normalized_data_type,
			"enrich_type": normalized_enrich_type,
			"enrich_description": str(enrich_description).strip() if enrich_description is not None else "",
			"info": str(info).strip() if info is not None else "",
			"enrich_mapping_function": normalized_mapping,
			"snippet_code": normalized_snippet,
			"connector_config": normalized_connector_config,
			"mcp_config": normalized_mcp_config,
			"enrich_output_fields": output_fields,
			"enabled": bool(enabled),
			"created_at": now,
			"updated_at": now
		}

		enrichments_col.insert_one(doc)
		mongo_client.close()

		return {
			"enrich_name": doc.get("enrich_name"),
			"enrich_data_type": doc.get("enrich_data_type"),
			"enrich_type": doc.get("enrich_type"),
			"enrich_description": doc.get("enrich_description"),
			"info": doc.get("info"),
			"enrich_mapping_function": doc.get("enrich_mapping_function"),
			"snippet_code": doc.get("snippet_code"),
			"connector_config": doc.get("connector_config"),
			"mcp_config": doc.get("mcp_config"),
			"enrich_output_fields": doc.get("enrich_output_fields"),
			"enabled": doc.get("enabled"),
			"created_at": doc.get("created_at").isoformat(),
			"updated_at": doc.get("updated_at").isoformat()
		}, None
	except Exception as e:
		print(e)
		return None, str(e)


def update_data_enrichment(enrich_name=None, updates=None):
	try:
		normalized_name = str(enrich_name or "").strip()
		if not normalized_name:
			return None, "enrich_name is required."

		updates = updates or {}
		update_fields = {}

		if "enrich_data_type" in updates:
			update_fields["enrich_data_type"] = str(updates.get("enrich_data_type") or "").strip()
		if "enrich_type" in updates:
			enrich_type_value = str(updates.get("enrich_type") or "").strip().lower()
			if enrich_type_value and enrich_type_value not in ENRICH_TYPES:
				return None, ENRICH_TYPES_ERROR
			update_fields["enrich_type"] = enrich_type_value
		if "enrich_description" in updates:
			update_fields["enrich_description"] = str(updates.get("enrich_description") or "").strip()
		if "info" in updates:
			update_fields["info"] = str(updates.get("info") or "").strip()
		if "enrich_mapping_function" in updates:
			update_fields["enrich_mapping_function"] = str(updates.get("enrich_mapping_function") or "").strip()
		if "snippet_code" in updates:
			update_fields["snippet_code"] = str(updates.get("snippet_code") or "").strip()
		if "python_snippet" in updates:
			update_fields["snippet_code"] = str(updates.get("python_snippet") or "").strip()
		if "connector_config" in updates:
			normalized_connector_config, connector_err = _normalize_connector_config(updates.get("connector_config"))
			if connector_err:
				return None, connector_err
			update_fields["connector_config"] = normalized_connector_config
		if "mcp_config" in updates:
			normalized_mcp_config, mcp_err = _normalize_mcp_config(updates.get("mcp_config"))
			if mcp_err:
				return None, mcp_err
			update_fields["mcp_config"] = normalized_mcp_config
		if "enrich_output_fields" in updates and isinstance(updates.get("enrich_output_fields"), list):
			update_fields["enrich_output_fields"] = [str(field).strip() for field in updates.get("enrich_output_fields") if str(field).strip()]
		if "enabled" in updates:
			update_fields["enabled"] = bool(updates.get("enabled"))

		if not update_fields:
			return None, "No valid update fields provided."

		update_fields["updated_at"] = datetime.now(timezone.utc)

		mongo_client, _ = all_connects.connect_mongodb()
		db = mongo_client["byoint_core_config"]
		enrichments_col = db["data_enrichments"]

		result = enrichments_col.update_one(
			{"enrich_name": normalized_name},
			{"$set": update_fields}
		)

		if result.matched_count == 0:
			mongo_client.close()
			return None, "Enrichment not found."

		updated_doc = enrichments_col.find_one({"enrich_name": normalized_name})
		mongo_client.close()

		final_type = str(updated_doc.get("enrich_type") or "builtin").strip().lower()
		if final_type == "builtin" and not str(updated_doc.get("enrich_mapping_function") or "").strip():
			return None, "enrich_mapping_function is required for builtin enrichments."
		if final_type == "custom" and not str(updated_doc.get("snippet_code") or updated_doc.get("python_snippet") or "").strip():
			return None, "snippet_code is required for custom enrichments."
		if final_type == "connector":
			connector_cfg, connector_err = _normalize_connector_config(updated_doc.get("connector_config"))
			if connector_err:
				return None, connector_err
			if not connector_cfg:
				return None, "connector_config is required for connector enrichments."
		if final_type == "mcp":
			mcp_cfg, mcp_err = _normalize_mcp_config(updated_doc.get("mcp_config"))
			if mcp_err:
				return None, mcp_err
			if not mcp_cfg:
				return None, "mcp_config is required for mcp enrichments."

		return {
			"enrich_name": updated_doc.get("enrich_name"),
			"enrich_data_type": updated_doc.get("enrich_data_type"),
			"enrich_type": updated_doc.get("enrich_type"),
			"enrich_description": updated_doc.get("enrich_description"),
			"info": updated_doc.get("info") or "",
			"enrich_mapping_function": updated_doc.get("enrich_mapping_function"),
			"snippet_code": updated_doc.get("snippet_code") or updated_doc.get("python_snippet"),
			"connector_config": updated_doc.get("connector_config") if isinstance(updated_doc.get("connector_config"), dict) else None,
			"mcp_config": updated_doc.get("mcp_config") if isinstance(updated_doc.get("mcp_config"), dict) else None,
			"enrich_output_fields": updated_doc.get("enrich_output_fields") if isinstance(updated_doc.get("enrich_output_fields"), list) else [],
			"enabled": bool(updated_doc.get("enabled", False)),
			"created_at": updated_doc.get("created_at").isoformat() if updated_doc.get("created_at") else None,
			"updated_at": updated_doc.get("updated_at").isoformat() if updated_doc.get("updated_at") else None
		}, None
	except Exception as e:
		print(e)
		return None, str(e)


def _apply_single_enrichment(indicator, enrichment_config):
	"""Apply a single enrichment to an indicator."""
	enrich_type = enrichment_config.get("enrich_data_type")
	indicator_type = indicator.get("type")

	if enrich_type != indicator_type:
		return None

	function_name = enrichment_config.get("enrich_mapping_function")
	enrich_mode = str(enrichment_config.get("enrich_type") or "builtin").strip().lower()
	output_fields = enrichment_config.get("enrich_output_fields", [])

	if not output_fields:
		return None

	if enrich_mode == "connector":
		connector_result, connector_err = _execute_connector_enrichment(indicator, enrichment_config)
		if connector_err:
			print(f"Error applying connector enrichment {enrichment_config.get('enrich_name')}: {connector_err}")
			return None
		return {
			"enrich_name": enrichment_config.get("enrich_name"),
			"output_fields": output_fields,
			"result": (connector_result or {}).get("result"),
		}

	if enrich_mode == "mcp":
		mcp_result, mcp_err = _execute_mcp_enrichment(indicator, enrichment_config)
		if mcp_err:
			print(f"Error applying mcp enrichment {enrichment_config.get('enrich_name')}: {mcp_err}")
			return None
		return {
			"enrich_name": enrichment_config.get("enrich_name"),
			"output_fields": output_fields,
			"result": (mcp_result or {}).get("result"),
		}

	if enrich_mode == "custom":
		try:
			snippet_code = str(enrichment_config.get("snippet_code") or enrichment_config.get("python_snippet") or "").strip()
			if not snippet_code:
				print(f"Custom enrichment snippet missing for: {enrichment_config.get('enrich_name')}")
				return None
			if not all_connects.is_custom_snippet_allowed():
				print(f"Skipping custom enrichment {enrichment_config.get('enrich_name')}: {all_connects.CUSTOM_SNIPPET_DISABLED_MESSAGE}")
				return None

			enrich_name = enrichment_config.get("enrich_name")
			snippet_inputs = {
				"indicator": dict(indicator or {}),
				"value": indicator.get("value"),
				"dtype": indicator.get("type"),
				"enrichment": dict(enrichment_config or {}),
			}
			try:
				response = snippet_sandbox.run_snippet(
					"enrichment",
					snippet_code,
					snippet_inputs,
					_ENRICHMENT_SNIPPET_ALLOWED_IMPORTS,
					_ENRICHMENT_SNIPPET_ALLOWED_BUILTINS,
					snippet_sandbox.ENRICHMENT_TIMEOUT_SECONDS,
				)
			except snippet_sandbox.SnippetError as e:
				if e.output:
					print(f"[snippet:{enrich_name}] {e.output}")
				print(f"Error applying custom enrichment {enrich_name}: {e}")
				return None

			if response.get("output"):
				print(f"[snippet:{enrich_name}] {response['output']}")

			if not response.get("has_result"):
				print(f"Custom enrichment snippet did not set a result variable: {enrich_name}")
				return None

			return {
				"enrich_name": enrich_name,
				"output_fields": output_fields,
				"result": response.get("result")
			}
		except Exception as e:
			print(f"Error applying custom enrichment {enrichment_config.get('enrich_name')}: {e}")
			return None

	if not function_name:
		return None

	try:
		func = getattr(sys.modules[__name__], function_name, None)
		if not func:
			print(f"Enrichment function not found: {function_name}")
			return None

		result = func(indicator.get("value"))

		return {
			"enrich_name": enrichment_config.get("enrich_name"),
			"output_fields": output_fields,
			"result": result
		}
	except Exception as e:
		print(f"Error applying enrichment {function_name}: {e}")
		return None


def apply_enrichments_to_indicator(indicator, enabled_only=True, selected_enrichment_names=None):
	"""Apply all matching enabled enrichments to an indicator and return enriched data."""
	if not indicator:
		return {}

	if isinstance(selected_enrichment_names, list):
		normalized_names = [str(name).strip() for name in selected_enrichment_names if str(name).strip()]
		if not normalized_names:
			return {}
		selected_enrichment_names = normalized_names

	enrichments = get_enrichments(
		enabled_only=enabled_only,
		selected_enrichment_names=selected_enrichment_names
	)
	enriched_fields = {}
	now = datetime.now(timezone.utc)

	for enrichment_config in enrichments:
		result = _apply_single_enrichment(indicator, enrichment_config)
		if result:
			output_fields = result.get("output_fields", [])
			result_value = result.get("result")

			if isinstance(result_value, dict):
				for field_name in output_fields:
					if field_name not in result_value:
						continue
					enriched_fields[field_name] = {
						"value": result_value.get(field_name),
						"updated_at": now
					}
				continue

			for field_name in output_fields:
				enriched_fields[field_name] = {
					"value": result_value,
					"updated_at": now
				}

	return enriched_fields


def _serialize_mongo_doc(doc):
	"""Convert a raw MongoDB document to a JSON-serializable dict."""
	if not isinstance(doc, dict):
		return doc
	from bson import ObjectId
	out = {}
	for key, value in doc.items():
		if key == "_id":
			continue
		if isinstance(value, ObjectId):
			out[key] = str(value)
		elif isinstance(value, datetime):
			out[key] = value.isoformat()
		elif isinstance(value, list):
			out[key] = [_serialize_mongo_doc(item) if isinstance(item, dict) else (str(item) if isinstance(item, ObjectId) else item) for item in value]
		elif isinstance(value, dict):
			out[key] = _serialize_mongo_doc(value)
		else:
			out[key] = value
	return out


def enrich_and_update_indicator(value, dtype, mongo_client=None, selected_enrichment_names=None):
	"""Fetch, enrich, and update an indicator in MongoDB."""
	should_close = False
	try:
		if not mongo_client:
			mongo_client, _ = all_connects.connect_mongodb()
			should_close = True

		db = mongo_client["byoint_core_data"]
		indicators_col = db["indicators"]

		indicator_doc = indicators_col.find_one({"value": value, "type": dtype})
		if not indicator_doc:
			return None, f"Indicator not found: {value} ({dtype})"

		enriched = apply_enrichments_to_indicator(
			indicator_doc,
			enabled_only=True,
			selected_enrichment_names=selected_enrichment_names
		)

		if enriched:
			set_ops = {}
			for field_name, field_payload in enriched.items():
				set_ops[f"data-enrichment.{field_name}.value"] = field_payload.get("value")
				set_ops[f"data-enrichment.{field_name}.updated_at"] = field_payload.get("updated_at")

			if set_ops:
				indicators_col.update_one(
					{"value": value, "type": dtype},
					{"$set": set_ops}
				)

		updated_doc = indicators_col.find_one({"value": value, "type": dtype})
		return _serialize_mongo_doc(updated_doc), None
	except Exception as e:
		return None, str(e)
	finally:
		if should_close and mongo_client:
			mongo_client.close()


if __name__ == "__main__":
	print(json.dumps(_demo_ipv4_determine_networktype(), indent=2))
