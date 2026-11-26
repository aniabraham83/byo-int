<template>
  <div class="container mt-4 pb-5">
    <div class="d-flex justify-content-between align-items-center mb-4">
      <div>
        <h2 class="mb-1">Output Details</h2>
        <p class="text-muted">Generated details for a selected enabled output</p>
        <p v-if="selectedName" class="mb-0 small text-primary">Output name: <strong>{{ selectedName }}</strong></p>
      </div>
      <div class="d-flex gap-2 align-items-center">
        <div v-if="rows.length > 0" class="dropdown">
          <button class="btn btn-outline-success dropdown-toggle" type="button" data-bs-toggle="dropdown" aria-expanded="false">
            Export
          </button>
          <ul class="dropdown-menu dropdown-menu-end">
            <li>
              <button class="dropdown-item" @click="exportText">📄 Export as Text (.txt)</button>
            </li>
            <li>
              <button class="dropdown-item" @click="exportJson">{ } Export as JSON (.json)</button>
            </li>
            <li>
              <button class="dropdown-item" @click="exportExcel">📊 Export as Excel (.xlsx)</button>
            </li>
          </ul>
        </div>
        <button class="btn btn-primary" @click="fetchOutputsEdl" :disabled="loading">
          <span v-if="loading" class="spinner-border spinner-border-sm me-2"></span>
          Refresh
        </button>
      </div>
    </div>

    <div v-if="loading" class="mt-3">
      <div class="spinner-border text-primary" role="status">
        <span class="visually-hidden">Loading...</span>
      </div>
    </div>

    <div v-else-if="error" class="alert alert-danger">{{ error }}</div>

    <div v-else>
      <div v-if="!selectedName" class="alert alert-info">Select an output from the Outputs page to view its details.</div>
      <div v-else-if="rows.length === 0" class="alert alert-info">No enabled output found for this name.</div>

      <div v-else class="edl-page-view">
        <div v-for="row in rows" :key="row.name + '_' + row.source_name" class="card mb-4">
          <div class="card-header d-flex justify-content-between align-items-center">
            <div>
              <strong>{{ row.name || '-' }}</strong>
              <span class="ms-2 text-muted">Source: {{ row.source_name || '-' }}</span>
            </div>
            <div>
              <span class="badge bg-info me-2">{{ row.type || '-' }}</span>
              <span class="badge bg-secondary">Count: {{ row.indicator_count || 0 }}</span>
            </div>
          </div>
          <div class="card-body">
            <div class="small text-muted mb-2" v-if="row.filter_search">Filter: {{ row.filter_search }}</div>
            <pre v-if="row.type === 'json'" class="json-view mb-0">{{ formatJsonOutput(row) }}</pre>
            <div v-else class="edl-html" v-html="row.edl || ''"></div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import ExcelJS from 'exceljs'
import { apiFetch } from '@/api'
export default {
  name: 'OutputsEdlPage',
  data() {
    return {
      rows: [],
      loading: false,
      error: '',
      selectedName: ''
    }
  },
  async mounted() {
    this.selectedName = (this.$route.query.name || '').toString().trim()
    await this.fetchOutputsEdl()
  },
  watch: {
    '$route.query.name': {
      immediate: false,
      async handler(val) {
        this.selectedName = (val || '').toString().trim()
        await this.fetchOutputsEdl()
      }
    }
  },
  methods: {
    exportText() {
      const lines = []
      for (const row of this.rows) {
        const entries = Array.isArray(row.entries) ? row.entries : []
        entries.forEach(e => lines.push(e))
      }
      const blob = new Blob([lines.join('\n')], { type: 'text/plain' })
      this._triggerDownload(blob, `${this.selectedName || 'output'}.txt`)
    },
    exportJson() {
      const payload = this.rows.map(row => ({
        name: row.name || '',
        source_name: row.source_name || [],
        type: row.type || '',
        enabled: !!row.enabled,
        feed_authentication_status: !!row.feed_authentication_status,
        filter_search: row.filter_search || '',
        source_filters: Array.isArray(row.source_filters) ? row.source_filters : [],
        indicator_count: row.indicator_count || 0,
        entries: Array.isArray(row.entries) ? row.entries : []
      }))
      const blob = new Blob([JSON.stringify(payload.length === 1 ? payload[0] : payload, null, 2)], { type: 'application/json' })
      this._triggerDownload(blob, `${this.selectedName || 'output'}.json`)
    },
    async exportExcel() {
      const allRows = []
      for (const row of this.rows) {
        const entries = Array.isArray(row.entries) ? row.entries : []
        if (entries.length === 0) {
          allRows.push({ output_name: row.name || '', source_name: Array.isArray(row.source_name) ? row.source_name.join(', ') : (row.source_name || ''), type: row.type || '', value: '' })
        } else {
          entries.forEach(entry => {
            allRows.push({ output_name: row.name || '', source_name: Array.isArray(row.source_name) ? row.source_name.join(', ') : (row.source_name || ''), type: row.type || '', value: entry })
          })
        }
      }
      const workbook = new ExcelJS.Workbook()
      const worksheet = workbook.addWorksheet('Indicators')
      worksheet.columns = [
        { header: 'Output Name', key: 'output_name', width: 32 },
        { header: 'Source Name', key: 'source_name', width: 32 },
        { header: 'Type', key: 'type', width: 18 },
        { header: 'Value', key: 'value', width: 48 }
      ]
      worksheet.addRows(allRows)

      const buffer = await workbook.xlsx.writeBuffer()
      const blob = new Blob(
        [buffer],
        {
          type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        }
      )
      this._triggerDownload(blob, `${this.selectedName || 'output'}.xlsx`)
    },
    _triggerDownload(blob, filename) {
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      a.click()
      URL.revokeObjectURL(url)
    },
    formatJsonOutput(row) {
      const payload = {
        name: row.name || '',
        source_name: row.source_name || [],
        type: row.type || '',
        enabled: !!row.enabled,
        feed_authentication_status: !!row.feed_authentication_status,
        filter_search: row.filter_search || '',
        source_filters: Array.isArray(row.source_filters) ? row.source_filters : [],
        indicator_count: row.indicator_count || 0,
        entries: Array.isArray(row.entries) ? row.entries : []
      }
      return JSON.stringify(payload, null, 2)
    },
    async fetchOutputsEdl() {
      this.loading = true
      this.error = ''
      if (!this.selectedName) {
        this.rows = []
        this.loading = false
        return
      }
      try {
        const res = await apiFetch(`/api/outputs/edl?name=${encodeURIComponent(this.selectedName)}`)
        const data = await res.json()

        if (!res.ok) {
          this.error = data.message || 'Failed to fetch outputs EDL'
          this.rows = []
          return
        }

        this.rows = Array.isArray(data.outputs_edl) ? data.outputs_edl : []
      } catch (e) {
        this.error = 'Network error while fetching output details'
        this.rows = []
      } finally {
        this.loading = false
      }
    }
  }
}
</script>

<style scoped>
.edl-page-view {
  width: 100%;
}

.edl-html {
  background: #fff;
  border: 1px solid #e9ecef;
  border-radius: 6px;
  padding: 0.75rem;
  max-height: 420px;
  overflow: auto;
  font-family: monospace;
  font-size: 0.85rem;
  line-height: 1.4;
}

.json-view {
  background: #0f172a;
  color: #e2e8f0;
  border: 1px solid #1e293b;
  border-radius: 6px;
  padding: 0.75rem;
  max-height: 420px;
  overflow: auto;
  font-family: monospace;
  font-size: 0.85rem;
  line-height: 1.4;
  white-space: pre-wrap;
}
</style>
