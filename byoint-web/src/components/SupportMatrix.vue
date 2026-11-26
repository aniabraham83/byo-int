<template>
  <div class="container-fluid mt-4 pb-5 px-4">
    <div class="d-flex justify-content-between align-items-center mb-4 flex-wrap gap-2">
      <div>
        <h2 class="mb-1">Support Matrix</h2>
        <p class="text-muted mb-0">Recorded integration testing: what has been verified, how, and what can be built with custom snippets</p>
      </div>
      <div class="d-flex gap-2">
        <button class="btn btn-outline-secondary" @click="fetchCapabilities" :disabled="loading">
          <span v-if="loading" class="spinner-border spinner-border-sm me-1"></span>
          Refresh
        </button>
        <button class="btn btn-primary" @click="openEditor()">+ Add Entry</button>
      </div>
    </div>

    <div v-if="error" class="alert alert-warning">{{ error }}</div>

    <div class="row g-3 mb-4">
      <div v-for="(meta, key) in statusMeta" :key="key" class="col-6 col-md-3">
        <button type="button" class="summary-tile w-100 text-start" :class="{ selected: statusFilter === key }" @click="toggleStatusFilter(key)">
          <div class="tile-value" :class="meta.text">{{ statusCounts[key] || 0 }}</div>
          <div class="tile-label">{{ meta.label }}</div>
        </button>
      </div>
    </div>

    <div class="d-flex flex-wrap gap-2 mb-3">
      <input v-model="searchQuery" type="text" class="form-control filter-input" placeholder="Search product, vendor, capability...">
      <select v-model="categoryFilter" class="form-select filter-select">
        <option value="">All categories</option>
        <option v-for="c in categories" :key="c" :value="c">{{ c }}</option>
      </select>
      <select v-model="methodFilter" class="form-select filter-select">
        <option value="">All methods</option>
        <option v-for="(label, key) in methodLabels" :key="key" :value="key">{{ label }}</option>
      </select>
      <select v-model="statusFilter" class="form-select filter-select">
        <option value="">All statuses</option>
        <option v-for="(meta, key) in statusMeta" :key="key" :value="key">{{ meta.label }}</option>
      </select>
    </div>

    <div class="table-responsive">
      <table class="table table-hover align-middle mb-0">
        <thead class="table-light">
          <tr>
            <th>Integration</th>
            <th>Category</th>
            <th>Method</th>
            <th>Capability</th>
            <th>Data Types</th>
            <th>Status</th>
            <th>Notes</th>
            <th class="text-end">Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="!loading && filteredRows.length === 0">
            <td colspan="8" class="text-center text-muted py-4">No entries match the current filters.</td>
          </tr>
          <tr v-for="row in filteredRows" :key="row._id">
            <td>
              <div class="fw-semibold">{{ row.product }}</div>
              <small v-if="row.vendor" class="text-muted d-block">{{ row.vendor }}</small>
              <small v-if="row.tested_version" class="text-muted d-block">Version: {{ row.tested_version }}</small>
              <small v-if="row.tested_by" class="text-muted d-block">Tested by {{ row.tested_by }}</small>
              <a v-if="row.reference_url" :href="row.reference_url" target="_blank" rel="noopener noreferrer" class="small">Reference ↗</a>
            </td>
            <td><span class="badge bg-light text-dark border">{{ row.category || '—' }}</span></td>
            <td>
              <span class="badge" :class="row.method === 'custom_snippet' ? 'bg-purple' : 'bg-primary-subtle text-primary-emphasis'">{{ methodLabels[row.method] || row.method }}</span>
              <div v-if="row.template_name"><code class="small">{{ row.template_name }}</code></div>
            </td>
            <td class="capability-cell">{{ row.capability || '—' }}</td>
            <td>
              <span v-for="t in (row.data_types || [])" :key="t" class="badge bg-light text-dark border me-1">{{ t }}</span>
              <span v-if="!(row.data_types || []).length" class="text-muted">—</span>
            </td>
            <td><span class="badge" :class="(statusMeta[row.status] || {}).badge">{{ (statusMeta[row.status] || {}).label || row.status }}</span></td>
            <td class="notes-cell"><small class="text-muted">{{ row.notes || '—' }}</small></td>
            <td class="text-end text-nowrap">
              <button v-if="row.snippet_example" class="btn btn-sm btn-outline-secondary me-1" @click="openSnippet(row)" title="View snippet">{ }</button>
              <button class="btn btn-sm btn-outline-primary me-1" @click="openEditor(row)">Edit</button>
              <button class="btn btn-sm btn-outline-danger" @click="deleteEntry(row)">Delete</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Add / Edit Modal -->
    <div v-if="showEditor" class="modal-overlay" @click.self="closeEditor">
      <div class="modal-content modal-wide">
        <div class="modal-header">
          <h5 class="modal-title">{{ editingId ? 'Edit Entry' : 'Add Entry' }}</h5>
          <button type="button" class="btn-close" @click="closeEditor"></button>
        </div>
        <div class="modal-body">
          <div class="row g-3">
            <div class="col-md-6">
              <label class="form-label">Product <span class="text-danger">*</span></label>
              <input v-model="form.product" type="text" class="form-control" placeholder="e.g. PostgreSQL">
            </div>
            <div class="col-md-6">
              <label class="form-label">Vendor</label>
              <input v-model="form.vendor" type="text" class="form-control">
            </div>
            <div class="col-md-4">
              <label class="form-label">Category</label>
              <input v-model="form.category" type="text" class="form-control" list="capability-categories" placeholder="e.g. Database">
              <datalist id="capability-categories">
                <option v-for="c in categories" :key="c" :value="c"></option>
              </datalist>
            </div>
            <div class="col-md-4">
              <label class="form-label">Method</label>
              <select v-model="form.method" class="form-select">
                <option v-for="(label, key) in methodLabels" :key="key" :value="key">{{ label }}</option>
              </select>
            </div>
            <div class="col-md-4">
              <label class="form-label">Status</label>
              <select v-model="form.status" class="form-select">
                <option v-for="(meta, key) in statusMeta" :key="key" :value="key">{{ meta.label }}</option>
              </select>
            </div>
            <div class="col-md-6">
              <label class="form-label">Linked Template</label>
              <select v-model="form.template_name" class="form-select">
                <option value="">— none —</option>
                <option v-for="t in templates" :key="t.template_name" :value="t.template_name">{{ t.template_name }} ({{ t.template_type }})</option>
              </select>
            </div>
            <div class="col-md-6">
              <label class="form-label">Data Types</label>
              <input v-model="form.data_types" type="text" class="form-control" placeholder="Comma-separated, e.g. ipv4,domain">
            </div>
            <div class="col-12">
              <label class="form-label">Capability</label>
              <input v-model="form.capability" type="text" class="form-control" placeholder="What the integration pulls or does">
            </div>
            <div class="col-md-6">
              <label class="form-label">Tested By</label>
              <input v-model="form.tested_by" type="text" class="form-control">
            </div>
            <div class="col-md-6">
              <label class="form-label">Tested Version</label>
              <input v-model="form.tested_version" type="text" class="form-control" placeholder="e.g. PostgreSQL 16.4">
            </div>
            <div class="col-12">
              <label class="form-label">Reference URL</label>
              <input v-model="form.reference_url" type="url" class="form-control">
            </div>
            <div class="col-12">
              <label class="form-label">Notes</label>
              <textarea v-model="form.notes" class="form-control" rows="2"></textarea>
            </div>
            <div class="col-12">
              <label class="form-label">Snippet Example</label>
              <textarea v-model="form.snippet_example" class="form-control font-monospace" rows="8" placeholder="Custom template snippet that produces result_list"></textarea>
            </div>
          </div>
          <div v-if="formError" class="alert alert-warning small mt-3 mb-0">{{ formError }}</div>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" @click="closeEditor">Cancel</button>
          <button type="button" class="btn btn-primary" @click="saveEntry" :disabled="saving">
            <span v-if="saving" class="spinner-border spinner-border-sm me-2"></span>
            {{ editingId ? 'Save Changes' : 'Create Entry' }}
          </button>
        </div>
      </div>
    </div>

    <!-- Snippet Modal -->
    <div v-if="snippetRow" class="modal-overlay" @click.self="snippetRow = null">
      <div class="modal-content modal-wide">
        <div class="modal-header">
          <h5 class="modal-title">{{ snippetRow.product }} — custom snippet</h5>
          <button type="button" class="btn-close" @click="snippetRow = null"></button>
        </div>
        <div class="modal-body">
          <p class="small text-muted mb-2">
            Create a <strong>Custom</strong> template on the Datapull Templates page with this snippet.
            Fields referenced in the snippet (e.g. <code>*_secret_ref</code>) must be added as ufield_args.
          </p>
          <pre class="snippet-block">{{ snippetRow.snippet_example }}</pre>
        </div>
        <div class="modal-footer">
          <span v-if="copied" class="text-success small me-auto">Copied to clipboard</span>
          <button type="button" class="btn btn-outline-primary" @click="copySnippet">Copy</button>
          <button type="button" class="btn btn-secondary" @click="snippetRow = null">Close</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { apiFetch } from '@/api'

