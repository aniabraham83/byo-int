from datetime import datetime, timezone
from functools import wraps
from flask import request, jsonify, g, make_response
from urllib.request import urlopen
from pymongo import UpdateOne
import re
import json
import os
import uuid
import socket
import time
import random
import requests
import threading
import importlib
import all_connects
import data_enrichments


dtype_regex_patterns = {
    'ipv4': '^(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\\.(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\\.(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\\.(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$'
}

DATAPULL_CORE_CONFIG = None
_DATAPULL_QUEUE_CLIENT = None
_DATAPULL_QUEUE_INIT_ATTEMPTED = False
_DATAPULL_QUEUE_KEY = str(os.getenv('DATAPULL_QUEUE_KEY') or 'datapull:execution:queue').strip()
_DATAPULL_WORKER_METRICS_PREFIX = str(os.getenv('DATAPULL_WORKER_METRICS_PREFIX') or 'datapull:worker:metrics:').strip()
_DATAPULL_WORKER_METRICS_INDEX_KEY = str(os.getenv('DATAPULL_WORKER_METRICS_INDEX_KEY') or 'datapull:worker:metrics:index').strip()

# --- Constants ---
CREDENTIAL_FIELD_EXACT = {
    'password', 'passphrase', 'token', 'secret', 'api_key', 'apikey',
    'bearer_token', 'client_secret', 'private_key', 'access_key'
}
CREDENTIAL_FIELD_SUFFIX = (
    '_password', '_token', '_secret', '_api_key', '_apikey',
    '_client_secret', '_private_key', '_access_key'
)


# --- Helper Functions ---
def _is_sensitive_payload_field(field_name):
    normalized = str(field_name or '').strip().lower()
    if not normalized:
        return False
    if normalized in CREDENTIAL_FIELD_EXACT:
        return True
    return any(normalized.endswith(suffix) for suffix in CREDENTIAL_FIELD_SUFFIX)


def _validate_datapull_payload_security(datapull_payload):
    """Reject plaintext credentials; require *_secret_ref with sec_* references."""
    if datapull_payload is None:
        return None

    if not isinstance(datapull_payload, dict):
        return "Invalid datapull_payload. Expected a JSON object."

    def _walk_payload(node, path_prefix='datapull_payload'):
        if isinstance(node, dict):
            for key, value in node.items():
                field_name = str(key or '').strip()
                if not field_name:
                    continue

                full_path = f"{path_prefix}.{field_name}"

                if field_name.endswith('_secret_ref'):
                    if value in [None, '']:
                        continue
                    if not str(value).startswith('sec_'):
                        return (
                            f"Invalid secret reference for '{full_path}'. "
                            "Expected value starting with 'sec_'"
                        )
                    continue

                if _is_sensitive_payload_field(field_name) and value not in [None, '']:
                    return (
                        f"Plaintext credential field '{full_path}' is not allowed. "
                        f"Use '{full_path}_secret_ref' with a stored secret reference."
                    )

                nested_error = _walk_payload(value, full_path)
                if nested_error:
                    return nested_error

        elif isinstance(node, list):
            for index, item in enumerate(node):
                nested_error = _walk_payload(item, f"{path_prefix}[{index}]")
                if nested_error:
                    return nested_error

        return None

    return _walk_payload(datapull_payload)


def _resolve_secret_refs_in_payload(datapull_payload):
    """Resolve *_secret_ref payload fields to runtime values without mutating source payload."""
    if not isinstance(datapull_payload, dict):
        return datapull_payload

    resolved_payload = dict(datapull_payload)
    for key, value in datapull_payload.items():
        field_name = str(key or '').strip()
        if not field_name.endswith('_secret_ref'):
            continue
        if value in [None, '']:
            continue

        secret_value, secret_error = resolve_datapull_secret_ref(value)
        if secret_error:
            raise ValueError(f"Failed resolving secret reference '{field_name}': {secret_error}")

        target_field = field_name[:-len('_secret_ref')]
        if target_field:
            resolved_payload[target_field] = secret_value

    return resolved_payload


def _extract_by_path(payload, path_text):
    if path_text is None:
        return None

    path_text = str(path_text or '').strip()
    if not path_text:
        return None
    if path_text.startswith('$.'):
        path_text = path_text[2:]

    parts = [part for part in path_text.split('.') if part]
    current = payload
    for part in parts:
        if isinstance(current, dict):
            if part not in current:
                return None
            current = current.get(part)
            continue
        if isinstance(current, list):
            try:
                index = int(part)
            except Exception:
                return None
            if index < 0 or index >= len(current):
                return None
            current = current[index]
            continue
        return None

    return current


def _collect_indicator_values(node, source, extracted_list, event_time=None, batch_buffer=None):
    if isinstance(node, dict):
        for _, value in node.items():
            _collect_indicator_values(value, source, extracted_list, event_time=event_time, batch_buffer=batch_buffer)
        return

    if isinstance(node, list):
        for item in node:
            _collect_indicator_values(item, source, extracted_list, event_time=event_time, batch_buffer=batch_buffer)
        return

    candidate = str(node)
    detect_dtype = dtype_extractor(candidate, source)
    if not detect_dtype:
        return

    runtime_time = event_time or datetime.now(timezone.utc)
    if batch_buffer is not None:
        batch_buffer.append((candidate, detect_dtype))
    else:
        update_indicators(candidate, detect_dtype, runtime_time, source)
    extracted_list.append({'value': candidate, 'dtype': detect_dtype, 'e_time': runtime_time})


def _extract_api_response_indicators(data, source, response_mode=None, response_schema=None):
    extracted_list = []
    normalized_mode = str(response_mode or 'walk_everything').strip().lower()
    batch_buffer = [] if is_insertmany_enabled_for_source(source) else None

    if normalized_mode in ('schema', 'explicit', 'mapping'):
        if isinstance(response_schema, dict):
            response_paths = list(response_schema.values())
        elif isinstance(response_schema, (list, tuple, set)):
            response_paths = list(response_schema)
        elif isinstance(response_schema, str):
            response_paths = [response_schema]
        else:
            response_paths = []

        for path_text in response_paths:
            value = _extract_by_path(data, path_text)
            if value is None:
                continue
            _collect_indicator_values(value, source, extracted_list, batch_buffer=batch_buffer)
    else:
        _collect_indicator_values(data, source, extracted_list, batch_buffer=batch_buffer)

    if batch_buffer:
        bulk_update_indicators(batch_buffer, source)
    return extracted_list


def _build_datapull_security_report(workflow_docs, include_compliant=False):
    """Build compliance report for workflow datapull_payload security."""
    report_rows = []
    total_checked = 0
    non_compliant_count = 0

    for workflow in (workflow_docs or []):
        total_checked += 1

        source_name = workflow.get('source_name')
        datapull_payload = workflow.get('datapull_payload')
        validation_error = _validate_datapull_payload_security(datapull_payload)
        is_compliant = validation_error is None

        if not is_compliant:
            non_compliant_count += 1

        if include_compliant or (not is_compliant):
            report_rows.append({
                'source_name': source_name,
                'scheduled': bool(workflow.get('scheduled')),
                'schedule_enabled': bool(workflow.get('schedule_enabled')),
                'source_template_type': workflow.get('source_template_type'),
                'compliant': is_compliant,
                'error': validation_error
            })

    return {
        'checked_at': datetime.utcnow().isoformat(),
        'total_workflows_checked': total_checked,
        'non_compliant_workflows': non_compliant_count,
        'compliant_workflows': max(0, total_checked - non_compliant_count),
        'compliance_rate': (
            round(((total_checked - non_compliant_count) / total_checked) * 100, 2)
            if total_checked > 0 else 100.0
        ),
        'workflows': report_rows
    }


def log_datapull_execution(log_entry):
    """Log datapull execution to the opslogs database."""
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client["byoint_opslogs"]
        logs = db["datapull_executions"]
        
        result = logs.insert_one(log_entry)
        print(f"Logged execution to opslogs: {log_entry.get('source_name')} (ID: {result.inserted_id})")
        
        mongo_client.close()
    except Exception as e:
        print(f"Error logging to opslogs: {e}")


def _to_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    normalized = str(value or '').strip().lower()
    return normalized in ['1', 'true', 'yes', 'y', 'on']


def connect_mongodb():
    return all_connects.connect_mongodb()


def load_datapull_core_config():
    """Load datapull core configuration from environment variable or database."""
    global DATAPULL_CORE_CONFIG

    env_config = os.environ.get("DATAPULL_CORE_CONFIG")
    if env_config:
        try:
            DATAPULL_CORE_CONFIG = json.loads(env_config)
            print("datapull: Loaded DATAPULL_CORE_CONFIG from environment variable")
            return DATAPULL_CORE_CONFIG
        except json.JSONDecodeError as e:
            print(f"datapull: Error parsing DATAPULL_CORE_CONFIG from environment: {e}")

    try:
        config_loader = globals().get('get_datapull_core_config')
        if not callable(config_loader):
            DATAPULL_CORE_CONFIG = {}
            return DATAPULL_CORE_CONFIG

        config = config_loader()
        if config:
            if '_id' in config:
                del config['_id']
            DATAPULL_CORE_CONFIG = config
        else:
            DATAPULL_CORE_CONFIG = {}
    except Exception as e:
        print(f"datapull: Error loading datapull core config: {e}")
        DATAPULL_CORE_CONFIG = {}

    return DATAPULL_CORE_CONFIG


def get_config_value(key, default=None):
    global DATAPULL_CORE_CONFIG
    if DATAPULL_CORE_CONFIG is None:
        load_datapull_core_config()
    if DATAPULL_CORE_CONFIG is None:
        return default
    return DATAPULL_CORE_CONFIG.get(key, default)


def is_indicator_logging_enabled():
    return _to_bool(get_config_value('enable_indicator_logging', False))


def log_indicator_activity(action, datapull_source, indicator_value=None, indicator_type=None, event_time=None, details=None, mongo_client=None):
    """Write indicator activity log if enabled in basicconfigs."""
    if not is_indicator_logging_enabled():
        return

    close_client = False
    active_client = mongo_client
    try:
        if active_client is None:
            active_client, _ = connect_mongodb()
            close_client = True

        ops_db = active_client["byoint_opslogs"]
        logs_col = ops_db["indicator_logs"]

        now = datetime.now(timezone.utc)
        event_dt = event_time if event_time else now

        log_doc = {
            "action": str(action or '').strip().lower(),
            "datapull_source": str(datapull_source or 'unknown'),
            "event_time": event_dt,
            "logged_at": now
        }

        if indicator_value not in [None, '']:
            log_doc["indicator_value"] = indicator_value
        if indicator_type not in [None, '']:
            log_doc["indicator_type"] = indicator_type
        if isinstance(details, dict) and details:
            log_doc["details"] = details

        logs_col.insert_one(log_doc)
    except Exception as e:
        print(f"Error writing indicator activity log: {e}")
    finally:
        if close_client and mongo_client is None and active_client:
            try:
                active_client.close()
            except Exception:
                pass


def get_datapull_template_function_mapping(template_name):
    try:
        client, _ = connect_mongodb()
        db = client["byoint_core_config"]
        templates = db["datapull_templates"]
        doc = templates.find_one({"template_name": template_name}, {"function_mapping": 1})
        client.close()
        if doc and "function_mapping" in doc:
            return doc["function_mapping"]
        return None
    except Exception as e:
        print(e)
        return None


def get_datapull_template(template_name):
    try:
        client, _ = connect_mongodb()
        db = client["byoint_core_config"]
        templates = db["datapull_templates"]
        doc = templates.find_one({"template_name": template_name})
        client.close()
        return doc
    except Exception as e:
        print(e)
        return None


def return_datapulls_sched_custom(source_name=None):
    try:
        mongo_client, _ = connect_mongodb()
        db = mongo_client["byoint_core_data"]
        datapull_workflows = db["datapull_workflows"]
        act_datapulls = datapull_workflows.find({"enabled": "Y", "scheduled": "Y"})
        for e_active in act_datapulls:
            source_name = e_active['source_name']
            id_val = e_active['_id']
            datapull_function = e_active['datapull_function']
            datapull_payload = e_active['datapull_payload']
            mongo_client.close()
            return str(id_val), str(datapull_function), datapull_payload, source_name
        mongo_client.close()
        return None, None, None, source_name
    except Exception as e:
        print(e)
        return None, None, None, source_name


def dtype_extractor(transit_val, source=None):
    try:
        detect_dtype = ''

        if source:
            try:
                mongo_client, _ = connect_mongodb()
                db = mongo_client["byoint_core_data"]
                workflows = db["datapull_workflows"]
                workflow = workflows.find_one({"source_name": source}, {"source_type": 1})

                if workflow and workflow.get("source_type"):
                    source_type = workflow.get("source_type")
                    config_db = mongo_client["byoint_core_config"]
                    data_types = config_db["data_types"]
                    data_type_doc = data_types.find_one({"name": source_type}, {"regex_extract_pattern": 1})
                    if data_type_doc and data_type_doc.get("regex_extract_pattern"):
                        regex_pattern = data_type_doc.get("regex_extract_pattern")
                        if re.search(regex_pattern, str(transit_val)):
                            mongo_client.close()
                            return source_type

                mongo_client.close()
            except Exception as e:
                print(f"Error querying source_type/regex pattern: {e}")

        for e_dtype, r_dtype in dtype_regex_patterns.items():
            if re.search(r_dtype, str(transit_val)):
                detect_dtype = e_dtype
                break

        return detect_dtype
    except Exception as e:
        print(e)
        return ''


def create_datapull_workflow(source_name=None, source_description=None, source_category=None, source_type=None, source_template_type=None, scheduled=None, schedule_enabled=None, schedule_interval_min=None, datapull_payload=None, br_score=None, tag=None, selected_enrichments=None, enrichment_enabled=False, insertmany=False, max_response_bytes=None, max_query_rows=None):
    try:
        mongo_client, _ = connect_mongodb()
        db = mongo_client["byoint_core_data"]
        datapull_workflows = db["datapull_workflows"]
        check_if_exist = datapull_workflows.count_documents({"source_name": source_name})

        if scheduled is None:
            scheduled = bool(schedule_interval_min)
        if schedule_enabled is None:
            schedule_enabled = bool(scheduled)
        if not scheduled:
            schedule_interval_min = None

        normalized_selected_enrichments = []
        if isinstance(selected_enrichments, list):
            normalized_selected_enrichments = [str(e).strip() for e in selected_enrichments if str(e).strip()]

        normalized_max_response_bytes = None
        if max_response_bytes not in [None, '']:
            try:
                normalized_max_response_bytes = max(1, int(max_response_bytes))
            except Exception:
                normalized_max_response_bytes = None

        normalized_max_query_rows = None
        if max_query_rows not in [None, '']:
            try:
                normalized_max_query_rows = max(1, int(max_query_rows))
            except Exception:
                normalized_max_query_rows = None

        if int(check_if_exist) == 0:
            datapull_function = None
            if source_template_type:
                template_doc = get_datapull_template(source_template_type)
                template_type = str((template_doc or {}).get('template_type') or '').strip().lower()
                if template_type != 'custom':
                    datapull_function = (template_doc or {}).get('function_mapping') or None

            pload = {
                "source_name": source_name,
                "source_description": source_description,
                "source_category": source_category,
                "source_type": source_type,
                "tag": tag,
                "source_template_type": source_template_type,
                "datapull_function": datapull_function,
                "br_score": br_score,
                "scheduled": scheduled,
                "schedule_enabled": schedule_enabled,
                "selected_enrichments": normalized_selected_enrichments,
                "enrichment_enabled": bool(normalized_selected_enrichments) if selected_enrichments is not None else bool(enrichment_enabled),
                "schedule_interval_min": schedule_interval_min,
                "insertmany": bool(insertmany),
                "max_response_bytes": normalized_max_response_bytes,
                "max_query_rows": normalized_max_query_rows,
                "enabled": "Y",
                "creation_time": datetime.now(timezone.utc),
                "datapull_payload": datapull_payload
            }
            result = datapull_workflows.insert_one(pload)
            mongo_client.close()
            # PyMongo mutates inserted documents with ObjectId; normalize for JSON response.
            response_doc = dict(pload)
            response_doc['_id'] = str(result.inserted_id)
            created_at = response_doc.get('creation_time')
            if hasattr(created_at, 'isoformat'):
                response_doc['creation_time'] = created_at.isoformat()
            return response_doc

        mongo_client.close()
        return None
    except Exception as e:
        print(e)
        return None


def create_datapull(source_name=None, source_description=None, source_category=None, source_type=None, source_template_type=None, scheduled=None, schedule_enabled=None, schedule_interval_min=None, datapull_payload=None, br_score=None, tag=None, selected_enrichments=None, enrichment_enabled=False):
    return create_datapull_workflow(
        source_name=source_name,
        source_description=source_description,
        source_category=source_category,
        source_type=source_type,
        source_template_type=source_template_type,
        scheduled=scheduled,
        schedule_enabled=schedule_enabled,
        schedule_interval_min=schedule_interval_min,
        datapull_payload=datapull_payload,
        br_score=br_score,
        tag=tag,
        selected_enrichments=selected_enrichments,
        enrichment_enabled=enrichment_enabled
    )


def update_active_field_for_all_indicators(mongo_client=None):
    close_client = False
    try:
        if mongo_client is None:
            mongo_client, _ = connect_mongodb()
            close_client = True

        db = mongo_client["byoint_core_data"]
        indicators = db["indicators"]
        indicators.update_many(
            {},
            [{"$set": {
                "active": {
                    "$anyElementTrue": {
                        "$map": {
                            "input": "$sources",
                            "as": "src",
                            "in": "$$src.last_update_status"
                        }
                    }
                }
            }}]
        )

        if close_client:
            mongo_client.close()
    except Exception as e:
        print(f"Error updating active field: {e}")
        if close_client and mongo_client:
            mongo_client.close()


def is_insertmany_enabled_for_source(source):
    """Check the per-workflow 'insertmany' flag (default disabled)."""
    if not source:
        return False
    mongo_client = None
    try:
        mongo_client, _ = connect_mongodb()
        db = mongo_client["byoint_core_data"]
        doc = db["datapull_workflows"].find_one({"source_name": source}, {"insertmany": 1})
        return bool((doc or {}).get("insertmany", False))
    except Exception:
        return False
    finally:
        if mongo_client:
            mongo_client.close()


def bulk_update_indicators(candidates, source, event_time=None):
    """Batched equivalent of update_indicators() for workflows with 'insertmany' enabled.

    candidates: list of (value, indicator_type) tuples.
    Uses one prefetch, one bulk_write, one batched activity-log insert, and a single
    active-field recompute instead of one Mongo round-trip per indicator.
    """
    if not candidates:
        return 0

    cur_dtime = event_time or datetime.now(timezone.utc)
    mongo_client = None
    try:
        mongo_client, _ = connect_mongodb()
        db = mongo_client["byoint_core_data"]
        indicators = db["indicators"]
        workflows = db["datapull_workflows"]

        workflow = workflows.find_one(
            {"source_name": source},
            {"br_score": 1, "tag": 1, "datapull_payload.br_score": 1, "selected_enrichments": 1}
        )
        source_br_score = workflow.get("br_score") if workflow else None
        if source_br_score is None and workflow:
            source_br_score = (workflow.get("datapull_payload") or {}).get("br_score")
        source_tag = str((workflow or {}).get("tag") or "").strip() or None
        source_tags = [source_tag] if source_tag else []
        selected_enrichments = workflow.get("selected_enrichments") if workflow else []
        if not isinstance(selected_enrichments, list):
            selected_enrichments = []

        # De-dupe candidates within this batch (last write wins for the same value/type key).
        unique_pairs = list({(str(value), str(dtype)) for value, dtype in candidates})

        existing_by_key = {}
        if unique_pairs:
            existing_filter = {"$or": [{"value": v, "type": t} for v, t in unique_pairs]}
            for doc in indicators.find(existing_filter, {"value": 1, "type": 1, "firstupdate_time": 1, "e_time": 1, "sources": 1}):
                existing_by_key[(doc.get("value"), doc.get("type"))] = doc

        bulk_ops = []
        for value, dtype in unique_pairs:
            existing_doc = existing_by_key.get((value, dtype))
            indicator_firstupdate_time = cur_dtime
            existing_sources = []
            if isinstance(existing_doc, dict):
                indicator_firstupdate_time = existing_doc.get("firstupdate_time") or existing_doc.get("e_time") or cur_dtime
                existing_sources = existing_doc.get("sources") if isinstance(existing_doc.get("sources"), list) else []

            source_firstupdate_time = indicator_firstupdate_time
            for source_entry in existing_sources:
                if isinstance(source_entry, dict) and str(source_entry.get("source_name") or "").strip() == str(source or "").strip():
                    source_firstupdate_time = source_entry.get("firstupdate_time") or source_entry.get("lastupdate_time") or indicator_firstupdate_time
                    break

            new_source_entry = {
                "source_name": source,
                "firstupdate_time": source_firstupdate_time,
                "lastupdate_time": cur_dtime,
                "last_update_status": True,
                "br_score": source_br_score,
                "tag": source_tags
            }

            merged_sources = []
            source_found = False
            for source_entry in existing_sources:
                if isinstance(source_entry, dict) and str(source_entry.get("source_name") or "").strip() == str(source or "").strip():
                    updated_entry = dict(source_entry)
                    updated_entry.update(new_source_entry)
                    merged_sources.append(updated_entry)
                    source_found = True
                else:
                    merged_sources.append(source_entry)
            if not source_found:
                merged_sources.append(new_source_entry)

            bulk_ops.append(UpdateOne(
                {"value": value, "type": dtype},
                {
                    "$set": {
                        "lastupdate": "Y",
                        "e_time": cur_dtime,
                        "firstupdate_time": indicator_firstupdate_time,
                        "sources": merged_sources
                    },
                    "$setOnInsert": {"active": True}
                },
                upsert=True
            ))

        if not bulk_ops:
            return 0

        bulk_result = indicators.bulk_write(bulk_ops, ordered=False)
        upserted_indexes = set((bulk_result.upserted_ids or {}).keys())

        if is_indicator_logging_enabled():
            log_now = datetime.now(timezone.utc)
            log_docs = [{
                "action": "created" if idx in upserted_indexes else "updated",
                "datapull_source": source,
                "indicator_value": value,
                "indicator_type": dtype,
                "event_time": cur_dtime,
                "logged_at": log_now,
            } for idx, (value, dtype) in enumerate(unique_pairs)]
            try:
                mongo_client["byoint_opslogs"]["indicator_logs"].insert_many(log_docs, ordered=False)
            except Exception as log_error:
                print(f"Error writing batched indicator activity logs: {log_error}")

        for value, dtype in unique_pairs:
            try:
                data_enrichments.enrich_and_update_indicator(
                    value=value,
                    dtype=dtype,
                    mongo_client=mongo_client,
                    selected_enrichment_names=selected_enrichments
                )
            except Exception as enrich_error:
                print(f"Error enriching indicator during bulk update: {enrich_error}")

        update_active_field_for_all_indicators(mongo_client)
        return len(unique_pairs)
    except Exception as e:
        print(f"Error in bulk_update_indicators: {e}")
        return 0
    finally:
        if mongo_client:
            mongo_client.close()


