<template>
  <div class="jobs-page">
    <div class="jobs-header">
      <div>
        <h1>Datapull Jobs</h1>
        <p class="subtitle">Envelope-level execution tracking, retry scheduling, and dead-letter operations</p>
      </div>
      <button class="refresh-btn" :disabled="loading" @click="loadActiveTab">
        {{ loading ? 'Refreshing...' : 'Refresh' }}
      </button>
    </div>

    <div class="tabs">
      <button :class="['tab-btn', activeTab === 'jobs' ? 'active' : '']" @click="switchTab('jobs')">Jobs</button>
      <button :class="['tab-btn', activeTab === 'dead' ? 'active' : '']" @click="switchTab('dead')">Dead Letter</button>
    </div>

    <div class="filters" v-if="activeTab === 'jobs'">
      <label>
        Status
        <select v-model="filters.status" @change="loadJobs">
          <option value="">All</option>
          <option value="queued">Queued</option>
          <option value="running">Running</option>
          <option value="completed">Completed</option>
          <option value="failed">Failed</option>
          <option value="dead_lettered">Dead Lettered</option>
        </select>
      </label>

      <label>
        Source Name
        <input v-model.trim="filters.sourceName" type="text" placeholder="ex: emergingthreats_badips" @keyup.enter="loadJobs" />
      </label>

      <label>
        Limit
        <select v-model.number="filters.limit" @change="loadActiveTab">
          <option :value="50">50</option>
          <option :value="100">100</option>
          <option :value="200">200</option>
          <option :value="500">500</option>
        </select>
      </label>

      <button class="apply-btn" :disabled="loading" @click="loadJobs">Apply</button>
    </div>

    <div class="table-card" v-if="activeTab === 'jobs' && jobs.length">
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Job ID</th>
              <th>Source</th>
              <th>Status</th>
              <th>Attempts</th>
              <th>Next Retry</th>
              <th>Created</th>
              <th>Last Attempt</th>
              <th>Error</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="job in jobs" :key="job.job_id || job._id">
              <td class="job-id">{{ job.job_id || '-' }}</td>
              <td>{{ job.source_name || '-' }}</td>
              <td>
                <span class="status-pill" :class="statusClass(job.status)">{{ job.status || '-' }}</span>
              </td>
              <td>{{ safeNum(job.attempt_count) }} / {{ safeNum(job.max_attempts) }}</td>
              <td>{{ formatDate(job.next_retry_at) }}</td>
              <td>{{ formatDate(job.created_at || job._created_timestamp) }}</td>
              <td>{{ formatDate(job.last_attempted_at) }}</td>
              <td class="error-col">{{ job.error || '-' }}</td>
              <td>
                <button class="table-action" @click="openJobDetails(job)">Details</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="table-card" v-if="activeTab === 'dead' && deadLetters.length">
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Job ID</th>
              <th>Source</th>
              <th>Reason</th>
              <th>Dead Lettered At</th>
              <th>Attempts</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="job in deadLetters" :key="job.job_id || job._id">
              <td class="job-id">{{ job.job_id || '-' }}</td>
              <td>{{ job.source_name || '-' }}</td>
              <td class="error-col">{{ job.dead_letter_reason || job.error || '-' }}</td>
              <td>{{ formatDate(job.dead_lettered_at) }}</td>
              <td>{{ safeNum(job.attempt_count) }} / {{ safeNum(job.max_attempts) }}</td>
              <td class="action-row">
                <button class="table-action" @click="openJobDetails(job)">Details</button>
                <button class="table-action table-action-primary" :disabled="requeueJobId === job.job_id" @click="requeueDead(job)">
                  {{ requeueJobId === job.job_id ? 'Requeueing...' : 'Requeue' }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div v-if="!loading && ((activeTab === 'jobs' && !jobs.length) || (activeTab === 'dead' && !deadLetters.length))" class="empty-state">
      {{ activeTab === 'dead' ? 'No dead-letter jobs found.' : 'No datapull jobs found for current filters.' }}
    </div>

    <div v-if="error" class="error-banner">{{ error }}</div>

    <div v-if="selectedJob" class="details-overlay" @click.self="closeJobDetails">
      <div class="details-panel">
        <div class="details-header">
          <h2>Job Details</h2>
          <button class="table-action" @click="closeJobDetails">Close</button>
        </div>
        <div class="detail-grid">
          <div><strong>Job ID:</strong> {{ selectedJob.job_id || '-' }}</div>
          <div><strong>Source:</strong> {{ selectedJob.source_name || '-' }}</div>
          <div><strong>Status:</strong> {{ selectedJob.status || '-' }}</div>
          <div><strong>Trigger:</strong> {{ selectedJob.trigger || '-' }}</div>
          <div><strong>Created:</strong> {{ formatDate(selectedJob.created_at || selectedJob._created_timestamp) }}</div>
          <div><strong>Completed:</strong> {{ formatDate(selectedJob.completed_at) }}</div>
          <div><strong>Next Retry:</strong> {{ formatDate(selectedJob.next_retry_at) }}</div>
          <div><strong>Error Type:</strong> {{ selectedJob.error_type || '-' }}</div>
        </div>

        <h3>Attempt Timeline</h3>
        <div v-if="attemptsTimeline.length" class="attempt-list">
          <div v-for="attempt in attemptsTimeline" :key="attempt.attempt_number + '-' + (attempt.started_at || attempt.completed_at || 'x')" class="attempt-item">
            <div><strong>#{{ attempt.attempt_number }}</strong> - {{ attempt.status || 'unknown' }}</div>
            <div>Started: {{ formatDate(attempt.started_at) }}</div>
            <div>Completed: {{ formatDate(attempt.completed_at) }}</div>
            <div v-if="attempt.error">Error: {{ attempt.error }}</div>
          </div>
        </div>
        <div v-else class="empty-state">No attempt records.</div>
      </div>
    </div>
  </div>
</template>

<script>
import { fetchDatapullJobs, fetchDeadLetterJobs, fetchDatapullJob, requeueDeadLetterJob } from '@/api'

export default {
  name: 'DatapullJobs',
  data() {
    return {
      jobs: [],
      deadLetters: [],
      loading: false,
      error: null,
      pollHandle: null,
      activeTab: 'jobs',
      selectedJob: null,
      requeueJobId: null,
      filters: {
        status: '',
        sourceName: '',
        limit: 100
      }
    }
  },
  computed: {
    attemptsTimeline() {
      if (!this.selectedJob) {
        return []
      }
      const attempts = []
      if (Array.isArray(this.selectedJob.attempt_history)) {
        attempts.push(...this.selectedJob.attempt_history)
      }
      if (Array.isArray(this.selectedJob.attempts)) {
        attempts.push(...this.selectedJob.attempts)
      }
      return attempts.sort((a, b) => Number(a.attempt_number || 0) - Number(b.attempt_number || 0))
    }
  },
  methods: {
    switchTab(tab) {
      this.activeTab = tab
      this.loadActiveTab()
    },
    async loadActiveTab() {
      if (this.activeTab === 'dead') {
        await this.loadDeadLetters()
        return
      }
      await this.loadJobs()
    },
    async loadJobs() {
      try {
        this.loading = true
        this.error = null
        this.jobs = await fetchDatapullJobs({
          status: this.filters.status,
          sourceName: this.filters.sourceName,
          limit: this.filters.limit
        })
      } catch (err) {
        this.error = err.message || 'Failed to load datapull jobs.'
      } finally {
        this.loading = false
      }
    },
    async loadDeadLetters() {
      try {
        this.loading = true
        this.error = null
        this.deadLetters = await fetchDeadLetterJobs(this.filters.limit)
      } catch (err) {
        this.error = err.message || 'Failed to load dead-letter jobs.'
      } finally {
        this.loading = false
      }
    },
    async openJobDetails(job) {
      const jobId = job && job.job_id ? String(job.job_id) : ''
      if (!jobId) {
        this.selectedJob = job
        return
      }

      try {
        const fetched = await fetchDatapullJob(jobId)
        this.selectedJob = fetched || job
      } catch (err) {
        this.error = err.message || 'Failed to fetch job details.'
        this.selectedJob = job
      }
    },
    closeJobDetails() {
      this.selectedJob = null
    },
    async requeueDead(job) {
      const jobId = job && job.job_id ? String(job.job_id) : ''
      if (!jobId) {
        return
      }
      this.requeueJobId = jobId
      try {
        this.error = null
        await requeueDeadLetterJob(jobId)
        await this.loadDeadLetters()
      } catch (err) {
        this.error = err.message || 'Failed to requeue dead-letter job.'
      } finally {
        this.requeueJobId = null
      }
    },
    formatDate(value) {
      if (!value) {
        return '-'
      }
      try {
        return new Date(value).toLocaleString()
      } catch (e) {
        return String(value)
      }
    },
    safeNum(value) {
      if (value === undefined || value === null || Number.isNaN(Number(value))) {
        return '-'
      }
      return Number(value)
    },
    statusClass(status) {
      const normalized = String(status || '').toLowerCase()
      if (normalized === 'completed' || normalized === 'success') return 'ok'
      if (normalized === 'running' || normalized === 'queued') return 'pending'
      if (normalized === 'dead_lettered') return 'dead'
      return 'bad'
    }
  },
  mounted() {
    this.loadActiveTab()
    this.pollHandle = setInterval(() => this.loadActiveTab(), 15000)
  },
  beforeUnmount() {
    if (this.pollHandle) {
      clearInterval(this.pollHandle)
      this.pollHandle = null
    }
  }
}
</script>

<style scoped>
.jobs-page {
  padding: 2rem;
  min-height: 100vh;
  background: linear-gradient(160deg, #f1f6fb 0%, #eaf6ee 100%);
}

.jobs-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 1rem;
  margin-bottom: 1rem;
}

h1 {
  margin: 0;
  color: #1f3c4f;
}

h2,
h3 {
  margin: 0.6rem 0;
  color: #1f3c4f;
}

.subtitle {
  margin: 0.3rem 0 0;
  color: #4f6f81;
}

.tabs {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 0.8rem;
}

.tab-btn {
  border: 1px solid #c7d6e2;
  border-radius: 999px;
  padding: 0.4rem 0.9rem;
  background: #fff;
  color: #315168;
  font-weight: 700;
  cursor: pointer;
}

.tab-btn.active {
  background: #1b7c6d;
  border-color: #1b7c6d;
  color: #fff;
}

.refresh-btn,
.apply-btn,
.table-action {
  border: 0;
  border-radius: 10px;
  padding: 0.45rem 0.8rem;
  background: #1b7c6d;
  color: #fff;
  font-weight: 600;
  cursor: pointer;
}

.table-action {
  font-size: 0.8rem;
  padding: 0.35rem 0.55rem;
}

.table-action.table-action-primary {
  background: #1d63b8;
}

.refresh-btn:disabled,
.apply-btn:disabled,
.table-action:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}

