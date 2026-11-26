"""
Endpoint documentation and OpenAPI schema helpers for Flasgger integration.

This module provides decorators and utilities to standardize API documentation
across all endpoints, including authentication requirements, PUBLIC_API_ENDPOINTS
allowlist status, and schema definitions.

Usage:
    @app.route('/api/indicators', methods=['GET'])
    @endpoint_doc(
        summary='List all indicators',
        auth_types=['session', 'api_key'],
        tags=['Indicators'],
        query_params={
            'page': {'type': 'integer', 'default': 1},
            'limit': {'type': 'integer', 'default': 50},
        },
        responses={
            200: {
                'description': 'Indicators list',
                'schema': {
                    'type': 'object',
                    'properties': {
                        'indicators': {'type': 'array'},
                        'total': {'type': 'integer'},
                    }
                }
            }
        }
    )
    @token_required
    def get_indicators():
        ...
"""

import functools
import json
from typing import Dict, List, Optional, Any


# Global registry of endpoint documentation
_ENDPOINT_DOCS_REGISTRY = {}


def endpoint_doc(
    summary: str,
    description: str = None,
    auth_types: List[str] = None,
    required_roles: List[str] = None,
    tags: List[str] = None,
    query_params: Dict[str, Any] = None,
    request_body: Dict[str, Any] = None,
    responses: Dict[int, Dict[str, Any]] = None,
    deprecated: bool = False,
    note: str = None
):
    """
    Decorator to document API endpoints with OpenAPI-compatible metadata.
    
    Args:
        summary: Short description of what the endpoint does
        description: Longer description (optional)
        auth_types: List of auth types that work with this endpoint: ['session', 'api_key', 'any']
                   'session' = browser session only
                   'api_key' = API key auth only
                   'any' = both session and api key (default)
        required_roles: Optional list of required RBAC roles (e.g., ['admin'])
        tags: OpenAPI tags for grouping (e.g., ['Indicators', 'Search'])
        query_params: Dict of query parameters with their specs
                     e.g., {'page': {'type': 'integer', 'description': '...', 'default': 1}}
        request_body: Request body schema for POST/PUT/PATCH
        responses: Dict of status code -> response spec
                  e.g., {200: {'description': '...', 'schema': {...}},
                        400: {'description': 'Bad request'}}
        deprecated: Whether endpoint is deprecated
        note: Additional note (e.g., "Part of PUBLIC_API_ENDPOINTS if enabled")
    
    Returns:
        Decorator function that registers metadata and passes through to Flask
    """
    auth_types = auth_types or ['any']
    required_roles = [str(r).strip().lower() for r in (required_roles or []) if str(r).strip()]
    tags = tags or []
    query_params = query_params or {}
    responses = responses or {}
    description = description or summary
    
    def decorator(f):
        # Store metadata in function attribute for Flasgger extraction
        endpoint_info = {
            'summary': summary,
            'description': description,
            'auth_types': auth_types,
            'required_roles': required_roles,
            'tags': tags or [f.__name__],
            'query_params': query_params,
            'request_body': request_body,
            'responses': responses,
            'deprecated': deprecated,
            'note': note,
            'function_name': f.__name__,
        }
        
        f._endpoint_doc_metadata = endpoint_info
        
        # Also register globally for easy lookup/auditing
        _ENDPOINT_DOCS_REGISTRY[f'{f.__module__}.{f.__name__}'] = endpoint_info

        # Build Flasgger-compatible YAML docstring so Swagger UI picks it up.
        # Start with '---' so Flasgger parses the block as YAML.
        flasgger_spec = _build_flasgger_spec(endpoint_info)
        f.__doc__ = '---\n' + json.dumps(flasgger_spec, indent=2, sort_keys=True)
        
        return f
    
    return decorator