const EMPTY_FORM = {
  product: '',
  vendor: '',
  category: '',
  method: 'builtin',
  status: 'untested',
  template_name: '',
  data_types: '',
  capability: '',
  tested_by: '',
  tested_version: '',
  reference_url: '',
  notes: '',
  snippet_example: ''
}

export default {
  name: 'SupportMatrix',
  data() {
    return {
      loading: false,
      error: '',
      capabilities: [],
      templates: [],
      searchQuery: '',
      categoryFilter: '',
      methodFilter: '',
      statusFilter: '',
      showEditor: false,
      editingId: null,
      form: { ...EMPTY_FORM },
      formError: '',
      saving: false,
      snippetRow: null,
      copied: false,
      methodLabels: {
        builtin: 'Built-in',
        custom_snippet: 'Custom snippet'
      },
      statusMeta: {
        tested: { label: 'Tested', badge: 'bg-success', text: 'text-success' },
        partial: { label: 'Partially tested', badge: 'bg-warning text-dark', text: 'text-warning' },
        untested: { label: 'Not tested', badge: 'bg-secondary', text: 'text-secondary' },
        unsupported: { label: 'Not supported', badge: 'bg-danger', text: 'text-danger' }
      }
    }
  },
  computed: {
    categories() {
      return [...new Set(this.capabilities.map((c) => c.category).filter(Boolean))].sort()
    },
    statusCounts() {
      const counts = {}
      this.capabilities.forEach((c) => { counts[c.status] = (counts[c.status] || 0) + 1 })
      return counts
    },
    filteredRows() {
      const q = this.searchQuery.trim().toLowerCase()
      return this.capabilities.filter((r) => {
        if (this.categoryFilter && r.category !== this.categoryFilter) return false
        if (this.methodFilter && r.method !== this.methodFilter) return false
        if (this.statusFilter && r.status !== this.statusFilter) return false
        if (!q) return true
        return [r.product, r.vendor, r.category, r.template_name, r.capability, r.notes, (r.data_types || []).join(' ')]
          .some((v) => String(v || '').toLowerCase().includes(q))
      })
    }
  },
  methods: {
    toggleStatusFilter(key) {
      this.statusFilter = this.statusFilter === key ? '' : key
    },
    async fetchCapabilities() {
      this.loading = true
      this.error = ''
      try {
        const res = await apiFetch('/api/integration_capabilities')
        const data = await res.json()
        if (res.ok) {
          this.capabilities = Array.isArray(data.capabilities) ? data.capabilities : []
        } else {
          this.error = data.message || 'Failed to load the support matrix.'
        }
      } catch (e) {
        this.error = 'Network error while loading the support matrix.'
      } finally {
        this.loading = false
      }
    },
    async fetchTemplates() {
      try {
        const res = await apiFetch('/api/datapull_templates')
        if (res.ok) {
          const data = await res.json()
          this.templates = Array.isArray(data.templates) ? data.templates : []
        }
      } catch (e) {
        this.templates = []
      }
    },
    openEditor(row = null) {
      this.formError = ''
      this.editingId = row ? row._id : null
      this.form = { ...EMPTY_FORM }
      if (row) {
        Object.keys(EMPTY_FORM).forEach((key) => {
          const value = row[key]
          this.form[key] = key === 'data_types' ? (value || []).join(', ') : (value ?? EMPTY_FORM[key])
        })
      }
      this.showEditor = true
    },
    closeEditor() {
      this.showEditor = false
      this.editingId = null
    },
    async saveEntry() {
      this.formError = ''
      if (!String(this.form.product || '').trim()) {
        this.formError = 'Product is required.'
        return
      }
      this.saving = true
      try {
        const url = this.editingId
          ? `/api/integration_capabilities/${encodeURIComponent(this.editingId)}`
          : '/api/integration_capabilities'
        const res = await apiFetch(url, {
          method: this.editingId ? 'PUT' : 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(this.form)
        })
        const data = await res.json()
        if (!res.ok) {
          this.formError = data.message || 'Failed to save entry.'
          return
        }
        this.closeEditor()
        await this.fetchCapabilities()
      } catch (e) {
        this.formError = 'Network error while saving.'
      } finally {
        this.saving = false
      }
    },
    async deleteEntry(row) {
      if (!confirm(`Delete "${row.product}" from the support matrix?`)) return
      try {
        const res = await apiFetch(`/api/integration_capabilities/${encodeURIComponent(row._id)}`, { method: 'DELETE' })
        if (!res.ok) {
          const data = await res.json()
          this.error = data.message || 'Failed to delete entry.'
          return
        }
        await this.fetchCapabilities()
      } catch (e) {
        this.error = 'Network error while deleting.'
      }
    },
    openSnippet(row) {
      this.copied = false
      this.snippetRow = row
    },
    async copySnippet() {
      try {
        await navigator.clipboard.writeText(this.snippetRow.snippet_example || '')
        this.copied = true
      } catch (e) {
        this.copied = false
      }
    }
  },
  mounted() {
    this.fetchCapabilities()
    this.fetchTemplates()
  }
}
</script>