def update_indicators(e_line, indicator_type, cur_dtime, source):
    try:
        mongo_client, _ = connect_mongodb()
        db = mongo_client["byoint_core_data"]
        indicators = db["indicators"]
        workflows = db["datapull_workflows"]

        source_br_score = None
        source_tag = None
        workflow = workflows.find_one(
            {"source_name": source},
            {"br_score": 1, "tag": 1, "datapull_payload.br_score": 1, "selected_enrichments": 1}
        )
        if workflow:
            source_br_score = workflow.get("br_score")
            source_tag = str(workflow.get("tag") or "").strip() or None
            if source_br_score is None:
                payload = workflow.get("datapull_payload", {})
                source_br_score = payload.get("br_score")
        selected_enrichments = workflow.get("selected_enrichments") if workflow else []
        if not isinstance(selected_enrichments, list):
            selected_enrichments = []
        source_tags = [source_tag] if source_tag else []

        existing_doc = indicators.find_one(
            {"value": e_line, "type": indicator_type},
            {"firstupdate_time": 1, "e_time": 1, "sources": 1}
        )

        indicator_firstupdate_time = cur_dtime
        if isinstance(existing_doc, dict):
            indicator_firstupdate_time = (
                existing_doc.get("firstupdate_time")
                or existing_doc.get("e_time")
                or cur_dtime
            )

        source_firstupdate_time = indicator_firstupdate_time
        existing_sources = existing_doc.get("sources") if isinstance(existing_doc, dict) else []
        if isinstance(existing_sources, list):
            for source_entry in existing_sources:
                if not isinstance(source_entry, dict):
                    continue
                if str(source_entry.get("source_name") or "").strip() != str(source or "").strip():
                    continue
                source_firstupdate_time = (
                    source_entry.get("firstupdate_time")
                    or source_entry.get("lastupdate_time")
                    or indicator_firstupdate_time
                )
                break

        # CRITICAL FIX: Merge sources instead of replacing the entire array.
        # This preserves existing sources (dynamic, static, etc.) while updating or adding the current source.
        new_source_entry = {
            "source_name": source,
            "firstupdate_time": source_firstupdate_time,
            "lastupdate_time": cur_dtime,
            "last_update_status": True,
            "br_score": source_br_score,
            "tag": source_tags
        }
        
        # Build merged sources array: update existing source or append new one
        merged_sources = []
        source_found = False
        if isinstance(existing_sources, list):
            for source_entry in existing_sources:
                if isinstance(source_entry, dict) and str(source_entry.get("source_name") or "").strip() == str(source or "").strip():
                    # Update this source entry instead of replacing entire array
                    updated_entry = dict(source_entry)  # Copy existing entry
                    updated_entry.update(new_source_entry)  # Merge new values
                    merged_sources.append(updated_entry)
                    source_found = True
                else:
                    # Preserve other sources
                    merged_sources.append(source_entry)
        
        # If source wasn't found in existing sources, add it as new
        if not source_found:
            merged_sources.append(new_source_entry)

        result = indicators.update_one(
            {"value": e_line, "type": indicator_type},
            {
                "$set": {
                    "lastupdate": "Y",
                    "e_time": cur_dtime,
                    "firstupdate_time": indicator_firstupdate_time,
                    "sources": merged_sources
                },
                "$setOnInsert": {
                    "active": True
                }
            },
            upsert=True
        )
        action = 'created' if result.upserted_id else 'updated'
        log_indicator_activity(
            action=action,
            datapull_source=source,
            indicator_value=e_line,
            indicator_type=indicator_type,
            event_time=cur_dtime,
            mongo_client=mongo_client
        )
        data_enrichments.enrich_and_update_indicator(
            value=e_line,
            dtype=indicator_type,
            mongo_client=mongo_client,
            selected_enrichment_names=selected_enrichments
        )

        update_active_field_for_all_indicators(mongo_client)
        mongo_client.close()
    except Exception as e:
        print(e)


def mark_source_indicators_inactive(source, collect_log='None', dp_log=''):
    if not source:
        return dp_log

    try:
        mongo_client, _ = connect_mongodb()
        db = mongo_client["byoint_core_data"]
        indicators = db["indicators"]

        result = indicators.update_many(
            {"sources.source_name": source},
            {"$set": {"sources.$[elem].last_update_status": False}},
            array_filters=[{"elem.source_name": source}]
        )

        if result.modified_count > 0:
            log_indicator_activity(
                action='deleted',
                datapull_source=source,
                event_time=datetime.now(timezone.utc),
                details={"marked_inactive_count": result.modified_count},
                mongo_client=mongo_client
            )

        update_active_field_for_all_indicators(mongo_client)
        if str(collect_log) in ['summary', 'detailed']:
            dp_log += f"Marked {result.modified_count} existing indicators last Update as false(resetting the last update status)\\n"
        mongo_client.close()
    except Exception as e:
        print(f"Error marking indicators as inactive: {e}")
        if str(collect_log) == 'detailed':
            dp_log += f"Error marking indicators as inactive: {e}\\n"

    return dp_log


DEFAULT_MAX_RESPONSE_BYTES = 50 * 1024 * 1024  # 50 MB; overridable per-workflow or via basicconfigs


def get_max_response_bytes(source=None):
    """Resolve the effective response-size cap: per-workflow override, else global config, else default."""
    if source:
        mongo_client = None
        try:
            mongo_client, _ = connect_mongodb()
            doc = mongo_client["byoint_core_data"]["datapull_workflows"].find_one(
                {"source_name": source}, {"max_response_bytes": 1}
            )
            override = (doc or {}).get("max_response_bytes")
            if override not in [None, '']:
                return max(1, int(override))
        except Exception:
            pass
        finally:
            if mongo_client:
                mongo_client.close()

    try:
        return max(1, int(get_config_value('max_response_bytes', DEFAULT_MAX_RESPONSE_BYTES)))
    except Exception:
        return DEFAULT_MAX_RESPONSE_BYTES


def _check_content_length_header(headers, max_bytes):
    content_length = (headers or {}).get('Content-Length')
    if content_length is None:
        return None
    try:
        if int(content_length) > max_bytes:
            return f"Response too large: Content-Length {content_length} bytes exceeds max_response_bytes limit of {max_bytes} bytes"
    except (TypeError, ValueError):
        pass
    return None


def _read_urlopen_with_limit(stream, max_bytes, chunk_size=65536):
    """Read a urllib response object incrementally, aborting once max_bytes is exceeded."""
    size_error = _check_content_length_header(getattr(stream, 'headers', None), max_bytes)
    if size_error:
        return None, size_error

    total = 0
    chunks = []
    while True:
        chunk = stream.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            return None, f"Response too large: exceeded max_response_bytes limit of {max_bytes} bytes"
        chunks.append(chunk)
    return b"".join(chunks), None


def _read_requests_response_with_limit(response, max_bytes, chunk_size=65536):
    """Read a streaming requests.Response incrementally, aborting once max_bytes is exceeded."""
    size_error = _check_content_length_header(response.headers, max_bytes)
    if size_error:
        return None, size_error

    total = 0
    chunks = []
    for chunk in response.iter_content(chunk_size=chunk_size):
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            return None, f"Response too large: exceeded max_response_bytes limit of {max_bytes} bytes"
        chunks.append(chunk)
    return b"".join(chunks), None


DEFAULT_MAX_QUERY_ROWS = 200000  # cap for DB/Mongo query templates; overridable per-workflow or via basicconfigs


def get_max_query_rows(source=None):
    """Resolve the effective row cap for DB/Mongo query templates: per-workflow override, else global config, else default."""
    if source:
        mongo_client = None
        try:
            mongo_client, _ = connect_mongodb()
            doc = mongo_client["byoint_core_data"]["datapull_workflows"].find_one(
                {"source_name": source}, {"max_query_rows": 1}
            )
            override = (doc or {}).get("max_query_rows")
            if override not in [None, '']:
                return max(1, int(override))
        except Exception:
            pass
        finally:
            if mongo_client:
                mongo_client.close()

    try:
        return max(1, int(get_config_value('max_query_rows', DEFAULT_MAX_QUERY_ROWS)))
    except Exception:
        return DEFAULT_MAX_QUERY_ROWS


def _fetch_cursor_rows_with_limit(cursor, max_rows, batch_size=5000):
    """Fetch DB-API cursor rows incrementally via fetchmany(), aborting once max_rows is exceeded."""
    rows = []
    while True:
        batch = cursor.fetchmany(batch_size)
        if not batch:
            break
        rows.extend(batch)
        if len(rows) > max_rows:
            return None, f"Query result too large: exceeded max_query_rows limit of {max_rows} rows"
    return rows, None


def _fetch_iterable_with_limit(iterable, max_rows):
    """Materialize a MongoDB cursor/iterable incrementally, aborting once max_rows is exceeded."""
    rows = []
    for item in iterable:
        rows.append(item)
        if len(rows) > max_rows:
            return None, f"Query result too large: exceeded max_query_rows limit of {max_rows} rows"
    return rows, None


def url_scraper_v1(url_to_extract=None, initial_insert=0, source=None, timeout=30):
    try:
        extracted_list = []
        dp_log = ''
        collect_log = get_config_value('collect_log', 'None')
        if str(collect_log) in ['summary', 'detailed']:
            dp_log = f"Starting datapull from {url_to_extract} at {datetime.now(timezone.utc)}\\n"

        dp_log = mark_source_indicators_inactive(source, collect_log, dp_log)

        max_bytes = get_max_response_bytes(source)
        u_contents = urlopen(url_to_extract, timeout=timeout)
        content_bytes, size_error = _read_urlopen_with_limit(u_contents, max_bytes)
        u_contents.close()
        if size_error:
            return [], dp_log + f"Error: {size_error}\\n"

        cur_dtime = datetime.now(timezone.utc)
        contents_text = content_bytes.decode("utf-8", errors="replace")

        if str(collect_log) == 'summary':
            dp_log += f"Total Entries fetched from {url_to_extract}: {len(contents_text.splitlines())}\\n"

        batch_buffer = [] if is_insertmany_enabled_for_source(source) else None
        for e_line in contents_text.splitlines():
            detect_dtype = dtype_extractor(e_line, source)
            if batch_buffer is not None:
                batch_buffer.append((e_line, detect_dtype))
            else:
                update_indicators(e_line, detect_dtype, cur_dtime, source)
            extracted_list.append({
                'value': e_line,
                'dtype': detect_dtype,
                'e_time': cur_dtime
            })

        if batch_buffer:
            bulk_update_indicators(batch_buffer, source, cur_dtime)

        return extracted_list, dp_log
    except Exception as e:
        print(e)
        return [], str(e)


def apirequest_bearer_v1(api_url=None, bearer_token=None, source=None, response_key=None, method='GET', request_payload=None, timeout=30, response_mode=None, response_schema=None):
    try:
        extracted_list = []
        dp_log = ''
        collect_log = get_config_value('collect_log', 'None')
        if str(collect_log) == 'summary':
            dp_log = f"Starting API datapull from {api_url} at {datetime.now(timezone.utc)}\\n"
        elif str(collect_log) == 'detailed':
            dp_log = f"Starting API datapull from {api_url} at {datetime.now(timezone.utc)}\\nMethod: {method}\\n"

        if not api_url:
            return extracted_list, dp_log + "Error: api_url is required\\n"
        if not bearer_token:
            return extracted_list, dp_log + "Error: bearer_token is required for authentication\\n"

        dp_log = mark_source_indicators_inactive(source, collect_log, dp_log)

        headers = {'Authorization': f'Bearer {bearer_token}', 'Content-Type': 'application/json'}
        if method.upper() == 'POST':
            response = requests.post(api_url, json=request_payload or {}, headers=headers, timeout=timeout, stream=True)
        else:
            response = requests.get(api_url, headers=headers, timeout=timeout, stream=True)

        response.raise_for_status()
        max_bytes = get_max_response_bytes(source)
        content_bytes, size_error = _read_requests_response_with_limit(response, max_bytes)
        response.close()
        if size_error:
            return [], dp_log + f"Error: {size_error}\\n"
        json_data = json.loads(content_bytes.decode('utf-8', errors='replace'))
        data = json_data[response_key] if response_key and isinstance(json_data, dict) and response_key in json_data else json_data
        cur_dtime = datetime.now(timezone.utc)
        extracted_list = _extract_api_response_indicators(data, source, response_mode=response_mode, response_schema=response_schema)
        for item in extracted_list:
            item['e_time'] = cur_dtime
        if str(collect_log) in ['summary', 'detailed']:
            dp_log += f"Successfully processed {len(extracted_list)} indicators\\n"
        return extracted_list, dp_log
    except requests.exceptions.Timeout:
        return [], f"Error: API request timeout after {timeout} seconds\\n"
    except requests.exceptions.ConnectionError as e:
        return [], f"Error: Connection error: {str(e)}\\n"
    except requests.exceptions.HTTPError as e:
        return [], f"Error: HTTP error: {e.response.status_code} - {e.response.text[:200]}\\n"
    except json.JSONDecodeError as e:
        return [], f"Error: Failed to parse API response as JSON: {str(e)}\\n"
    except Exception as e:
        return [], f"Error: Unexpected error: {str(e)}\\n"


def apirequest_key_v1(api_url=None, api_key=None, source=None, response_key=None, method='GET', request_payload=None, timeout=30, auth_header=None, verify_ssl=True, response_mode=None, response_schema=None):
    try:
        extracted_list = []
        dp_log = ''
        collect_log = get_config_value('collect_log', 'None')
        if str(collect_log) in ['summary', 'detailed']:
            dp_log = f"Starting API datapull from {api_url} at {datetime.now(timezone.utc)}\\n"

        if not api_url:
            return extracted_list, dp_log + "Error: api_url is required\\n"
        if not api_key:
            return extracted_list, dp_log + "Error: api_key is required for authentication\\n"

        dp_log = mark_source_indicators_inactive(source, collect_log, dp_log)

        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        auth_header = str(auth_header or 'X-API-Key').strip()
        if auth_header == 'X-API-Key':
            headers[auth_header] = api_key
        else:
            headers["Authorization"] = api_key

        if method.upper() == 'POST':
            response = requests.post(api_url, json=request_payload or {}, headers=headers, timeout=timeout, verify=verify_ssl, stream=True)
        else:
            response = requests.get(api_url, headers=headers, timeout=timeout, verify=verify_ssl, stream=True)

        response.raise_for_status()
        max_bytes = get_max_response_bytes(source)
        content_bytes, size_error = _read_requests_response_with_limit(response, max_bytes)
        response.close()
        if size_error:
            return [], dp_log + f"Error: {size_error}\\n"
        json_data = json.loads(content_bytes.decode('utf-8', errors='replace'))
        data = json_data[response_key] if response_key and isinstance(json_data, dict) and response_key in json_data else json_data
        cur_dtime = datetime.now(timezone.utc)
        extracted_list = _extract_api_response_indicators(data, source, response_mode=response_mode, response_schema=response_schema)
        for item in extracted_list:
            item['e_time'] = cur_dtime
        if str(collect_log) in ['summary', 'detailed']:
            dp_log += f"Successfully processed {len(extracted_list)} indicators\\n"
        return extracted_list, dp_log
    except requests.exceptions.Timeout:
        return [], f"Error: API request timeout after {timeout} seconds\\n"
    except requests.exceptions.ConnectionError as e:
        return [], f"Error: Connection error: {str(e)}\\n"
    except requests.exceptions.HTTPError as e:
        return [], f"Error: HTTP error: {e.response.status_code} - {e.response.text[:200]}\\n"
    except json.JSONDecodeError as e:
        return [], f"Error: Failed to parse API response as JSON: {str(e)}\\n"
    except Exception as e:
        return [], f"Error: Unexpected error: {str(e)}\\n"


def apirequest_basic_auth_v1(api_url=None, username=None, password=None, username_secret_ref=None, password_secret_ref=None, source=None, response_key=None, method='GET', request_payload=None, timeout=30, verify_ssl=True, response_mode=None, response_schema=None):
    try:
        extracted_list = []
        dp_log = ''
        collect_log = get_config_value('collect_log', 'None')
        if str(collect_log) in ['summary', 'detailed']:
            dp_log = f"Starting API datapull from {api_url} at {datetime.now(timezone.utc)}\\n"

        if not api_url:
            return extracted_list, dp_log + "Error: api_url is required\\n"
        if not username:
            return extracted_list, dp_log + "Error: username is required for basic authentication\\n"
        if password in [None, '']:
            return extracted_list, dp_log + "Error: password is required for basic authentication\\n"

        dp_log = mark_source_indicators_inactive(source, collect_log, dp_log)

        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        auth = (str(username), str(password))

        if method.upper() == 'POST':
            response = requests.post(
                api_url,
                json=request_payload or {},
                headers=headers,
                auth=auth,
                timeout=timeout,
                verify=verify_ssl,
                stream=True
            )
        else:
            response = requests.get(
                api_url,
                headers=headers,
                auth=auth,
                timeout=timeout,
                verify=verify_ssl,
                stream=True
            )

        response.raise_for_status()
        max_bytes = get_max_response_bytes(source)
        content_bytes, size_error = _read_requests_response_with_limit(response, max_bytes)
        response.close()
        if size_error:
            return [], dp_log + f"Error: {size_error}\\n"
        json_data = json.loads(content_bytes.decode('utf-8', errors='replace'))
        data = json_data[response_key] if response_key and isinstance(json_data, dict) and response_key in json_data else json_data
        cur_dtime = datetime.now(timezone.utc)
        extracted_list = _extract_api_response_indicators(data, source, response_mode=response_mode, response_schema=response_schema)
        for item in extracted_list:
            item['e_time'] = cur_dtime
        if str(collect_log) in ['summary', 'detailed']:
            dp_log += f"Successfully processed {len(extracted_list)} indicators\\n"
        return extracted_list, dp_log
    except requests.exceptions.Timeout:
        return [], f"Error: API request timeout after {timeout} seconds\\n"
    except requests.exceptions.ConnectionError as e:
        return [], f"Error: Connection error: {str(e)}\\n"
    except requests.exceptions.HTTPError as e:
        return [], f"Error: HTTP error: {e.response.status_code} - {e.response.text[:200]}\\n"
    except json.JSONDecodeError as e:
        return [], f"Error: Failed to parse API response as JSON: {str(e)}\\n"
    except Exception as e:
        return [], f"Error: Unexpected error: {str(e)}\\n"


MCP_PROTOCOL_VERSION = '2025-06-18'
MCP_TEXT_TOKEN_STRIP = ' \t\r\n,;"\'()[]{}<>`'