def _build_flasgger_spec(meta: Dict[str, Any]) -> Dict[str, Any]:
    """Build a Flasgger-compatible spec dict from endpoint_doc metadata."""
    auth_types = meta.get('auth_types', ['any'])
    if auth_types == ['api_key']:
        auth_note = 'Authentication: API key only'
    elif auth_types == ['session']:
        auth_note = 'Authentication: Session (browser) only'
    else:
        auth_note = 'Authentication: Session or API key'

    description = meta.get('description') or meta.get('summary', '')
    full_description = f"{description}\n\n{auth_note}"
    if meta.get('required_roles'):
        full_description += f"\n\nRequired Roles: {', '.join(meta.get('required_roles'))}"
    if meta.get('note'):
        full_description += f"\n\nNote: {meta.get('note')}"

    spec = {
        'summary': meta.get('summary', ''),
        'description': full_description,
        'tags': meta.get('tags', []),
        'responses': {
            str(code): {'description': info.get('description', '')}
            for code, info in (meta.get('responses') or {}).items()
        },
    }

    parameters = []
    for param_name, param_spec in (meta.get('query_params') or {}).items():
        p = {
            'name': param_name,
            'in': 'query',
            'type': param_spec.get('type', 'string'),
            'description': param_spec.get('description', ''),
            'required': param_spec.get('required', False),
        }
        if 'default' in param_spec:
            p['default'] = param_spec['default']
        parameters.append(p)

    request_body = meta.get('request_body')
    if request_body:
        props = request_body.get('properties', {})
        parameters.append({
            'name': 'body',
            'in': 'body',
            'required': bool(request_body.get('required')),
            'schema': {
                'type': 'object',
                'properties': {k: {'type': v.get('type', 'string')} for k, v in props.items()},
            }
        })

    if parameters:
        spec['parameters'] = parameters

    if meta.get('deprecated'):
        spec['deprecated'] = True

    return spec


def build_flasgger_doc(func, public_api_endpoints=None) -> Dict[str, Any]:
    """
    Build Flasgger-compatible docstring from endpoint_doc metadata.
    
    This converts the endpoint_doc decorator metadata into Flasgger format
    for automatic OpenAPI generation.
    
    Args:
        func: Flask route function with _endpoint_doc_metadata
        public_api_endpoints: List of allowed PUBLIC_API_ENDPOINTS rules (for status note)
    
    Returns:
        Dict ready to be inserted as docstring or Flasgger spec
    """
    if not hasattr(func, '_endpoint_doc_metadata'):
        return None
    
    meta = func._endpoint_doc_metadata
    auth_types = meta.get('auth_types', ['any'])
    required_roles = meta.get('required_roles', [])
    tags = meta.get('tags', [])
    
    # Build auth info for description
    auth_info = ', '.join(auth_types)
    if auth_types == ['api_key']:
        auth_note = "**Authentication:** API key only"
    elif auth_types == ['session']:
        auth_note = "**Authentication:** Session (browser) only"
    elif 'any' in auth_types:
        auth_note = "**Authentication:** Session or API key"
    else:
        auth_note = f"**Authentication:** {auth_info}"
    
    full_description = f"{meta.get('description', meta.get('summary', ''))}\n\n{auth_note}"
    if required_roles:
        full_description += f"\n\n**Required Roles:** {', '.join(required_roles)}"
    if meta.get('note'):
        full_description += f"\n\n*Note: {meta.get('note')}*"
    
    spec = {
        'summary': meta.get('summary'),
        'description': full_description,
        'tags': tags,
        'responses': meta.get('responses', {})
    }
    
    # Add parameters section
    parameters = []
    
    # Query parameters
    query_params = meta.get('query_params', {})
    for param_name, param_spec in query_params.items():
        param_def = {
            'name': param_name,
            'in': 'query',
            'type': param_spec.get('type', 'string'),
            'description': param_spec.get('description', ''),
            'required': param_spec.get('required', False),
        }
        if 'default' in param_spec:
            param_def['default'] = param_spec['default']
        parameters.append(param_def)
    
    # Request body
    request_body = meta.get('request_body')
    if request_body:
        param_def = {
            'name': 'body',
            'in': 'body',
            'required': request_body.get('required', True),
            'schema': request_body.get('schema', {})
        }
        parameters.append(param_def)
    
    if parameters:
        spec['parameters'] = parameters
    
    if meta.get('deprecated'):
        spec['deprecated'] = True
    
    return spec


