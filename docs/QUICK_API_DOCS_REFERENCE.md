# API Documentation Quick Reference

## The Setup (Already Done ✅)

1. **Added to requirements.txt**: `flasgger`
2. **Created**: `byoint_core/endpoint_docs.py` — documentation helpers and decorators
3. **Updated**: `byoint_core/core.py` — Flasgger initialization, example endpoint docs
4. **Created**: `docs/byoint_core/API_DOCS_README.md` — comprehensive documentation
5. **Created**: `docs/byoint_core/ENDPOINT_DOCUMENTATION_GUIDE.py` — examples by endpoint type

## Access Documentation

### Interactive Swagger UI
```
https://localhost/api/docs       (Docker Compose, via nginx)
http://localhost:5000/api/docs   (only when running Flask directly; Compose doesn't publish 5000)
```
Try endpoints, view schemas, filter by tags

### OpenAPI JSON Spec
```bash
curl -k https://localhost/api/docs.json | jq .
```
For programmatic use, SDK generation, API gateways

## Add Docs to a New Endpoint (2 min)

### Step 1: Import at top of core.py (ALREADY DONE)
```python
import endpoint_docs
```

### Step 2: Add @endpoint_docs.endpoint_doc() decorator

```python
@app.route('/api/myendpoint', methods=['GET'])
@endpoint_docs.endpoint_doc(
    summary='What this does',
    auth_types=['session', 'api_key'],
    tags=['MyTag'],
    query_params={'param': {'type': 'string', 'description': '...'}},
    responses={200: {'description': 'Success'}, 400: {'description': 'Bad req'}}
)
@token_required
def my_endpoint():
    # existing code
```

That's it! Swagger UI auto-updates on browser refresh.

## Quick Examples

### GET with pagination
```python
@endpoint_docs.endpoint_doc(
    summary='List items',
    auth_types=['session', 'api_key'],
    query_params={**endpoint_docs.PAGINATION_PARAMS, 'search': {...}},
    responses={200: {'schema': endpoint_docs.PAGINATED_RESPONSE_SCHEMA}}
)
```

### POST with body
```python
@endpoint_docs.endpoint_doc(
    summary='Create item',
    request_body={
        'required': True,
        'schema': {
            'type': 'object',
            'properties': {'name': {'type': 'string'}}
        }
    },
    responses={201: {'description': 'Created'}, 400: {'description': 'Bad req'}}
)
```

### API-key only endpoint
```python
@endpoint_docs.endpoint_doc(
    summary='Admin operation',
    auth_types=['api_key'],  # Only API keys, not sessions
    note='Part of PUBLIC_API_ENDPOINTS if configured'
)
```

### Deprecated endpoint
```python
@endpoint_docs.endpoint_doc(
    summary='[DEPRECATED] Old endpoint',
    deprecated=True,
    note='Use /api/v2/endpoint instead'
)
```

## Common Response Schemas (Pre-built)

```python
endpoint_docs.SUCCESS_RESPONSE_SCHEMA      # {message, data}
endpoint_docs.ERROR_RESPONSE_SCHEMA        # {message, error}
endpoint_docs.PAGINATED_RESPONSE_SCHEMA    # {items, total, page, pages}
endpoint_docs.PAGINATION_PARAMS            # {page, limit}
endpoint_docs.SEARCH_PARAM                 # {search}
```

## Configuration

```bash
# Enable Swagger (default)
SWAGGER_DOCS_ENABLED=true

# Disable for production (if docs should be private)
SWAGGER_DOCS_ENABLED=false
```

## Python API (for automated docs/audits)

```python
from byoint_core import endpoint_docs

# Get all documented endpoints
all_endpoints = endpoint_docs.get_all_endpoint_docs()

# Filter by auth type
api_key_only = endpoint_docs.filter_endpoints_by_auth_type('api_key')

# Generate audit report
print(endpoint_docs.generate_endpoint_audit_summary())
```

## Validated Examples in This PR

The following endpoints already have documentation added:

✅ **GET /api/indicators** — List with pagination and filtering
✅ **POST /api/indicators/new** — Create/update with schema
✅ **GET /api/indicators/detail** — Get single indicator  
✅ **GET /api/datapull/queue-status** — API key only, operational endpoint

Browse to `http://localhost:5000/api/docs` to see them in Swagger UI.

## Next Steps

1. **Add docs to remaining endpoints** — Start with high-use endpoints
2. **Test with API gateway** — Export spec, import to Kong/AWS API Gateway
3. **Generate SDKs** — Use `openapi-generator` with the `/api/docs.json` spec
4. **CI/CD integration** — Check that all routes have `@endpoint_docs` in pull requests

## Common Mistakes

❌ **Forgetting @endpoint_docs decorator**
→ Endpoint won't appear in Swagger UI

❌ **Vague summaries** like "Get data" or "Do thing"  
→ Use specific action-oriented summaries: "List users with pagination", "Create indicator from feed"

❌ **Forgetting to set auth_types**
→ Default is `['any']` (both session and api_key OK); set to `['api_key']` if admin-only

❌ **Invalid JSON schema in request_body**
→ Must have `'type': 'object'` at top level

✅ **Use pre-built schemas/params** (`PAGINATION_PARAMS`, `SEARCH_PARAM`, etc.)
→ Keeps documentation consistent

## Swagger UI Pro Tips

- **Search** by endpoint name or tag at top of page
- **Try it out** button on each endpoint (if authenticated)
- **Model** button shows schema structure with examples
- **Download** button exports full OpenAPI YAML
- **Share** link persists expanded/collapsed state