def _mcp_parse_jsonrpc_response(response, request_id, max_bytes):
    """Read an MCP Streamable HTTP response (application/json or text/event-stream) and return the JSON-RPC message matching request_id."""
    content_bytes, size_error = _read_requests_response_with_limit(response, max_bytes)
    response.close()
    if size_error:
        raise ValueError(size_error)
    body_text = content_bytes.decode('utf-8', errors='replace')
    content_type = str(response.headers.get('Content-Type') or '').lower()

    if 'text/event-stream' in content_type:
        messages = []
        data_lines = []
        for line in body_text.splitlines() + ['']:
            if line.startswith('data:'):
                data_lines.append(line[5:].lstrip())
            elif line.strip() == '' and data_lines:
                try:
                    messages.append(json.loads('\n'.join(data_lines)))
                except json.JSONDecodeError:
                    pass
                data_lines = []
    else:
        parsed = json.loads(body_text) if body_text.strip() else None
        messages = parsed if isinstance(parsed, list) else [parsed]

    for message in messages:
        if isinstance(message, dict) and message.get('id') == request_id:
            if message.get('error'):
                error = message.get('error') or {}
                raise ValueError(f"MCP error {error.get('code')}: {error.get('message')}")
            return message.get('result') or {}
    raise ValueError(f"No JSON-RPC response with id {request_id} received from MCP endpoint")


def _mcp_tool_result_to_data(tool_result):
    """Flatten an MCP tools/call result into JSON-like data for indicator extraction."""
    if tool_result.get('structuredContent') is not None:
        return tool_result.get('structuredContent')

    data = []
    for item in tool_result.get('content') or []:
        if not isinstance(item, dict):
            continue
        if item.get('type') == 'text':
            text = str(item.get('text') or '')
        elif item.get('type') == 'resource' and isinstance(item.get('resource'), dict):
            text = str(item['resource'].get('text') or '')
        else:
            continue
        try:
            data.append(json.loads(text))
        except (json.JSONDecodeError, ValueError):
            # Free text: split into tokens so embedded indicators can match the anchored dtype regexes.
            tokens = [token.strip(MCP_TEXT_TOKEN_STRIP) for token in text.split()]
            data.extend(token for token in tokens if token)
    return data


def mcp_tool_call_v1(mcp_url=None, tool_name=None, tool_arguments=None, auth_token=None, auth_token_secret_ref=None, source=None, timeout=30, verify_ssl=True, response_mode=None, response_schema=None, **kwargs):
    try:
        extracted_list = []
        dp_log = ''
        collect_log = get_config_value('collect_log', 'None')
        if str(collect_log) in ['summary', 'detailed']:
            dp_log = f"Starting MCP datapull from {mcp_url} (tool: {tool_name}) at {datetime.now(timezone.utc)}\\n"

        if not mcp_url:
            return extracted_list, dp_log + "Error: mcp_url is required\\n"
        if not tool_name:
            return extracted_list, dp_log + "Error: tool_name is required\\n"

        arguments = tool_arguments
        if isinstance(arguments, str):
            arguments = json.loads(arguments) if arguments.strip() else {}
        if arguments in [None, '']:
            arguments = {}
        if not isinstance(arguments, dict):
            return extracted_list, dp_log + "Error: tool_arguments must be a JSON object\\n"

        if isinstance(verify_ssl, str):
            verify_ssl = verify_ssl.strip().lower() not in ['false', '0', 'no', 'off']
        try:
            timeout = int(timeout or 30)
        except Exception:
            timeout = 30

        dp_log = mark_source_indicators_inactive(source, collect_log, dp_log)

        max_bytes = get_max_response_bytes(source)
        headers = {
            'Accept': 'application/json, text/event-stream',
            'Content-Type': 'application/json',
        }
        if auth_token:
            headers['Authorization'] = f'Bearer {auth_token}'

        def _post(message):
            return requests.post(mcp_url, json=message, headers=headers, timeout=timeout, verify=verify_ssl, stream=True)

        init_response = _post({
            'jsonrpc': '2.0',
            'id': 1,
            'method': 'initialize',
            'params': {
                'protocolVersion': MCP_PROTOCOL_VERSION,
                'capabilities': {},
                'clientInfo': {'name': 'byoint-datapull', 'version': '1.0'},
            },
        })
        init_response.raise_for_status()
        session_id = init_response.headers.get('Mcp-Session-Id')
        init_result = _mcp_parse_jsonrpc_response(init_response, 1, max_bytes)
        if session_id:
            headers['Mcp-Session-Id'] = session_id
        headers['MCP-Protocol-Version'] = str(init_result.get('protocolVersion') or MCP_PROTOCOL_VERSION)
        if str(collect_log) == 'detailed':
            server_info = init_result.get('serverInfo') or {}
            dp_log += f"MCP server: {server_info.get('name')} {server_info.get('version') or ''} (protocol {headers['MCP-Protocol-Version']})\\n"

        _post({'jsonrpc': '2.0', 'method': 'notifications/initialized'}).close()

        call_response = _post({
            'jsonrpc': '2.0',
            'id': 2,
            'method': 'tools/call',
            'params': {'name': str(tool_name).strip(), 'arguments': arguments},
        })
        call_response.raise_for_status()
        tool_result = _mcp_parse_jsonrpc_response(call_response, 2, max_bytes)

        if session_id:
            try:
                requests.delete(mcp_url, headers=headers, timeout=timeout, verify=verify_ssl).close()
            except Exception:
                pass

        data = _mcp_tool_result_to_data(tool_result)
        if tool_result.get('isError'):
            return [], dp_log + f"Error: MCP tool '{tool_name}' returned an error: {str(data)[:500]}\\n"

        cur_dtime = datetime.now(timezone.utc)
        extracted_list = _extract_api_response_indicators(data, source, response_mode=response_mode, response_schema=response_schema)
        for item in extracted_list:
            item['e_time'] = cur_dtime
        if str(collect_log) in ['summary', 'detailed']:
            dp_log += f"Successfully processed {len(extracted_list)} indicators\\n"
        return extracted_list, dp_log
    except requests.exceptions.Timeout:
        return [], f"Error: MCP request timeout after {timeout} seconds\\n"
    except requests.exceptions.ConnectionError as e:
        return [], f"Error: Connection error: {str(e)}\\n"
    except requests.exceptions.HTTPError as e:
        return [], f"Error: HTTP error: {e.response.status_code} - {e.response.text[:200]}\\n"
    except json.JSONDecodeError as e:
        return [], f"Error: Failed to parse MCP response or tool_arguments as JSON: {str(e)}\\n"
    except Exception as e:
        return [], f"Error: Unexpected error: {str(e)}\\n"


def mysql_query_v1(db_host=None, db_port=3306, db_name=None, db_user=None, db_password=None, db_query=None, source=None, query_params=None, timeout=30, **kwargs):
    try:
        extracted_list = []
        dp_log = ''
        collect_log = get_config_value('collect_log', 'None')
        if str(collect_log) in ['summary', 'detailed']:
            dp_log = f"Starting MySQL/MariaDB datapull from {db_host}:{db_port}/{db_name} at {datetime.now(timezone.utc)}\\n"

        if not db_host:
            return extracted_list, dp_log + "Error: db_host is required\\n"
        if not db_name:
            return extracted_list, dp_log + "Error: db_name is required\\n"
        if not db_user:
            return extracted_list, dp_log + "Error: db_user is required\\n"
        if db_password in [None, '']:
            return extracted_list, dp_log + "Error: db_password is required\\n"
        if not db_query:
            return extracted_list, dp_log + "Error: db_query is required\\n"

        dp_log = mark_source_indicators_inactive(source, collect_log, dp_log)

        try:
            import pymysql
        except Exception:
            return [], dp_log + "Error: PyMySQL dependency not installed. Add 'pymysql' to requirements.\\n"

        try:
            db_port = int(db_port or 3306)
        except Exception:
            db_port = 3306

        connection = pymysql.connect(
            host=str(db_host).strip(),
            port=db_port,
            user=str(db_user).strip(),
            password=str(db_password),
            database=str(db_name).strip(),
            connect_timeout=int(timeout or 30),
            read_timeout=int(timeout or 30),
            write_timeout=int(timeout or 30),
            cursorclass=pymysql.cursors.DictCursor,
        )

        cur_dtime = datetime.now(timezone.utc)
        try:
            with connection.cursor() as cursor:
                params = query_params if isinstance(query_params, (list, tuple, dict)) else None
                if params is None:
                    cursor.execute(db_query)
                else:
                    cursor.execute(db_query, params)

                if cursor.description:
                    rows, row_error = _fetch_cursor_rows_with_limit(cursor, get_max_query_rows(source))
                    if row_error:
                        return [], dp_log + f"Error: {row_error}\\n"
                else:
                    connection.commit()
                    rows = []
        finally:
            connection.close()

        batch_buffer = [] if is_insertmany_enabled_for_source(source) else None

        def walk_and_collect(node):
            if isinstance(node, dict):
                for _, value in node.items():
                    walk_and_collect(value)
                return
            if isinstance(node, list):
                for element in node:
                    walk_and_collect(element)
                return
            if isinstance(node, tuple):
                for element in node:
                    walk_and_collect(element)
                return
            candidate = str(node)
            detect_dtype = dtype_extractor(candidate, source)
            if not detect_dtype:
                return
            if batch_buffer is not None:
                batch_buffer.append((candidate, detect_dtype))
            else:
                update_indicators(candidate, detect_dtype, cur_dtime, source)
            extracted_list.append({'value': candidate, 'dtype': detect_dtype, 'e_time': cur_dtime})

        walk_and_collect(rows)
        if batch_buffer:
            bulk_update_indicators(batch_buffer, source, cur_dtime)

        if str(collect_log) in ['summary', 'detailed']:
            dp_log += f"Rows fetched: {len(rows)}\\n"
            dp_log += f"Successfully processed {len(extracted_list)} indicators\\n"

        return extracted_list, dp_log
    except Exception as e:
        return [], f"Error: Unexpected error: {str(e)}\\n"


def mssql_query_v1(db_host=None, db_port=1433, db_name=None, db_user=None, db_password=None, db_query=None, source=None, query_params=None, timeout=30, **kwargs):
    try:
        extracted_list = []
        dp_log = ''
        collect_log = get_config_value('collect_log', 'None')
        if str(collect_log) in ['summary', 'detailed']:
            dp_log = f"Starting MSSQL datapull from {db_host}:{db_port}/{db_name} at {datetime.now(timezone.utc)}\\n"

        if not db_host:
            return extracted_list, dp_log + "Error: db_host is required\\n"
        if not db_name:
            return extracted_list, dp_log + "Error: db_name is required\\n"
        if not db_user:
            return extracted_list, dp_log + "Error: db_user is required\\n"
        if db_password in [None, '']:
            return extracted_list, dp_log + "Error: db_password is required\\n"
        if not db_query:
            return extracted_list, dp_log + "Error: db_query is required\\n"

        dp_log = mark_source_indicators_inactive(source, collect_log, dp_log)

        try:
            import pymssql
        except Exception:
            return [], dp_log + "Error: pymssql dependency not installed. Add 'pymssql' to requirements.\\n"

        try:
            db_port = int(db_port or 1433)
        except Exception:
            db_port = 1433

        connection = pymssql.connect(
            server=str(db_host).strip(),
            port=db_port,
            user=str(db_user).strip(),
            password=str(db_password),
            database=str(db_name).strip(),
            login_timeout=int(timeout or 30),
            timeout=int(timeout or 30),
            as_dict=True,
        )

        cur_dtime = datetime.now(timezone.utc)
        try:
            with connection.cursor() as cursor:
                params = query_params if isinstance(query_params, (list, tuple, dict)) else None
                if params is None:
                    cursor.execute(db_query)
                else:
                    cursor.execute(db_query, params)

                if cursor.description:
                    rows, row_error = _fetch_cursor_rows_with_limit(cursor, get_max_query_rows(source))
                    if row_error:
                        return [], dp_log + f"Error: {row_error}\\n"
                else:
                    connection.commit()
                    rows = []
        finally:
            connection.close()

        batch_buffer = [] if is_insertmany_enabled_for_source(source) else None

        def walk_and_collect(node):
            if isinstance(node, dict):
                for _, value in node.items():
                    walk_and_collect(value)
                return
            if isinstance(node, list):
                for element in node:
                    walk_and_collect(element)
                return
            if isinstance(node, tuple):
                for element in node:
                    walk_and_collect(element)
                return
            candidate = str(node)
            detect_dtype = dtype_extractor(candidate, source)
            if not detect_dtype:
                return
            if batch_buffer is not None:
                batch_buffer.append((candidate, detect_dtype))
            else:
                update_indicators(candidate, detect_dtype, cur_dtime, source)
            extracted_list.append({'value': candidate, 'dtype': detect_dtype, 'e_time': cur_dtime})

        walk_and_collect(rows)
        if batch_buffer:
            bulk_update_indicators(batch_buffer, source, cur_dtime)

        if str(collect_log) in ['summary', 'detailed']:
            dp_log += f"Rows fetched: {len(rows)}\\n"
            dp_log += f"Successfully processed {len(extracted_list)} indicators\\n"

        return extracted_list, dp_log
    except Exception as e:
        return [], f"Error: Unexpected error: {str(e)}\\n"


def oracle_query_v1(db_host=None, db_port=1521, db_name=None, db_user=None, db_password=None, db_query=None, source=None, query_params=None, timeout=30, **kwargs):
    try:
        extracted_list = []
        dp_log = ''
        collect_log = get_config_value('collect_log', 'None')
        if str(collect_log) in ['summary', 'detailed']:
            dp_log = f"Starting Oracle datapull from {db_host}:{db_port}/{db_name} at {datetime.now(timezone.utc)}\\n"

        if not db_host:
            return extracted_list, dp_log + "Error: db_host is required\\n"
        if not db_name:
            return extracted_list, dp_log + "Error: db_name is required\\n"
        if not db_user:
            return extracted_list, dp_log + "Error: db_user is required\\n"
        if db_password in [None, '']:
            return extracted_list, dp_log + "Error: db_password is required\\n"
        if not db_query:
            return extracted_list, dp_log + "Error: db_query is required\\n"

        dp_log = mark_source_indicators_inactive(source, collect_log, dp_log)

        try:
            import oracledb
        except Exception:
            return [], dp_log + "Error: oracledb dependency not installed. Add 'oracledb' to requirements.\\n"

        try:
            db_port = int(db_port or 1521)
        except Exception:
            db_port = 1521

        dsn = oracledb.makedsn(str(db_host).strip(), db_port, service_name=str(db_name).strip())
        connection = oracledb.connect(
            user=str(db_user).strip(),
            password=str(db_password),
            dsn=dsn,
            tcp_connect_timeout=int(timeout or 30),
        )
        try:
            connection.call_timeout = int(timeout or 30) * 1000
        except Exception:
            pass

        cur_dtime = datetime.now(timezone.utc)
        try:
            with connection.cursor() as cursor:
                params = query_params if isinstance(query_params, (list, tuple, dict)) else None
                if params is None:
                    cursor.execute(db_query)
                else:
                    cursor.execute(db_query, params)

                if cursor.description:
                    rows, row_error = _fetch_cursor_rows_with_limit(cursor, get_max_query_rows(source))
                    if row_error:
                        return [], dp_log + f"Error: {row_error}\\n"
                else:
                    connection.commit()
                    rows = []
        finally:
            connection.close()

        batch_buffer = [] if is_insertmany_enabled_for_source(source) else None

        def walk_and_collect(node):
            if isinstance(node, dict):
                for _, value in node.items():
                    walk_and_collect(value)
                return
            if isinstance(node, list):
                for element in node:
                    walk_and_collect(element)
                return
            if isinstance(node, tuple):
                for element in node:
                    walk_and_collect(element)
                return
            candidate = str(node)
            detect_dtype = dtype_extractor(candidate, source)
            if not detect_dtype:
                return
            if batch_buffer is not None:
                batch_buffer.append((candidate, detect_dtype))
            else:
                update_indicators(candidate, detect_dtype, cur_dtime, source)
            extracted_list.append({'value': candidate, 'dtype': detect_dtype, 'e_time': cur_dtime})

        walk_and_collect(rows)
        if batch_buffer:
            bulk_update_indicators(batch_buffer, source, cur_dtime)

        if str(collect_log) in ['summary', 'detailed']:
            dp_log += f"Rows fetched: {len(rows)}\\n"
            dp_log += f"Successfully processed {len(extracted_list)} indicators\\n"

        return extracted_list, dp_log
    except Exception as e:
        return [], f"Error: Unexpected error: {str(e)}\\n"


def postgresql_query_v1(db_host=None, db_port=5432, db_name=None, db_user=None, db_password=None, db_query=None, source=None, query_params=None, timeout=30, **kwargs):
    try:
        extracted_list = []
        dp_log = ''
        collect_log = get_config_value('collect_log', 'None')
        if str(collect_log) in ['summary', 'detailed']:
            dp_log = f"Starting PostgreSQL datapull from {db_host}:{db_port}/{db_name} at {datetime.now(timezone.utc)}\\n"

        if not db_host:
            return extracted_list, dp_log + "Error: db_host is required\\n"
        if not db_name:
            return extracted_list, dp_log + "Error: db_name is required\\n"
        if not db_user:
            return extracted_list, dp_log + "Error: db_user is required\\n"
        if db_password in [None, '']:
            return extracted_list, dp_log + "Error: db_password is required\\n"
        if not db_query:
            return extracted_list, dp_log + "Error: db_query is required\\n"

        dp_log = mark_source_indicators_inactive(source, collect_log, dp_log)

        try:
            import psycopg2
            import psycopg2.extras
        except Exception:
            return [], dp_log + "Error: psycopg2 dependency not installed. Add 'psycopg2-binary' to requirements.\\n"

        try:
            db_port = int(db_port or 5432)
        except Exception:
            db_port = 5432

        connection = psycopg2.connect(
            host=str(db_host).strip(),
            port=db_port,
            dbname=str(db_name).strip(),
            user=str(db_user).strip(),
            password=str(db_password),
            connect_timeout=int(timeout or 30),
        )
        connection.autocommit = False

        cur_dtime = datetime.now(timezone.utc)
        try:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                params = query_params if isinstance(query_params, (list, tuple, dict)) else None
                if params is None:
                    cursor.execute(db_query)
                else:
                    cursor.execute(db_query, params)

                if cursor.description:
                    rows, row_error = _fetch_cursor_rows_with_limit(cursor, get_max_query_rows(source))
                    if row_error:
                        return [], dp_log + f"Error: {row_error}\\n"
                else:
                    connection.commit()
                    rows = []
        finally:
            connection.close()

        batch_buffer = [] if is_insertmany_enabled_for_source(source) else None

        def walk_and_collect(node):
            if isinstance(node, dict):
                for _, value in node.items():
                    walk_and_collect(value)
                return
            if isinstance(node, list):
                for element in node:
                    walk_and_collect(element)
                return
            if isinstance(node, tuple):
                for element in node:
                    walk_and_collect(element)
                return
            candidate = str(node)
            detect_dtype = dtype_extractor(candidate, source)
            if not detect_dtype:
                return
            if batch_buffer is not None:
                batch_buffer.append((candidate, detect_dtype))
            else:
                update_indicators(candidate, detect_dtype, cur_dtime, source)
            extracted_list.append({'value': candidate, 'dtype': detect_dtype, 'e_time': cur_dtime})

        walk_and_collect(rows)
        if batch_buffer:
            bulk_update_indicators(batch_buffer, source, cur_dtime)

        if str(collect_log) in ['summary', 'detailed']:
            dp_log += f"Rows fetched: {len(rows)}\\n"
            dp_log += f"Successfully processed {len(extracted_list)} indicators\\n"

        return extracted_list, dp_log
    except Exception as e:
        return [], f"Error: Unexpected error: {str(e)}\\n"


