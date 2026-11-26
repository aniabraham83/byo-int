<template>
  <div class="container mt-4 pb-5">
    <div class="d-flex justify-content-between align-items-center mb-4">
      <div>
        <div class="d-flex align-items-center gap-2 mb-1">
          <h2 class="mb-0">Data Enrichments</h2>
          <button
            type="button"
            class="btn btn-outline-secondary btn-sm info-button"
            @click="showPageInfo = true"
            aria-haspopup="dialog"
            title="What are data enrichments?"
          >i</button>
        </div>
        <p class="text-muted mb-0">View, create, and edit enrichment mappings from byoint_core_config.data_enrichments.</p>
      </div>
      <div class="d-flex gap-2">
        <button class="btn btn-success" @click="openCreateModal">
          <i class="me-2">+</i> New Enrichment
        </button>
        <button class="btn btn-primary" @click="fetchEnrichments" :disabled="loading">
          <span v-if="loading" class="spinner-border spinner-border-sm me-2"></span>
          Refresh
        </button>
      </div>
    </div>

    <div v-if="showPageInfo" class="modal-overlay" @click.self="showPageInfo = false">
      <div class="modal-content" style="max-width: 620px;" role="dialog" aria-modal="true" aria-labelledby="page-info-title">
        <div class="modal-header">
          <h5 id="page-info-title" class="modal-title">What are data enrichments?</h5>
          <button type="button" class="btn-close" aria-label="Close" @click="showPageInfo = false"></button>
        </div>
        <div class="modal-body small">
          <p class="mb-2">
            Enrichments add context to indicators after they are pulled in, for example the country or network type of an IP address.
            Results are stored on the indicator under <code>data-enrichment.&lt;field&gt;</code> with an updated timestamp.
          </p>
          <div class="fw-semibold mb-1">When they run</div>
          <ul class="mb-2 ps-3">
            <li>An enrichment runs only if it is <strong>Enabled</strong> and selected on a datapull workflow.</li>
            <li>It applies only to indicators whose type matches its <strong>Data Type</strong> (e.g. <code>ipv4</code>, <code>domain</code>).</li>
            <li>At least one <strong>Output Field</strong> is required; that's the name the result is saved under.</li>
          </ul>
          <div class="fw-semibold mb-1">Enrich types</div>
          <ul class="mb-0 ps-3">
            <li><strong>Custom</strong>: runs your own Python snippet (limited to <code>requests</code>, <code>datetime</code>, <code>json</code>, <code>re</code>).</li>
            <li><strong>Connector</strong>: calls an external HTTP API per indicator using <code v-pre>{{value}}</code>/<code v-pre>{{type}}</code> placeholders, with credentials from Secrets, and maps response paths to output fields. A <strong>Database Query</strong> connector instead runs a read-only lookup (PostgreSQL, MySQL, SQL Server, Oracle, or MongoDB) with the indicator bound as a query parameter.</li>
            <li><strong>MCP Tool</strong>: calls a tool on an MCP server (Streamable HTTP) per indicator, with arguments built from <code v-pre>{{value}}</code>/<code v-pre>{{type}}</code>, and maps paths in the tool result to output fields.</li>
          </ul>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" @click="showPageInfo = false">Close</button>
        </div>
      </div>
    </div>

    <div v-if="rowInfoItem" class="modal-overlay" @click.self="rowInfoItem = null">
      <div class="modal-content" style="max-width: 560px;" role="dialog" aria-modal="true" aria-labelledby="row-info-title">
        <div class="modal-header">
          <h5 id="row-info-title" class="modal-title">About {{ rowInfoItem.enrich_name }}</h5>
          <button type="button" class="btn-close" aria-label="Close" @click="rowInfoItem = null"></button>
        </div>
        <div class="modal-body small info-row">{{ rowInfoItem.info }}</div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" @click="rowInfoItem = null">Close</button>
        </div>
      </div>
    </div>

    <div v-if="message" :class="['alert', messageType === 'error' ? 'alert-danger' : 'alert-success']">
      {{ message }}
    </div>

    <div v-if="loading" class="mt-3">
      <div class="spinner-border text-primary" role="status">
        <span class="visually-hidden">Loading...</span>
      </div>
    </div>

    <div v-else-if="error" class="alert alert-danger">{{ error }}</div>

    <div v-else>
      <div v-if="enrichments.length === 0" class="alert alert-info">No data enrichments found.</div>
      <div v-else class="table-responsive">
        <table class="table table-striped table-hover align-middle">
          <thead class="table-light">
            <tr>
              <th>Name</th>
              <th>Data Type</th>
              <th>Enrich Type</th>
              <th>Function</th>
              <th>Output Fields</th>
              <th>Enabled</th>
              <th>Updated</th>
              <th>Edit</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="item in enrichments" :key="item.enrich_name">
            <tr>
              <td>
                <div class="d-flex align-items-center gap-2">
                  <strong>{{ item.enrich_name }}</strong>
                  <button
                    v-if="item.info"
                    type="button"
                    class="btn btn-outline-secondary btn-sm info-button"
                    @click="rowInfoItem = item"
                    aria-haspopup="dialog"
                    :title="`About ${item.enrich_name}`"
                  >i</button>
                </div>
              </td>
              <td>{{ item.enrich_data_type || '-' }}</td>
              <td>{{ item.enrich_type || '-' }}</td>
              <td v-if="item.enrich_type === 'connector'"><code>{{ item.connector_config?.provider_kind === 'db' ? 'db: ' + (item.connector_config?.request_template?.db_engine || '?') : (item.connector_config?.provider_kind || '-') }}</code></td>
              <td v-else-if="item.enrich_type === 'mcp'"><code>{{ item.mcp_config?.tool_name || '-' }}</code></td>
              <td v-else><code>{{ item.enrich_mapping_function || '-' }}</code></td>
              <td>{{ formatOutputFields(item.enrich_output_fields) }}</td>
              <td>
                <span v-if="item.enabled" class="badge bg-success">Yes</span>
                <span v-else class="badge bg-secondary">No</span>
              </td>
              <td>{{ formatDate(item.updated_at) }}</td>
              <td>
                <button class="btn btn-sm btn-warning" @click="openEditModal(item)">Edit</button>
              </td>
            </tr>
            </template>
          </tbody>
        </table>
      </div>
    </div>

    <div v-if="showCreateModal" class="modal-overlay" @click.self="closeCreateModal">
      <div class="modal-content" style="max-width: 620px;">
        <div class="modal-header">
          <h5 class="modal-title">Create Data Enrichment</h5>
          <button type="button" class="btn-close" @click="closeCreateModal"></button>
        </div>
        <div class="modal-body">
          <form @submit.prevent="submitCreateEnrichment">
            <div class="mb-3">
              <label class="form-label">Enrichment Name</label>
              <input v-model.trim="createForm.enrich_name" type="text" class="form-control" required>
            </div>
            <div class="mb-3">
              <label class="form-label">Data Type</label>
              <select v-model="createForm.enrich_data_type" class="form-select" required>
                <option value="">-- Select Data Type --</option>
                <option v-for="dtype in dataTypes" :key="dtype" :value="dtype">{{ dtype }}</option>
              </select>
            </div>
            <div class="mb-3">
              <label class="form-label">Enrichment Type</label>
              <select v-model="createForm.enrich_type" class="form-select" required>
                <option value="custom">Custom</option>
                <option value="connector">Connector (API/DB)</option>
                <option value="mcp">MCP Tool</option>
              </select>
            </div>
            <div v-if="createForm.enrich_type === 'mcp'" class="mb-3">
              <div class="card bg-light">
                <div class="card-body">
                  <h6 class="card-title">MCP Tool Configuration</h6>
                  <div class="mb-3">
                    <label class="form-label">MCP Server URL</label>
                    <input v-model.trim="createForm.mcp_url" type="text" class="form-control font-monospace" placeholder="https://mcp.example.com/mcp" required>
                    <div class="form-text">Streamable HTTP endpoint of the MCP server.</div>
                  </div>
                  <div class="mb-3">
                    <label class="form-label">Tool Name</label>
                    <input v-model.trim="createForm.mcp_tool_name" type="text" class="form-control font-monospace" placeholder="e.g. lookup_ip" required>
                  </div>
                  <div class="mb-3">
                    <label class="form-label">Tool Arguments (JSON)</label>
                    <textarea v-model="createForm.mcp_tool_arguments_text" class="form-control font-monospace" rows="4" placeholder='{"ip": "{{value}}"}'></textarea>
                    <div class="form-text">Use <code v-pre>{{value}}</code> and <code v-pre>{{type}}</code> as placeholders for the indicator. Supports <code v-pre>{{secret:name}}</code>.</div>
                  </div>
                  <div class="mb-3">
                    <label class="form-label">Bearer Token Secret Ref</label>
                    <select v-model="createForm.mcp_auth_secret_ref" class="form-select">
                      <option value="">-- None --</option>
                      <option v-for="s in secrets" :key="s.secret_ref" :value="s.secret_ref">{{ s.name ? s.name + ' (' + s.secret_ref + ')' : s.secret_ref }}</option>
                    </select>
                    <div class="form-text">Optional. Sent as <code>Authorization: Bearer</code> header.</div>
                  </div>
                  <div class="mb-3">
                    <div class="d-flex justify-content-between align-items-center mb-2">
                      <label class="form-label mb-0">Response Mapping</label>
                      <button type="button" class="btn btn-outline-secondary btn-sm" @click="createForm.mcp_response_rows.push({ field: '', path: '' })">+ Add Field</button>
                    </div>
                    <div class="form-text mb-2">Optional. Map output fields to paths in the tool result (<code>structuredContent</code>, or JSON text content). Unmapped output fields receive the whole result.</div>
                    <div v-for="(row, idx) in createForm.mcp_response_rows" :key="idx" class="d-flex gap-2 mb-2 align-items-center">
                      <input v-model.trim="row.field" type="text" class="form-control" placeholder="Output field (e.g. country)" style="flex:1">
                      <span class="text-muted">→</span>
                      <input v-model.trim="row.path" type="text" class="form-control font-monospace" placeholder="$.country" style="flex:2">
                      <button type="button" class="btn btn-outline-danger btn-sm px-2" @click="createForm.mcp_response_rows.splice(idx, 1)" :disabled="createForm.mcp_response_rows.length === 1">×</button>
                    </div>
                  </div>
                  <div class="row">
                    <div class="col-md-6 mb-3">
                      <label class="form-label">Timeout (seconds)</label>
                      <input v-model.number="createForm.mcp_timeout_seconds" type="number" min="1" max="120" class="form-control" required>
                    </div>
                    <div class="col-md-6 mb-3">
                      <label class="form-label">Retry Count</label>
                      <input v-model.number="createForm.mcp_retry_count" type="number" min="0" max="5" class="form-control" required>
                    </div>
                  </div>
                  <div class="mb-3 form-check">
                    <input id="createMcpVerifySsl" v-model="createForm.mcp_verify_ssl" type="checkbox" class="form-check-input">
                    <label class="form-check-label" for="createMcpVerifySsl">Verify SSL certificate</label>
                  </div>
                  <div class="mb-3 d-flex gap-2 align-items-center">
                    <input v-model.trim="testSampleValue" type="text" class="form-control form-control-sm" style="max-width: 220px;" :placeholder="defaultSampleValue(createForm.enrich_data_type)" title="Indicator value to test with">
                    <button type="button" class="btn btn-outline-primary btn-sm text-nowrap" @click="testMcpPreview('create')" :disabled="testingConnector">
                      <span v-if="testingConnector" class="spinner-border spinner-border-sm me-2"></span>
                      {{ testingConnector ? 'Testing...' : 'Test with Sample Value' }}
                    </button>
                  </div>
                  <div v-if="testConnectorResult" class="alert" :class="testConnectorResult.error ? 'alert-warning' : 'alert-info'">
                    <h6 v-if="!testConnectorResult.error" class="mb-2">Test Result Preview:</h6>
                    <h6 v-else class="mb-2">Test Error:</h6>
                    <pre class="text-break">{{ JSON.stringify(testConnectorResult, null, 2) }}</pre>
                  </div>
                </div>
              </div>
            </div>
            <div class="mb-3" v-if="createForm.enrich_type === 'builtin'">
              <label class="form-label">Mapping Function</label>
              <input v-model.trim="createForm.enrich_mapping_function" type="text" class="form-control" placeholder="e.g. ipv4_find_networktype" :required="createForm.enrich_type === 'builtin'">
            </div>
            <div class="mb-3" v-else-if="createForm.enrich_type === 'custom'">
              <label class="form-label">Python Snippet</label>
              <textarea
                v-model="createForm.snippet_code"
                class="form-control"
                rows="8"
                placeholder="Set result = ... using value, indicator, and enrichment; use a dict for multi-output"
                :required="createForm.enrich_type === 'custom'"
              ></textarea>
              <div class="form-text">Custom snippet must set <code>result</code>. Use a scalar for one output field or a dict keyed by output field names for multi-output. Available variables: <code>value</code>, <code>indicator</code>, and <code>enrichment</code>.</div>
            </div>
            <div v-else-if="createForm.enrich_type === 'connector'" class="mb-3">
              <div class="card bg-light">
                <div class="card-body">
                  <h6 class="card-title">Connector Configuration</h6>
                  <div class="mb-3">
                    <label class="form-label">Provider Kind</label>
                    <select v-model="createForm.connector_config.provider_kind" class="form-select" required>
                      <option value="">-- Select Provider --</option>
                      <option value="http">HTTP API</option>
                      <option value="db">Database Query</option>
                    </select>
                  </div>
                  <div v-if="createForm.connector_config.provider_kind === 'db'" class="mb-3">
                    <div class="card bg-light p-3">
                      <h6 class="card-subtitle mb-3">Database Query Configuration</h6>
                      <div class="row">
                        <div class="col-md-6 mb-3">
                          <label class="form-label">Engine</label>
                          <select v-model="createForm.db_engine" class="form-select" required>
                            <option v-for="(label, key) in dbEngines" :key="key" :value="key">{{ label }}</option>
                          </select>
                        </div>
                        <div class="col-md-6 mb-3">
                          <label class="form-label">Result</label>
                          <select v-model="createForm.db_result_mode" class="form-select">
                            <option value="first_row">First row (object)</option>
                            <option value="all_rows">All rows (array)</option>
                          </select>
                        </div>
                      </div>
                      <div class="row">
                        <div class="col-md-8 mb-3">
                          <label class="form-label">Host</label>
                          <input v-model.trim="createForm.db_host" type="text" class="form-control" placeholder="db.internal.example.com" required>
                        </div>
                        <div class="col-md-4 mb-3">
                          <label class="form-label">Port</label>
                          <input v-model.number="createForm.db_port" type="number" min="1" max="65535" class="form-control" :placeholder="String(dbDefaultPorts[createForm.db_engine] || '')">
                        </div>
                      </div>
                      <div class="row">
                        <div :class="createForm.db_engine === 'mongodb' ? 'col-md-6 mb-3' : 'col-12 mb-3'">
                          <label class="form-label">{{ createForm.db_engine === 'oracle' ? 'Service Name' : 'Database' }}</label>
                          <input v-model.trim="createForm.db_name" type="text" class="form-control" required>
                        </div>
                        <div v-if="createForm.db_engine === 'mongodb'" class="col-md-6 mb-3">
                          <label class="form-label">Collection</label>
                          <input v-model.trim="createForm.db_collection" type="text" class="form-control" required>
                        </div>
                      </div>
                      <div class="row">
                        <div class="col-md-6 mb-3">
                          <label class="form-label">Username</label>
                          <input v-model.trim="createForm.db_user" type="text" class="form-control" required>
                        </div>
                        <div class="col-md-6 mb-3">
                          <label class="form-label">Password Secret Ref</label>
                          <select v-model="createForm.db_password_secret_ref" class="form-select" required>
                            <option value="">-- Select Secret --</option>
                            <option v-for="s in secrets" :key="s.secret_ref" :value="s.secret_ref">{{ s.name ? s.name + ' (' + s.secret_ref + ')' : s.secret_ref }}</option>
                          </select>
                          <div v-if="secrets.length === 0" class="form-text text-warning">No active secrets found. Create one in the Secrets page first.</div>
                        </div>
                      </div>
                      <div v-if="createForm.db_engine === 'mongodb'" class="mb-3">
                        <label class="form-label">Auth Source</label>
                        <input v-model.trim="createForm.db_auth_source" type="text" class="form-control" placeholder="Defaults to the database name">
                      </div>
                      <div class="mb-3">
                        <label class="form-label">{{ createForm.db_engine === 'mongodb' ? 'Query (JSON filter or aggregation pipeline)' : 'SQL Query' }}</label>
                        <textarea v-model="createForm.db_query" class="form-control font-monospace" rows="4" :placeholder="dbQueryPlaceholder(createForm.db_engine)" required></textarea>
                        <div v-if="createForm.db_engine === 'mongodb'" class="form-text">Use <code v-pre>"{{value}}"</code> and <code v-pre>"{{type}}"</code> inside JSON string values. A JSON array runs as an aggregation pipeline.</div>
                        <div v-else-if="createForm.db_engine === 'oracle'" class="form-text">Bind the indicator with <code>:value</code> and <code>:type</code>. Values are sent as bound parameters, never spliced into the SQL.</div>
                        <div v-else class="form-text">Bind the indicator with <code>%(value)s</code> and <code>%(type)s</code>; write a literal <code>%</code> as <code>%%</code>. Values are sent as bound parameters, never spliced into the SQL.</div>
                      </div>
                      <div v-if="createForm.db_result_mode === 'all_rows'" class="mb-3">
                        <label class="form-label">Row Limit</label>
                        <input v-model.number="createForm.db_row_limit" type="number" min="1" max="1000" class="form-control">
                      </div>
                      <div class="form-text">Use a read-only database account. The query runs once per indicator and is never committed.</div>
                    </div>
                  </div>
                  <div v-if="createForm.connector_config.provider_kind === 'http'" class="mb-3">
                    <div class="card bg-light p-3">
                      <h6 class="card-subtitle mb-3">HTTP Request Configuration</h6>
                      
                      <div class="mb-3">
                        <label class="form-label">API URL</label>
                        <input v-model.trim="createForm.connector_url" type="text" class="form-control font-monospace" placeholder="https://api.example.com/lookup?q={{value}}" required>
                        <div class="form-text">Use <code v-pre>{{value}}</code> and <code v-pre>{{type}}</code> as placeholders. Supports <code v-pre>{{secret:name}}</code> for query params.</div>
                      </div>
                      
                      <div class="row">
                        <div class="col-md-6 mb-3">
                          <label class="form-label">HTTP Method</label>
                          <select v-model="createForm.connector_method" class="form-select" required>
                            <option value="GET">GET</option>
                            <option value="POST">POST</option>
                            <option value="PUT">PUT</option>
                            <option value="PATCH">PATCH</option>
                            <option value="DELETE">DELETE</option>
                          </select>
                        </div>
                        <div class="col-md-6 mb-3">
                          <label class="form-label">Authentication Type</label>
                          <select v-model="createForm.connector_auth_type" class="form-select">
                            <option value="none">None</option>
                            <option value="api_key">API Key Header</option>
                            <option value="api_with_bearertoken">Bearer Token</option>
                            <option value="api_basicauth">Basic Auth</option>
                          </select>
                        </div>
                      </div>
                      
                      <div v-if="createForm.connector_auth_type === 'api_basicauth'" class="mb-3">
                        <div class="row">
                          <div class="col-md-6 mb-2">
                            <label class="form-label">Username</label>
                            <input v-model.trim="createForm.connector_auth_basic_username" type="text" class="form-control" placeholder="e.g. admin">
                          </div>
                          <div class="col-md-6 mb-2">
                            <label class="form-label">Password Secret Ref</label>
                            <select v-model="createForm.connector_auth_secret_name" class="form-select">
                              <option value="">-- Select Secret --</option>
                              <option v-for="s in secrets" :key="s.secret_ref" :value="s.secret_ref">{{ s.name ? s.name + ' (' + s.secret_ref + ')' : s.secret_ref }}</option>
                            </select>
                            <div v-if="secrets.length === 0" class="form-text text-warning">No active secrets found. Create one in the Secrets page first.</div>
                          </div>
                        </div>
                      </div>
                      <div v-else-if="createForm.connector_auth_type !== 'none'" class="mb-3">
                        <label class="form-label">Secret Ref</label>
                        <select v-model="createForm.connector_auth_secret_name" class="form-select">
                          <option value="">-- Select Secret --</option>
                          <option v-for="s in secrets" :key="s.secret_ref" :value="s.secret_ref">{{ s.name ? s.name + ' (' + s.secret_ref + ')' : s.secret_ref }}</option>
                        </select>
                        <div v-if="secrets.length === 0" class="form-text text-warning">No active secrets found. Create one in the Secrets page first.</div>
                        <div class="form-text">Secret value resolved at runtime. Sent as <span v-if="createForm.connector_auth_type === 'api_key'"><code>X-API-Key</code> header</span><span v-else><code>Authorization: Bearer</code> header</span>.</div>
                      </div>
                      
                      <div v-if="createForm.connector_method !== 'GET'" class="mb-3">
                        <label class="form-label">Request Body (JSON)</label>
                        <textarea v-model="createForm.connector_body_text" class="form-control font-monospace" rows="6" placeholder='{"search": "{{value}}", "type": "{{type}}"}'></textarea>
                        <div class="form-text">Optional. Leave empty for GET requests. Supports <code v-pre>{{value}}</code> and <code v-pre>{{type}}</code> placeholders.</div>
                      </div>
                    </div>
                  </div>
                  <div class="mb-3">
                    <div class="d-flex justify-content-between align-items-center mb-2">
                        <div class="d-flex align-items-center gap-2">
                          <label class="form-label mb-0">Response Mapping</label>
                          <button
                            type="button"
                            class="btn btn-outline-secondary btn-sm info-button"
                            @click="showCreateResponseMappingHelp = !showCreateResponseMappingHelp"
                            :aria-expanded="showCreateResponseMappingHelp ? 'true' : 'false'"
                            title="Show response mapping examples"
                          >i</button>
                        </div>
                        <button type="button" class="btn btn-outline-secondary btn-sm" @click="createForm.connector_response_rows.push({ field: '', path: '' })">+ Add Field</button>
                    </div>
                    <div class="form-text mb-2">Map output field names to paths in the API response or DB result (e.g. <code>$.country</code> for a column, <code>$.0.country</code> in all-rows mode).</div>
                      <div v-if="showCreateResponseMappingHelp" class="alert alert-light border small mb-3">
                        <div class="fw-semibold mb-2">Common path patterns</div>
                        <div class="mb-1"><code>$.country</code> for <code>{"country":"US"}</code></div>
                        <div class="mb-1"><code>$.asn.name</code> for nested objects like <code>{"asn":{"name":"ExampleNet"}}</code></div>
                        <div class="mb-1"><code>$.results.0.score</code> for arrays like <code>{"results":[{"score":42}]}</code></div>
                        <div class="mb-0">Use the Test button below to inspect the response preview and copy the field path you need.</div>
                      </div>
                    <div v-for="(row, idx) in createForm.connector_response_rows" :key="idx" class="d-flex gap-2 mb-2 align-items-center">
                      <input v-model.trim="row.field" type="text" class="form-control" placeholder="Output field (e.g. country)" style="flex:1">
                      <span class="text-muted">→</span>
                      <input v-model.trim="row.path" type="text" class="form-control font-monospace" placeholder="$.country" style="flex:2">
                      <button type="button" class="btn btn-outline-danger btn-sm px-2" @click="createForm.connector_response_rows.splice(idx, 1)" :disabled="createForm.connector_response_rows.length === 1">×</button>
                    </div>
                  </div>
                  <div class="row">
                    <div class="col-md-6 mb-3">
                      <label class="form-label">Timeout (seconds)</label>
                      <input v-model.number="createForm.connector_config.timeout_seconds" type="number" min="1" max="120" class="form-control" required>
                    </div>
                    <div class="col-md-6 mb-3">
                      <label class="form-label">Retry Count</label>
                      <input v-model.number="createForm.connector_config.retry_count" type="number" min="0" max="5" class="form-control" required>
                    </div>
                  </div>
                  <div v-if="createForm.connector_config.provider_kind !== 'db'" class="mb-3 form-check">
                    <input id="createVerifySsl" v-model="createForm.connector_config.verify_ssl" type="checkbox" class="form-check-input">
                    <label class="form-check-label" for="createVerifySsl">Verify SSL certificate</label>
                    <div class="form-text">Disable only for self-signed/internal endpoints.</div>
                  </div>
                  <div class="mb-3 d-flex gap-2 align-items-center">
                    <input v-model.trim="testSampleValue" type="text" class="form-control form-control-sm" style="max-width: 220px;" :placeholder="defaultSampleValue(createForm.enrich_data_type)" title="Indicator value to test with">
                    <button type="button" class="btn btn-outline-primary btn-sm text-nowrap" @click="testConnectorPreview('create')" :disabled="testingConnector">
                      <span v-if="testingConnector" class="spinner-border spinner-border-sm me-2"></span>
                      {{ testingConnector ? 'Testing...' : 'Test with Sample Value' }}
                    </button>
                  </div>
                  <div v-if="testConnectorResult" class="alert" :class="testConnectorResult.error ? 'alert-warning' : 'alert-info'">
                    <h6 v-if="!testConnectorResult.error" class="mb-2">Test Result Preview:</h6>
                    <h6 v-else class="mb-2">Test Error:</h6>
                    <pre class="text-break">{{ JSON.stringify(testConnectorResult, null, 2) }}</pre>
                  </div>
                </div>
              </div>
            </div>
            <div class="mb-3">
              <label class="form-label">Output Fields (comma-separated)</label>
              <input v-model.trim="createForm.enrich_output_fields_text" type="text" class="form-control" placeholder="e.g. networktype" required>
            </div>
            <div class="mb-3">
              <label class="form-label">Description</label>
              <input v-model.trim="createForm.enrich_description" type="text" class="form-control" placeholder="Optional">
            </div>
            <div class="mb-3">
              <label class="form-label">Info</label>
              <textarea v-model.trim="createForm.info" class="form-control" rows="3" placeholder="Optional. What this enrichment does, its source, and example output. Shown via the i button in the list."></textarea>
            </div>
            <div class="mb-3">
              <div class="form-check">
                <input v-model="createForm.enabled" type="checkbox" class="form-check-input" id="createEnrichmentEnabled">
                <label class="form-check-label" for="createEnrichmentEnabled">Enabled</label>
              </div>
            </div>
          </form>
          <div v-if="formError" class="alert alert-danger mt-2 mb-0">{{ formError }}</div>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" @click="closeCreateModal">Cancel</button>
          <button type="button" class="btn btn-primary" @click="submitCreateEnrichment" :disabled="submitting">
            <span v-if="submitting" class="spinner-border spinner-border-sm me-2"></span>
            {{ submitting ? 'Creating...' : 'Create Enrichment' }}
          </button>
        </div>
      </div>
    </div>

    <div v-if="showEditModal" class="modal-overlay" @click.self="closeEditModal">
      <div class="modal-content" style="max-width: 620px;">
        <div class="modal-header">
          <h5 class="modal-title">Edit Data Enrichment</h5>
          <button type="button" class="btn-close" @click="closeEditModal"></button>
        </div>
        <div class="modal-body">
          <form @submit.prevent="submitEditEnrichment">
            <div class="mb-3">
              <label class="form-label">Enrichment Name</label>
              <input v-model.trim="editForm.enrich_name" type="text" class="form-control" disabled>
            </div>
            <div class="mb-3">
              <label class="form-label">Data Type</label>
              <select v-model="editForm.enrich_data_type" class="form-select" required>
                <option value="">-- Select Data Type --</option>
                <option v-for="dtype in dataTypes" :key="dtype" :value="dtype">{{ dtype }}</option>
              </select>
            </div>
            <div class="mb-3">
              <label class="form-label">Enrichment Type</label>
              <select v-model="editForm.enrich_type" class="form-select" required>
                <option v-if="editOriginalType === 'builtin'" value="builtin">Builtin</option>
                <option value="custom">Custom</option>
                <option value="connector">Connector (API/DB)</option>
                <option value="mcp">MCP Tool</option>
              </select>
            </div>
            <div v-if="editForm.enrich_type === 'mcp'" class="mb-3">
              <div class="card bg-light">
                <div class="card-body">
                  <h6 class="card-title">MCP Tool Configuration</h6>
                  <div class="mb-3">
                    <label class="form-label">MCP Server URL</label>
                    <input v-model.trim="editForm.mcp_url" type="text" class="form-control font-monospace" placeholder="https://mcp.example.com/mcp" required>
                    <div class="form-text">Streamable HTTP endpoint of the MCP server.</div>
                  </div>
                  <div class="mb-3">
                    <label class="form-label">Tool Name</label>
                    <input v-model.trim="editForm.mcp_tool_name" type="text" class="form-control font-monospace" placeholder="e.g. lookup_ip" required>
                  </div>
                  <div class="mb-3">
                    <label class="form-label">Tool Arguments (JSON)</label>
                    <textarea v-model="editForm.mcp_tool_arguments_text" class="form-control font-monospace" rows="4" placeholder='{"ip": "{{value}}"}'></textarea>
                    <div class="form-text">Use <code v-pre>{{value}}</code> and <code v-pre>{{type}}</code> as placeholders for the indicator. Supports <code v-pre>{{secret:name}}</code>.</div>
                  </div>
                  <div class="mb-3">
                    <label class="form-label">Bearer Token Secret Ref</label>
                    <select v-model="editForm.mcp_auth_secret_ref" class="form-select">
                      <option value="">-- None --</option>
                      <option v-for="s in secrets" :key="s.secret_ref" :value="s.secret_ref">{{ s.name ? s.name + ' (' + s.secret_ref + ')' : s.secret_ref }}</option>
                    </select>
                    <div class="form-text">Optional. Sent as <code>Authorization: Bearer</code> header.</div>
                  </div>
                  <div class="mb-3">
                    <div class="d-flex justify-content-between align-items-center mb-2">
                      <label class="form-label mb-0">Response Mapping</label>
                      <button type="button" class="btn btn-outline-secondary btn-sm" @click="editForm.mcp_response_rows.push({ field: '', path: '' })">+ Add Field</button>
                    </div>
                    <div class="form-text mb-2">Optional. Map output fields to paths in the tool result (<code>structuredContent</code>, or JSON text content). Unmapped output fields receive the whole result.</div>
                    <div v-for="(row, idx) in editForm.mcp_response_rows" :key="idx" class="d-flex gap-2 mb-2 align-items-center">
                      <input v-model.trim="row.field" type="text" class="form-control" placeholder="Output field (e.g. country)" style="flex:1">
                      <span class="text-muted">→</span>
                      <input v-model.trim="row.path" type="text" class="form-control font-monospace" placeholder="$.country" style="flex:2">
                      <button type="button" class="btn btn-outline-danger btn-sm px-2" @click="editForm.mcp_response_rows.splice(idx, 1)" :disabled="editForm.mcp_response_rows.length === 1">×</button>
                    </div>
                  </div>
                  <div class="row">
                    <div class="col-md-6 mb-3">
                      <label class="form-label">Timeout (seconds)</label>
                      <input v-model.number="editForm.mcp_timeout_seconds" type="number" min="1" max="120" class="form-control" required>
                    </div>
                    <div class="col-md-6 mb-3">
                      <label class="form-label">Retry Count</label>
                      <input v-model.number="editForm.mcp_retry_count" type="number" min="0" max="5" class="form-control" required>
                    </div>
                  </div>
                  <div class="mb-3 form-check">
                    <input id="editMcpVerifySsl" v-model="editForm.mcp_verify_ssl" type="checkbox" class="form-check-input">
                    <label class="form-check-label" for="editMcpVerifySsl">Verify SSL certificate</label>
                  </div>
                  <div class="mb-3 d-flex gap-2 align-items-center">
                    <input v-model.trim="testSampleValue" type="text" class="form-control form-control-sm" style="max-width: 220px;" :placeholder="defaultSampleValue(editForm.enrich_data_type)" title="Indicator value to test with">
                    <button type="button" class="btn btn-outline-primary btn-sm text-nowrap" @click="testMcpPreview('edit')" :disabled="testingConnector">
                      <span v-if="testingConnector" class="spinner-border spinner-border-sm me-2"></span>
                      {{ testingConnector ? 'Testing...' : 'Test with Sample Value' }}
                    </button>
                  </div>
                  <div v-if="testConnectorResult" class="alert" :class="testConnectorResult.error ? 'alert-warning' : 'alert-info'">
                    <h6 v-if="!testConnectorResult.error" class="mb-2">Test Result Preview:</h6>
                    <h6 v-else class="mb-2">Test Error:</h6>
                    <pre class="text-break">{{ JSON.stringify(testConnectorResult, null, 2) }}</pre>
                  </div>
                </div>
              </div>
            </div>
            <div class="mb-3" v-if="editForm.enrich_type === 'builtin'">
              <label class="form-label">Mapping Function</label>
              <input v-model.trim="editForm.enrich_mapping_function" type="text" class="form-control" :required="editForm.enrich_type === 'builtin'">
            </div>
            <div class="mb-3" v-else-if="editForm.enrich_type === 'custom'">
              <label class="form-label">Python Snippet</label>
              <textarea
                v-model="editForm.snippet_code"
                class="form-control"
                rows="8"
                placeholder="Set result = ... using value, indicator, and enrichment; use a dict for multi-output"
                :required="editForm.enrich_type === 'custom'"
              ></textarea>
              <div class="form-text">Custom snippet must set <code>result</code>. Use a scalar for one output field or a dict keyed by output field names for multi-output. Available variables: <code>value</code>, <code>indicator</code>, and <code>enrichment</code>.</div>
            </div>
            <div v-else-if="editForm.enrich_type === 'connector'" class="mb-3">
              <div class="card bg-light">
                <div class="card-body">
                  <h6 class="card-title">Connector Configuration</h6>
                  <div class="mb-3">
                    <label class="form-label">Provider Kind</label>
                    <select v-model="editForm.connector_config.provider_kind" class="form-select" required>
                      <option value="">-- Select Provider --</option>
                      <option value="http">HTTP API</option>
                      <option value="db">Database Query</option>
                    </select>
                  </div>
                  <div v-if="editForm.connector_config.provider_kind === 'db'" class="mb-3">
                    <div class="card bg-light p-3">
                      <h6 class="card-subtitle mb-3">Database Query Configuration</h6>
                      <div class="row">
                        <div class="col-md-6 mb-3">
                          <label class="form-label">Engine</label>
                          <select v-model="editForm.db_engine" class="form-select" required>
                            <option v-for="(label, key) in dbEngines" :key="key" :value="key">{{ label }}</option>
                          </select>
                        </div>
                        <div class="col-md-6 mb-3">
                          <label class="form-label">Result</label>
                          <select v-model="editForm.db_result_mode" class="form-select">
                            <option value="first_row">First row (object)</option>
                            <option value="all_rows">All rows (array)</option>
                          </select>
                        </div>
                      </div>
                      <div class="row">
                        <div class="col-md-8 mb-3">
                          <label class="form-label">Host</label>
                          <input v-model.trim="editForm.db_host" type="text" class="form-control" placeholder="db.internal.example.com" required>
                        </div>
                        <div class="col-md-4 mb-3">
                          <label class="form-label">Port</label>
                          <input v-model.number="editForm.db_port" type="number" min="1" max="65535" class="form-control" :placeholder="String(dbDefaultPorts[editForm.db_engine] || '')">
                        </div>
                      </div>
                      <div class="row">
                        <div :class="editForm.db_engine === 'mongodb' ? 'col-md-6 mb-3' : 'col-12 mb-3'">
                          <label class="form-label">{{ editForm.db_engine === 'oracle' ? 'Service Name' : 'Database' }}</label>
                          <input v-model.trim="editForm.db_name" type="text" class="form-control" required>
                        </div>
                        <div v-if="editForm.db_engine === 'mongodb'" class="col-md-6 mb-3">
                          <label class="form-label">Collection</label>
                          <input v-model.trim="editForm.db_collection" type="text" class="form-control" required>
                        </div>
                      </div>
                      <div class="row">
                        <div class="col-md-6 mb-3">
                          <label class="form-label">Username</label>
                          <input v-model.trim="editForm.db_user" type="text" class="form-control" required>
                        </div>
                        <div class="col-md-6 mb-3">
                          <label class="form-label">Password Secret Ref</label>
                          <select v-model="editForm.db_password_secret_ref" class="form-select" required>
                            <option value="">-- Select Secret --</option>
                            <option v-for="s in secrets" :key="s.secret_ref" :value="s.secret_ref">{{ s.name ? s.name + ' (' + s.secret_ref + ')' : s.secret_ref }}</option>
                          </select>
                          <div v-if="secrets.length === 0" class="form-text text-warning">No active secrets found. Create one in the Secrets page first.</div>
                        </div>
                      </div>
                      <div v-if="editForm.db_engine === 'mongodb'" class="mb-3">
                        <label class="form-label">Auth Source</label>
                        <input v-model.trim="editForm.db_auth_source" type="text" class="form-control" placeholder="Defaults to the database name">
                      </div>
                      <div class="mb-3">
                        <label class="form-label">{{ editForm.db_engine === 'mongodb' ? 'Query (JSON filter or aggregation pipeline)' : 'SQL Query' }}</label>
                        <textarea v-model="editForm.db_query" class="form-control font-monospace" rows="4" :placeholder="dbQueryPlaceholder(editForm.db_engine)" required></textarea>
                        <div v-if="editForm.db_engine === 'mongodb'" class="form-text">Use <code v-pre>"{{value}}"</code> and <code v-pre>"{{type}}"</code> inside JSON string values. A JSON array runs as an aggregation pipeline.</div>
                        <div v-else-if="editForm.db_engine === 'oracle'" class="form-text">Bind the indicator with <code>:value</code> and <code>:type</code>. Values are sent as bound parameters, never spliced into the SQL.</div>
                        <div v-else class="form-text">Bind the indicator with <code>%(value)s</code> and <code>%(type)s</code>; write a literal <code>%</code> as <code>%%</code>. Values are sent as bound parameters, never spliced into the SQL.</div>
                      </div>
                      <div v-if="editForm.db_result_mode === 'all_rows'" class="mb-3">
                        <label class="form-label">Row Limit</label>
                        <input v-model.number="editForm.db_row_limit" type="number" min="1" max="1000" class="form-control">
                      </div>
                      <div class="form-text">Use a read-only database account. The query runs once per indicator and is never committed.</div>
                    </div>
                  </div>
                  <div v-if="editForm.connector_config.provider_kind === 'http'" class="mb-3">
                    <div class="card bg-light p-3">
                      <h6 class="card-subtitle mb-3">HTTP Request Configuration</h6>
                      
                      <div class="mb-3">
                        <label class="form-label">API URL</label>
                        <input v-model.trim="editForm.connector_url" type="text" class="form-control font-monospace" placeholder="https://api.example.com/lookup?q={{value}}" required>
                        <div class="form-text">Use <code v-pre>{{value}}</code> and <code v-pre>{{type}}</code> as placeholders. Supports <code v-pre>{{secret:name}}</code> for query params.</div>
                      </div>
                      
                      <div class="row">
                        <div class="col-md-6 mb-3">
                          <label class="form-label">HTTP Method</label>
                          <select v-model="editForm.connector_method" class="form-select" required>
                            <option value="GET">GET</option>
                            <option value="POST">POST</option>
                            <option value="PUT">PUT</option>
                            <option value="PATCH">PATCH</option>
                            <option value="DELETE">DELETE</option>
                          </select>
                        </div>
                        <div class="col-md-6 mb-3">
                          <label class="form-label">Authentication Type</label>
                          <select v-model="editForm.connector_auth_type" class="form-select">
                            <option value="none">None</option>
                            <option value="api_key">API Key Header</option>
                            <option value="api_with_bearertoken">Bearer Token</option>
                            <option value="api_basicauth">Basic Auth</option>
                          </select>
                        </div>
                      </div>
                      
                      <div v-if="editForm.connector_auth_type === 'api_basicauth'" class="mb-3">
                        <div class="row">
                          <div class="col-md-6 mb-2">
                            <label class="form-label">Username</label>
                            <input v-model.trim="editForm.connector_auth_basic_username" type="text" class="form-control" placeholder="e.g. admin">
                          </div>
                          <div class="col-md-6 mb-2">
                            <label class="form-label">Password Secret Ref</label>
                            <select v-model="editForm.connector_auth_secret_name" class="form-select">
                              <option value="">-- Select Secret --</option>
                              <option v-for="s in secrets" :key="s.secret_ref" :value="s.secret_ref">{{ s.name ? s.name + ' (' + s.secret_ref + ')' : s.secret_ref }}</option>
                            </select>
                            <div v-if="secrets.length === 0" class="form-text text-warning">No active secrets found. Create one in the Secrets page first.</div>
                          </div>
                        </div>
                      </div>
                      <div v-else-if="editForm.connector_auth_type !== 'none'" class="mb-3">
                        <label class="form-label">Secret Ref</label>
                        <select v-model="editForm.connector_auth_secret_name" class="form-select">
                          <option value="">-- Select Secret --</option>
                          <option v-for="s in secrets" :key="s.secret_ref" :value="s.secret_ref">{{ s.name ? s.name + ' (' + s.secret_ref + ')' : s.secret_ref }}</option>
                        </select>
                        <div v-if="secrets.length === 0" class="form-text text-warning">No active secrets found. Create one in the Secrets page first.</div>
                        <div class="form-text">Secret value resolved at runtime. Sent as <span v-if="editForm.connector_auth_type === 'api_key'"><code>X-API-Key</code> header</span><span v-else><code>Authorization: Bearer</code> header</span>.</div>
                      </div>
                      
                      <div v-if="editForm.connector_method !== 'GET'" class="mb-3">
                        <label class="form-label">Request Body (JSON)</label>
                        <textarea v-model="editForm.connector_body_text" class="form-control font-monospace" rows="6" placeholder='{"search": "{{value}}", "type": "{{type}}"}'></textarea>
                        <div class="form-text">Optional. Leave empty for GET requests. Supports <code v-pre>{{value}}</code> and <code v-pre>{{type}}</code> placeholders.</div>
                      </div>
                    </div>
                  </div>
                  <div class="mb-3">
                    <div class="d-flex justify-content-between align-items-center mb-2">
                        <div class="d-flex align-items-center gap-2">
                          <label class="form-label mb-0">Response Mapping</label>
                          <button
                            type="button"
                            class="btn btn-outline-secondary btn-sm info-button"
                            @click="showEditResponseMappingHelp = !showEditResponseMappingHelp"
                            :aria-expanded="showEditResponseMappingHelp ? 'true' : 'false'"
                            title="Show response mapping examples"
                          >i</button>
                        </div>
                        <button type="button" class="btn btn-outline-secondary btn-sm" @click="editForm.connector_response_rows.push({ field: '', path: '' })">+ Add Field</button>
                    </div>
                    <div class="form-text mb-2">Map output field names to paths in the API response or DB result (e.g. <code>$.country</code> for a column, <code>$.0.country</code> in all-rows mode).</div>
                      <div v-if="showEditResponseMappingHelp" class="alert alert-light border small mb-3">
                        <div class="fw-semibold mb-2">Common path patterns</div>
                        <div class="mb-1"><code>$.country</code> for <code>{"country":"US"}</code></div>
                        <div class="mb-1"><code>$.asn.name</code> for nested objects like <code>{"asn":{"name":"ExampleNet"}}</code></div>
                        <div class="mb-1"><code>$.results.0.score</code> for arrays like <code>{"results":[{"score":42}]}</code></div>
                        <div class="mb-0">Use the Test button below to inspect the response preview and copy the field path you need.</div>
                      </div>
                    <div v-for="(row, idx) in editForm.connector_response_rows" :key="idx" class="d-flex gap-2 mb-2 align-items-center">
                      <input v-model.trim="row.field" type="text" class="form-control" placeholder="Output field (e.g. country)" style="flex:1">
                      <span class="text-muted">→</span>
                      <input v-model.trim="row.path" type="text" class="form-control font-monospace" placeholder="$.country" style="flex:2">
                      <button type="button" class="btn btn-outline-danger btn-sm px-2" @click="editForm.connector_response_rows.splice(idx, 1)" :disabled="editForm.connector_response_rows.length === 1">×</button>
                    </div>
                  </div>
                  <div class="row">
                    <div class="col-md-6 mb-3">
                      <label class="form-label">Timeout (seconds)</label>
                      <input v-model.number="editForm.connector_config.timeout_seconds" type="number" min="1" max="120" class="form-control" required>
                    </div>
                    <div class="col-md-6 mb-3">
                      <label class="form-label">Retry Count</label>
                      <input v-model.number="editForm.connector_config.retry_count" type="number" min="0" max="5" class="form-control" required>
                    </div>
                  </div>
                  <div v-if="editForm.connector_config.provider_kind !== 'db'" class="mb-3 form-check">
                    <input id="editVerifySsl" v-model="editForm.connector_config.verify_ssl" type="checkbox" class="form-check-input">
                    <label class="form-check-label" for="editVerifySsl">Verify SSL certificate</label>
                    <div class="form-text">Disable only for self-signed/internal endpoints.</div>
                  </div>
                  <div class="mb-3 d-flex gap-2 align-items-center">
                    <input v-model.trim="testSampleValue" type="text" class="form-control form-control-sm" style="max-width: 220px;" :placeholder="defaultSampleValue(editForm.enrich_data_type)" title="Indicator value to test with">
                    <button type="button" class="btn btn-outline-primary btn-sm text-nowrap" @click="testConnectorPreview('edit')" :disabled="testingConnector">
                      <span v-if="testingConnector" class="spinner-border spinner-border-sm me-2"></span>
                      {{ testingConnector ? 'Testing...' : 'Test with Sample Value' }}
                    </button>
                  </div>
                  <div v-if="testConnectorResult" class="alert" :class="testConnectorResult.error ? 'alert-warning' : 'alert-info'">
                    <h6 v-if="!testConnectorResult.error" class="mb-2">Test Result Preview:</h6>
                    <h6 v-else class="mb-2">Test Error:</h6>
                    <pre class="text-break">{{ JSON.stringify(testConnectorResult, null, 2) }}</pre>
                  </div>
                </div>
              </div>
            </div>
            <div class="mb-3">
              <label class="form-label">Output Fields (comma-separated)</label>
              <input v-model.trim="editForm.enrich_output_fields_text" type="text" class="form-control" required>
            </div>
            <div class="mb-3">
              <label class="form-label">Description</label>
              <input v-model.trim="editForm.enrich_description" type="text" class="form-control" placeholder="Optional">
            </div>
            <div class="mb-3">
              <label class="form-label">Info</label>
              <textarea v-model.trim="editForm.info" class="form-control" rows="3" placeholder="Optional. What this enrichment does, its source, and example output. Shown via the i button in the list."></textarea>
            </div>
            <div class="mb-3">
              <div class="form-check">
                <input v-model="editForm.enabled" type="checkbox" class="form-check-input" id="editEnrichmentEnabled">
                <label class="form-check-label" for="editEnrichmentEnabled">Enabled</label>
              </div>
            </div>
          </form>
          <div v-if="formError" class="alert alert-danger mt-2 mb-0">{{ formError }}</div>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" @click="closeEditModal">Cancel</button>
          <button type="button" class="btn btn-primary" @click="submitEditEnrichment" :disabled="submitting">
            <span v-if="submitting" class="spinner-border spinner-border-sm me-2"></span>
            {{ submitting ? 'Saving...' : 'Save Changes' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { apiFetch } from '@/api'

function defaultMcpFields() {
  return {
    mcp_url: '',
    mcp_tool_name: '',
    mcp_tool_arguments_text: '{\n  "value": "{{value}}"\n}',
    mcp_auth_secret_ref: '',
    mcp_response_rows: [{ field: '', path: '' }],
    mcp_timeout_seconds: 30,
    mcp_retry_count: 0,
    mcp_verify_ssl: true
  }
}

const DB_ENGINES = {
  postgresql: 'PostgreSQL',
  mysql: 'MySQL / MariaDB',
  mssql: 'Microsoft SQL Server',
  oracle: 'Oracle',
  mongodb: 'MongoDB'
}
const DB_DEFAULT_PORTS = { postgresql: 5432, mysql: 3306, mssql: 1433, oracle: 1521, mongodb: 27017 }

function defaultDbFields() {
  return {
    db_engine: 'postgresql',
    db_host: '',
    db_port: '',
    db_name: '',
    db_collection: '',
    db_auth_source: '',
    db_user: '',
    db_password_secret_ref: '',
    db_query: '',
    db_result_mode: 'first_row',
    db_row_limit: 100
  }
}

export default {
  name: 'DataEnrichmentsPage',
  data() {
    return {
      enrichments: [],
      dataTypes: [],
      loading: false,
      error: '',
      message: '',
      messageType: 'success',
      submitting: false,
      formError: '',
      showCreateModal: false,
      showEditModal: false,
      showPageInfo: false,
      rowInfoItem: null,
      editOriginalType: '',
      showCreateResponseMappingHelp: false,
      showEditResponseMappingHelp: false,
      testingConnector: false,
      testConnectorResult: null,
      testSampleValue: '',
      dbEngines: DB_ENGINES,
      dbDefaultPorts: DB_DEFAULT_PORTS,
      secrets: [],
      createForm: {
        enrich_name: '',
        enrich_data_type: '',
        enrich_type: 'custom',
        enrich_mapping_function: '',
        snippet_code: '',
        enrich_output_fields_text: '',
        enrich_description: '',
        info: '',
        enabled: false,
        connector_config: {
          provider_kind: '',
          timeout_seconds: 30,
          retry_count: 2,
          verify_ssl: true
        },
        connector_url: '',
        connector_method: 'GET',
        connector_auth_type: 'none',
        connector_auth_secret_name: '',
        connector_auth_basic_username: '',
        connector_body_text: '',
        connector_response_rows: [{ field: '', path: '' }],
        connector_response_mapping_text: '',
        ...defaultMcpFields(),
        ...defaultDbFields()
      },
      editForm: {
        enrich_name: '',
        enrich_data_type: '',
        enrich_type: 'builtin',
        enrich_mapping_function: '',
        snippet_code: '',
        enrich_output_fields_text: '',
        enrich_description: '',
        info: '',
        enabled: false,
        connector_config: {
          provider_kind: '',
          timeout_seconds: 30,
          retry_count: 2,
          verify_ssl: true
        },
        connector_url: '',
        connector_method: 'GET',
        connector_auth_type: 'none',
        connector_auth_secret_name: '',
        connector_auth_basic_username: '',
        connector_body_text: '',
        connector_response_mapping_text: '',
        ...defaultMcpFields(),
        ...defaultDbFields()
      }
    }
  },
  async mounted() {
    await this.fetchDataTypes()
    await this.fetchEnrichments()
    await this.fetchSecrets()
  },
  methods: {
    parseOutputFields(value) {
      return String(value || '')
        .split(',')
        .map((entry) => entry.trim())
        .filter((entry) => entry)
    },
    formatOutputFields(fields) {
      return Array.isArray(fields) && fields.length ? fields.join(', ') : '-'
    },
    formatDate(value) {
      if (!value) return '-'
      const date = new Date(value)
      if (Number.isNaN(date.getTime())) return String(value)
      return date.toLocaleString()
    },
    clearFormMessages() {
      this.formError = ''
    },
    buildRequestTemplate(form) {
      // Build request_template from UI fields
      const headers = {}
      
      if (form.connector_auth_type === 'api_key') {
        headers['X-API-Key'] = `{{secret:${form.connector_auth_secret_name || 'api_key'}}}`
      } else if (form.connector_auth_type === 'api_with_bearertoken') {
        headers['Authorization'] = `Bearer {{secret:${form.connector_auth_secret_name || 'api_token'}}}`
      } else if (form.connector_auth_type === 'api_basicauth') {
        headers['Authorization'] = `Basic {{secret:${form.connector_auth_secret_name || 'auth_basic'}}}`
      }

      // For basic auth, store username separately alongside the password secret ref
      const basicUsername = form.connector_auth_type === 'api_basicauth' ? (form.connector_auth_basic_username || '') : undefined
      
      const template = {
        url_template: form.connector_url,
        method: form.connector_method || 'GET',
        ...(basicUsername !== undefined ? { basic_username: basicUsername } : {})
      }
      
      if (Object.keys(headers).length > 0) {
        template.headers_template = headers
      }
      
      if (form.connector_body_text && form.connector_body_text.trim()) {
        try {
          template.body_template = JSON.parse(form.connector_body_text)
        } catch (e) {
          template.body_template = form.connector_body_text
        }
      }
      
      return template
    },
    resetCreateForm() {
      this.createForm = {
        enrich_name: '',
        enrich_data_type: '',
        enrich_type: 'custom',
        enrich_mapping_function: '',
        snippet_code: '',
        enrich_output_fields_text: '',
        enrich_description: '',
        info: '',
        enabled: false,
        connector_config: {
          provider_kind: '',
          timeout_seconds: 30,
          retry_count: 2,
          verify_ssl: true
        },
        connector_url: '',
        connector_method: 'GET',
        connector_auth_type: 'none',
        connector_auth_secret_name: '',
        connector_auth_basic_username: '',
        connector_body_text: '',
        connector_response_rows: [{ field: '', path: '' }],
        connector_response_mapping_text: '',
        ...defaultMcpFields(),
        ...defaultDbFields()
      }
      this.showCreateResponseMappingHelp = false
      this.testConnectorResult = null
    },
    openCreateModal() {
      this.clearFormMessages()
      this.resetCreateForm()
      this.showCreateModal = true
    },
    closeCreateModal() {
      this.showCreateModal = false
        this.showCreateResponseMappingHelp = false
      this.submitting = false
      this.formError = ''
      this.testConnectorResult = null
      this.resetCreateForm()
    },
    openEditModal(item) {
      this.clearFormMessages()
      this.testConnectorResult = null
      
      this.editOriginalType = item.enrich_type || 'builtin'

      // Load basic fields
      this.editForm = {
        enrich_name: item.enrich_name || '',
        enrich_data_type: item.enrich_data_type || '',
        enrich_type: item.enrich_type || 'builtin',
        enrich_mapping_function: item.enrich_mapping_function || '',
        snippet_code: item.snippet_code || '',
        enrich_output_fields_text: this.formatOutputFields(item.enrich_output_fields),
        enrich_description: item.enrich_description || '',
        info: item.info || '',
        enabled: item.enabled === true,
        connector_config: {
          provider_kind: '',
          timeout_seconds: 30,
          retry_count: 2,
          verify_ssl: true
        },
        connector_url: '',
        connector_method: 'GET',
        connector_auth_type: 'none',
        connector_auth_secret_name: '',
        connector_auth_basic_username: '',
        connector_body_text: '',
        connector_response_rows: [{ field: '', path: '' }],
        connector_response_mapping_text: '',
        ...defaultMcpFields(),
        ...defaultDbFields()
      }

      if (item.mcp_config) {
        const mc = item.mcp_config
        const rows = Object.entries(mc.response_mapping || {}).map(([field, path]) => ({ field, path: String(path) }))
        Object.assign(this.editForm, {
          mcp_url: mc.mcp_url || '',
          mcp_tool_name: mc.tool_name || '',
          mcp_tool_arguments_text: mc.tool_arguments && Object.keys(mc.tool_arguments).length ? JSON.stringify(mc.tool_arguments, null, 2) : '',
          mcp_auth_secret_ref: mc.auth_secret_ref || '',
          mcp_response_rows: rows.length > 0 ? rows : [{ field: '', path: '' }],
          mcp_timeout_seconds: mc.timeout_seconds || 30,
          mcp_retry_count: mc.retry_count || 0,
          mcp_verify_ssl: mc.verify_ssl !== false
        })
      }

      if (item.connector_config) {
        this.editForm.connector_config = {
          provider_kind: item.connector_config.provider_kind || '',
          timeout_seconds: item.connector_config.timeout_seconds || 30,
          retry_count: item.connector_config.retry_count || 2,
          verify_ssl: item.connector_config.verify_ssl !== false
        }
        
        // Parse request_template into UI fields
        const rt = item.connector_config.request_template || {}
        if (item.connector_config.provider_kind === 'db') {
          Object.assign(this.editForm, {
            db_engine: rt.db_engine || 'postgresql',
            db_host: rt.db_host || '',
            db_port: rt.db_port || '',
            db_name: rt.db_name || '',
            db_collection: rt.db_collection || '',
            db_auth_source: rt.db_auth_source || '',
            db_user: rt.db_user || '',
            db_password_secret_ref: rt.db_password_secret_ref || '',
            db_query: rt.query_template || '',
            db_result_mode: rt.result_mode || 'first_row',
            db_row_limit: rt.row_limit || 100
          })
        }
        this.editForm.connector_url = rt.url_template || ''
        this.editForm.connector_method = String(rt.method || 'GET').toUpperCase()
        
        // Parse auth type from headers
        const headers = rt.headers_template || {}
        if (Object.keys(headers).length > 0) {
          const headerStr = JSON.stringify(headers)
          if (headerStr.includes('{{secret:')) {
            const secretMatch = headerStr.match(/\{\{secret:([a-zA-Z0-9_-]+)\}\}/)
            if (secretMatch) {
              this.editForm.connector_auth_secret_name = secretMatch[1]
              if (headerStr.includes('Bearer')) {
                this.editForm.connector_auth_type = 'api_with_bearertoken'
              } else if (headerStr.includes('Basic')) {
                this.editForm.connector_auth_type = 'api_basicauth'
                // Try parse basic_username if stored separately
                const rt2 = item.connector_config.request_template || {}
                this.editForm.connector_auth_basic_username = rt2.basic_username || ''
              } else {
                this.editForm.connector_auth_type = 'api_key'
              }
            }
          }
        }
        
        if (rt.body_template) {
          this.editForm.connector_body_text = typeof rt.body_template === 'string' ? rt.body_template : JSON.stringify(rt.body_template, null, 2)
        }
        
        if (item.connector_config.response_mapping) {
          const rm = item.connector_config.response_mapping
          const rows = Object.entries(rm).map(([field, path]) => ({ field, path: String(path) }))
          this.editForm.connector_response_rows = rows.length > 0 ? rows : [{ field: '', path: '' }]
        }
      }
      
      this.showEditModal = true
    },
    closeEditModal() {
      this.showEditModal = false
        this.showEditResponseMappingHelp = false
      this.submitting = false
      this.formError = ''
      this.testConnectorResult = null
    },
    defaultSampleValue(dataType) {
      return dataType === 'ipv4' ? '192.0.2.1' : 'example.value'
    },
    dbQueryPlaceholder(engine) {
      if (engine === 'mongodb') return '{"ip": "{{value}}"}'
      if (engine === 'oracle') return 'SELECT country, asn FROM ip_intel WHERE ip = :value'
      return 'SELECT country, asn FROM ip_intel WHERE ip = %(value)s'
    },
    validateConnectorTarget(form) {
      if (form.connector_config.provider_kind === 'http') {
        return form.connector_url.trim() ? '' : 'URL is required for HTTP connector enrichments.'
      }
      if (form.connector_config.provider_kind !== 'db') return ''

      const required = [
        ['db_host', 'Host'],
        ['db_name', form.db_engine === 'oracle' ? 'Service name' : 'Database'],
        ['db_user', 'Username'],
        ['db_password_secret_ref', 'Password secret ref'],
        ['db_query', 'Query']
      ]
      if (form.db_engine === 'mongodb') required.push(['db_collection', 'Collection'])
      for (const [field, label] of required) {
        if (!String(form[field] || '').trim()) return `${label} is required for database connector enrichments.`
      }

      if (form.db_engine === 'mongodb') {
        let parsed
        try {
          parsed = JSON.parse(form.db_query)
        } catch (e) {
          return 'MongoDB query must be valid JSON: ' + e.message
        }
        if (!parsed || typeof parsed !== 'object') return 'MongoDB query must be a JSON filter object or aggregation pipeline array.'
      } else if (form.db_query.includes('{{')) {
        const bind = form.db_engine === 'oracle' ? ':value' : '%(value)s'
        return `Use bound parameters such as ${bind} in SQL queries instead of {{...}} placeholders.`
      }
      return ''
    },
    buildConnectorRequestTemplate(form) {
      if (form.connector_config.provider_kind !== 'db') return this.buildRequestTemplate(form)
      const template = {
        db_engine: form.db_engine,
        db_host: form.db_host,
        db_port: form.db_port || DB_DEFAULT_PORTS[form.db_engine],
        db_name: form.db_name,
        db_user: form.db_user,
        db_password_secret_ref: form.db_password_secret_ref,
        query_template: String(form.db_query || '').trim(),
        result_mode: form.db_result_mode,
        row_limit: form.db_row_limit || 100
      }
      if (form.db_engine === 'mongodb') {
        template.db_collection = form.db_collection
        template.db_auth_source = form.db_auth_source
      }
      return template
    },
    validateMcpForm(form) {
      if (!form.mcp_url) return 'MCP server URL is required for MCP enrichments.'
      if (!form.mcp_tool_name) return 'Tool name is required for MCP enrichments.'
      const text = String(form.mcp_tool_arguments_text || '').trim()
      if (text) {
        let parsed
        try {
          parsed = JSON.parse(text)
        } catch (e) {
          return 'Invalid tool arguments JSON: ' + e.message
        }
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
          return 'Tool arguments must be a JSON object.'
        }
      }
      return ''
    },
    buildMcpConfig(form) {
      const text = String(form.mcp_tool_arguments_text || '').trim()
      return {
        mcp_url: form.mcp_url,
        tool_name: form.mcp_tool_name,
        tool_arguments: text ? JSON.parse(text) : {},
        auth_secret_ref: form.mcp_auth_secret_ref || '',
        timeout_seconds: form.mcp_timeout_seconds,
        retry_count: form.mcp_retry_count,
        verify_ssl: form.mcp_verify_ssl !== false,
        response_mapping: this.buildResponseMapping(form.mcp_response_rows)
      }
    },
    buildResponseMapping(rows) {
      const mapping = {}
      for (const row of (rows || [])) {
        const field = String(row.field || '').trim()
        const path = String(row.path || '').trim()
        if (field && path) mapping[field] = path
      }
      return mapping
    },
    async fetchSecrets() {
      try {
        const res = await apiFetch('/api/secrets')
        const data = await res.json()
        if (res.ok) {
          const all = Array.isArray(data.secrets) ? data.secrets : []
          this.secrets = all.filter(s => s && s.active !== false && s.secret_ref)
        }
      } catch (e) {
        this.secrets = []
      }
    },
    async fetchDataTypes() {
      try {
        const res = await apiFetch('/api/data_types')
        const data = await res.json()
        if (!res.ok) {
          this.dataTypes = []
          return
        }
        this.dataTypes = Array.isArray(data.data_types) ? data.data_types : []
      } catch (e) {
        this.dataTypes = []
      }
    },
    async fetchEnrichments() {
      this.loading = true
      this.error = ''
      try {
        const res = await apiFetch('/api/data_enrichments')
        const data = await res.json()
        if (!res.ok) {
          this.error = data.message || 'Failed to fetch data enrichments.'
          this.enrichments = []
          return
        }
        this.enrichments = Array.isArray(data.enrichments) ? data.enrichments : []
      } catch (e) {
        this.error = 'Network error while fetching data enrichments.'
        this.enrichments = []
      } finally {
        this.loading = false
      }
    },
    async submitCreateEnrichment() {
      if (!this.createForm.enrich_name || !this.createForm.enrich_data_type) {
        this.formError = 'enrich_name and data type are required.'
        return
      }

      if (this.createForm.enrich_type === 'builtin' && !this.createForm.enrich_mapping_function) {
        this.formError = 'mapping function is required for builtin enrichments.'
        return
      }

      if (this.createForm.enrich_type === 'custom' && !String(this.createForm.snippet_code || '').trim()) {
        this.formError = 'python snippet is required for custom enrichments.'
        return
      }

      if (this.createForm.enrich_type === 'connector') {
        if (!this.createForm.connector_config.provider_kind) {
          this.formError = 'provider kind is required for connector enrichments.'
          return
        }
        
        const targetError = this.validateConnectorTarget(this.createForm)
        if (targetError) {
          this.formError = targetError
          return
        }
        
        const _createRows = this.buildResponseMapping(this.createForm.connector_response_rows)
        if (Object.keys(_createRows).length === 0) {
          this.formError = 'At least one response mapping row is required.'
          return
        }

        // Validate body JSON if present
        if (this.createForm.connector_body_text && this.createForm.connector_body_text.trim()) {
          try {
            JSON.parse(this.createForm.connector_body_text)
          } catch (e) {
            this.formError = 'Invalid body JSON: ' + e.message
            return
          }
        }
      }

      if (this.createForm.enrich_type === 'mcp') {
        const mcpError = this.validateMcpForm(this.createForm)
        if (mcpError) {
          this.formError = mcpError
          return
        }
      }

      const outputFields = this.parseOutputFields(this.createForm.enrich_output_fields_text)
      if (outputFields.length === 0) {
        this.formError = 'At least one output field is required.'
        return
      }

      this.submitting = true
      this.formError = ''
      try {
        const payload = {
          enrich_name: this.createForm.enrich_name,
          enrich_data_type: this.createForm.enrich_data_type,
          enrich_type: this.createForm.enrich_type,
          enrich_mapping_function: this.createForm.enrich_mapping_function,
          snippet_code: this.createForm.snippet_code,
          enrich_output_fields: outputFields,
          enrich_description: this.createForm.enrich_description || '',
          info: this.createForm.info || '',
          enabled: this.createForm.enabled === true
        }

        // Add connector_config if connector type
        if (this.createForm.enrich_type === 'connector') {
          payload.connector_config = {
            provider_kind: this.createForm.connector_config.provider_kind,
            timeout_seconds: this.createForm.connector_config.timeout_seconds,
            retry_count: this.createForm.connector_config.retry_count,
            verify_ssl: this.createForm.connector_config.verify_ssl !== false,
            request_template: this.buildConnectorRequestTemplate(this.createForm),
            response_mapping: this.buildResponseMapping(this.createForm.connector_response_rows)
          }
        }
        if (this.createForm.enrich_type === 'mcp') {
          payload.mcp_config = this.buildMcpConfig(this.createForm)
        }

        const res = await apiFetch('/api/data_enrichments/create', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        })
        const data = await res.json()
        if (!res.ok) {
          this.formError = data.message || 'Failed to create data enrichment.'
          return
        }

        this.message = data.message || 'Data enrichment created successfully.'
        this.messageType = 'success'
        this.closeCreateModal()
        await this.fetchEnrichments()
      } catch (e) {
        this.formError = 'Network error while creating data enrichment.'
      } finally {
        this.submitting = false
      }
    },
    async submitEditEnrichment() {
      if (!this.editForm.enrich_name || !this.editForm.enrich_data_type) {
        this.formError = 'enrich_name and data type are required.'
        return
      }

      if (this.editForm.enrich_type === 'builtin' && !this.editForm.enrich_mapping_function) {
        this.formError = 'mapping function is required for builtin enrichments.'
        return
      }

      if (this.editForm.enrich_type === 'custom' && !String(this.editForm.snippet_code || '').trim()) {
        this.formError = 'python snippet is required for custom enrichments.'
        return
      }

      if (this.editForm.enrich_type === 'connector') {
        if (!this.editForm.connector_config.provider_kind) {
          this.formError = 'provider kind is required for connector enrichments.'
          return
        }
        
        const targetError = this.validateConnectorTarget(this.editForm)
        if (targetError) {
          this.formError = targetError
          return
        }
        
        const _editRows = this.buildResponseMapping(this.editForm.connector_response_rows)
        if (Object.keys(_editRows).length === 0) {
          this.formError = 'At least one response mapping row is required.'
          return
        }

        // Validate body JSON if present
        if (this.editForm.connector_body_text && this.editForm.connector_body_text.trim()) {
          try {
            JSON.parse(this.editForm.connector_body_text)
          } catch (e) {
            this.formError = 'Invalid body JSON: ' + e.message
            return
          }
        }
      }

      if (this.editForm.enrich_type === 'mcp') {
        const mcpError = this.validateMcpForm(this.editForm)
        if (mcpError) {
          this.formError = mcpError
          return
        }
      }

      const outputFields = this.parseOutputFields(this.editForm.enrich_output_fields_text)
      if (outputFields.length === 0) {
        this.formError = 'At least one output field is required.'
        return
      }

      this.submitting = true
      this.formError = ''
      try {
        const payload = {
          enrich_name: this.editForm.enrich_name,
          enrich_data_type: this.editForm.enrich_data_type,
          enrich_type: this.editForm.enrich_type,
          enrich_mapping_function: this.editForm.enrich_mapping_function,
          snippet_code: this.editForm.snippet_code,
          enrich_output_fields: outputFields,
          enrich_description: this.editForm.enrich_description || '',
          info: this.editForm.info || '',
          enabled: this.editForm.enabled === true
        }

        // Add connector_config if connector type
        if (this.editForm.enrich_type === 'connector') {
          payload.connector_config = {
            provider_kind: this.editForm.connector_config.provider_kind,
            timeout_seconds: this.editForm.connector_config.timeout_seconds,
            retry_count: this.editForm.connector_config.retry_count,
            verify_ssl: this.editForm.connector_config.verify_ssl !== false,
            request_template: this.buildConnectorRequestTemplate(this.editForm),
            response_mapping: this.buildResponseMapping(this.editForm.connector_response_rows)
          }
        }
        if (this.editForm.enrich_type === 'mcp') {
          payload.mcp_config = this.buildMcpConfig(this.editForm)
        }

        const res = await apiFetch('/api/data_enrichments/update', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        })
        const data = await res.json()
        if (!res.ok) {
          this.formError = data.message || 'Failed to update data enrichment.'
          return
        }

        this.message = data.message || 'Data enrichment updated successfully.'
        this.messageType = 'success'
        this.closeEditModal()
        await this.fetchEnrichments()
      } catch (e) {
        this.formError = 'Network error while updating data enrichment.'
      } finally {
        this.submitting = false
      }
    },
    async testConnectorPreview(formType) {
      const form = formType === 'create' ? this.createForm : this.editForm

      if (!form.connector_config.provider_kind) {
        this.testConnectorResult = { error: 'Provider kind is required' }
        return
      }

      const targetError = this.validateConnectorTarget(form)
      if (targetError) {
        this.testConnectorResult = { error: targetError }
        return
      }

      const _testMapping = this.buildResponseMapping(form.connector_response_rows)
      if (Object.keys(_testMapping).length === 0) {
        this.testConnectorResult = { error: 'At least one response mapping row is required' }
        return
      }

      if (form.connector_body_text && form.connector_body_text.trim()) {
        try {
          JSON.parse(form.connector_body_text)
        } catch (e) {
          this.testConnectorResult = { error: 'Invalid body JSON: ' + e.message }
          return
        }
      }

      this.testingConnector = true
      this.testConnectorResult = null

      try {
        const sampleValue = this.testSampleValue || this.defaultSampleValue(form.enrich_data_type)
        let outputFields = this.parseOutputFields(form.enrich_output_fields_text)
        if (outputFields.length === 0) {
          // For test mode, infer output fields from mapping keys when the textbox is blank.
          outputFields = Object.keys(_testMapping)
        }

        const res = await apiFetch('/api/data_enrichments/test-connector', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            value: sampleValue,
            dtype: form.enrich_data_type,
            connector_config: {
              provider_kind: form.connector_config.provider_kind,
              timeout_seconds: form.connector_config.timeout_seconds,
              retry_count: form.connector_config.retry_count,
              verify_ssl: form.connector_config.verify_ssl !== false,
              request_template: this.buildConnectorRequestTemplate(form),
              response_mapping: _testMapping
            },
            enrich_output_fields: outputFields
          })
        })
        const data = await res.json()

        if (!res.ok) {
          this.testConnectorResult = {
            error: data.message || 'Test failed',
            details: data.preview || data
          }
        } else {
          this.testConnectorResult = {
            success: true,
            preview: data.preview || data.mapped_result,
            meta: data.meta || {}
          }
        }
      } catch (e) {
        this.testConnectorResult = { error: 'Network error: ' + e.message }
      } finally {
        this.testingConnector = false
      }
    },
    async testMcpPreview(formType) {
      const form = formType === 'create' ? this.createForm : this.editForm

      const mcpError = this.validateMcpForm(form)
      if (mcpError) {
        this.testConnectorResult = { error: mcpError }
        return
      }

      const mcpConfig = this.buildMcpConfig(form)
      let outputFields = this.parseOutputFields(form.enrich_output_fields_text)
      if (outputFields.length === 0) {
        // For test mode, infer output fields from mapping keys, else preview the whole result.
        outputFields = Object.keys(mcpConfig.response_mapping)
        if (outputFields.length === 0) outputFields = ['result']
      }

      this.testingConnector = true
      this.testConnectorResult = null

      try {
        const sampleValue = this.testSampleValue || this.defaultSampleValue(form.enrich_data_type)
        const res = await apiFetch('/api/data_enrichments/test-mcp', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            value: sampleValue,
            dtype: form.enrich_data_type,
            mcp_config: mcpConfig,
            enrich_output_fields: outputFields
          })
        })
        const data = await res.json()

        if (!res.ok) {
          this.testConnectorResult = {
            error: data.message || 'Test failed',
            details: data.preview || data
          }
        } else {
          this.testConnectorResult = {
            success: true,
            preview: data.preview?.mapped_result,
            meta: data.preview?.meta || {}
          }
        }
      } catch (e) {
        this.testConnectorResult = { error: 'Network error: ' + e.message }
      } finally {
        this.testingConnector = false
      }
    }
  }
}
</script>

<style scoped>
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1050;
}

.modal-content {
  background: white;
  border-radius: 12px;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.2);
  width: 90%;
  max-height: 90vh;
  overflow-y: auto;
}

.modal-header {
  padding: 1rem 1.25rem;
  border-bottom: 1px solid #e9ecef;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.modal-body {
  padding: 1.25rem;
}

.modal-footer {
  padding: 1rem 1.25rem;
  border-top: 1px solid #e9ecef;
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
}

.info-row {
  white-space: pre-line;
}

.info-button {
  width: 1.5rem;
  height: 1.5rem;
  border-radius: 999px;
  padding: 0;
  line-height: 1;
  font-weight: 600;
}
</style>
