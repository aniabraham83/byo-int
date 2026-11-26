<template>
  <div class="dashboard-shell">
    <section class="hero-panel mb-4">
      <div>
        <h1 class="hero-title mb-1">Summary</h1>
        <p class="hero-subtitle mb-0">Operational snapshot from live data.</p>
      </div>
      <div class="process-flow" aria-label="Process flow: Data Sources, Enrich, Outputs">
        <div class="flow-step flow-sources">Data Sources</div>
        <span class="flow-arrow">→</span>
        <div class="flow-step flow-enrich">Enrich</div>
        <span class="flow-arrow">→</span>
        <div class="flow-step flow-outputs">Outputs</div>
      </div>
      <div class="hero-actions">
        <button class="btn btn-outline-light" @click="showAbout = true" title="What is BYO-INT?">
          ℹ️ About
        </button>
        <button class="btn btn-dark" @click="loadDashboard" :disabled="loading">
          <span v-if="loading" class="spinner-border spinner-border-sm me-2"></span>
          Refresh
        </button>
      </div>
    </section>

    <!-- About BYO-INT Modal -->
    <div v-if="showAbout" class="about-overlay" @click.self="showAbout = false">
      <div class="about-modal" role="dialog" aria-modal="true" aria-labelledby="about-title">
        <div class="about-header">
          <div>
            <h4 id="about-title" class="mb-0">BYO-INT</h4>
            <small class="about-tagline">Your intel, your way</small>
          </div>
          <button type="button" class="about-close" @click="showAbout = false" aria-label="Close">×</button>
        </div>
        <div class="about-body">
          <p class="mb-3">
            BYO-INT is an extensible platform for those who want to manage their own intel and integrations.
            Its primary functional components are:
          </p>
          <div class="about-component flow-sources">
            <h6 class="mb-1">1. Datapull <span class="about-role">Collection</span></h6>
            <p class="mb-0">
              Fetches indicator data from different sources. Examples of indicators are IPv4 addresses, hostnames and domains.
              Sources can be static or dynamic: <strong>static</strong> is used for adding entries manually or for one-time
              updates from a static source; <strong>dynamic</strong> is used when the source is external or changes over time,
              and can be configured to run on a schedule.
            </p>
          </div>
          <div class="about-component flow-enrich">
            <h6 class="mb-1">2. Data Enrichment <span class="about-role">Context</span></h6>
            <p class="mb-0">
              Enriches the data extracted from different sources, and the enrichment can be used as a filter by other components.
              This is where the platform is tailored to your local context and environment: every environment is different,
              so enrichment is driven by local context rather than something native.
            </p>
          </div>
          <div class="about-component flow-outputs">
            <h6 class="mb-1">3. Data Output <span class="about-role">Consumption</span></h6>
            <p class="mb-0">
              Generates output that can be consumed by external integrations and sources, such as an EDL (external dynamic list),
              JSON (API style), MCP, or a generic CSV/text export.
            </p>
          </div>
        </div>
        <div class="about-footer">
          <button type="button" class="btn btn-dark" @click="showAbout = false">Close</button>
        </div>
      </div>
    </div>

    <div v-if="error" class="alert alert-danger">{{ error }}</div>

    <section class="row g-3 mb-4">
      <div class="col-md-4">
        <article class="kpi-card kpi-ink">
          <div class="kpi-label">Datapull Workflows</div>
          <div class="kpi-value">{{ formatNumber(metrics.workflowCount) }}</div>
        </article>
      </div>
      <div class="col-md-4">
        <article class="kpi-card kpi-amber">
          <div class="kpi-label">Total Indicators</div>
          <div class="kpi-value">{{ formatNumber(metrics.totalIndicators) }}</div>
        </article>
      </div>
      <div class="col-md-4">
        <article class="kpi-card kpi-cyan">
          <div class="kpi-label">Outputs</div>
          <div class="kpi-value">{{ formatNumber(metrics.outputsCount) }}</div>
        </article>
      </div>
    </section>

    <section class="panel-card mb-4">
      <div class="panel-header" :class="{ collapsed: flowCollapsed }">
        <h5 class="panel-title mb-0">Data Flow</h5>
        <button
          type="button"
          class="btn btn-sm btn-outline-secondary"
          :aria-expanded="!flowCollapsed"
          @click="flowCollapsed = !flowCollapsed"
        >
          {{ flowCollapsed ? '▸ Expand' : '▾ Collapse' }}
        </button>
      </div>
      <DataFlowDiagram
        v-show="!flowCollapsed"
        :datapulls="flow.datapulls"
        :enrichments="flow.enrichments"
        :outputs="flow.outputs"
      />
    </section>

    <section class="row g-3">
      <div class="col-lg-6">
        <article class="panel-card h-100">
          <h5 class="panel-title">Indicators by Type</h5>
          <div class="chart-wrap">
            <canvas ref="typesChart"></canvas>
          </div>
        </article>
      </div>
      <div class="col-lg-6">
        <article class="panel-card h-100">
          <h5 class="panel-title">Type Breakdown</h5>
          <div v-if="!metrics.indicatorCountsByType.length" class="text-muted">No indicator data available.</div>
          <div v-else class="table-responsive">
            <table class="table table-sm align-middle mb-0">
              <thead>
                <tr>
                  <th>Type</th>
                  <th class="text-end">Count</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in metrics.indicatorCountsByType" :key="row.type">
                  <td>{{ row.type }}</td>
                  <td class="text-end fw-semibold">{{ formatNumber(row.count) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </article>
      </div>
    </section>
  </div>
</template>

<script>
import Chart from 'chart.js/auto'
import { fetchDashboardMetrics, fetchDashboardFlow } from '@/api'
import DataFlowDiagram from '@/components/DataFlowDiagram.vue'

export default {
  name: 'HomePage',
  components: { DataFlowDiagram },
  data() {
    return {
      loading: false,
      error: '',
      showAbout: false,
      flowCollapsed: true,
      flow: {
        datapulls: [],
        enrichments: [],
        outputs: []
      },
      metrics: {
        workflowCount: 0,
        totalIndicators: 0,
        outputsCount: 0,
        indicatorCountsByType: []
      },
      typesChart: null
    }
  },
  async mounted() {
    await this.loadDashboard()
  },
  beforeUnmount() {
    if (this.typesChart) {
      this.typesChart.destroy()
      this.typesChart = null
    }
  },
  methods: {
    formatNumber(value) {
      const n = Number(value || 0)
      return n.toLocaleString()
    },
    async loadDashboard() {
      this.loading = true
      this.error = ''
      try {
        const [data, flow] = await Promise.all([fetchDashboardMetrics(), fetchDashboardFlow()])
        this.flow.datapulls = Array.isArray(flow.datapulls) ? flow.datapulls : []
        this.flow.enrichments = Array.isArray(flow.enrichments) ? flow.enrichments : []
        this.flow.outputs = Array.isArray(flow.outputs) ? flow.outputs : []

        this.metrics.workflowCount = Number(data.workflow_count || 0)
        this.metrics.outputsCount = Number(data.outputs_count || 0)
        this.metrics.totalIndicators = Number(data.total_indicators || 0)
        this.metrics.indicatorCountsByType = Array.isArray(data.indicator_counts_by_type)
          ? data.indicator_counts_by_type.map(row => ({
              type: String(row.type || 'unknown'),
              count: Number(row.count || 0)
            }))
          : []

        this.renderTypesChart()
      } catch (e) {
        this.error = e.message || 'Failed to load summary metrics.'
      } finally {
        this.loading = false
      }
    },
    renderTypesChart() {
      if (!this.$refs.typesChart) return

      if (this.typesChart) {
        this.typesChart.destroy()
        this.typesChart = null
      }

      const labels = this.metrics.indicatorCountsByType.map(i => i.type)
      const values = this.metrics.indicatorCountsByType.map(i => i.count)

      this.typesChart = new Chart(this.$refs.typesChart, {
        type: 'doughnut',
        data: {
          labels,
          datasets: [{
            data: values,
            backgroundColor: [
              '#14213d',
              '#fca311',
              '#2a9d8f',
              '#e76f51',
              '#264653',
              '#8ecae6',
              '#ffb703',
              '#90be6d'
            ],
            borderColor: '#fff',
            borderWidth: 2
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: {
              position: 'bottom',
              labels: { padding: 15 }
            }
          }
        }
      })
    }
  }
}
</script>

<style scoped>
.dashboard-shell {
  padding: 1.5rem;
  background:
    radial-gradient(circle at 10% 10%, rgba(252, 163, 17, 0.12), transparent 35%),
    radial-gradient(circle at 90% 20%, rgba(42, 157, 143, 0.12), transparent 35%),
    #f7f8fa;
  min-height: 100vh;
}

.hero-panel {
  background: #14213d;
  color: #ffffff;
  border-radius: 14px;
  padding: 1.25rem 1.5rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.hero-title {
  font-weight: 700;
  font-size: 1.9rem;
}

.hero-subtitle {
  opacity: 0.84;
}

.process-flow {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  flex-wrap: wrap;
}

.flow-step {
  padding: 0.5rem 0.9rem;
  border-radius: 10px;
  font-size: 0.9rem;
  font-weight: 600;
  color: #14213d;
  white-space: nowrap;
}

.flow-sources {
  background: #ebf0f9;
}

.flow-enrich {
  background: #ffe8bf;
}

.flow-outputs {
  background: #c8f5ed;
}

.hero-actions {
  display: flex;
  gap: 0.5rem;
  flex-shrink: 0;
}

.about-overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1050;
  padding: 1rem;
}

.about-modal {
  background: #ffffff;
  border-radius: 14px;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.25);
  max-width: 680px;
  width: 100%;
  max-height: 90vh;
  overflow-y: auto;
}

.about-header {
  background: #14213d;
  color: #ffffff;
  padding: 1.1rem 1.5rem;
  border-radius: 14px 14px 0 0;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.about-tagline {
  opacity: 0.8;
  font-style: italic;
}

.about-close {
  background: none;
  border: none;
  color: #ffffff;
  font-size: 1.8rem;
  line-height: 1;
  cursor: pointer;
}

.about-body {
  padding: 1.25rem 1.5rem;
  color: #1f2937;
}

.about-component {
  border-radius: 10px;
  padding: 0.85rem 1rem;
  margin-bottom: 0.75rem;
}

.about-role {
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #475569;
  margin-left: 0.35rem;
}

.about-footer {
  padding: 0.9rem 1.5rem;
  border-top: 1px solid #e5e7eb;
  display: flex;
  justify-content: flex-end;
}

.flow-arrow {
  font-size: 1.2rem;
  opacity: 0.7;
}

.kpi-card {
  border-radius: 14px;
  padding: 1rem 1.1rem;
  color: #111;
  min-height: 116px;
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.06);
}

.kpi-label {
  font-size: 0.88rem;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  opacity: 0.8;
}

.kpi-value {
  margin-top: 0.55rem;
  font-size: 2rem;
  font-weight: 700;
}

.kpi-ink {
  background: linear-gradient(135deg, #ffffff 0%, #ebf0f9 100%);
}

.kpi-amber {
  background: linear-gradient(135deg, #fff7e8 0%, #ffe8bf 100%);
}

.kpi-cyan {
  background: linear-gradient(135deg, #e9fbf8 0%, #c8f5ed 100%);
}

.panel-card {
  background: #ffffff;
  border-radius: 14px;
  padding: 1rem 1.1rem;
  border: 1px solid #e7e9ee;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 0.9rem;
}

.panel-header.collapsed {
  margin-bottom: 0;
}

.panel-title {
  font-size: 1rem;
  font-weight: 700;
  margin-bottom: 0.9rem;
  color: #14213d;
}

.chart-wrap {
  position: relative;
  min-height: 300px;
}

@media (max-width: 768px) {
  .dashboard-shell {
    padding: 1rem;
  }

  .hero-panel {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>