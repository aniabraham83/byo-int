"""
EXAMPLE: How to Add endpoint_doc Metadata to Existing Routes

This file shows before/after examples for adding comprehensive API documentation
to your existing Flask routes using the @endpoint_doc decorator.

The decorator is minimal—just add it before @token_required and documentation
is automatically extracted for OpenAPI generation.

---

EXAMPLE 1: Simple GET endpoint (indicators list)
"""

# BEFORE:
# @app.route('/api/indicators', methods=['GET'])
# @token_required
# def get_indicators():
#     try:
#         ...

# AFTER:
# @app.route('/api/indicators', methods=['GET'])
# @endpoint_doc(
#     summary='List all indicators',
#     description='Retrieve paginated list of indicators with optional search/filtering',
#     auth_types=['session', 'api_key'],
#     tags=['Indicators'],
#     query_params={
#         **endpoint_docs.PAGINATION_PARAMS,
#         'search': {
#             'type': 'string',
#             'description': 'Search indicators by value, dtype, type, or source name',
#             'required': False
#         },
#         'active': {
#             'type': 'boolean',
#             'description': 'Filter by active status (true/false)',
#             'required': False
#         },
#         'source': {
#             'type': 'string',
#             'description': 'Filter by source name',
#             'required': False
#         }
#     },
#     responses={
#         200: {
#             'description': 'Indicators retrieved successfully',
#             'schema': {
#                 'type': 'object',
#                 'properties': {
#                     'indicators': {
#                         'type': 'array',
#                         'items': {
#                             'type': 'object',
#                             'properties': {
#                                 'value': {'type': 'string'},
#                                 'type': {'type': 'string'},
#                                 'sources': {'type': 'array'},
#                                 'active': {'type': 'boolean'},
#                                 'max_br_score': {'type': 'number'}
#                             }
#                         }
#                     },
#                     'total': {'type': 'integer'},
#                     'page': {'type': 'integer'},
#                     'pages': {'type': 'integer'}
#                 }
#             }
#         },
#         400: {'description': 'Invalid pagination parameters'},
#         500: {'description': 'Server error'}
#     },
#     note='Supports both session and API key authentication'
# )
# @token_required
# def get_indicators():
#     ...


"""
---

EXAMPLE 2: POST endpoint with request body (add indicator)
"""

# BEFORE:
# @app.route('/api/indicators/new', methods=['POST'])
# @token_required
# def add_indicator():
#     if not request.is_json:
#         return jsonify({'message': 'Request must be JSON.'}), 400
#     data = request.json
#     value = data.get('value')
#     ...

# AFTER:
# @app.route('/api/indicators/new', methods=['POST'])
# @endpoint_doc(
#     summary='Create or update an indicator',
#     description='Add a new indicator or update existing one (upsert by value/type)',
#     auth_types=['session', 'api_key'],
#     tags=['Indicators'],
#     request_body={
#         'required': True,
#         'schema': {
#             'type': 'object',
#             'required': ['value', 'type', 'sources'],
#             'properties': {
#                 'value': {
#                     'type': 'string',
#                     'description': 'Indicator value (IP, domain, hash, etc.)'
#                 },
#                 'type': {
#                     'type': 'string',
#                     'enum': ['ipv4', 'ipv6', 'domain', 'url', 'file_hash', 'md5', 'sha1', 'sha256'],
#                     'description': 'Indicator type'
#                 },
#                 'sources': {
#                     'type': 'array',
#                     'items': {
#                         'type': 'object',
#                         'properties': {
#                             'source_name': {'type': 'string'},
#                             'br_score': {'type': 'number', 'minimum': 0, 'maximum': 1}
#                         }
#                     },
#                     'description': 'List of sources where indicator was seen'
#                 }
#             }
#         }
#     },
#     responses={
#         201: {
#             'description': 'Indicator created/updated successfully',
#             'schema': {
#                 'type': 'object',
#                 'properties': {
#                     'message': {'type': 'string'},
#                     'indicator': {'type': 'object'}
#                 }
#             }
#         },
#         400: {'description': 'Missing required fields'},
#         500: {'description': 'Server error'}
#     }
# )
# @token_required
# def add_indicator():
#     ...


"""
---

EXAMPLE 3: Restricted endpoint (API_KEY only or PUBLIC_API_ENDPOINTS restricted)
"""