.filters {
  display: grid;
  grid-template-columns: repeat(4, minmax(140px, 1fr)) auto;
  gap: 0.8rem;
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 8px 20px rgba(21, 59, 83, 0.08);
  padding: 1rem;
  margin-bottom: 1rem;
}

.filters label {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  color: #38576c;
  font-weight: 600;
  font-size: 0.85rem;
}

.filters input,
.filters select {
  border: 1px solid #d0dbe4;
  border-radius: 8px;
  padding: 0.5rem 0.6rem;
  font-size: 0.9rem;
  color: #1f2f3d;
  background: #fff;
}

.table-card {
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 8px 20px rgba(21, 59, 83, 0.08);
  padding: 1rem;
}

.table-wrap {
  overflow-x: auto;
}

table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.9rem;
}

th,
td {
  border-bottom: 1px solid #e6edf2;
  text-align: left;
  padding: 0.65rem 0.5rem;
  vertical-align: top;
}

th {
  background: #f2f7fb;
  color: #355062;
}

.job-id {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;
  font-size: 0.82rem;
}

.status-pill {
  border-radius: 999px;
  padding: 0.15rem 0.6rem;
  font-size: 0.75rem;
  font-weight: 700;
  display: inline-block;
}

.status-pill.ok {
  background: #def8e8;
  color: #0f7a3d;
}

