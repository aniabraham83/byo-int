<template>
  <div class="container mt-4">
    <h2>Indicator Logs</h2>

    <div class="mb-3">
      <div class="input-group input-group-lg">
        <span class="input-group-text bg-white"><i>🔍</i></span>
        <input
          v-model="search"
          @input="onSearchInput"
          type="text"
          class="form-control"
          placeholder="Search across all log fields..."
        />
        <button v-if="search" class="btn btn-outline-secondary" @click="clearSearch">✕</button>
      </div>
    </div>

    <div class="d-flex align-items-center gap-2 mb-3 flex-wrap">
      <button class="btn btn-outline-primary" @click="fetchLogs" :disabled="loading">
        <span v-if="loading" class="spinner-border spinner-border-sm me-1"></span>
        Refresh
      </button>
      <select v-model.number="pageSize" class="form-select" style="width: 110px;" @change="onPageSizeChange">
        <option :value="25">25 / page</option>
        <option :value="50">50 / page</option>
        <option :value="100">100 / page</option>
        <option :value="250">250 / page</option>
      </select>
      <span class="text-muted small">{{ showingText }}</span>
    </div>

    <div v-if="error" class="alert alert-danger">{{ error }}</div>
    <div v-if="loading" class="text-center my-4">Loading...</div>

    <div v-if="!loading && logs.length" class="table-responsive">
      <table class="table table-striped table-bordered table-sm align-middle">
        <thead class="table-light">
          <tr>
            <th v-for="column in tableColumns" :key="column">{{ displayColumnName(column) }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(log, index) in logs" :key="`${index}-${log.event_time || ''}-${log.action || ''}`">
            <td v-for="column in tableColumns" :key="`${index}-${column}`" class="text-break">
              {{ formatCell(log[column]) }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <nav v-if="!loading && pages > 1" class="mt-3">
      <ul class="pagination mb-2">
        <li class="page-item" :class="{ disabled: page === 1 || loading }">
          <button class="page-link" @click="goToPage(page - 1)" :disabled="page === 1 || loading">Previous</button>
        </li>
        <li
          v-for="pageNumber in visiblePages"
          :key="pageNumber"
          class="page-item"
          :class="{ active: pageNumber === page }"
        >
          <button class="page-link" @click="goToPage(pageNumber)" :disabled="loading">{{ pageNumber }}</button>
        </li>
        <li class="page-item" :class="{ disabled: page === pages || loading }">
          <button class="page-link" @click="goToPage(page + 1)" :disabled="page === pages || loading">Next</button>
        </li>
      </ul>
      <div class="small text-muted">Page {{ page }} of {{ pages }}</div>
    </nav>

    <div v-if="!loading && !error && !logs.length" class="alert alert-info">
      No indicator logs found.
    </div>
  </div>
</template>

<script>
import { apiFetch } from '@/api'

export default {
  name: 'IndicatorLogsPage',
  data() {
    return {
      logs: [],
      loading: false,
      error: null,
      search: '',
      page: 1,
      pages: 0,
      pageSize: 50,
      total: 0,
      searchDebounceTimer: null
    }
  },
  computed: {
    showingText() {
      if (!this.total) {
        return 'Showing 0 entries'
      }

      const start = (this.page - 1) * this.pageSize + 1
      const end = Math.min((this.page - 1) * this.pageSize + this.logs.length, this.total)
      if (this.search) {
        return `Showing ${start}-${end} of ${this.total} matching logs`
      }
      return `Showing ${start}-${end} of ${this.total} logs`
    },
    tableColumns() {
      const preferredOrder = ['indicator_value', 'action', 'datapull_source', 'event_time', 'logged_at', 'indicator_type', 'details']
      const columnSet = new Set()

      this.logs.forEach((entry) => {
        Object.keys(entry || {}).forEach((key) => columnSet.add(key))
      })

      columnSet.delete('_id')

      const discovered = Array.from(columnSet)
      const orderedPreferred = preferredOrder.filter((key) => columnSet.has(key))
      const remaining = discovered.filter((key) => !preferredOrder.includes(key)).sort((a, b) => a.localeCompare(b))
      return [...orderedPreferred, ...remaining]
    },
    visiblePages() {
      if (this.pages <= 7) {
        return Array.from({ length: this.pages }, (_, index) => index + 1)
      }

      let start = Math.max(1, this.page - 3)
      let end = Math.min(this.pages, start + 6)
      start = Math.max(1, end - 6)

      return Array.from({ length: end - start + 1 }, (_, index) => start + index)
    }
  },
  methods: {
    displayColumnName(column) {
      if (column === 'indicator_value') {
        return 'indicator'
      }
      return column
    },
    formatCell(value) {
      if (value === null || value === undefined) {
        return ''
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
    onSearchInput() {
      this.page = 1
      if (this.searchDebounceTimer) {
        clearTimeout(this.searchDebounceTimer)
      }
      this.searchDebounceTimer = setTimeout(() => {
        this.fetchLogs()
      }, 300)
    },
    clearSearch() {
      this.search = ''
      this.page = 1
      this.fetchLogs()
    },
    onPageSizeChange() {
      this.page = 1
      this.fetchLogs()
    },
    goToPage(targetPage) {
      if (this.loading || targetPage < 1 || targetPage > this.pages || targetPage === this.page) {
        return
      }
      this.page = targetPage
      this.fetchLogs()
    },
    async fetchLogs() {
      this.loading = true
      this.error = null
      try {
        const params = new URLSearchParams({
          page: String(this.page),
          limit: String(this.pageSize)
        })

        if (this.search) {
          params.set('search', this.search)
        }

        const res = await apiFetch(`/api/indicator-logs?${params.toString()}`)
        const data = await res.json().catch(() => ({}))
        if (!res.ok) {
          this.logs = []
          this.total = 0
          this.pages = 0
          this.error = data.message || 'Failed to fetch indicator logs.'
          return
        }
        this.logs = Array.isArray(data.logs) ? data.logs : []
        this.total = Number(data.total || 0)
        this.pages = Number(data.pages || 0)
        this.page = Number(data.page || this.page)
      } catch (e) {
        this.logs = []
        this.total = 0
        this.pages = 0
        this.error = 'Failed to fetch indicator logs.'
      } finally {
        this.loading = false
      }
    }
  },
  mounted() {
    this.fetchLogs()
  },
  beforeUnmount() {
    if (this.searchDebounceTimer) {
      clearTimeout(this.searchDebounceTimer)
    }
  }
}
</script>