<template>
  <div class="audit-logs-page">
    <div class="page-header">
      <h2>🔍 API Audit Logs</h2>
      <p class="page-subtitle">Review all API requests captured by the platform.</p>
    </div>

    <!-- Filters -->
    <div class="filter-bar">
      <div class="filter-group">
        <label>Method</label>
        <select v-model="filters.method" @change="onFilterChange">
          <option value="">All</option>
          <option>GET</option>
          <option>POST</option>
          <option>PUT</option>
          <option>PATCH</option>
          <option>DELETE</option>
        </select>
      </div>

      <div class="filter-group">
        <label>Path contains</label>
        <input v-model="filters.path" @input="onFilterChange" placeholder="/api/..." />
      </div>

      <div class="filter-group">
        <label>User</label>
        <input v-model="filters.user" @input="onFilterChange" placeholder="username" />
      </div>

      <div class="filter-group">
        <label>Status code</label>
        <select v-model="filters.status_code" @change="onFilterChange">
          <option value="">All</option>
          <option>200</option>
          <option>201</option>
          <option>400</option>
          <option>401</option>
          <option>403</option>
          <option>404</option>
          <option>500</option>
        </select>
      </div>

      <div class="filter-group filter-actions">
        <button class="btn-secondary" @click="resetFilters">Reset</button>
        <button class="btn-primary" @click="loadLogs">Refresh</button>
      </div>
    </div>

    <!-- Summary bar -->
    <div class="summary-bar" v-if="!loading">
      <span>Showing <strong>{{ logs.length }}</strong> of <strong>{{ total }}</strong> entries</span>
      <span v-if="filters.method || filters.path || filters.user || filters.status_code" class="filtered-badge">Filtered</span>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="loading-state">Loading audit logs...</div>

    <!-- Error -->
    <div v-else-if="error" class="error-state">{{ error }}</div>

    <!-- Empty -->
    <div v-else-if="logs.length === 0" class="empty-state">No audit log entries found.</div>

    <!-- Log table -->
    <div v-else class="table-wrapper">
      <table class="audit-table">
        <thead>
          <tr>
            <th>Timestamp</th>
            <th>Method</th>
            <th>Path</th>
            <th>Status</th>
            <th>User</th>
            <th>Duration</th>
            <th>IP</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="log in logs"
            :key="log.request_id"
            @click="selectLog(log)"
            :class="{ 'row-selected': selectedLog && selectedLog.request_id === log.request_id, 'row-error': log.status_code >= 400 }"
          >
            <td class="col-time">{{ formatTime(log.created_at) }}</td>
            <td>
              <span :class="['method-badge', 'method-' + log.method]">{{ log.method }}</span>
            </td>
            <td class="col-path" :title="log.path">{{ log.path }}</td>
            <td>
              <span :class="['status-badge', statusClass(log.status_code)]">{{ log.status_code }}</span>
            </td>
            <td class="col-user">{{ log.auth && log.auth.user ? log.auth.user : '—' }}</td>
            <td class="col-duration">{{ log.duration_ms != null ? log.duration_ms + 'ms' : '—' }}</td>
            <td class="col-ip">{{ log.source && log.source.ip ? log.source.ip : '—' }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Pagination -->
    <div class="pagination" v-if="total > pageSize">
      <button :disabled="currentPage === 0" @click="prevPage" class="btn-secondary">← Prev</button>
      <span>Page {{ currentPage + 1 }} of {{ totalPages }}</span>
      <button :disabled="currentPage >= totalPages - 1" @click="nextPage" class="btn-secondary">Next →</button>
    </div>

    <!-- Detail panel -->
    <transition name="slide">
      <div v-if="selectedLog" class="detail-panel">
        <div class="detail-header">
          <h3>Request Detail</h3>
          <button class="btn-close" @click="selectedLog = null">✕</button>
        </div>
        <div class="detail-grid">
          <div class="detail-row">
            <span class="detail-label">Request ID</span>
            <span class="detail-value mono">{{ selectedLog.request_id }}</span>
          </div>
          <div class="detail-row">
            <span class="detail-label">Timestamp</span>
            <span class="detail-value">{{ formatTimeFull(selectedLog.created_at) }}</span>
          </div>
          <div class="detail-row">
            <span class="detail-label">Method</span>
            <span class="detail-value"><span :class="['method-badge', 'method-' + selectedLog.method]">{{ selectedLog.method }}</span></span>
          </div>
          <div class="detail-row">
            <span class="detail-label">Path</span>
            <span class="detail-value mono">{{ selectedLog.path }}</span>
          </div>
          <div class="detail-row" v-if="selectedLog.query_keys && selectedLog.query_keys.length">
            <span class="detail-label">Query Keys</span>
            <span class="detail-value mono">{{ selectedLog.query_keys.join(', ') }}</span>
          </div>
          <div class="detail-row">
            <span class="detail-label">Status Code</span>
            <span class="detail-value"><span :class="['status-badge', statusClass(selectedLog.status_code)]">{{ selectedLog.status_code }}</span></span>
          </div>
          <div class="detail-row">
            <span class="detail-label">Duration</span>
            <span class="detail-value">{{ selectedLog.duration_ms != null ? selectedLog.duration_ms + ' ms' : '—' }}</span>
          </div>
          <div class="detail-row">
            <span class="detail-label">User</span>
            <span class="detail-value">{{ selectedLog.auth && selectedLog.auth.user ? selectedLog.auth.user : '—' }}</span>
          </div>
          <div class="detail-row">
            <span class="detail-label">Auth Type</span>
            <span class="detail-value">{{ selectedLog.auth && selectedLog.auth.type ? selectedLog.auth.type : '—' }}</span>
          </div>
          <div class="detail-row">
            <span class="detail-label">IP Address</span>
            <span class="detail-value mono">{{ selectedLog.source && selectedLog.source.ip ? selectedLog.source.ip : '—' }}</span>
          </div>
          <div class="detail-row">
            <span class="detail-label">User Agent</span>
            <span class="detail-value mono small">{{ selectedLog.source && selectedLog.source.user_agent ? selectedLog.source.user_agent : '—' }}</span>
          </div>
          <div class="detail-row">
            <span class="detail-label">Content Type</span>
            <span class="detail-value">{{ selectedLog.request && selectedLog.request.content_type ? selectedLog.request.content_type : '—' }}</span>
          </div>
          <div class="detail-row">
            <span class="detail-label">Req Size</span>
            <span class="detail-value">{{ formatBytes(selectedLog.request && selectedLog.request.content_length) }}</span>
          </div>
          <div class="detail-row">
            <span class="detail-label">Resp Size</span>
            <span class="detail-value">{{ formatBytes(selectedLog.response && selectedLog.response.content_length) }}</span>
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>

<script>
import { fetchAuditLogs } from '@/api'

export default {
  name: 'AuditLogs',
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
        method: '',
        path: '',
        user: '',
        status_code: '',
      },
    }
  },
  computed: {
    totalPages() {
      return Math.max(1, Math.ceil(this.total / this.pageSize))
    },
  },
  mounted() {
    this.loadLogs()
  },
  methods: {
    async loadLogs() {
      this.loading = true
      this.error = null
      try {
        const result = await fetchAuditLogs({
          limit: this.pageSize,
          skip: this.currentPage * this.pageSize,
          ...this.activeFilters(),
        })
        this.logs = result.logs
        this.total = result.total
      } catch (e) {
        this.error = e.message || 'Failed to load audit logs.'
      } finally {
        this.loading = false
      }
    },
    activeFilters() {
      const f = {}
      if (this.filters.method) f.method = this.filters.method
      if (this.filters.path) f.path = this.filters.path
      if (this.filters.user) f.user = this.filters.user
      if (this.filters.status_code) f.status_code = this.filters.status_code
      return f
    },
    onFilterChange() {
      clearTimeout(this.filterTimeout)
      this.filterTimeout = setTimeout(() => {
        this.currentPage = 0
        this.loadLogs()
      }, 400)
    },
    resetFilters() {
      this.filters = { method: '', path: '', user: '', status_code: '' }
      this.currentPage = 0
      this.loadLogs()
    },
    selectLog(log) {
      this.selectedLog = this.selectedLog && this.selectedLog.request_id === log.request_id ? null : log
    },
    prevPage() {
      if (this.currentPage > 0) {
        this.currentPage--
        this.loadLogs()
      }
    },
    nextPage() {
      if (this.currentPage < this.totalPages - 1) {
        this.currentPage++
        this.loadLogs()
      }
    },
    formatTime(ts) {
      if (!ts) return '—'
      return new Date(ts).toLocaleString()
    },
    formatTimeFull(ts) {
      if (!ts) return '—'
      return new Date(ts).toISOString().replace('T', ' ').substring(0, 23) + ' UTC'
    },
    formatBytes(bytes) {
      if (bytes == null) return '—'
      if (bytes < 1024) return bytes + ' B'
      return (bytes / 1024).toFixed(1) + ' KB'
    },
    statusClass(code) {
      if (code >= 500) return 'status-5xx'
      if (code >= 400) return 'status-4xx'
      if (code >= 300) return 'status-3xx'
      return 'status-2xx'
    },
  },
}
</script>

