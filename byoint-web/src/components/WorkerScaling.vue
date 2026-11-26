<template>
  <div class="container mt-4 pb-5">
    <div class="d-flex justify-content-between align-items-center mb-3">
      <div>
        <h2 class="mb-1">Worker Scaling</h2>
        <p class="text-muted mb-0">Set desired datapull worker count and trigger scale from UI when enabled.</p>
      </div>
      <button class="btn btn-outline-primary" :disabled="loading" @click="loadState">
        <span v-if="loading" class="spinner-border spinner-border-sm me-2"></span>
        Refresh
      </button>
    </div>

    <div v-if="message" :class="['alert', messageTypeClass]">
      {{ message }}
    </div>

    <div class="card mb-4">
      <div class="card-header"><strong>Runtime State</strong></div>
      <div class="card-body">
        <div class="row g-3">
          <div class="col-md-3">
            <label class="form-label text-muted">Active Workers</label>
            <div class="fw-semibold fs-5">{{ runtimeState.worker_count_active }}</div>
          </div>
          <div class="col-md-3">
            <label class="form-label text-muted">Total Workers Seen</label>
            <div class="fw-semibold fs-5">{{ runtimeState.worker_count_total }}</div>
          </div>
          <div class="col-md-3">
            <label class="form-label text-muted">Queue Depth</label>
            <div class="fw-semibold fs-5">{{ runtimeState.queue_depth }}</div>
          </div>
          <div class="col-md-3">
            <label class="form-label text-muted">Desired Count</label>
            <div class="fw-semibold fs-5">{{ workerScaling.desired_worker_count }}</div>
          </div>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-header"><strong>Scaling Configuration</strong></div>
      <div class="card-body">
        <div class="row g-3 align-items-end">
          <div class="col-md-3">
            <label class="form-label">Desired Worker Count</label>
            <input
              v-model.number="workerScaling.desired_worker_count"
              class="form-control"
              type="number"
              min="1"
              :max="workerScaling.max_workers"
            />
          </div>
          <div class="col-md-3">
            <label class="form-label">Minimum Workers</label>
            <input v-model.number="workerScaling.min_workers" class="form-control" type="number" min="1" />
          </div>
          <div class="col-md-3">
            <label class="form-label">Maximum Workers</label>
            <input v-model.number="workerScaling.max_workers" class="form-control" type="number" min="1" />
          </div>
          <div class="col-md-3">
            <div class="form-check form-switch mt-3">
              <input id="autoScalingToggle" v-model="workerScaling.auto_scaling_enabled" class="form-check-input" type="checkbox" />
              <label class="form-check-label" for="autoScalingToggle">Auto Scaling Enabled</label>
            </div>
          </div>
        </div>

        <div class="d-flex gap-2 mt-4 flex-wrap">
          <button class="btn btn-primary" :disabled="loading" @click="saveConfig">
            <span v-if="saving" class="spinner-border spinner-border-sm me-2"></span>
            Save Configuration
          </button>
          <button class="btn btn-outline-success" :disabled="loading" @click="applyScaling">
            Apply Scaling
          </button>
          <button class="btn btn-outline-secondary" :disabled="!scaleCommand" @click="copyCommand">
            Copy Scale Command
          </button>
        </div>

        <div class="mt-3">
          <label class="form-label text-muted">Scale Command</label>
          <input class="form-control" type="text" :value="scaleCommand" readonly />
          <div class="form-text">
            If API apply is disabled, run this command from your host terminal.
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import {
  fetchWorkerScalingConfig,
  updateWorkerScalingConfig,
  applyWorkerScaling
} from '@/api'

export default {
  name: 'WorkerScaling',
  data() {
    return {
      loading: false,
      saving: false,
      message: '',
      messageType: 'success',
      workerScaling: {
        desired_worker_count: 1,
        auto_scaling_enabled: false,
        min_workers: 1,
        max_workers: 10
      },
      runtimeState: {
        queue_depth: 0,
        worker_count_total: 0,
        worker_count_active: 0,
        workers: []
      },
      scaleCommand: ''
    }
  },
  computed: {
    messageTypeClass() {
      if (this.messageType === 'error') return 'alert-danger'
      if (this.messageType === 'warning') return 'alert-warning'
      return 'alert-success'
    }
  },
  async mounted() {
    await this.loadState()
  },
  methods: {
    setMessage(text, type = 'success') {
      this.message = text
      this.messageType = type
    },
    async loadState() {
      this.loading = true
      this.message = ''
      try {
        const data = await fetchWorkerScalingConfig()
        this.workerScaling = data.worker_scaling || this.workerScaling
        this.runtimeState = data.runtime_state || this.runtimeState
        this.scaleCommand = data.scale_command || ''
      } catch (e) {
        this.setMessage(e.message || 'Failed to load worker scaling state.', 'error')
      } finally {
        this.loading = false
      }
    },
    async saveConfig() {
      this.saving = true
      this.setMessage('')
      try {
        const data = await updateWorkerScalingConfig(this.workerScaling)
        this.workerScaling = data.worker_scaling || this.workerScaling
        this.scaleCommand = data.scale_command || this.scaleCommand
        this.setMessage(data.message || 'Worker scaling configuration updated.')
        await this.loadState()
      } catch (e) {
        this.setMessage(e.message || 'Failed to update worker scaling configuration.', 'error')
      } finally {
        this.saving = false
      }
    },
    async applyScaling() {
      this.loading = true
      this.setMessage('')
      try {
        const data = await applyWorkerScaling(this.workerScaling.desired_worker_count)
        this.setMessage(data.message || 'Scaling command executed.')
        await this.loadState()
      } catch (e) {
        this.setMessage(e.message || 'Failed to apply scaling from API.', 'warning')
      } finally {
        this.loading = false
      }
    },
    async copyCommand() {
      if (!this.scaleCommand) return
      try {
        await navigator.clipboard.writeText(this.scaleCommand)
        this.setMessage('Scale command copied to clipboard.')
      } catch (e) {
        this.setMessage('Unable to copy command automatically. Please copy it manually.', 'warning')
      }
    }
  }
}
</script>