def get_all_endpoint_docs(public_api_endpoints=None) -> Dict[str, Any]:
    """
    Get complete documentation registry for all endpoints.
    
    Useful for building custom docs pages or validating endpoint coverage.
    
    Args:
        public_api_endpoints: Optional list of allowed endpoints to mark in registry
    
    Returns:
        Dict mapping endpoint_key -> metadata
    """
    return dict(_ENDPOINT_DOCS_REGISTRY)


def filter_endpoints_by_auth_type(auth_type: str) -> Dict[str, Any]:
    """
    Get all endpoints that support a specific auth type.
    
    Args:
        auth_type: 'session', 'api_key', or 'any'
    
    Returns:
        Filtered registry
    """
    return {
        key: meta for key, meta in _ENDPOINT_DOCS_REGISTRY.items()
        if auth_type in meta.get('auth_types', ['any'])
    }


def generate_endpoint_audit_summary(public_api_endpoints=None) -> str:
    """
    Generate a text summary of all documented endpoints for audit purposes.
    
    Includes auth type, allowlist status, and basic schema info.
    
    Args:
        public_api_endpoints: Optional list of allowed endpoints
    
    Returns:
        Formatted text summary
    """
    public_api_endpoints = public_api_endpoints or []
    lines = []
    lines.append("=" * 80)
    lines.append("API ENDPOINT DOCUMENTATION AUDIT")
    lines.append("=" * 80)
    
    for endpoint_key in sorted(_ENDPOINT_DOCS_REGISTRY.keys()):
        meta = _ENDPOINT_DOCS_REGISTRY[endpoint_key]
        lines.append("")
        lines.append(f"Endpoint: {meta.get('function_name')}")
        lines.append(f"  Summary: {meta.get('summary')}")
        lines.append(f"  Auth Types: {', '.join(meta.get('auth_types', ['any']))}")
        if meta.get('required_roles'):
            lines.append(f"  Required Roles: {', '.join(meta.get('required_roles', []))}")
        lines.append(f"  Tags: {', '.join(meta.get('tags', []))}")
        
        if meta.get('deprecated'):
            lines.append("  ⚠️  DEPRECATED")
        
        if meta.get('note'):
            lines.append(f"  Note: {meta.get('note')}")
    
    lines.append("")
    lines.append("=" * 80)
    return "\n".join(lines)


# Common response schemas to reuse

SUCCESS_RESPONSE_SCHEMA = {
    'type': 'object',
    'properties': {
        'message': {'type': 'string'},
        'data': {'type': 'object'}
    }
}

ERROR_RESPONSE_SCHEMA = {
    'type': 'object',
    'properties': {
        'message': {'type': 'string'},
        'error': {'type': 'string'}
    }
}

PAGINATED_RESPONSE_SCHEMA = {
    'type': 'object',
    'properties': {
        'items': {'type': 'array'},
        'total': {'type': 'integer'},
        'page': {'type': 'integer'},
        'pages': {'type': 'integer'}
    }
}


# Common parameter definitions to reuse

PAGINATION_PARAMS = {
    'page': {
        'type': 'integer',
        'description': 'Page number (1-indexed)',
        'required': False,
        'default': 1
    },
    'limit': {
        'type': 'integer',
        'description': 'Items per page',
        'required': False,
        'default': 50
    }
}

SEARCH_PARAM = {
    'search': {
        'type': 'string',
        'description': 'Full-text search term',
        'required': False
    }
}
