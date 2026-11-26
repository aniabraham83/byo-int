<template>
  <div class="container mt-4 pb-5">
    <!-- Page Header -->
    <div class="d-flex justify-content-between align-items-center mb-4">
      <div>
        <h2 class="mb-1">Datapull Workflows</h2>
        <p class="text-muted">Manage and monitor your data extraction workflows</p>
      </div>
      <div class="d-flex gap-2">
        <button class="btn btn-outline-danger" @click="openSecurityReportModal()" :disabled="securityReportLoading" title="Show datapull integrity report for scheduled workflows">
          <span v-if="securityReportLoading" class="spinner-border spinner-border-sm me-2"></span>
          Integrity Check
        </button>
        <div class="field-filter-container">
          <button class="btn btn-outline-secondary" @click="toggleFieldFilter" title="Toggle columns">
            ⚙️
          </button>
          <div v-if="showFieldFilter" class="field-filter-dropdown">
            <div class="field-filter-header">Select columns to display:</div>
            <div class="field-filter-items">
              <label v-for="field in availableFields" :key="field" class="field-filter-item">
                <input type="checkbox" v-model="visibleFields" :value="field" @change="saveFieldPreferences">
                <span>{{ formatFieldName(field) }}</span>
              </label>
            </div>
            <div class="field-filter-footer">
              <button class="btn btn-sm btn-link" @click="selectAllFields">Select All</button>
              <button class="btn btn-sm btn-link" @click="clearAllFields">Clear All</button>
            </div>
          </div>
        </div>
        <button class="btn btn-primary btn-lg" @click="openAddModal" title="Add new datapull workflow">
          <i class="me-2">+</i> New Datapull
        </button>
      </div>
    </div>

    <!-- Loading State -->
    <div v-if="loading" class="mt-3">
      <div class="spinner-border text-primary" role="status">
        <span class="visually-hidden">Loading...</span>
      </div>
    </div>

    <!-- Workflows Table -->
    <div v-else>
      <div v-if="workflows.length === 0" class="alert alert-info">
        <i class="me-2">ℹ️</i> No datapull workflows found. <a href="#" @click.prevent="openAddModal">Create one</a>
      </div>
      <div v-else class="table-responsive">
        <table class="table table-striped table-hover">
          <thead class="table-light">
            <tr>
              <th v-if="isFieldVisible('source')">Source</th>
              <th v-if="isFieldVisible('category')">Category</th>
              <th v-if="isFieldVisible('type')">Type</th>
              <th v-if="isFieldVisible('tag')">Tag</th>
              <th v-if="isFieldVisible('template')">Template</th>
              <th v-if="isFieldVisible('function')">Function</th>
              <th v-if="isFieldVisible('br_score')">BR Score</th>
              <th v-if="isFieldVisible('scheduled')">Scheduled</th>
              <th v-if="isFieldVisible('interval')">Interval</th>
              <th v-if="isFieldVisible('enabled')">Enabled</th>
              <th v-if="isFieldVisible('enrichment')">Enrichment</th>
              <th v-if="isFieldVisible('created')">Created</th>
              <th v-if="isFieldVisible('payload')">Payload</th>
              <th v-if="isFieldVisible('edit')">Edit</th>
              <th v-if="isFieldVisible('logs')">Logs</th>
              <th v-if="isFieldVisible('integrity')">Integrity</th>
              <th v-if="isFieldVisible('scheduler')">Scheduler Job</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="wf in workflows" :key="wf.source_name + wf.creation_time">
              <td v-if="isFieldVisible('source')"><strong>{{ wf.source_name }}</strong></td>
              <td v-if="isFieldVisible('category')">
                {{ wf.source_category }}
                <button v-if="wf.source_category === 'dynamic'" class="btn btn-sm btn-outline-success ms-2" @click="runAdhocJob(wf)" title="Run Adhoc Job">
                  ▶
                </button>
              </td>
              <td v-if="isFieldVisible('type')">{{ wf.source_type || '-' }}</td>
              <td v-if="isFieldVisible('tag')">{{ wf.tag || '-' }}</td>
              <td v-if="isFieldVisible('template')"><span class="badge bg-info">{{ wf.source_template_type }}</span></td>
              <td v-if="isFieldVisible('function')"><code>{{ wf.datapull_function }}</code></td>
              <td v-if="isFieldVisible('br_score')">{{ wf.br_score !== undefined && wf.br_score !== null ? wf.br_score : '-' }}</td>
              <td v-if="isFieldVisible('scheduled')">{{ wf.scheduled }}</td>
              <td v-if="isFieldVisible('interval')">{{ wf.scheduled ? `${wf.schedule_interval_min} min` : '-' }}</td>
              <td v-if="isFieldVisible('enabled')">
                <span v-if="wf.enabled" class="badge bg-success">Yes</span>
                <span v-else class="badge bg-secondary">No</span>
              </td>
              <td v-if="isFieldVisible('enrichment')">
                <span v-if="Array.isArray(wf.selected_enrichments) && wf.selected_enrichments.length" class="small">
                  {{ wf.selected_enrichments.join(', ') }}
                </span>
                <span v-else class="badge bg-secondary">None</span>
              </td>
              <td v-if="isFieldVisible('created')"><small>{{ wf.creation_time }}</small></td>
              <td v-if="isFieldVisible('payload')"><pre style="white-space:pre-wrap;word-break:break-word;font-size:0.75rem;max-height:100px;overflow:auto">{{ formatPayload(wf.datapull_payload) }}</pre></td>
              <td v-if="isFieldVisible('edit')">
                <button class="btn btn-sm btn-warning" @click="openEditModal(wf)">Edit</button>
              </td>
              <td v-if="isFieldVisible('logs')">
                <button class="btn btn-sm btn-info" @click="openLogsModal(wf)">View Logs</button>
              </td>
              <td v-if="isFieldVisible('integrity')">
                <button class="btn btn-sm btn-outline-danger" @click="openSecurityReportModal(wf.source_name)">Integrity</button>
              </td>
              <td v-if="isFieldVisible('scheduler')">
                <span v-if="wf.scheduler_job">
                  <span class="badge bg-success">Active</span>
                  <span class="ms-2">Next: {{ wf.scheduler_job.next_run_time ? new Date(wf.scheduler_job.next_run_time).toLocaleString() : 'N/A' }}</span>
                </span>
                <span v-else class="badge bg-secondary">None</span>
              </td>
    <!-- Execution Logs Modal (single, outside table) -->
    <div v-if="showLogsModal" class="modal-overlay" @click.self="closeLogsModal">
      <div class="modal-content" style="max-width:700px;">
        <div class="modal-header">
          <h5 class="modal-title">Execution Logs: {{ logsModalSourceName }}</h5>
          <button type="button" class="btn-close" @click="closeLogsModal"></button>
        </div>
        <div class="modal-body">
          <DataPullExecutionLogs :sourceName="logsModalSourceName" @close="closeLogsModal" />
        </div>
      </div>
    </div>
    <!-- Edit Datapull Modal (single, outside table) -->
    <div v-if="showEditModal" class="modal-overlay" @click.self="closeEditModal">
      <div class="modal-content">
        <div class="modal-header">
          <h5 class="modal-title">Edit Datapull Workflow</h5>
          <button type="button" class="btn-close" @click="closeEditModal"></button>
        </div>
        <div class="modal-body">
          <form @submit.prevent="submitEditDatapull">
                        <div class="mb-3">
                          <label class="form-label">Source Name</label>
                          <input v-model="editFormData.source_name" type="text" class="form-control" disabled>
                        </div>
                        <div class="mb-3">
                          <label class="form-label">Source Category</label>
                          <input v-model="editFormData.source_category" type="text" class="form-control" disabled>
                        </div>
                        <div class="mb-3">
                          <label class="form-label">Source Type</label>
                          <input v-model="editFormData.source_type" type="text" class="form-control" disabled>
                        </div>
                        <div class="mb-3">
                          <label class="form-label">Tag</label>
                          <select v-model="editFormData.tag" class="form-select">
                            <option value="">-- Select Tag --</option>
                            <option v-for="tag in tagOptions" :key="tag.tag" :value="tag.tag">{{ tag.tag }}</option>
                          </select>
                        </div>
                        <div class="mb-3">
                          <label class="form-label">Template Type</label>
                          <select v-model="editFormData.source_template_type" class="form-select" disabled>
                            <option value="">-- Select Template --</option>
                            <option value="generic_url_text">Generic URL Text</option>
                            <option value="custom_api">Custom API</option>
                            <option value="file_upload">File Upload</option>
                          </select>
                        </div>
                        <div class="mb-3">
                          <label class="form-label">BR Score</label>
                          <input v-model.number="editFormData.br_score" type="number" min="0" class="form-control">
                        </div>
                        <div class="mb-3">
                          <label class="form-label">Enable Scheduling?</label>
                          <div class="form-check">
                            <input v-model="editFormData.scheduled" type="checkbox" class="form-check-input" id="editScheduled">
                            <label class="form-check-label" for="editScheduled">Run on schedule</label>
                          </div>
                        </div>
                        <div v-if="editFormData.scheduled" class="mb-3">
                          <label class="form-label">Interval (minutes)</label>
                          <input v-model.number="editFormData.schedule_interval_min" type="number" class="form-control">
                        </div>
                        <div class="mb-3">
                          <div class="form-check">
                            <input v-model="editFormData.insertmany" type="checkbox" class="form-check-input" id="editInsertmany">
                            <label class="form-check-label" for="editInsertmany">Insert Many (batch indicator writes for large feeds)</label>
                          </div>
                          <div class="form-text">Disabled by default. Enable for scheduled workflows that pull a large volume of indicators.</div>
                        </div>
                        <div class="mb-3">
                          <label class="form-label">Max Response Size (bytes)</label>
                          <input v-model.number="editFormData.max_response_bytes" type="number" min="1" class="form-control" placeholder="Global default">
                          <div class="form-text">Leave blank to use the global default configured under Configuration.</div>
                        </div>
                        <div class="mb-3">
                          <label class="form-label">Max Query Rows</label>
                          <input v-model.number="editFormData.max_query_rows" type="number" min="1" class="form-control" placeholder="Global default">
                          <div class="form-text">Applies to DB/Mongo query templates. Leave blank to use the global default.</div>
                        </div>
                        <div v-if="editFormData.source_category === 'dynamic'" class="card border-light bg-light mb-3">
                          <div class="card-body py-3">
                            <label class="form-label">API Response Extraction</label>
                            <select v-model="editFormData.response_mode" class="form-select mb-2">
                              <option value="walk_everything">Walk everything</option>
                              <option value="schema">Use schema path(s)</option>
                            </select>
                            <div class="form-text mb-2">Use <code>$.data.ipv4</code> style JSON paths. Type is inferred automatically from extracted value.</div>
                            <div v-if="editFormData.response_mode === 'schema'">
                              <div class="d-flex justify-content-between align-items-center mb-2">
                                <label class="form-label mb-0">Value Paths</label>
                                <button type="button" class="btn btn-outline-secondary btn-sm" @click="editFormData.response_paths.push('')">+ Add Path</button>
                              </div>
                              <div v-for="(path, idx) in editFormData.response_paths" :key="`edit_path_${idx}`" class="d-flex gap-2 mb-2 align-items-center">
                                <input v-model.trim="editFormData.response_paths[idx]" type="text" class="form-control font-monospace" placeholder="$.data.ipv4">
                                <button type="button" class="btn btn-outline-danger btn-sm px-2" @click="editFormData.response_paths.splice(idx, 1)" :disabled="editFormData.response_paths.length === 1">×</button>
                              </div>
                            </div>
                          </div>
                        </div>
                        <div class="mb-3">
                          <label class="form-label">Selected Enrichments</label>
                          <input
                            v-model="enrichmentSearchQueryEdit"
                            type="text"
                            class="form-control mb-2"
                            placeholder="Search enrichments..."
                          >
                          <div class="border rounded p-2" style="max-height: 160px; overflow-y: auto;">
                            <div v-if="filteredEnrichmentsEdit.length === 0" class="text-muted small">No enrichments found.</div>
                            <div v-for="enrichment in filteredEnrichmentsEdit" :key="enrichment.enrich_name" class="form-check">
                              <input
                                :id="`edit_enrich_${enrichment.enrich_name}`"
                                v-model="editFormData.selected_enrichments"
                                class="form-check-input"
                                type="checkbox"
                                :value="enrichment.enrich_name"
                              >
                              <label class="form-check-label" :for="`edit_enrich_${enrichment.enrich_name}`">{{ enrichment.enrich_name }}</label>
                            </div>
                          </div>
                          <div v-if="editFormData.selected_enrichments.length" class="mt-2 d-flex flex-wrap gap-1">
                            <span v-for="name in editFormData.selected_enrichments" :key="`editbadge_${name}`" class="badge bg-secondary d-inline-flex align-items-center">
                              {{ name }}
                              <button type="button" class="btn-close btn-close-white ms-1" style="font-size:0.6rem;" @click="editFormData.selected_enrichments = editFormData.selected_enrichments.filter(n => n !== name)"></button>
                            </span>
                            <button type="button" class="btn btn-sm btn-outline-secondary" @click="editFormData.selected_enrichments = []">Clear all</button>
                          </div>
                        </div>
                      </form>
                    </div>
                    <div class="modal-footer">
                      <button type="button" class="btn btn-danger me-auto" @click="openDeleteModal({ source_name: editFormData.source_name })" :disabled="isEditSubmitting || !editFormData.source_name">
                        Delete Workflow
                      </button>
                      <button type="button" class="btn btn-secondary" @click="closeEditModal">Cancel</button>
                      <button type="button" class="btn btn-primary" @click="submitEditDatapull" :disabled="isEditSubmitting">
                        <span v-if="isEditSubmitting" class="spinner-border spinner-border-sm me-2"></span>
                        {{ isEditSubmitting ? 'Saving...' : 'Save Changes' }}
                      </button>
                    </div>
                  </div>
                </div>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Adhoc Job Execution Modal -->
    <div v-if="showAdhocJobModal" class="modal-overlay" @click.self="closeAdhocJobModal">
      <div class="modal-content" style="max-width: 700px; min-height: 400px;">
        <div class="modal-header">
          <h5 class="modal-title">Adhoc Job Execution: {{ adhocJobSourceName }}</h5>
          <button v-if="!adhocJobRunning" type="button" class="btn-close" @click="closeAdhocJobModal"></button>
        </div>
        <div class="modal-body">
          <div class="adhoc-job-output">
            <div v-if="adhocJobOutput.length === 0" class="text-muted">
              Waiting for job to start...
            </div>
            <div v-for="(log, index) in adhocJobOutput" :key="index" class="adhoc-log-line">
              <span class="adhoc-log-time">{{ log.timestamp }}</span>
              <span class="adhoc-log-message">{{ log.message }}</span>
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <button v-if="!adhocJobRunning" type="button" class="btn btn-secondary" @click="closeAdhocJobModal">Close</button>
          <button v-else type="button" class="btn btn-secondary" disabled>
            <span class="spinner-border spinner-border-sm me-2"></span>
            Running...
          </button>
        </div>
      </div>
    </div>

    <!-- Add Datapull Modal -->
    <div v-if="showAddModal" class="modal-overlay" @click.self="closeAddModal">
      <div class="modal-content">
        <div class="modal-header">
          <h5 class="modal-title">Create New Datapull Workflow</h5>
          <button type="button" class="btn-close" @click="closeAddModal"></button>
        </div>
        <div class="modal-body">
          <form @submit.prevent="submitNewDatapull">
            <div class="mb-3">
              <label for="sourceName" class="form-label">Source Name</label>
              <input v-model="formData.source_name" type="text" class="form-control" id="sourceName" placeholder="e.g., osint-feed-1" required>
            </div>
            <div class="mb-3">
              <label for="sourceCategory" class="form-label">Source Category</label>
              <select v-model="formData.source_category" class="form-select" id="sourceCategory" required @change="onCategoryChange">
                <option value="">-- Select Category --</option>
                <option value="static">Static</option>
                <option value="dynamic">Dynamic</option>
              </select>
            </div>
            <div class="mb-3">
              <label for="sourceType" class="form-label">Source Type</label>
              <select v-model="formData.source_type" class="form-select" id="sourceType" required>
                <option value="">-- Select Source Type --</option>
                <option v-for="type in sourceTypeOptions" :key="type" :value="type">
                  {{ type }}
                </option>
              </select>
            </div>
            <div class="mb-3">
              <label for="tagField" class="form-label">Tag</label>
              <select v-model="formData.tag" class="form-select" id="tagField">
                <option value="">-- Select Tag --</option>
                <option v-for="tag in tagOptions" :key="tag.tag" :value="tag.tag">
                  {{ tag.tag }}
                </option>
              </select>
            </div>
            <div class="mb-3">
              <label for="templateType" class="form-label">Template Type</label>
              <select v-model="formData.source_template_type" class="form-select" id="templateType" required :disabled="formData.source_category === 'static'" @change="onTemplateChange">
                <option value="">-- Select Template --</option>
                <option v-for="template in datapullTemplates" :key="template.template_name" :value="template.template_name">
                  {{ template.template_name }}
                </option>
              </select>
            </div>
            <!-- Dynamic Fields from Template -->
            <div v-if="currentTemplateFields.length > 0">
              <div v-for="field in currentTemplateFields" :key="field.name" class="mb-3">
                <label :for="'field_' + field.name" class="form-label">
                  {{ formatFieldLabel(field.name) }}
                  <span v-if="field.required" class="text-danger">*</span>
                </label>
                <div v-if="isBooleanField(field.name)" class="form-check">
                  <input
                    :id="'field_' + field.name"
                    v-model="formData.dynamicFields[field.name]"
                    type="checkbox"
                    class="form-check-input"
                  >
                  <label class="form-check-label" :for="'field_' + field.name">
                    {{ field.description || 'Enabled' }}
                  </label>
                </div>
                <div v-else-if="isSecretRefField(field.name)">
                  <select
                    :id="'field_' + field.name"
                    v-model="formData.dynamicFields[field.name]"
                    class="form-select"
                    :required="field.required"
                  >
                    <option value="">-- Select Secret Reference --</option>
                    <option v-for="secret in datapullSecrets" :key="secret.secret_ref" :value="secret.secret_ref">
                      {{ formatSecretOptionLabel(secret) }}
                    </option>
                  </select>
                  <small class="text-muted" v-if="datapullSecrets.length === 0">
                    No active secrets available. Create one in the Secrets page first.
                  </small>
                </div>
                <input
                  v-else
                  :id="'field_' + field.name"
                  v-model="formData.dynamicFields[field.name]"
                  type="text"
                  class="form-control"
                  :placeholder="field.description || ''"
                  :required="field.required"
                >
              </div>
            </div>
            <div v-if="showMysqlQueryHelper" class="card border-info mb-3">
              <div class="card-header bg-info-subtle">
                <strong>MySQL Query Helper</strong>
              </div>
              <div class="card-body">
                <div class="mb-2">
                  <label class="form-label">Table Name</label>
                  <input v-model.trim="mysqlQueryHelper.tableName" type="text" class="form-control" placeholder="e.g., indicators_source">
                </div>
                <div class="mb-2">
                  <label class="form-label">Field Name(s)</label>
                  <input v-model.trim="mysqlQueryHelper.fieldNames" type="text" class="form-control" placeholder="e.g., ip_address or ip_address, domain">
                </div>
                <div class="d-flex gap-2">
                  <button type="button" class="btn btn-sm btn-outline-info" @click="generateMysqlQueryFromHelper">Generate Query</button>
                  <small class="text-muted align-self-center">Writes into the <strong>Db Query</strong> field above.</small>
                </div>
              </div>
            </div>
            <div v-else-if="formData.source_category === 'dynamic' && formData.source_template_type" class="alert alert-warning small">
              <strong>No fields configured</strong> for this template. Check that the template has <code>ufield_args</code> defined in the database.
            </div>
            <div v-if="formData.source_category === 'dynamic'" class="card border-light bg-light mb-3">
              <div class="card-body py-3">
                <label class="form-label">API Response Extraction</label>
                <select v-model="formData.response_mode" class="form-select mb-2">
                  <option value="walk_everything">Walk everything</option>
                  <option value="schema">Use schema path(s)</option>
                </select>
                <div class="form-text mb-2">Use <code>$.data.ipv4</code> style JSON paths. Type is inferred automatically from extracted value.</div>
                <div v-if="formData.response_mode === 'schema'">
                  <div class="d-flex justify-content-between align-items-center mb-2">
                    <label class="form-label mb-0">Value Paths</label>
                    <button type="button" class="btn btn-outline-secondary btn-sm" @click="formData.response_paths.push('')">+ Add Path</button>
                  </div>
                  <div v-for="(path, idx) in formData.response_paths" :key="`create_path_${idx}`" class="d-flex gap-2 mb-2 align-items-center">
                    <input v-model.trim="formData.response_paths[idx]" type="text" class="form-control font-monospace" placeholder="$.data.ipv4">
                    <button type="button" class="btn btn-outline-danger btn-sm px-2" @click="formData.response_paths.splice(idx, 1)" :disabled="formData.response_paths.length === 1">×</button>
                  </div>
                </div>
              </div>
            </div>
            <div class="mb-3">
              <label for="brScore" class="form-label">BR Score</label>
              <input v-model.number="formData.br_score" type="number" min="0" class="form-control" id="brScore" placeholder="0">
            </div>
            <div class="mb-3">
              <label for="scheduled" class="form-label">Enable Scheduling?</label>
              <div class="form-check">
                <input v-model="formData.scheduled" type="checkbox" class="form-check-input" id="scheduled">
                <label class="form-check-label" for="scheduled">Run on schedule</label>
              </div>
            </div>
            <div v-if="formData.scheduled" class="mb-3">
              <label for="interval" class="form-label">Interval (minutes)</label>
              <input v-model.number="formData.schedule_interval_min" type="number" class="form-control" id="interval" placeholder="60">
            </div>
            <div class="mb-3">
              <div class="form-check">
                <input v-model="formData.insertmany" type="checkbox" class="form-check-input" id="insertmany">
                <label class="form-check-label" for="insertmany">Insert Many (batch indicator writes for large feeds)</label>
              </div>
              <div class="form-text">Disabled by default. Enable for scheduled workflows that pull a large volume of indicators.</div>
            </div>
            <div class="mb-3">
              <label for="maxResponseBytes" class="form-label">Max Response Size (bytes)</label>
              <input v-model.number="formData.max_response_bytes" type="number" min="1" class="form-control" id="maxResponseBytes" placeholder="Global default">
              <div class="form-text">Leave blank to use the global default configured under Configuration.</div>
            </div>
            <div class="mb-3">
              <label for="maxQueryRows" class="form-label">Max Query Rows</label>
              <input v-model.number="formData.max_query_rows" type="number" min="1" class="form-control" id="maxQueryRows" placeholder="Global default">
              <div class="form-text">Applies to DB/Mongo query templates. Leave blank to use the global default.</div>
            </div>
            <div class="mb-3">
              <label class="form-label">Selected Enrichments</label>
              <input
                v-model="enrichmentSearchQueryCreate"
                type="text"
                class="form-control mb-2"
                placeholder="Search enrichments..."
              >
              <div class="border rounded p-2" style="max-height: 160px; overflow-y: auto;">
                <div v-if="filteredEnrichmentsCreate.length === 0" class="text-muted small">No enrichments found.</div>
                <div v-for="enrichment in filteredEnrichmentsCreate" :key="enrichment.enrich_name" class="form-check">
                  <input
                    :id="`create_enrich_${enrichment.enrich_name}`"
                    v-model="formData.selected_enrichments"
                    class="form-check-input"
                    type="checkbox"
                    :value="enrichment.enrich_name"
                  >
                  <label class="form-check-label" :for="`create_enrich_${enrichment.enrich_name}`">{{ enrichment.enrich_name }}</label>
                </div>
              </div>
              <div v-if="formData.selected_enrichments.length" class="mt-2 d-flex flex-wrap gap-1">
                <span v-for="name in formData.selected_enrichments" :key="`createbadge_${name}`" class="badge bg-secondary d-inline-flex align-items-center">
                  {{ name }}
                  <button type="button" class="btn-close btn-close-white ms-1" style="font-size:0.6rem;" @click="formData.selected_enrichments = formData.selected_enrichments.filter(n => n !== name)"></button>
                </span>
                <button type="button" class="btn btn-sm btn-outline-secondary" @click="formData.selected_enrichments = []">Clear all</button>
              </div>
            </div>
            <div class="alert alert-warning small">
              <strong>Note:</strong> This will create a new datapull workflow entry. Ensure all fields are correctly filled.
            </div>
          </form>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" @click="closeAddModal">Cancel</button>
          <button type="button" class="btn btn-primary" @click="submitNewDatapull" :disabled="isSubmitting">
            <span v-if="isSubmitting" class="spinner-border spinner-border-sm me-2"></span>
            {{ isSubmitting ? 'Creating...' : 'Create Workflow' }}
          </button>
        </div>
      </div>
    </div>

    <!-- Security Report Modal -->
    <div v-if="showSecurityReportModal" class="modal-overlay" @click.self="closeSecurityReportModal">
      <div class="modal-content" style="max-width: 900px;">
        <div class="modal-header">
          <h5 class="modal-title">Datapull Integrity Check</h5>
          <button type="button" class="btn-close" @click="closeSecurityReportModal"></button>
        </div>
        <div class="modal-body">
          <div v-if="selectedIntegritySourceName" class="alert alert-light border small">
            Source: <strong>{{ selectedIntegritySourceName }}</strong>
          </div>
          <div class="d-flex justify-content-between align-items-center mb-3">
            <small class="text-muted">Checked: {{ securityReport.checked_at || '-' }}</small>
            <button class="btn btn-sm btn-outline-primary" @click="fetchSecurityReport(selectedIntegritySourceName)" :disabled="securityReportLoading">
              <span v-if="securityReportLoading" class="spinner-border spinner-border-sm me-2"></span>
              Refresh
            </button>
          </div>

          <div v-if="securityReportError" class="alert alert-danger small">{{ securityReportError }}</div>

          <div v-if="!securityReportError && !isSingleIntegrityView" class="row g-2 mb-3">
            <div class="col-md-3"><div class="alert alert-secondary mb-0 py-2">Checked: <strong>{{ securityReport.total_workflows_checked ?? 0 }}</strong></div></div>
            <div class="col-md-3"><div class="alert alert-success mb-0 py-2">Healthy: <strong>{{ securityReport.healthy_workflows ?? 0 }}</strong></div></div>
            <div class="col-md-3"><div class="alert alert-warning mb-0 py-2">Watch: <strong>{{ securityReport.watch_workflows ?? 0 }}</strong></div></div>
            <div class="col-md-3"><div class="alert alert-danger mb-0 py-2">Risk: <strong>{{ securityReport.risk_workflows ?? 0 }}</strong></div></div>
          </div>

          <div v-if="!securityReportError && !isSingleIntegrityView" class="row g-2 mb-3">
            <div class="col-md-4"><div class="alert alert-info mb-0 py-2">Avg Score: <strong>{{ securityReport.avg_integrity_score ?? 0 }}</strong></div></div>
            <div class="col-md-4"><div class="alert alert-light border mb-0 py-2">Mode: <strong>{{ securityReport.mode || 'scheduled_only' }}</strong></div></div>
            <div class="col-md-4"><div class="alert alert-light border mb-0 py-2">Rows: <strong>{{ (securityReport.workflows || []).length }}</strong></div></div>
          </div>

          <div v-if="!securityReportError && integrityRows.length === 0" class="alert alert-success small mb-0">
            {{ isSingleIntegrityView ? 'No integrity data found for this datapull.' : 'No datapulls need attention in this scope.' }}
          </div>

          <div v-else-if="!securityReportError && isSingleIntegrityView" class="table-responsive">
            <table class="table table-sm table-striped mb-0">
              <tbody v-if="integrityRows[0]">
                <tr>
                  <th class="w-25">Score</th>
                  <td><strong>{{ integrityRows[0].integrity_score ?? 0 }}</strong></td>
                </tr>
                <tr>
                  <th>Status</th>
                  <td>
                    <span class="badge" :class="integrityBadgeClass(integrityRows[0].integrity_status)">{{ formatIntegrityStatus(integrityRows[0].integrity_status) }}</span>
                  </td>
                </tr>
                <tr>
                  <th>Runs</th>
                  <td class="small">{{ integrityRows[0].success_runs ?? 0 }}/{{ integrityRows[0].total_runs_considered ?? 0 }}</td>
                </tr>
                <tr>
                  <th>Error Rate</th>
                  <td class="small">{{ integrityRows[0].error_rate_pct ?? 0 }}%</td>
                </tr>
                <tr>
                  <th>Latest Count</th>
                  <td class="small">{{ integrityRows[0].latest_extracted_count !== null && integrityRows[0].latest_extracted_count !== undefined ? integrityRows[0].latest_extracted_count : '-' }}</td>
                </tr>
                <tr>
                  <th>Last Success</th>
                  <td class="small">{{ formatDateTime(integrityRows[0].last_success_at) }}</td>
                </tr>
                <tr>
                  <th>Signals</th>
                  <td class="small">{{ formatIntegrityReasons(integrityRows[0].reasons) }}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div v-else-if="!securityReportError" class="table-responsive">
            <table class="table table-sm table-striped table-hover mb-0">
              <thead class="table-light">
                <tr>
                  <th v-if="!isSingleIntegrityView">Source</th>
                  <th>Score</th>
                  <th>Status</th>
                  <th>Runs</th>
                  <th>Error Rate</th>
                  <th>Latest Count</th>
                  <th>Last Success</th>
                  <th>Signals</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in integrityRows" :key="`${row.source_name}_${row.source_template_type}`">
                  <td v-if="!isSingleIntegrityView">{{ row.source_name || '-' }}</td>
                  <td><strong>{{ row.integrity_score ?? 0 }}</strong></td>
                  <td>
                    <span class="badge" :class="integrityBadgeClass(row.integrity_status)">{{ formatIntegrityStatus(row.integrity_status) }}</span>
                  </td>
                  <td class="small">{{ row.success_runs ?? 0 }}/{{ row.total_runs_considered ?? 0 }}</td>
                  <td class="small">{{ row.error_rate_pct ?? 0 }}%</td>
                  <td class="small">{{ row.latest_extracted_count !== null && row.latest_extracted_count !== undefined ? row.latest_extracted_count : '-' }}</td>
                  <td class="small">{{ formatDateTime(row.last_success_at) }}</td>
                  <td class="small">{{ formatIntegrityReasons(row.reasons) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>

    <!-- Delete Datapull Modal -->
    <div v-if="showDeleteModal" class="modal-overlay" @click.self="closeDeleteModal">
      <div class="modal-content" style="max-width: 820px;">
        <div class="modal-header">
          <h5 class="modal-title">Delete Datapull Workflow: {{ deleteTargetWorkflow ? deleteTargetWorkflow.source_name : '' }}</h5>
          <button type="button" class="btn-close" @click="closeDeleteModal"></button>
        </div>
        <div class="modal-body">
          <div v-if="deletePreviewLoading" class="text-muted">
            <span class="spinner-border spinner-border-sm me-2"></span>
            Loading indicator impact analysis...
          </div>
          <div v-else>
            <div class="alert alert-warning small">
              This action removes the datapull workflow and applies indicator cleanup rules shown below.
            </div>

            <div class="row g-2 mb-3" v-if="deletePreview">
              <div class="col-md-4"><div class="alert alert-secondary mb-0 py-2">Impacted: <strong>{{ deletePreview.impacted_indicator_count ?? 0 }}</strong></div></div>
              <div class="col-md-4"><div class="alert alert-danger mb-0 py-2">Will be deleted: <strong>{{ deletePreview.delete_indicator_count ?? 0 }}</strong></div></div>
              <div class="col-md-4"><div class="alert alert-info mb-0 py-2">Set active=N: <strong>{{ deletePreview.deactivate_source_entry_count ?? 0 }}</strong></div></div>
            </div>

            <div class="small mb-3" v-if="deletePreview && Array.isArray(deletePreview.rules)">
              <div v-for="(rule, idx) in deletePreview.rules" :key="`rule_${idx}`">{{ idx + 1 }}. {{ rule }}</div>
            </div>

            <div v-if="deletePreview" class="mb-3">
              <div class="d-flex justify-content-between align-items-center mb-2">
                <h6 class="mb-0">Indicator Values Preview (Delete)</h6>
                <small class="text-muted">Showing up to {{ Array.isArray(deletePreview.delete_indicator_samples) ? deletePreview.delete_indicator_samples.length : 0 }} sample(s)</small>
              </div>
              <div v-if="Array.isArray(deletePreview.delete_indicator_samples) && deletePreview.delete_indicator_samples.length" class="table-responsive border rounded">
                <table class="table table-sm table-striped mb-0">
                  <thead class="table-light">
                    <tr>
                      <th>Value</th>
                      <th>Type</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(sample, idx) in deletePreview.delete_indicator_samples" :key="`delete_sample_${idx}`">
                      <td class="small font-monospace">{{ formatPreviewValue(sample.value) }}</td>
                      <td class="small">{{ sample.type || '-' }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div v-else class="small text-muted">No sample indicators marked for delete.</div>
            </div>

            <div v-if="deletePreview" class="mb-3">
              <div class="d-flex justify-content-between align-items-center mb-2">
                <h6 class="mb-0">Indicator Values Preview (Set active=N)</h6>
                <small class="text-muted">Showing up to {{ Array.isArray(deletePreview.deactivate_indicator_samples) ? deletePreview.deactivate_indicator_samples.length : 0 }} sample(s)</small>
              </div>
              <div v-if="Array.isArray(deletePreview.deactivate_indicator_samples) && deletePreview.deactivate_indicator_samples.length" class="table-responsive border rounded">
                <table class="table table-sm table-striped mb-0">
                  <thead class="table-light">
                    <tr>
                      <th>Value</th>
                      <th>Type</th>
                      <th>Also In Sources</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(sample, idx) in deletePreview.deactivate_indicator_samples" :key="`deactivate_sample_${idx}`">
                      <td class="small font-monospace">{{ formatPreviewValue(sample.value) }}</td>
                      <td class="small">{{ sample.type || '-' }}</td>
                      <td class="small">{{ formatSourceList(sample.also_in_sources) }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div v-else class="small text-muted">No sample indicators marked for source deactivation.</div>
            </div>

            <div v-if="deletePreviewError" class="alert alert-danger small mb-0">{{ deletePreviewError }}</div>
          </div>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" @click="closeDeleteModal" :disabled="isDeleteSubmitting">Cancel</button>
          <button type="button" class="btn btn-danger" @click="confirmDeleteDatapull" :disabled="isDeleteSubmitting || deletePreviewLoading || !!deletePreviewError">
            <span v-if="isDeleteSubmitting" class="spinner-border spinner-border-sm me-2"></span>
            {{ isDeleteSubmitting ? 'Deleting...' : 'Delete Workflow' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import DataPullExecutionLogs from './DataPullExecutionLogs.vue';
import { apiFetch } from '@/api'
export default {
  name: 'DataPullWorkflowsPage',
  components: { DataPullExecutionLogs },
  data() {
    return {
      workflows: [],
      loading: false,
      showAddModal: false,
      isSubmitting: false,
      showLogsModal: false,
      logsModalSourceName: '',
      showEditModal: false,
      isEditSubmitting: false,
      showDeleteModal: false,
      isDeleteSubmitting: false,
      deletePreviewLoading: false,
      deletePreviewError: '',
      deleteTargetWorkflow: null,
      deletePreview: null,
      showAdhocJobModal: false,
      adhocJobOutput: [],
      adhocJobRunning: false,
      adhocJobSourceName: '',
      showFieldFilter: false,
      showSecurityReportModal: false,
      selectedIntegritySourceName: '',
      securityReportLoading: false,
      securityReportError: '',
      securityReport: {
        checked_at: null,
        total_workflows_checked: 0,
        healthy_workflows: 0,
        watch_workflows: 0,
        risk_workflows: 0,
        avg_integrity_score: 0,
        mode: 'scheduled_only',
        workflows: []
      },
      availableFields: ['source', 'category', 'type', 'tag', 'template', 'function', 'br_score', 'scheduled', 'interval', 'enabled', 'enrichment', 'created', 'payload', 'edit', 'logs', 'integrity', 'scheduler'],
      visibleFields: [],
      tagOptions: [],
      editFormData: {
        source_name: '',
        source_category: '',
        source_type: '',
        tag: '',
        source_template_type: '',
        br_score: '',
        scheduled: false,
        schedule_interval_min: 60,
        selected_enrichments: [],
        insertmany: false,
        max_response_bytes: null,
        max_query_rows: null,
        datapull_payload: {},
        response_mode: 'walk_everything',
        response_paths: ['']
      },
      formData: {
        source_name: '',
        source_category: '',
        source_type: '',
        tag: '',
        source_template_type: '',
        br_score: '',
        scheduled: false,
        schedule_interval_min: 60,
        selected_enrichments: [],
        insertmany: false,
        max_response_bytes: null,
        max_query_rows: null,
        dynamicFields: {},
        response_mode: 'walk_everything',
        response_paths: ['']
      },
      datapullTemplates: [],
      datapullSecrets: [],
      currentTemplateFields: [],
      sourceTypeOptions: [],
      dataEnrichmentOptions: [],
      enrichmentSearchQueryCreate: '',
      enrichmentSearchQueryEdit: '',
      mysqlQueryHelper: {
        tableName: '',
        fieldNames: ''
      }
    }
  },
  computed: {
    filteredEnrichmentsCreate() {
      const q = this.enrichmentSearchQueryCreate.toLowerCase()
      if (!q) return this.dataEnrichmentOptions
      return this.dataEnrichmentOptions.filter(e => e.enrich_name.toLowerCase().includes(q))
    },
    filteredEnrichmentsEdit() {
      const q = this.enrichmentSearchQueryEdit.toLowerCase()
      if (!q) return this.dataEnrichmentOptions
      return this.dataEnrichmentOptions.filter(e => e.enrich_name.toLowerCase().includes(q))
    },
    selectedTemplate() {
      return this.datapullTemplates.find(t => t.template_name === this.formData.source_template_type) || null
    },
    showMysqlQueryHelper() {
      return this.formData.source_category === 'dynamic'
        && !!this.formData.source_template_type
        && !!this.selectedTemplate
        && ['mysql_query_v1', 'oracle_query_v1', 'postgresql_query_v1'].includes(this.selectedTemplate.function_mapping)
    },
    isSingleIntegrityView() {
      return !!String(this.selectedIntegritySourceName || '').trim()
    },
    integrityRows() {
      const rows = Array.isArray(this.securityReport.workflows) ? this.securityReport.workflows : []
      return this.isSingleIntegrityView ? rows.slice(0, 1) : rows
    }
  },
  methods: {
    async openSecurityReportModal(sourceName = '') {
      this.selectedIntegritySourceName = String(sourceName || '').trim()
      this.showSecurityReportModal = true
      await this.fetchSecurityReport(this.selectedIntegritySourceName)
    },
    closeSecurityReportModal() {
      this.showSecurityReportModal = false
      this.selectedIntegritySourceName = ''
    },
    async fetchSecurityReport(sourceName = '') {
      this.securityReportLoading = true
      this.securityReportError = ''
      try {
        const normalizedSourceName = String(sourceName || this.selectedIntegritySourceName || '').trim()
        const params = new URLSearchParams()
        if (normalizedSourceName) {
          params.set('source_name', normalizedSourceName)
          params.set('scheduled_only', 'false')
        } else {
          params.set('scheduled_only', 'true')
        }
        const res = await apiFetch(`/api/datapull/integrity-check?${params.toString()}`)
        const data = await res.json()
        if (!res.ok) {
          this.securityReportError = data.message || 'Failed to load integrity check.'
          this.securityReport = {
            checked_at: null,
            total_workflows_checked: 0,
            healthy_workflows: 0,
            watch_workflows: 0,
            risk_workflows: 0,
            avg_integrity_score: 0,
            mode: 'scheduled_only',
            workflows: []
          }
          return
        }

        this.securityReport = {
          checked_at: data.checked_at || null,
          total_workflows_checked: data.total_workflows_checked ?? 0,
          healthy_workflows: data.healthy_workflows ?? 0,
          watch_workflows: data.watch_workflows ?? 0,
          risk_workflows: data.risk_workflows ?? 0,
          avg_integrity_score: data.avg_integrity_score ?? 0,
          mode: data.mode || 'scheduled_only',
          workflows: Array.isArray(data.workflows) ? data.workflows : []
        }
      } catch (e) {
        this.securityReportError = 'Network error while loading integrity check.'
      } finally {
        this.securityReportLoading = false
      }
    },
    formatIntegrityStatus(status) {
      const normalized = String(status || '').toLowerCase()
      if (normalized === 'healthy') return 'Healthy'
      if (normalized === 'watch') return 'Watch'
      if (normalized === 'risk') return 'Risk'
      return '-'
    },
    integrityBadgeClass(status) {
      const normalized = String(status || '').toLowerCase()
      if (normalized === 'healthy') return 'bg-success'
      if (normalized === 'watch') return 'bg-warning text-dark'
      if (normalized === 'risk') return 'bg-danger'
      return 'bg-secondary'
    },
    formatIntegrityReasons(reasons) {
      if (!Array.isArray(reasons) || reasons.length === 0) {
        return '-'
      }
      return reasons.join(' | ')
    },
    formatDateTime(value) {
      if (!value) return '-'
      const parsed = new Date(value)
      if (Number.isNaN(parsed.getTime())) return '-'
      return parsed.toLocaleString()
    },
    toggleFieldFilter() {
      this.showFieldFilter = !this.showFieldFilter;
    },
    isFieldVisible(field) {
      return this.visibleFields.includes(field);
    },
    formatFieldName(field) {
      const names = {
        source: 'Source',
        category: 'Category',
        type: 'Type',
        tag: 'Tag',
        template: 'Template',
        function: 'Function',
        br_score: 'BR Score',
        scheduled: 'Scheduled',
        interval: 'Interval',
        enabled: 'Enabled',
        enrichment: 'Enrichment',
        created: 'Created',
        payload: 'Payload',
        edit: 'Edit',
        logs: 'Logs',
        integrity: 'Integrity',
        scheduler: 'Scheduler Job'
      };
      return names[field] || field;
    },
    saveFieldPreferences() {
      localStorage.setItem('datapull_visible_fields', JSON.stringify(this.visibleFields));
    },
    loadFieldPreferences() {
      const saved = localStorage.getItem('datapull_visible_fields');
      if (saved) {
        try {
          this.visibleFields = JSON.parse(saved);
        } catch (e) {
          this.visibleFields = this.availableFields;
        }
      } else {
        this.visibleFields = this.availableFields;
      }
    },
    selectAllFields() {
      this.visibleFields = [...this.availableFields];
      this.saveFieldPreferences();
    },
    clearAllFields() {
      this.visibleFields = [];
      this.saveFieldPreferences();
    },
    async fetchDatapullTemplates() {
      try {
        const res = await apiFetch('/api/datapull_templates')
        if (res.ok) {
          const data = await res.json()
          this.datapullTemplates = data.templates || []
        } else {
          console.error('API returned non-OK status:', res.status)
        }
      } catch (e) {
        console.error('Error fetching templates:', e)
        this.datapullTemplates = []
      }
    },
    async fetchSourceTypeOptions() {
      try {
        const res = await apiFetch('/api/data_types')
        if (res.ok) {
          const data = await res.json()
          this.sourceTypeOptions = Array.isArray(data.data_types) ? data.data_types : []
        } else {
          this.sourceTypeOptions = []
        }
      } catch (e) {
        console.error('Error fetching source types:', e)
        this.sourceTypeOptions = []
      }
    },
    async fetchTags() {
      try {
        const res = await apiFetch('/api/tags')
        if (res.ok) {
          const data = await res.json()
          this.tagOptions = Array.isArray(data.tags) ? data.tags : []
        } else {
          this.tagOptions = []
        }
      } catch (e) {
        console.error('Error fetching tags:', e)
        this.tagOptions = []
      }
    },
    async fetchDataEnrichmentOptions() {
      try {
        const res = await apiFetch('/api/data_enrichments')
        if (res.ok) {
          const data = await res.json()
          this.dataEnrichmentOptions = Array.isArray(data.enrichments) ? data.enrichments : []
        } else {
          this.dataEnrichmentOptions = []
        }
      } catch (e) {
        console.error('Error fetching data enrichments:', e)
        this.dataEnrichmentOptions = []
      }
    },
    onTemplateChange() {
      this.resetMysqlQueryHelper()
      const selectedTemplate = this.datapullTemplates.find(
        t => t.template_name === this.formData.source_template_type
      )
      
      if (selectedTemplate) {
        if (selectedTemplate.ufield_args && Array.isArray(selectedTemplate.ufield_args)) {
          let fields = []
          fields = selectedTemplate.ufield_args.map(field => {
            if (typeof field === 'string') {
              return { name: field, required: true, description: '' }
            } else if (typeof field === 'object') {
              return {
                name: field.name || field.field_name,
                required: field.required !== undefined
                  ? field.required !== false
                  : ![false, 'false'].includes(field.mandatory),
                description: field.description || ''
              }
            }
            return null
          }).filter(f => f !== null)

          this.currentTemplateFields = fields
          this.formData.dynamicFields = {}
          fields.forEach(field => {
            this.formData.dynamicFields[field.name] = this.isBooleanField(field.name) ? true : ''
          })
          if (selectedTemplate.function_mapping === 'mysql_query_v1' && this.formData.dynamicFields.db_port === '') {
            this.formData.dynamicFields.db_port = '3306'
          }
          if (selectedTemplate.function_mapping === 'oracle_query_v1' && this.formData.dynamicFields.db_port === '') {
            this.formData.dynamicFields.db_port = '1521'
          }
          if (selectedTemplate.function_mapping === 'postgresql_query_v1' && this.formData.dynamicFields.db_port === '') {
            this.formData.dynamicFields.db_port = '5432'
          }
          if (selectedTemplate.function_mapping === 'ldap_search_v1') {
            const ldapDefaults = { ldap_server: 'ldaps://', search_filter: '(objectClass=computer)', attributes: 'dNSHostName', search_scope: 'SUBTREE', page_size: '1000' }
            Object.entries(ldapDefaults).forEach(([key, value]) => {
              if (this.formData.dynamicFields[key] === '') this.formData.dynamicFields[key] = value
            })
          }
        } else {
          console.warn('Template selected but has no ufield_args:', selectedTemplate.template_name)
          this.currentTemplateFields = []
          this.formData.dynamicFields = {}
        }
      } else {
        console.warn('Template not found for type:', this.formData.source_template_type)
        this.currentTemplateFields = []
        this.formData.dynamicFields = {}
      }
    },
    resetMysqlQueryHelper() {
      this.mysqlQueryHelper = {
        tableName: '',
        fieldNames: ''
      }
    },
    generateMysqlQueryFromHelper() {
      const tableName = String(this.mysqlQueryHelper.tableName || '').trim()
      const fieldNames = String(this.mysqlQueryHelper.fieldNames || '').trim()

      if (!tableName || !fieldNames) {
        alert('Please provide both table name and field name(s).')
        return
      }

      const tableOk = /^[a-zA-Z0-9_.]+$/.test(tableName)
      const fieldsOk = /^[a-zA-Z0-9_.,\s*]+$/.test(fieldNames)
      if (!tableOk || !fieldsOk) {
        alert('Only letters, numbers, underscore, dot, comma and space are allowed in helper fields.')
        return
      }

      const normalizedFields = fieldNames
        .split(',')
        .map(v => v.trim())
        .filter(Boolean)
        .join(', ')

      if (!normalizedFields) {
        alert('Please provide at least one field name.')
        return
      }

      this.formData.dynamicFields.db_query = `SELECT ${normalizedFields} FROM ${tableName};`
    },
    formatFieldLabel(fieldName) {
      return fieldName
        .split('_')
        .map(word => word.charAt(0).toUpperCase() + word.slice(1))
        .join(' ')
    },
    isBooleanField(fieldName) {
      return ['verify_ssl', 'start_tls'].includes(fieldName)
    },
    isSecretRefField(fieldName) {
      return String(fieldName || '').toLowerCase().endsWith('_secret_ref')
    },
    formatSecretOptionLabel(secret) {
      const name = String((secret || {}).name || '').trim()
      const ref = String((secret || {}).secret_ref || '').trim()
      if (name && ref) {
        return `${name} (${ref})`
      }
      return ref || name || 'Unnamed secret'
    },
    async fetchDatapullSecrets() {
      try {
        const res = await apiFetch('/api/secrets')
        if (res.ok) {
          const data = await res.json()
          const allSecrets = Array.isArray(data.secrets) ? data.secrets : []
          this.datapullSecrets = allSecrets.filter(secret => secret && secret.active !== false && secret.secret_ref)
        } else {
          this.datapullSecrets = []
        }
      } catch (e) {
        console.error('Error fetching datapull secrets:', e)
        this.datapullSecrets = []
      }
    },
    async runAdhocJob(wf) {
            if (!confirm(`Run adhoc job for '${wf.source_name}'?`)) return;
            this.adhocJobSourceName = wf.source_name;
            this.adhocJobOutput = [];
            this.adhocJobRunning = true;
            this.showAdhocJobModal = true;
            this.addAdhocLog(`Starting adhoc job for '${wf.source_name}'...`);
            try {
              const headers = { 'Content-Type': 'application/json' };
              this.addAdhocLog('Sending request to server...');
              const res = await apiFetch('/api/test/execute-workflow', {
                method: 'POST',
                headers,
                body: JSON.stringify({ source_name: wf.source_name })
              });
              const data = await res.json();
              if (!res.ok) {
                this.addAdhocLog(`❌ Error: ${data.error || data.message || 'Failed to run adhoc job.'}`);
              } else {
                this.addAdhocLog(`✓ Success: ${data.message || 'Job completed successfully'}`);
                if (data.dp_log) {
                  this.addAdhocLog('--- DP Log Output ---');
                  const lines = typeof data.dp_log === 'string' ? data.dp_log.split('\n') : Array.isArray(data.dp_log) ? data.dp_log : [String(data.dp_log)];
                  lines.forEach(line => this.addAdhocLog(line));
                }
              }
            } catch (e) {
              this.addAdhocLog(`❌ Network error: ${e.message}`);
            } finally {
              this.adhocJobRunning = false;
            }
          },
          addAdhocLog(message) {
            this.adhocJobOutput.push({
              timestamp: new Date().toLocaleTimeString(),
              message: message
            });
            // Auto-scroll to bottom
            this.$nextTick(() => {
              const logContainer = document.querySelector('.adhoc-job-output');
              if (logContainer) {
                logContainer.scrollTop = logContainer.scrollHeight;
              }
            });
          },
          closeAdhocJobModal() {
            this.showAdhocJobModal = false;
            this.adhocJobOutput = [];
            this.adhocJobRunning = false;
            this.adhocJobSourceName = '';
          },
      openLogsModal(wf) {
        this.logsModalSourceName = wf.source_name;
        this.showLogsModal = true;
      },
      closeLogsModal() {
        this.showLogsModal = false;
        this.logsModalSourceName = '';
      },
    onCategoryChange() {
      if (this.formData.source_category === 'static') {
        this.formData.source_template_type = 'static';
      } else if (this.formData.source_template_type === 'static') {
        this.formData.source_template_type = '';
      }
    },
    openEditModal(wf) {
      const editPayload = (wf && typeof wf.datapull_payload === 'object' && wf.datapull_payload) ? { ...wf.datapull_payload } : {}
      const rawPaths = editPayload.response_paths
      const normalizedPaths = Array.isArray(rawPaths)
        ? rawPaths.map(v => String(v || '').trim()).filter(Boolean)
        : (String(rawPaths || '').trim() ? [String(rawPaths).trim()] : [])
      this.editFormData = {
        source_name: wf.source_name,
        source_category: wf.source_category,
        source_type: wf.source_type,
        tag: wf.tag || '',
        source_template_type: wf.source_template_type,
        br_score: wf.br_score ?? ((wf.datapull_payload && wf.datapull_payload.br_score) || ''),
        scheduled: wf.scheduled === 'Y' || wf.scheduled === true,
        schedule_interval_min: wf.schedule_interval_min || 60,
        selected_enrichments: Array.isArray(wf.selected_enrichments) ? [...wf.selected_enrichments] : [],
        insertmany: !!wf.insertmany,
        max_response_bytes: wf.max_response_bytes ?? null,
        max_query_rows: wf.max_query_rows ?? null,
        datapull_payload: editPayload,
        response_mode: String(editPayload.response_mode || 'walk_everything').trim().toLowerCase() === 'schema' ? 'schema' : 'walk_everything',
        response_paths: normalizedPaths.length ? normalizedPaths : ['']
      }
      this.enrichmentSearchQueryEdit = ''
      this.showEditModal = true
    },
    closeEditModal() {
      this.showEditModal = false
      this.enrichmentSearchQueryEdit = ''
    },
    async openDeleteModal(wf) {
      this.showDeleteModal = true
      this.deleteTargetWorkflow = wf
      this.deletePreview = null
      this.deletePreviewError = ''
      await this.fetchDeletePreview()
    },
    closeDeleteModal() {
      this.showDeleteModal = false
      this.deleteTargetWorkflow = null
      this.deletePreview = null
      this.deletePreviewError = ''
      this.deletePreviewLoading = false
      this.isDeleteSubmitting = false
    },
    async fetchDeletePreview() {
      if (!this.deleteTargetWorkflow || !this.deleteTargetWorkflow.source_name) {
        this.deletePreviewError = 'Missing source name for delete preview.'
        return
      }

      this.deletePreviewLoading = true
      this.deletePreviewError = ''
      try {
        const res = await apiFetch('/api/datapull/delete/preview', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({
            source_name: this.deleteTargetWorkflow.source_name
          })
        })
        const data = await res.json().catch(() => ({}))
        if (!res.ok) {
          this.deletePreviewError = data.message || 'Failed to load delete preview.'
          this.deletePreview = null
          return
        }
        this.deletePreview = data.impact || null
      } catch (e) {
        this.deletePreviewError = 'Network error while loading delete preview.'
        this.deletePreview = null
      } finally {
        this.deletePreviewLoading = false
      }
    },
    async confirmDeleteDatapull() {
      if (!this.deleteTargetWorkflow || !this.deleteTargetWorkflow.source_name) {
        this.deletePreviewError = 'Missing source name for delete operation.'
        return
      }

      this.isDeleteSubmitting = true
      this.deletePreviewError = ''
      try {
        const res = await apiFetch('/api/datapull/delete', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({
            source_name: this.deleteTargetWorkflow.source_name
          })
        })
        const data = await res.json().catch(() => ({}))
        if (!res.ok) {
          this.deletePreviewError = data.message || 'Failed to delete datapull workflow.'
          return
        }

        const cleanup = (data.result || {}).indicator_cleanup || {}
        alert(
          `Datapull workflow deleted successfully.\n` +
          `Indicators deleted: ${cleanup.deleted_indicator_count ?? 0}\n` +
          `Source entries set active=N: ${cleanup.deactivated_source_entry_count ?? 0}`
        )

        this.closeDeleteModal()
        await this.fetchWorkflows()
      } catch (e) {
        this.deletePreviewError = 'Network error while deleting datapull workflow.'
      } finally {
        this.isDeleteSubmitting = false
      }
    },
    async submitEditDatapull() {
      this.isEditSubmitting = true
      try {
        const headers = {
          'Content-Type': 'application/json'
        }
        const payload = {
          source_name: this.editFormData.source_name,
          source_category: this.editFormData.source_category,
          source_template_type: this.editFormData.source_template_type,
          datapull_payload: {
            ...(this.editFormData.datapull_payload || {}),
            response_mode: this.editFormData.response_mode,
            response_paths: this.editFormData.response_mode === 'schema'
              ? (this.editFormData.response_paths || []).map(v => String(v || '').trim()).filter(Boolean)
              : []
          },
          tag: this.editFormData.tag || null,
          br_score: this.editFormData.br_score,
          scheduled: this.editFormData.scheduled,
          schedule_enabled: this.editFormData.scheduled,
          schedule_interval_min: this.editFormData.scheduled ? (this.editFormData.schedule_interval_min || 60) : null,
          selected_enrichments: Array.isArray(this.editFormData.selected_enrichments) ? this.editFormData.selected_enrichments : [],
          enrichment_enabled: Array.isArray(this.editFormData.selected_enrichments) && this.editFormData.selected_enrichments.length > 0,
          insertmany: !!this.editFormData.insertmany,
          max_response_bytes: this.editFormData.max_response_bytes || null,
          max_query_rows: this.editFormData.max_query_rows || null
        }
        const res = await apiFetch('/api/datapull/update', {
          method: 'POST',
          headers,
          body: JSON.stringify(payload)
        })
        if (!res.ok) {
          const err = await res.json()
          alert(`Error: ${err.message || 'Failed to update datapull'}`)
          return
        }
        alert('Datapull workflow updated successfully!')
        this.closeEditModal()
        await this.fetchWorkflows()
      } catch (e) {
        console.error('Edit submit error:', e)
        alert('Network error while updating datapull.')
      } finally {
        this.isEditSubmitting = false
      }
    },
    async fetchWorkflows() {
      this.loading = true
      try {
        const res = await apiFetch('/api/datapull_workflows')
        let workflows = [];
        if (res.ok) {
          const data = await res.json()
          workflows = data.workflows || []
        }
        const jobsRes = await apiFetch('/api/scheduled-jobs')
        let jobs = [];
        if (jobsRes.ok) {
          const jobsData = await jobsRes.json();
          jobs = Array.isArray(jobsData.jobs) ? jobsData.jobs : [];
        }
        // Map jobs to workflows
        this.workflows = workflows.map(wf => {
          const job = jobs.find(j => j.source_name === wf.source_name);
          return { ...wf, scheduler_job: job ? {
            next_run_time: job.next_run,
            last_status: job.last_status,
            last_run: job.last_run
          } : null };
        });
      } catch (e) {
        console.error('Fetch error:', e)
        this.workflows = []
      } finally {
        this.loading = false
      }
    },
    formatPayload(p) {
      try {
        return JSON.stringify(p, null, 2)
      } catch (e) {
        return String(p)
      }
    },
    formatPreviewValue(value) {
      if (value === null || value === undefined || value === '') {
        return '-'
      }
      if (typeof value === 'object') {
        try {
          return JSON.stringify(value)
        } catch (e) {
          return String(value)
        }
      }
      return String(value)
    },
    formatSourceList(sources) {
      if (!Array.isArray(sources) || sources.length === 0) {
        return '-'
      }
      return sources.join(', ')
    },
    openAddModal() {
      this.showAddModal = true
      this.resetForm()
    },
    closeAddModal() {
      this.showAddModal = false
      this.enrichmentSearchQueryCreate = ''
      this.resetForm()
    },
    resetForm() {
      this.formData = {
        source_name: '',
        source_category: '',
        source_type: '',
        tag: '',
        source_template_type: '',
        br_score: '',
        scheduled: false,
        schedule_interval_min: 60,
        selected_enrichments: [],
        insertmany: false,
        max_response_bytes: null,
        max_query_rows: null,
        dynamicFields: {},
        response_mode: 'walk_everything',
        response_paths: ['']
      }
      this.currentTemplateFields = []
      this.resetMysqlQueryHelper()
    },
    async submitNewDatapull() {
      if (!this.formData.source_name || !this.formData.source_category || !this.formData.source_type || !this.formData.source_template_type) {
        alert('Please fill in all required fields.')
        return
      }

      this.isSubmitting = true
      try {
        const headers = {
          'Content-Type': 'application/json'
        }

        // Build datapull_payload from dynamic template fields only
        const datapull_payload = {
          ...this.formData.dynamicFields,
          response_mode: this.formData.response_mode,
          response_paths: this.formData.response_mode === 'schema'
            ? (this.formData.response_paths || []).map(v => String(v || '').trim()).filter(Boolean)
            : []
        }

        const payload = {
          source_name: this.formData.source_name,
          source_category: this.formData.source_category,
          source_type: this.formData.source_type,
          tag: this.formData.tag || null,
          source_template_type: this.formData.source_template_type,
          datapull_payload: datapull_payload,
          br_score: this.formData.br_score,
          scheduled: this.formData.scheduled,
          schedule_enabled: this.formData.scheduled,
          schedule_interval_min: this.formData.scheduled ? (this.formData.schedule_interval_min || 60) : null,
          selected_enrichments: Array.isArray(this.formData.selected_enrichments) ? this.formData.selected_enrichments : [],
          enrichment_enabled: Array.isArray(this.formData.selected_enrichments) && this.formData.selected_enrichments.length > 0,
          insertmany: !!this.formData.insertmany,
          max_response_bytes: this.formData.max_response_bytes || null,
          max_query_rows: this.formData.max_query_rows || null
        }

        const res = await apiFetch('/api/datapull/create', {
          method: 'POST',
          headers,
          body: JSON.stringify(payload)
        })

        if (!res.ok) {
          const err = await res.json()
          alert(`Error: ${err.message || 'Failed to create datapull'}`)
          return
        }

        alert('Datapull workflow created successfully!')
        this.closeAddModal()
        await this.fetchWorkflows()
      } catch (e) {
        console.error('Submit error:', e)
        alert('Network error while creating datapull.')
      } finally {
        this.isSubmitting = false
      }
    }
  },
  mounted() {
    this.loadFieldPreferences()
    this.fetchWorkflows()
    this.fetchDatapullTemplates()
    this.fetchDatapullSecrets()
    this.fetchSourceTypeOptions()
    this.fetchTags()
    this.fetchDataEnrichmentOptions()
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
  max-width: 600px;
  width: 90%;
  max-height: 90vh;
  overflow-y: auto;
}

.modal-header {
  padding: 1.5rem;
  border-bottom: 1px solid #e9ecef;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.modal-title {
  font-size: 1.25rem;
  font-weight: 600;
  margin: 0;
}

.btn-close {
  background: none;
  border: none;
  font-size: 1.5rem;
  cursor: pointer;
  color: #666;
}

.btn-close:hover {
  color: #000;
}

.modal-body {
  padding: 1.5rem;
}

.modal-footer {
  padding: 1.5rem;
  border-top: 1px solid #e9ecef;
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
}

.table-responsive {
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
}

.table-hover tbody tr:hover {
  background-color: #f8f9fa;
}

.btn-lg {
  padding: 0.75rem 1.5rem;
  font-size: 1rem;
  border-radius: 8px;
  transition: all 0.3s ease;
}

.btn-lg:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
}

code {
  background-color: #f5f5f5;
  padding: 0.2rem 0.4rem;
  border-radius: 4px;
  font-size: 0.85rem;
}

.adhoc-job-output {
  background-color: #1e1e1e;
  color: #d4d4d4;
  padding: 1rem;
  border-radius: 6px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  font-size: 0.875rem;
  max-height: 350px;
  overflow-y: auto;
  line-height: 1.5;
}

.adhoc-log-line {
  display: flex;
  margin-bottom: 0.5rem;
}

.adhoc-log-time {
  color: #858585;
  margin-right: 0.75rem;
  min-width: 90px;
  flex-shrink: 0;
}

.adhoc-log-message {
  color: #d4d4d4;
  word-break: break-word;
  white-space: pre-wrap;
}

.field-filter-container {
  position: relative;
  display: inline-block;
}

.field-filter-dropdown {
  position: absolute;
  top: 100%;
  right: 0;
  background: white;
  border: 1px solid #e9ecef;
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  z-index: 1000;
  min-width: 250px;
  margin-top: 0.5rem;
}

.field-filter-header {
  padding: 0.75rem 1rem;
  border-bottom: 1px solid #e9ecef;
  font-weight: 600;
  font-size: 0.9rem;
}

.field-filter-items {
  max-height: 300px;
  overflow-y: auto;
  padding: 0.5rem 0;
}

.field-filter-item {
  display: flex;
  align-items: center;
  padding: 0.5rem 1rem;
  cursor: pointer;
  user-select: none;
}

.field-filter-item:hover {
  background-color: #f8f9fa;
}

.field-filter-item input {
  margin-right: 0.75rem;
  cursor: pointer;
}

.field-filter-footer {
  padding: 0.75rem 1rem;
  border-top: 1px solid #e9ecef;
  display: flex;
  gap: 0.5rem;
  justify-content: flex-end;
}

.field-filter-footer .btn-link {
  padding: 0.25rem 0.75rem;
  font-size: 0.85rem;
}

@media (max-width: 768px) {
  .modal-content {
    width: 95%;
  }

  .d-flex {
    flex-direction: column;
    gap: 1rem;
  }

  .btn-lg {
    width: 100%;
  }
}
</style>