def mongodb_query_v1(db_host=None, db_port=27017, db_name=None, db_collection=None, db_user=None, db_password=None, db_query=None, source=None, query_params=None, timeout=30, **kwargs):
    try:
        extracted_list = []
        dp_log = ''
        collect_log = get_config_value('collect_log', 'None')
        if str(collect_log) in ['summary', 'detailed']:
            dp_log = f"Starting MongoDB datapull from {db_host}:{db_port}/{db_name}.{db_collection} at {datetime.now(timezone.utc)}\n"

        if not db_host:
            return extracted_list, dp_log + "Error: db_host is required\n"
        if not db_name:
            return extracted_list, dp_log + "Error: db_name is required\n"
        if not db_collection:
            return extracted_list, dp_log + "Error: db_collection is required\n"
        if not db_user:
            return extracted_list, dp_log + "Error: db_user is required\n"
        if db_password in [None, '']:
            return extracted_list, dp_log + "Error: db_password is required\n"
        if db_query in [None, '']:
            return extracted_list, dp_log + "Error: db_query is required\n"

        dp_log = mark_source_indicators_inactive(source, collect_log, dp_log)

        try:
            import pymongo
        except Exception:
            return [], dp_log + "Error: pymongo dependency not installed. Add 'pymongo' to requirements.\n"

        try:
            db_port = int(db_port or 27017)
        except Exception:
            db_port = 27017

        auth_source = str(kwargs.get('auth_source') or kwargs.get('db_auth_source') or db_name or 'admin').strip() or 'admin'
        connect_timeout_ms = max(1, int(timeout or 30)) * 1000
        mongo_uri = (
            f"mongodb://{str(db_user).strip()}:{str(db_password)}"
            f"@{str(db_host).strip()}:{db_port}/{str(db_name).strip()}"
            f"?authSource={auth_source}"
        )
        client = pymongo.MongoClient(
            mongo_uri,
            serverSelectionTimeoutMS=connect_timeout_ms,
            connectTimeoutMS=connect_timeout_ms,
            socketTimeoutMS=connect_timeout_ms,
        )

        cur_dtime = datetime.now(timezone.utc)
        try:
            db = client[str(db_name).strip()]
            collection = db[str(db_collection).strip()]

            query_spec = db_query
            if isinstance(db_query, str):
                query_text = str(db_query).strip()
                try:
                    query_spec = json.loads(query_text)
                except Exception:
                    return [], dp_log + "Error: db_query must be valid JSON when passed as a string\n"

            if isinstance(query_spec, list):
                rows, row_error = _fetch_iterable_with_limit(collection.aggregate(query_spec, allowDiskUse=True), get_max_query_rows(source))
                if row_error:
                    return [], dp_log + f"Error: {row_error}\n"
            elif isinstance(query_spec, dict):
                projection = kwargs.get('projection')
                if not isinstance(projection, (dict, list, tuple)):
                    projection = None

                cursor = collection.find(query_spec, projection)

                sort_value = kwargs.get('sort')
                if isinstance(sort_value, (list, tuple)) and sort_value:
                    cursor = cursor.sort(list(sort_value))

                limit_value = kwargs.get('limit')
                if limit_value not in [None, '']:
                    try:
                        cursor = cursor.limit(max(1, int(limit_value)))
                    except Exception:
                        pass

                rows, row_error = _fetch_iterable_with_limit(cursor, get_max_query_rows(source))
                if row_error:
                    return [], dp_log + f"Error: {row_error}\n"
            else:
                return [], dp_log + "Error: db_query must be a JSON object or JSON array\n"
        finally:
            client.close()

        batch_buffer = [] if is_insertmany_enabled_for_source(source) else None

        def walk_and_collect(node):
            if isinstance(node, dict):
                for _, value in node.items():
                    walk_and_collect(value)
                return
            if isinstance(node, list):
                for element in node:
                    walk_and_collect(element)
                return
            if isinstance(node, tuple):
                for element in node:
                    walk_and_collect(element)
                return
            candidate = str(node)
            detect_dtype = dtype_extractor(candidate, source)
            if not detect_dtype:
                return
            if batch_buffer is not None:
                batch_buffer.append((candidate, detect_dtype))
            else:
                update_indicators(candidate, detect_dtype, cur_dtime, source)
            extracted_list.append({'value': candidate, 'dtype': detect_dtype, 'e_time': cur_dtime})

        walk_and_collect(rows)
        if batch_buffer:
            bulk_update_indicators(batch_buffer, source, cur_dtime)

        if str(collect_log) in ['summary', 'detailed']:
            dp_log += f"Rows fetched: {len(rows)}\n"
            dp_log += f"Successfully processed {len(extracted_list)} indicators\n"

        return extracted_list, dp_log
    except Exception as e:
        return [], f"Error: Unexpected error: {str(e)}\n"


def _ldap_attribute_values(value):
    """Normalize an ldap3 attribute value to a list of strings, dropping binary values (objectSid, objectGUID, ...)."""
    values = value if isinstance(value, (list, tuple)) else [value]
    normalized = []
    for item in values:
        if item is None or isinstance(item, (bytes, bytearray)):
            continue
        text = str(item).strip()
        if text:
            normalized.append(text)
    return normalized


def ldap_search_v1(ldap_server=None, bind_dn=None, bind_password=None, base_dn=None, search_filter=None, attributes=None, search_scope='SUBTREE', start_tls=False, verify_ssl=True, page_size=1000, source=None, timeout=30, **kwargs):
    try:
        extracted_list = []
        dp_log = ''
        collect_log = get_config_value('collect_log', 'None')
        if str(collect_log) in ['summary', 'detailed']:
            dp_log = f"Starting LDAP datapull from {ldap_server} (base: {base_dn}) at {datetime.now(timezone.utc)}\\n"

        if not ldap_server:
            return extracted_list, dp_log + "Error: ldap_server is required\\n"
        if not bind_dn:
            return extracted_list, dp_log + "Error: bind_dn is required\\n"
        if bind_password in [None, '']:
            return extracted_list, dp_log + "Error: bind_password is required\\n"
        if not base_dn:
            return extracted_list, dp_log + "Error: base_dn is required\\n"
        if not search_filter:
            return extracted_list, dp_log + "Error: search_filter is required\\n"

        if isinstance(attributes, str):
            attribute_list = [a.strip() for a in attributes.split(',') if a.strip()]
        elif isinstance(attributes, (list, tuple)):
            attribute_list = [str(a).strip() for a in attributes if str(a).strip()]
        else:
            attribute_list = []
        if not attribute_list:
            return extracted_list, dp_log + "Error: attributes is required (comma-separated, e.g. dNSHostName,cn)\\n"

        try:
            from ldap3 import Server, Connection, Tls, SUBTREE, LEVEL, BASE
            import ssl
        except Exception:
            return [], dp_log + "Error: ldap3 dependency not installed. Add 'ldap3' to requirements.\\n"

        scope_map = {'SUBTREE': SUBTREE, 'LEVEL': LEVEL, 'ONE': LEVEL, 'BASE': BASE}
        scope_key = str(search_scope or 'SUBTREE').strip().upper()
        if scope_key not in scope_map:
            return extracted_list, dp_log + "Error: search_scope must be one of SUBTREE, LEVEL, BASE\\n"

        try:
            timeout = int(timeout or 30)
        except Exception:
            timeout = 30
        try:
            page_size = max(1, int(page_size or 1000))
        except Exception:
            page_size = 1000

        server_url = str(ldap_server).strip()
        use_ldaps = server_url.lower().startswith('ldaps://')
        tls = Tls(validate=ssl.CERT_REQUIRED if _to_bool(verify_ssl) else ssl.CERT_NONE)
        server = Server(server_url, use_ssl=use_ldaps, tls=tls, connect_timeout=timeout)
        connection = Connection(
            server,
            user=str(bind_dn).strip(),
            password=str(bind_password),
            receive_timeout=timeout,
            read_only=True,
            auto_bind=False,
        )

        max_rows = get_max_query_rows(source)
        rows = []
        try:
            connection.open()
            # StartTLS only applies to plain ldap:// connections; ldaps:// is already encrypted.
            if _to_bool(start_tls) and not use_ldaps:
                if not connection.start_tls():
                    return [], dp_log + f"Error: StartTLS failed: {connection.result}\\n"
            if not connection.bind():
                return [], dp_log + f"Error: LDAP bind failed: {connection.result.get('description')} {connection.result.get('message') or ''}\\n"

            entries = connection.extend.standard.paged_search(
                search_base=str(base_dn).strip(),
                search_filter=str(search_filter).strip(),
                search_scope=scope_map[scope_key],
                attributes=attribute_list,
                paged_size=page_size,
                generator=True,
            )
            for entry in entries:
                if entry.get('type') != 'searchResEntry':
                    continue
                row = {}
                for attr_name, attr_value in (entry.get('attributes') or {}).items():
                    values = _ldap_attribute_values(attr_value)
                    if values:
                        row[attr_name] = values
                rows.append(row)
                if len(rows) > max_rows:
                    return [], dp_log + f"Error: Query result too large: exceeded max_query_rows limit of {max_rows} rows\\n"
        finally:
            try:
                connection.unbind()
            except Exception:
                pass

        # Only reset existing indicators once the bind and search have succeeded.
        dp_log = mark_source_indicators_inactive(source, collect_log, dp_log)

        cur_dtime = datetime.now(timezone.utc)
        extracted_list = _extract_api_response_indicators(rows, source)
        for item in extracted_list:
            item['e_time'] = cur_dtime

        if str(collect_log) in ['summary', 'detailed']:
            dp_log += f"Entries fetched: {len(rows)}\\n"
            dp_log += f"Successfully processed {len(extracted_list)} indicators\\n"

        return extracted_list, dp_log
    except Exception as e:
        return [], f"Error: Unexpected error: {str(e)}\\n"


# --- Datapull Secret Functions ---
def get_datapull_core_config():
    mongo_client = None
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_config"]
        basicconfigs_collection = db["basicconfigs"]
        return basicconfigs_collection.find_one({"module": "core"})
    except Exception as e:
        print(f"Error fetching datapull core config: {e}")
        return None
    finally:
        if mongo_client:
            mongo_client.close()


load_datapull_core_config()


def create_datapull_secret(name, secret_value, created_by=None, description=None):
    mongo_client = None
    try:
        if not name or secret_value is None:
            return None, "name and secret_value are required"

        now = all_connects._utc_now()
        encrypted = all_connects._encrypt_datapull_secret_value(secret_value)
        import secrets
        secret_ref = f"sec_{secrets.token_urlsafe(12)}"

        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_config"]
        secrets_col = db["datapull_secrets"]
        secrets_col.create_index("secret_ref", unique=True)
        secrets_col.create_index("name", unique=True)

        if secrets_col.find_one({"name": str(name).strip()}):
            return None, "Secret name already exists"

        doc = {
            "secret_ref": secret_ref,
            "name": str(name).strip(),
            "description": description,
            "created_by": created_by,
            "created_at": now,
            "updated_at": now,
            "active": True,
            "version": 1,
            "algorithm": encrypted.get("algorithm"),
            "nonce": encrypted.get("nonce"),
            "ciphertext": encrypted.get("ciphertext")
        }
        secrets_col.insert_one(doc)

        return {
            "secret_ref": doc.get("secret_ref"),
            "name": doc.get("name"),
            "description": doc.get("description"),
            "created_by": doc.get("created_by"),
            "created_at": doc.get("created_at"),
            "updated_at": doc.get("updated_at"),
            "active": doc.get("active"),
            "version": doc.get("version")
        }, None
    except Exception as e:
        print(e)
        return None, str(e)
    finally:
        if mongo_client:
            mongo_client.close()


def _collect_payload_secret_refs(payload, refs_set):
    if isinstance(payload, dict):
        for key, value in payload.items():
            field_name = str(key or '').strip()
            if field_name.endswith('_secret_ref'):
                normalized_ref = str(value or '').strip()
                if normalized_ref.startswith('sec_'):
                    refs_set.add(normalized_ref)
            _collect_payload_secret_refs(value, refs_set)
        return

    if isinstance(payload, list):
        for item in payload:
            _collect_payload_secret_refs(item, refs_set)


def list_datapull_secrets(include_usage=False):
    mongo_client = None
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        config_db = mongo_client["byoint_core_config"]
        secrets_col = config_db["datapull_secrets"]

        usage_map = {}
        if include_usage:
            core_db = mongo_client["byoint_core_data"]
            workflows_col = core_db["datapull_workflows"]

            for workflow in workflows_col.find({}, {"source_name": 1, "datapull_payload": 1}):
                source_name = str(workflow.get("source_name") or "unknown_source")
                refs = set()
                _collect_payload_secret_refs(workflow.get("datapull_payload"), refs)
                for secret_ref in refs:
                    usage_map.setdefault(secret_ref, set()).add(source_name)

        out = []
        for doc in secrets_col.find({}, {"ciphertext": 0, "nonce": 0}).sort("name", 1):
            created_at = doc.get("created_at")
            updated_at = doc.get("updated_at")
            secret_ref = doc.get("secret_ref")
            used_by_sources = sorted(list(usage_map.get(secret_ref, set())), key=lambda value: str(value).lower()) if include_usage else []
            out.append({
                "secret_ref": secret_ref,
                "name": doc.get("name"),
                "description": doc.get("description"),
                "created_by": doc.get("created_by"),
                "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else created_at,
                "updated_at": updated_at.isoformat() if hasattr(updated_at, "isoformat") else updated_at,
                "active": bool(doc.get("active", True)),
                "version": doc.get("version", 1),
                "where_used_count": len(used_by_sources),
                "where_used_sources": used_by_sources
            })

        return out, None
    except Exception as e:
        print(e)
        return [], str(e)
    finally:
        if mongo_client:
            mongo_client.close()


def get_datapull_secret_by_name(name):
    mongo_client = None
    try:
        if not name:
            return None, "name is required"

        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_config"]
        secrets_col = db["datapull_secrets"]
        doc = secrets_col.find_one({"name": str(name).strip()}, {"ciphertext": 0, "nonce": 0})
        if not doc:
            return None, "Secret not found"

        created_at = doc.get("created_at")
        updated_at = doc.get("updated_at")
        return {
            "secret_ref": doc.get("secret_ref"),
            "name": doc.get("name"),
            "description": doc.get("description"),
            "created_by": doc.get("created_by"),
            "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else created_at,
            "updated_at": updated_at.isoformat() if hasattr(updated_at, "isoformat") else updated_at,
            "active": bool(doc.get("active", True)),
            "version": doc.get("version", 1)
        }, None
    except Exception as e:
        print(e)
        return None, str(e)
    finally:
        if mongo_client:
            mongo_client.close()


def rotate_datapull_secret(secret_ref, new_secret_value, rotated_by=None):
    mongo_client = None
    try:
        if not secret_ref or new_secret_value in [None, '']:
            return None, "secret_ref and new_secret_value are required"

        now = all_connects._utc_now()
        encrypted = all_connects._encrypt_datapull_secret_value(new_secret_value)

        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_config"]
        secrets_col = db["datapull_secrets"]

        current_doc = secrets_col.find_one({"secret_ref": str(secret_ref).strip(), "active": True})
        if not current_doc:
            return None, "Secret not found or inactive"

        current_version = int(current_doc.get("version", 1))
        previous_version_entry = {
            "version": current_version,
            "algorithm": current_doc.get("algorithm"),
            "nonce": current_doc.get("nonce"),
            "ciphertext": current_doc.get("ciphertext"),
            "rotated_at": now,
            "rotated_by": rotated_by
        }

        secrets_col.update_one(
            {"_id": current_doc.get("_id")},
            {
                "$set": {
                    "algorithm": encrypted.get("algorithm"),
                    "nonce": encrypted.get("nonce"),
                    "ciphertext": encrypted.get("ciphertext"),
                    "version": current_version + 1,
                    "updated_at": now,
                    "rotated_by": rotated_by
                },
                "$push": {
                    "previous_versions": previous_version_entry
                }
            }
        )

        updated_doc = secrets_col.find_one({"_id": current_doc.get("_id")}, {"ciphertext": 0, "nonce": 0})
        created_at = updated_doc.get("created_at") if updated_doc else None
        updated_at = updated_doc.get("updated_at") if updated_doc else None
        return {
            "secret_ref": updated_doc.get("secret_ref") if updated_doc else str(secret_ref).strip(),
            "name": updated_doc.get("name") if updated_doc else None,
            "description": updated_doc.get("description") if updated_doc else None,
            "created_by": updated_doc.get("created_by") if updated_doc else None,
            "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else created_at,
            "updated_at": updated_at.isoformat() if hasattr(updated_at, "isoformat") else updated_at,
            "active": bool((updated_doc or {}).get("active", True)),
            "version": (updated_doc or {}).get("version", current_version + 1)
        }, None
    except Exception as e:
        print(e)
        return None, str(e)
    finally:
        if mongo_client:
            mongo_client.close()


def _payload_contains_secret_ref(payload, secret_ref):
    if isinstance(payload, dict):
        for key, value in payload.items():
            field_name = str(key or '').strip()
            if field_name.endswith('_secret_ref') and str(value or '').strip() == str(secret_ref or '').strip():
                return True
            if _payload_contains_secret_ref(value, secret_ref):
                return True
        return False

    if isinstance(payload, list):
        for item in payload:
            if _payload_contains_secret_ref(item, secret_ref):
                return True
        return False

    return False


def deactivate_datapull_secret(secret_ref, deactivated_by=None):
    mongo_client = None
    try:
        if not secret_ref:
            return None, "secret_ref is required"

        normalized_ref = str(secret_ref).strip()
        now = all_connects._utc_now()

        mongo_client, _ = all_connects.connect_mongodb()
        config_db = mongo_client["byoint_core_config"]
        core_db = mongo_client["byoint_core_data"]
        secrets_col = config_db["datapull_secrets"]
        workflows_col = core_db["datapull_workflows"]

        secret_doc = secrets_col.find_one({"secret_ref": normalized_ref, "active": True})
        if not secret_doc:
            return None, "Secret not found or already inactive"

        referencing_sources = []
        for workflow in workflows_col.find({}, {"source_name": 1, "datapull_payload": 1}):
            payload = workflow.get("datapull_payload")
            if _payload_contains_secret_ref(payload, normalized_ref):
                referencing_sources.append(str(workflow.get("source_name") or "unknown_source"))

        if referencing_sources:
            sample_sources = ", ".join(referencing_sources[:10])
            suffix = "" if len(referencing_sources) <= 10 else f" (+{len(referencing_sources) - 10} more)"
            return None, f"Secret is still referenced by workflows: {sample_sources}{suffix}"

        secrets_col.update_one(
            {"_id": secret_doc.get("_id")},
            {
                "$set": {
                    "active": False,
                    "updated_at": now,
                    "deactivated_at": now,
                    "deactivated_by": deactivated_by
                }
            }
        )

        updated_doc = secrets_col.find_one({"_id": secret_doc.get("_id")}, {"ciphertext": 0, "nonce": 0})
        created_at = updated_doc.get("created_at") if updated_doc else None
        updated_at = updated_doc.get("updated_at") if updated_doc else None

        return {
            "secret_ref": updated_doc.get("secret_ref") if updated_doc else normalized_ref,
            "name": updated_doc.get("name") if updated_doc else None,
            "description": updated_doc.get("description") if updated_doc else None,
            "created_by": updated_doc.get("created_by") if updated_doc else None,
            "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else created_at,
            "updated_at": updated_at.isoformat() if hasattr(updated_at, "isoformat") else updated_at,
            "active": bool((updated_doc or {}).get("active", False)),
            "version": (updated_doc or {}).get("version", 1)
        }, None
    except Exception as e:
        print(e)
        return None, str(e)
    finally:
        if mongo_client:
            mongo_client.close()


def resolve_datapull_secret_ref(secret_ref):
    mongo_client = None
    try:
        if not secret_ref:
            return None, "secret_ref is required"

        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_config"]
        secrets_col = db["datapull_secrets"]
        doc = secrets_col.find_one({"secret_ref": str(secret_ref).strip(), "active": True})
        if not doc:
            return None, f"Secret not found or inactive: {secret_ref}"

        plaintext = all_connects._decrypt_datapull_secret_value(doc)
        return plaintext, None
    except Exception as e:
        print(e)
        return None, str(e)
    finally:
        if mongo_client:
            mongo_client.close()


# --- Datapull Workflow Functions ---
def get_datapull_workflows_data():
    """Fetch all datapull workflows."""
    mongo_client = None
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_data"]
        workflows = db["datapull_workflows"]
        cursor = workflows.find({})
        out = []
        for d in cursor:
            datapull_payload = d.get('datapull_payload', {})
            br_score = d.get('br_score', datapull_payload.get('br_score'))
            selected_enrichments = d.get('selected_enrichments') if isinstance(d.get('selected_enrichments'), list) else []
            out.append({
                'source_name': d.get('source_name'),
                'source_description': d.get('source_description'),
                'source_category': d.get('source_category'),
                'source_type': d.get('source_type'),
                'tag': d.get('tag'),
                'source_template_type': d.get('source_template_type'),
                'datapull_function': d.get('datapull_function'),
                'br_score': br_score,
                'scheduled': d.get('scheduled'),
                'schedule_interval_min': d.get('schedule_interval_min'),
                'enabled': d.get('schedule_enabled'),
                'selected_enrichments': selected_enrichments,
                'enrichment_enabled': bool(selected_enrichments),
                'insertmany': bool(d.get('insertmany', False)),
                'max_response_bytes': d.get('max_response_bytes'),
                'max_query_rows': d.get('max_query_rows'),
                'creation_time': d.get('creation_time').isoformat() if d.get('creation_time') else None,
                'datapull_payload': datapull_payload
            })
        return out
    except Exception as e:
        print(f"Error fetching workflows: {e}")
        return []
    finally:
        if mongo_client:
            mongo_client.close()


def get_datapull_security_report_data(source_name=None, include_compliant=False):
    """Get datapull security compliance report."""
    mongo_client = None
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_data"]
        workflows = db["datapull_workflows"]

        query = {}
        if source_name:
            query['source_name'] = source_name

        docs = list(workflows.find(query, {
            '_id': 0,
            'source_name': 1,
            'scheduled': 1,
            'schedule_enabled': 1,
            'source_template_type': 1,
            'datapull_payload': 1
        }))

        report = _build_datapull_security_report(docs, include_compliant=include_compliant)
        return report
    except Exception as e:
        print(f"Error getting security report: {e}")
        return None
    finally:
        if mongo_client:
            mongo_client.close()


def _extract_processed_count_from_dp_log(dp_log_text):
    """Best-effort parse of extracted indicator counts from datapull logs."""
    text = str(dp_log_text or '')
    if not text:
        return None

    patterns = [
        r'processed\s+(\d+)\s+indicators',
        r'successfully\s+processed\s+(\d+)\s+indicators',
        r'total\s+entries\s+fetched[^\d]*(\d+)'
    ]

    matches = []
    for pattern in patterns:
        for match in re.findall(pattern, text, flags=re.IGNORECASE):
            try:
                matches.append(int(match))
            except Exception:
                continue

    if not matches:
        return None
    return matches[-1]


