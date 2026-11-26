# API Documentation System

## Overview

The ByoInt API now includes **auto-generated OpenAPI 3.0 documentation** powered by [Flasgger](https://github.com/flasgger/flasgger).

- **Interactive UI**: Browse endpoints, view schemas, try-it-out capability at `/api/docs`
- **Machine-readable spec**: JSON OpenAPI spec at `/api/docs.json` (for tooling, SDKs, gateways)
- **Minimal overhead**: Just add `@endpoint_doc()` decorator to existing routes
- **Auth-aware**: Automatically reflects session vs API key requirements
- **PUBLIC_API_ENDPOINTS support**: Can mark endpoints as restricted in documentation

## Quick Start

### For End Users / API Consumers

1. **Browse documentation interactively**:
   - Open browser: `https://localhost/api/docs` (Docker Compose, via nginx)
   - Or, when running Flask directly: `http://localhost:5000/api/docs` (Compose doesn't publish port 5000)
   - Search, filter by tags, view schemas, try endpoints (with auth)

2. **Get JSON spec**:
   - `curl http://localhost:5000/api/docs.json | jq .`
   - Use in API testing tools, client generators, API gateways

3. **Filter by authentication type**:
   - UI shows which endpoints work with session vs API key
   - Spec includes auth requirements for each endpoint

### For Developers

1. **Add documentation to a route**:

```python
@app.route('/api/indicators', methods=['GET'])
@endpoint_doc(
    summary='List all indicators',
    auth_types=['session', 'api_key'],
    tags=['Indicators'],
    query_params={
        **endpoint_docs.PAGINATION_PARAMS,
        'search': {'type': 'string', 'description': 'Search term'}
    },
    responses={
        200: {'description': 'Indicators list', 'schema': {...}},
        400: {'description': 'Invalid parameters'}
    }
)
@token_required
def get_indicators():
    # existing implementation
```

2. **Reload documentation**:
   - Swagger UI auto-refreshes on page reload
   - Spec endpoint always reflects current Flask routes

3. **Validate coverage**:
   - Python: `endpoint_docs.get_all_endpoint_docs()`
   - Python: `endpoint_docs.generate_endpoint_audit_summary()`
   - JSON: GET `/api/docs.json` → parse and validate

## Decorator Reference

### `@endpoint_doc()` Parameters

```python
@endpoint_doc(
    summary='Short description',                    # Required: 1-3 word summary
    description='Longer description',               # Optional: full description
    auth_types=['session', 'api_key'],              # Optional: who can call this
    tags=['Category1', 'Category2'],                # Optional: for grouping
    query_params={                                  # Optional: GET query parameters
        'param_name': {
            'type': 'string|integer|boolean|number',
            'description': 'explanation',
            'required': True|False,
            'default': 'value'
        }
    },
    request_body={                                  # Optional: POST/PUT/PATCH body
        'required': True|False,
        'schema': {
            'type': 'object',
            'properties': {...},
            'required': ['field1', 'field2']
        }
    },
    responses={                                     # Optional: response specs
        200: {
            'description': 'Success message',
            'schema': {
                'type': 'object',
                'properties': {...}
            }
        },
        400: {'description': 'Bad request'},
        403: {'description': 'Forbidden'}
    },
    deprecated=False,                               # Optional: mark as deprecated
    note='Additional info'                          # Optional: extra note
)
```

### Authentication Types

- **`['session', 'api_key']`** (default): Accessible from browser sessions AND API keys
- **`['api_key']`**: Only accessible via API key authentication
- **`['session']`**: Only accessible from browser sessions (UI-only)
- **`['any']`**: Explicitly "either/or" (same as default)

### Common Parameters (Pre-built)

Reuse these from `endpoint_docs` module:

```python
# Pagination parameters for list endpoints
query_params={
    **endpoint_docs.PAGINATION_PARAMS,  # Adds: page, limit
    ...
}

# Search parameter for filterable endpoints
query_params={
    'search': endpoint_docs.SEARCH_PARAM,
    ...
}

# Common response schemas
responses={
    200: {
        'description': 'Success',
        'schema': endpoint_docs.SUCCESS_RESPONSE_SCHEMA
    },
    400: {
        'description': 'Bad request',
        'schema': endpoint_docs.ERROR_RESPONSE_SCHEMA
    }
}
```

## Examples

### Simple GET Endpoint

```python
@app.route('/api/indicators', methods=['GET'])
@endpoint_doc(
    summary='List indicators',
    auth_types=['session', 'api_key'],
    tags=['Indicators'],
    query_params={
        'page': {'type': 'integer', 'default': 1},
        'limit': {'type': 'integer', 'default': 50}
    },
    responses={
        200: {'description': 'Indicators retrieved'},
        500: {'description': 'Server error'}
    }
)
@token_required
def get_indicators():
    # existing code...
```

### POST Endpoint with JSON Body

```python
@app.route('/api/indicators/new', methods=['POST'])
@endpoint_doc(
    summary='Create indicator',
    auth_types=['session', 'api_key'],
    tags=['Indicators'],
    request_body={
        'required': True,
        'schema': {
            'type': 'object',
            'required': ['value', 'type', 'sources'],
            'properties': {
                'value': {'type': 'string'},
                'type': {'type': 'string', 'enum': ['ipv4', 'domain', 'url']},
                'sources': {'type': 'array', 'items': {'type': 'object'}}
            }
        }
    },
    responses={
        201: {'description': 'Indicator created'},
        400: {'description': 'Missing fields'},
        500: {'description': 'Server error'}
    }
)
@token_required
def add_indicator():
    # existing code...
```

### API-Key Restricted Endpoint

```python
@app.route('/api/admin/settings', methods=['GET'])
@endpoint_doc(
    summary='Get admin settings',
    auth_types=['api_key'],  # Only for API keys, not sessions
    tags=['Admin'],
    responses={
        200: {'description': 'Settings retrieved'},
        403: {'description': 'API key access denied'}
    },
    note='Requires PUBLIC_API_ENDPOINTS allowlist if configured'
)
@token_required
def get_admin_settings():
    # existing code...
```

### Deprecated Endpoint

```python
@app.route('/api/legacy/data', methods=['GET'])
@endpoint_doc(
    summary='[DEPRECATED] Get data',
    auth_types=['session'],
    deprecated=True,
    note='Use GET /api/v2/data instead (available since 2025-09)'
)
@token_required
def get_legacy_data():
    # existing code...
```

## Configuration

### Enable/Disable Swagger UI

```bash
# Enable (default)
SWAGGER_DOCS_ENABLED=true

# Disable (for production if docs are private)
SWAGGER_DOCS_ENABLED=false
```

When disabled:
- Route handlers still work normally
- `/api/docs` and `/api/docs.json` return 404
- No performance impact

### Environment Variables

```bash
SWAGGER_DOCS_ENABLED=true|false      # Default: true
```

## Accessing Documentation

### Web Interface

```
https://localhost/api/docs                  # Docker Compose, via nginx
http://localhost:5000/api/docs              # Flask run directly (not published by Compose)
```

Features:
- Search endpoints by name/tag
- Filter by method (GET, POST, etc.)
- View request/response schemas
- Try endpoints interactively (if authenticated)
- Download Swagger YAML

### Programmatic Access

#### Python

```python
# Get all documented endpoints
from byoint_core import endpoint_docs

all_docs = endpoint_docs.get_all_endpoint_docs()
for endpoint_key, meta in all_docs.items():
    print(f"{endpoint_key}: {meta['summary']}")

# Filter by auth type
api_key_endpoints = endpoint_docs.filter_endpoints_by_auth_type('api_key')

# Generate audit report
print(endpoint_docs.generate_endpoint_audit_summary())
```

#### Shell / cURL

```bash
# Get full OpenAPI spec
curl -s http://localhost:5000/api/docs.json | jq .

# Count endpoints by method
curl -s http://localhost:5000/api/docs.json | jq '.paths | keys | length'

# List all endpoints with tags
curl -s http://localhost:5000/api/docs.json | \
  jq '.paths | to_entries[] | {path: .key, methods: .value | keys}'

# Export spec for API gateway / SDK generation
curl http://localhost:5000/api/docs.json > openapi.json
```

## Authentication in Swagger UI

### Using Session (Browser)

1. Visit `https://localhost/api/docs`
2. You'll be logged in (browser auto-sends session cookie)
3. Click "Try it out" on any endpoint
4. Execute request

### Using API Key

1. If you need to test API key endpoints:
   - Get your API key from `/api/configuration/apikeys`
   - In Swagger UI, look for "Authorize" button (if configured)
   - Paste API key in authorization dialog
   - Then "Try it out" on endpoints

**Note**: Authorization button in Swagger UI is optional—configure in `core.py` if needed.

## PUBLIC_API_ENDPOINTS Integration

If you have `PUBLIC_API_ENDPOINTS` allowlist configured:

```python
@endpoint_doc(
    summary='List outputs',
    ...
    note='Available to API keys if listed in PUBLIC_API_ENDPOINTS'
)
```

In the documentation:
- Endpoints marked as `auth_types=['api_key']` show they may be restricted
- The note explains the allowlist behavior
- Actual enforcement happens in `auth.py` token_required decorator

To see current allowlist at runtime:
```bash
curl http://localhost:5000/api/debug/public-api-endpoints
```

## Best Practices

✅ **DO:**
- Add `@endpoint_doc` to all new routes
- Use consistent tags for grouping related endpoints (e.g., 'Indicators', 'Datapull')
- Include specific response codes (200, 201, 400, 403, 404, 500)
- Reuse common schemas (`PAGINATION_PARAMS`, `SEARCH_PARAM`, etc.)
- Set `auth_types` accurately to reflect actual requirements
- Use descriptive summaries (max ~10 words)
- Include units/constraints in descriptions: "Page number (1-indexed)", "Score 0-100"

❌ **DON'T:**
- Leave schema properties undocumented
- Use vague summaries like "Get data" or "Do thing"
- Mix multiple concerns in one endpoint
- Create `auth_types=['session']` when `['session', 'api_key']` is needed
- Forget to update docs when changing endpoint behavior

## Troubleshooting

### Swagger UI shows "404 Not Found"

**Cause**: Flasgger not initialized or `SWAGGER_DOCS_ENABLED=false`

**Solution**:
```bash
# Check if enabled
echo $SWAGGER_DOCS_ENABLED    # Should be "true"

# Restart Flask
python core.py
```

### Endpoints not appearing in Swagger UI

**Cause**: Missing `@endpoint_doc` decorator

**Solution**:
```python
# Required for endpoint to appear in docs
@app.route('/api/myendpoint', methods=['GET'])
@endpoint_doc(summary='My endpoint')  # Add this
@token_required
def my_endpoint():
```

### Schema validation errors

**Cause**: Invalid JSON schema in request_body or responses

**Solution**: Validate schema structure:
```python
# Valid schema
'schema': {
    'type': 'object',
    'properties': {
        'name': {'type': 'string'},
        'age': {'type': 'integer', 'minimum': 0}
    }
}

# Invalid: missing 'type'
'schema': {
    'properties': {  # ❌ Missing 'type' field
        'name': {'type': 'string'}
    }
}
```

### Authorization tests failing in Swagger UI

**Cause**: Session cookie not sent or API key invalid

**Solution**:
- If using browser: Make sure you're logged in (check `/api/whoami`)
- If using API key: Generate new key and verify it's included in header

## Next Steps

1. **Add documentation to critical endpoints** (start with the most-used ones)
2. **Set up automatic OpenAPI spec export** for API gateway or client generators
3. **Configure Swagger UI authorization** for easier interactive testing
4. **Add endpoint coverage to CI/CD** to ensure new routes are documented

See [ENDPOINT_DOCUMENTATION_GUIDE.py](./ENDPOINT_DOCUMENTATION_GUIDE.py) for detailed examples of documented endpoints.