# @app.route('/api/datapull/queue-status', methods=['GET'])
# @endpoint_doc(
#     summary='Get datapull queue status',
#     description='Check queue depth, worker status, and scheduler state',
#     auth_types=['api_key'],  # Only allowed for API key auth
#     tags=['Datapull', 'Queue'],
#     responses={
#         200: {
#             'description': 'Queue status retrieved',
#             'schema': {
#                 'type': 'object',
#                 'properties': {
#                     'queue_available': {'type': 'boolean'},
#                     'queue_depth': {'type': 'integer'},
#                     'worker_enabled': {'type': 'boolean'},
#                     'worker_running': {'type': 'boolean'},
#                     'worker_count_total': {'type': 'integer'},
#                     'worker_count_active': {'type': 'integer'}
#                 }
#             }
#         },
#         403: {'description': 'API key denied (endpoint not in PUBLIC_API_ENDPOINTS allowlist)'},
#         500: {'description': 'Server error'}
#     },
#     note='Part of PUBLIC_API_ENDPOINTS allowlist. If defined, only keys with this endpoint enabled can access.'
# )
# @token_required
# def get_datapull_queue_status():
#     ...


"""
---

EXAMPLE 4: Endpoint with complex filtering (data enrichments)
"""

# @app.route('/api/data_enrichments', methods=['GET'])
# @endpoint_doc(
#     summary='List data enrichments',
#     description='Get available data enrichment sources and their configurations',
#     auth_types=['session', 'api_key'],
#     tags=['Data Enrichments'],
#     query_params={
#         'enabled_only': {
#             'type': 'boolean',
#             'description': 'If true, only return enabled enrichments',
#             'default': False
#         }
#     },
#     responses={
#         200: {
#             'description': 'Enrichments list',
#             'schema': {
#                 'type': 'object',
#                 'properties': {
#                     'enrichments': {
#                         'type': 'array',
#                         'items': {
#                             'type': 'object',
#                             'properties': {
#                                 'name': {'type': 'string'},
#                                 'description': {'type': 'string'},
#                                 'enabled': {'type': 'boolean'},
#                                 'config': {'type': 'object'}
#                             }
#                         }
#                     }
#                 }
#             }
#         }
#     }
# )
# @token_required
# def get_data_enrichments():
#     ...


"""
---

EXAMPLE 5: Deprecated endpoint
"""

# @app.route('/api/legacy/indicators', methods=['GET'])
# @endpoint_doc(
#     summary='[DEPRECATED] List indicators (legacy format)',
#     auth_types=['session'],
#     tags=['Indicators', 'Legacy'],
#     deprecated=True,
#     note='Deprecated as of 2026-05. Use GET /api/indicators instead.',
#     responses={
#         200: {'description': 'Indicators in legacy format'},
#         410: {'description': 'Endpoint deprecated'}
#     }
# )
# @token_required
# def get_indicators_legacy():
#     ...


"""
---

INTEGRATION STEPS:

1. Add @endpoint_doc decorator to your routes (before @token_required)

2. Swagger UI will be available at:
   - Frontend: https://localhost/api/docs
   - Or direct: http://localhost:5000/api/docs

3. OpenAPI JSON spec available at:
   - http://localhost:5000/api/docs.json

4. To disable Swagger in production:
   - Set SWAGGER_DOCS_ENABLED=false environment variable

---

COMMON AUTH TYPE PATTERNS:

- auth_types=['session', 'api_key']
  → Available to both browser sessions and API keys (most endpoints)

- auth_types=['api_key']
  → Available ONLY to API key authentication (sensitive operations)
  → May be further restricted by PUBLIC_API_ENDPOINTS allowlist

- auth_types=['session']
  → Available ONLY to browser sessions (UI-only operations)

---

COMMON RESPONSE STATUS CODES:

- 200: Success (GET, PUT, PATCH with response body)
- 201: Created (POST that creates new resource)
- 204: No Content (successful but empty response)
- 400: Bad Request (validation error)
- 401: Unauthorized (auth required but not provided)
- 403: Forbidden (authenticated but not allowed for this endpoint)
- 404: Not Found (resource doesn't exist)
- 409: Conflict (duplicate resource, etc.)
- 500: Server Error

---

DEPLOYMENT NOTES:

- Swagger UI adds minimal overhead (~50KB)
- Disable SWAGGER_DOCS_ENABLED in production if docs shouldn't be public
- API spec endpoint (/api/docs.json) can be consumed by:
  - API gateway tools
  - Client code generators
  - API testing frameworks
  - Documentation aggregators

---

SCHEMA REUSE:

From endpoint_docs module:

  endpoint_docs.PAGINATION_PARAMS
  → Consistent page/limit params for list endpoints

  endpoint_docs.SEARCH_PARAM
  → Consistent search param for searchable endpoints

  endpoint_docs.SUCCESS_RESPONSE_SCHEMA
  → Standard {message, data} success response

  endpoint_docs.PAGINATED_RESPONSE_SCHEMA
  → Standard {items, total, page, pages} paginated response

Example:
  query_params={
      **endpoint_docs.PAGINATION_PARAMS,
      'search': endpoint_docs.SEARCH_PARAM,
      ...
  }

---
"""