<style scoped>
.audit-logs-page {
  padding: 24px;
  position: relative;
}

.page-header h2 {
  margin: 0 0 4px;
}

.page-subtitle {
  color: #666;
  margin: 0 0 20px;
  font-size: 14px;
}

/* Filters */
.filter-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: flex-end;
  margin-bottom: 16px;
  padding: 14px 16px;
  background: #f8f9fa;
  border-radius: 8px;
  border: 1px solid #e9ecef;
}

.filter-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 120px;
}

.filter-group label {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  color: #888;
}

.filter-group input,
.filter-group select {
  padding: 6px 10px;
  border: 1px solid #ccc;
  border-radius: 4px;
  font-size: 13px;
  background: #fff;
}

.filter-actions {
  flex-direction: row;
  align-items: center;
  gap: 8px;
}

/* Summary */
.summary-bar {
  font-size: 13px;
  color: #555;
  margin-bottom: 10px;
  display: flex;
  align-items: center;
  gap: 10px;
}

.filtered-badge {
  background: #e7f3ff;
  color: #0066cc;
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 600;
}

/* States */
.loading-state,
.error-state,
.empty-state {
  padding: 40px;
  text-align: center;
  color: #888;
  font-size: 14px;
}

.error-state {
  color: #c0392b;
}

