<template>
  <div class="container mt-4 pb-5">
    <div class="d-flex justify-content-between align-items-center mb-4">
      <div>
        <h2 class="mb-1">Configuration</h2>
        <p class="text-muted mb-0">View and edit documents from byoint_core_config.basicconfigs.</p>
      </div>
      <button class="btn btn-primary" @click="fetchConfigs" :disabled="loading">
        <span v-if="loading" class="spinner-border spinner-border-sm me-2"></span>
        Refresh
      </button>
    </div>

    <div v-if="message" :class="['alert', messageType === 'error' ? 'alert-danger' : 'alert-success']">
      {{ message }}
    </div>

    <div class="card mb-4">
      <div class="card-header d-flex justify-content-between align-items-center">
        <strong>Mongo Init/Reset Workflow</strong>
        <button class="btn btn-sm btn-outline-secondary" @click="fetchMongoInitStatus" :disabled="mongoInitLoading">
          Status
        </button>
      </div>
      <div class="card-body">
        <div class="row g-3 align-items-end">
          <div class="col-md-3">
            <label class="form-label">Mode</label>
            <select class="form-select" v-model="mongoInitMode" :disabled="mongoInitLoading">
              <option value="init">init</option>
              <option value="reset">reset</option>
            </select>
          </div>
          <div class="col-md-6">
            <label class="form-label">Init File (optional)</label>
            <input
              v-model.trim="mongoInitFile"
              type="text"
              class="form-control"
              :disabled="mongoInitLoading"
              placeholder="mongo_init.json"
            />
          </div>
          <div class="col-md-3 d-grid">
            <button class="btn btn-warning" @click="triggerMongoInit" :disabled="mongoInitLoading">
              <span v-if="mongoInitLoading" class="spinner-border spinner-border-sm me-2"></span>
              Run Workflow
            </button>
          </div>
        </div>

        <div v-if="mongoInitStatus" class="mt-3 small text-muted">
          <div><strong>Current status:</strong> {{ mongoInitStatus.status || '-' }}</div>
          <div v-if="mongoInitStatus.lock && mongoInitStatus.lock.updated_at">
            <strong>Last update:</strong> {{ mongoInitStatus.lock.updated_at }}
          </div>
          <div v-if="mongoInitStatus.lock && mongoInitStatus.lock.mode">
            <strong>Last mode:</strong> {{ mongoInitStatus.lock.mode }}
          </div>
          <div v-if="mongoInitStatus.lock && mongoInitStatus.lock.error" class="text-danger">
            <strong>Last error:</strong> {{ mongoInitStatus.lock.error }}
          </div>
        </div>

        <div v-if="mongoInitMessage" :class="['alert', mongoInitMessageType === 'error' ? 'alert-danger' : 'alert-success', 'mt-3', 'mb-0']">
          {{ mongoInitMessage }}
        </div>
      </div>
    </div>

    <div class="card mb-4">
      <div class="card-header d-flex justify-content-between align-items-center">
        <strong>RBAC Configuration</strong>
        <button class="btn btn-sm btn-outline-secondary" @click="fetchRbacConfig" :disabled="rbacLoading">
          Reload
        </button>
      </div>
      <div class="card-body">
        <div class="alert alert-light border small">
          Roles are fixed to <strong>admin</strong> and <strong>user</strong>.
          User roles come from User Management. Configure restricted page mapping below.
        </div>
        <div class="row g-3">
          <div class="col-md-12">
            <label class="form-label">Restricted Pages Mapping</label>
            <textarea
              v-model="rbacRestrictedPagesText"
              class="form-control"
              rows="6"
              :disabled="rbacLoading"
              placeholder="/users=admin&#10;/configuration=admin"
              spellcheck="false"
            ></textarea>
            <div class="form-text">One mapping per line: <code>/page-path=admin</code> or <code>/page-path=user</code>.</div>
          </div>
          <div class="col-md-3 d-grid">
            <button class="btn btn-primary" @click="saveRbacConfig" :disabled="rbacLoading">
              <span v-if="rbacLoading" class="spinner-border spinner-border-sm me-2"></span>
              Save RBAC
            </button>
          </div>
        </div>

        <div v-if="rbacMessage" :class="['alert', rbacMessageType === 'error' ? 'alert-danger' : 'alert-success', 'mt-3', 'mb-0']">
          {{ rbacMessage }}
        </div>
      </div>
    </div>

    <div v-if="loading" class="mt-3">
      <div class="spinner-border text-primary" role="status">
        <span class="visually-hidden">Loading...</span>
      </div>
    </div>

    <div v-else-if="error" class="alert alert-danger">{{ error }}</div>

    <div v-else>
      <div v-if="configs.length === 0" class="alert alert-info">No configuration documents found.</div>

      <div v-else>
        <div v-for="cfg in configs" :key="cfg.module || cfg._id" class="card mb-4">
          <div class="card-header d-flex justify-content-between align-items-center">
            <div>
              <strong>{{ cfg.module || 'Configuration' }}</strong>
              <span class="text-muted small ms-2">{{ Object.keys(configFields(cfg)).length }} settings</span>
            </div>
            <button class="btn btn-sm btn-outline-secondary" @click="openViewModal(cfg)">View JSON</button>
          </div>
          <div class="card-body p-0">
            <div
              v-for="(value, key) in configFields(cfg)"
              :key="key"
              class="config-row d-flex align-items-start border-bottom px-3 py-2"
            >
              <div class="config-key me-3">
                <div class="config-key-name">{{ key }}</div>
                <div v-if="fieldDescription(cfg, key)" class="config-desc text-muted">{{ fieldDescription(cfg, key) }}</div>
              </div>

              <template v-if="isSnippetToggle(cfg, key)">
                <div class="config-value flex-grow-1">
                  <span v-if="value === true" class="badge bg-warning text-dark">Enabled: custom snippets can run</span>
                  <span v-else class="badge bg-secondary">Disabled</span>
                </div>
                <div class="form-check form-switch ms-3 mb-0">
                  <input
                    :id="`toggle-${key}`"
                    class="form-check-input"
                    type="checkbox"
                    role="switch"
                    :checked="value === true"
                    :disabled="saving"
                    :aria-label="`Toggle ${key}`"
                    @click.prevent="onSnippetToggleClick(value === true)"
                  />
                </div>
              </template>

              <template v-else>
                <div class="config-value flex-grow-1">
                  <span v-if="value === null || value === undefined" class="text-muted fst-italic">not set</span>
                  <span v-else-if="typeof value === 'boolean'" :class="['badge', value ? 'bg-success' : 'bg-secondary']">
                    {{ value }}
                  </span>
                  <span v-else-if="typeof value === 'number'">
                    {{ value.toLocaleString() }}
                    <span v-if="isBytesField(key)" class="text-muted small ms-1">({{ formatBytes(value) }})</span>
                  </span>
                  <template v-else-if="Array.isArray(value)">
                    <span v-if="!value.length" class="text-muted fst-italic">empty list</span>
                    <div v-else class="d-flex flex-wrap gap-1">
                      <span v-for="(item, i) in value.slice(0, previewCount)" :key="i" class="badge bg-light text-dark border chip">
                        {{ formatScalar(item) }}
                      </span>
                      <button
                        v-if="value.length > previewCount"
                        type="button"
                        class="btn btn-link btn-sm p-0 align-baseline"
                        @click="openFieldModal(cfg, key, value)"
                      >+{{ value.length - previewCount }} more</button>
                    </div>
                  </template>
                  <template v-else-if="typeof value === 'object'">
                    <span v-if="!Object.keys(value).length" class="text-muted fst-italic">empty</span>
                    <div v-else class="d-flex flex-wrap gap-2">
                      <span v-for="[k, v] in Object.entries(value).slice(0, previewCount)" :key="k" class="kv">
                        <span class="text-muted">{{ k }}:</span> {{ formatNested(k, v) }}
                      </span>
                      <button
                        v-if="Object.keys(value).length > previewCount"
                        type="button"
                        class="btn btn-link btn-sm p-0 align-baseline"
                        @click="openFieldModal(cfg, key, value)"
                      >+{{ Object.keys(value).length - previewCount }} more</button>
                    </div>
                  </template>
                  <span v-else class="config-text" :title="String(value)">{{ value }}</span>
                </div>
                <div class="config-actions d-flex gap-2 ms-3">
                  <button class="btn btn-sm btn-outline-secondary" @click="openFieldModal(cfg, key, value)">View</button>
                  <button class="btn btn-sm btn-outline-primary" @click="openEditModal(cfg, key, value)">
                    {{ isAddOnlyListField(key) ? 'Add Entry' : 'Edit' }}
                  </button>
                </div>
              </template>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div v-if="showSnippetWarningModal" class="modal-overlay" @click.self="closeSnippetWarningModal">
      <div class="modal-content" style="max-width: 640px;" role="dialog" aria-labelledby="snippet-warning-title">
        <div class="modal-header">
          <h5 id="snippet-warning-title" class="modal-title">Enable custom snippets?</h5>
          <button type="button" class="btn-close" @click="closeSnippetWarningModal" :disabled="saving"></button>
        </div>
        <div class="modal-body">
          <div class="alert alert-info">
            Custom snippets in datapull templates and data enrichments run as Python code in the sandboxed
            <code>snippet_runner</code> container. It has no access to app secrets or the BYO-INT database,
            a read-only filesystem, and time and memory limits.
          </div>
          <p class="mb-2">The sandbox still allows some things, so before you enable this:</p>
          <ul class="mb-3">
            <li>
              The import and builtin allowlists reduce mistakes but can be bypassed. The container is the
              real boundary.
            </li>
            <li>
              A snippet receives the inputs it is given, including any secrets the workflow passes to it,
              and can send them anywhere.
            </li>
            <li>
              A snippet can make network requests, including to internal systems on your network.
            </li>
            <li>
              Anyone who can create or edit datapull templates or enrichments can run code in the runner.
            </li>
          </ul>
          <p class="mb-0">
            Only enable this if every user who can edit templates and enrichments is trusted, and review
            snippet code before you save it.
          </p>
          <div v-if="snippetToggleError" class="alert alert-danger mt-3 mb-0">{{ snippetToggleError }}</div>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" @click="closeSnippetWarningModal" :disabled="saving">Cancel</button>
          <button type="button" class="btn btn-warning" @click="setSnippetToggle(true)" :disabled="saving">
            <span v-if="saving" class="spinner-border spinner-border-sm me-2"></span>
            I understand, enable
          </button>
        </div>
      </div>
    </div>

    <div v-if="showViewModal" class="modal-overlay" @click.self="closeViewModal">
      <div class="modal-content" style="max-width: 900px;" role="dialog" aria-labelledby="module-view-title">
        <div class="modal-header">
          <h5 id="module-view-title" class="modal-title">Configuration: <code>{{ selectedModule || '-' }}</code></h5>
          <button type="button" class="btn-close" @click="closeViewModal"></button>
        </div>
        <div class="modal-body">
          <div class="d-flex justify-content-between align-items-center mb-2">
            <div class="form-check form-switch mb-0">
              <input id="reveal-module-secrets" v-model="revealSecrets" class="form-check-input" type="checkbox" role="switch" />
              <label class="form-check-label small" for="reveal-module-secrets">Show secrets</label>
            </div>
            <button type="button" class="btn btn-sm btn-outline-secondary" @click="copyText(selectedConfigPretty)">
              {{ copied ? 'Copied' : 'Copy JSON' }}
            </button>
          </div>
          <pre class="json-preview mb-0">{{ selectedConfigPretty }}</pre>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" @click="closeViewModal">Close</button>
        </div>
      </div>
    </div>

    <div v-if="showFieldModal" class="modal-overlay" @click.self="closeFieldModal">
      <div class="modal-content" style="max-width: 760px;" role="dialog" aria-labelledby="field-view-title">
        <div class="modal-header">
          <h5 id="field-view-title" class="modal-title">
            <code>{{ fieldModal.key }}</code>
            <span class="text-muted small ms-2">{{ fieldModal.module }} · {{ valueTypeLabel(fieldModal.value) }}</span>
          </h5>
          <button type="button" class="btn-close" @click="closeFieldModal"></button>
        </div>
        <div class="modal-body">
          <p v-if="fieldModal.description" class="text-muted small">{{ fieldModal.description }}</p>

          <div class="d-flex justify-content-between align-items-center mb-3">
            <ul class="nav nav-pills nav-sm">
              <li class="nav-item">
                <button type="button" :class="['nav-link', 'py-1', { active: fieldModalTab === 'formatted' }]" @click="fieldModalTab = 'formatted'">Formatted</button>
              </li>
              <li class="nav-item">
                <button type="button" :class="['nav-link', 'py-1', { active: fieldModalTab === 'json' }]" @click="fieldModalTab = 'json'">Raw JSON</button>
              </li>
            </ul>
            <div v-if="hasSecrets(fieldModal.value)" class="form-check form-switch mb-0">
              <input id="reveal-field-secrets" v-model="revealSecrets" class="form-check-input" type="checkbox" role="switch" />
              <label class="form-check-label small" for="reveal-field-secrets">Show secrets</label>
            </div>
          </div>

          <template v-if="fieldModalTab === 'formatted'">
            <!-- List -->
            <template v-if="Array.isArray(fieldModal.value)">
              <div class="d-flex justify-content-between align-items-center mb-2">
                <span class="text-muted small">{{ fieldModal.value.length }} entries</span>
                <input
                  v-if="fieldModal.value.length > 10"
                  v-model.trim="fieldFilter"
                  type="search"
                  class="form-control form-control-sm w-auto"
                  placeholder="Filter entries"
                  aria-label="Filter entries"
                />
              </div>
              <div v-if="!filteredListEntries.length" class="text-muted small">No entries.</div>
              <ol v-else class="list-group list-group-numbered field-list">
                <li v-for="entry in filteredListEntries" :key="entry.index" class="list-group-item py-1 small">
                  <code v-if="entry.isObject" class="text-break">{{ entry.text }}</code>
                  <span v-else class="text-break">{{ entry.text }}</span>
                </li>
              </ol>
            </template>

            <!-- Object -->
            <table v-else-if="isPlainObject(fieldModal.value)" class="table table-sm align-middle mb-0">
              <tbody>
                <tr v-for="[k, v] in Object.entries(fieldModal.value)" :key="k">
                  <th class="text-muted fw-medium field-table-key">{{ k }}</th>
                  <td>
                    <span v-if="v === null || v === undefined" class="text-muted fst-italic">not set</span>
                    <span v-else-if="isSecretKey(k) && !revealSecrets" class="text-muted">••••••••</span>
                    <span v-else-if="typeof v === 'boolean'" :class="['badge', v ? 'bg-success' : 'bg-secondary']">{{ v }}</span>
                    <div v-else-if="Array.isArray(v)" class="d-flex flex-wrap gap-1">
                      <span v-if="!v.length" class="text-muted fst-italic">empty list</span>
                      <span v-for="(item, i) in v" :key="i" class="badge bg-light text-dark border chip">{{ formatScalar(item) }}</span>
                    </div>
                    <pre v-else-if="typeof v === 'object'" class="json-inline mb-0">{{ toJson(v) }}</pre>
                    <span v-else class="text-break">{{ v }}</span>
                  </td>
                </tr>
              </tbody>
            </table>

            <!-- Single value -->
            <div v-else class="field-scalar">
              <span v-if="fieldModal.value === null || fieldModal.value === undefined" class="text-muted fst-italic">not set</span>
              <span v-else-if="typeof fieldModal.value === 'boolean'" :class="['badge', fieldModal.value ? 'bg-success' : 'bg-secondary']">{{ fieldModal.value }}</span>
              <template v-else-if="typeof fieldModal.value === 'number'">
                {{ fieldModal.value.toLocaleString() }}
                <span v-if="isBytesField(fieldModal.key)" class="text-muted small ms-1">({{ formatBytes(fieldModal.value) }})</span>
              </template>
              <span v-else-if="isSecretKey(fieldModal.key) && !revealSecrets" class="text-muted">••••••••</span>
              <span v-else class="text-break">{{ fieldModal.value }}</span>
            </div>
          </template>

          <template v-else>
            <div class="d-flex justify-content-end mb-2">
              <button type="button" class="btn btn-sm btn-outline-secondary" @click="copyText(fieldModalJson)">
                {{ copied ? 'Copied' : 'Copy JSON' }}
              </button>
            </div>
            <pre class="json-preview mb-0">{{ fieldModalJson }}</pre>
          </template>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" @click="closeFieldModal">Close</button>
          <button type="button" class="btn btn-primary" @click="editFromFieldModal">
            {{ isAddOnlyListField(fieldModal.key) ? 'Add Entry' : 'Edit' }}
          </button>
        </div>
      </div>
    </div>

    <div v-if="showEditModal" class="modal-overlay" @click.self="closeEditModal">
      <div class="modal-content" style="max-width: 600px;">
        <div class="modal-header">
          <h5 class="modal-title">
            {{ isAddOnlyEditor ? 'Add Entry' : 'Edit' }} <code>{{ editKey }}</code>
          </h5>
          <button type="button" class="btn-close" @click="closeEditModal"></button>
        </div>
        <div class="modal-body">
          <template v-if="isAddOnlyEditor">
            <div class="mb-2 text-muted small">
              Add a single new entry to <code>{{ editKey }}</code>. Existing entries are read-only here.
            </div>

            <div class="readonly-list mb-3">
              <div v-if="!currentListEntries.length" class="text-muted small">No entries yet.</div>
              <div v-else class="d-flex flex-wrap gap-2">
                <span v-for="entry in currentListEntries" :key="entry" class="badge bg-light text-dark border list-entry-chip">
                  {{ entry }}
                </span>
              </div>
            </div>

            <label class="form-label">New entry</label>
            <input
              v-model="newListEntry"
              type="text"
              class="form-control"
              :disabled="saving"
              placeholder="Type a single value and save"
              @keyup.enter="submitAddEntry"
            />
          </template>

          <template v-else>
            <div class="mb-2 text-muted small">Enter a new value for <code>{{ editKey }}</code>.</div>
            <textarea
              v-model="editValue"
              class="form-control"
              rows="5"
              :disabled="saving"
              spellcheck="false"
            ></textarea>
          </template>

          <div v-if="formError" class="alert alert-danger mt-3 mb-0">{{ formError }}</div>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" @click="closeEditModal" :disabled="saving">Cancel</button>
          <button
            type="button"
            class="btn btn-primary"
            @click="isAddOnlyEditor ? submitAddEntry() : submitEdit()"
            :disabled="saving"
          >
            <span v-if="saving" class="spinner-border spinner-border-sm me-2"></span>
            {{ saving ? 'Saving...' : 'Save' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { apiFetch } from '@/api'

// Keys whose values are hidden until the viewer turns on "Show secrets".
const SECRET_KEY_PATTERN = /(secret|password|passwd|token|api_?key|private_?key)/i
const SECRET_MASK = '••••••••'

// One-line descriptions shown under each setting, by module.
const FIELD_DESCRIPTIONS = {
  core: {
    allow_custom_snippet: 'Allows custom Python snippets in datapull templates and data enrichments.',
    API_AUDIT_LOG_METHODS: 'HTTP methods recorded in the API audit log.',
    PUBLIC_API_ENDPOINTS: 'API paths that API keys are allowed to call (* matches any suffix).',
    collect_log: 'How much detail datapulls write to their logs: None, summary or detailed.',
    custom_snippets_allowed_builtins: 'Python builtins that custom template snippets may use.',
    custom_snippets_allowed_imports: 'Modules custom template snippets may import. Third-party modules must also be installed in the snippet runner.',
    enable_indicator_logging: 'Records per-indicator activity logs during datapulls.',
    output_categories: 'Categories available when creating data outputs.',
    sso: 'Single sign-on (OpenID Connect) settings.',
    worker_scaling: 'Datapull worker scaling settings.',
    max_response_bytes: 'Largest response a datapull will read from a source.',
    max_query_rows: 'Most rows a database query template returns.'
  },
  auth: {
    rbac: 'Role-based access control: known roles, default role and admin-only pages.'
  }
}

export default {
  name: 'ConfigurationPage',
  data() {
    return {
      configs: [],
      loading: false,
      saving: false,
      error: '',
      message: '',
      messageType: 'success',
      formError: '',
      showViewModal: false,
      showEditModal: false,
      selectedConfig: null,
      selectedModule: '',
      editModule: '',
      editKey: '',
      editValue: '',
      isAddOnlyEditor: false,
      currentListEntries: [],
      newListEntry: '',
      mongoInitMode: 'init',
      mongoInitFile: '',
      mongoInitLoading: false,
      mongoInitStatus: null,
      mongoInitMessage: '',
      mongoInitMessageType: 'success',
      rbacLoading: false,
      rbacRestrictedPagesText: '',
      rbacMessage: '',
      rbacMessageType: 'success',
      showSnippetWarningModal: false,
      snippetToggleError: '',
      showFieldModal: false,
      fieldModal: { module: '', key: '', value: null, description: '' },
      fieldModalTab: 'formatted',
      fieldFilter: '',
      revealSecrets: false,
      copied: false,
      previewCount: 6
    }
  },
  computed: {
    selectedConfigPretty() {
      if (!this.selectedConfig) {
        return '{}'
      }
      return this.toJson(this.revealSecrets ? this.selectedConfig : this.maskSecrets(this.selectedConfig))
    },
    fieldModalJson() {
      const value = this.fieldModal.value
      return this.toJson(this.revealSecrets ? value : this.maskSecrets(value, this.fieldModal.key))
    },
    filteredListEntries() {
      const list = Array.isArray(this.fieldModal.value) ? this.fieldModal.value : []
      const needle = this.fieldFilter.toLowerCase()
      return list
        .map((item, index) => ({
          index,
          isObject: item !== null && typeof item === 'object',
          text: this.formatScalar(item)
        }))
        .filter(entry => !needle || entry.text.toLowerCase().includes(needle))
    }
  },
  async mounted() {
    await this.fetchConfigs()
    await this.fetchMongoInitStatus()
    await this.fetchRbacConfig()
  },
  methods: {
    clearMessages() {
      this.error = ''
      this.message = ''
      this.formError = ''
    },
    configFields(cfg) {
      if (!cfg || typeof cfg !== 'object') return {}
      return Object.fromEntries(Object.entries(cfg).filter(([k]) => k !== '_id' && k !== 'module'))
    },
    isAddOnlyListField(key) {
      return key === 'custom_snippets_allowed_builtins' || key === 'custom_snippets_allowed_imports'
    },
    isSnippetToggle(cfg, key) {
      return (cfg || {}).module === 'core' && key === 'allow_custom_snippet'
    },
    onSnippetToggleClick(currentlyEnabled) {
      this.clearMessages()
      if (currentlyEnabled) {
        // Turning off is always safe, so no confirmation is needed.
        this.setSnippetToggle(false)
      } else {
        this.snippetToggleError = ''
        this.showSnippetWarningModal = true
      }
    },
    closeSnippetWarningModal() {
      if (this.saving) return
      this.showSnippetWarningModal = false
      this.snippetToggleError = ''
    },
    async setSnippetToggle(enabled) {
      this.saving = true
      this.snippetToggleError = ''
      try {
        const res = await apiFetch('/api/configuration/basicconfigs/update', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          // Send only this field; the backend applies it with $set, leaving other core settings untouched.
          body: JSON.stringify({ module: 'core', config: { allow_custom_snippet: enabled } })
        })
        const data = await res.json().catch(() => ({}))
        if (!res.ok) {
          const msg = data.message || 'Failed to update allow_custom_snippet.'
          if (this.showSnippetWarningModal) {
            this.snippetToggleError = msg
          } else {
            this.message = msg
            this.messageType = 'error'
          }
          return
        }
        this.showSnippetWarningModal = false
        this.message = enabled ? 'Custom snippets enabled.' : 'Custom snippets disabled.'
        this.messageType = 'success'
        await this.fetchConfigs()
      } catch (e) {
        const msg = 'Network error while updating allow_custom_snippet.'
        if (this.showSnippetWarningModal) {
          this.snippetToggleError = msg
        } else {
          this.message = msg
          this.messageType = 'error'
        }
      } finally {
        this.saving = false
      }
    },
    fieldDescription(cfg, key) {
      const moduleDescriptions = FIELD_DESCRIPTIONS[(cfg || {}).module] || {}
      return moduleDescriptions[key] || ''
    },
    isPlainObject(value) {
      return value !== null && typeof value === 'object' && !Array.isArray(value)
    },
    isSecretKey(key) {
      return SECRET_KEY_PATTERN.test(String(key || ''))
    },
    isBytesField(key) {
      return /_bytes$/i.test(String(key || ''))
    },
    formatBytes(bytes) {
      const units = ['B', 'KB', 'MB', 'GB', 'TB']
      let size = Number(bytes)
      let unit = 0
      while (Math.abs(size) >= 1024 && unit < units.length - 1) {
        size /= 1024
        unit += 1
      }
      return `${Number.isInteger(size) ? size : size.toFixed(1)} ${units[unit]}`
    },
    formatScalar(item) {
      if (item === null || item === undefined) return 'null'
      if (typeof item === 'object') return JSON.stringify(item)
      return String(item)
    },
    // Short inline text for a value inside an object summary on the main page.
    formatNested(key, value) {
      if (value === null || value === undefined || value === '') return '—'
      if (this.isSecretKey(key)) return SECRET_MASK
      if (Array.isArray(value)) return value.length === 1 ? '1 item' : `${value.length} items`
      if (typeof value === 'object') return '{…}'
      const text = String(value)
      return text.length > 40 ? `${text.slice(0, 40)}…` : text
    },
    valueTypeLabel(value) {
      if (value === null || value === undefined) return 'not set'
      if (Array.isArray(value)) return `list of ${value.length}`
      if (typeof value === 'object') return `object with ${Object.keys(value).length} keys`
      if (typeof value === 'string') return 'text'
      return typeof value
    },
    hasSecrets(value, key = '') {
      if (this.isSecretKey(key) && value !== null && value !== undefined && value !== '') return true
      if (Array.isArray(value)) return value.some(item => this.hasSecrets(item))
      if (this.isPlainObject(value)) return Object.entries(value).some(([k, v]) => this.hasSecrets(v, k))
      return false
    },
    // Copy of value with secret fields replaced by a mask (null/empty values are left as-is).
    maskSecrets(value, key = '') {
      if (this.isSecretKey(key) && value !== null && value !== undefined && value !== '') return SECRET_MASK
      if (Array.isArray(value)) return value.map(item => this.maskSecrets(item))
      if (this.isPlainObject(value)) {
        return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, this.maskSecrets(v, k)]))
      }
      return value
    },
    toJson(value) {
      return JSON.stringify(value === undefined ? null : value, null, 2)
    },
    async copyText(text) {
      try {
        await navigator.clipboard.writeText(text)
        this.copied = true
        setTimeout(() => { this.copied = false }, 1500)
      } catch (e) {
        this.message = 'Could not copy to the clipboard.'
        this.messageType = 'error'
      }
    },
    openFieldModal(cfg, key, value) {
      this.clearMessages()
      this.fieldModal = {
        module: String((cfg || {}).module || ''),
        key,
        value,
        description: this.fieldDescription(cfg, key)
      }
      this.fieldModalTab = 'formatted'
      this.fieldFilter = ''
      this.revealSecrets = false
      this.copied = false
      this.showFieldModal = true
    },
    closeFieldModal() {
      this.showFieldModal = false
      this.revealSecrets = false
      this.fieldFilter = ''
    },
    editFromFieldModal() {
      const { module, key, value } = this.fieldModal
      const cfg = this.configs.find(c => c.module === module) || { module }
      this.closeFieldModal()
      this.openEditModal(cfg, key, value)
    },
    async fetchConfigs() {
      this.loading = true
      this.error = ''
      try {
        const res = await apiFetch('/api/configuration/basicconfigs')
        const data = await res.json()
        if (!res.ok) {
          this.error = data.message || 'Failed to fetch configuration.'
          this.configs = []
          return
        }
        this.configs = Array.isArray(data.configs) ? data.configs : []
      } catch (e) {
        this.error = 'Network error while fetching configuration.'
        this.configs = []
      } finally {
        this.loading = false
      }
    },
    openViewModal(cfg) {
      this.clearMessages()
      this.selectedConfig = cfg || {}
      this.selectedModule = String((cfg || {}).module || '')
      this.revealSecrets = false
      this.copied = false
      this.showViewModal = true
    },
    closeViewModal() {
      this.showViewModal = false
      this.selectedConfig = null
      this.selectedModule = ''
      this.revealSecrets = false
    },
    openEditModal(cfg, key, value) {
      this.clearMessages()
      this.editModule = String((cfg || {}).module || '')
      this.editKey = key
      this.isAddOnlyEditor = this.isAddOnlyListField(key)

      if (this.isAddOnlyEditor) {
        this.currentListEntries = Array.isArray(value)
          ? value.map(v => String(v)).filter(v => v.trim() !== '')
          : []
        this.newListEntry = ''
        this.editValue = ''
      } else {
        this.currentListEntries = []
        this.newListEntry = ''
        this.editValue = typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value ?? '')
      }

      this.showEditModal = true
    },
    closeEditModal() {
      this.showEditModal = false
      this.editModule = ''
      this.editKey = ''
      this.editValue = ''
      this.isAddOnlyEditor = false
      this.currentListEntries = []
      this.newListEntry = ''
      this.saving = false
      this.formError = ''
    },
    async fetchMongoInitStatus() {
      this.mongoInitLoading = true
      this.mongoInitMessage = ''
      try {
        const res = await apiFetch('/api/configuration/mongo-init/status')
        const data = await res.json().catch(() => ({}))

        if (!res.ok) {
          this.mongoInitMessage = data.message || 'Failed to fetch Mongo init workflow status.'
          this.mongoInitMessageType = 'error'
          return
        }

        this.mongoInitStatus = data || null
      } catch (e) {
        this.mongoInitMessage = 'Network error while fetching Mongo init workflow status.'
        this.mongoInitMessageType = 'error'
      } finally {
        this.mongoInitLoading = false
      }
    },
    async triggerMongoInit() {
      this.mongoInitLoading = true
      this.mongoInitMessage = ''

      try {
        if (this.mongoInitMode === 'reset') {
          const confirmed = window.confirm('Reset will clear and repopulate configured collections from init file. Continue?')
          if (!confirmed) {
            this.mongoInitMessage = 'Reset cancelled.'
            this.mongoInitMessageType = 'error'
            return
          }
        }

        const payload = {
          mode: this.mongoInitMode
        }
        if (this.mongoInitFile) {
          payload.init_file_path = this.mongoInitFile
        }

        const res = await apiFetch('/api/configuration/mongo-init/trigger', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        })
        const data = await res.json().catch(() => ({}))

        if (!res.ok) {
          this.mongoInitMessage = data.message || data.reason || 'Failed to run Mongo init workflow.'
          this.mongoInitMessageType = 'error'
          return
        }

        const resultStatus = String(data.status || '').toLowerCase()
        if (resultStatus === 'completed') {
          this.mongoInitMessage = `Workflow completed (${data.mode || this.mongoInitMode}).`
          this.mongoInitMessageType = 'success'
        } else if (resultStatus === 'skipped') {
          this.mongoInitMessage = `Workflow skipped: ${data.reason || 'unknown reason'}.`
          this.mongoInitMessageType = 'error'
        } else {
          this.mongoInitMessage = 'Workflow triggered.'
          this.mongoInitMessageType = 'success'
        }

        await this.fetchMongoInitStatus()
      } catch (e) {
        this.mongoInitMessage = 'Network error while triggering Mongo init workflow.'
        this.mongoInitMessageType = 'error'
      } finally {
        this.mongoInitLoading = false
      }
    },
    parseRestrictedPagesMap(textValue) {
      const lines = String(textValue || '').split('\n')
      const result = {}

      for (const line of lines) {
        const raw = String(line || '').trim()
        if (!raw || raw.startsWith('#')) {
          continue
        }

        const separatorIndex = raw.indexOf('=')
        if (separatorIndex < 0) {
          continue
        }

        let path = raw.slice(0, separatorIndex).trim()
        const role = raw.slice(separatorIndex + 1).trim().toLowerCase()
        if (!path) {
          continue
        }
        if (!path.startsWith('/')) {
          path = `/${path}`
        }
        if (role !== 'admin' && role !== 'user') {
          continue
        }

        result[path] = role
      }

      return result
    },
    formatRestrictedPagesMap(mapValue) {
      if (!mapValue || typeof mapValue !== 'object') {
        return ''
      }

      return Object.keys(mapValue)
        .sort()
        .map((path) => `${path}=${String(mapValue[path] || '').toLowerCase()}`)
        .join('\n')
    },
    async fetchRbacConfig() {
      this.rbacLoading = true
      this.rbacMessage = ''
      try {
        const res = await apiFetch('/api/configuration/rbac')
        const data = await res.json().catch(() => ({}))

        if (!res.ok) {
          this.rbacMessage = data.message || 'Failed to fetch RBAC configuration.'
          this.rbacMessageType = 'error'
          return
        }

        const rbac = (data && typeof data.rbac === 'object' && data.rbac) ? data.rbac : {}
        this.rbacRestrictedPagesText = this.formatRestrictedPagesMap(rbac.restricted_pages)
      } catch (e) {
        this.rbacMessage = 'Network error while fetching RBAC configuration.'
        this.rbacMessageType = 'error'
      } finally {
        this.rbacLoading = false
      }
    },
    async saveRbacConfig() {
      this.rbacLoading = true
      this.rbacMessage = ''

      try {
        const restrictedPages = this.parseRestrictedPagesMap(this.rbacRestrictedPagesText)
        const payload = {
          rbac: {
            restricted_pages: restrictedPages
          }
        }

        const res = await apiFetch('/api/configuration/rbac/update', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        })
        const data = await res.json().catch(() => ({}))

        if (!res.ok) {
          this.rbacMessage = data.message || 'Failed to update RBAC configuration.'
          this.rbacMessageType = 'error'
          return
        }

        this.rbacMessage = data.message || 'RBAC configuration updated successfully.'
        this.rbacMessageType = 'success'
        await this.fetchRbacConfig()
      } catch (e) {
        this.rbacMessage = 'Network error while updating RBAC configuration.'
        this.rbacMessageType = 'error'
      } finally {
        this.rbacLoading = false
      }
    },
    async submitAddEntry() {
      if (!this.editModule || !this.editKey) {
        this.formError = 'Invalid module or field.'
        return
      }

      const entry = String(this.newListEntry || '').trim()
      if (!entry) {
        this.formError = 'Please enter a value to add.'
        return
      }

      const existingNormalized = this.currentListEntries.map(v => String(v).trim().toLowerCase())
      if (existingNormalized.includes(entry.toLowerCase())) {
        this.formError = 'This entry already exists.'
        return
      }

      this.saving = true
      this.formError = ''
      try {
        const existing = this.configs.find(c => c.module === this.editModule) || {}
        const payload = { ...existing }
        delete payload._id

        payload[this.editKey] = [...this.currentListEntries, entry]

        const res = await apiFetch('/api/configuration/basicconfigs/update', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            module: this.editModule,
            config: payload
          })
        })

        const data = await res.json()
        if (!res.ok) {
          this.formError = data.message || 'Failed to add entry.'
          return
        }

        this.message = data.message || 'Configuration updated successfully.'
        this.messageType = 'success'
        this.closeEditModal()
        await this.fetchConfigs()
      } catch (e) {
        this.formError = 'Network error while saving configuration.'
      } finally {
        this.saving = false
      }
    },
    async submitEdit() {
      if (!this.editModule || !this.editKey) {
        this.formError = 'Invalid module or field.'
        return
      }

      // Try to parse as JSON first (for objects/arrays/booleans/numbers), else treat as string
      let parsedValue
      try {
        parsedValue = JSON.parse(this.editValue)
      } catch (e) {
        parsedValue = this.editValue
      }

      this.saving = true
      this.formError = ''
      try {
        // Merge updated field into the existing config
        const existing = this.configs.find(c => c.module === this.editModule) || {}
        const payload = { ...existing }
        delete payload._id
        payload[this.editKey] = parsedValue

        const res = await apiFetch('/api/configuration/basicconfigs/update', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            module: this.editModule,
            config: payload
          })
        })

        const data = await res.json()
        if (!res.ok) {
          this.formError = data.message || 'Failed to save configuration.'
          return
        }

        this.message = data.message || 'Configuration updated successfully.'
        this.messageType = 'success'
        this.closeEditModal()
        await this.fetchConfigs()
      } catch (e) {
        this.formError = 'Network error while saving configuration.'
      } finally {
        this.saving = false
      }
    }
  }
}
</script>