def _normalize_execution_timestamp(log_doc):
    ts = log_doc.get('end_time') or log_doc.get('timestamp')
    if isinstance(ts, datetime):
        return ts
    if isinstance(ts, str) and ts.strip():
        try:
            return datetime.fromisoformat(ts.replace('Z', '+00:00')).replace(tzinfo=None)
        except Exception:
            return None
    return None


def _derive_integrity_status(score):
    if score >= 80:
        return 'healthy'
    if score >= 60:
        return 'watch'
    return 'risk'


def get_datapull_integrity_report_data(source_name=None, scheduled_only=True, lookback_runs=20):
    """Build Datapull Integrity Check report (defaults to scheduled workflows only)."""
    mongo_client = None
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        data_db = mongo_client['byoint_core_data']
        ops_db = mongo_client['byoint_opslogs']

        workflows_col = data_db['datapull_workflows']
        executions_col = ops_db['datapull_executions']

        query = {}
        if source_name:
            query['source_name'] = str(source_name).strip()
        if scheduled_only:
            query['scheduled'] = True
            query['schedule_enabled'] = True

        workflow_docs = list(workflows_col.find(query, {
            '_id': 0,
            'source_name': 1,
            'source_template_type': 1,
            'scheduled': 1,
            'schedule_enabled': 1,
            'schedule_interval_min': 1
        }))

        lookback_runs = max(5, min(int(lookback_runs or 20), 200))
        now = datetime.utcnow()
        rows = []

        for wf in workflow_docs:
            source = str(wf.get('source_name') or '').strip()
            if not source:
                continue

            logs = list(executions_col.find(
                {'source_name': source},
                {
                    '_id': 0,
                    'timestamp': 1,
                    'end_time': 1,
                    'status': 1,
                    'dp_log': 1,
                    'duration_seconds': 1,
                    'error': 1
                }
            ).sort('timestamp', -1).limit(lookback_runs))

            total_runs = len(logs)
            success_logs = []
            error_runs = 0
            durations = []

            for log_doc in logs:
                status_text = str(log_doc.get('status') or '').strip().lower()
                if status_text in ('error', 'failed', 'dead_lettered'):
                    error_runs += 1
                if status_text in ('success', 'completed'):
                    success_logs.append(log_doc)
                try:
                    duration_seconds = float(log_doc.get('duration_seconds') or 0)
                    if duration_seconds > 0:
                        durations.append(duration_seconds)
                except Exception:
                    pass

            success_runs = len(success_logs)
            error_rate_pct = round((error_runs / total_runs) * 100, 2) if total_runs > 0 else 0.0

            last_run_at = _normalize_execution_timestamp(logs[0]) if logs else None
            last_success_at = _normalize_execution_timestamp(success_logs[0]) if success_logs else None

            processed_counts = []
            for log_doc in success_logs:
                parsed_count = _extract_processed_count_from_dp_log(log_doc.get('dp_log'))
                if parsed_count is not None:
                    processed_counts.append(parsed_count)

            latest_extracted_count = processed_counts[0] if processed_counts else None
            baseline_counts = processed_counts[1:] if len(processed_counts) > 1 else []
            baseline_avg = round(sum(baseline_counts) / len(baseline_counts), 2) if baseline_counts else None

            count_anomaly = False
            if latest_extracted_count is not None and baseline_avg is not None:
                deviation = abs(latest_extracted_count - baseline_avg)
                relative_deviation = deviation / max(1, baseline_avg)
                count_anomaly = relative_deviation > 0.7

            zero_yield_streak = 0
            for log_doc in success_logs:
                parsed_count = _extract_processed_count_from_dp_log(log_doc.get('dp_log'))
                if parsed_count is None:
                    break
                if parsed_count == 0:
                    zero_yield_streak += 1
                    continue
                break

            interval_min = None
            try:
                interval_min = int(wf.get('schedule_interval_min') or 0)
            except Exception:
                interval_min = None

            overdue = False
            overdue_by_minutes = None
            if bool(wf.get('scheduled')) and bool(wf.get('schedule_enabled')):
                if last_success_at is None:
                    overdue = True
                elif interval_min and interval_min > 0:
                    elapsed_min = (now - last_success_at).total_seconds() / 60.0
                    threshold_min = interval_min * 2
                    if elapsed_min > threshold_min:
                        overdue = True
                        overdue_by_minutes = round(elapsed_min - threshold_min, 2)

            score = 100
            reasons = []

            if total_runs == 0:
                score -= 30
                reasons.append('No recent executions found')

            if overdue:
                score -= 20
                if overdue_by_minutes is not None:
                    reasons.append(f'Overdue by {overdue_by_minutes} minutes')
                else:
                    reasons.append('Scheduled datapull has no recent successful run')

            if error_rate_pct >= 50:
                score -= 25
                reasons.append(f'High error rate ({error_rate_pct}%)')
            elif error_rate_pct >= 20:
                score -= 15
                reasons.append(f'Elevated error rate ({error_rate_pct}%)')

            if zero_yield_streak >= 3:
                score -= 25
                reasons.append(f'Zero-yield streak of {zero_yield_streak} successful run(s)')
            elif zero_yield_streak >= 1:
                score -= 10
                reasons.append(f'Zero-yield in latest run ({zero_yield_streak} streak)')

            if count_anomaly:
                score -= 15
                reasons.append('Extraction count deviates from recent trend')

            score = max(0, min(100, int(round(score))))
            status = _derive_integrity_status(score)

            avg_duration_seconds = round(sum(durations) / len(durations), 2) if durations else None

            rows.append({
                'source_name': source,
                'source_template_type': wf.get('source_template_type'),
                'scheduled': bool(wf.get('scheduled')),
                'schedule_enabled': bool(wf.get('schedule_enabled')),
                'schedule_interval_min': interval_min,
                'integrity_status': status,
                'integrity_score': score,
                'reasons': reasons,
                'last_run_at': last_run_at.isoformat() if hasattr(last_run_at, 'isoformat') else None,
                'last_success_at': last_success_at.isoformat() if hasattr(last_success_at, 'isoformat') else None,
                'total_runs_considered': total_runs,
                'success_runs': success_runs,
                'error_runs': error_runs,
                'error_rate_pct': error_rate_pct,
                'avg_duration_seconds': avg_duration_seconds,
                'latest_extracted_count': latest_extracted_count,
                'baseline_avg_extracted_count': baseline_avg,
                'zero_yield_streak': zero_yield_streak,
                'count_anomaly': bool(count_anomaly),
                'overdue': overdue,
                'overdue_by_minutes': overdue_by_minutes,
            })

        rows.sort(key=lambda r: (r.get('integrity_score', 0), r.get('source_name') or ''))

        healthy_count = sum(1 for r in rows if r.get('integrity_status') == 'healthy')
        watch_count = sum(1 for r in rows if r.get('integrity_status') == 'watch')
        risk_count = sum(1 for r in rows if r.get('integrity_status') == 'risk')
        avg_score = round(sum(r.get('integrity_score', 0) for r in rows) / len(rows), 2) if rows else 100.0

        return {
            'checked_at': datetime.utcnow().isoformat(),
            'mode': 'scheduled_only' if scheduled_only else 'all_workflows',
            'total_workflows_checked': len(rows),
            'healthy_workflows': healthy_count,
            'watch_workflows': watch_count,
            'risk_workflows': risk_count,
            'avg_integrity_score': avg_score,
            'workflows': rows,
        }
    except Exception as e:
        print(f"Error getting integrity report: {e}")
        return None
    finally:
        if mongo_client:
            mongo_client.close()


def get_datapull_templates_data():
    """Fetch all datapull templates."""
    mongo_client = None
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_config"]
        templates = db["datapull_templates"]
        cursor = templates.find({})
        out = []
        for d in cursor:
            template_type = str(d.get('template_type') or '').strip().lower()
            info_text = d.get('info')
            if template_type == 'builtin' and not str(info_text or '').strip():
                function_mapping = str(d.get('function_mapping') or '').strip()
                template_name = str(d.get('template_name') or '').strip()
                if function_mapping:
                    info_text = (
                        f"Built-in template '{template_name}' uses the server-side datapull function "
                        f"'{function_mapping}' to extract indicators from the source content and write them to the indicator store."
                    )
                else:
                    info_text = (
                        f"Built-in template '{template_name}' uses server-side datapull logic to extract indicators from source content and write them to the indicator store."
                    )
                if d.get('_id') is not None:
                    try:
                        templates.update_one({'_id': d.get('_id')}, {'$set': {'info': info_text}})
                    except Exception:
                        pass

            out.append({
                'template_name': d.get('template_name'),
                'template_type': d.get('template_type'),
                'description': d.get('description'),
                'info': info_text,
                'function_mapping': d.get('function_mapping'),
                'python_snippet': d.get('snippet_code') or d.get('python_snippet'),
                'ufield_args': d.get('ufield_args'),
                'created_at': d.get('created_at').isoformat() if d.get('created_at') else None
            })
        return out
    except Exception as e:
        print(f"Error fetching templates: {e}")
        return []
    finally:
        if mongo_client:
            mongo_client.close()


def create_datapull_template_data(template_name, template_type, description=None, info=None, function_mapping=None, snippet_code=None, ufield_args=None):
    """Create a new datapull template."""
    mongo_client = None
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_config"]
        templates = db["datapull_templates"]
        
        if templates.find_one({'template_name': template_name}):
            return None, "Template name already exists."

        template_type_text = str(template_type or '').strip()
        info_text = str(info or '').strip()
        if template_type_text.lower() == 'builtin' and not info_text:
            if function_mapping:
                info_text = (
                    f"Built-in template '{template_name}' uses the server-side datapull function "
                    f"'{function_mapping}' to extract indicators from the source content and write them to the indicator store."
                )
            else:
                info_text = (
                    f"Built-in template '{template_name}' uses server-side datapull logic to extract indicators from source content and write them to the indicator store."
                )

        doc = {
            'template_name': template_name,
            'template_type': template_type_text,
            'description': description,
            'info': info_text,
            'function_mapping': function_mapping,
            'snippet_code': snippet_code,
            'ufield_args': ufield_args if isinstance(ufield_args, list) else [],
            'created_at': datetime.utcnow()
        }
        result = templates.insert_one(doc)
        doc['_id'] = str(result.inserted_id)
        return doc, None
    except Exception as e:
        print(f"Error creating template: {e}")
        return None, str(e)
    finally:
        if mongo_client:
            mongo_client.close()


def get_datapull_executions_data(source_name):
    """Fetch datapull execution logs for a source."""
    mongo_client = None
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client["byoint_opslogs"]
        logs_col = db["datapull_executions"]
        logs = list(logs_col.find({"source_name": source_name}).sort("timestamp", -1).limit(50))
        
        for log in logs:
            log['_id'] = str(log.get('_id'))
            if 'timestamp' in log and hasattr(log['timestamp'], 'isoformat'):
                log['timestamp'] = log['timestamp'].isoformat()
        
        return logs
    except Exception as e:
        print(f"Error fetching executions: {e}")
        return []
    finally:
        if mongo_client:
            mongo_client.close()


INTEGRATION_CAPABILITY_STATUSES = ('tested', 'partial', 'untested', 'unsupported')
INTEGRATION_CAPABILITY_METHODS = ('builtin', 'custom_snippet')
INTEGRATION_CAPABILITY_TEXT_FIELDS = (
    'product', 'vendor', 'category', 'template_name', 'capability', 'tested_version',
    'tested_by', 'notes', 'snippet_example', 'reference_url'
)


def _normalize_integration_capability(data, partial=False):
    """Validate and normalize an integration capability payload. Returns (doc, error)."""
    doc = {}
    for field in INTEGRATION_CAPABILITY_TEXT_FIELDS:
        if field in data:
            value = data.get(field)
            doc[field] = str(value).strip() if value not in [None, ''] else None

    if 'data_types' in data:
        raw_types = data.get('data_types')
        if isinstance(raw_types, str):
            raw_types = raw_types.split(',')
        doc['data_types'] = [str(t).strip() for t in (raw_types or []) if str(t).strip()]

    if 'status' in data or not partial:
        status = str(data.get('status') or 'untested').strip().lower()
        if status not in INTEGRATION_CAPABILITY_STATUSES:
            return None, f"status must be one of: {', '.join(INTEGRATION_CAPABILITY_STATUSES)}"
        doc['status'] = status

    if 'method' in data or not partial:
        method = str(data.get('method') or 'builtin').strip().lower()
        if method not in INTEGRATION_CAPABILITY_METHODS:
            return None, f"method must be one of: {', '.join(INTEGRATION_CAPABILITY_METHODS)}"
        doc['method'] = method

    if not partial and not doc.get('product'):
        return None, 'product is required'
    if partial and 'product' in doc and not doc['product']:
        return None, 'product cannot be empty'

    return doc, None


def _serialize_integration_capability(doc):
    item = dict(doc)
    for key in ('created_at', 'updated_at'):
        if hasattr(item.get(key), 'isoformat'):
            item[key] = item[key].isoformat()
    return item


def list_integration_capabilities():
    mongo_client = None
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        col = mongo_client["byoint_core_config"]["integration_capabilities"]
        docs = list(col.find({}).sort([("category", 1), ("product", 1)]))
    finally:
        if mongo_client:
            mongo_client.close()
    return [_serialize_integration_capability(doc) for doc in docs]


def create_integration_capability(data, actor=None):
    doc, error = _normalize_integration_capability(data or {})
    if error:
        return None, error
    now = datetime.now(timezone.utc)
    doc.update({
        '_id': f"cap_{uuid.uuid4().hex[:16]}",
        'created_at': now,
        'updated_at': now,
        'created_by': actor,
        'updated_by': actor,
    })
    mongo_client = None
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        mongo_client["byoint_core_config"]["integration_capabilities"].insert_one(doc)
    finally:
        if mongo_client:
            mongo_client.close()
    return _serialize_integration_capability(doc), None


def update_integration_capability(capability_id, data, actor=None):
    updates, error = _normalize_integration_capability(data or {}, partial=True)
    if error:
        return None, error
    updates.update({'updated_at': datetime.now(timezone.utc), 'updated_by': actor})
    mongo_client = None
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        col = mongo_client["byoint_core_config"]["integration_capabilities"]
        result = col.update_one({'_id': capability_id}, {'$set': updates})
        if result.matched_count == 0:
            return None, 'not_found'
        doc = col.find_one({'_id': capability_id})
    finally:
        if mongo_client:
            mongo_client.close()
    return _serialize_integration_capability(doc), None


def delete_integration_capability(capability_id):
    mongo_client = None
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        result = mongo_client["byoint_core_config"]["integration_capabilities"].delete_one({'_id': capability_id})
        return result.deleted_count > 0
    finally:
        if mongo_client:
            mongo_client.close()


def get_datapull_jobs_data(status=None, source_name=None, limit=100):
    """Fetch persisted datapull job envelopes with optional filtering."""
    mongo_client = None
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client["byoint_opslogs"]
        jobs_col = db["datapull_jobs"]

        query = {}
        normalized_status = str(status or '').strip().lower()
        if normalized_status:
            query['status'] = normalized_status

        normalized_source = str(source_name or '').strip()
        if normalized_source:
            query['source_name'] = normalized_source

        try:
            limit = int(limit)
        except Exception:
            limit = 100
        limit = max(1, min(limit, 500))

        docs = list(jobs_col.find(query).sort([('_created_timestamp', -1), ('created_at', -1)]).limit(limit))
        for doc in docs:
            doc['_id'] = str(doc.get('_id'))
            for field in ('_created_timestamp',):
                if field in doc and hasattr(doc[field], 'isoformat'):
                    doc[field] = doc[field].isoformat()

        return docs
    except Exception as e:
        print(f"Error fetching datapull jobs: {e}")
        return []
    finally:
        if mongo_client:
            mongo_client.close()


def get_source_names_data(selected_type=None):
    """Get all source names from workflows."""
    mongo_client = None
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_data"]
        workflows_col = db["datapull_workflows"]

        query = {"source_category": "static"}
        if selected_type:
            query["source_type"] = selected_type

        workflows = list(workflows_col.find(query, {"_id": 0, "source_name": 1}))
        name_set = set()
        for workflow in workflows:
            source_name = str(workflow.get("source_name") or '').strip()
            if source_name:
                name_set.add(source_name)

        name_list = sorted(list(name_set), key=lambda n: n.lower())
        return name_list
    except Exception as e:
        print(f"Error fetching source names: {e}")
        return []
    finally:
        if mongo_client:
            mongo_client.close()


def update_datapull_workflow_data(source_name, updates):
    """Update a datapull workflow."""
    mongo_client = None
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_data"]
        workflows = db["datapull_workflows"]
        
        update_fields = {}
        for field in [
            'source_category', 'source_template_type', 'tag', 'datapull_payload',
            'scheduled', 'schedule_interval_min', 'schedule_enabled', 'br_score', 'enrichment_enabled', 'selected_enrichments', 'active', 'insertmany', 'max_response_bytes', 'max_query_rows']:
            if field in updates:
                update_fields[field] = updates[field]

        if 'insertmany' in update_fields:
            update_fields['insertmany'] = bool(update_fields['insertmany'])

        if 'max_response_bytes' in update_fields:
            raw_max_response_bytes = update_fields.get('max_response_bytes')
            if raw_max_response_bytes in [None, '']:
                update_fields['max_response_bytes'] = None
            else:
                try:
                    update_fields['max_response_bytes'] = max(1, int(raw_max_response_bytes))
                except Exception:
                    update_fields['max_response_bytes'] = None

        if 'max_query_rows' in update_fields:
            raw_max_query_rows = update_fields.get('max_query_rows')
            if raw_max_query_rows in [None, '']:
                update_fields['max_query_rows'] = None
            else:
                try:
                    update_fields['max_query_rows'] = max(1, int(raw_max_query_rows))
                except Exception:
                    update_fields['max_query_rows'] = None
        
        if 'selected_enrichments' in update_fields:
            selected = update_fields.get('selected_enrichments')
            if isinstance(selected, list):
                update_fields['selected_enrichments'] = [str(e).strip() for e in selected if str(e).strip()]
            else:
                update_fields['selected_enrichments'] = []
            if 'enrichment_enabled' not in update_fields:
                update_fields['enrichment_enabled'] = bool(update_fields['selected_enrichments'])
        
        if 'enabled' in updates and 'schedule_enabled' not in update_fields:
            update_fields['schedule_enabled'] = updates['enabled']
        
        if update_fields.get('scheduled') is False:
            update_fields['schedule_interval_min'] = None
            if 'schedule_enabled' not in update_fields:
                update_fields['schedule_enabled'] = False
        
        if 'datapull_payload' in update_fields:
            payload_error = _validate_datapull_payload_security(update_fields.get('datapull_payload'))
            if payload_error:
                return False, payload_error
            if isinstance(update_fields.get('datapull_payload'), dict):
                update_fields['datapull_payload'] = dict(update_fields['datapull_payload'])
                update_fields['datapull_payload'].pop('br_score', None)
        
        result = workflows.update_one(
            {"source_name": source_name},
            {"$set": update_fields}
        )
        
        if result.matched_count == 0:
            return False, "Datapull not found!"
        
        return True, None
    except Exception as e:
        print(f"Error updating datapull: {e}")
        return False, str(e)
    finally:
        if mongo_client:
            mongo_client.close()


def get_workflow_indicator_impact_data(source_name, sample_limit=25):
    """Summarize indicator impact for deleting a workflow source."""
    mongo_client = None
    try:
        normalized_source = str(source_name or '').strip()
        if not normalized_source:
            return None, 'source_name is required.'

        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_data"]
        workflows = db["datapull_workflows"]
        indicators = db["indicators"]

        workflow = workflows.find_one({'source_name': normalized_source}, {'_id': 0, 'source_name': 1})
        if not workflow:
            return None, f"Datapull workflow '{normalized_source}' not found."

        try:
            sample_limit = int(sample_limit)
        except Exception:
            sample_limit = 25
        sample_limit = max(1, min(sample_limit, 100))

        impacted_total = 0
        delete_total = 0
        deactivate_total = 0
        delete_samples = []
        deactivate_samples = []

        cursor = indicators.find(
            {'sources.source_name': normalized_source},
            {'value': 1, 'type': 1, 'dtype': 1, 'sources.source_name': 1}
        )

        for indicator in cursor:
            impacted_total += 1
            sources = indicator.get('sources') if isinstance(indicator.get('sources'), list) else []
            remaining_sources = []
            for source_entry in sources:
                if not isinstance(source_entry, dict):
                    continue
                source_entry_name = str(source_entry.get('source_name') or '').strip()
                if source_entry_name and source_entry_name != normalized_source:
                    remaining_sources.append(source_entry_name)

            sample_record = {
                'value': indicator.get('value'),
                'type': indicator.get('type') or indicator.get('dtype')
            }

            if remaining_sources:
                deactivate_total += 1
                if len(deactivate_samples) < sample_limit:
                    sample_record['also_in_sources'] = sorted(list(set(remaining_sources)))
                    deactivate_samples.append(sample_record)
            else:
                delete_total += 1
                if len(delete_samples) < sample_limit:
                    delete_samples.append(sample_record)

        impact = {
            'source_name': normalized_source,
            'impacted_indicator_count': impacted_total,
            'delete_indicator_count': delete_total,
            'deactivate_source_entry_count': deactivate_total,
            'delete_indicator_samples': delete_samples,
            'deactivate_indicator_samples': deactivate_samples,
            'rules': [
                'Indicators found only in this datapull workflow will be removed.',
                "Indicators found in other datapull workflows will keep the indicator record and mark this source entry as inactive (active='N', last_update_status=false)."
            ]
        }
        return impact, None
    except Exception as e:
        print(f"Error computing workflow indicator impact: {e}")
        return None, str(e)
    finally:
        if mongo_client:
            mongo_client.close()