/* Table */
.table-wrapper {
  overflow-x: auto;
  border-radius: 8px;
  border: 1px solid #e0e0e0;
}

.audit-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.audit-table thead {
  background: #f1f3f5;
}

.audit-table th {
  padding: 10px 12px;
  text-align: left;
  font-weight: 600;
  color: #444;
  border-bottom: 2px solid #dee2e6;
  white-space: nowrap;
}

.audit-table td {
  padding: 8px 12px;
  border-bottom: 1px solid #f0f0f0;
  vertical-align: middle;
}

.audit-table tr:hover {
  background: #f5f8ff;
  cursor: pointer;
}

.row-selected {
  background: #e8f0fe !important;
}

.row-error td {
  background: #fff5f5;
}

.col-path {
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: monospace;
  font-size: 12px;
}

.col-time { white-space: nowrap; font-size: 12px; }
.col-user { max-width: 120px; overflow: hidden; text-overflow: ellipsis; }
.col-duration { white-space: nowrap; color: #555; }
.col-ip { font-family: monospace; font-size: 12px; }

/* Badges */
.method-badge {
  padding: 2px 7px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
}
.method-GET    { background: #d4edda; color: #155724; }
.method-POST   { background: #cce5ff; color: #004085; }
.method-PUT    { background: #fff3cd; color: #856404; }
.method-PATCH  { background: #ffeeba; color: #856404; }
.method-DELETE { background: #f8d7da; color: #721c24; }

.status-badge {
  padding: 2px 7px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
}
.status-2xx { background: #d4edda; color: #155724; }
.status-3xx { background: #d1ecf1; color: #0c5460; }
.status-4xx { background: #fff3cd; color: #856404; }
.status-5xx { background: #f8d7da; color: #721c24; }

/* Pagination */
.pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
  padding: 16px 0;
  font-size: 13px;
  color: #555;
}

/* Detail panel */
.detail-panel {
  position: fixed;
  top: 0;
  right: 0;
  width: 400px;
  height: 100%;
  background: #fff;
  border-left: 1px solid #ddd;
  box-shadow: -4px 0 20px rgba(0,0,0,0.1);
  overflow-y: auto;
  z-index: 200;
  padding: 0;
}

.detail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid #eee;
  position: sticky;
  top: 0;
  background: #fff;
}

.detail-header h3 {
  margin: 0;
  font-size: 15px;
}

.btn-close {
  background: none;
  border: none;
  font-size: 18px;
  cursor: pointer;
  color: #888;
  padding: 4px 8px;
}

.btn-close:hover { color: #333; }

.detail-grid {
  padding: 16px 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.detail-row {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.detail-label {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  color: #888;
}

.detail-value {
  font-size: 13px;
  color: #222;
  word-break: break-all;
}

.detail-value.mono {
  font-family: monospace;
  font-size: 12px;
  background: #f5f5f5;
  padding: 3px 6px;
  border-radius: 3px;
}

.detail-value.small {
  font-size: 11px;
}

/* Slide transition */
.slide-enter-active, .slide-leave-active { transition: transform 0.25s ease, opacity 0.25s; }
.slide-enter-from, .slide-leave-to { transform: translateX(100%); opacity: 0; }

/* Buttons */
.btn-primary, .btn-secondary {
  padding: 7px 14px;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
}
.btn-primary { background: #0066cc; color: #fff; }
.btn-primary:hover { background: #004fa3; }
.btn-secondary { background: #e9ecef; color: #333; }
.btn-secondary:hover { background: #d1d5db; }
.btn-secondary:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