<style scoped>
.summary-tile {
  border-radius: 12px;
  padding: 1rem 1.25rem;
  background: #fff;
  border: 1px solid #e2e8f0;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
  transition: border-color 0.15s ease;
}

.summary-tile:hover,
.summary-tile.selected {
  border-color: #0d6efd;
}

.tile-value {
  font-size: 1.75rem;
  font-weight: 700;
  line-height: 1.1;
}

.tile-label {
  color: #64748b;
  font-size: 0.85rem;
}

.filter-input {
  max-width: 320px;
}

.filter-select {
  max-width: 200px;
}

.capability-cell {
  min-width: 200px;
}

.notes-cell {
  min-width: 220px;
  max-width: 340px;
}

.bg-purple {
  background-color: #6f42c1;
  color: #fff;
}

.table-responsive {
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
}

code {
  background-color: #f5f5f5;
  padding: 0.1rem 0.3rem;
  border-radius: 4px;
}

.snippet-block {
  background: #0f172a;
  color: #e2e8f0;
  padding: 1rem;
  border-radius: 8px;
  font-size: 0.8rem;
  max-height: 60vh;
  overflow: auto;
  white-space: pre;
}

.modal-overlay {
  position: fixed;
  inset: 0;
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

.modal-wide {
  max-width: 820px;
}

.modal-header,
.modal-footer {
  padding: 1.25rem 1.5rem;
  display: flex;
  align-items: center;
}

.modal-header {
  border-bottom: 1px solid #e9ecef;
  justify-content: space-between;
}

.modal-footer {
  border-top: 1px solid #e9ecef;
  justify-content: flex-end;
  gap: 0.5rem;
}

.modal-title {
  font-size: 1.15rem;
  font-weight: 600;
  margin: 0;
}

.modal-body {
  padding: 1.5rem;
}

.btn-close {
  background: none;
  border: none;
  font-size: 1.5rem;
  cursor: pointer;
  color: #666;
}

@media (max-width: 768px) {
  .filter-input,
  .filter-select {
    max-width: 100%;
  }
}
</style>