.status-pill.pending {
  background: #e5f1ff;
  color: #1e5aa6;
}

.status-pill.bad {
  background: #ffe4e4;
  color: #8b3030;
}

.status-pill.dead {
  background: #f3e8ff;
  color: #5f2d91;
}

.action-row {
  display: flex;
  gap: 0.4rem;
}

.error-col {
  max-width: 260px;
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

.details-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.35);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2000;
}

.details-panel {
  width: min(900px, 92vw);
  max-height: 85vh;
  overflow-y: auto;
  background: #fff;
  border-radius: 12px;
  padding: 1rem;
}

.details-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.6rem;
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(200px, 1fr));
  gap: 0.5rem 1rem;
  margin-bottom: 1rem;
}

.attempt-list {
  display: grid;
  gap: 0.6rem;
}

.attempt-item {
  border: 1px solid #dbe7f0;
  border-radius: 8px;
  padding: 0.55rem 0.65rem;
}

@media (max-width: 1000px) {
  .filters {
    grid-template-columns: repeat(2, minmax(140px, 1fr));
  }

  .detail-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .jobs-page {
    padding: 1rem;
  }

  .jobs-header {
    flex-direction: column;
    align-items: stretch;
  }

  .filters {
    grid-template-columns: 1fr;
  }
}
</style>
