



from flask import Flask, request, jsonify, g, make_response
from flask_cors import CORS
from datetime import datetime, timedelta
import html
import json
from uuid import uuid4


from flask_apscheduler import APScheduler
from apscheduler.schedulers.background import BackgroundScheduler
import threading
import subprocess
import shutil

class Config:
    SCHEDULER_API_ENABLED = True

import logging,yaml,sys,os,atexit
import re
import requests
from urllib.parse import urlparse, quote
sys.path.append(os.path.dirname(__file__))

from authlib.integrations.flask_client import OAuth
from flasgger import Flasgger

import auth,datapull,data_output,all_connects,data_enrichments,endpoint_docs,bootstrap,mcp_output
import snippet_sandbox

# Keep this process's secrets out of reach of snippet child processes (covers gunicorn workers
# and queue_worker.py, which imports this module).
snippet_sandbox.protect_process_environ()


# --- Datapull Templates API ---
from pymongo import MongoClient



default_dp_fname = "datapull"




def _env_bool(name, default=False):
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in ('1', 'true', 'yes', 'on')


def _to_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


def _default_sso_config_values():
    return {
        # SSO is intentionally disabled by default until explicitly enabled in basicconfigs.
        'enable': False,
        'provider_name': 'Single Sign-On',
        'discovery_url': None,
        'client_id': None,
        'client_secret': None,
        'scopes': 'openid profile email',
        'auto_create_users': True,
        'redirect_uri': None
    }


def _default_api_audit_log_methods():
    # Keep audit logs focused by default to write operations.
    return ['POST']


def _default_worker_scaling_config():
    return {
        'desired_worker_count': 1,
        'auto_scaling_enabled': False,
        'min_workers': 1,
        'max_workers': 10,
    }


def _normalize_http_methods(raw_methods, default_methods=None):
    default_methods = default_methods or []
    if raw_methods is None:
        raw_methods = default_methods

    if isinstance(raw_methods, str):
        candidates = [entry.strip() for entry in raw_methods.split(',') if entry.strip()]
    elif isinstance(raw_methods, (list, tuple, set)):
        candidates = [str(entry).strip() for entry in raw_methods if str(entry).strip()]
    else:
        candidates = []

    normalized = []
    for method in candidates:
        upper_method = str(method).strip().upper()
        if not upper_method:
            continue
        if upper_method in ('ALL', '*'):
            return ['*']
        normalized.append(upper_method)

    if not normalized:
        normalized = [str(entry).strip().upper() for entry in default_methods if str(entry).strip()]

    # Preserve order while de-duplicating.
    deduped = []
    seen = set()
    for method in normalized:
        if method in seen:
            continue
        seen.add(method)
        deduped.append(method)
    return deduped


def _ensure_and_load_core_sso_config():
    defaults = _default_sso_config_values()
    default_public_api_endpoints = []
    default_api_audit_log_methods = _default_api_audit_log_methods()
    default_worker_scaling_config = _default_worker_scaling_config()
    default_output_categories = _default_output_categories()
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client['byoint_core_config']
        basicconfigs_col = db['basicconfigs']

        core_doc = basicconfigs_col.find_one({'module': 'core'})
        if not core_doc:
            new_doc = {
                'module': 'core',
                'sso': defaults,
                'PUBLIC_API_ENDPOINTS': default_public_api_endpoints,
                'API_AUDIT_LOG_METHODS': default_api_audit_log_methods,
                'worker_scaling': default_worker_scaling_config,
                'output_categories': default_output_categories,
                all_connects.ALLOW_CUSTOM_SNIPPET_KEY: False,
            }
            basicconfigs_col.insert_one(new_doc)
            mongo_client.close()
            return new_doc, True

        sso_settings = core_doc.get('sso')
        if not isinstance(sso_settings, dict):
            sso_settings = {}

        # Backward compatibility: migrate legacy flat SSO fields into nested sso object.
        legacy_to_nested_map = {
            'sso_enable': 'enable',
            'sso_provider_name': 'provider_name',
            'sso_discovery_url': 'discovery_url',
            'sso_client_id': 'client_id',
            'sso_client_secret': 'client_secret',
            'sso_scopes': 'scopes',
            'sso_auto_create_users': 'auto_create_users',
            'sso_redirect_uri': 'redirect_uri'
        }
        for legacy_key, nested_key in legacy_to_nested_map.items():
            if nested_key not in sso_settings and legacy_key in core_doc:
                sso_settings[nested_key] = core_doc.get(legacy_key)

        for key, value in defaults.items():
            if key not in sso_settings:
                sso_settings[key] = value

        # Keep public API allowlist in core config so API-key access can be restricted by endpoint.
        public_api_endpoints = core_doc.get('PUBLIC_API_ENDPOINTS')
        if public_api_endpoints is None:
            public_api_endpoints = core_doc.get('public_api_endpoints')
        if public_api_endpoints is None:
            public_api_endpoints = list(default_public_api_endpoints)
        if isinstance(public_api_endpoints, str):
            public_api_endpoints = [entry.strip() for entry in public_api_endpoints.split(',') if entry.strip()]
        elif not isinstance(public_api_endpoints, list):
            public_api_endpoints = list(default_public_api_endpoints)

        api_audit_log_methods = core_doc.get('API_AUDIT_LOG_METHODS')
        if api_audit_log_methods is None:
            api_audit_log_methods = core_doc.get('api_audit_log_methods')
        api_audit_log_methods = _normalize_http_methods(
            api_audit_log_methods,
            default_methods=default_api_audit_log_methods
        )

        worker_scaling = core_doc.get('worker_scaling')
        if not isinstance(worker_scaling, dict):
            worker_scaling = {}
        for key, value in default_worker_scaling_config.items():
            if key not in worker_scaling:
                worker_scaling[key] = value

        output_categories = core_doc.get('output_categories')
        if isinstance(output_categories, str):
            output_categories = [entry.strip() for entry in output_categories.split(',') if entry.strip()]
        elif not isinstance(output_categories, list):
            output_categories = list(default_output_categories)

        normalized_output_categories = []
        seen_output_categories = set()
        for entry in output_categories + default_output_categories:
            normalized_entry = str(entry or '').strip()
            normalized_key = normalized_entry.lower()
            if not normalized_entry or normalized_key in seen_output_categories:
                continue
            seen_output_categories.add(normalized_key)
            normalized_output_categories.append(normalized_entry)

        basicconfigs_col.update_one(
            {'_id': core_doc['_id']},
            {
                '$set': {
                    'sso': sso_settings,
                    'PUBLIC_API_ENDPOINTS': public_api_endpoints,
                    'API_AUDIT_LOG_METHODS': api_audit_log_methods,
                    'worker_scaling': worker_scaling,
                    'output_categories': normalized_output_categories,
                }
            }
        )
        core_doc['sso'] = sso_settings
        core_doc['PUBLIC_API_ENDPOINTS'] = public_api_endpoints
        core_doc['API_AUDIT_LOG_METHODS'] = api_audit_log_methods
        core_doc['worker_scaling'] = worker_scaling
        core_doc['output_categories'] = normalized_output_categories

        mongo_client.close()
        return core_doc, True
    except Exception as e:
        print(f'Warning: failed to load SSO config from basicconfigs; SSO is disabled: {e}')
        return {}, False


def _resolve_sso_setting(config_doc, key, default=None):
    if isinstance(config_doc, dict) and key in config_doc:
        return config_doc.get(key)
    return default


def _coerce_worker_scaling_config(raw_value):
    defaults = _default_worker_scaling_config()
    cfg = dict(defaults)
    if isinstance(raw_value, dict):
        cfg.update(raw_value)

    try:
        cfg['desired_worker_count'] = int(cfg.get('desired_worker_count', defaults['desired_worker_count']))
    except Exception:
        cfg['desired_worker_count'] = defaults['desired_worker_count']

    cfg['auto_scaling_enabled'] = bool(cfg.get('auto_scaling_enabled', defaults['auto_scaling_enabled']))

    try:
        cfg['min_workers'] = int(cfg.get('min_workers', defaults['min_workers']))
    except Exception:
        cfg['min_workers'] = defaults['min_workers']

    try:
        cfg['max_workers'] = int(cfg.get('max_workers', defaults['max_workers']))
    except Exception:
        cfg['max_workers'] = defaults['max_workers']

    cfg['min_workers'] = max(1, cfg['min_workers'])
    cfg['max_workers'] = max(cfg['min_workers'], cfg['max_workers'])
    cfg['desired_worker_count'] = max(cfg['min_workers'], min(cfg['desired_worker_count'], cfg['max_workers']))
    return cfg


def _default_output_categories():
    return ['general', 'blocklist', 'allowlist']


def _get_runtime_worker_scaling_state():
    workers = datapull.list_worker_metrics()
    active_workers = [worker for worker in workers if not worker.get('is_stale')]
    queue_depth = datapull.get_workflow_queue_depth()
    return {
        'queue_depth': int(queue_depth or 0),
        'worker_count_total': len(workers),
        'worker_count_active': len(active_workers),
        'workers': workers,
    }


def _scale_compose_workers(desired_worker_count):
    docker_binary = shutil.which('docker')
    if not docker_binary:
        return {
            'ok': False,
            'message': 'docker CLI is not available in this runtime. Use the command from your host shell.',
            'command': f'docker compose -f docker-compose.yml up -d --scale datapull_worker={desired_worker_count}'
        }

    command = [
        docker_binary,
        'compose',
        '-f',
        'docker-compose.yml',
        'up',
        '-d',
        '--scale',
        f'datapull_worker={desired_worker_count}'
    ]

    try:
        completed = subprocess.run(
            command,
            cwd=os.path.dirname(os.path.dirname(__file__)),
            capture_output=True,
            text=True,
            timeout=180,
            check=False
        )
    except Exception as e:
        return {
            'ok': False,
            'message': f'Failed to run docker compose scaling command: {e}',
            'command': ' '.join(command)
        }

    if completed.returncode != 0:
        err_text = (completed.stderr or completed.stdout or '').strip()
        return {
            'ok': False,
            'message': f'docker compose scaling failed: {err_text or "unknown error"}',
            'command': ' '.join(command)
        }

    return {
        'ok': True,
        'message': 'Worker scaling command executed successfully.',
        'command': ' '.join(command),
        'output': (completed.stdout or '').strip()
    }

SESSION_COOKIE_SECURE = _env_bool('SESSION_COOKIE_SECURE', False)
SESSION_COOKIE_NAME = os.getenv('SESSION_COOKIE_NAME', '__Host-byoint_session' if SESSION_COOKIE_SECURE else 'byoint_session')
SESSION_COOKIE_MAX_AGE = max(300, int(os.getenv('SESSION_IDLE_MINUTES', '30')) * 60)
SESSION_COOKIE_SAMESITE = os.getenv('SESSION_COOKIE_SAMESITE', 'Lax')
FRONTEND_BASE_URL = str(os.getenv('FRONTEND_BASE_URL') or '').rstrip('/')
_CORE_SSO_CONFIG, _CORE_SSO_CONFIG_LOADED = _ensure_and_load_core_sso_config()
_SSO_SETTINGS = _CORE_SSO_CONFIG.get('sso') if isinstance(_CORE_SSO_CONFIG.get('sso'), dict) else {}
SSO_ENABLED = _to_bool(
    _resolve_sso_setting(_SSO_SETTINGS, 'enable', False),
    default=False
 ) and _CORE_SSO_CONFIG_LOADED
SSO_PROVIDER_NAME = _resolve_sso_setting(
    _SSO_SETTINGS,
    'provider_name',
    'Single Sign-On'
)
SSO_DISCOVERY_URL = _resolve_sso_setting(_SSO_SETTINGS, 'discovery_url')
SSO_CLIENT_ID = _resolve_sso_setting(_SSO_SETTINGS, 'client_id')
SSO_CLIENT_SECRET = _resolve_sso_setting(_SSO_SETTINGS, 'client_secret')
SSO_SCOPES = _resolve_sso_setting(_SSO_SETTINGS, 'scopes', 'openid profile email')
SSO_AUTO_CREATE_USERS = _to_bool(
    _resolve_sso_setting(_SSO_SETTINGS, 'auto_create_users', True),
    default=True
)
SSO_REDIRECT_URI = _resolve_sso_setting(_SSO_SETTINGS, 'redirect_uri')
PUBLIC_API_ENDPOINTS = (
    _CORE_SSO_CONFIG.get('PUBLIC_API_ENDPOINTS')
    if isinstance(_CORE_SSO_CONFIG, dict)
    else None
)
if PUBLIC_API_ENDPOINTS is None and isinstance(_CORE_SSO_CONFIG, dict):
    PUBLIC_API_ENDPOINTS = _CORE_SSO_CONFIG.get('public_api_endpoints')
if PUBLIC_API_ENDPOINTS is None:
    PUBLIC_API_ENDPOINTS = os.getenv('PUBLIC_API_ENDPOINTS')

API_AUDIT_LOG_METHODS = None
if isinstance(_CORE_SSO_CONFIG, dict):
    API_AUDIT_LOG_METHODS = _CORE_SSO_CONFIG.get('API_AUDIT_LOG_METHODS')
if API_AUDIT_LOG_METHODS is None and isinstance(_CORE_SSO_CONFIG, dict):
    API_AUDIT_LOG_METHODS = _CORE_SSO_CONFIG.get('api_audit_log_methods')
if API_AUDIT_LOG_METHODS is None:
    API_AUDIT_LOG_METHODS = os.getenv('API_AUDIT_LOG_METHODS')
API_AUDIT_LOG_METHODS = _normalize_http_methods(
    API_AUDIT_LOG_METHODS,
    default_methods=_default_api_audit_log_methods()
)
API_AUDIT_LOG_METHODS_SET = set(API_AUDIT_LOG_METHODS)


def _should_log_api_audit(path, method):
    if not str(path or '').startswith('/api/'):
        return False
    if str(method or '').upper() == 'OPTIONS':
        return False
    if '*' in API_AUDIT_LOG_METHODS_SET:
        return True
    return str(method or '').upper() in API_AUDIT_LOG_METHODS_SET


def _get_frontend_origins():
    configured_origins = os.getenv('FRONTEND_ORIGINS')
    if configured_origins:
        return [origin.strip() for origin in configured_origins.split(',') if origin.strip()]

    return [
        'http://localhost:8080',
        'http://127.0.0.1:8080',
        'http://localhost:8081',
        'http://127.0.0.1:8081',
        'http://localhost:5173',
        'http://127.0.0.1:5173'
    ]


app = Flask(__name__)
CORS(app, supports_credentials=True, origins=_get_frontend_origins())
app.secret_key = os.getenv('FLASK_SECRET_KEY') or os.getenv('SECRET_KEY')
if not app.secret_key:
    raise RuntimeError('Missing Flask session secret. Set FLASK_SECRET_KEY or SECRET_KEY before starting the application.')
app.config['SESSION_COOKIE_NAME'] = os.getenv('FLASK_STATE_COOKIE_NAME', 'byoint_oidc_state')
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = SESSION_COOKIE_SAMESITE
app.config['SESSION_COOKIE_SECURE'] = SESSION_COOKIE_SECURE

# Initialize Flasgger for OpenAPI/Swagger documentation.
# Docs are available at /api/docs and spec at /api/docs.json
_swagger_enabled = _env_bool('SWAGGER_DOCS_ENABLED', True)
if _swagger_enabled:
    swagger_template = {
        'swagger': '2.0',
        'info': {
            'title': 'ByoInt API',
            'version': '1.0.0',
            'description': 'Indicator management, data enrichment, and datapull orchestration API',
        },
        'basePath': '/',
    }

    swagger_config = {
        'headers': [],
        'specs': [{
            'endpoint': 'spec',
            'route': '/api/docs.json',
            'rule_filter': lambda rule: True,  # Document all routes
            'model_filter': lambda tag: True,
        }],
        'static_url_path': '/api/flasgger_static',
        'swagger_ui': True,
        'specs_route': '/api/docs',
    }

    Flasgger(
        app,
        template=swagger_template,
        config=swagger_config,
    )


def _get_request_source_details():
    forwarded_for = str(request.headers.get('X-Forwarded-For') or '').strip()
    access_route = [str(item).strip() for item in request.access_route or [] if str(item).strip()]
    client_ip = access_route[0] if access_route else str(request.headers.get('X-Real-IP') or request.remote_addr or '').strip() or None

    return {
        'client_ip': client_ip,
        'forwarded_for': forwarded_for or None,
        'access_route': access_route or None,
        'origin': str(request.headers.get('Origin') or '').strip() or None,
        'referer': str(request.headers.get('Referer') or '').strip() or None,
        'user_agent': str(request.headers.get('User-Agent') or '').strip() or None,
        'host': str(request.headers.get('Host') or '').strip() or None,
        'scheme': request.scheme,
    }


def _is_mutating_api_request(path, method):
    normalized_path = str(path or '').strip()
    normalized_method = str(method or '').strip().upper()
    if not normalized_path.startswith('/api/'):
        return False
    return normalized_method in ('POST', 'PUT', 'PATCH', 'DELETE')


def _classify_change_action(path, method):
    normalized_path = str(path or '').strip().lower()
    normalized_method = str(method or '').strip().upper()

    if normalized_method == 'DELETE' or '/delete' in normalized_path:
        return 'deleted'
    if '/create' in normalized_path or normalized_path.endswith('/new'):
        return 'created'
    if '/update' in normalized_path or normalized_method in ('PUT', 'PATCH'):
        return 'updated'
    if normalized_method == 'POST':
        return 'changed'
    return normalized_method.lower() or 'unknown'


def _classify_change_source(auth_type):
    normalized = str(auth_type or '').strip().lower()
    if normalized == 'session':
        return 'ui'
    if normalized == 'api_key':
        return 'external_api'
    return 'system'


def _entity_from_path(path):
    chunks = [chunk for chunk in str(path or '').strip('/').split('/') if chunk]
    if len(chunks) < 2:
        return None
    # /api/<entity>/...
    return chunks[1]


def _collection_for_entity(entity):
    entity_map = {
        'datapull': ('byoint_core_data', 'datapull_workflows'),
        'datapull_templates': ('byoint_core_config', 'datapull_templates'),
        'data_types': ('byoint_core_config', 'data_types'),
        'tags': ('byoint_core_config', 'tags'),
        'users': ('byoint_core_config', 'users'),
        'secrets': ('byoint_core_config', 'datapull_secrets'),
        'data_enrichments': ('byoint_core_config', 'data_enrichments'),
        'configuration': ('byoint_core_config', 'basicconfigs'),
        'output-guardrails': ('byoint_core_config', 'output_guardrails'),
        'indicators': ('byoint_core_data', 'indicators'),
    }
    return entity_map.get(str(entity or '').strip().lower())


def _extract_entity_id(path, payload):
    payload = payload if isinstance(payload, dict) else {}
    for key in ('id', '_id', 'name', 'source_name', 'template_name', 'secret_ref', 'user', 'value'):
        val = payload.get(key)
        if val not in [None, '']:
            return str(val)

    chunks = [chunk for chunk in str(path or '').strip('/').split('/') if chunk]
    if len(chunks) >= 3 and chunks[-1] not in ('create', 'update', 'delete', 'requeue', 'new'):
        return str(chunks[-1])
    return None


