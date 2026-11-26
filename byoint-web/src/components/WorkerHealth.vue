<template>
  <div class="worker-health-container">
    <div class="header-row">
      <div>
        <h1>Worker Health</h1>
        <p class="subtitle">Queue and worker telemetry for datapull execution</p>
      </div>
      <button class="refresh-btn" :disabled="loading" @click="fetchHealth">
        {{ loading ? 'Refreshing...' : 'Refresh Now' }}
      </button>
    </div>

    <div class="summary-grid" v-if="health">
      <div class="metric-card">
        <div class="metric-label">Queue Available</div>
        <div class="metric-value" :class="health.queue_available ? 'ok' : 'bad'">
          {{ health.queue_available ? 'Yes' : 'No' }}
        </div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Queue Depth</div>
        <div class="metric-value">{{ safeNumber(health.queue_depth) }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Active Workers</div>
        <div class="metric-value">{{ safeNumber(health.worker_count_active) }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Total Workers</div>
        <div class="metric-value">{{ safeNumber(health.worker_count_total) }}</div>
      </div>
    </div>

    <div class="queue-meta" v-if="health">
      <div><strong>Queue Key:</strong> {{ health.queue_key || 'N/A' }}</div>
      <div><strong>Worker Mode Enabled (API container):</strong> {{ health.worker_enabled ? 'true' : 'false' }}</div>
      <div><strong>Worker Thread Running (API container):</strong> {{ health.worker_running ? 'true' : 'false' }}</div>
      <div><strong>Last Updated:</strong> {{ formatDate(lastUpdated) }}</div>
    </div>

    <div class="workers-card" v-if="workers.length">
      <h2>Workers</h2>
      <div class="table-wrap">
        <table class="workers-table">
          <thead>
            <tr>
              <th>Worker ID</th>
              <th>State</th>
              <th>Heartbeat Age (s)</th>
              <th>Processed</th>
              <th>Success</th>
              <th>Errors</th>
              <th>Last Source</th>
              <th>Last Status</th>
              <th>Last Error</th>
              <th>Last Duration (ms)</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="worker in workers" :key="worker.worker_id">
              <td>{{ worker.worker_id }}</td>
              <td>
                <span class="state-badge" :class="worker.is_stale ? 'stale' : 'running'">
                  {{ worker.is_stale ? 'stale' : worker.state || 'running' }}
                </span>
              </td>
              <td>{{ safeNumber(worker.heartbeat_age_seconds) }}</td>
              <td>{{ safeNumber(worker.processed_count) }}</td>
              <td>{{ safeNumber(worker.success_count) }}</td>
              <td>{{ safeNumber(worker.error_count) }}</td>
              <td>{{ worker.last_source_name || '-' }}</td>
              <td>{{ worker.last_status || '-' }}</td>
              <td class="error-col">{{ worker.last_error || '-' }}</td>
              <td>{{ safeNumber(worker.last_duration_ms) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div v-else-if="health" class="empty-state">No worker metrics found yet.</div>
    <div v-if="error" class="error-banner">{{ error }}</div>
  </div>
</template>

<script>
import { fetchDatapullQueueStatus } from '@/api'

export default {
  name: 'WorkerHealth',
  data() {
    return {
      health: null,
      workers: [],
      loading: false,
      error: null,
      intervalHandle: null,
      lastUpdated: null
    }
  },
  methods: {
    async fetchHealth() {
      try {
        this.loading = true
        this.error = null
        const data = await fetchDatapullQueueStatus()
        this.health = data
        this.workers = Array.isArray(data.workers) ? data.workers : []
        this.lastUpdated = new Date().toISOString()
      } catch (err) {
        this.error = err.message || 'Failed to load worker health.'
      } finally {
        this.loading = false
      }
    },
    safeNumber(value) {
      if (value === null || value === undefined || Number.isNaN(Number(value))) {
        return '-'
      }
      return Number(value)
    },
    formatDate(isoString) {
      if (!isoString) {
        return 'N/A'
      }
      return new Date(isoString).toLocaleString()
    }
  },
  mounted() {
    this.fetchHealth()
    this.intervalHandle = setInterval(() => this.fetchHealth(), 15000)
  },
  beforeUnmount() {
    if (this.intervalHandle) {
      clearInterval(this.intervalHandle)
      this.intervalHandle = null
    }
  }
}
</script>

<style scoped>
.worker-health-container {
  padding: 2rem;
  min-height: 100vh;
  background: linear-gradient(160deg, #f2f6ff 0%, #eaf5f0 100%);
}

.header-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 1rem;
  margin-bottom: 1rem;
}

h1 {
  margin: 0;
  color: #153b53;
}

.subtitle {
  margin: 0.35rem 0 0;
  color: #4f6f81;
}

.refresh-btn {
  border: 0;
  border-radius: 10px;
  padding: 0.6rem 1rem;
  background: #106c64;
  color: #fff;
  font-weight: 600;
  cursor: pointer;
}

.refresh-btn:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(140px, 1fr));
  gap: 1rem;
  margin-bottom: 1rem;
}

.metric-card {
  background: #fff;
  border-radius: 12px;
  padding: 1rem;
  box-shadow: 0 8px 20px rgba(21, 59, 83, 0.08);
}

.metric-label {
  font-size: 0.82rem;
  color: #6b8291;
  margin-bottom: 0.4rem;
}

.metric-value {
  font-size: 1.4rem;
  font-weight: 700;
  color: #1f2f3d;
}

.metric-value.ok {
  color: #107d45;
}

.metric-value.bad {
  color: #ad2f2f;
}

.queue-meta {
  background: #fff;
  border-radius: 12px;
  padding: 1rem;
  margin-bottom: 1rem;
  box-shadow: 0 8px 20px rgba(21, 59, 83, 0.08);
  display: grid;
  grid-template-columns: repeat(2, minmax(250px, 1fr));
  gap: 0.5rem 1rem;
}

.workers-card {
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 8px 20px rgba(21, 59, 83, 0.08);
  padding: 1rem;
}

.workers-card h2 {
  margin: 0 0 0.8rem;
  color: #153b53;
}

.table-wrap {
  overflow-x: auto;
}

.workers-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.9rem;
}

.workers-table th,
.workers-table td {
  border-bottom: 1px solid #e6edf2;
  text-align: left;
  padding: 0.65rem 0.5rem;
  vertical-align: top;
}

.workers-table th {
  background: #f2f7fb;
  color: #355062;
}

.state-badge {
  border-radius: 999px;
  padding: 0.15rem 0.6rem;
  font-size: 0.75rem;
  font-weight: 700;
  display: inline-block;
}

.state-badge.running {
  background: #def8e8;
  color: #0f7a3d;
}

.state-badge.stale {
  background: #ffe3cf;
  color: #a55b1d;
}

.error-col {
  max-width: 220px;
  white-space: pre-wrap;
  word-break: break-word;
  color: #8b3030;
}

.empty-state {
  padding: 1rem;
  background: #fff;
  border-radius: 12px;
  color: #547083;
}

.error-banner {
  margin-top: 1rem;
  background: #ffe4e4;
  color: #8b3030;
  border: 1px solid #f2b5b5;
  padding: 0.8rem 1rem;
  border-radius: 10px;
}

@media (max-width: 1024px) {
  .summary-grid {
    grid-template-columns: repeat(2, minmax(140px, 1fr));
  }

  .queue-meta {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .worker-health-container {
    padding: 1rem;
  }

  .header-row {
    flex-direction: column;
    align-items: stretch;
  }

  .summary-grid {
    grid-template-columns: 1fr;
  }
}
</style>
