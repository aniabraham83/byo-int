<template>
  <div class="change-logs-page">
    <div class="page-header">
      <h2>Platform Change Logs</h2>
      <p class="page-subtitle">Track create, update, and delete activity from UI and external API clients.</p>
    </div>

    <div class="filter-bar">
      <div class="filter-group">
        <label>Action</label>
        <select v-model="filters.action" @change="onFilterChange">
          <option value="">All</option>
          <option value="created">Add</option>
          <option value="updated">Update</option>
          <option value="deleted">Delete</option>
          <option value="changed">Change</option>
        </select>
      </div>

      <div class="filter-group">
        <label>Source</label>
        <select v-model="filters.source" @change="onFilterChange">
          <option value="">All</option>
          <option value="ui">UI</option>
          <option value="external_api">External API</option>
          <option value="system">System</option>
        </select>
      </div>

      <div class="filter-group">
        <label>Actor</label>
        <input v-model="filters.actor" @input="onFilterChange" placeholder="username" />
      </div>

      <div class="filter-group">
        <label>Entity</label>
        <input v-model="filters.entity" @input="onFilterChange" placeholder="datapull, users, tags..." />
      </div>

      <div class="filter-group filter-search">
        <label>Search</label>
        <input v-model="filters.search" @input="onFilterChange" placeholder="path, actor, entity id" />
      </div>

      <div class="filter-actions">
        <button class="btn-secondary" @click="resetFilters">Reset</button>
        <button class="btn-primary" @click="loadLogs">Refresh</button>
      </div>
    </div>

    <div class="summary-bar" v-if="!loading">
      <span>Showing <strong>{{ logs.length }}</strong> of <strong>{{ total }}</strong> entries</span>
      <span v-if="activeFilterCount > 0" class="filtered-badge">Filtered</span>
    </div>

    <div v-if="loading" class="state-msg">Loading change logs...</div>
    <div v-else-if="error" class="state-msg error">{{ error }}</div>
    <div v-else-if="logs.length === 0" class="state-msg">No platform change logs found.</div>

    <div v-else class="table-wrapper">
      <table class="change-table">
        <thead>
          <tr>
            <th>Time</th>
            <th>Action</th>
            <th>Summary</th>
            <th>Entity</th>
            <th>Entity ID</th>
            <th>Actor</th>
            <th>Source</th>
            <th>Path</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="log in logs"
            :key="log.request_id + '_' + log.created_at"
            @click="selectLog(log)"
            :class="{ selected: selectedLog && selectedLog.request_id === log.request_id }"
          >
            <td>{{ formatTime(log.created_at) }}</td>
            <td><span :class="['action-badge', 'action-' + (log.action || 'changed')]">{{ displayAction(log.action) }}</span></td>
            <td class="summary-col" :title="summaryText(log)">{{ summaryText(log) }}</td>
            <td>{{ log.entity || '-' }}</td>
            <td class="mono">{{ log.entity_id || '-' }}</td>
            <td>{{ log.actor || '-' }}</td>
            <td><span :class="['source-badge', 'source-' + (log.source || 'system')]">{{ log.source || 'system' }}</span></td>
            <td class="mono path-col" :title="log.path">{{ log.path || '-' }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="pagination" v-if="total > pageSize">
      <button :disabled="currentPage === 0" @click="prevPage" class="btn-secondary">Prev</button>
      <span>Page {{ currentPage + 1 }} of {{ totalPages }}</span>
      <button :disabled="currentPage >= totalPages - 1" @click="nextPage" class="btn-secondary">Next</button>
    </div>

    <div v-if="selectedLog" class="detail-panel">
      <div class="detail-header">
        <h3>Change Detail</h3>
        <button class="btn-close" @click="selectedLog = null">x</button>
      </div>
      <div class="detail-grid">
        <div><strong>Request ID:</strong> <span class="mono">{{ selectedLog.request_id }}</span></div>
        <div><strong>Time:</strong> {{ formatTime(selectedLog.created_at) }}</div>
        <div><strong>Action:</strong> {{ displayAction(selectedLog.action) }}</div>
        <div><strong>Actor:</strong> {{ selectedLog.actor || '-' }}</div>
        <div><strong>Source:</strong> {{ selectedLog.source || '-' }}</div>
        <div><strong>Entity:</strong> {{ selectedLog.entity || '-' }}</div>
        <div><strong>Entity ID:</strong> <span class="mono">{{ selectedLog.entity_id || '-' }}</span></div>
        <div><strong>Method:</strong> {{ selectedLog.method || '-' }}</div>
        <div><strong>Path:</strong> <span class="mono">{{ selectedLog.path || '-' }}</span></div>
        <div><strong>Client IP:</strong> {{ selectedLog.client_ip || '-' }}</div>
      </div>

      <div class="detail-section">
        <h4>Summary</h4>
        <div>{{ summaryText(selectedLog) }}</div>
      </div>

      <div class="detail-section">
        <h4>Changed Fields</h4>
        <div v-if="Array.isArray(selectedLog.change_fields) && selectedLog.change_fields.length">
          {{ selectedLog.change_fields.join(', ') }}
        </div>
        <div v-else>-</div>
      </div>

      <div class="detail-section" v-if="Array.isArray(selectedLog.field_changes) && selectedLog.field_changes.length">
        <h4>Field-Level Changes</h4>
        <div class="field-change-list">
          <div v-for="fc in selectedLog.field_changes" :key="fc.field" class="field-change-row">
            <div class="field-name">{{ fc.field }}</div>
            <div class="field-before"><strong>Before:</strong> {{ stringifyInline(fc.before) }}</div>
            <div class="field-after"><strong>After:</strong> {{ stringifyInline(fc.after) }}</div>
          </div>
        </div>
      </div>

      <div class="detail-section">
        <h4>Before Snapshot</h4>
        <pre class="json-box">{{ formatJson(selectedLog.before_snapshot) }}</pre>
      </div>

      <div class="detail-section">
        <h4>After Snapshot</h4>
        <pre class="json-box">{{ formatJson(selectedLog.after_snapshot) }}</pre>
      </div>

      <div class="detail-section">
        <h4>Request Payload</h4>
        <pre class="json-box">{{ formatJson(selectedLog.request_payload || selectedLog.changes) }}</pre>
      </div>

      <div class="detail-section">
        <h4>Response Payload</h4>
        <pre class="json-box">{{ formatJson(selectedLog.response_payload) }}</pre>
      </div>

      <div class="detail-section">
        <h4>Change Payload</h4>
        <pre class="json-box">{{ formatJson(selectedLog.changes) }}</pre>
      </div>
    </div>
  </div>
</template>

<script>
import { fetchPlatformChangeLogs } from '@/api'

export default {
  name: 'PlatformChangeLogs',
  data() {
    return {
      logs: [],
      total: 0,
      loading: false,
      error: null,
      selectedLog: null,
      currentPage: 0,
      pageSize: 100,
      filterTimeout: null,
      filters: {
        action: '',
        source: '',
        actor: '',
        entity: '',
        search: ''
      }
    }
  },
  computed: {
    totalPages() {
      return Math.max(1, Math.ceil(this.total / this.pageSize))
    },
    activeFilterCount() {
      return Object.values(this.filters).filter(v => String(v || '').trim() !== '').length
    }
  },
  mounted() {
    this.loadLogs()
  },
  methods: {
    async loadLogs() {
      this.loading = true
      this.error = null
      try {
        const result = await fetchPlatformChangeLogs({
          limit: this.pageSize,
          skip: this.currentPage * this.pageSize,
          ...this.filters
        })
        this.logs = Array.isArray(result.logs) ? result.logs : []
        this.total = Number(result.total || 0)
      } catch (e) {
        this.error = e.message || 'Failed to load platform change logs.'
      } finally {
        this.loading = false
      }
    },
    onFilterChange() {
      clearTimeout(this.filterTimeout)
      this.filterTimeout = setTimeout(() => {
        this.currentPage = 0
        this.loadLogs()
      }, 300)
    },
    resetFilters() {
      this.filters = {
        action: '',
        source: '',
        actor: '',
        entity: '',
        search: ''
      }
      this.currentPage = 0
      this.loadLogs()
    },
    selectLog(log) {
      this.selectedLog = this.selectedLog && this.selectedLog.request_id === log.request_id ? null : log
    },
    prevPage() {
      if (this.currentPage > 0) {
        this.currentPage -= 1
        this.loadLogs()
      }
    },
    nextPage() {
      if (this.currentPage < this.totalPages - 1) {
        this.currentPage += 1
        this.loadLogs()
      }
    },
    formatTime(ts) {
      if (!ts) return '-'
      return new Date(ts).toLocaleString()
    },
    displayAction(action) {
      const normalized = String(action || '').toLowerCase()
      if (normalized === 'created') return 'Add'
      if (normalized === 'updated') return 'Update'
      if (normalized === 'deleted') return 'Delete'
      if (normalized === 'changed') return 'Change'
      return normalized || 'Unknown'
    },
    summaryText(log) {
      const item = log || {}
      if (item.summary) {
        return String(item.summary)
      }
      const action = this.displayAction(item.action)
      const entity = String(item.entity || 'record').replace(/[_-]+/g, ' ')
      const entityId = item.entity_id ? ` '${item.entity_id}'` : ''
      if (action === 'Add') return `New ${entity}${entityId} was created.`
      if (action === 'Delete') return `${entity}${entityId} was deleted.`
      if (action === 'Update') return `${entity}${entityId} was updated.`
      return `${entity}${entityId} changed.`
    },
    formatJson(value) {
      try {
        return JSON.stringify(value || {}, null, 2)
      } catch (e) {
        return '{}'
      }
    },
    stringifyInline(value) {
      if (value === null || value === undefined) return '-'
      if (typeof value === 'object') {
        try {
          return JSON.stringify(value)
        } catch (e) {
          return '[object]'
        }
      }
      return String(value)
    }
  },
  beforeUnmount() {
    if (this.filterTimeout) {
      clearTimeout(this.filterTimeout)
    }
  }
}
</script>

<style scoped>
.change-logs-page { padding: 24px; }
.page-subtitle { color: #666; margin-bottom: 16px; }
.filter-bar { display: flex; flex-wrap: wrap; gap: 12px; padding: 12px; border: 1px solid #e5e7eb; border-radius: 8px; margin-bottom: 12px; }
.filter-group { display: flex; flex-direction: column; gap: 4px; min-width: 150px; }
.filter-group input, .filter-group select { padding: 6px 8px; border: 1px solid #cbd5e1; border-radius: 6px; }
.filter-search { min-width: 220px; }
.filter-actions { display: flex; align-items: end; gap: 8px; }
.btn-primary, .btn-secondary { border: 1px solid #cbd5e1; border-radius: 6px; padding: 8px 10px; background: #fff; cursor: pointer; }
.btn-primary { background: #0f766e; color: #fff; border-color: #0f766e; }
.summary-bar { margin-bottom: 10px; display: flex; gap: 10px; align-items: center; }
.filtered-badge { background: #fef3c7; color: #92400e; border-radius: 999px; padding: 2px 8px; font-size: 12px; }
.state-msg { padding: 14px; border: 1px solid #e5e7eb; border-radius: 8px; }
.state-msg.error { border-color: #fecaca; color: #991b1b; background: #fef2f2; }
.table-wrapper { overflow: auto; border: 1px solid #e5e7eb; border-radius: 8px; }
.change-table { width: 100%; border-collapse: collapse; }
.change-table th, .change-table td { padding: 8px; border-bottom: 1px solid #eef2f7; text-align: left; font-size: 13px; }
.change-table tr.selected { background: #f1f5f9; }
.summary-col { max-width: 360px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.path-col { max-width: 380px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.action-badge, .source-badge { border-radius: 999px; padding: 2px 8px; font-size: 12px; text-transform: capitalize; }
.action-created { background: #dcfce7; color: #166534; }
.action-updated, .action-changed { background: #e0f2fe; color: #075985; }
.action-deleted { background: #fee2e2; color: #991b1b; }
.source-ui { background: #ede9fe; color: #5b21b6; }
.source-external_api { background: #ffedd5; color: #9a3412; }
.source-system { background: #e2e8f0; color: #334155; }
.pagination { display: flex; gap: 10px; align-items: center; margin-top: 12px; }
.detail-panel { margin-top: 16px; border: 1px solid #e5e7eb; border-radius: 8px; padding: 14px; }
.detail-header { display: flex; justify-content: space-between; align-items: center; }
.detail-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 8px; margin-top: 10px; }
.detail-section { margin-top: 12px; }
.json-box { background: #0b1020; color: #dbeafe; padding: 10px; border-radius: 8px; max-height: 240px; overflow: auto; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, Liberation Mono, Courier New, monospace; }
.btn-close { border: none; background: transparent; cursor: pointer; }
.field-change-list { display: flex; flex-direction: column; gap: 8px; }
.field-change-row { border: 1px solid #e5e7eb; border-radius: 6px; padding: 8px; }
.field-name { font-weight: 600; margin-bottom: 4px; }
.field-before, .field-after { font-size: 13px; color: #334155; }
</style>
