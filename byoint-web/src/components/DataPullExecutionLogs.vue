<template>
  <div>
    <h5>Execution Logs for {{ sourceName }}</h5>
    <div v-if="loading" class="my-3">
      <span>Loading logs...</span>
    </div>
    <div v-else-if="logs.length === 0" class="alert alert-info my-3">
      No execution logs found for this datapull.
    </div>
    <div v-else class="table-responsive">
      <table class="table table-sm table-bordered">
        <thead>
          <tr>
            <th>Timestamp</th>
            <th>Status</th>
            <th>Duration (s)</th>
            <th>Error</th>
            <th>DP Logs</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="log in logs" :key="log._id">
            <td>{{ log.timestamp ? new Date(log.timestamp).toLocaleString() : '' }}</td>
            <td :class="{'text-success': log.status === 'success', 'text-danger': log.status === 'error'}">{{ log.status }}</td>
            <td>{{ log.duration_seconds ? log.duration_seconds.toFixed(2) : '' }}</td>
            <td><span v-if="log.error">{{ log.error }}</span></td>
            <td>
              <button
                v-if="log.dp_log"
                class="btn btn-link p-0"
                type="button"
                @click="openDpLog(log)"
              >
                dp_log
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-if="showDpLog" class="dp-log-modal" @click.self="closeDpLog">
      <div class="dp-log-modal__content">
        <div class="dp-log-modal__header">
          <strong>DP Log</strong>
          <button class="btn btn-sm btn-outline-secondary" type="button" @click="closeDpLog">Close</button>
        </div>
        <div class="dp-log-modal__body">
          <div v-if="dpLogLines.length === 0" class="text-muted">No log content.</div>
          <div v-else class="dp-log-modal__lines">
            <div v-for="(line, index) in dpLogLines" :key="index" class="dp-log-modal__line">{{ line }}</div>
          </div>
        </div>
      </div>
    </div>
    <button class="btn btn-secondary mt-2" @click="$emit('close')">Close</button>
  </div>
</template>

<script>
import { apiFetch } from '@/api'

export default {
  name: 'DataPullExecutionLogs',
  props: {
    sourceName: { type: String, required: true }
  },
  data() {
    return {
      logs: [],
      loading: false,
      showDpLog: false,
      dpLogLines: []
    };
  },
  methods: {
    openDpLog(log) {
      let raw = log && log.dp_log != null ? log.dp_log : '';
      if (Array.isArray(raw)) {
        raw = raw.join('\n');
      } else if (typeof raw === 'object') {
        raw = JSON.stringify(raw, null, 2);
      } else {
        raw = String(raw);
      }
      this.dpLogLines = raw.split(/\r?\n/);
      this.showDpLog = true;
    },
    closeDpLog() {
      this.showDpLog = false;
      this.dpLogLines = [];
    },
    async fetchLogs() {
      this.loading = true;
      try {
        const res = await apiFetch(`/api/datapull_executions?source_name=${encodeURIComponent(this.sourceName)}`);
        if (res.ok) {
          const data = await res.json();
          this.logs = Array.isArray(data.logs) ? data.logs : [];
        } else {
          this.logs = [];
        }
      } catch (e) {
        this.logs = [];
      } finally {
        this.loading = false;
      }
    }
  },
  mounted() {
    this.fetchLogs();
  }
};
</script>

<style scoped>
.dp-log-modal {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1050;
}

.dp-log-modal__content {
  background: #fff;
  width: min(900px, 92vw);
  max-height: 80vh;
  border-radius: 6px;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.25);
  display: flex;
  flex-direction: column;
}

.dp-log-modal__header {
  padding: 12px 16px;
  border-bottom: 1px solid #e6e6e6;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.dp-log-modal__body {
  padding: 12px 16px;
  overflow: auto;
}

.dp-log-modal__lines {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  font-size: 12px;
  line-height: 1.4;
  white-space: pre-wrap;
  word-break: break-word;
}

.dp-log-modal__line {
  white-space: pre-wrap;
}

.dp-log-modal__pre {
  margin: 0;
  font-size: 12px;
  line-height: 1.4;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