def delete_datapull_workflow_data(source_name):
    """Delete a datapull workflow and apply indicator cleanup semantics."""
    mongo_client = None
    try:
        normalized_source = str(source_name or '').strip()
        if not normalized_source:
            return None, 'source_name is required.'

        impact, impact_err = get_workflow_indicator_impact_data(normalized_source)
        if impact_err:
            return None, impact_err

        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_data"]
        workflows = db["datapull_workflows"]
        indicators = db["indicators"]

        delete_ids = []
        deactivate_ids = []
        cursor = indicators.find(
            {'sources.source_name': normalized_source},
            {'sources.source_name': 1}
        )

        for indicator in cursor:
            indicator_id = indicator.get('_id')
            if indicator_id is None:
                continue

            sources = indicator.get('sources') if isinstance(indicator.get('sources'), list) else []
            has_other_sources = False
            for source_entry in sources:
                if not isinstance(source_entry, dict):
                    continue
                source_entry_name = str(source_entry.get('source_name') or '').strip()
                if source_entry_name and source_entry_name != normalized_source:
                    has_other_sources = True
                    break

            if has_other_sources:
                deactivate_ids.append(indicator_id)
            else:
                delete_ids.append(indicator_id)

        deleted_indicators = 0
        deactivated_entries = 0

        if delete_ids:
            delete_result = indicators.delete_many({'_id': {'$in': delete_ids}})
            deleted_indicators = int(delete_result.deleted_count or 0)

        if deactivate_ids:
            deactivate_result = indicators.update_many(
                {'_id': {'$in': deactivate_ids}, 'sources.source_name': normalized_source},
                {
                    '$set': {
                        'sources.$[elem].last_update_status': False,
                        'sources.$[elem].active': 'N'
                    }
                },
                array_filters=[{'elem.source_name': normalized_source}]
            )
            deactivated_entries = int(deactivate_result.modified_count or 0)

        update_active_field_for_all_indicators(mongo_client)

        workflow_delete_result = workflows.delete_one({'source_name': normalized_source})
        if workflow_delete_result.deleted_count == 0:
            return None, f"Datapull workflow '{normalized_source}' not found."

        response = {
            'source_name': normalized_source,
            'workflow_deleted': True,
            'indicator_cleanup': {
                'impacted_indicator_count': int(impact.get('impacted_indicator_count', 0)),
                'deleted_indicator_count': deleted_indicators,
                'deactivated_source_entry_count': deactivated_entries
            }
        }
        return response, None
    except Exception as e:
        print(f"Error deleting datapull workflow: {e}")
        return None, str(e)
    finally:
        if mongo_client:
            mongo_client.close()


def execute_workflow_shared(workflow, default_dp_module='datapull', custom_template_executor=None, cache_invalidator=None):
    """Execute a workflow with shared behavior for API process and future worker processes."""
    result = None
    dp_log = ''
    thread_id = threading.current_thread().ident
    source_name = workflow.get('source_name')
    source_template_type = workflow.get('source_template_type')
    datapull_function = workflow.get('datapull_function')
    datapull_payload = workflow.get('datapull_payload', {})
    start_time = datetime.utcnow()
    log_entry = {
        'timestamp': start_time,
        'source_name': source_name,
        'source_template_type': source_template_type,
        'datapull_function': datapull_function,
        'status': 'running',
        'error': None,
        'thread_id': thread_id
    }

    try:
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client["byoint_opslogs"]
        scheduler_logs = db["scheduler_logs"]
        scheduler_logs.insert_one({
            'event': 'job_started',
            'timestamp': start_time,
            'source_name': source_name,
            'datapull_function': datapull_function,
            'thread_id': thread_id
        })
        mongo_client.close()
    except Exception as e:
        print(f"Error logging job start to scheduler_logs: {e}")

    try:
        print(f"[Thread {thread_id}] Executing scheduled workflow: {source_name}")

        mongo_client_template, _ = all_connects.connect_mongodb()
        db_config = mongo_client_template["byoint_core_config"]
        templates_col = db_config["datapull_templates"]
        template = templates_col.find_one({"template_name": source_template_type})

        payload_error = _validate_datapull_payload_security(datapull_payload)
        if payload_error:
            raise ValueError(payload_error)

        resolved_payload = _resolve_secret_refs_in_payload(datapull_payload)
        kwargs = {"source": source_name}

        if template and template.get('ufield_args'):
            ufield_args = template.get('ufield_args', [])
            for field_info in ufield_args:
                if isinstance(field_info, dict):
                    field_name = field_info.get('name') or field_info.get('field_name')
                elif isinstance(field_info, str):
                    field_name = field_info
                else:
                    continue
                if field_name and isinstance(resolved_payload, dict) and field_name in resolved_payload:
                    kwargs[field_name] = resolved_payload[field_name]
                    # If template defines *_secret_ref fields, also forward resolved runtime value.
                    if str(field_name).endswith('_secret_ref'):
                        target_field = str(field_name)[:-len('_secret_ref')]
                        if target_field and target_field in resolved_payload:
                            kwargs[target_field] = resolved_payload[target_field]

        mongo_client_template.close()

        template_type = str((template or {}).get('template_type') or '').strip().lower()
        snippet_code = (template or {}).get('snippet_code') or (template or {}).get('python_snippet')

        workflow_response_mode = str((resolved_payload or {}).get('response_mode') or 'walk_everything').strip().lower()
        raw_workflow_paths = (resolved_payload or {}).get('response_paths')
        if isinstance(raw_workflow_paths, (list, tuple, set)):
            workflow_response_paths = [str(path).strip() for path in raw_workflow_paths if str(path).strip()]
        elif isinstance(raw_workflow_paths, str):
            workflow_response_paths = [str(raw_workflow_paths).strip()] if str(raw_workflow_paths).strip() else []
        else:
            workflow_response_paths = []

        if template_type == 'custom':
            if not callable(custom_template_executor):
                raise ValueError("Custom template executor is not configured")
            result, dp_log = custom_template_executor(snippet_code, kwargs, source_name)
        else:
            if not datapull_function:
                raise ValueError(f"No datapull_function configured for template '{source_template_type}'")
            module = importlib.import_module(default_dp_module)
            executor = getattr(module, datapull_function)
            if str(datapull_function).startswith('apirequest_') or datapull_function == 'mcp_tool_call_v1':
                result, dp_log = executor(**kwargs, response_mode=workflow_response_mode, response_schema=workflow_response_paths)
            else:
                result, dp_log = executor(**kwargs)

        log_entry['status'] = 'success'
        print(f"[Thread {thread_id}] Workflow {source_name} executed successfully.")
        job_status = 'job_finished'
        job_error = None
    except Exception as e:
        log_entry['status'] = 'error'
        log_entry['error'] = str(e)
        print(f"[Thread {thread_id}] Error executing workflow: {e}")
        job_status = 'job_error'
        job_error = str(e)
        dp_log = str(e)
    finally:
        log_entry['end_time'] = datetime.utcnow()
        log_entry['duration_seconds'] = (log_entry['end_time'] - start_time).total_seconds()
        if not dp_log or not str(dp_log).strip():
            dp_log = f"Execution completed with status: {log_entry.get('status')}"
        log_entry['dp_log'] = dp_log
        log_datapull_execution(log_entry)

        try:
            mongo_client, _ = all_connects.connect_mongodb()
            db = mongo_client["byoint_opslogs"]
            scheduler_logs = db["scheduler_logs"]
            scheduler_logs.insert_one({
                'event': job_status,
                'timestamp': datetime.utcnow(),
                'source_name': source_name,
                'datapull_function': datapull_function,
                'thread_id': thread_id,
                'error': job_error
            })
            mongo_client.close()
        except Exception as e:
            print(f"Error logging job finish to scheduler_logs: {e}")

        try:
            if callable(cache_invalidator):
                cache_invalidator()
        except Exception as e:
            print(f"Error invalidating feed caches after workflow run: {e}")

    return {
        'status': log_entry.get('status'),
        'source_name': source_name,
        'dp_log': dp_log,
        'result': result
    }


def _get_datapull_queue_client():
    global _DATAPULL_QUEUE_CLIENT, _DATAPULL_QUEUE_INIT_ATTEMPTED

    if _DATAPULL_QUEUE_CLIENT is not None:
        return _DATAPULL_QUEUE_CLIENT
    if _DATAPULL_QUEUE_INIT_ATTEMPTED:
        return None

    _DATAPULL_QUEUE_INIT_ATTEMPTED = True

    try:
        socket_timeout_seconds = float(os.getenv('DATAPULL_QUEUE_SOCKET_TIMEOUT_SECONDS', '10'))
        socket_timeout_seconds = max(5.0, socket_timeout_seconds)
        client = all_connects.get_redis_client(
            socket_timeout=socket_timeout_seconds,
            socket_connect_timeout=2,
        )
        if client is None:
            return None
        _DATAPULL_QUEUE_CLIENT = client
        return _DATAPULL_QUEUE_CLIENT
    except Exception:
        return None


def _log_scheduler_event(event, source_name=None, datapull_function=None, error=None, details=None):
    mongo_client = None
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client['byoint_opslogs']
        scheduler_logs = db['scheduler_logs']
        doc = {
            'event': event,
            'timestamp': datetime.utcnow(),
            'source_name': source_name,
            'datapull_function': datapull_function,
            'error': error,
        }
        if isinstance(details, dict) and details:
            doc['details'] = details
        scheduler_logs.insert_one(doc)
    except Exception as e:
        print(f"Error writing scheduler event '{event}': {e}")
    finally:
        if mongo_client:
            mongo_client.close()


def load_workflow_by_source_name(source_name):
    mongo_client = None
    try:
        source_name = str(source_name or '').strip()
        if not source_name:
            return None

        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client['byoint_core_data']
        workflow = db['datapull_workflows'].find_one({'source_name': source_name})
        if not workflow:
            return None
        return workflow
    except Exception as e:
        print(f"Error loading workflow for source '{source_name}': {e}")
        return None
    finally:
        if mongo_client:
            mongo_client.close()


def enqueue_workflow_execution(source_name, trigger='scheduler', metadata=None):
    source_name = str(source_name or '').strip()
    if not source_name:
        return None, 'Missing source_name for queue enqueue.'

    client = _get_datapull_queue_client()
    if not client:
        return None, 'Redis queue is unavailable.'

    message = {
        'message_id': str(uuid.uuid4()),
        'source_name': source_name,
        'trigger': str(trigger or 'scheduler'),
        'enqueued_at': datetime.utcnow().isoformat() + 'Z',
    }
    if isinstance(metadata, dict) and metadata:
        message['metadata'] = metadata

    try:
        client.rpush(_DATAPULL_QUEUE_KEY, json.dumps(message))
        _log_scheduler_event(
            event='job_queued',
            source_name=source_name,
            details={'queue_key': _DATAPULL_QUEUE_KEY, 'message_id': message['message_id'], 'trigger': message['trigger']}
        )
        return message, None
    except Exception as e:
        return None, str(e)


def dequeue_workflow_execution(block_seconds=5):
    client = _get_datapull_queue_client()
    if not client:
        return None, 'Redis queue is unavailable.'

    try:
        block_seconds = int(block_seconds)
    except Exception:
        block_seconds = 5
    block_seconds = max(1, min(block_seconds, 30))

    try:
        popped = client.blpop(_DATAPULL_QUEUE_KEY, timeout=block_seconds)
        if not popped or len(popped) < 2:
            return None, None
        raw_message = popped[1]
        message = json.loads(raw_message)
        if not isinstance(message, dict):
            return None, 'Invalid queue message format.'
        return message, None
    except Exception as e:
        if 'Timeout reading from socket' in str(e):
            return None, None
        return None, str(e)


def get_workflow_queue_depth():
    client = _get_datapull_queue_client()
    if not client:
        return None
    try:
        return int(client.llen(_DATAPULL_QUEUE_KEY))
    except Exception:
        return None


def is_workflow_queue_available():
    return _get_datapull_queue_client() is not None


def _worker_metrics_ttl_seconds():
    try:
        return max(30, int(os.getenv('DATAPULL_WORKER_HEARTBEAT_TTL_SECONDS', '120')))
    except Exception:
        return 120


def get_worker_identity():
    configured = str(os.getenv('DATAPULL_WORKER_ID') or '').strip()
    if configured:
        return configured
    hostname = str(socket.gethostname() or 'worker').strip()
    return f"{hostname}-{os.getpid()}"


def _worker_metrics_key(worker_id):
    worker_id = str(worker_id or '').strip()
    return f"{_DATAPULL_WORKER_METRICS_PREFIX}{worker_id}"


def record_worker_heartbeat(worker_id=None, state='running', extra=None):
    client = _get_datapull_queue_client()
    if not client:
        return False

    worker_id = get_worker_identity() if not worker_id else str(worker_id).strip()
    if not worker_id:
        return False

    now_dt = datetime.utcnow()
    now_ts = int(time.time())
    payload = {
        'worker_id': worker_id,
        'state': str(state or 'running'),
        'last_heartbeat': now_dt.isoformat() + 'Z',
        'last_heartbeat_ts': str(now_ts),
    }
    if isinstance(extra, dict):
        for key, value in extra.items():
            if value is None:
                continue
            payload[str(key)] = str(value)

    key = _worker_metrics_key(worker_id)
    ttl = _worker_metrics_ttl_seconds()

    try:
        client.hset(key, mapping=payload)
        client.expire(key, ttl)
        client.sadd(_DATAPULL_WORKER_METRICS_INDEX_KEY, worker_id)
        client.expire(_DATAPULL_WORKER_METRICS_INDEX_KEY, ttl * 10)
        return True
    except Exception:
        return False


def record_worker_job_result(worker_id=None, source_name=None, status='unknown', error=None, duration_ms=None, message_id=None):
    client = _get_datapull_queue_client()
    if not client:
        return False

    worker_id = get_worker_identity() if not worker_id else str(worker_id).strip()
    if not worker_id:
        return False

    key = _worker_metrics_key(worker_id)
    ttl = _worker_metrics_ttl_seconds()
    now_dt = datetime.utcnow()
    now_ts = int(time.time())
    status = str(status or 'unknown').strip().lower()

    try:
        pipe = client.pipeline()
        pipe.hset(key, mapping={
            'worker_id': worker_id,
            'state': 'running',
            'last_heartbeat': now_dt.isoformat() + 'Z',
            'last_heartbeat_ts': str(now_ts),
            'last_processed_at': now_dt.isoformat() + 'Z',
            'last_source_name': str(source_name or ''),
            'last_message_id': str(message_id or ''),
            'last_status': status,
        })
        pipe.hincrby(key, 'processed_count', 1)

        if status == 'success':
            pipe.hincrby(key, 'success_count', 1)
            pipe.hset(key, 'last_error', '')
        else:
            pipe.hincrby(key, 'error_count', 1)
            pipe.hset(key, 'last_error', str(error or 'unknown error'))

        if duration_ms is not None:
            try:
                duration_int = max(0, int(duration_ms))
                pipe.hset(key, 'last_duration_ms', str(duration_int))
            except Exception:
                pass

        pipe.expire(key, ttl)
        pipe.sadd(_DATAPULL_WORKER_METRICS_INDEX_KEY, worker_id)
        pipe.expire(_DATAPULL_WORKER_METRICS_INDEX_KEY, ttl * 10)
        pipe.execute()
        return True
    except Exception:
        return False


def list_worker_metrics():
    client = _get_datapull_queue_client()
    if not client:
        return []

    ttl = _worker_metrics_ttl_seconds()
    stale_after = ttl + 15
    now_ts = int(time.time())

    try:
        worker_ids = list(client.smembers(_DATAPULL_WORKER_METRICS_INDEX_KEY) or [])
    except Exception:
        return []

    workers = []
    for worker_id in worker_ids:
        wid = str(worker_id or '').strip()
        if not wid:
            continue
        key = _worker_metrics_key(wid)
        try:
            raw = client.hgetall(key) or {}
        except Exception:
            raw = {}
        if not raw:
            continue

        try:
            heartbeat_ts = int(raw.get('last_heartbeat_ts') or '0')
        except Exception:
            heartbeat_ts = 0
        age_seconds = max(0, now_ts - heartbeat_ts) if heartbeat_ts > 0 else None
        is_stale = age_seconds is None or age_seconds > stale_after

        workers.append({
            'worker_id': wid,
            'state': raw.get('state') or ('stale' if is_stale else 'running'),
            'is_stale': bool(is_stale),
            'heartbeat_age_seconds': age_seconds,
            'last_heartbeat': raw.get('last_heartbeat'),
            'last_processed_at': raw.get('last_processed_at'),
            'last_source_name': raw.get('last_source_name'),
            'last_message_id': raw.get('last_message_id'),
            'last_status': raw.get('last_status'),
            'last_error': raw.get('last_error'),
            'last_duration_ms': int(raw.get('last_duration_ms') or '0') if str(raw.get('last_duration_ms') or '').isdigit() else None,
            'processed_count': int(raw.get('processed_count') or '0') if str(raw.get('processed_count') or '').isdigit() else 0,
            'success_count': int(raw.get('success_count') or '0') if str(raw.get('success_count') or '').isdigit() else 0,
            'error_count': int(raw.get('error_count') or '0') if str(raw.get('error_count') or '').isdigit() else 0,
        })

    workers.sort(key=lambda item: str(item.get('worker_id') or '').lower())
    return workers


# Phase 3: Job Envelope and Persistence Model
_DATAPULL_DEAD_LETTER_QUEUE_KEY = str(os.getenv('DATAPULL_DEAD_LETTER_QUEUE_KEY') or 'datapull:dead-letter-queue').strip()
_DATAPULL_DELAYED_QUEUE_KEY = str(os.getenv('DATAPULL_DELAYED_QUEUE_KEY') or 'datapull:execution:delayed').strip()
_DATAPULL_JOB_LOCK_PREFIX = str(os.getenv('DATAPULL_JOB_LOCK_PREFIX') or 'datapull:job:lock:').strip()
_MAX_JOB_ATTEMPTS = int(os.getenv('DATAPULL_MAX_JOB_ATTEMPTS', '3'))
_RETRY_BASE_SECONDS = int(os.getenv('DATAPULL_RETRY_BASE_SECONDS', '10'))
_RETRY_MAX_SECONDS = int(os.getenv('DATAPULL_RETRY_MAX_SECONDS', '300'))
_RETRY_JITTER_SECONDS = int(os.getenv('DATAPULL_RETRY_JITTER_SECONDS', '5'))
_DATAPULL_SCHEDULER_LEADER_KEY = str(os.getenv('DATAPULL_SCHEDULER_LEADER_KEY') or 'datapull:scheduler:leader').strip()
_DATAPULL_SCHEDULER_LEADER_TTL_SECONDS = int(os.getenv('DATAPULL_SCHEDULER_LEADER_TTL_SECONDS', '90'))
_JOB_INDEXES_INITIALIZED = False


def _init_job_indexes():
    global _JOB_INDEXES_INITIALIZED
    if _JOB_INDEXES_INITIALIZED:
        return

    mongo_client = None
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        jobs_col = mongo_client['byoint_opslogs']['datapull_jobs']
        jobs_col.create_index('job_id', unique=True)
        jobs_col.create_index([('status', 1), ('_created_timestamp', -1)])
        jobs_col.create_index([('source_name', 1), ('_created_timestamp', -1)])
        jobs_col.create_index('next_retry_at')
        _JOB_INDEXES_INITIALIZED = True
    except Exception as e:
        print(f"Error initializing datapull_jobs indexes: {e}")
    finally:
        if mongo_client:
            mongo_client.close()


def _utc_now_iso():
    return datetime.utcnow().isoformat() + 'Z'


def _iso_to_epoch(iso_value):
    try:
        normalized = str(iso_value or '').strip().replace('Z', '+00:00')
        if not normalized:
            return None
        return datetime.fromisoformat(normalized).timestamp()
    except Exception:
        return None