def _extract_entity_lookup(path, entity, payload, response_payload):
    payload = payload if isinstance(payload, dict) else {}
    response_payload = response_payload if isinstance(response_payload, dict) else {}

    path_chunks = [chunk for chunk in str(path or '').strip('/').split('/') if chunk]
    path_tail = path_chunks[-1] if len(path_chunks) >= 3 else None
    if path_tail in ('create', 'update', 'delete', 'requeue'):
        path_tail = None

    # Common lookup keys by preference.
    candidate_keys = ['value', 'source_name', 'template_name', 'name', 'secret_ref', 'tag', 'user', 'module', 'enrich_name', 'rule_id', 'id']

    for key in candidate_keys:
        value = payload.get(key)
        if value not in [None, '']:
            return {key: value}

    # Check nested response envelopes.
    for root_key in ('result', 'template', 'secret', 'user', 'tag', 'data_type', 'workflow'):
        node = response_payload.get(root_key)
        if isinstance(node, dict):
            for key in candidate_keys:
                value = node.get(key)
                if value not in [None, '']:
                    return {key: value}

    for key in candidate_keys:
        value = response_payload.get(key)
        if value not in [None, '']:
            return {key: value}

    if path_tail not in [None, '']:
        # Infer ID key based on entity where possible.
        inferred_key = 'id'
        if entity == 'data_types':
            inferred_key = 'name'
        elif entity == 'secrets':
            inferred_key = 'secret_ref'
        elif entity == 'users':
            inferred_key = 'user'
        elif entity == 'datapull':
            inferred_key = 'source_name'
        elif entity == 'datapull_templates':
            inferred_key = 'template_name'
        return {inferred_key: path_tail}

    return None


def _serialize_change_value(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _serialize_change_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_serialize_change_value(v) for v in value]
    if hasattr(value, '__class__') and value.__class__.__name__ == 'ObjectId':
        return str(value)
    return value


def _fetch_change_snapshot(entity, lookup):
    if not isinstance(lookup, dict) or not lookup:
        return None

    target = _collection_for_entity(entity)
    if not target:
        return None

    mongo_client = None
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        db_name, collection_name = target
        db = mongo_client[db_name]
        col = db[collection_name]
        doc = col.find_one(lookup)
        return _serialize_change_value(doc) if doc else None
    except Exception:
        return None
    finally:
        if mongo_client:
            mongo_client.close()


def _compute_field_changes(before_snapshot, after_snapshot):
    if not isinstance(before_snapshot, dict) and not isinstance(after_snapshot, dict):
        return []

    before_snapshot = before_snapshot if isinstance(before_snapshot, dict) else {}
    after_snapshot = after_snapshot if isinstance(after_snapshot, dict) else {}

    keys = sorted(set(before_snapshot.keys()) | set(after_snapshot.keys()))
    changes = []
    for key in keys:
        old_value = before_snapshot.get(key)
        new_value = after_snapshot.get(key)
        if old_value != new_value:
            changes.append({
                'field': key,
                'before': _sanitize_change_payload(old_value),
                'after': _sanitize_change_payload(new_value),
            })
    return changes


def _humanize_entity_label(entity):
    raw = str(entity or '').strip().replace('_', ' ').replace('-', ' ')
    raw = ' '.join([token for token in raw.split(' ') if token])
    if not raw:
        return 'record'
    return raw.lower()


def _build_change_summary(action, entity, entity_id, field_changes):
    action = str(action or '').strip().lower()
    entity_label = _humanize_entity_label(entity)
    entity_id_text = str(entity_id or '').strip()
    entity_phrase = f"{entity_label} '{entity_id_text}'" if entity_id_text else entity_label

    if action == 'created':
        return f"New {entity_phrase} was created."

    if action == 'deleted':
        return f"{entity_phrase.capitalize()} was deleted."

    if action in ('updated', 'changed'):
        changed_fields = []
        if isinstance(field_changes, list):
            changed_fields = [str((entry or {}).get('field') or '').strip() for entry in field_changes if str((entry or {}).get('field') or '').strip()]

        if changed_fields:
            top_fields = changed_fields[:5]
            suffix = '...' if len(changed_fields) > 5 else ''
            return f"{entity_phrase.capitalize()} was updated. Fields: {', '.join(top_fields)}{suffix}"
        return f"{entity_phrase.capitalize()} was updated."

    return f"{entity_phrase.capitalize()} was changed."


def _derive_change_action(initial_action, before_snapshot, after_snapshot, status_code):
    initial_action = str(initial_action or '').strip().lower()
    status_code = int(status_code or 0)

    # Keep explicit delete/create actions when path/method already classify them.
    if initial_action in ('created', 'deleted', 'updated'):
        return initial_action

    # Infer common CRUD outcomes for generic POST endpoints.
    if before_snapshot is None and after_snapshot is not None:
        return 'created'
    if before_snapshot is not None and after_snapshot is None:
        return 'deleted'
    if before_snapshot is not None and after_snapshot is not None:
        return 'updated'

    if status_code == 201:
        return 'created'
    if status_code in (200, 204):
        return 'updated'

    return initial_action or 'changed'


def _extract_response_payload(response):
    try:
        content_type = str(response.content_type or '').lower()
        if 'application/json' not in content_type:
            return None
        raw_text = response.get_data(as_text=True)
        if not raw_text:
            return None
        parsed = json.loads(raw_text)
        return parsed if isinstance(parsed, dict) else {'value': parsed}
    except Exception:
        return None


def _sanitize_change_payload(value):
    sensitive_markers = ('password', 'secret', 'token', 'apikey', 'api_key', 'client_secret', 'private_key', 'access_key')

    if isinstance(value, dict):
        sanitized = {}
        for key, child in value.items():
            key_text = str(key or '').strip().lower()
            if any(marker in key_text for marker in sensitive_markers):
                sanitized[key] = '***'
            else:
                sanitized[key] = _sanitize_change_payload(child)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_change_payload(item) for item in value]
    return value


def _write_platform_change_log(response, request_id, source_details, duration_ms):
    if not _is_mutating_api_request(request.path, request.method):
        return None

    status_code = int(getattr(response, 'status_code', 0) or 0)
    if status_code >= 400:
        return None

    ignored_paths = {
        '/api/audit-logs',
        '/api/platform-change-logs',
        '/api/auth',
        '/api/auth/sso/login',
        '/api/auth/sso/callback',
        '/api/logout',
        '/api/whoami',
        '/api/configuration/mongo-init/trigger',
    }
    if str(request.path or '').strip() in ignored_paths:
        return None

    payload = getattr(g, 'platform_change_payload', None)
    payload = payload if isinstance(payload, dict) else {}
    response_payload = _extract_response_payload(response)
    response_payload = response_payload if isinstance(response_payload, dict) else {}
    initial_action = _classify_change_action(request.path, request.method)
    source = _classify_change_source(getattr(g, 'auth_type', None))
    actor = getattr(g, 'current_user', None)
    entity = _entity_from_path(request.path)
    entity_lookup = _extract_entity_lookup(request.path, entity, payload, response_payload)

    before_snapshot = getattr(g, 'platform_change_before_snapshot', None)
    after_snapshot = _fetch_change_snapshot(entity, entity_lookup)

    action = _derive_change_action(initial_action, before_snapshot, after_snapshot, status_code)
    field_changes = _compute_field_changes(before_snapshot, after_snapshot)
    entity_id = _extract_entity_id(request.path, payload)
    if not entity_id and isinstance(entity_lookup, dict) and entity_lookup:
        try:
            entity_id = str(next(iter(entity_lookup.values())))
        except Exception:
            entity_id = None
    change_summary = _build_change_summary(action, entity, entity_id, field_changes)

    change_doc = {
        'request_id': request_id,
        'created_at': all_connects._utc_now(),
        'action': action,
        'source': source,
        'actor': actor,
        'method': request.method,
        'path': request.path,
        'entity': entity,
        'entity_id': entity_id,
        'summary': change_summary,
        'change_fields': sorted(list(payload.keys())),
        'changes': _sanitize_change_payload(payload),
        'request_payload': _sanitize_change_payload(payload),
        'response_payload': _sanitize_change_payload(response_payload),
        'entity_lookup': _sanitize_change_payload(entity_lookup),
        'before_snapshot': _sanitize_change_payload(before_snapshot),
        'after_snapshot': _sanitize_change_payload(after_snapshot),
        'field_changes': field_changes,
        'status_code': status_code,
        'duration_ms': duration_ms,
        'client_ip': (source_details or {}).get('client_ip'),
        'auth_type': getattr(g, 'auth_type', None),
    }

    mongo_client = None
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client['byoint_opslogs']
        change_logs = db['platform_change_logs']
        change_logs.insert_one(change_doc)
    except Exception as e:
        app.logger.warning('Failed to write platform change log: %s', e)
    finally:
        if mongo_client:
            mongo_client.close()
    return None


def _write_manual_platform_change_log(
    request_id,
    action,
    entity,
    entity_id,
    summary,
    details,
    status_code,
    duration_ms,
    source_details,
):
    """Write an explicit platform change log entry for custom workflows."""
    change_doc = {
        'request_id': request_id,
        'created_at': all_connects._utc_now(),
        'action': str(action or '').strip().lower() or 'changed',
        'source': _classify_change_source(getattr(g, 'auth_type', None)),
        'actor': getattr(g, 'current_user', None),
        'method': request.method,
        'path': request.path,
        'entity': entity,
        'entity_id': entity_id,
        'summary': summary,
        'status_code': int(status_code or 0),
        'duration_ms': duration_ms,
        'client_ip': (source_details or {}).get('client_ip'),
        'auth_type': getattr(g, 'auth_type', None),
        'changes': _sanitize_change_payload(details),
        'request_payload': _sanitize_change_payload(details),
    }

    mongo_client = None
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client['byoint_opslogs']
        change_logs = db['platform_change_logs']
        change_logs.insert_one(change_doc)
    except Exception as e:
        app.logger.warning('Failed to write manual platform change log: %s', e)
    finally:
        if mongo_client:
            mongo_client.close()
    return None


@app.before_request
def _start_api_audit_timer():
    should_log_api = _should_log_api_audit(request.path, request.method)
    if should_log_api:
        g.api_audit_started_at = all_connects._utc_now()

    if should_log_api or _is_mutating_api_request(request.path, request.method):
        g.api_audit_request_id = str(
            request.headers.get('X-Request-Id')
            or request.headers.get('X-Correlation-Id')
            or uuid4().hex
        ).strip() or uuid4().hex

    if _is_mutating_api_request(request.path, request.method):
        payload = request.get_json(silent=True)
        payload = payload if isinstance(payload, dict) else {}
        g.platform_change_payload = payload
        entity = _entity_from_path(request.path)
        lookup = _extract_entity_lookup(request.path, entity, payload, {})
        g.platform_change_before_snapshot = _fetch_change_snapshot(entity, lookup)
    return None


@app.after_request
def _write_api_audit_log(response):
    try:
        should_log_api = _should_log_api_audit(request.path, request.method)
        started_at = getattr(g, 'api_audit_started_at', None)
        duration_ms = None
        if started_at:
            duration_ms = int((all_connects._utc_now() - started_at).total_seconds() * 1000)

        request_id = getattr(g, 'api_audit_request_id', None) or str(
            request.headers.get('X-Request-Id')
            or request.headers.get('X-Correlation-Id')
            or uuid4().hex
        ).strip() or uuid4().hex

        source_details = _get_request_source_details()

        # Platform change logs are independent of API audit method filters.
        _write_platform_change_log(response, request_id, source_details, duration_ms)

        if not should_log_api:
            return response

        session_id = getattr(g, 'session_id', None)
        audit_doc = {
            'request_id': request_id,
            'created_at': all_connects._utc_now(),
            'method': request.method,
            'path': request.path,
            'endpoint': request.endpoint,
            'query_keys': sorted(request.args.keys()),
            'status_code': int(getattr(response, 'status_code', 0) or 0),
            'duration_ms': duration_ms,
            'source': source_details,
            'auth': {
                'type': getattr(g, 'auth_type', None),
                'user': getattr(g, 'current_user', None),
                'session_id_hash': all_connects._hash_session_id(session_id) if session_id else None,
            },
            'request': {
                'content_type': request.content_type,
                'content_length': request.content_length,
            },
            'response': {
                'content_length': response.calculate_content_length(),
            },
        }
        all_connects.write_api_audit_log(audit_doc)
    except Exception as e:
        app.logger.warning('Failed to write API audit log: %s', e)

    return response
oauth = OAuth(app)
oauth_oidc_client = None
if SSO_ENABLED and SSO_DISCOVERY_URL and SSO_CLIENT_ID:
    oauth_oidc_client = oauth.register(
        name='oidc',
        client_id=SSO_CLIENT_ID,
        client_secret=SSO_CLIENT_SECRET,
        server_metadata_url=SSO_DISCOVERY_URL,
        client_kwargs={'scope': SSO_SCOPES}
    )

token_required = auth.register_routes(
    app,
    oauth_oidc_client=oauth_oidc_client,
    settings={
        'session_cookie_name': SESSION_COOKIE_NAME,
        'session_cookie_max_age': SESSION_COOKIE_MAX_AGE,
        'session_cookie_samesite': SESSION_COOKIE_SAMESITE,
        'session_cookie_secure': SESSION_COOKIE_SECURE,
        'frontend_base_url': FRONTEND_BASE_URL,
        'sso_enabled': SSO_ENABLED,
        'sso_provider_name': SSO_PROVIDER_NAME,
        'sso_auto_create_users': SSO_AUTO_CREATE_USERS,
        'sso_redirect_uri': SSO_REDIRECT_URI,
        'public_api_endpoints': PUBLIC_API_ENDPOINTS,
    }
)

datapull.register_routes(app, token_required)

#VARIABLES
use_native_worker_scheduler = True




# Debug endpoint to inspect scheduler runtime state
@app.route('/api/debug/scheduler', methods=['GET'])
def debug_scheduler():
    global scheduler_initialized, scheduler_is_leader, scheduler_leader_identity

    jobs = []
    try:
        for job in scheduler.get_jobs():
            next_run = job.next_run_time.isoformat() if getattr(job, 'next_run_time', None) else None
            jobs.append({
                'id': str(job.id),
                'name': str(job.name),
                'next_run_time': next_run,
            })
    except Exception as e:
        jobs = [{'error': str(e)}]

    return jsonify({
        'scheduler_initialized': bool(scheduler_initialized),
        'scheduler_running': bool(getattr(scheduler, 'running', False)),
        'scheduler_is_leader': bool(scheduler_is_leader),
        'scheduler_leader_identity': scheduler_leader_identity,
        'job_count': len(jobs),
        'jobs': jobs,
    }), 200


