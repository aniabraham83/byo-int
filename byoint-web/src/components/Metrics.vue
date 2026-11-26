<template>
  <div class="metrics-container">
    <h1>Datapull Metrics & Observability</h1>
    
    <!-- Header with refresh and time range controls -->
    <div class="metrics-header">
      <div class="time-range-selector">
        <label>Time Range:</label>
        <select v-model="timeRangeMinutes" @change="loadMetrics">
          <option value="60">Last 1 hour</option>
          <option value="360">Last 6 hours</option>
          <option value="1440">Last 24 hours</option>
          <option value="10080">Last 7 days</option>
          <option value="43200">Last 30 days</option>
        </select>
      </div>
      <button @click="loadMetrics" class="refresh-btn">
        🔄 Refresh Metrics
      </button>
    </div>

    <!-- Loading state -->
    <div v-if="loading" class="loading">⏳ Loading metrics...</div>

    <!-- Error state -->
    <div v-if="error" class="error-message">
      ⚠️ {{ error }}
    </div>

    <!-- Metrics Summary Cards -->
    <div v-if="!loading && metrics" class="metrics-summary">
      <div class="metric-card success">
        <div class="metric-label">Completion Rate</div>
        <div class="metric-value">{{ metrics.completion_rate_pct }}%</div>
        <div class="metric-detail">{{ metrics.total_jobs }} total jobs</div>
      </div>

      <div class="metric-card info">
        <div class="metric-label">Avg Latency</div>
        <div class="metric-value">{{ metrics.avg_latency_ms }}ms</div>
        <div class="metric-detail">{{ metrics.latency_count }} measured</div>
      </div>

      <div class="metric-card warning">
        <div class="metric-label">P95 Latency</div>
        <div class="metric-value">{{ metrics.p95_latency_ms }}ms</div>
        <div class="metric-detail">95th percentile</div>
      </div>

      <div class="metric-card warning">
        <div class="metric-label">Dead Letter Rate</div>
        <div class="metric-value">{{ metrics.dead_letter_rate_pct }}%</div>
        <div class="metric-detail">{{ metrics.dead_letter_count }} dead letters</div>
      </div>
    </div>

    <!-- Status breakdown -->
    <div v-if="!loading && metrics && metrics.status_breakdown" class="breakdown-section">
      <h2>Job Status Breakdown</h2>
      <div class="breakdown-cards">
        <div
          v-for="(count, status) in metrics.status_breakdown"
          :key="status"
          class="breakdown-card"
          :class="statusClass(status)"
        >
          <div class="status-label">{{ formatStatusLabel(status) }}</div>
          <div class="status-value">{{ count }}</div>
          <div class="status-pct">{{ ((count / metrics.total_jobs) * 100).toFixed(1) }}%</div>
        </div>
      </div>
    </div>

    <!-- Error breakdown -->
    <div v-if="!loading && metrics && metrics.error_breakdown && Object.keys(metrics.error_breakdown).length > 0" class="error-section">
      <h2>Error Type Breakdown (Top 5)</h2>
      <div class="error-list">
        <div v-for="(count, errorType) in metrics.error_breakdown" :key="errorType" class="error-item">
          <span class="error-type">{{ errorType }}</span>
          <span class="error-count">{{ count }} occurrences</span>
          <div class="error-bar" :style="{ width: ((count / Math.max(...Object.values(metrics.error_breakdown))) * 100) + '%' }"></div>
        </div>
      </div>
    </div>

    <!-- Per-source metrics table -->
    <div class="sources-section">
      <h2>Metrics by Source</h2>
      <div class="source-filters">
        <input
          v-model="sourceFilter"
          type="text"
          placeholder="Filter sources..."
          class="source-filter-input"
        />
      </div>
      <div v-if="sourceMetricsLoading" class="loading">⏳ Loading source metrics...</div>
      <div v-else-if="sourceMetricsLoading === false && filteredSourceMetrics.length === 0" class="no-data">
        No source metrics found for time range.
      </div>
      <table v-else class="metrics-table">
        <thead>
          <tr>
            <th>Source Name</th>
            <th>Total Jobs</th>
            <th>Completion %</th>
            <th>Avg Latency (ms)</th>
            <th>Max Latency (ms)</th>
            <th>Errors</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="metric in filteredSourceMetrics" :key="metric.source_name">
            <td class="source-name">{{ metric.source_name }}</td>
            <td class="metric-value">{{ metric.total_jobs }}</td>
            <td :class="completionRateClass(metric.completion_rate_pct)">
              {{ metric.completion_rate_pct }}%
            </td>
            <td>{{ metric.avg_latency_ms }}ms</td>
            <td>{{ metric.max_latency_ms }}ms</td>
            <td :class="{ 'has-errors': metric.error_count > 0 }">
              {{ metric.error_count }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script>
import { fetchDatapullMetrics, fetchDatapullMetricsBySource } from '../api'

export default {
  name: 'DatapullMetrics',
  data() {
    return {
      metrics: null,
      sourceMetrics: [],
      sourceFilter: '',
      loading: true,
      sourceMetricsLoading: false,
      timeRangeMinutes: '1440',
      error: null,
      refreshIntervalId: null,
    }
  },
  computed: {
    filteredSourceMetrics() {
      if (!this.sourceFilter) return this.sourceMetrics
      const filter = this.sourceFilter.toLowerCase()
      return this.sourceMetrics.filter(m =>
        m.source_name.toLowerCase().includes(filter)
      )
    },
  },
  mounted() {
    this.loadMetrics()
    // Auto-refresh every 30 seconds
    this.refreshIntervalId = setInterval(this.loadMetrics, 30000)
  },
  beforeUnmount() {
    if (this.refreshIntervalId) {
      clearInterval(this.refreshIntervalId)
    }
  },
  methods: {
    async loadMetrics() {
      try {
        this.loading = true
        this.error = null
        
        // Load aggregate metrics
        const metricsData = await fetchDatapullMetrics({
          time_range_minutes: this.timeRangeMinutes,
        })
        this.metrics = metricsData?.metrics
        
        // Load per-source metrics
        this.sourceMetricsLoading = true
        const sourceData = await fetchDatapullMetricsBySource({
          time_range_minutes: this.timeRangeMinutes,
          limit: 100,
        })
        this.sourceMetrics = sourceData?.metrics_by_source || []
      } catch (err) {
        this.error = `Failed to load metrics: ${err.message}`
        console.error('Metrics error:', err)
      } finally {
        this.loading = false
        this.sourceMetricsLoading = false
      }
    },
    statusClass(status) {
      const status_lower = String(status || '').toLowerCase()
      if (status_lower.includes('completed') || status_lower.includes('success')) {
        return 'status-success'
      }
      if (status_lower.includes('failed') || status_lower.includes('error')) {
        return 'status-error'
      }
      if (status_lower.includes('dead')) {
        return 'status-dead'
      }
      return 'status-neutral'
    },
    formatStatusLabel(status) {
      return status
        .replace(/_/g, ' ')
        .split(' ')
        .map(word => word.charAt(0).toUpperCase() + word.slice(1))
        .join(' ')
    },
    completionRateClass(rate) {
      if (rate >= 95) return 'completion-excellent'
      if (rate >= 80) return 'completion-good'
      if (rate >= 50) return 'completion-warning'
      return 'completion-poor'
    },
  },
}
</script>

<style scoped>
.metrics-container {
  padding: 20px;
  background: #f9fafb;
  min-height: 100vh;
}

h1 {
  color: #1f2937;
  margin-bottom: 20px;
  font-size: 28px;
}

h2 {
  color: #374151;
  font-size: 18px;
  margin: 20px 0 15px 0;
  border-bottom: 2px solid #e5e7eb;
  padding-bottom: 10px;
}

.metrics-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  gap: 15px;
}