def _classify_job_error(error_text):
    normalized = str(error_text or '').strip().lower()
    if not normalized:
        return {'retryable': True, 'error_type': 'unknown_error'}

    non_retryable_markers = [
        'missing source_name',
        'not found when dequeued',
        'no datapull_function configured',
        'invalid datapull_payload',
        'plaintext credential field',
        'invalid secret reference',
        'custom template executor is not configured',
        'invalid queue message format',
    ]
    for marker in non_retryable_markers:
        if marker in normalized:
            return {'retryable': False, 'error_type': 'configuration_error'}

    if 'timeout' in normalized:
        return {'retryable': True, 'error_type': 'timeout_error'}
    if 'connection' in normalized or 'network' in normalized:
        return {'retryable': True, 'error_type': 'network_error'}
    if 'auth' in normalized or 'unauthorized' in normalized or 'forbidden' in normalized:
        return {'retryable': False, 'error_type': 'auth_error'}
    return {'retryable': True, 'error_type': 'runtime_error'}


def _calculate_retry_delay_seconds(attempt_count):
    attempt_count = max(1, int(attempt_count or 1))
    base = max(1, _RETRY_BASE_SECONDS)
    max_delay = max(base, _RETRY_MAX_SECONDS)
    jitter = max(0, _RETRY_JITTER_SECONDS)

    backoff = min(max_delay, base * (2 ** (attempt_count - 1)))
    if jitter > 0:
        backoff += random.randint(0, jitter)
    return min(max_delay, backoff)


def promote_due_delayed_jobs(max_count=20):
    client = _get_datapull_queue_client()
    if not client:
        return 0

    try:
        max_count = max(1, min(int(max_count), 200))
    except Exception:
        max_count = 20

    moved = 0
    now_ts = time.time()
    try:
        due_items = client.zrangebyscore(_DATAPULL_DELAYED_QUEUE_KEY, '-inf', now_ts, start=0, num=max_count)
        for raw_item in due_items:
            removed = client.zrem(_DATAPULL_DELAYED_QUEUE_KEY, raw_item)
            if removed:
                client.rpush(_DATAPULL_QUEUE_KEY, raw_item)
                moved += 1
    except Exception as e:
        print(f"Error promoting delayed jobs: {e}")
    return moved


def try_acquire_scheduler_leader(identity):
    client = _get_datapull_queue_client()
    if not client:
        return True

    identity = str(identity or '').strip()
    if not identity:
        return False

    try:
        return bool(client.set(_DATAPULL_SCHEDULER_LEADER_KEY, identity, nx=True, ex=max(15, _DATAPULL_SCHEDULER_LEADER_TTL_SECONDS)))
    except Exception:
        return False


def renew_scheduler_leader(identity):
    client = _get_datapull_queue_client()
    if not client:
        return True

    identity = str(identity or '').strip()
    if not identity:
        return False

    try:
        current = client.get(_DATAPULL_SCHEDULER_LEADER_KEY)
        if current != identity:
            return False
        client.set(_DATAPULL_SCHEDULER_LEADER_KEY, identity, xx=True, ex=max(15, _DATAPULL_SCHEDULER_LEADER_TTL_SECONDS))
        return True
    except Exception:
        return False


def release_scheduler_leader(identity):
    client = _get_datapull_queue_client()
    if not client:
        return True

    identity = str(identity or '').strip()
    if not identity:
        return False

    try:
        current = client.get(_DATAPULL_SCHEDULER_LEADER_KEY)
        if current != identity:
            return False
        client.delete(_DATAPULL_SCHEDULER_LEADER_KEY)
        return True
    except Exception:
        return False


def _get_job_idempotency_key(source_name, trigger_context=None):
    """Generate idempotency key for job; derived from source and trigger context."""
    source_name = str(source_name or '').strip()
    if not source_name:
        return None
    
    base = f"{source_name}:{trigger_context}" if trigger_context else source_name
    return f"datapull:job:idempotent:{base}"


def _acquire_job_lock(job_id, lock_ttl_seconds=300):
    """Attempt to acquire distributed lock for job processing; prevents concurrent execution."""
    client = _get_datapull_queue_client()
    if not client:
        return True  
    
    job_id = str(job_id or '').strip()
    if not job_id:
        return False
    
    try:
        lock_key = f"{_DATAPULL_JOB_LOCK_PREFIX}{job_id}"
        result = client.set(lock_key, '1', nx=True, ex=lock_ttl_seconds)
        return bool(result)
    except Exception:
        return False


def _release_job_lock(job_id):
    """Release distributed lock after job processing."""
    client = _get_datapull_queue_client()
    if not client:
        return False
    
    job_id = str(job_id or '').strip()
    if not job_id:
        return False
    
    try:
        lock_key = f"{_DATAPULL_JOB_LOCK_PREFIX}{job_id}"
        client.delete(lock_key)
        return True
    except Exception:
        return False


def create_job_envelope(source_name, trigger='scheduler', metadata=None, max_attempts=None, requested_by=None, trigger_source=None, correlation_id=None):
    """Create a job envelope that wraps a workflow with execution state tracking.
    
    Phase 5 enhancement: Add audit fields for request tracking and traceability.
    - requested_by: user/client that triggered execution (e.g., 'admin', 'api-key-xyz')
    - trigger_source: 'scheduled', 'manual', 'api', 'bulk', etc.
    - correlation_id: optional trace ID for distributed request tracking
    """
    source_name = str(source_name or '').strip()
    if not source_name:
        return None
    
    if max_attempts is None:
        max_attempts = _MAX_JOB_ATTEMPTS
    else:
        max_attempts = max(1, int(max_attempts))
    
    now_utc = datetime.utcnow()
    envelope = {
        'job_id': str(uuid.uuid4()),
        'source_name': source_name,
        'trigger': str(trigger or 'scheduler'),
        'status': 'queued',
        'attempt_count': 0,
        'max_attempts': max_attempts,
        'created_at': now_utc.isoformat() + 'Z',
        'first_enqueued_at': now_utc.isoformat() + 'Z',
        'last_attempted_at': None,
        'completed_at': None,
        'error': None,
        'attempts': [],
        # Phase 5 audit fields
        'requested_by': str(requested_by or '').strip() or None,
        'trigger_source': str(trigger_source or trigger or 'scheduler').strip() or None,
        'correlation_id': str(correlation_id or '').strip() or None,
    }
    
    if isinstance(metadata, dict) and metadata:
        envelope['metadata'] = metadata
    
    return envelope


def persist_job_envelope(envelope):
    """Store job envelope state in MongoDB for audit trail and retry tracking."""
    if not isinstance(envelope, dict) or not envelope.get('job_id'):
        return False
    
    mongo_client = None
    try:
        _init_job_indexes()
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client['byoint_opslogs']
        jobs_col = db['datapull_jobs']
        
        doc = dict(envelope)
        doc['_created_timestamp'] = datetime.utcnow()
        
        result = jobs_col.update_one(
            {'job_id': envelope['job_id']},
            {'$set': doc},
            upsert=True
        )
        return bool(result)
    except Exception as e:
        print(f"Error persisting job envelope: {e}")
        return False
    finally:
        if mongo_client:
            mongo_client.close()


def load_job_envelope(job_id):
    """Load job envelope state from MongoDB."""
    job_id = str(job_id or '').strip()
    if not job_id:
        return None
    
    mongo_client = None
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client['byoint_opslogs']
        jobs_col = db['datapull_jobs']
        
        doc = jobs_col.find_one({'job_id': job_id})
        if doc:
            doc.pop('_id', None)
            if '_created_timestamp' in doc and hasattr(doc['_created_timestamp'], 'isoformat'):
                doc['_created_timestamp'] = doc['_created_timestamp'].isoformat()
        return doc
    except Exception as e:
        print(f"Error loading job envelope: {e}")
        return None
    finally:
        if mongo_client:
            mongo_client.close()


def enqueue_job_envelope(envelope, delay_seconds=0):
    """Enqueue job envelope to Redis queue."""
    if not isinstance(envelope, dict) or not envelope.get('job_id'):
        return None, 'Invalid job envelope'
    
    client = _get_datapull_queue_client()
    if not client:
        return None, 'Redis queue is unavailable.'
    
    try:
        payload = json.dumps(envelope)
        try:
            delay_seconds = max(0, int(delay_seconds or 0))
        except Exception:
            delay_seconds = 0

        if delay_seconds > 0:
            due_ts = time.time() + delay_seconds
            client.zadd(_DATAPULL_DELAYED_QUEUE_KEY, {payload: due_ts})
        else:
            client.rpush(_DATAPULL_QUEUE_KEY, payload)
        persist_job_envelope(envelope)
        return envelope, None
    except Exception as e:
        return None, str(e)


def dequeue_job_envelope(block_seconds=5):
    """Dequeue job envelope from Redis queue; treats socket timeouts as empty polls."""
    client = _get_datapull_queue_client()
    if not client:
        return None, 'Redis queue is unavailable.'
    
    try:
        block_seconds = int(block_seconds)
    except Exception:
        block_seconds = 5
    block_seconds = max(1, min(block_seconds, 30))
    
    try:
        promote_due_delayed_jobs(max_count=20)
        popped = client.blpop(_DATAPULL_QUEUE_KEY, timeout=block_seconds)
        if not popped or len(popped) < 2:
            return None, None
        
        raw_message = popped[1]
        envelope = json.loads(raw_message)
        if not isinstance(envelope, dict):
            return None, 'Invalid queue message format.'
        return envelope, None
    except Exception as e:
        if 'Timeout reading from socket' in str(e):
            return None, None
        return None, str(e)


def move_to_dead_letter(envelope, reason):
    """Move job envelope to dead-letter queue when max retries exceeded."""
    if not isinstance(envelope, dict):
        return False
    
    client = _get_datapull_queue_client()
    if not client:
        return False
    
    envelope = dict(envelope)
    envelope['status'] = 'dead_lettered'
    envelope['dead_letter_reason'] = str(reason or '')
    envelope['dead_lettered_at'] = datetime.utcnow().isoformat() + 'Z'
    
    try:
        client.rpush(_DATAPULL_DEAD_LETTER_QUEUE_KEY, json.dumps(envelope))
        persist_job_envelope(envelope)
        return True
    except Exception as e:
        print(f"Error moving job to dead-letter: {e}")
        return False


def get_dead_letter_queue(limit=100):
    """Retrieve dead-lettered jobs for operational visibility."""
    mongo_client = None
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client['byoint_opslogs']
        jobs_col = db['datapull_jobs']
        
        docs = list(jobs_col.find({'status': 'dead_lettered'}).sort([('_created_timestamp', -1), ('dead_lettered_at', -1)]).limit(limit))
        for doc in docs:
            doc['_id'] = str(doc.get('_id', ''))
            if '_created_timestamp' in doc and hasattr(doc['_created_timestamp'], 'isoformat'):
                doc['_created_timestamp'] = doc['_created_timestamp'].isoformat()
        return docs
    except Exception as e:
        print(f"Error fetching dead-letter queue: {e}")
        return []
    finally:
        if mongo_client:
            mongo_client.close()


def requeue_dead_letter_job(job_id, requested_by=None):
    """Requeue a dead-lettered job envelope for another execution cycle."""
    envelope = load_job_envelope(job_id)
    if not envelope:
        return None, f"Job {job_id} not found"

    if str(envelope.get('status') or '').strip().lower() != 'dead_lettered':
        return None, f"Job {job_id} is not dead-lettered"

    now_iso = _utc_now_iso()
    previous_attempts = envelope.get('attempts') if isinstance(envelope.get('attempts'), list) else []
    envelope['attempt_history'] = previous_attempts
    envelope['attempts'] = []
    envelope['attempt_count'] = 0
    envelope['status'] = 'queued'
    envelope['error'] = None
    envelope['error_type'] = None
    envelope['retryable'] = None
    envelope['dead_letter_reason'] = None
    envelope['dead_lettered_at'] = None
    envelope['next_retry_at'] = None
    envelope['completed_at'] = None
    envelope['requeued_at'] = now_iso

    metadata = envelope.get('metadata') if isinstance(envelope.get('metadata'), dict) else {}
    metadata['requeued_by'] = requested_by or 'system'
    metadata['requeued_at'] = now_iso
    envelope['metadata'] = metadata

    queued, err = enqueue_job_envelope(envelope, delay_seconds=0)
    if err:
        return None, err
    return queued, None


def execute_queued_workflow_message(message, default_dp_module='datapull', custom_template_executor=None, cache_invalidator=None):
    """Execute job envelope with retry logic, idempotency locking, and dead-letter handling."""
    if not isinstance(message, dict):
        return {'status': 'error', 'error': 'Invalid queue message'}

    envelope = message if message.get('job_id') else None
    if envelope:
        job_id = envelope.get('job_id')
        source_name = str(envelope.get('source_name') or '').strip()
        trigger = str(envelope.get('trigger') or '').strip()
    else:
        job_id = str(message.get('message_id') or '').strip()
        source_name = str(message.get('source_name') or '').strip()
        trigger = str(message.get('trigger') or '').strip()

    if not source_name:
        error_msg = 'Queue message missing source_name'
        _log_scheduler_event('job_error', error=error_msg, details={'job_id': job_id})
        return {'status': 'error', 'error': error_msg, 'job_id': job_id}
    
    if envelope and job_id:
        attempt_count = envelope.get('attempt_count', 0) + 1
        if attempt_count > envelope.get('max_attempts', _MAX_JOB_ATTEMPTS):
            move_to_dead_letter(envelope, f'Max attempts ({envelope.get("max_attempts")}) exceeded')
            return {'status': 'dead_lettered', 'job_id': job_id, 'source_name': source_name, 'reason': 'Max attempts exceeded'}
        
        if not _acquire_job_lock(job_id, lock_ttl_seconds=600):
            return {'status': 'skipped', 'job_id': job_id, 'source_name': source_name, 'reason': 'Lock already held; another worker processing'}

    workflow = load_workflow_by_source_name(source_name)
    if not workflow:
        error_msg = f"Workflow '{source_name}' not found when dequeued"
        _log_scheduler_event('job_skipped_missing_workflow', source_name=source_name, error=error_msg, details={'job_id': job_id, 'trigger': trigger})
        if envelope:
            envelope['status'] = 'failed'
            envelope['error'] = error_msg
            persist_job_envelope(envelope)
        return {'status': 'error', 'error': error_msg, 'job_id': job_id}

    try:
        if envelope:
            envelope['status'] = 'running'
            envelope['attempt_count'] = attempt_count
            envelope['last_attempted_at'] = _utc_now_iso()
            persist_job_envelope(envelope)

        result = execute_workflow_shared(
            workflow=workflow,
            default_dp_module=default_dp_module,
            custom_template_executor=custom_template_executor,
            cache_invalidator=cache_invalidator
        )

        result_status = str((result or {}).get('status') or '').strip().lower()
        if result_status not in ('success', 'completed'):
            result_error = str((result or {}).get('error') or (result or {}).get('dp_log') or 'Workflow execution failed')
            raise RuntimeError(result_error)
        
        if envelope:
            envelope['status'] = 'completed'
            envelope['completed_at'] = _utc_now_iso()
            envelope['error'] = None
            envelope['error_type'] = None
            envelope['retryable'] = None
            envelope['next_retry_at'] = None
            attempt_record = {
                'attempt_number': attempt_count,
                'status': result_status,
                'started_at': envelope.get('last_attempted_at'),
                'completed_at': envelope['completed_at'],
                'duration_seconds': result.get('duration_seconds', 0),
            }
            if 'attempts' not in envelope or not isinstance(envelope['attempts'], list):
                envelope['attempts'] = []
            envelope['attempts'].append(attempt_record)
            persist_job_envelope(envelope)
            
            # Phase 6: Record success metric
            duration_ms = int(result.get('duration_seconds', 0) * 1000)
            record_job_metric(
                source_name=source_name,
                status='completed',
                duration_ms=duration_ms,
                attempt_number=attempt_count,
                trigger_source=envelope.get('trigger_source'),
                requested_by=envelope.get('requested_by')
            )

        result['job_id'] = job_id
        result['trigger'] = trigger
        return result
    except Exception as e:
        error_str = str(e)
        classification = _classify_job_error(error_str)
        retryable = bool(classification.get('retryable'))
        error_type = str(classification.get('error_type') or 'runtime_error')
        if envelope:
            envelope['status'] = 'failed'
            envelope['error'] = error_str
            envelope['error_type'] = error_type
            envelope['retryable'] = retryable
            attempt_record = {
                'attempt_number': attempt_count,
                'status': 'error',
                'started_at': envelope.get('last_attempted_at'),
                'error': error_str,
                'error_type': error_type,
                'retryable': retryable,
            }
            if 'attempts' not in envelope or not isinstance(envelope['attempts'], list):
                envelope['attempts'] = []
            envelope['attempts'].append(attempt_record)
            should_retry = retryable and attempt_count < envelope.get('max_attempts', _MAX_JOB_ATTEMPTS)
            if should_retry:
                # Phase 6: Record retry metric
                record_job_metric(
                    source_name=source_name,
                    status='failed_will_retry',
                    duration_ms=0,
                    error_type=error_type,
                    attempt_number=attempt_count,
                    trigger_source=envelope.get('trigger_source'),
                    requested_by=envelope.get('requested_by')
                )
                
                retry_delay_seconds = _calculate_retry_delay_seconds(attempt_count)
                next_retry_epoch = time.time() + retry_delay_seconds
                envelope['status'] = 'queued'
                envelope['next_retry_at'] = datetime.utcfromtimestamp(next_retry_epoch).isoformat() + 'Z'
                persist_job_envelope(envelope)
                enqueue_job_envelope(envelope, delay_seconds=retry_delay_seconds)
                _release_job_lock(job_id)
                return {
                    'status': 'failed_will_retry',
                    'job_id': job_id,
                    'source_name': source_name,
                    'attempt': attempt_count,
                    'retry_in_seconds': retry_delay_seconds,
                    'next_retry_at': envelope.get('next_retry_at'),
                    'error': error_str,
                    'error_type': error_type,
                }

            envelope['next_retry_at'] = None
            if attempt_count >= envelope.get('max_attempts', _MAX_JOB_ATTEMPTS) or not retryable:
                move_to_dead_letter(
                    envelope,
                    f"{error_type}: {error_str}" if error_type else error_str
                )
                # Phase 6: Record failure metric (dead-lettered)
                record_job_metric(
                    source_name=source_name,
                    status='dead_lettered',
                    duration_ms=0,
                    error_type=error_type,
                    attempt_number=attempt_count,
                    trigger_source=envelope.get('trigger_source'),
                    requested_by=envelope.get('requested_by')
                )
            else:
                persist_job_envelope(envelope)
                # Phase 6: Record failure metric (persisted for retry)
                record_job_metric(
                    source_name=source_name,
                    status='failed',
                    duration_ms=0,
                    error_type=error_type,
                    attempt_number=attempt_count,
                    trigger_source=envelope.get('trigger_source'),
                    requested_by=envelope.get('requested_by')
                )
        
        return {
            'status': 'error',
            'error': error_str,
            'job_id': job_id,
            'error_type': error_type,
            'retryable': retryable,
        }
    finally:
        if envelope and job_id:
            _release_job_lock(job_id)


# --- Phase 6: Metrics & Observability ---
def record_job_metric(source_name, status, duration_ms=0, error_type=None, attempt_number=1, trigger_source=None, requested_by=None):
    """Record job execution metric for observability (Phase 6).
    
    Stores metrics in MongoDB for analysis: completion rates, latency, error breakdown.
    """
    source_name = str(source_name or '').strip()
    if not source_name:
        return False
    
    mongo_client = None
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client['byoint_opslogs']
        metrics_col = db['datapull_metrics']
        
        metric_doc = {
            'timestamp': datetime.utcnow(),
            'source_name': source_name,
            'status': str(status or 'unknown'),
            'duration_ms': max(0, int(duration_ms or 0)),
            'error_type': str(error_type or '').strip() or None,
            'attempt_number': max(1, int(attempt_number or 1)),
            'trigger_source': str(trigger_source or 'unknown').strip() or None,
            'requested_by': str(requested_by or '').strip() or None,
        }
        
        metrics_col.insert_one(metric_doc)
        
        # Create indexes if they don't exist (lazy)
        try:
            metrics_col.create_index([('source_name', 1), ('timestamp', -1)])
            metrics_col.create_index([('timestamp', -1)])
            metrics_col.create_index([('status', 1)])
        except Exception:
            pass  # Indexes may already exist
        
        return True
    except Exception as e:
        print(f"Error recording job metric: {e}")
        return False
    finally:
        if mongo_client:
            mongo_client.close()