@app.route('/api/datapull/queue-status', methods=['GET'])
@endpoint_docs.endpoint_doc(
    summary='Get datapull queue status',
    description='Returns queue depth, worker status, and scheduler leader state.',
    auth_types=['session', 'api_key'],
    tags=['Datapull'],
    responses={
        200: {'description': 'Queue status returned'},
        500: {'description': 'Server error'}
    }
)
@token_required
def get_datapull_queue_status():
    try:
        queue_depth = datapull.get_workflow_queue_depth()
        queue_available = datapull.is_workflow_queue_available()
        worker_enabled = _env_bool('DATAPULL_QUEUE_WORKER_ENABLED', True)
        worker_running = bool(queue_worker_thread and queue_worker_thread.is_alive())
        queue_key = str(os.getenv('DATAPULL_QUEUE_KEY') or 'datapull:execution:queue').strip()
        workers = datapull.list_worker_metrics()
        active_workers = [w for w in workers if not w.get('is_stale')]
        require_scheduler_leader = _env_bool('DATAPULL_SCHEDULER_REQUIRE_LEADER', True)

        return jsonify({
            'queue_key': queue_key,
            'queue_available': queue_available,
            'queue_depth': queue_depth,
            'worker_enabled': worker_enabled,
            'worker_running': worker_running,
            'worker_count_total': len(workers),
            'worker_count_active': len(active_workers),
            'workers': workers,
            'scheduler_require_leader': require_scheduler_leader,
            'scheduler_is_leader': scheduler_is_leader,
            'scheduler_leader_identity': scheduler_leader_identity if scheduler_is_leader else None,
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/datapull/metrics', methods=['GET'])
@token_required
def get_datapull_metrics():
    """Phase 6: Get metrics for job execution."""
    try:
        source_name = request.args.get('source_name')
        time_range_minutes = int(request.args.get('time_range_minutes', '1440'))
        metrics = datapull.get_job_metrics_summary(source_name=source_name, time_range_minutes=time_range_minutes)
        if not metrics:
            return jsonify({'metrics': None, 'message': 'No metrics available for time range'}), 200
        return jsonify({'metrics': metrics}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/datapull/metrics/by-source', methods=['GET'])
@token_required
def get_datapull_metrics_by_source():
    """Phase 6: Get per-source metrics."""
    try:
        time_range_minutes = int(request.args.get('time_range_minutes', '1440'))
        limit = int(request.args.get('limit', '50'))
        metrics = datapull.get_metrics_by_source(time_range_minutes=time_range_minutes, limit=limit)
        return jsonify({'metrics_by_source': metrics}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


scheduler_initialized = False  # Flag to prevent double initialization
queue_worker_thread = None
queue_worker_stop_event = threading.Event()
scheduler_leader_thread = None
scheduler_leader_stop_event = threading.Event()
scheduler_leader_identity = f"{os.getenv('HOSTNAME', 'api')}-{os.getpid()}"
scheduler_is_leader = False
runtime_bootstrapped = False

scheduler = BackgroundScheduler()


@app.before_request
def _ensure_runtime_bootstrap():
    """Ensure runtime bootstrap executes in the request-serving worker process."""
    global runtime_bootstrapped
    if runtime_bootstrapped:
        return None

    try:
        bootstrap_runtime()
    except Exception as e:
        app.logger.warning('Runtime bootstrap failed: %s', e)
    return None

'''with open('config.yaml') as f:
    config_dict = yaml.safe_load(f)
    collect_sys_path = config_dict['collect']['base_path']
if collect_sys_path:
    sys.path.append(collect_sys_path)
    import datapull
'''

def refresh_output_feed_cache_job():
    try:
        refreshed_count = data_output.refresh_output_feed_cache()
        print(f"Feed cache refresh job complete. Refreshed feeds: {refreshed_count}")
    except Exception as e:
        print(f"Feed cache refresh job error: {e}")


def enqueue_scheduled_workflow_job(source_name):
    source_name = str(source_name or '').strip()
    if not source_name:
        print("Skipping queue enqueue due to missing source_name")
        return

    # Phase 5: Pass trigger_source='scheduled' for audit trail
    enqueue_result = enqueue_workflow_execution(
        source_name=source_name,
        trigger='scheduler',
        trigger_source='scheduled'
    )
    if enqueue_result.get('status') == 'error':
        print(f"Scheduled enqueue failed for {source_name}: {enqueue_result.get('error')}")
    else:
        print(f"Scheduled job enqueued: {source_name} (job_id={enqueue_result.get('job_id')})")


def enqueue_workflow_execution(source_name, trigger='manual', requested_by=None, trigger_source=None, correlation_id=None):
    """Enqueue workflow using job envelope — Phase 5: QUEUE-ONLY mode (no direct fallback).
    
    All execution paths MUST go through the queue. If Redis is unavailable, request fails.
    This ensures consistent job tracking, retry logic, and distributed execution safety.
    
    Audit fields (Phase 5):
    - requested_by: user/client identifier
    - trigger_source: 'scheduled', 'manual', 'api', 'bulk', etc.
    - correlation_id: optional trace ID
    """
    source_name = str(source_name or '').strip()
    if not source_name:
        return {'status': 'error', 'error': 'Missing source_name', 'code': 'MISSING_SOURCE'}

    # Validate workflow exists
    workflow = datapull.load_workflow_by_source_name(source_name)
    if not workflow:
        return {'status': 'error', 'error': f"Workflow not found for source_name: {source_name}", 'code': 'WORKFLOW_NOT_FOUND'}

    # Phase 5: Use trigger_source if provided, otherwise derive from trigger
    _trigger_source = trigger_source or trigger or 'manual'
    
    # Create job envelope with audit fields
    envelope = datapull.create_job_envelope(
        source_name=source_name,
        trigger=trigger,
        requested_by=requested_by,
        trigger_source=_trigger_source,
        correlation_id=correlation_id,
        metadata=None
    )
    if not envelope:
        return {'status': 'error', 'error': 'Failed to create job envelope', 'code': 'ENVELOPE_CREATE_FAILED'}
    
    # Phase 5: NO FALLBACK — if queue fails, request fails
    queue_env, queue_err = datapull.enqueue_job_envelope(envelope)
    if queue_err:
        return {
            'status': 'error',
            'error': f'Queue unavailable (Redis required): {queue_err}',
            'code': 'QUEUE_UNAVAILABLE'
        }

    # Standardized successful response
    return {
        'status': 'queued',
        'code': 'SUCCESS',
        'job_id': envelope.get('job_id'),
        'source_name': source_name,
        'trigger': trigger,
        'trigger_source': _trigger_source,
        'requested_by': requested_by,
        'correlation_id': correlation_id
    }


def _queue_worker_loop():
    """Worker loop that dequeues job envelopes with Phase 3 retry and locking support."""
    worker_id = datapull.get_worker_identity()
    print("Datapull queue worker loop started.")
    datapull.record_worker_heartbeat(worker_id=worker_id, state='running', extra={'event': 'worker_started'})

    while not queue_worker_stop_event.is_set():
        datapull.record_worker_heartbeat(worker_id=worker_id, state='running')
        envelope, queue_err = datapull.dequeue_job_envelope(block_seconds=5)
        if queue_err:
            datapull.record_worker_job_result(worker_id=worker_id, status='error', error=f"dequeue error: {queue_err}")
            print(f"Datapull queue worker dequeue error: {queue_err}")
            continue
        if not envelope:
            continue

        started_at = datetime.utcnow()
        try:
            queue_result = datapull.execute_queued_workflow_message(
                message=envelope,
                default_dp_module=default_dp_fname,
                custom_template_executor=execute_custom_template_snippet,
                cache_invalidator=data_output.invalidate_all_output_feed_caches
            )
            status = queue_result.get('status')
            source_name = queue_result.get('source_name') or envelope.get('source_name')
            duration_ms = int((datetime.utcnow() - started_at).total_seconds() * 1000)
            datapull.record_worker_job_result(
                worker_id=worker_id,
                source_name=source_name,
                status='success' if status in ('success', 'completed') else 'error',
                error=queue_result.get('error') if status not in ('success', 'completed') else None,
                duration_ms=duration_ms,
                message_id=queue_result.get('job_id') or envelope.get('job_id')
            )
            print(f"Datapull queue worker processed '{source_name}' (job {envelope.get('job_id')}) with status: {status}")
        except Exception as e:
            duration_ms = int((datetime.utcnow() - started_at).total_seconds() * 1000)
            datapull.record_worker_job_result(
                worker_id=worker_id,
                source_name=envelope.get('source_name'),
                status='error',
                error=str(e),
                duration_ms=duration_ms,
                message_id=envelope.get('job_id')
            )
            print(f"Datapull queue worker execution error: {e}")

    datapull.record_worker_heartbeat(worker_id=worker_id, state='stopped', extra={'event': 'worker_stopped'})
    print("Datapull queue worker loop stopped.")


def start_queue_worker_if_enabled():
    global queue_worker_thread

    if not _env_bool('DATAPULL_QUEUE_WORKER_ENABLED', True):
        print("DATAPULL_QUEUE_WORKER_ENABLED is false; queue worker will not start.")
        return

    if queue_worker_thread and queue_worker_thread.is_alive():
        print("Datapull queue worker already running.")
        return

    queue_worker_stop_event.clear()
    queue_worker_thread = threading.Thread(target=_queue_worker_loop, name='datapull-queue-worker', daemon=True)
    queue_worker_thread.start()
    print("Datapull queue worker started.")


def run_queue_worker_forever():
    start_queue_worker_if_enabled()
    if not (queue_worker_thread and queue_worker_thread.is_alive()):
        return

    try:
        while True:
            queue_worker_stop_event.wait(60)
            if queue_worker_stop_event.is_set():
                break
    except KeyboardInterrupt:
        print("Queue worker shutdown requested.")
    finally:
        queue_worker_stop_event.set()


def _scheduler_leader_renew_loop():
    renewal_seconds = max(5, int(os.getenv('DATAPULL_SCHEDULER_LEADER_RENEW_SECONDS', '30')))
    while not scheduler_leader_stop_event.wait(renewal_seconds):
        ok = datapull.renew_scheduler_leader(scheduler_leader_identity)
        if not ok:
            print("Scheduler leader lock renewal failed; current instance should no longer schedule new jobs.")
            break


def _start_scheduler_leader_renewal():
    global scheduler_leader_thread
    if scheduler_leader_thread and scheduler_leader_thread.is_alive():
        return
    scheduler_leader_stop_event.clear()
    scheduler_leader_thread = threading.Thread(
        target=_scheduler_leader_renew_loop,
        name='scheduler-leader-renew',
        daemon=True
    )
    scheduler_leader_thread.start()


def _stop_scheduler_leader_renewal():
    scheduler_leader_stop_event.set()


def _shutdown_runtime():
    global scheduler_is_leader
    _stop_scheduler_leader_renewal()
    if scheduler_is_leader:
        datapull.release_scheduler_leader(scheduler_leader_identity)
        scheduler_is_leader = False


def bootstrap_runtime():
    global runtime_bootstrapped
    if runtime_bootstrapped:
        return

    try:
        workflow_result = bootstrap.apply_env_mongo_init_workflow()
        status_text = str((workflow_result or {}).get('status') or '').strip().lower()
        if status_text and status_text != 'skipped':
            print(f"Mongo init workflow completed: {workflow_result}")
    except Exception as e:
        print(f"Mongo init workflow failed: {e}")
        raise

    print("Initializing scheduled datapull workflows...")
    initialize_scheduled_workflows()

    require_scheduler_leader = _env_bool('DATAPULL_SCHEDULER_REQUIRE_LEADER', True)
    if require_scheduler_leader and not scheduler_is_leader and not scheduler_initialized:
        # Do not mark runtime as bootstrapped yet; retry on the next request.
        return

    start_queue_worker_if_enabled()
    atexit.register(_shutdown_runtime)
    runtime_bootstrapped = True

def initialize_scheduled_workflows():
    """Initialize all scheduled datapull workflows on app startup."""
    global scheduler_initialized, scheduler, scheduler_is_leader
    
    # Prevent double initialization
    if scheduler_initialized:
        print("Scheduler already initialized, skipping...")
        return

    require_scheduler_leader = _env_bool('DATAPULL_SCHEDULER_REQUIRE_LEADER', True)
    if require_scheduler_leader:
        scheduler_is_leader = datapull.try_acquire_scheduler_leader(scheduler_leader_identity)
        if not scheduler_is_leader:
            print("Scheduler leader lock not acquired; skipping scheduler initialization on this instance.")
            return

        print(f"Scheduler leader lock acquired by {scheduler_leader_identity}")
        _start_scheduler_leader_renewal()
    
    try:
        mongo_client, mongo_connect_string = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_data"]
        workflows = db["datapull_workflows"]
        
        # Find all scheduled and enabled workflows
        scheduled_workflows = list(workflows.find({
            'scheduled': True,
            'schedule_enabled': True
        }))
        
        if not scheduled_workflows:
            print("No scheduled workflows found.")
        
        print(f"Initializing {len(scheduled_workflows)} scheduled workflows...")
        
        for workflow in scheduled_workflows:
            source_name = workflow.get('source_name')
            interval_min = workflow.get('schedule_interval_min', 60)
            
            # Validate required fields
            if not source_name or not interval_min:
                print(f"Skipping workflow with missing fields: {source_name}")
                continue
            
            try:
                # Create a job ID based on source name (avoid duplicates)
                job_id = f"workflow_{source_name}"
                
                # Remove existing job if it exists
                if scheduler.get_job(job_id):
                    scheduler.remove_job(job_id)
                
                # Add the scheduled job
                scheduler.add_job(
                    func=enqueue_scheduled_workflow_job,
                    args=[source_name],
                    trigger='interval',
                    minutes=interval_min,
                    id=job_id,
                    name=f"Datapull: {source_name}",
                    misfire_grace_time=300  # 5 minute grace period
                )
                
                print(f"Scheduled workflow: {source_name} (every {interval_min} minutes)")
            except Exception as e:
                print(f"Error scheduling workflow {source_name}: {e}")

        try:
            refresh_interval_min = int(os.getenv('FEED_CACHE_REFRESH_MINUTES', '5'))
        except Exception:
            refresh_interval_min = 5
        refresh_interval_min = max(1, refresh_interval_min)

        try:
            if scheduler.get_job('feed_cache_refresh'):
                scheduler.remove_job('feed_cache_refresh')
            scheduler.add_job(
                func=refresh_output_feed_cache_job,
                trigger='interval',
                minutes=refresh_interval_min,
                id='feed_cache_refresh',
                name='Feed Cache Refresh',
                misfire_grace_time=120
            )
            print(f"Scheduled feed cache refresh (every {refresh_interval_min} minutes)")
        except Exception as e:
            print(f"Error scheduling feed cache refresh job: {e}")
        
        # Start the scheduler if not already running
        if not scheduler.running:
            scheduler.start()
            print("APScheduler started successfully.")

        _ensure_custom_snippet_imports_config()
        _ensure_custom_snippet_builtins_config()
        _ensure_allow_custom_snippet_config()
        _ensure_max_response_bytes_config()
        _ensure_max_query_rows_config()
        
        scheduler_initialized = True
        mongo_client.close()
    except Exception as e:
        print(f"Error initializing scheduled workflows: {e}")

def _persist_custom_result_list(result_list, source_name):
    """Persist custom snippet result_list items to indicators using standard datapull logic."""
    if not isinstance(result_list, list):
        raise ValueError("Custom snippet 'result_list' must be a list")

    cur_dtime = datetime.utcnow()
    extracted_list = []

    for item in result_list:
        candidate_value = None
        candidate_dtype = None

        if isinstance(item, dict):
            candidate_value = item.get('value')
            candidate_dtype = item.get('dtype')
        else:
            candidate_value = item

        if candidate_value is None:
            continue

        candidate_value = str(candidate_value)
        if candidate_dtype is None:
            candidate_dtype = datapull.dtype_extractor(candidate_value, source_name)

        datapull.update_indicators(candidate_value, candidate_dtype, cur_dtime, source_name)
        extracted_list.append({
            'value': candidate_value,
            'dtype': candidate_dtype,
            'e_time': cur_dtime
        })

    return extracted_list


DEFAULT_CUSTOM_SNIPPET_ALLOWED_IMPORTS = ["requests", "datetime", "json", "re"]

SAFE_CUSTOM_SNIPPET_BUILTINS_CATALOG = {
    "str": str,
    "len": len,
    "print": print,
    "repr": repr,
    "format": format,
    "ord": ord,
    "chr": chr,
    "enumerate": enumerate,
    "range": range,
    "int": int,
    "float": float,
    "bool": bool,
    "list": list,
    "dict": dict,
    "set": set,
    "tuple": tuple,
    "min": min,
    "max": max,
    "sum": sum,
    "sorted": sorted,
    "all": all,
    "any": any,
    "isinstance": isinstance,
    "type": type,
    "Exception": Exception,
    "ValueError": ValueError,
    "TypeError": TypeError,
}

DEFAULT_CUSTOM_SNIPPET_ALLOWED_BUILTINS = [
    "str", "len", "print", "repr", "format", "ord", "chr", "enumerate", "range",
    "int", "float", "bool", "list", "dict", "set", "tuple",
    "min", "max", "sum", "sorted", "all", "any", "isinstance", "type",
    "Exception", "ValueError", "TypeError"
]


def _load_custom_snippet_allowed_imports():
    """Load allowed import module names for custom snippets from basicconfigs."""
    try:
        config_doc = datapull.get_datapull_core_config() or {}
        raw_allowed = config_doc.get("custom_snippets_allowed_imports")
        if isinstance(raw_allowed, list):
            normalized = []
            for item in raw_allowed:
                module_name = str(item or "").strip()
                if module_name:
                    normalized.append(module_name)
            if normalized:
                return set(normalized)
    except Exception as e:
        print(f"Warning: failed to load custom_snippets_allowed_imports, using defaults: {e}")

    return set(DEFAULT_CUSTOM_SNIPPET_ALLOWED_IMPORTS)


def _load_custom_snippet_allowed_builtins():
    """Load allowed builtin names for custom snippets from basicconfigs."""
    try:
        config_doc = datapull.get_datapull_core_config() or {}
        raw_allowed = config_doc.get("custom_snippets_allowed_builtins")
        if isinstance(raw_allowed, list):
            names = []
            for item in raw_allowed:
                builtin_name = str(item or "").strip()
                if builtin_name:
                    names.append(builtin_name)
            if names:
                return {
                    name: SAFE_CUSTOM_SNIPPET_BUILTINS_CATALOG[name]
                    for name in names
                    if name in SAFE_CUSTOM_SNIPPET_BUILTINS_CATALOG
                }
    except Exception as e:
        print(f"Warning: failed to load custom_snippets_allowed_builtins, using defaults: {e}")

    return {
        name: SAFE_CUSTOM_SNIPPET_BUILTINS_CATALOG[name]
        for name in DEFAULT_CUSTOM_SNIPPET_ALLOWED_BUILTINS
        if name in SAFE_CUSTOM_SNIPPET_BUILTINS_CATALOG
    }


def _ensure_custom_snippet_imports_config():
    """Seed custom_snippets_allowed_imports in basicconfigs if missing."""
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_config"]
        basicconfigs_col = db["basicconfigs"]
        existing_core = basicconfigs_col.find_one({"module": "core"}, {"_id": 1, "custom_snippets_allowed_imports": 1})
        if existing_core:
            if "custom_snippets_allowed_imports" not in existing_core:
                basicconfigs_col.update_one(
                    {"_id": existing_core["_id"]},
                    {"$set": {"custom_snippets_allowed_imports": DEFAULT_CUSTOM_SNIPPET_ALLOWED_IMPORTS}}
                )
        else:
            print("Warning: module 'core' not found in basicconfigs; skipping custom_snippets_allowed_imports seed")
        mongo_client.close()
    except Exception as e:
        print(f"Warning: failed to seed custom_snippets_allowed_imports: {e}")


def _ensure_custom_snippet_builtins_config():
    """Seed custom_snippets_allowed_builtins in basicconfigs if missing."""
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_config"]
        basicconfigs_col = db["basicconfigs"]
        existing_core = basicconfigs_col.find_one({"module": "core"}, {"_id": 1, "custom_snippets_allowed_builtins": 1})
        if existing_core:
            if "custom_snippets_allowed_builtins" not in existing_core:
                basicconfigs_col.update_one(
                    {"_id": existing_core["_id"]},
                    {"$set": {"custom_snippets_allowed_builtins": DEFAULT_CUSTOM_SNIPPET_ALLOWED_BUILTINS}}
                )
        else:
            print("Warning: module 'core' not found in basicconfigs; skipping custom_snippets_allowed_builtins seed")
        mongo_client.close()
    except Exception as e:
        print(f"Warning: failed to seed custom_snippets_allowed_builtins: {e}")


def _ensure_allow_custom_snippet_config():
    """Seed allow_custom_snippet=false in the core config if missing (custom snippets are off by default)."""
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        basicconfigs_col = mongo_client["byoint_core_config"]["basicconfigs"]
        basicconfigs_col.update_one(
            {"module": "core", all_connects.ALLOW_CUSTOM_SNIPPET_KEY: {"$exists": False}},
            {"$set": {all_connects.ALLOW_CUSTOM_SNIPPET_KEY: False}}
        )
        mongo_client.close()
    except Exception as e:
        print(f"Warning: failed to seed {all_connects.ALLOW_CUSTOM_SNIPPET_KEY}: {e}")


def _ensure_max_response_bytes_config():
    """Seed max_response_bytes (datapull response-size cap) in basicconfigs if missing."""
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_config"]
        basicconfigs_col = db["basicconfigs"]
        existing_core = basicconfigs_col.find_one({"module": "core"}, {"_id": 1, "max_response_bytes": 1})
        if existing_core:
            if "max_response_bytes" not in existing_core:
                basicconfigs_col.update_one(
                    {"_id": existing_core["_id"]},
                    {"$set": {"max_response_bytes": 50 * 1024 * 1024}}
                )
        else:
            print("Warning: module 'core' not found in basicconfigs; skipping max_response_bytes seed")
        mongo_client.close()
    except Exception as e:
        print(f"Warning: failed to seed max_response_bytes: {e}")


def _ensure_max_query_rows_config():
    """Seed max_query_rows (DB/Mongo query template row cap) in basicconfigs if missing."""
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_config"]
        basicconfigs_col = db["basicconfigs"]
        existing_core = basicconfigs_col.find_one({"module": "core"}, {"_id": 1, "max_query_rows": 1})
        if existing_core:
            if "max_query_rows" not in existing_core:
                basicconfigs_col.update_one(
                    {"_id": existing_core["_id"]},
                    {"$set": {"max_query_rows": 200000}}
                )
        else:
            print("Warning: module 'core' not found in basicconfigs; skipping max_query_rows seed")
        mongo_client.close()
    except Exception as e:
        print(f"Warning: failed to seed max_query_rows: {e}")


def _run_template_snippet(snippet_code, kwargs, source_name):
    """Run a template snippet in an isolated child process and return its response.

    Anything the snippet printed is forwarded to the app log, as before.
    """
    try:
        response = snippet_sandbox.run_snippet(
            "template",
            snippet_code,
            dict(kwargs or {}),
            _load_custom_snippet_allowed_imports(),
            _load_custom_snippet_allowed_builtins().keys(),
            snippet_sandbox.TEMPLATE_TIMEOUT_SECONDS,
        )
    except snippet_sandbox.SnippetError as e:
        if e.output:
            print(f"[snippet:{source_name}] {e.output}")
        raise
    if response.get("output"):
        print(f"[snippet:{source_name}] {response['output']}")
    return response


def execute_custom_template_snippet(snippet_code, kwargs, source_name):
    """Execute a custom template snippet and return (result, dp_log)."""
    if not snippet_code or not str(snippet_code).strip():
        raise ValueError("Custom template is missing snippet_code")
    if not all_connects.is_custom_snippet_allowed():
        raise PermissionError(all_connects.CUSTOM_SNIPPET_DISABLED_MESSAGE)

    try:
        response = _run_template_snippet(snippet_code, kwargs, source_name)
    except snippet_sandbox.SnippetError as e:
        raise RuntimeError(str(e)) from None

    result_list = response.get("result_list")
    dp_log = response.get("dp_log") or ''

    extracted_list = _persist_custom_result_list(result_list, source_name)
    if not dp_log:
        dp_log = f"Custom snippet processed {len(extracted_list)} indicators"
    else:
        dp_log = f"{dp_log}\nCustom snippet processed {len(extracted_list)} indicators"

    return extracted_list, dp_log


def _test_custom_template_snippet_dry_run(snippet_code, kwargs, preview_limit=20):
    """Execute a custom template snippet in dry-run mode (no persistence). Returns (result_list_preview, log, error)."""
    if not snippet_code or not str(snippet_code).strip():
        return None, None, "snippet_code is required"
    if not all_connects.is_custom_snippet_allowed():
        return None, None, all_connects.CUSTOM_SNIPPET_DISABLED_MESSAGE

    try:
        response = _run_template_snippet(snippet_code, kwargs, "dry-run")
    except snippet_sandbox.SnippetError as e:
        return None, None, str(e)

    result_list = response.get("result_list") or []
    dp_log = response.get("dp_log") or ''

    preview = result_list[:preview_limit]
    total = len(result_list)
    log_msg = dp_log or f"Dry-run: {total} item(s) returned"
    return preview, total, log_msg


def _resolve_indicator_type_regex(selected_type):
    selected_type_text = str(selected_type or '').strip()
    if not selected_type_text:
        return None

    mongo_client = None
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        config_db = mongo_client['byoint_core_config']
        data_types = config_db['data_types']
        type_doc = data_types.find_one(
            {'name': selected_type_text},
            {'_id': 0, 'regex_extract_pattern': 1}
        )
        regex_pattern = str((type_doc or {}).get('regex_extract_pattern') or '').strip()
        if regex_pattern:
            return regex_pattern
    except Exception:
        return None
    finally:
        if mongo_client:
            mongo_client.close()

    fallback_pattern = datapull.dtype_regex_patterns.get(selected_type_text)
    if fallback_pattern:
        return str(fallback_pattern)

    return None


def _refang_text_for_detection(raw_text):
    text = str(raw_text or '')
    if not text:
        return ''

    # Normalize common defanged protocol forms.
    text = re.sub(r'\bhxxps\b', 'https', text, flags=re.IGNORECASE)
    text = re.sub(r'\bhxxp\b', 'http', text, flags=re.IGNORECASE)

    # Normalize common defanged dot forms.
    text = re.sub(r'\[\s*\.\s*\]', '.', text)
    text = re.sub(r'\(\s*\.\s*\)', '.', text)
    text = re.sub(r'\{\s*\.\s*\}', '.', text)

    # Normalize common defanged colon/slash forms used in URLs.
    text = re.sub(r'\[\s*:\s*\]', ':', text)
    text = re.sub(r'\(\s*:\s*\)', ':', text)
    text = re.sub(r'\{\s*:\s*\}', ':', text)
    text = re.sub(r'\[\s*/\s*\]', '/', text)
    text = re.sub(r'\(\s*/\s*\)', '/', text)
    text = re.sub(r'\{\s*/\s*\}', '/', text)

    return text


def _extract_type_matches_from_text(raw_text, regex_pattern, max_results=2000):
    max_results = max(1, min(int(max_results or 2000), 10000))
    if not regex_pattern:
        return []

    try:
        compiled = re.compile(regex_pattern, re.IGNORECASE | re.MULTILINE)
    except re.error:
        return []

    raw_text = str(raw_text or '')
    if not raw_text:
        return []

    stripped_html = re.sub(r'(?is)<(script|style).*?>.*?</\1>', ' ', raw_text)
    plain_text = html.unescape(re.sub(r'(?s)<[^>]+>', '\n', stripped_html))

    candidates = []
    seen = set()

    def _add_candidate(candidate_value):
        value_text = str(candidate_value or '').strip().strip('"\'`[](){}<>,;')
        if not value_text:
            return
        dedupe_key = value_text.lower()
        if dedupe_key in seen:
            return
        seen.add(dedupe_key)
        candidates.append(value_text)

    refanged_text = _refang_text_for_detection(plain_text)

    for searchable_text in [plain_text, refanged_text]:
        if not searchable_text:
            continue

        for line in searchable_text.splitlines():
            line_text = str(line or '').strip()
            if not line_text:
                continue
            for match in compiled.finditer(line_text):
                _add_candidate(match.group(0))
                if len(candidates) >= max_results:
                    return candidates

        for match in compiled.finditer(searchable_text):
            _add_candidate(match.group(0))
            if len(candidates) >= max_results:
                return candidates

    return candidates


@app.route('/api/indicators/import-url/preview', methods=['POST'])
@token_required
def preview_indicators_from_url():
    if not request.is_json:
        return jsonify({'message': 'Request must be JSON.'}), 400

    data = request.json or {}
    url = str(data.get('url') or '').strip()
    selected_type = str(data.get('type') or data.get('dtype') or '').strip()
    max_results = data.get('max_results', 2000)

    if not url or not selected_type:
        return jsonify({'message': 'Missing required fields: url and type.'}), 400

    try:
        max_results = int(max_results)
    except Exception:
        max_results = 2000

    max_results = max(1, min(max_results, 10000))

    parsed_url = urlparse(url)
    if parsed_url.scheme not in ('http', 'https'):
        return jsonify({'message': 'Only http(s) URLs are supported.'}), 400
    if not str(parsed_url.netloc or '').strip():
        return jsonify({'message': 'Invalid URL.'}), 400

    blocked_hosts = {'localhost', '127.0.0.1', '::1'}
    host_name = str(parsed_url.hostname or '').strip().lower()
    if host_name in blocked_hosts:
        return jsonify({'message': 'Localhost URLs are not allowed for URL import.'}), 400

    regex_pattern = _resolve_indicator_type_regex(selected_type)
    if not regex_pattern:
        return jsonify({'message': f'No regex pattern configured for type: {selected_type}'}), 400

    try:
        response = requests.get(
            url,
            timeout=20,
            headers={'User-Agent': 'ByoInt-IndicatorImporter/1.0'}
        )
        response.raise_for_status()
    except Exception as e:
        return jsonify({'message': f'Failed to fetch URL: {e}'}), 400

    page_text = response.text or ''
    detected_indicators = _extract_type_matches_from_text(
        page_text,
        regex_pattern,
        max_results=max_results
    )

    return jsonify({
        'url': url,
        'type': selected_type,
        'regex_extract_pattern': regex_pattern,
        'detected_count': len(detected_indicators),
        'detected_indicators': detected_indicators
    }), 200

@app.route('/api/indicators', methods=['GET'])
@endpoint_docs.endpoint_doc(
    summary='List indicators',
    description='Returns a paginated list of indicators with optional search and filter.',
    auth_types=['session', 'api_key'],
    tags=['Indicators'],
    query_params={
        'page': {'type': 'integer', 'default': 1, 'description': 'Page number'},
        'limit': {'type': 'integer', 'default': 50, 'description': 'Results per page'},
        'search': {'type': 'string', 'description': 'Search by value, type, or source'},
        'active': {'type': 'string', 'description': 'Filter by active status (true/false)'},
        'source': {'type': 'string', 'description': 'Filter by source name'},
    },
    responses={
        200: {'description': 'Paginated indicators list'},
        400: {'description': 'Invalid parameters'},
        500: {'description': 'Server error'}
    }
)
@token_required
def get_indicators():
    try:
        # pagination params
        try:
            page = int(request.args.get('page', 1))
            limit = int(request.args.get('limit', 50))
        except ValueError:
            return jsonify({'message': 'Invalid pagination parameters.'}), 400

        if page < 1 or limit < 1:
            return jsonify({'message': 'page and limit must be >= 1'}), 400

        search = request.args.get('search', '').strip()
        active_filter = request.args.get('active', '').strip()
        source_filter = request.args.get('source', '').strip()
        mongo_client, mongo_connect_string = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_data"]
        indicators = db["indicators"]

        query = {}
        if search:
            regex = {"$regex": search, "$options": "i"}
            query = {
                "$or": [
                    {"value": regex},
                    {"dtype": regex},
                    {"type": regex},
                    {"sources.source_name": regex}
                ]
            }

        # Add active filter if specified
        if active_filter.lower() == 'true':
            query['active'] = True
        elif active_filter.lower() == 'false':
            query['active'] = False

        # Add source filter if specified
        if source_filter:
            query['sources.source_name'] = source_filter

        total = indicators.count_documents(query)
        skip = (page - 1) * limit
        cursor = indicators.find(query).skip(skip).limit(limit)
        out = []
        for d in cursor:
            sources = d.get('sources', [])
            firstupdate_time = d.get('firstupdate_time') or d.get('e_time')
            br_scores = []
            for src in sources:
                score = src.get('br_score') if isinstance(src, dict) else None
                if score is None:
                    continue
                try:
                    br_scores.append(float(score))
                except (ValueError, TypeError):
                    continue

            max_br_score = max(br_scores) if br_scores else None

            out.append({
                'value': d.get('value'),
                'type': d.get('dtype') or d.get('type'),
                'sources': sources,
                'active': d.get('active', False),
                'max_br_score': max_br_score,
                'firstupdate_time': firstupdate_time.isoformat() if hasattr(firstupdate_time, 'isoformat') else firstupdate_time
            })

        pages = (total + limit - 1) // limit
        return jsonify({'indicators': out, 'total': total, 'page': page, 'pages': pages}), 200
    except Exception as e:
        return jsonify({'message': str(e)}), 500

@app.route('/api/indicators/new', methods=['POST'])
@endpoint_docs.endpoint_doc(
    summary='Add or update an indicator',
    description='Upserts an indicator by value and type. Applies enrichments if enabled.',
    auth_types=['session', 'api_key'],
    tags=['Indicators'],
    request_body={
        'required': ['value', 'type', 'sources'],
        'properties': {
            'value': {'type': 'string'},
            'type': {'type': 'string'},
            'sources': {'type': 'array'},
        }
    },
    responses={
        201: {'description': 'Indicator added/updated'},
        400: {'description': 'Missing required fields'},
        500: {'description': 'Server error'}
    }
)
@token_required
def add_indicator():
    if not request.is_json:
        return jsonify({'message': 'Request must be JSON.'}), 400
    data = request.json
    value = data.get('value')
    dtype = data.get('type') or data.get('dtype')
    sources = data.get('sources')
    comment_text = str(data.get('comment') or '').strip()
    if not value or not dtype or not sources:
        return jsonify({'message': 'Missing required fields.'}), 400
    if len(comment_text) > 2000:
        return jsonify({'message': 'Comment is too long (max 2000 characters).'}), 400
    try:
        mongo_client, mongo_connect_string = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_data"]
        indicators = db["indicators"]
        cur_dtime = datetime.utcnow()
        actor = str(getattr(g, 'current_user', '') or '').strip() or None
        normalized_sources = []
        source_tag_cache = {}
        def _normalize_tags(raw_tags):
            if isinstance(raw_tags, list):
                return [str(tag).strip() for tag in raw_tags if str(tag).strip()]
            if raw_tags is None:
                return []
            return [tag.strip() for tag in str(raw_tags).split(',') if tag.strip()]
        if isinstance(sources, list):
            for source_entry in sources:
                if not isinstance(source_entry, dict):
                    continue
                normalized_entry = dict(source_entry)
                source_name = str(normalized_entry.get('source_name') or '').strip()
                normalized_tags = _normalize_tags(normalized_entry.get('tag'))
                if not normalized_tags and source_name:
                    if source_name not in source_tag_cache:
                        workflow = datapull.load_workflow_by_source_name(source_name)
                        source_tag_cache[source_name] = str((workflow or {}).get('tag') or '').strip()
                    normalized_tags = _normalize_tags(source_tag_cache.get(source_name, ''))
                normalized_entry['tag'] = normalized_tags
                normalized_entry['last_update_status'] = True
                normalized_entry['lastupdate_time'] = normalized_entry.get('lastupdate_time') or cur_dtime
                normalized_entry['firstupdate_time'] = normalized_entry.get('firstupdate_time') or normalized_entry.get('lastupdate_time') or cur_dtime

                source_comment_text = str(normalized_entry.get('comment') or '').strip()
                if not source_comment_text and comment_text:
                    source_comment_text = comment_text
                if source_comment_text:
                    normalized_entry['comment'] = source_comment_text
                    normalized_entry['comments'] = [{
                        'comment': source_comment_text,
                        'created_at': cur_dtime,
                        'created_by': actor,
                        'source_name': source_name or None,
                    }]

                normalized_sources.append(normalized_entry)
        else:
            normalized_sources = sources
        # Upsert by value/type with proper source merging
        
        # CRITICAL FIX: Fetch existing sources and merge instead of replacing
        existing_doc = indicators.find_one(
            {"value": value, "type": dtype},
            {"sources": 1}
        )
        existing_sources = existing_doc.get("sources", []) if isinstance(existing_doc, dict) else []
        
        # Merge: preserve existing sources that aren't being updated
        # and add/update sources from normalized_sources
        merged_sources = list(existing_sources) if isinstance(existing_sources, list) else []
        
        # Track which source names are being updated
        updated_source_names = set()
        if isinstance(normalized_sources, list):
            for new_entry in normalized_sources:
                source_name = str(new_entry.get('source_name') or '').strip()
                if not source_name:
                    merged_sources.append(new_entry)
                    continue
                
                updated_source_names.add(source_name)
                # Find and update existing source or append new one
                found = False
                for i, existing_entry in enumerate(merged_sources):
                    if isinstance(existing_entry, dict) and str(existing_entry.get('source_name') or '').strip() == source_name:
                        # Update existing source entry
                        merged_sources[i] = dict(existing_entry)
                        merged_sources[i].update(new_entry)
                        existing_comments = existing_entry.get('comments') if isinstance(existing_entry.get('comments'), list) else []
                        new_comments = new_entry.get('comments') if isinstance(new_entry.get('comments'), list) else []
                        if existing_comments or new_comments:
                            merged_sources[i]['comments'] = [*existing_comments, *new_comments]
                        found = True
                        break
                
                if not found:
                    # Add new source
                    merged_sources.append(new_entry)
        
        update_doc = {
            "$set": {"type": dtype, "sources": merged_sources, "lastupdate": "Y", "e_time": cur_dtime},
            "$setOnInsert": {"active": True, "firstupdate_time": cur_dtime}
        }

        result = indicators.update_one(
            {"value": value, "type": dtype},
            update_doc,
            upsert=True
        )

        datapull_source = 'static'
        if isinstance(normalized_sources, list):
            for source_entry in normalized_sources:
                if isinstance(source_entry, dict):
                    source_name = str(source_entry.get('source_name') or '').strip()
                    if source_name:
                        datapull_source = source_name
                        break

        action = 'created' if result.upserted_id else 'updated'
        datapull.log_indicator_activity(
            action=action,
            datapull_source=datapull_source,
            indicator_value=value,
            indicator_type=dtype,
            event_time=datetime.utcnow(),
            details={
                'entrypoint': '/api/indicators/new',
                'actor': actor,
                'static_added_by': actor,
                'has_comment': bool(comment_text)
            },
            mongo_client=mongo_client
        )
        
        # Apply enrichments if enabled
        enriched_doc, enrich_error = data_enrichments.enrich_and_update_indicator(value, dtype, mongo_client)
        
        mongo_client.close()
        
        message = 'Indicator added/updated successfully!'
        if enrich_error:
            message += f' (Enrichment note: {enrich_error})'
        
        return jsonify({'message': message, 'indicator': enriched_doc or {}}), 201
    except Exception as e:
        return jsonify({'message': str(e)}), 500


@app.route('/api/indicators/bulk-add', methods=['POST'])
@token_required
def bulk_add_indicators():
    if not request.is_json:
        return jsonify({'message': 'Request must be JSON.'}), 400
    
    data = request.json
    indicators = data.get('indicators') or []
    
    if not isinstance(indicators, list) or len(indicators) == 0:
        return jsonify({'message': 'indicators must be a non-empty array.'}), 400
    
    try:
        mongo_client, mongo_connect_string = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_data"]
        indicators_col = db["indicators"]
        actor = str(getattr(g, 'current_user', '') or '').strip() or None
        
        results = []
        source_tag_cache = {}
        def _normalize_tags(raw_tags):
            if isinstance(raw_tags, list):
                return [str(tag).strip() for tag in raw_tags if str(tag).strip()]
            if raw_tags is None:
                return []
            return [tag.strip() for tag in str(raw_tags).split(',') if tag.strip()]
        
        for item in indicators:
            value = item.get('value')
            dtype = item.get('type') or item.get('dtype')
            sources = item.get('sources')
            
            if not value or not dtype or not sources:
                results.append({'value': value, 'type': dtype, 'status': 'skipped', 'error': 'Missing required fields.'})
                continue
            
            try:
                cur_dtime = datetime.utcnow()
                normalized_sources = []
                if isinstance(sources, list):
                    for source_entry in sources:
                        if not isinstance(source_entry, dict):
                            continue
                        normalized_entry = dict(source_entry)
                        source_name = str(normalized_entry.get('source_name') or '').strip()
                        normalized_tags = _normalize_tags(normalized_entry.get('tag'))
                        if not normalized_tags and source_name:
                            if source_name not in source_tag_cache:
                                workflow = datapull.load_workflow_by_source_name(source_name)
                                source_tag_cache[source_name] = str((workflow or {}).get('tag') or '').strip()
                            normalized_tags = _normalize_tags(source_tag_cache.get(source_name, ''))
                        normalized_entry['tag'] = normalized_tags
                        normalized_entry['last_update_status'] = True
                        normalized_entry['lastupdate_time'] = normalized_entry.get('lastupdate_time') or cur_dtime
                        normalized_entry['firstupdate_time'] = normalized_entry.get('firstupdate_time') or normalized_entry.get('lastupdate_time') or cur_dtime

                        source_comment_text = str(normalized_entry.get('comment') or '').strip()
                        if source_comment_text:
                            normalized_entry['comment'] = source_comment_text
                            normalized_entry['comments'] = [{
                                'comment': source_comment_text,
                                'created_at': cur_dtime,
                                'created_by': actor,
                                'source_name': source_name or None,
                            }]

                        normalized_sources.append(normalized_entry)
                else:
                    normalized_sources = sources

                # CRITICAL FIX: Fetch existing sources and merge instead of replacing
                existing_doc = indicators_col.find_one(
                    {"value": value, "type": dtype},
                    {"sources": 1}
                )
                existing_sources = existing_doc.get("sources", []) if isinstance(existing_doc, dict) else []
                
                # Merge: preserve existing sources that aren't being updated
                merged_sources = list(existing_sources) if isinstance(existing_sources, list) else []
                
                if isinstance(normalized_sources, list):
                    for new_entry in normalized_sources:
                        source_name = str(new_entry.get('source_name') or '').strip()
                        if not source_name:
                            merged_sources.append(new_entry)
                            continue
                        
                        # Find and update existing source or append new one
                        found = False
                        for i, existing_entry in enumerate(merged_sources):
                            if isinstance(existing_entry, dict) and str(existing_entry.get('source_name') or '').strip() == source_name:
                                # Update existing source entry
                                merged_sources[i] = dict(existing_entry)
                                merged_sources[i].update(new_entry)
                                existing_comments = existing_entry.get('comments') if isinstance(existing_entry.get('comments'), list) else []
                                new_comments = new_entry.get('comments') if isinstance(new_entry.get('comments'), list) else []
                                if existing_comments or new_comments:
                                    merged_sources[i]['comments'] = [*existing_comments, *new_comments]
                                found = True
                                break
                        
                        if not found:
                            # Add new source
                            merged_sources.append(new_entry)

                result = indicators_col.update_one(
                    {"value": value, "type": dtype},
                    {
                        "$set": {"type": dtype, "sources": merged_sources, "lastupdate": "Y", "e_time": cur_dtime},
                        "$setOnInsert": {"active": True, "firstupdate_time": cur_dtime}
                    },
                    upsert=True
                )
                
                datapull_source = 'static'
                if isinstance(sources, list):
                    for source_entry in sources:
                        if isinstance(source_entry, dict):
                            source_name = str(source_entry.get('source_name') or '').strip()
                            if source_name:
                                datapull_source = source_name
                                break
                
                action = 'created' if result.upserted_id else 'updated'
                has_comment = False
                if isinstance(sources, list):
                    for source_entry in sources:
                        if isinstance(source_entry, dict) and str(source_entry.get('comment') or '').strip():
                            has_comment = True
                            break
                datapull.log_indicator_activity(
                    action=action,
                    datapull_source=datapull_source,
                    indicator_value=value,
                    indicator_type=dtype,
                    event_time=datetime.utcnow(),
                    details={
                        'entrypoint': '/api/indicators/bulk-add',
                        'actor': actor,
                        'static_added_by': actor,
                        'has_comment': has_comment
                    },
                    mongo_client=mongo_client
                )
                
                results.append({'value': value, 'type': dtype, 'status': 'ok'})
            except Exception as item_error:
                results.append({'value': value, 'type': dtype, 'status': 'error', 'error': str(item_error)})
        
        mongo_client.close()
        
        ok_count = sum(1 for r in results if r['status'] == 'ok')
        err_count = sum(1 for r in results if r['status'] == 'error')
        skipped_count = sum(1 for r in results if r['status'] == 'skipped')
        
        return jsonify({
            'message': f'Bulk add complete. {ok_count} added/updated, {err_count} errors, {skipped_count} skipped.',
            'results': results,
            'ok_count': ok_count,
            'error_count': err_count,
            'skipped_count': skipped_count
        }), 200
    except Exception as e:
        return jsonify({'message': str(e)}), 500


@app.route('/api/indicators/enrich', methods=['POST'])
@token_required
def enrich_indicator():
    if not request.is_json:
        return jsonify({'message': 'Request must be JSON.'}), 400
    data = request.json
    value = str(data.get('value') or '').strip()
    dtype = str(data.get('type') or data.get('dtype') or '').strip()
    raw_selected = data.get('selected_enrichments')
    selected_enrichments = None
    if isinstance(raw_selected, list):
        selected_enrichments = [str(name).strip() for name in raw_selected if str(name).strip()]
    if not value or not dtype:
        return jsonify({'message': 'Missing required fields: value and type.'}), 400
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        enriched_doc, enrich_error = data_enrichments.enrich_and_update_indicator(
            value,
            dtype,
            mongo_client,
            selected_enrichment_names=selected_enrichments
        )
        mongo_client.close()
        if enrich_error and not enriched_doc:
            return jsonify({'message': enrich_error}), 404
        return jsonify({'message': 'Enrichment applied.', 'indicator': enriched_doc or {}, 'note': enrich_error}), 200
    except Exception as e:
        return jsonify({'message': str(e)}), 500


@app.route('/api/indicators/enrich-bulk', methods=['POST'])
@token_required
def enrich_indicators_bulk():
    if not request.is_json:
        return jsonify({'message': 'Request must be JSON.'}), 400
    data = request.json
    items = data.get('indicators') or []
    raw_selected = data.get('selected_enrichments')
    selected_enrichments = None
    if isinstance(raw_selected, list):
        selected_enrichments = [str(name).strip() for name in raw_selected if str(name).strip()]
    if not isinstance(items, list) or not items:
        return jsonify({'message': 'indicators must be a non-empty list of {value, type} objects.'}), 400
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        results = []
        for item in items:
            value = str(item.get('value') or '').strip()
            dtype = str(item.get('type') or item.get('dtype') or '').strip()
            if not value or not dtype:
                results.append({'value': value, 'type': dtype, 'status': 'skipped', 'error': 'missing value or type'})
                continue
            enriched_doc, enrich_error = data_enrichments.enrich_and_update_indicator(
                value,
                dtype,
                mongo_client,
                selected_enrichment_names=selected_enrichments
            )
            if enrich_error and not enriched_doc:
                results.append({'value': value, 'type': dtype, 'status': 'error', 'error': enrich_error})
            else:
                results.append({'value': value, 'type': dtype, 'status': 'ok', 'note': enrich_error})
        mongo_client.close()
        ok_count = sum(1 for r in results if r['status'] == 'ok')
        err_count = sum(1 for r in results if r['status'] == 'error')
        return jsonify({'message': f'Enrichment complete. {ok_count} ok, {err_count} errors.', 'results': results}), 200
    except Exception as e:
        return jsonify({'message': str(e)}), 500


@app.route('/api/indicators/detail', methods=['GET'])
@endpoint_docs.endpoint_doc(
    summary='Get indicator detail',
    description='Returns full detail for a single indicator including enrichment data.',
    auth_types=['session', 'api_key'],
    tags=['Indicators'],
    query_params={
        'value': {'type': 'string', 'description': 'Indicator value (required)'},
        'type': {'type': 'string', 'description': 'Indicator type (optional filter)'},
    },
    responses={
        200: {'description': 'Indicator detail'},
        400: {'description': 'Missing value parameter'},
        404: {'description': 'Indicator not found'},
        500: {'description': 'Server error'}
    }
)
@token_required
def get_indicator_detail():
    try:
        value = str(request.args.get('value') or '').strip()
        dtype = str(request.args.get('type') or '').strip()

        if not value:
            return jsonify({'message': 'Missing required query parameter: value'}), 400

        mongo_client, mongo_connect_string = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_data"]
        indicators = db["indicators"]

        query = {'value': value}
        if dtype:
            query['$or'] = [{'dtype': dtype}, {'type': dtype}]

        indicator_doc = indicators.find_one(query)
        if not indicator_doc:
            mongo_client.close()
            return jsonify({'message': 'Indicator not found.'}), 404

        sources = indicator_doc.get('sources', [])
        br_scores = []
        for src in sources:
            score = src.get('br_score') if isinstance(src, dict) else None
            if score is None:
                continue
            try:
                br_scores.append(float(score))
            except (ValueError, TypeError):
                continue

        max_br_score = max(br_scores) if br_scores else None

        enrichment_data = {}
        comments_data = []

        raw_enrichment_obj = indicator_doc.get('data-enrichment')
        if isinstance(raw_enrichment_obj, dict):
            for field_name, field_payload in raw_enrichment_obj.items():
                if isinstance(field_payload, dict):
                    field_value = field_payload.get('value')
                    updated_at = field_payload.get('updated_at')
                    enrichment_data[field_name] = {
                        'value': field_value,
                        'updated_at': updated_at.isoformat() if hasattr(updated_at, 'isoformat') else updated_at
                    }
                else:
                    enrichment_data[field_name] = {
                        'value': field_payload,
                        'updated_at': None
                    }

        if isinstance(sources, list):
            for source_entry in sources:
                if not isinstance(source_entry, dict):
                    continue
                source_name = str(source_entry.get('source_name') or '').strip() or None
                source_comments = source_entry.get('comments') if isinstance(source_entry.get('comments'), list) else []

                if source_comments:
                    for comment_entry in source_comments:
                        if not isinstance(comment_entry, dict):
                            continue
                        comment_text = str(comment_entry.get('comment') or '').strip()
                        if not comment_text:
                            continue
                        created_at = comment_entry.get('created_at')
                        comments_data.append({
                            'comment': comment_text,
                            'created_at': created_at.isoformat() if hasattr(created_at, 'isoformat') else created_at,
                            'created_by': str(comment_entry.get('created_by') or '').strip() or None,
                            'source_name': source_name,
                        })
                else:
                    source_comment = str(source_entry.get('comment') or '').strip()
                    if source_comment:
                        comments_data.append({
                            'comment': source_comment,
                            'created_at': source_entry.get('lastupdate_time').isoformat() if hasattr(source_entry.get('lastupdate_time'), 'isoformat') else source_entry.get('lastupdate_time'),
                            'created_by': None,
                            'source_name': source_name,
                        })

        comments_data.sort(
            key=lambda item: str(item.get('created_at') or ''),
            reverse=True
        )

        indicator = {
            'value': indicator_doc.get('value'),
            'type': indicator_doc.get('dtype') or indicator_doc.get('type'),
            'dtype': indicator_doc.get('dtype'),
            'active': indicator_doc.get('active', False),
            'max_br_score': max_br_score,
            'source_count': len(sources),
            'sources': sources,
            'firstupdate_time': (indicator_doc.get('firstupdate_time') or indicator_doc.get('e_time')).isoformat() if hasattr((indicator_doc.get('firstupdate_time') or indicator_doc.get('e_time')), 'isoformat') else (indicator_doc.get('firstupdate_time') or indicator_doc.get('e_time')),
            'last_seen': indicator_doc.get('e_time').isoformat() if hasattr(indicator_doc.get('e_time'), 'isoformat') else indicator_doc.get('e_time'),
            'enrichment_data': enrichment_data,
            'comments': comments_data
        }

        mongo_client.close()
        return jsonify({'indicator': indicator}), 200
    except Exception as e:
        return jsonify({'message': str(e)}), 500


@app.route('/api/indicators/comment', methods=['POST'])
@token_required
def add_indicator_comment():
    if not request.is_json:
        return jsonify({'message': 'Request must be JSON.'}), 400

    data = request.json or {}
    value = str(data.get('value') or '').strip()
    dtype = str(data.get('type') or data.get('dtype') or '').strip()
    comment_text = str(data.get('comment') or '').strip()
    source_name = str(data.get('source_name') or '').strip()

    if not value or not comment_text or not source_name:
        return jsonify({'message': 'Missing required fields: value, source_name, and comment.'}), 400

    if len(comment_text) > 2000:
        return jsonify({'message': 'Comment is too long (max 2000 characters).'}), 400

    mongo_client = None
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client['byoint_core_data']
        indicators = db['indicators']

        query = {'value': value}
        if dtype:
            query['$or'] = [{'dtype': dtype}, {'type': dtype}]

        indicator_doc = indicators.find_one(query)
        if not indicator_doc:
            return jsonify({'message': 'Indicator not found.'}), 404

        existing_sources = indicator_doc.get('sources') if isinstance(indicator_doc.get('sources'), list) else []
        matched_source = False
        updated_sources = []
        for source_entry in existing_sources:
            if not isinstance(source_entry, dict):
                updated_sources.append(source_entry)
                continue

            updated_entry = dict(source_entry)
            current_source_name = str(updated_entry.get('source_name') or '').strip()
            if current_source_name == source_name:
                matched_source = True
                existing_comments = updated_entry.get('comments') if isinstance(updated_entry.get('comments'), list) else []
                updated_entry['comments'] = [
                    *existing_comments,
                    {
                        'comment': comment_text,
                        'created_at': datetime.utcnow(),
                        'created_by': str(getattr(g, 'current_user', '') or '').strip() or None,
                        'source_name': source_name,
                    }
                ]
                updated_entry['comment'] = comment_text
                updated_entry['lastupdate_time'] = datetime.utcnow()
            updated_sources.append(updated_entry)

        if not matched_source:
            return jsonify({'message': f'Source not found on indicator: {source_name}'}), 404

        actor = str(getattr(g, 'current_user', '') or '').strip() or None
        created_at = datetime.utcnow()

        result = indicators.update_one(
            {'_id': indicator_doc.get('_id')},
            {'$set': {'sources': updated_sources, 'e_time': created_at}}
        )

        datapull.log_indicator_activity(
            action='commented',
            datapull_source=source_name,
            indicator_value=value,
            indicator_type=dtype or indicator_doc.get('dtype') or indicator_doc.get('type'),
            event_time=datetime.utcnow(),
            details={
                'entrypoint': '/api/indicators/comment',
                'source_name': source_name,
                'comment_preview': (comment_text[:140] + '...') if len(comment_text) > 140 else comment_text,
                'actor': actor,
                'matched_count': result.matched_count,
                'modified_count': result.modified_count,
            },
            mongo_client=mongo_client
        )

        return jsonify({
            'message': 'Indicator comment added successfully.',
            'comment': {
                'comment': comment_text,
                'created_at': created_at.isoformat(),
                'created_by': actor,
                'source_name': source_name,
            }
        }), 201
    except Exception as e:
        return jsonify({'message': str(e)}), 500
    finally:
        if mongo_client:
            mongo_client.close()


@app.route('/api/indicators/timeline', methods=['GET'])
@token_required
def get_indicator_timeline():
    """Return timeline for an indicator including first-add attribution."""
    mongo_client = None
    try:
        value = str(request.args.get('value') or '').strip()
        dtype = str(request.args.get('type') or request.args.get('dtype') or '').strip()

        if not value:
            return jsonify({'message': 'Missing required query parameter: value'}), 400

        mongo_client, _ = all_connects.connect_mongodb()

        core_db = mongo_client['byoint_core_data']
        indicators_col = core_db['indicators']

        indicator_query = {'value': value}
        if dtype:
            indicator_query['$or'] = [{'dtype': dtype}, {'type': dtype}]

        indicator_doc = indicators_col.find_one(indicator_query)
        if not indicator_doc:
            return jsonify({'message': 'Indicator not found.'}), 404

        resolved_type = str(indicator_doc.get('dtype') or indicator_doc.get('type') or '').strip()

        ops_db = mongo_client['byoint_opslogs']
        logs_col = ops_db['indicator_logs']
        platform_change_logs_col = ops_db['platform_change_logs']

        logs_query = {'indicator_value': value}
        if resolved_type:
            logs_query['indicator_type'] = resolved_type

        def _serialize_value(value_obj):
            if isinstance(value_obj, datetime):
                return value_obj.isoformat()
            if isinstance(value_obj, dict):
                return {k: _serialize_value(v) for k, v in value_obj.items()}
            if isinstance(value_obj, list):
                return [_serialize_value(v) for v in value_obj]
            if hasattr(value_obj, '__class__') and value_obj.__class__.__name__ == 'ObjectId':
                return str(value_obj)
            return value_obj

        def _to_iso(value_obj):
            if hasattr(value_obj, 'isoformat'):
                return value_obj.isoformat()
            return value_obj

        fallback_actor_cache = {}

        def _infer_static_actor(event_dt):
            cache_key = _to_iso(event_dt)
            if cache_key in fallback_actor_cache:
                return fallback_actor_cache[cache_key]

            time_filter = {}
            if isinstance(event_dt, datetime):
                time_filter = {
                    'created_at': {
                        '$gte': event_dt - timedelta(days=2),
                        '$lte': event_dt + timedelta(days=2)
                    }
                }

            query = {
                'path': {'$in': ['/api/indicators/new', '/api/indicators/bulk-add']},
                '$or': [
                    {
                        'request_payload.value': value,
                        '$or': [
                            {'request_payload.type': resolved_type},
                            {'request_payload.dtype': resolved_type}
                        ] if resolved_type else [
                            {'request_payload.value': value}
                        ]
                    },
                    {
                        'request_payload.indicators': {
                            '$elemMatch': ({
                                'value': value,
                                '$or': [
                                    {'type': resolved_type},
                                    {'dtype': resolved_type}
                                ]
                            } if resolved_type else {
                                'value': value
                            })
                        }
                    }
                ]
            }
            if time_filter:
                query.update(time_filter)

            best_actor = None
            best_distance_seconds = None
            try:
                for change_doc in platform_change_logs_col.find(query, {'actor': 1, 'created_at': 1}).sort([('created_at', -1)]).limit(100):
                    actor_value = str(change_doc.get('actor') or '').strip() or None
                    if not actor_value:
                        continue

                    created_at = change_doc.get('created_at')
                    if isinstance(event_dt, datetime) and isinstance(created_at, datetime):
                        distance_seconds = abs((created_at - event_dt).total_seconds())
                    else:
                        distance_seconds = 0

                    if best_distance_seconds is None or distance_seconds < best_distance_seconds:
                        best_distance_seconds = distance_seconds
                        best_actor = actor_value
            except Exception:
                best_actor = None

            fallback_actor_cache[cache_key] = best_actor
            return best_actor

        timeline = []
        for log_doc in logs_col.find(logs_query).sort([('event_time', 1), ('_id', 1)]):
            details = log_doc.get('details') if isinstance(log_doc.get('details'), dict) else {}
            source_name = str(log_doc.get('datapull_source') or '').strip()
            entrypoint = str(details.get('entrypoint') or '').strip().lower()

            via = 'datapull'
            if source_name.lower() == 'static' or entrypoint in ('/api/indicators/new', '/api/indicators/bulk-add'):
                via = 'static'

            actor = (
                details.get('static_added_by')
                or details.get('updated_by')
                or details.get('actor')
                or None
            )
            if not actor and via == 'static':
                actor = _infer_static_actor(log_doc.get('event_time') or log_doc.get('logged_at'))

            timeline.append({
                'timestamp': _to_iso(log_doc.get('event_time') or log_doc.get('logged_at')),
                'logged_at': _to_iso(log_doc.get('logged_at')),
                'action': str(log_doc.get('action') or '').strip().lower() or None,
                'source': source_name or None,
                'via': via,
                'actor': actor,
                'details': _serialize_value(details)
            })

        first_created_event = None
        for event in timeline:
            if str(event.get('action') or '') == 'created':
                first_created_event = event
                break
        if first_created_event is None and timeline:
            first_created_event = timeline[0]

        first_seen = indicator_doc.get('firstupdate_time') or indicator_doc.get('e_time')
        if first_created_event and first_created_event.get('timestamp'):
            first_seen = first_seen or first_created_event.get('timestamp')

        summary = {
            'first_added_at': _to_iso(first_seen),
            'first_added_via': first_created_event.get('via') if first_created_event else None,
            'first_added_source': first_created_event.get('source') if first_created_event else None,
            'first_added_by': first_created_event.get('actor') if first_created_event else None,
        }

        indicator_payload = {
            'value': indicator_doc.get('value'),
            'type': resolved_type,
            'firstupdate_time': _to_iso(indicator_doc.get('firstupdate_time') or indicator_doc.get('e_time')),
            'last_seen': _to_iso(indicator_doc.get('e_time')),
            'sources': _serialize_value(indicator_doc.get('sources') if isinstance(indicator_doc.get('sources'), list) else [])
        }

        return jsonify({'indicator': indicator_payload, 'summary': summary, 'timeline': timeline}), 200
    except Exception as e:
        return jsonify({'message': str(e)}), 500
    finally:
        if mongo_client:
            mongo_client.close()


@app.route('/api/indicators/tag', methods=['POST'])
@token_required
def update_indicator_source_tag():
    if not request.is_json:
        return jsonify({'message': 'Request must be JSON.'}), 400

    data = request.json or {}
    value = str(data.get('value') or '').strip()
    dtype = str(data.get('type') or data.get('dtype') or '').strip()
    source_name = str(data.get('source_name') or '').strip()
    raw_tags = data.get('tags') if 'tags' in data else data.get('tag')

    def _normalize_tags(raw_value):
        if isinstance(raw_value, list):
            return [str(tag).strip() for tag in raw_value if str(tag).strip()]
        if raw_value is None:
            return []
        return [tag.strip() for tag in str(raw_value).split(',') if tag.strip()]

    tags = _normalize_tags(raw_tags)

    if not value:
        return jsonify({'message': 'Missing required fields.'}), 400

    mongo_client = None
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client['byoint_core_data']
        indicators = db['indicators']
        config_db = mongo_client['byoint_core_config']
        tag_col = config_db['tags']

        allowed_tags = set()
        for tag_doc in tag_col.find({}, {'_id': 0, 'name': 1}):
            tag_name = str(tag_doc.get('name') or '').strip()
            if tag_name:
                allowed_tags.add(tag_name)

        invalid_tags = [tag for tag in tags if tag not in allowed_tags]
        if invalid_tags:
            return jsonify({'message': f"Invalid tag(s): {', '.join(invalid_tags)}. Use tags from byoint_core_config.tags only."}), 400

        query = {'value': value}
        if dtype:
            query['$or'] = [{'dtype': dtype}, {'type': dtype}]

        indicator_doc = indicators.find_one(query)
        if not indicator_doc:
            return jsonify({'message': 'Indicator not found.'}), 404

        existing_sources = indicator_doc.get('sources', [])
        if not isinstance(existing_sources, list) or not existing_sources:
            return jsonify({'message': 'Indicator has no sources to update.'}), 404

        target_source_name = source_name
        if not target_source_name:
            if len(existing_sources) == 1 and isinstance(existing_sources[0], dict):
                target_source_name = str(existing_sources[0].get('source_name') or '').strip()
            else:
                return jsonify({'message': 'source_name is required when the indicator has multiple sources.'}), 400

        updated_sources = []
        matched = False
        for source_entry in existing_sources:
            if not isinstance(source_entry, dict):
                updated_sources.append(source_entry)
                continue

            updated_entry = dict(source_entry)
            current_source_name = str(updated_entry.get('source_name') or '').strip()
            if current_source_name == target_source_name:
                updated_entry['tag'] = tags
                matched = True
            updated_sources.append(updated_entry)

        if not matched:
            return jsonify({'message': f"Source not found on indicator: {target_source_name}"}), 404

        result = indicators.update_one(
            {'_id': indicator_doc.get('_id')},
            {'$set': {'sources': updated_sources}}
        )

        datapull.log_indicator_activity(
            action='updated',
            datapull_source=target_source_name,
            indicator_value=value,
            indicator_type=dtype or indicator_doc.get('dtype') or indicator_doc.get('type'),
            event_time=datetime.utcnow(),
            details={'entrypoint': '/api/indicators/tag', 'tags': tags, 'matched_count': result.matched_count, 'modified_count': result.modified_count},
            mongo_client=mongo_client
        )

        return jsonify({
            'message': 'Indicator tag updated successfully!',
            'indicator': {
                'value': value,
                'type': dtype or indicator_doc.get('dtype') or indicator_doc.get('type'),
                'sources': updated_sources,
            }
        }), 200
    except Exception as e:
        return jsonify({'message': str(e)}), 500
    finally:
        if mongo_client:
            mongo_client.close()


@app.route('/api/indicators/sources', methods=['GET'])
@token_required
def get_indicator_sources():
    """Get all unique source names from indicators collection"""
    try:
        mongo_client, mongo_connect_string = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_data"]
        indicators = db["indicators"]
        
        # Use aggregation to get unique source names
        pipeline = [
            {"$unwind": "$sources"},
            {"$group": {"_id": "$sources.source_name"}},
            {"$sort": {"_id": 1}}
        ]
        
        result = list(indicators.aggregate(pipeline))
        sources = [item["_id"] for item in result if item.get("_id")]
        
        mongo_client.close()
        return jsonify({'sources': sources}), 200
    except Exception as e:
        return jsonify({'message': str(e)}), 500


@app.route('/api/indicators/types', methods=['GET'])
@token_required
def get_indicator_types():
    """Get all unique indicator types from indicators collection"""
    try:
        mongo_client, mongo_connect_string = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_data"]
        indicators = db["indicators"]

        types = indicators.distinct("type")
        dtype_types = indicators.distinct("dtype")
        indicator_types = sorted({t for t in (types + dtype_types) if t})

        mongo_client.close()
        return jsonify({'indicator_types': indicator_types}), 200
    except Exception as e:
        return jsonify({'message': str(e)}), 500





@app.route('/api/outputs', methods=['GET'])
@token_required
def get_outputs():
    try:
        mongo_client, mongo_connect_string = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_data"]
        outputs = db["outputs"]

        def serialize_value(value):
            if isinstance(value, datetime):
                return value.isoformat()
            if isinstance(value, dict):
                return {k: serialize_value(v) for k, v in value.items()}
            if isinstance(value, list):
                return [serialize_value(v) for v in value]
            if hasattr(value, '__class__') and value.__class__.__name__ == 'ObjectId':
                return str(value)
            return value

        out = []
        for d in outputs.find({}).sort('_id', -1):
            out.append(serialize_value(d))

        mongo_client.close()
        return jsonify({'outputs': out}), 200
    except Exception as e:
        return jsonify({'message': str(e)}), 500


@app.route('/api/dashboard/metrics', methods=['GET'])
@token_required
def get_dashboard_metrics():
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_data"]

        workflows_col = db["datapull_workflows"]
        outputs_col = db["outputs"]
        indicators_col = db["indicators"]

        workflow_count = workflows_col.count_documents({})
        outputs_count = outputs_col.count_documents({})

        pipeline = [
            {
                "$project": {
                    "type_key": {
                        "$ifNull": ["$dtype", {"$ifNull": ["$type", "unknown"]}]
                    }
                }
            },
            {
                "$group": {
                    "_id": "$type_key",
                    "count": {"$sum": 1}
                }
            },
            {
                "$project": {
                    "_id": 0,
                    "type": {
                        "$cond": [
                            {"$or": [{"$eq": ["$_id", None]}, {"$eq": ["$_id", ""]}]},
                            "unknown",
                            {"$toString": "$_id"}
                        ]
                    },
                    "count": 1
                }
            },
            {"$sort": {"count": -1, "type": 1}}
        ]

        indicator_counts_by_type = list(indicators_col.aggregate(pipeline))
        total_indicators = sum(int(item.get('count', 0)) for item in indicator_counts_by_type)

        mongo_client.close()
        return jsonify({
            'workflow_count': workflow_count,
            'outputs_count': outputs_count,
            'total_indicators': total_indicators,
            'indicator_counts_by_type': indicator_counts_by_type
        }), 200
    except Exception as e:
        return jsonify({'message': str(e)}), 500


@app.route('/api/dashboard/flow', methods=['GET'])
@token_required
def get_dashboard_flow():
    """Datapull -> enrichment -> output graph for the dashboard diagram."""
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        data_db = mongo_client["byoint_core_data"]
        config_db = mongo_client["byoint_core_config"]

        def as_name_list(value):
            if isinstance(value, list):
                return [str(v).strip() for v in value if str(v).strip()]
            text = str(value or '').strip()
            return [text] if text else []

        datapulls = []
        for d in data_db["datapull_workflows"].find({}, {'source_name': 1, 'source_type': 1, 'active': 1, 'schedule_enabled': 1, 'selected_enrichments': 1}):
            for source in as_name_list(d.get('source_name')):
                datapulls.append({
                    'name': source,
                    'source_type': d.get('source_type') or '',
                    'active': bool(d.get('active', True)),
                    'schedule_enabled': bool(d.get('schedule_enabled', False)),
                    'enrichments': as_name_list(d.get('selected_enrichments'))
                })

        enrichments = []
        for d in config_db["data_enrichments"].find({}, {'enrich_name': 1, 'enrich_data_type': 1, 'enrich_type': 1, 'enabled': 1}):
            name = str(d.get('enrich_name') or '').strip()
            if name:
                enrichments.append({
                    'name': name,
                    'data_type': d.get('enrich_data_type') or '',
                    'enrich_type': d.get('enrich_type') or '',
                    'enabled': bool(d.get('enabled', False))
                })

        outputs = []
        for d in data_db["outputs"].find({}, {'name': 1, 'type': 1, 'enabled': 1, 'source_name': 1, 'filter_search': 1}):
            criteria = data_output._extract_filter_criteria(d.get('filter_search'))
            outputs.append({
                'name': str(d.get('name') or '').strip(),
                'type': d.get('type') or '',
                'enabled': bool(d.get('enabled', True)),
                'sources': as_name_list(d.get('source_name')),
                'filter_enrichments': criteria.get('selected_enrichments') or []
            })

        mongo_client.close()
        return jsonify({'datapulls': datapulls, 'enrichments': enrichments, 'outputs': outputs}), 200
    except Exception as e:
        return jsonify({'message': str(e)}), 500


@app.route('/api/outputs/filter_options', methods=['GET'])
@token_required
def get_output_filter_options():
    try:
        raw = request.args.get('source_names', '')
        source_names = [s.strip() for s in raw.split(',') if s.strip()] if raw else []
        options, err = data_output.get_filter_options_for_sources(source_names)
        if err:
            return jsonify({'message': err}), 500
        return jsonify(options), 200
    except Exception as e:
        return jsonify({'message': str(e)}), 500


@app.route('/api/outputs/query_preview', methods=['POST'])
@token_required
def get_output_query_preview():
    try:
        if not request.is_json:
            return jsonify({'message': 'Request must be JSON.'}), 400

        data = request.json or {}
        source_name = data.get('source_name')
        filter_search = data.get('filter_search')
        output_category = data.get('output_category')

        if isinstance(source_name, list):
            normalized_source = [str(s).strip() for s in source_name if str(s).strip()]
        else:
            source_text = str(source_name or '').strip()
            normalized_source = [source_text] if source_text else []

        query, err = data_output.get_indicator_query_preview(
            output_source=normalized_source,
            filter_search=filter_search,
            output_category=output_category
        )
        if err:
            return jsonify({'message': err}), 500

        return jsonify({'query': query}), 200
    except Exception as e:
        return jsonify({'message': str(e)}), 500


@app.route('/api/outputs/enrichment_values', methods=['GET'])
@token_required
def get_output_enrichment_values():
    try:
        values, err = data_output.get_distinct_enrichment_values()
        if err:
            return jsonify({'message': err}), 500
        return jsonify({'enrichment_values': values}), 200
    except Exception as e:
        return jsonify({'message': str(e)}), 500


@app.route('/api/outputs/sources', methods=['GET'])
@token_required
def get_output_sources():
    try:
        mongo_client, mongo_connect_string = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_data"]
        workflows = db["datapull_workflows"]
        source_type = str(request.args.get('source_type') or '').strip()

        query = {}
        if source_type:
            query['source_type'] = source_type

        source_set = set()
        for d in workflows.find(query, {'source_name': 1}):
            source_value = d.get('source_name')
            if isinstance(source_value, list):
                for source_item in source_value:
                    source_item_text = str(source_item).strip()
                    if source_item_text:
                        source_set.add(source_item_text)
            else:
                source_text = str(source_value or '').strip()
                if source_text:
                    source_set.add(source_text)

        mongo_client.close()
        return jsonify({'sources': sorted(list(source_set), key=lambda s: s.lower())}), 200
    except Exception as e:
        return jsonify({'message': str(e)}), 500


@app.route('/api/outputs/create', methods=['POST'])
@token_required
def create_output():
    if not request.is_json:
        return jsonify({'message': 'Request must be JSON!'}), 400

    data = request.json or {}
    name = data.get('name')
    source_name = data.get('source_name')
    output_type = str(data.get('type') or '').strip().lower()
    output_sourcetype = data.get('output_sourcetype')
    filter_search = data.get('filter_search')
    enabled = data.get('enabled', True)
    feed_authentication_status = bool(data.get('feed_authentication_status', False))

    if output_type in ('json', 'mcp'):
        feed_authentication_status = True

    if isinstance(source_name, list):
        source_name = [str(s).strip() for s in source_name if str(s).strip()]
    else:
        source_name = str(source_name or '').strip()

    if not name or not source_name or not output_type:
        return jsonify({'message': 'Missing required fields: name, source_name, type'}), 400

    enabled = bool(enabled)

    try:
        mongo_client, mongo_connect_string = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_data"]
        outputs = db["outputs"]

        doc = {
            'name': name,
            'source_name': source_name,
            'type': output_type,
            'output_sourcetype': output_sourcetype,
            'output_category': str(data.get('output_category') or 'general').strip().lower(),
            'filter_search': filter_search,
            'enabled': enabled,
            'feed_authentication_status': feed_authentication_status,
            'creation_time': datetime.utcnow()
        }

        insert_result = outputs.insert_one(doc)
        doc['_id'] = str(insert_result.inserted_id)
        doc['creation_time'] = doc['creation_time'].isoformat()

        try:
            data_output.invalidate_output_feed_cache(name)
        except Exception:
            pass

        mongo_client.close()
        return jsonify({'message': 'Output created successfully!', 'output': doc}), 201
    except Exception as e:
        return jsonify({'message': str(e)}), 500


@app.route('/api/outputs/edl', methods=['GET'])
@token_required
def get_outputs_edl():
    try:
        output_name = request.args.get('name')
        if output_name and str(output_name).strip():
            one = data_output.output_edl_by_name(str(output_name).strip())
            return jsonify({'outputs_edl': [one] if one else []}), 200

        source = request.args.get('source')
        data = data_output.output_edl(source=source)
        return jsonify({'outputs_edl': data or []}), 200
    except Exception as e:
        return jsonify({'message': str(e)}), 500


@app.route('/feeds/<outputname>', methods=['GET'])
def feed_output_page(outputname):
    try:
        output_type = ''
        feed_authentication_status = False

        try:
            mongo_client, _ = all_connects.connect_mongodb()
            db = mongo_client["byoint_core_data"]
            output_doc = db["outputs"].find_one(
                {"name": outputname},
                {"feed_authentication_status": 1, "type": 1}
            )
            mongo_client.close()
        except Exception:
            output_doc = None

        if output_doc:
            output_type = str(output_doc.get("type") or '').strip().lower()
            feed_authentication_status = bool(output_doc.get("feed_authentication_status", False))

        requires_auth = output_type == 'json' or feed_authentication_status
        response_is_json = output_type == 'json'

        if requires_auth:
            current_user, auth_type, auth_error, session_id, clear_cookie = auth.authenticate_request()
            if auth_error:
                message = 'Authentication required for this feed.' if auth_error == 'Authentication required.' else auth_error
                if response_is_json:
                    response = make_response(jsonify({'message': message}), 401)
                    if clear_cookie:
                        auth.clear_session_cookie(response)
                    return response
                response = make_response(f"<html><body><h3>{html.escape(message)}</h3></body></html>", 401)
                response.headers['Content-Type'] = 'text/html; charset=utf-8'
                if clear_cookie:
                    auth.clear_session_cookie(response)
                return response

        result = data_output.output_edl_by_name_cached(outputname)
        if not result:
            if response_is_json:
                return jsonify({'message': f'Feed not found: {outputname}'}), 404
            return f"<html><body><h3>Feed not found: {html.escape(outputname)}</h3></body></html>", 404, {'Content-Type': 'text/html; charset=utf-8'}

        result_type = str(result.get('type') or '').strip().lower()
        if result_type == 'mcp':
            mcp_path = f"/mcp/{quote(outputname, safe='')}"
            return f"<html><body><h3>{html.escape(outputname)} is an MCP output.</h3><p>Connect an MCP client (Streamable HTTP) to <code>{html.escape(mcp_path)}</code> with an API key as a Bearer token.</p></body></html>", 200, {'Content-Type': 'text/html; charset=utf-8'}

        if result_type == 'json':
            return jsonify({
                'name': result.get('name'),
                'source_name': result.get('source_name'),
                'type': result.get('type'),
                'enabled': result.get('enabled', False),
                'feed_authentication_status': bool(result.get('feed_authentication_status', True)),
                'filter_search': result.get('filter_search'),
                'source_filters': result.get('source_filters') or [],
                'indicator_count': result.get('indicator_count', 0),
                'entries': result.get('entries') or []
            }), 200

        if result_type != 'edl_feed':
            return f"<html><body><h3>Unsupported feed type for: {html.escape(outputname)}</h3></body></html>", 400, {'Content-Type': 'text/html; charset=utf-8'}

        entries = result.get('entries') or []
        escaped_entries = [html.escape(str(e)) for e in entries]
        body_html = '<br/>'.join(escaped_entries)

        page_html = f"""
<!DOCTYPE html>
<html>
    <head>
        <meta charset=\"utf-8\" />
        <title>{html.escape(outputname)} feed</title>
    </head>
    <body>
        {body_html}
    </body>
</html>
"""
        return page_html, 200, {'Content-Type': 'text/html; charset=utf-8'}
    except Exception as e:
        return f"<html><body><h3>Error generating feed: {html.escape(str(e))}</h3></body></html>", 500, {'Content-Type': 'text/html; charset=utf-8'}


@app.route('/mcp/<outputname>', methods=['POST', 'GET', 'DELETE'])
def mcp_output_endpoint(outputname):
    # Stateless Streamable HTTP transport: no server-initiated SSE stream and no sessions.
    if request.method != 'POST':
        return jsonify({'message': 'Method not allowed. Send JSON-RPC messages via POST.'}), 405, {'Allow': 'POST'}

    current_user, auth_type, auth_error, session_id, clear_cookie = auth.authenticate_request()
    if auth_error:
        response = make_response(jsonify({'message': auth_error}), 401)
        response.headers['WWW-Authenticate'] = 'Bearer'
        if clear_cookie:
            auth.clear_session_cookie(response)
        return response

    try:
        mongo_client, _ = all_connects.connect_mongodb()
        output_doc = mongo_client["byoint_core_data"]["outputs"].find_one({"name": outputname}, {"type": 1, "enabled": 1})
        mongo_client.close()
    except Exception as e:
        return jsonify(mcp_output._error(None, mcp_output.INTERNAL_ERROR, str(e))), 500

    if not output_doc or str(output_doc.get('type') or '').strip().lower() != 'mcp':
        return jsonify({'message': f'MCP output not found: {outputname}'}), 404
    if not data_output._is_enabled_output(output_doc):
        return jsonify({'message': f'MCP output is disabled: {outputname}'}), 404

    message = request.get_json(silent=True)
    if message is None:
        return jsonify(mcp_output._error(None, mcp_output.PARSE_ERROR, 'Request body must be valid JSON.')), 400
    if isinstance(message, list):
        return jsonify(mcp_output._error(None, mcp_output.INVALID_REQUEST, 'JSON-RPC batching is not supported.')), 400

    try:
        response_body = mcp_output.handle_message(outputname, message)
    except Exception as e:
        request_id = message.get('id') if isinstance(message, dict) else None
        return jsonify(mcp_output._error(request_id, mcp_output.INTERNAL_ERROR, str(e))), 500

    if response_body is None:
        return '', 202
    return jsonify(response_body), 200


@app.route('/api/feeds/<outputname>', methods=['GET'])
@token_required
def get_feed_output(outputname):
    try:
        result = data_output.output_edl_by_name_cached(outputname)
        if not result:
            return jsonify({'message': f'Feed not found: {outputname}'}), 404

        return jsonify({'feed': result}), 200
    except Exception as e:
        return jsonify({'message': str(e)}), 500


@app.route('/api/output-guardrails', methods=['GET'])
@token_required
def get_output_guardrails():
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client['byoint_core_config']
        guardrails_col = db['output_guardrails']
        
        guardrails = list(guardrails_col.find({}, {'_id': 1, 'action': 1, 'description': 1, 'output_category': 1, 'tag': 1}))
        
        for item in guardrails:
            if '_id' in item:
                item['_id'] = str(item['_id'])
        
        mongo_client.close()
        return jsonify({'guardrails': guardrails}), 200
    except Exception as e:
        return jsonify({'message': str(e)}), 500


@app.route('/api/output-guardrails', methods=['POST'])
@token_required
def create_output_guardrail():
    if not request.is_json:
        return jsonify({'message': 'Request must be JSON'}), 400
    
    data = request.json or {}
    
    try:
        action = (data.get('action') or '').strip()
        description = (data.get('description') or '').strip()
        output_category = (data.get('output_category') or '').strip()
        tag = (data.get('tag') or '').strip()
        
        if not action:
            action = 'disallow'
        if action != 'disallow':
            return jsonify({'message': 'Only "disallow" action is supported.'}), 400
        if not output_category:
            return jsonify({'message': 'output_category is required'}), 400
        if not tag:
            return jsonify({'message': 'tag is required'}), 400
        
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client['byoint_core_config']
        guardrails_col = db['output_guardrails']
        
        new_rule = {
            'action': action,
            'description': description,
            'output_category': output_category,
            'tag': tag,
        }
        
        result = guardrails_col.insert_one(new_rule)
        new_rule['_id'] = str(result.inserted_id)

        try:
            data_output.invalidate_all_output_feed_caches()
        except Exception:
            pass
        
        mongo_client.close()
        return jsonify({'message': 'Guardrail created', 'guardrail': new_rule}), 201
    except Exception as e:
        return jsonify({'message': str(e)}), 500


@app.route('/api/output-guardrails/<rule_id>', methods=['PUT'])
@token_required
def update_output_guardrail(rule_id):
    if not request.is_json:
        return jsonify({'message': 'Request must be JSON'}), 400
    
    data = request.json or {}
    
    try:
        from bson.objectid import ObjectId
        
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client['byoint_core_config']
        guardrails_col = db['output_guardrails']
        
        try:
            obj_id = ObjectId(rule_id)
        except:
            mongo_client.close()
            return jsonify({'message': 'Invalid rule ID'}), 400
        
        update_doc = {}
        if 'action' in data:
            action = (data.get('action') or '').strip()
            if action != 'disallow':
                return jsonify({'message': 'Only "disallow" action is supported.'}), 400
            update_doc['action'] = action
        
        if 'description' in data:
            update_doc['description'] = (data.get('description') or '').strip()
        
        if 'output_category' in data:
            category = (data.get('output_category') or '').strip()
            if not category:
                return jsonify({'message': 'output_category cannot be empty'}), 400
            update_doc['output_category'] = category
        
        if 'tag' in data:
            tag = (data.get('tag') or '').strip()
            if not tag:
                return jsonify({'message': 'tag cannot be empty'}), 400
            update_doc['tag'] = tag
        
        if not update_doc:
            mongo_client.close()
            return jsonify({'message': 'No fields to update'}), 400
        
        result = guardrails_col.update_one({'_id': obj_id}, {'$set': update_doc})
        
        if result.matched_count == 0:
            mongo_client.close()
            return jsonify({'message': 'Rule not found'}), 404

        try:
            data_output.invalidate_all_output_feed_caches()
        except Exception:
            pass
        
        mongo_client.close()
        return jsonify({'message': 'Guardrail updated'}), 200
    except Exception as e:
        return jsonify({'message': str(e)}), 500


@app.route('/api/output-guardrails/<rule_id>', methods=['DELETE'])
@token_required
def delete_output_guardrail(rule_id):
    try:
        from bson.objectid import ObjectId
        
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client['byoint_core_config']
        guardrails_col = db['output_guardrails']
        
        try:
            obj_id = ObjectId(rule_id)
        except:
            mongo_client.close()
            return jsonify({'message': 'Invalid rule ID'}), 400
        
        result = guardrails_col.delete_one({'_id': obj_id})
        
        if result.deleted_count == 0:
            mongo_client.close()
            return jsonify({'message': 'Rule not found'}), 404

        try:
            data_output.invalidate_all_output_feed_caches()
        except Exception:
            pass
        
        mongo_client.close()
        return jsonify({'message': 'Guardrail deleted'}), 200
    except Exception as e:
        return jsonify({'message': str(e)}), 500


# Endpoint to get all data types for indicator type dropdown
@app.route('/api/data_types', methods=['GET'])
@token_required
def get_data_types():
    try:
        mongo_client, mongo_connect_string = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_config"]
        data_types_col = db["data_types"]
        types = list(data_types_col.find({}, {"_id": 0, "name": 1}))
        # Return as a flat list of name strings
        name_list = [t["name"] for t in types if "name" in t]
        mongo_client.close()
        return jsonify({'data_types': name_list}), 200
    except Exception as e:
        return jsonify({'message': str(e)}), 500


@app.route('/api/data_types/details', methods=['GET'])
@token_required
def get_data_types_details():
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_config"]
        data_types_col = db["data_types"]

        details = []
        for doc in data_types_col.find({}, {"_id": 0}).sort("name", 1):
            created_at = doc.get('created_at')
            updated_at = doc.get('updated_at')
            details.append({
                'name': str(doc.get('name') or '').strip(),
                'type': str(doc.get('type') or '').strip() or None,
                'regex_extract_pattern': str(doc.get('regex_extract_pattern') or '').strip() or None,
                'description': str(doc.get('description') or '').strip() or None,
                'created_at': created_at.isoformat() if hasattr(created_at, 'isoformat') else created_at,
                'updated_at': updated_at.isoformat() if hasattr(updated_at, 'isoformat') else updated_at,
            })

        mongo_client.close()
        return jsonify({'data_types': details}), 200
    except Exception as e:
        return jsonify({'message': str(e), 'data_types': []}), 500


@app.route('/api/data_types', methods=['POST'])
@token_required
def create_data_type():
    if not request.is_json:
        return jsonify({'message': 'Request must be JSON.'}), 400

    data = request.json or {}
    dtype_name = str(data.get('name') or data.get('data_type') or '').strip()
    dtype_type = str(data.get('type') or '').strip() or None
    regex_extract_pattern = data.get('regex_extract_pattern')
    description = data.get('description')

    regex_extract_pattern = str(regex_extract_pattern).strip() if regex_extract_pattern is not None else None
    description = str(description).strip() if description is not None else None

    if not dtype_name:
        return jsonify({'message': 'Data type name is required.'}), 400

    if regex_extract_pattern:
        try:
            re.compile(regex_extract_pattern)
        except re.error as e:
            return jsonify({'message': f'Invalid regex_extract_pattern: {e}'}), 400

    try:
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_config"]
        data_types_col = db["data_types"]
        data_types_col.create_index("name", unique=True)

        existing = data_types_col.find_one({'name': dtype_name})
        if existing:
            mongo_client.close()
            return jsonify({'message': 'Data type already exists.'}), 409

        now = datetime.utcnow()
        doc = {
            'name': dtype_name,
            'created_at': now,
            'updated_at': now
        }
        if dtype_type:
            doc['type'] = dtype_type
        if regex_extract_pattern:
            doc['regex_extract_pattern'] = regex_extract_pattern
        if description:
            doc['description'] = description

        data_types_col.insert_one(doc)
        mongo_client.close()

        return jsonify({
            'message': 'Data type created successfully.',
            'data_type': {
                'name': doc.get('name'),
                'regex_extract_pattern': doc.get('regex_extract_pattern'),
                'description': doc.get('description'),
                'created_at': now.isoformat(),
                'updated_at': now.isoformat()
            }
        }), 201
    except Exception as e:
        return jsonify({'message': str(e)}), 500


@app.route('/api/data_types/<string:dtype_name>', methods=['DELETE'])
@token_required
def delete_data_type(dtype_name):
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_config"]
        data_types_col = db["data_types"]

        doc = data_types_col.find_one({'name': dtype_name})
        if not doc:
            mongo_client.close()
            return jsonify({'message': 'Data type not found.'}), 404

        doc_type = str(doc.get('type') or '').strip().lower()
        if doc_type != 'custom':
            mongo_client.close()
            return jsonify({'message': 'Only Custom data types can be deleted.'}), 403

        data_types_col.delete_one({'name': dtype_name})
        mongo_client.close()
        return jsonify({'message': f'Data type "{dtype_name}" deleted successfully.'}), 200
    except Exception as e:
        return jsonify({'message': str(e)}), 500


@app.route('/api/configuration/basicconfigs', methods=['GET'])
@token_required
@auth.require_roles('admin')
def get_basicconfigs():
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_config"]
        basicconfigs_col = db["basicconfigs"]

        def serialize_value(value):
            if isinstance(value, datetime):
                return value.isoformat()
            if isinstance(value, dict):
                return {k: serialize_value(v) for k, v in value.items()}
            if isinstance(value, list):
                return [serialize_value(v) for v in value]
            if hasattr(value, '__class__') and value.__class__.__name__ == 'ObjectId':
                return str(value)
            return value

        configs = []
        for d in basicconfigs_col.find({}).sort('module', 1):
            configs.append(serialize_value(d))

        mongo_client.close()
        return jsonify({'configs': configs}), 200
    except Exception as e:
        return jsonify({'message': str(e), 'configs': []}), 500


@app.route('/api/configuration/basicconfigs/update', methods=['POST'])
@token_required
@auth.require_roles('admin')
def update_basicconfig():
    if not request.is_json:
        return jsonify({'message': 'Request must be JSON.'}), 400

    data = request.json or {}
    module = str(data.get('module') or '').strip()
    config_doc = data.get('config')

    if not module:
        return jsonify({'message': 'module is required.'}), 400

    if not isinstance(config_doc, dict):
        return jsonify({'message': 'config must be a JSON object.'}), 400

    if '_id' in config_doc:
        config_doc = dict(config_doc)
        config_doc.pop('_id', None)

    if 'module' in config_doc and str(config_doc.get('module') or '').strip() != module:
        return jsonify({'message': 'config.module must match module.'}), 400

    config_doc['module'] = module

    snippet_flag = all_connects.ALLOW_CUSTOM_SNIPPET_KEY
    if snippet_flag in config_doc and not isinstance(config_doc[snippet_flag], bool):
        return jsonify({'message': f"{snippet_flag} must be true or false."}), 400

    try:
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_config"]
        basicconfigs_col = db["basicconfigs"]

        update_result = basicconfigs_col.update_one(
            {'module': module},
            {'$set': config_doc}
        )

        if update_result.matched_count == 0:
            mongo_client.close()
            return jsonify({'message': f"Configuration module '{module}' not found."}), 404

        updated_doc = basicconfigs_col.find_one({'module': module})

        def serialize_value(value):
            if isinstance(value, datetime):
                return value.isoformat()
            if isinstance(value, dict):
                return {k: serialize_value(v) for k, v in value.items()}
            if isinstance(value, list):
                return [serialize_value(v) for v in value]
            if hasattr(value, '__class__') and value.__class__.__name__ == 'ObjectId':
                return str(value)
            return value

        mongo_client.close()
        return jsonify({
            'message': 'Configuration updated successfully.',
            'config': serialize_value(updated_doc or config_doc)
        }), 200
    except Exception as e:
        return jsonify({'message': str(e)}), 500


@app.route('/api/configuration/mongo-init/status', methods=['GET'])
@endpoint_docs.endpoint_doc(
    summary='Get mongo init/reset workflow status',
    description='Returns effective mode, lock status, and startup workflow configuration.',
    auth_types=['session', 'api_key'],
    required_roles=['admin'],
    tags=['Configuration', 'RBAC'],
    responses={
        200: {'description': 'Workflow status returned'},
        403: {'description': 'Insufficient permissions'},
        500: {'description': 'Server error'}
    }
)
@token_required
@auth.require_roles('admin')
def get_mongo_init_status():
    try:
        status_payload = bootstrap.get_mongo_init_workflow_status()
        return jsonify(status_payload), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/configuration/mongo-init/trigger', methods=['POST'])
@endpoint_docs.endpoint_doc(
    summary='Trigger mongo init/reset workflow',
    description='Runs on-demand mongo initialization/reset based on mode and target init file.',
    auth_types=['session', 'api_key'],
    required_roles=['admin'],
    tags=['Configuration', 'RBAC'],
    request_body={
        'required': True,
        'properties': {
            'mode': {'type': 'string'},
            'init_file_path': {'type': 'string'}
        }
    },
    responses={
        200: {'description': 'Workflow completed'},
        400: {'description': 'Invalid request payload'},
        403: {'description': 'Insufficient permissions'},
        404: {'description': 'Init file not found'},
        409: {'description': 'Workflow skipped (lock not acquired)'},
        500: {'description': 'Server error'}
    }
)
@token_required
@auth.require_roles('admin')
def trigger_mongo_init_workflow_route():
    started_at = all_connects._utc_now()
    request_id = getattr(g, 'api_audit_request_id', None) or str(uuid4().hex)
    source_details = _get_request_source_details()

    if not request.is_json:
        return jsonify({'message': 'Request must be JSON.'}), 400

    data = request.json or {}
    mode = str(data.get('mode') or '').strip().lower()
    init_file_path = str(data.get('init_file_path') or '').strip() or None

    if mode not in ('init', 'reset'):
        return jsonify({'message': "mode must be either 'init' or 'reset'."}), 400

    try:
        result = bootstrap.trigger_mongo_init_workflow(mode=mode, init_file_path=init_file_path)
        status_text = str(result.get('status') or '').strip().lower()

        duration_ms = int((all_connects._utc_now() - started_at).total_seconds() * 1000)
        summary = f"Mongo init workflow '{mode}' {status_text or 'completed'}."
        _write_manual_platform_change_log(
            request_id=request_id,
            action='triggered',
            entity='mongo_init_workflow',
            entity_id=str(mode),
            summary=summary,
            details={
                'mode': mode,
                'init_file_path': init_file_path,
                'result': result,
            },
            status_code=200 if status_text != 'skipped' else 409,
            duration_ms=duration_ms,
            source_details=source_details,
        )

        if status_text == 'skipped' and str(result.get('reason') or '').strip().lower() == 'lock_not_acquired':
            return jsonify(result), 409
        return jsonify(result), 200
    except FileNotFoundError as e:
        duration_ms = int((all_connects._utc_now() - started_at).total_seconds() * 1000)
        _write_manual_platform_change_log(
            request_id=request_id,
            action='triggered',
            entity='mongo_init_workflow',
            entity_id=str(mode or ''),
            summary=f"Mongo init workflow '{mode or 'unknown'}' failed: init file not found.",
            details={
                'mode': mode,
                'init_file_path': init_file_path,
                'error': str(e),
            },
            status_code=404,
            duration_ms=duration_ms,
            source_details=source_details,
        )
        return jsonify({'status': 'error', 'message': str(e)}), 404
    except ValueError as e:
        duration_ms = int((all_connects._utc_now() - started_at).total_seconds() * 1000)
        _write_manual_platform_change_log(
            request_id=request_id,
            action='triggered',
            entity='mongo_init_workflow',
            entity_id=str(mode or ''),
            summary=f"Mongo init workflow trigger rejected: {str(e)}",
            details={
                'mode': mode,
                'init_file_path': init_file_path,
                'error': str(e),
            },
            status_code=400,
            duration_ms=duration_ms,
            source_details=source_details,
        )
        return jsonify({'status': 'error', 'message': str(e)}), 400
    except Exception as e:
        duration_ms = int((all_connects._utc_now() - started_at).total_seconds() * 1000)
        _write_manual_platform_change_log(
            request_id=request_id,
            action='triggered',
            entity='mongo_init_workflow',
            entity_id=str(mode or ''),
            summary=f"Mongo init workflow '{mode or 'unknown'}' failed.",
            details={
                'mode': mode,
                'init_file_path': init_file_path,
                'error': str(e),
            },
            status_code=500,
            duration_ms=duration_ms,
            source_details=source_details,
        )
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/configuration/output-categories', methods=['GET'])
@token_required
def get_output_categories():
    try:
        core_doc, loaded = _ensure_and_load_core_sso_config()
        if not loaded:
            return jsonify({'message': 'Failed to load configuration.', 'output_categories': []}), 500

        output_categories = core_doc.get('output_categories')
        if not isinstance(output_categories, list):
            output_categories = _default_output_categories()

        normalized_output_categories = []
        seen_output_categories = set()
        for entry in output_categories:
            normalized_entry = str(entry or '').strip()
            normalized_key = normalized_entry.lower()
            if not normalized_entry or normalized_key in seen_output_categories:
                continue
            seen_output_categories.add(normalized_key)
            normalized_output_categories.append(normalized_entry)

        return jsonify({'output_categories': normalized_output_categories}), 200
    except Exception as e:
        return jsonify({'message': str(e), 'output_categories': []}), 500


@app.route('/api/configuration/output-categories', methods=['POST'])
@token_required
def add_output_category():
    if not request.is_json:
        return jsonify({'message': 'Request must be JSON.'}), 400

    data = request.json or {}
    category = str(data.get('category') or '').strip()
    if not category:
        return jsonify({'message': 'category is required.'}), 400

    try:
        core_doc, loaded = _ensure_and_load_core_sso_config()
        if not loaded:
            return jsonify({'message': 'Failed to load configuration.'}), 500

        output_categories = core_doc.get('output_categories')
        if not isinstance(output_categories, list):
            output_categories = _default_output_categories()

        normalized_output_categories = []
        seen_output_categories = set()
        for entry in output_categories:
            normalized_entry = str(entry or '').strip()
            normalized_key = normalized_entry.lower()
            if not normalized_entry or normalized_key in seen_output_categories:
                continue
            seen_output_categories.add(normalized_key)
            normalized_output_categories.append(normalized_entry)

        if category.lower() in seen_output_categories:
            return jsonify({'message': 'Output category already exists.'}), 409

        normalized_output_categories.append(category)

        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client['byoint_core_config']
        basicconfigs_col = db['basicconfigs']
        basicconfigs_col.update_one(
            {'module': 'core'},
            {'$set': {'output_categories': normalized_output_categories}}
        )
        mongo_client.close()

        return jsonify({
            'message': 'Output category added successfully.',
            'category': category,
            'output_categories': normalized_output_categories
        }), 201
    except Exception as e:
        return jsonify({'message': str(e)}), 500


@app.route('/api/audit-logs', methods=['GET'])
@token_required
def get_audit_logs():
    try:
        limit = min(int(request.args.get('limit', 100)), 500)
        skip = int(request.args.get('skip', 0))
        method_filter = request.args.get('method', '').upper() or None
        path_filter = request.args.get('path', '').strip() or None
        user_filter = request.args.get('user', '').strip() or None
        status_filter = request.args.get('status_code', '').strip() or None

        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client['byoint_core_data']
        col = db['api_audit_logs']

        query = {}
        if method_filter:
            query['method'] = method_filter
        if path_filter:
            query['path'] = {'$regex': path_filter, '$options': 'i'}
        if user_filter:
            query['auth.user'] = {'$regex': user_filter, '$options': 'i'}
        if status_filter:
            query['status_code'] = int(status_filter)

        total = col.count_documents(query)
        cursor = col.find(query, {'_id': 0}).sort('created_at', -1).skip(skip).limit(limit)
        logs = []
        for doc in cursor:
            if 'created_at' in doc and hasattr(doc['created_at'], 'isoformat'):
                doc['created_at'] = doc['created_at'].isoformat()
            logs.append(doc)

        mongo_client.close()
        return jsonify({'logs': logs, 'total': total, 'limit': limit, 'skip': skip}), 200
    except Exception as e:
        return jsonify({'message': str(e)}), 500


@app.route('/api/platform-change-logs', methods=['GET'])
@token_required
def get_platform_change_logs():
    try:
        limit = min(int(request.args.get('limit', 100)), 500)
        skip = int(request.args.get('skip', 0))
        action = str(request.args.get('action', '') or '').strip().lower()
        source = str(request.args.get('source', '') or '').strip().lower()
        actor = str(request.args.get('actor', '') or '').strip()
        entity = str(request.args.get('entity', '') or '').strip().lower()
        search = str(request.args.get('search', '') or '').strip()

        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client['byoint_opslogs']
        col = db['platform_change_logs']

        query = {}
        if action:
            query['action'] = action
        if source:
            query['source'] = source
        if actor:
            query['actor'] = {'$regex': actor, '$options': 'i'}
        if entity:
            query['entity'] = entity
        if search:
            query['$or'] = [
                {'path': {'$regex': search, '$options': 'i'}},
                {'entity_id': {'$regex': search, '$options': 'i'}},
                {'actor': {'$regex': search, '$options': 'i'}},
            ]

        total = col.count_documents(query)
        cursor = col.find(query, {'_id': 0}).sort('created_at', -1).skip(skip).limit(limit)
        logs = []
        for doc in cursor:
            if 'created_at' in doc and hasattr(doc['created_at'], 'isoformat'):
                doc['created_at'] = doc['created_at'].isoformat()
            logs.append(doc)

        mongo_client.close()
        return jsonify({'logs': logs, 'total': total, 'limit': limit, 'skip': skip}), 200
    except Exception as e:
        return jsonify({'message': str(e)}), 500


@app.route('/api/configuration/workers', methods=['GET'])
@token_required
def get_worker_scaling_config():
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client['byoint_core_config']
        basicconfigs_col = db['basicconfigs']
        core_doc = basicconfigs_col.find_one({'module': 'core'}) or {}
        worker_scaling = _coerce_worker_scaling_config(core_doc.get('worker_scaling'))
        mongo_client.close()

        runtime_state = _get_runtime_worker_scaling_state()
        return jsonify({
            'worker_scaling': worker_scaling,
            'runtime_state': runtime_state,
            'scale_command': f'docker compose -f docker-compose.yml up -d --scale datapull_worker={worker_scaling.get("desired_worker_count", 1)}'
        }), 200
    except Exception as e:
        return jsonify({'message': str(e)}), 500


@app.route('/api/configuration/workers/update', methods=['POST'])
@token_required
def update_worker_scaling_config():
    if not request.is_json:
        return jsonify({'message': 'Request must be JSON.'}), 400

    data = request.json or {}
    raw_worker_scaling = data.get('worker_scaling')
    if not isinstance(raw_worker_scaling, dict):
        return jsonify({'message': 'worker_scaling must be a JSON object.'}), 400

    worker_scaling = _coerce_worker_scaling_config(raw_worker_scaling)

    try:
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client['byoint_core_config']
        basicconfigs_col = db['basicconfigs']

        update_result = basicconfigs_col.update_one(
            {'module': 'core'},
            {'$set': {'worker_scaling': worker_scaling}}
        )

        if update_result.matched_count == 0:
            mongo_client.close()
            return jsonify({'message': "Configuration module 'core' not found."}), 404

        mongo_client.close()
        return jsonify({
            'message': 'Worker scaling configuration updated successfully.',
            'worker_scaling': worker_scaling,
            'scale_command': f'docker compose -f docker-compose.yml up -d --scale datapull_worker={worker_scaling.get("desired_worker_count", 1)}'
        }), 200
    except Exception as e:
        return jsonify({'message': str(e)}), 500


@app.route('/api/configuration/workers/apply', methods=['POST'])
@token_required
def apply_worker_scaling():
    if not _env_bool('ENABLE_WORKER_SCALING_API', False):
        return jsonify({
            'message': 'Worker scaling API execution is disabled. Save config and run command from host shell.',
            'scale_command': 'docker compose -f docker-compose.yml up -d --scale datapull_worker=<desired_worker_count>'
        }), 400

    if not request.is_json:
        return jsonify({'message': 'Request must be JSON.'}), 400

    data = request.json or {}
    desired_worker_count = data.get('desired_worker_count')
    try:
        desired_worker_count = int(desired_worker_count)
    except Exception:
        return jsonify({'message': 'desired_worker_count must be an integer.'}), 400

    desired_worker_count = max(1, desired_worker_count)
    scale_result = _scale_compose_workers(desired_worker_count)
    status_code = 200 if scale_result.get('ok') else 500
    return jsonify(scale_result), status_code


@app.route('/api/configuration/rbac', methods=['GET'])
@endpoint_docs.endpoint_doc(
    summary='Get RBAC configuration',
    description='Returns RBAC definitions from basicconfigs module auth.',
    auth_types=['session', 'api_key'],
    required_roles=['admin'],
    tags=['Configuration', 'RBAC'],
    responses={
        200: {'description': 'RBAC config returned'},
        403: {'description': 'Insufficient permissions'},
        500: {'description': 'Server error'}
    }
)
@token_required
@auth.require_roles('admin')
def get_rbac_config_route():
    try:
        rbac = auth.get_rbac_config()
        return jsonify({'rbac': rbac}), 200
    except Exception as e:
        return jsonify({'message': str(e)}), 500


@app.route('/api/configuration/rbac/update', methods=['POST'])
@endpoint_docs.endpoint_doc(
    summary='Update RBAC configuration',
    description='Updates RBAC definitions under basicconfigs module auth.',
    auth_types=['session', 'api_key'],
    required_roles=['admin'],
    tags=['Configuration', 'RBAC'],
    request_body={
        'required': True,
        'properties': {
            'rbac': {'type': 'object'}
        }
    },
    responses={
        200: {'description': 'RBAC config updated'},
        400: {'description': 'Invalid payload'},
        403: {'description': 'Insufficient permissions'},
        500: {'description': 'Server error'}
    }
)
@token_required
@auth.require_roles('admin')
def update_rbac_config_route():
    if not request.is_json:
        return jsonify({'message': 'Request must be JSON.'}), 400

    data = request.json or {}
    raw_rbac = data.get('rbac')
    if not isinstance(raw_rbac, dict):
        return jsonify({'message': 'rbac must be a JSON object.'}), 400

    success, message, updated_rbac = auth.update_rbac_config(raw_rbac)
    if not success:
        status_code = 400 if 'must be' in str(message or '').lower() else 500
        return jsonify({'message': message}), status_code

    return jsonify({'message': message, 'rbac': updated_rbac}), 200


@app.route('/api/data_enrichments', methods=['GET'])
@token_required
def get_data_enrichments():
    try:
        enrichments, err = data_enrichments.list_data_enrichments()
        if err:
            return jsonify({'message': err, 'enrichments': []}), 500
        return jsonify({'enrichments': enrichments}), 200
    except Exception as e:
        return jsonify({'message': str(e), 'enrichments': []}), 500


@app.route('/api/data_enrichments/create', methods=['POST'])
@token_required
def create_data_enrichment():
    if not request.is_json:
        return jsonify({'message': 'Request must be JSON.'}), 400

    data = request.json or {}
    enrich_name = str(data.get('enrich_name') or '').strip()
    enrich_data_type = str(data.get('enrich_data_type') or '').strip()
    enrich_type = str(data.get('enrich_type') or 'builtin').strip().lower()
    enrich_mapping_function = str(data.get('enrich_mapping_function') or '').strip()
    snippet_code = str(data.get('snippet_code') or data.get('python_snippet') or '').strip()
    connector_config = data.get('connector_config')
    mcp_config = data.get('mcp_config')
    enrich_description = data.get('enrich_description')
    info = data.get('info')
    enrich_output_fields = data.get('enrich_output_fields')
    enabled = bool(data.get('enabled', False))

    if not enrich_name or not enrich_data_type:
        return jsonify({'message': 'enrich_name and enrich_data_type are required.'}), 400
    if enrich_type not in data_enrichments.ENRICH_TYPES:
        return jsonify({'message': data_enrichments.ENRICH_TYPES_ERROR}), 400
    if enrich_type == 'builtin' and not enrich_mapping_function:
        return jsonify({'message': 'enrich_mapping_function is required for builtin enrichments.'}), 400
    if enrich_type == 'custom' and not snippet_code:
        return jsonify({'message': 'snippet_code is required for custom enrichments.'}), 400
    if enrich_type == 'connector' and not isinstance(connector_config, dict):
        return jsonify({'message': 'connector_config is required for connector enrichments.'}), 400
    if enrich_type == 'mcp' and not isinstance(mcp_config, dict):
        return jsonify({'message': 'mcp_config is required for mcp enrichments.'}), 400

    enrichment_doc, err = data_enrichments.create_data_enrichment(
        enrich_name=enrich_name,
        enrich_data_type=enrich_data_type,
        enrich_type=enrich_type,
        enrich_description=enrich_description,
        enrich_mapping_function=enrich_mapping_function,
        snippet_code=snippet_code,
        connector_config=connector_config,
        enrich_output_fields=enrich_output_fields,
        enabled=enabled,
        info=info,
        mcp_config=mcp_config
    )

    if err:
        status = 409 if 'already exists' in str(err).lower() else 400
        return jsonify({'message': err}), status

    return jsonify({'message': 'Data enrichment created successfully.', 'enrichment': enrichment_doc}), 201


@app.route('/api/data_enrichments/update', methods=['POST'])
@token_required
def update_data_enrichment():
    if not request.is_json:
        return jsonify({'message': 'Request must be JSON.'}), 400

    data = request.json or {}
    enrich_name = str(data.get('enrich_name') or '').strip()
    if not enrich_name:
        return jsonify({'message': 'enrich_name is required.'}), 400

    updates = {}
    for field in ['enrich_data_type', 'enrich_type', 'enrich_description', 'info', 'enrich_mapping_function', 'enrich_output_fields', 'enabled', 'connector_config', 'mcp_config']:
        if field in data:
            updates[field] = data[field]
    if 'snippet_code' in data:
        updates['snippet_code'] = data.get('snippet_code')
    if 'python_snippet' in data:
        updates['python_snippet'] = data.get('python_snippet')

    enrichment_doc, err = data_enrichments.update_data_enrichment(enrich_name=enrich_name, updates=updates)
    if err:
        err_text = str(err).lower()
        if 'not found' in err_text:
            return jsonify({'message': err}), 404
        return jsonify({'message': err}), 400

    return jsonify({'message': 'Data enrichment updated successfully.', 'enrichment': enrichment_doc}), 200


@app.route('/api/data_enrichments/test-connector', methods=['POST'])
@token_required
def test_data_enrichment_connector():
    if not request.is_json:
        return jsonify({'message': 'Request must be JSON.'}), 400

    data = request.json or {}
    enrich_name = str(data.get('enrich_name') or '').strip()
    value = str(data.get('value') or '').strip()
    dtype = str(data.get('dtype') or data.get('type') or '').strip()
    connector_config = data.get('connector_config')
    enrich_output_fields = data.get('enrich_output_fields')

    if enrich_name and (connector_config is None or enrich_output_fields is None):
        # Allow testing from an existing enrichment definition.
        candidates = data_enrichments.get_enrichments(enabled_only=False, selected_enrichment_names=[enrich_name])
        selected = candidates[0] if isinstance(candidates, list) and candidates else None
        if not isinstance(selected, dict):
            return jsonify({'message': f'Enrichment not found: {enrich_name}'}), 404
        connector_config = selected.get('connector_config')
        enrich_output_fields = selected.get('enrich_output_fields')
        if not dtype:
            dtype = str(selected.get('enrich_data_type') or '').strip()

    if not value:
        return jsonify({'message': 'value is required.'}), 400
    if not isinstance(connector_config, dict):
        return jsonify({'message': 'connector_config is required and must be a JSON object.'}), 400
    if not isinstance(enrich_output_fields, list) or not enrich_output_fields:
        return jsonify({'message': 'enrich_output_fields must be a non-empty array.'}), 400

    preview, err = data_enrichments.test_connector_enrichment(
        value=value,
        dtype=dtype,
        connector_config=connector_config,
        enrich_output_fields=enrich_output_fields
    )
    if err:
        return jsonify({'message': err}), 400

    return jsonify({'message': 'Connector test executed successfully.', 'preview': preview}), 200


@app.route('/api/data_enrichments/test-mcp', methods=['POST'])
@token_required
def test_data_enrichment_mcp():
    if not request.is_json:
        return jsonify({'message': 'Request must be JSON.'}), 400

    data = request.json or {}
    value = str(data.get('value') or '').strip()
    dtype = str(data.get('dtype') or data.get('type') or '').strip()
    mcp_config = data.get('mcp_config')
    enrich_output_fields = data.get('enrich_output_fields')

    if not value:
        return jsonify({'message': 'value is required.'}), 400
    if not isinstance(mcp_config, dict):
        return jsonify({'message': 'mcp_config is required and must be a JSON object.'}), 400
    if not isinstance(enrich_output_fields, list) or not enrich_output_fields:
        return jsonify({'message': 'enrich_output_fields must be a non-empty array.'}), 400

    preview, err = data_enrichments.test_mcp_enrichment(
        value=value,
        dtype=dtype,
        mcp_config=mcp_config,
        enrich_output_fields=enrich_output_fields
    )
    if err:
        return jsonify({'message': err}), 400

    return jsonify({'message': 'MCP tool test executed successfully.', 'preview': preview}), 200


@app.route('/api/tags', methods=['GET'])
@token_required
def get_tags():
    try:
        mongo_client, mongo_connect_string = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_config"]
        tag_col = db["tags"]

        out = []
        for d in tag_col.find({}, {"_id": 0}).sort("name", 1):
            out.append({
                'tag': d.get('name'),
                'type': d.get('type'),
                'description': d.get('description'),
                'created_at': d.get('created_at').isoformat() if d.get('created_at') else None,
                'updated_at': d.get('updated_at').isoformat() if d.get('updated_at') else None
            })

        mongo_client.close()
        return jsonify({'tags': out}), 200
    except Exception as e:
        return jsonify({'message': str(e), 'tags': []}), 500


@app.route('/api/tags', methods=['POST'])
@token_required
def create_tag():
    if not request.is_json:
        return jsonify({'message': 'Request must be JSON.'}), 400

    data = request.json or {}
    tag_value = str(data.get('tag') or '').strip()
    tag_type = str(data.get('type') or '').strip() or 'custom'
    description = data.get('description')
    description = str(description).strip() if description is not None else None

    if not tag_value:
        return jsonify({'message': 'Tag is required.'}), 400

    try:
        mongo_client, mongo_connect_string = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_config"]
        tag_col = db["tags"]
        tag_col.create_index("name", unique=True)

        existing = tag_col.find_one({'name': tag_value})
        if existing:
            mongo_client.close()
            return jsonify({'message': 'Tag already exists.'}), 409

        now = datetime.utcnow()
        doc = {
            'name': tag_value,
            'type': tag_type,
            'description': description,
            'created_at': now,
            'updated_at': now
        }
        tag_col.insert_one(doc)
        mongo_client.close()

        return jsonify({
            'message': 'Tag created successfully.',
            'tag': {
                'tag': doc.get('name'),
                'type': doc.get('type'),
                'description': doc.get('description'),
                'created_at': now.isoformat(),
                'updated_at': now.isoformat()
            }
        }), 201
    except Exception as e:
        return jsonify({'message': str(e)}), 500


# Add GET endpoint for /api/datapull_templates


@app.route('/api/datapull_templates/test', methods=['POST'])
@token_required
def test_datapull_template_snippet():
    """Dry-run a custom Python snippet with provided field values, returning a result preview (no persistence)."""
    if not request.is_json:
        return jsonify({'message': 'Request must be JSON.'}), 400
    data = request.json or {}
    snippet_code = data.get('snippet_code') or data.get('python_snippet') or ''
    kwargs = data.get('kwargs') or {}
    preview_limit = min(int(data.get('preview_limit', 20)), 50)

    if not snippet_code.strip():
        return jsonify({'message': 'snippet_code is required.'}), 400
    if not isinstance(kwargs, dict):
        return jsonify({'message': 'kwargs must be an object of field name/value pairs.'}), 400

    try:
        preview, total, log_msg = _test_custom_template_snippet_dry_run(snippet_code, kwargs, preview_limit=preview_limit)
        if preview is None:
            return jsonify({'message': log_msg}), 400
        return jsonify({
            'preview': preview,
            'total': total,
            'log': log_msg,
            'truncated': total > preview_limit
        }), 200
    except Exception as e:
        return jsonify({'message': str(e)}), 500


# Endpoint to get datapull execution logs for a given source_name



@app.route('/api/indicator-logs', methods=['GET'])
@token_required
def get_indicator_logs():
    try:
        raw_page = request.args.get('page', '1')
        raw_limit = request.args.get('limit', '500')
        search = str(request.args.get('search') or '').strip().lower()

        try:
            page = int(raw_page)
        except Exception:
            page = 1
        try:
            limit = int(raw_limit)
        except Exception:
            limit = 500
        page = max(1, page)
        limit = max(1, min(limit, 2000))
        skip = (page - 1) * limit

        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client["byoint_opslogs"]
        logs_col = db["indicator_logs"]

        def serialize_value(value):
            if isinstance(value, datetime):
                return value.isoformat()
            if isinstance(value, dict):
                return {k: serialize_value(v) for k, v in value.items()}
            if isinstance(value, list):
                return [serialize_value(v) for v in value]
            if hasattr(value, '__class__') and value.__class__.__name__ == 'ObjectId':
                return str(value)
            return value

        def matches_search(entry):
            if not search:
                return True
            try:
                return search in str(serialize_value(entry)).lower()
            except Exception:
                return search in str(entry).lower()

        logs = []

        if search:
            matched_entries = []
            for entry in logs_col.find({}).sort([("event_time", -1), ("_id", -1)]):
                if matches_search(entry):
                    matched_entries.append(serialize_value(entry))

            total = len(matched_entries)
            logs = matched_entries[skip:skip + limit]
        else:
            total = logs_col.count_documents({})
            for entry in logs_col.find({}).sort([("event_time", -1), ("_id", -1)]).skip(skip).limit(limit):
                logs.append(serialize_value(entry))

        pages = (total + limit - 1) // limit if total else 0

        mongo_client.close()
        return jsonify({
            'logs': logs,
            'count': len(logs),
            'total': total,
            'page': page,
            'pages': pages,
            'limit': limit,
            'search': search
        }), 200
    except Exception as e:
        return jsonify({'message': str(e), 'logs': [], 'count': 0, 'total': 0, 'page': 1, 'pages': 0, 'limit': 0}), 500


    

@app.route('/')
def hello_msg():
    # Phase 7 cutover: root endpoint is health/info only; no in-process datapull execution.
    return jsonify({
        'status': 'ok',
        'service': 'byoint-core',
        'mode': 'queue-driven'
    }), 200

@app.route('/api/scheduled-jobs', methods=['GET'])
@token_required
def get_scheduled_jobs():
    """Get scheduled workflow metadata and APScheduler state (Phase 7 schedule-only view)."""
    try:
        from datetime import datetime
        
        mongo_client, _ = all_connects.connect_mongodb()
        core_db = mongo_client["byoint_core_data"]
        
        workflows = core_db["datapull_workflows"]
        
        # Get all scheduled workflows
        scheduled = list(workflows.find({'scheduled': True, 'schedule_enabled': True}))
        
        jobs = []
        for workflow in scheduled:
            source_name = workflow.get('source_name')
            interval_min = workflow.get('schedule_interval_min', 60)
            job_id = f"workflow_{source_name}"
            aps_job = scheduler.get_job(job_id)

            # APScheduler job info
            overdue = False
            if aps_job and aps_job.next_run_time:
                now = datetime.utcnow()
                # Convert next_run_time to naive UTC for comparison
                next_run_dt = aps_job.next_run_time
                if next_run_dt.tzinfo is not None:
                    next_run_dt = next_run_dt.astimezone().replace(tzinfo=None)
                overdue = now > next_run_dt
                next_run = next_run_dt.isoformat()
            else:
                next_run = None
            active = aps_job is not None and aps_job.next_run_time is not None
            paused = aps_job is not None and aps_job.next_run_time is None
            jobs.append({
                'source_name': source_name,
                'source_description': workflow.get('source_description'),
                'source_category': workflow.get('source_category'),
                'interval_minutes': interval_min,
                'next_run': next_run if next_run else 'N/A',
                'datapull_function': workflow.get('datapull_function'),
                'scheduler_active': active,
                'scheduler_paused': paused,
                'aps_job_id': aps_job.id if aps_job else 'N/A',
                'aps_job_status': (
                    'scheduled' if aps_job and aps_job.next_run_time else 'not scheduled'
                ) if aps_job else 'not found',
                'overdue': overdue
            })
        
        mongo_client.close()
        return jsonify({'jobs': jobs}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500




@app.route('/api/test/execute-workflow', methods=['POST'])
@token_required
def test_execute_workflow():
    """Manually trigger workflow execution — Phase 5: Queue-only, no fallback.
    
    All triggers now use standardized job envelope enqueuing.
    Returns: {status, code, job_id, source_name, trigger, trigger_source, requested_by, correlation_id}
    """
    try:
        source_name = None
        correlation_id = None
        
        if request.is_json:
            data = request.json or {}
            source_name = data.get('source_name')
            correlation_id = data.get('correlation_id')

        if not source_name:
            return jsonify({
                'status': 'error',
                'code': 'MISSING_SOURCE',
                'error': 'Missing source_name in request body'
            }), 400

        # Get caller identity for audit trail
        requested_by = str(getattr(g, 'current_user', '') or '').strip() or None

        # Phase 5: Standardized queue-only execution
        exec_result = enqueue_workflow_execution(
            source_name=source_name,
            trigger='manual',
            trigger_source='manual',
            requested_by=requested_by,
            correlation_id=correlation_id
        )

        if exec_result.get('status') == 'error':
            return jsonify(exec_result), 400 if exec_result.get('code') == 'MISSING_SOURCE' else 404

        # Successful queuing: return 202 (Accepted)
        return jsonify({
            'status': 'queued',
            'code': 'SUCCESS',
            'message': f"Workflow {source_name} queued for execution",
            'job_id': exec_result.get('job_id'),
            'source_name': source_name,
            'trigger': 'manual',
            'trigger_source': 'manual',
            'requested_by': requested_by,
            'correlation_id': correlation_id
        }), 202
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'code': 'INTERNAL_ERROR',
            'error': str(e)
        }), 500

if __name__ == '__main__':
    import os
    bootstrap_runtime()
    app.run(host='0.0.0.0', debug=False)