.time-range-selector {
  display: flex;
  align-items: center;
  gap: 10px;
}

.time-range-selector label {
  font-weight: 600;
  color: #4b5563;
}

.time-range-selector select {
  padding: 8px 12px;
  border: 1px solid #d1d5db;
  border-radius: 4px;
  font-size: 14px;
  cursor: pointer;
  background-color: white;
}

.refresh-btn {
  padding: 10px 20px;
  background: #3b82f6;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-weight: 600;
  transition: background 0.3s;
}

.refresh-btn:hover {
  background: #2563eb;
}

.loading {
  padding: 20px;
  text-align: center;
  color: #6b7280;
  font-size: 16px;
}

.error-message {
  padding: 15px;
  background: #fee;
  border: 1px solid #fcc;
  border-radius: 4px;
  color: #991b1b;
  margin-bottom: 15px;
}

.metrics-summary {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 15px;
  margin-bottom: 30px;
}

.metric-card {
  padding: 20px;
  border-radius: 6px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
  color: white;
}

.metric-card.success {
  background: linear-gradient(135deg, #10b981 0%, #059669 100%);
}

.metric-card.warning {
  background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);
}

.metric-card.info {
  background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%);
}

.metric-card.danger {
  background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%);
}

.metric-label {
  font-size: 12px;
  font-weight: 600;
  opacity: 0.9;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.metric-value {
  font-size: 32px;
  font-weight: 700;
  margin: 10px 0;
}

.metric-detail {
  font-size: 12px;
  opacity: 0.85;
}

.breakdown-section {
  background: white;
  padding: 20px;
  border-radius: 6px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
  margin-bottom: 20px;
}

.breakdown-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 12px;
}