def get_job_metrics_summary(source_name=None, time_range_minutes=1440):
    """Get metrics summary: completion rate, latency stats, error breakdown (Phase 6).
    
    Args:
        source_name: optional filter by source; if None, aggregate across all sources
        time_range_minutes: lookback window (default 24h)
    
    Returns: {completion_rate_pct, avg_latency_ms, p95_latency_ms, p99_latency_ms, 
              error_breakdown, dead_letter_rate_pct}
    """
    mongo_client = None
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client['byoint_opslogs']
        metrics_col = db['datapull_metrics']
        
        cutoff_time = datetime.utcnow().timestamp() - (time_range_minutes * 60)
        cutoff_dt = datetime.utcfromtimestamp(cutoff_time)
        
        match_filter = {'timestamp': {'$gte': cutoff_dt}}
        if source_name:
            match_filter['source_name'] = str(source_name).strip()
        
        pipeline = [
            {'$match': match_filter},
            {'$facet': {
                'all_jobs': [
                    {'$count': 'total'},
                ],
                'status_counts': [
                    {'$group': {
                        '_id': '$status',
                        'count': {'$sum': 1}
                    }},
                ],
                'latency_stats': [
                    {'$match': {'duration_ms': {'$gt': 0}}},
                    {'$sort': {'duration_ms': 1}},
                    {'$group': {
                        '_id': None,
                        'avg_ms': {'$avg': '$duration_ms'},
                        'min_ms': {'$min': '$duration_ms'},
                        'max_ms': {'$max': '$duration_ms'},
                        'count': {'$sum': 1}
                    }},
                ],
                'error_breakdown': [
                    {'$match': {'error_type': {'$ne': None}}},
                    {'$group': {
                        '_id': '$error_type',
                        'count': {'$sum': 1}
                    }},
                    {'$sort': {'count': -1}},
                    {'$limit': 5},
                ],
            }},
        ]
        
        results = list(metrics_col.aggregate(pipeline))
        if not results:
            return None
        
        facet_result = results[0]
        total_jobs = facet_result.get('all_jobs', [{}])[0].get('total', 0) if facet_result.get('all_jobs') else 0
        
        if total_jobs == 0:
            return None
        
        status_counts = {item['_id']: item['count'] for item in facet_result.get('status_counts', [])}
        completed = status_counts.get('completed', 0) + status_counts.get('success', 0)
        completion_rate_pct = round((completed / total_jobs * 100), 2) if total_jobs > 0 else 0
        
        latency_stats = facet_result.get('latency_stats', [{}])[0]
        avg_latency_ms = round(latency_stats.get('avg_ms', 0), 2)
        
        # Percentile calculation (simplified: use max if less than 100 samples)
        # In production, use MongoDB's $percentile stage (MongoDB 5.2+)
        latency_count = latency_stats.get('count', 0)
        p95_latency_ms = latency_stats.get('max_ms', 0)
        p99_latency_ms = latency_stats.get('max_ms', 0)
        if latency_count > 10:
            p95_idx = int(latency_count * 0.95)
            p99_idx = int(latency_count * 0.99)
            metrics_sample = list(metrics_col.find(match_filter, {'duration_ms': 1}).sort('duration_ms', 1).limit(latency_count))
            if p95_idx < len(metrics_sample):
                p95_latency_ms = metrics_sample[p95_idx].get('duration_ms', 0)
            if p99_idx < len(metrics_sample):
                p99_latency_ms = metrics_sample[p99_idx].get('duration_ms', 0)
        
        error_breakdown = {item['_id']: item['count'] for item in facet_result.get('error_breakdown', [])}
        
        # Check dead-letter collection
        dead_letter_col = db['datapull_dead_letters']
        dead_letter_count = dead_letter_col.count_documents({'_created_timestamp': {'$gte': cutoff_dt}})
        dead_letter_rate_pct = round((dead_letter_count / total_jobs * 100), 2) if total_jobs > 0 else 0
        
        return {
            'total_jobs': total_jobs,
            'completion_rate_pct': completion_rate_pct,
            'avg_latency_ms': avg_latency_ms,
            'p95_latency_ms': p95_latency_ms,
            'p99_latency_ms': p99_latency_ms,
            'latency_count': latency_count,
            'status_breakdown': status_counts,
            'error_breakdown': error_breakdown,
            'dead_letter_count': dead_letter_count,
            'dead_letter_rate_pct': dead_letter_rate_pct,
            'time_range_minutes': time_range_minutes,
        }
    except Exception as e:
        print(f"Error querying job metrics: {e}")
        return None
    finally:
        if mongo_client:
            mongo_client.close()


def get_metrics_by_source(time_range_minutes=1440, limit=50):
    """Get per-source metrics breakdown (Phase 6).
    
    Returns list of {source_name, completion_rate_pct, avg_latency_ms, job_count, error_count}.
    """
    mongo_client = None
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client['byoint_opslogs']
        metrics_col = db['datapull_metrics']
        
        cutoff_time = datetime.utcnow().timestamp() - (time_range_minutes * 60)
        cutoff_dt = datetime.utcfromtimestamp(cutoff_time)
        
        pipeline = [
            {'$match': {'timestamp': {'$gte': cutoff_dt}}},
            {'$group': {
                '_id': '$source_name',
                'total_jobs': {'$sum': 1},
                'completed': {'$sum': {'$cond': [{'$eq': ['$status', 'completed']}, 1, 0]}},
                'failed': {'$sum': {'$cond': [{'$in': ['$status', ['failed', 'error']]}, 1, 0]}},
                'avg_duration_ms': {'$avg': '$duration_ms'},
                'max_duration_ms': {'$max': '$duration_ms'},
                'errors': {'$push': {'$cond': [{'$ne': ['$error_type', None]}, '$error_type', '$$REMOVE']}},
            }},
            {'$project': {
                'source_name': '$_id',
                'total_jobs': 1,
                'completed': 1,
                'failed': 1,
                'completion_rate_pct': {'$round': [{'$multiply': [{'$divide': ['$completed', '$total_jobs']}, 100]}, 2]},
                'avg_latency_ms': {'$round': ['$avg_duration_ms', 2]},
                'max_latency_ms': '$max_duration_ms',
                'error_count': {'$size': '$errors'},
                '_id': 0,
            }},
            {'$sort': {'total_jobs': -1}},
            {'$limit': limit},
        ]
        
        results = list(metrics_col.aggregate(pipeline))
        return results
    except Exception as e:
        print(f"Error querying per-source metrics: {e}")
        return []
    finally:
        if mongo_client:
            mongo_client.close()


# --- Route Registration ---
def register_routes(app, token_required):
    """Register all datapull-related routes."""
    
    @app.route('/api/datapull_workflows', methods=['GET'])
    @token_required
    def get_datapull_workflows():
        try:
            workflows = get_datapull_workflows_data()
            return jsonify({'workflows': workflows}), 200
        except Exception as e:
            return jsonify({'message': str(e)}), 500

    @app.route('/api/datapull/security-report', methods=['GET'])
    @token_required
    def get_datapull_security_report():
        """Return Phase 3 credential-security compliance report for datapull workflows."""
        try:
            source_name = str(request.args.get('source_name') or '').strip()
            include_compliant = str(request.args.get('include_compliant') or '').strip().lower() in ('1', 'true', 'yes')

            report = get_datapull_security_report_data(source_name=source_name, include_compliant=include_compliant)
            return jsonify(report), 200
        except Exception as e:
            return jsonify({'message': str(e)}), 500

    @app.route('/api/datapull/integrity-check', methods=['GET'])
    @token_required
    def get_datapull_integrity_check():
        """Return Datapull Integrity Check report (scheduled workflows by default)."""
        try:
            source_name = str(request.args.get('source_name') or '').strip()
            scheduled_only = str(request.args.get('scheduled_only') or 'true').strip().lower() in ('1', 'true', 'yes', 'y', 'on')
            lookback_runs_raw = request.args.get('lookback_runs')
            try:
                lookback_runs = int(lookback_runs_raw) if lookback_runs_raw is not None else 20
            except Exception:
                lookback_runs = 20

            report = get_datapull_integrity_report_data(
                source_name=source_name,
                scheduled_only=scheduled_only,
                lookback_runs=lookback_runs
            )
            if report is None:
                return jsonify({'message': 'Failed to generate integrity check report.'}), 500
            return jsonify(report), 200
        except Exception as e:
            return jsonify({'message': str(e)}), 500

    @app.route('/api/datapull_templates', methods=['GET'])
    @token_required
    def get_datapull_templates():
        try:
            templates = get_datapull_templates_data()
            return jsonify({'templates': templates}), 200
        except Exception as e:
            return jsonify({'message': str(e)}), 500

    @app.route('/api/datapull_templates/create', methods=['POST'])
    @token_required
    def create_datapull_template():
        if not request.is_json:
            return jsonify({'message': 'Request must be JSON.'}), 400
        data = request.json
        template_name = data.get('template_name')
        template_type = data.get('template_type')
        description = data.get('description')
        info = data.get('info')
        function_mapping = data.get('function_mapping')
        snippet_code = data.get('snippet_code') or data.get('python_snippet')
        ufield_args = data.get('ufield_args')
        if not template_name or not template_type:
            return jsonify({'message': 'Missing required fields.'}), 400
        try:
            doc, err = create_datapull_template_data(template_name, template_type, description, info, function_mapping, snippet_code, ufield_args)
            if err:
                return jsonify({'message': err}), 409 if 'already exists' in err else 400
            return jsonify({'message': 'Template created successfully!', 'template': doc}), 201
        except Exception as e:
            return jsonify({'message': str(e)}), 500

    @app.route('/api/datapull_executions', methods=['GET'])
    @token_required
    def get_datapull_executions():
        source_name = request.args.get('source_name')
        if not source_name:
            return jsonify({'message': 'Missing source_name parameter.'}), 400
        try:
            logs = get_datapull_executions_data(source_name)
            return jsonify({'logs': logs}), 200
        except Exception as e:
            return jsonify({'message': str(e)}), 500

    @app.route('/api/integration_capabilities', methods=['GET'])
    @token_required
    def list_integration_capabilities_route():
        """List tested integrations recorded in the support matrix."""
        try:
            return jsonify({'capabilities': list_integration_capabilities()}), 200
        except Exception as e:
            return jsonify({'message': str(e)}), 500

    @app.route('/api/integration_capabilities', methods=['POST'])
    @token_required
    def create_integration_capability_route():
        if not request.is_json:
            return jsonify({'message': 'Request must be JSON.'}), 400
        try:
            actor = str(getattr(g, 'current_user', '') or '').strip() or None
            doc, error = create_integration_capability(request.json or {}, actor=actor)
            if error:
                return jsonify({'message': error}), 400
            return jsonify({'message': 'Integration capability created.', 'capability': doc}), 201
        except Exception as e:
            return jsonify({'message': str(e)}), 500

    @app.route('/api/integration_capabilities/<string:capability_id>', methods=['PUT'])
    @token_required
    def update_integration_capability_route(capability_id):
        if not request.is_json:
            return jsonify({'message': 'Request must be JSON.'}), 400
        try:
            actor = str(getattr(g, 'current_user', '') or '').strip() or None
            doc, error = update_integration_capability(capability_id, request.json or {}, actor=actor)
            if error == 'not_found':
                return jsonify({'message': 'Integration capability not found.'}), 404
            if error:
                return jsonify({'message': error}), 400
            return jsonify({'message': 'Integration capability updated.', 'capability': doc}), 200
        except Exception as e:
            return jsonify({'message': str(e)}), 500

    @app.route('/api/integration_capabilities/<string:capability_id>', methods=['DELETE'])
    @token_required
    def delete_integration_capability_route(capability_id):
        try:
            if not delete_integration_capability(capability_id):
                return jsonify({'message': 'Integration capability not found.'}), 404
            return jsonify({'message': 'Integration capability deleted.'}), 200
        except Exception as e:
            return jsonify({'message': str(e)}), 500

    @app.route('/api/datapull/jobs', methods=['GET'])
    @token_required
    def get_datapull_jobs_route():
        """List datapull job envelopes for the jobs UI page."""
        try:
            status = request.args.get('status')
            source_name = request.args.get('source_name')
            limit = request.args.get('limit', 100)
            jobs = get_datapull_jobs_data(status=status, source_name=source_name, limit=limit)
            return jsonify({'jobs': jobs}), 200
        except Exception as e:
            return jsonify({'message': str(e)}), 500

    @app.route('/api/datapull/dead-letter-queue', methods=['GET'])
    @token_required
    def get_dead_letter_queue_route():
        """Retrieve jobs that exceeded max attempts (Phase 3)."""
        try:
            limit = int(request.args.get('limit', 100))
            limit = max(1, min(limit, 500))
            dead_letters = get_dead_letter_queue(limit=limit)
            return jsonify({'dead_letters': dead_letters}), 200
        except Exception as e:
            return jsonify({'message': str(e)}), 500

    @app.route('/api/datapull/dead-letter-queue/requeue', methods=['POST'])
    @token_required
    def requeue_dead_letter_job_route():
        """Requeue a dead-lettered job by job_id."""
        if not request.is_json:
            return jsonify({'message': 'Request must be JSON.'}), 400
        data = request.json or {}
        job_id = str(data.get('job_id') or '').strip()
        if not job_id:
            return jsonify({'message': 'job_id is required.'}), 400

        try:
            requested_by = str(getattr(g, 'current_user', '') or '').strip() or None
            queued, err = requeue_dead_letter_job(job_id=job_id, requested_by=requested_by)
            if err:
                status_code = 404 if 'not found' in str(err).lower() else 400
                return jsonify({'message': err}), status_code
            return jsonify({'message': 'Job requeued successfully.', 'job': queued}), 200
        except Exception as e:
            return jsonify({'message': str(e)}), 500

    @app.route('/api/datapull/job/<job_id>', methods=['GET'])
    @token_required
    def get_job_status_route(job_id):
        """Retrieve job envelope state (Phase 3)."""
        try:
            envelope = load_job_envelope(job_id)
            if not envelope:
                return jsonify({'message': f'Job {job_id} not found'}), 404
            return jsonify({'job': envelope}), 200
        except Exception as e:
            return jsonify({'message': str(e)}), 500

    @app.route('/api/source_names', methods=['GET'])
    @token_required
    def get_source_names():
        try:
            selected_type = str(request.args.get('type') or '').strip()
            names = get_source_names_data(selected_type=selected_type)
            return jsonify({'source_names': names}), 200
        except Exception as e:
            return jsonify({'message': str(e)}), 500

    @app.route('/api/secrets', methods=['GET'])
    @token_required
    def list_datapull_secrets_route():
        try:
            include_usage = str(request.args.get('include_usage') or '').strip().lower() in ('1', 'true', 'yes')
            secrets_list, err = list_datapull_secrets(include_usage=include_usage)
            if err:
                return jsonify({'message': err}), 500
            return jsonify({'secrets': secrets_list}), 200
        except Exception as e:
            return jsonify({'message': str(e)}), 500

    @app.route('/api/secrets/create', methods=['POST'])
    @token_required
    def create_datapull_secret_route():
        if not request.is_json:
            return jsonify({'message': 'Request must be JSON.'}), 400

        data = request.json or {}
        name = str(data.get('name') or '').strip()
        secret_value = data.get('value')
        description = data.get('description')
        description = str(description).strip() if description is not None else None

        if not name or secret_value in [None, '']:
            return jsonify({'message': 'name and value are required.'}), 400

        created_by = getattr(g, 'current_user', None)
        secret_meta, err = create_datapull_secret(
            name=name,
            secret_value=secret_value,
            created_by=created_by,
            description=description
        )
        if err:
            status = 409 if 'already exists' in str(err).lower() else 500
            return jsonify({'message': err}), status

        return jsonify({'message': 'Secret created successfully.', 'secret': secret_meta}), 201

    @app.route('/api/secrets/rotate', methods=['POST'])
    @token_required
    def rotate_datapull_secret_route():
        if not request.is_json:
            return jsonify({'message': 'Request must be JSON.'}), 400

        data = request.json or {}
        secret_ref = str(data.get('secret_ref') or '').strip()
        new_value = data.get('value')

        if not secret_ref or new_value in [None, '']:
            return jsonify({'message': 'secret_ref and value are required.'}), 400

        rotated_by = getattr(g, 'current_user', None)
        secret_meta, err = rotate_datapull_secret(
            secret_ref=secret_ref,
            new_secret_value=new_value,
            rotated_by=rotated_by
        )
        if err:
            status = 404 if 'not found' in str(err).lower() else 500
            return jsonify({'message': err}), status

        return jsonify({'message': 'Secret rotated successfully.', 'secret': secret_meta}), 200

    @app.route('/api/secrets/<secret_ref>', methods=['DELETE'])
    @token_required
    def delete_datapull_secret_route(secret_ref):
        normalized_ref = str(secret_ref or '').strip()
        if not normalized_ref:
            return jsonify({'message': 'secret_ref is required.'}), 400

        deleted_by = getattr(g, 'current_user', None)
        secret_meta, err = deactivate_datapull_secret(
            secret_ref=normalized_ref,
            deactivated_by=deleted_by
        )
        if err:
            err_text = str(err).lower()
            if 'referenced by workflows' in err_text:
                return jsonify({'message': err}), 409
            if 'not found' in err_text or 'inactive' in err_text:
                return jsonify({'message': err}), 404
            return jsonify({'message': err}), 500

        return jsonify({'message': 'Secret deactivated successfully.', 'secret': secret_meta}), 200

    @app.route('/api/datapull/create', methods=['POST'])
    @token_required
    def create_datapull():
        if not request.is_json:
            return jsonify({'message': 'Request must be JSON!'}), 400
        data = request.json or {}
        
        source_name = data.get('source_name')
        if not source_name:
            return jsonify({'message': 'Missing source_name!'}), 400
        
        source_category = data.get('source_category')
        source_template_type = data.get('source_template_type')
        
        if not source_category or not source_template_type:
            return jsonify({'message': 'Missing required fields!'}), 400
        
        datapull_payload = data.get('datapull_payload')
        payload_error = _validate_datapull_payload_security(datapull_payload)
        if payload_error:
            return jsonify({'message': payload_error}), 400
        
        try:
            source_description = data.get('source_description')
            source_type = data.get('source_type')
            tag = data.get('tag')
            br_score = data.get('br_score')
            scheduled = data.get('scheduled')
            schedule_enabled = data.get('schedule_enabled')
            enrichment_enabled = data.get('enrichment_enabled')
            selected_enrichments = data.get('selected_enrichments')
            schedule_interval_min = data.get('schedule_interval_min')
            
            if br_score is None and isinstance(datapull_payload, dict):
                br_score = datapull_payload.get('br_score')
            if isinstance(datapull_payload, dict) and 'br_score' in datapull_payload:
                datapull_payload = dict(datapull_payload)
                datapull_payload.pop('br_score', None)
            
            if scheduled is None:
                scheduled = bool(schedule_interval_min)
            if schedule_enabled is None:
                schedule_enabled = bool(scheduled)
            
            normalized_selected_enrichments = []
            if isinstance(selected_enrichments, list):
                normalized_selected_enrichments = [str(e).strip() for e in selected_enrichments if str(e).strip()]
            if enrichment_enabled is None:
                enrichment_enabled = bool(normalized_selected_enrichments)
            
            if not scheduled:
                schedule_interval_min = None
            
            result = create_datapull_workflow(
                source_name=source_name, source_category=source_category, source_type=source_type,
                tag=tag, source_template_type=source_template_type, source_description=source_description,
                scheduled=scheduled, schedule_enabled=schedule_enabled, schedule_interval_min=schedule_interval_min,
                datapull_payload=datapull_payload, br_score=br_score,
                selected_enrichments=normalized_selected_enrichments, enrichment_enabled=bool(enrichment_enabled),
                insertmany=bool(data.get('insertmany', False)),
                max_response_bytes=data.get('max_response_bytes'),
                max_query_rows=data.get('max_query_rows')
            )
            return jsonify({'message': 'Datapull created successfully!', 'result': result}), 201
        except Exception as e:
            return jsonify({'message': str(e)}), 500

    @app.route('/api/datapull/update', methods=['POST'])
    @token_required
    def update_datapull():
        if not request.is_json:
            return jsonify({'message': 'Request must be JSON!'}), 400
        data = request.json
        source_name = data.get('source_name')
        if not source_name:
            return jsonify({'message': 'Missing source_name!'}), 400
        try:
            success, error = update_datapull_workflow_data(source_name, data)
            if not success:
                return jsonify({'message': error}), 400 if 'found' not in error else 404
            return jsonify({'message': 'Datapull updated successfully!'}), 200
        except Exception as e:
            return jsonify({'message': str(e)}), 500

    @app.route('/api/datapull/delete/preview', methods=['POST'])
    @token_required
    def delete_datapull_preview():
        if not request.is_json:
            return jsonify({'message': 'Request must be JSON!'}), 400

        data = request.json or {}
        source_name = data.get('source_name')
        if not source_name:
            return jsonify({'message': 'Missing source_name!'}), 400

        try:
            impact, error = get_workflow_indicator_impact_data(source_name)
            if error:
                status_code = 404 if 'not found' in str(error).lower() else 400
                return jsonify({'message': error}), status_code

            return jsonify({'impact': impact}), 200
        except Exception as e:
            return jsonify({'message': str(e)}), 500

    @app.route('/api/datapull/delete', methods=['POST'])
    @token_required
    def delete_datapull():
        if not request.is_json:
            return jsonify({'message': 'Request must be JSON!'}), 400

        data = request.json or {}
        source_name = data.get('source_name')
        if not source_name:
            return jsonify({'message': 'Missing source_name!'}), 400

        try:
            result, error = delete_datapull_workflow_data(source_name)
            if error:
                status_code = 404 if 'not found' in str(error).lower() else 400
                return jsonify({'message': error}), status_code

            return jsonify({
                'message': 'Datapull workflow deleted successfully!',
                'result': result
            }), 200
        except Exception as e:
            return jsonify({'message': str(e)}), 500
