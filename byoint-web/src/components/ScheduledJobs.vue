<template>
  <div class="scheduled-jobs-container">
    <div class="header-section">
      <h1>Scheduled Jobs</h1>
      <p class="subtitle">Monitor your scheduled datapull workflows</p>
    </div>

    <div class="jobs-content" v-if="jobs.length > 0">
      <table class="jobs-table">
        <thead>
          <tr>
            <th>Source Name</th>
            <th>Description</th>
            <th>Category</th>
            <th>Interval (min)</th>
            <th>Next Run</th>
            <th>APScheduler Job ID</th>
            <th>APScheduler Status</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="job in jobs" :key="job.source_name" class="job-row">
            <td class="source-name">{{ job.source_name }}</td>
            <td class="description">{{ job.source_description || '-' }}</td>
            <td class="category">
              <span class="badge" :class="`badge-${job.source_category.toLowerCase()}`">
                {{ job.source_category }}
              </span>
            </td>
            <td class="interval">{{ job.interval_minutes }}</td>
            <td class="next-run">
              {{ formatDateTime(job.next_run) }}
            </td>
            <td class="aps-job-id">{{ job.aps_job_id || '—' }}</td>
            <td class="aps-job-status">
              <span v-if="job.aps_job_status" class="badge bg-info">{{ job.aps_job_status }}</span>
              <span v-else class="badge bg-secondary">—</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="empty-state" v-else>
      <p>No scheduled jobs found</p>
    </div>

    <div v-if="error" class="alert alert-danger">
      {{ error }}
    </div>
  </div>
</template>

<script>
import { apiFetch } from '@/api'

export default {
  name: 'ScheduledJobs',
  data() {
    return {
      jobs: [],
      error: null,
      loading: true
    }
  },
  methods: {
    async fetchScheduledJobs() {
      try {
        this.loading = true;
        this.error = null;
        const response = await apiFetch('/api/scheduled-jobs', {
          headers: { 'Content-Type': 'application/json' }
        });
        let data = null;
        try {
          data = await response.json();
        } catch (jsonErr) {
          // If JSON parsing fails, show generic error
          this.error = 'Failed to parse server response.';
          this.jobs = [];
          return;
        }
        if (!response.ok) {
          this.error = data.error || data.message || 'Failed to fetch scheduled jobs.';
          this.jobs = [];
          return;
        }
        this.jobs = data.jobs || [];
      } catch (err) {
        this.error = err.message || 'Network error fetching jobs.';
        this.jobs = [];
        console.error('Error fetching scheduled jobs:', err);
      } finally {
        this.loading = false;
      }
    },
    formatDateTime(isoString) {
      if (!isoString) return 'N/A'
      
      const date = new Date(isoString)
      const now = new Date()
      
      // Check if it's today, tomorrow, or a future date
      const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
      const dateOnly = new Date(date.getFullYear(), date.getMonth(), date.getDate())
      
      if (dateOnly.getTime() === today.getTime()) {
        // Today - show time only
        return date.toLocaleTimeString('en-US', { 
          hour: '2-digit', 
          minute: '2-digit',
          hour12: true 
        })
      } else {
        // Past or future - show date and time
        return date.toLocaleString('en-US', {
          month: 'short',
          day: 'numeric',
          hour: '2-digit',
          minute: '2-digit',
          hour12: true
        })
      }
    }
  },
  mounted() {
    this.fetchScheduledJobs()
    // Refresh every 30 seconds
    this.interval = setInterval(() => {
      this.fetchScheduledJobs()
    }, 30000)
  },
  beforeUnmount() {
    if (this.interval) {
      clearInterval(this.interval)
    }
  }
}
</script>

<style scoped>
.scheduled-jobs-container {
  padding: 2rem;
  background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
  min-height: 100vh;
}

.header-section {
  margin-bottom: 2rem;
}

.header-section h1 {
  font-size: 2.5rem;
  color: #2c3e50;
  margin-bottom: 0.5rem;
  font-weight: 700;
}

.subtitle {
  color: #7f8c8d;
  font-size: 1rem;
}

.jobs-content {
  background: white;
  border-radius: 8px;
  box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
  overflow: hidden;
}

.jobs-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.95rem;
}

.jobs-table thead {
  background-color: #34495e;
  color: white;
}

.jobs-table th {
  padding: 1rem;
  text-align: left;
  font-weight: 600;
  border-bottom: 2px solid #2c3e50;
}

.job-row {
  border-bottom: 1px solid #ecf0f1;
  transition: background-color 0.2s ease;
}

.job-row:hover {
  background-color: #f8f9fa;
}

.jobs-table td {
  padding: 1rem;
  color: #2c3e50;
}

.source-name {
  font-weight: 600;
  color: #2980b9;
}

.description {
  color: #7f8c8d;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.category {
  text-align: center;
}

.badge {
  display: inline-block;
  padding: 0.4rem 0.8rem;
  border-radius: 20px;
  font-size: 0.85rem;
  font-weight: 500;
}

.badge-feeds {
  background-color: #e8f4f8;
  color: #0c5460;
}

.badge-malware {
  background-color: #f8d7da;
  color: #721c24;
}

.badge-phishing {
  background-color: #fff3cd;
  color: #856404;
}

.interval {
  text-align: center;
  color: #2c3e50;
}

.status {
  text-align: center;
}

.status-badge {
  display: inline-block;
  padding: 0.4rem 0.8rem;
  border-radius: 4px;
  font-size: 0.85rem;
  font-weight: 600;
  text-align: center;
  min-width: 90px;
}

.status-success {
  background-color: #d4edda;
  color: #155724;
}

.status-error {
  background-color: #f8d7da;
  color: #721c24;
}

.status-never {
  background-color: #e2e3e5;
  color: #383d41;
}

.status-running {
  background-color: #d1ecf1;
  color: #0c5460;
}

.last-run,
.next-run {
  color: #7f8c8d;
  font-size: 0.9rem;
}

.empty-state {
  padding: 3rem;
  text-align: center;
  color: #7f8c8d;
  background: white;
  border-radius: 8px;
  box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
}

.alert {
  margin-top: 1rem;
  padding: 1rem;
  border-radius: 4px;
}

.alert-danger {
  background-color: #f8d7da;
  color: #721c24;
  border: 1px solid #f5c6cb;
}
</style>