.breakdown-card {
  padding: 15px;
  border-radius: 4px;
  text-align: center;
  border: 1px solid #e5e7eb;
}

.breakdown-card.status-success {
  background: #ecfdf5;
  border-color: #a7f3d0;
}

.breakdown-card.status-error {
  background: #fef2f2;
  border-color: #fecaca;
}

.breakdown-card.status-dead {
  background: #f3f4f6;
  border-color: #d1d5db;
}

.breakdown-card.status-neutral {
  background: #f9fafb;
  border-color: #e5e7eb;
}

.status-label {
  font-size: 12px;
  color: #6b7280;
  font-weight: 600;
  text-transform: uppercase;
}

.status-value {
  font-size: 24px;
  font-weight: 700;
  color: #1f2937;
  margin: 8px 0;
}

.status-pct {
  font-size: 12px;
  color: #9ca3af;
}

.error-section {
  background: white;
  padding: 20px;
  border-radius: 6px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
  margin-bottom: 20px;
}

.error-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.error-item {
  display: flex;
  align-items: center;
  gap: 10px;
}

.error-type {
  min-width: 150px;
  font-weight: 600;
  color: #1f2937;
  font-family: monospace;
}

.error-count {
  min-width: 80px;
  text-align: right;
  color: #6b7280;
}

.error-bar {
  flex: 1;
  height: 6px;
  background: linear-gradient(90deg, #ef4444, #f97316);
  border-radius: 3px;
}

.sources-section {
  background: white;
  padding: 20px;
  border-radius: 6px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}

.source-filters {
  margin-bottom: 15px;
}

.source-filter-input {
  width: 100%;
  max-width: 400px;
  padding: 8px 12px;
  border: 1px solid #d1d5db;
  border-radius: 4px;
  font-size: 14px;
}

.no-data {
  padding: 20px;
  text-align: center;
  color: #9ca3af;
  font-style: italic;
}

.metrics-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
}

.metrics-table thead {
  background: #f3f4f6;
}

.metrics-table th {
  padding: 12px;
  text-align: left;
  font-weight: 600;
  color: #374151;
  border-bottom: 2px solid #e5e7eb;
}

.metrics-table td {
  padding: 12px;
  border-bottom: 1px solid #f3f4f6;
}

.metrics-table tbody tr:hover {
  background: #f9fafb;
}

.source-name {
  font-weight: 600;
  color: #1f2937;
}

.completion-excellent {
  color: #10b981;
  font-weight: 600;
}

.completion-good {
  color: #3b82f6;
  font-weight: 600;
}

.completion-warning {
  color: #f59e0b;
  font-weight: 600;
}

.completion-poor {
  color: #ef4444;
  font-weight: 600;
}

.has-errors {
  color: #ef4444;
  font-weight: 600;
}

@media (max-width: 768px) {
  .metrics-header {
    flex-direction: column;
    align-items: flex-start;
  }

  .metrics-summary {
    grid-template-columns: 1fr 1fr;
  }

  .breakdown-cards {
    grid-template-columns: repeat(2, 1fr);
  }

  .metrics-table {
    font-size: 12px;
  }

  .metrics-table th,
  .metrics-table td {
    padding: 8px;
  }
}
</style>