<style scoped>
.config-key {
  flex: 0 0 280px;
  max-width: 280px;
  font-size: 0.875rem;
}
.config-key-name {
  font-weight: 500;
  font-family: var(--bs-font-monospace);
  word-break: break-word;
}
.config-desc {
  font-size: 0.75rem;
  line-height: 1.3;
  margin-top: 2px;
}
.config-value {
  font-size: 0.875rem;
  min-width: 0;
  padding-top: 2px;
}
.config-text {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: bottom;
}
.config-actions {
  flex-shrink: 0;
}
.config-row:last-child {
  border-bottom: none !important;
}
.config-row:hover {
  background-color: var(--bs-tertiary-bg, #f8f9fa);
}
.chip {
  font-weight: 500;
  font-family: var(--bs-font-monospace);
}
.kv {
  font-size: 0.8125rem;
  white-space: nowrap;
}
.field-list {
  max-height: 50vh;
  overflow-y: auto;
}
.field-table-key {
  width: 35%;
  font-family: var(--bs-font-monospace);
  font-size: 0.8125rem;
  word-break: break-word;
}
.field-scalar {
  font-size: 1rem;
  word-break: break-word;
}
.json-inline {
  font-size: 0.8125rem;
  background: #f8f9fa;
  border-radius: 6px;
  padding: 0.5rem;
  white-space: pre-wrap;
  word-break: break-word;
}
@media (max-width: 768px) {
  .config-row {
    flex-wrap: wrap;
  }
  .config-key {
    flex: 1 1 100%;
    max-width: 100%;
    margin-bottom: 0.25rem;
  }
  .config-actions {
    margin-left: 0 !important;
    margin-top: 0.5rem;
  }
}
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
  width: 95%;
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

.json-preview {
  background: #f8f9fa;
  border: 1px solid #e9ecef;
  border-radius: 8px;
  padding: 1rem;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 65vh;
  overflow-y: auto;
  font-size: 0.9rem;
}

.readonly-list {
  border: 1px solid #e9ecef;
  border-radius: 8px;
  padding: 0.75rem;
  background: #f8f9fa;
  max-height: 180px;
  overflow-y: auto;
}

.list-entry-chip {
  font-weight: 500;
}
</style>
