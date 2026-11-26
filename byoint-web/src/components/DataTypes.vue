<template>
  <div class="container mt-4 pb-5">
    <div class="d-flex justify-content-between align-items-center mb-4">
      <div>
        <h2 class="mb-1">Data Types</h2>
        <p class="text-muted mb-0">View and add data types from the byoint_core_config.data_types collection.</p>
      </div>
      <div class="d-flex gap-2">
        <button class="btn btn-success" @click="openCreateModal">
          <i class="me-2">+</i> New Data Type
        </button>
        <button class="btn btn-primary" @click="fetchDataTypes" :disabled="loading">
          <span v-if="loading" class="spinner-border spinner-border-sm me-2"></span>
          Refresh
        </button>
      </div>
    </div>

    <div v-if="message" :class="['alert', messageType === 'error' ? 'alert-danger' : 'alert-success']">
      {{ message }}
    </div>

    <div v-if="loading" class="mt-3">
      <div class="spinner-border text-primary" role="status">
        <span class="visually-hidden">Loading...</span>
      </div>
    </div>

    <div v-else-if="error" class="alert alert-danger">{{ error }}</div>

    <div v-else>
      <div v-if="dataTypes.length === 0" class="alert alert-info">No data types found.</div>

      <div v-else class="table-responsive">
        <table class="table table-striped table-hover align-middle">
          <thead class="table-light">
            <tr>
              <th>Data Type</th>
              <th>Type</th>
              <th>Regex Extract Pattern</th>
              <th>Description</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in dataTypes" :key="item.name">
              <td><strong>{{ item.name }}</strong></td>
              <td>{{ item.type || '-' }}</td>
              <td>
                <code v-if="item.regex_extract_pattern">{{ item.regex_extract_pattern }}</code>
                <span v-else>-</span>
              </td>
              <td>{{ item.description || '-' }}</td>
              <td>
                <button
                  v-if="item.type && item.type.toLowerCase() === 'custom'"
                  class="btn btn-sm btn-outline-danger"
                  @click="deleteDataType(item.name)"
                >Delete</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div v-if="showCreateModal" class="modal-overlay" @click.self="closeCreateModal">
      <div class="modal-content" style="max-width: 600px;">
        <div class="modal-header">
          <h5 class="modal-title">Create Data Type</h5>
          <button type="button" class="btn-close" @click="closeCreateModal"></button>
        </div>
        <div class="modal-body">
          <form @submit.prevent="submitCreateDataType">
            <div class="mb-3">
              <label class="form-label">Data Type Name</label>
              <input v-model.trim="createForm.name" type="text" class="form-control" required>
            </div>
            <div class="mb-3">
              <label class="form-label">Type</label>
              <input type="text" class="form-control" value="Custom" disabled>
            </div>
            <div class="mb-3">
              <label class="form-label">Regex Extract Pattern</label>
              <input
                v-model.trim="createForm.regex_extract_pattern"
                type="text"
                class="form-control"
                placeholder="Optional (example: ^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$)"
              >
              <div class="form-text">Optional. Used by datapull type extraction when source_type is selected.</div>
            </div>
            <div class="mb-3">
              <label class="form-label">Description</label>
              <input v-model.trim="createForm.description" type="text" class="form-control" placeholder="Optional">
            </div>
          </form>
          <div v-if="formError" class="alert alert-danger mt-2 mb-0">{{ formError }}</div>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" @click="closeCreateModal">Cancel</button>
          <button type="button" class="btn btn-primary" @click="submitCreateDataType" :disabled="submitting">
            <span v-if="submitting" class="spinner-border spinner-border-sm me-2"></span>
            {{ submitting ? 'Creating...' : 'Create Data Type' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { apiFetch } from '@/api'

export default {
  name: 'DataTypesPage',
  data() {
    return {
      dataTypes: [],
      loading: false,
      error: '',
      message: '',
      messageType: 'success',
      submitting: false,
      formError: '',
      showCreateModal: false,
      createForm: {
        name: '',
        type: 'Custom',
        regex_extract_pattern: '',
        description: ''
      }
    }
  },
  async mounted() {
    await this.fetchDataTypes()
  },
  methods: {
    clearFlash() {
      this.message = ''
      this.messageType = 'success'
      this.formError = ''
    },
    resetCreateForm() {
      this.createForm = {
        name: '',
        type: 'Custom',
        regex_extract_pattern: '',
        description: ''
      }
    },
    openCreateModal() {
      this.clearFlash()
      this.resetCreateForm()
      this.showCreateModal = true
    },
    closeCreateModal() {
      this.showCreateModal = false
      this.submitting = false
      this.formError = ''
      this.resetCreateForm()
    },
    async fetchDataTypes() {
      this.loading = true
      this.error = ''
      try {
        const res = await apiFetch('/api/data_types/details')
        const data = await res.json()
        if (!res.ok) {
          const fallbackRes = await apiFetch('/api/data_types')
          const fallbackData = await fallbackRes.json()
          if (!fallbackRes.ok) {
            this.error = data.message || fallbackData.message || 'Failed to fetch data types.'
            this.dataTypes = []
            return
          }

          const names = Array.isArray(fallbackData.data_types) ? fallbackData.data_types : []
          this.dataTypes = names
            .map((name) => ({
              name,
              regex_extract_pattern: '',
              description: ''
            }))
            .sort((a, b) => a.name.localeCompare(b.name))
          return
        }

        const rows = Array.isArray(data.data_types) ? data.data_types : []
        this.dataTypes = rows
          .map((row) => ({
            name: String((row || {}).name || '').trim(),
            type: String((row || {}).type || '').trim(),
            regex_extract_pattern: String((row || {}).regex_extract_pattern || '').trim(),
            description: String((row || {}).description || '').trim()
          }))
          .filter((row) => row.name)
          .sort((a, b) => a.name.localeCompare(b.name))
      } catch (e) {
        this.error = 'Network error while fetching data types.'
        this.dataTypes = []
      } finally {
        this.loading = false
      }
    },
    async submitCreateDataType() {
      if (!this.createForm.name) {
        this.formError = 'Data type name is required.'
        return
      }

      this.submitting = true
      this.formError = ''
      try {
        const res = await apiFetch('/api/data_types', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: this.createForm.name,
            type: this.createForm.type || null,
            regex_extract_pattern: this.createForm.regex_extract_pattern || null,
            description: this.createForm.description || null
          })
        })

        const data = await res.json()
        if (!res.ok) {
          this.formError = data.message || 'Failed to create data type.'
          return
        }

        this.message = data.message || 'Data type created successfully.'
        this.messageType = 'success'
        this.closeCreateModal()
        await this.fetchDataTypes()
      } catch (e) {
        this.formError = 'Network error while creating data type.'
      } finally {
        this.submitting = false
      }
    },
    async deleteDataType(name) {
      if (!confirm(`Delete data type "${name}"?`)) return
      try {
        const res = await apiFetch(`/api/data_types/${encodeURIComponent(name)}`, { method: 'DELETE' })
        const data = await res.json()
        if (!res.ok) {
          this.message = data.message || 'Failed to delete data type.'
          this.messageType = 'error'
          return
        }
        this.message = data.message || 'Data type deleted.'
        this.messageType = 'success'
        await this.fetchDataTypes()
      } catch (e) {
        this.message = 'Network error while deleting data type.'
        this.messageType = 'error'
      }
    }
  }
}
</script>

<style scoped>
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1050;
}

.modal-content {
  background: white;
  border-radius: 12px;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.2);
  width: 90%;
  max-height: 90vh;
  overflow-y: auto;
}

.modal-header {
  padding: 1rem 1.25rem;
  border-bottom: 1px solid #e9ecef;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.modal-body {
  padding: 1.25rem;
}

.modal-footer {
  padding: 1rem 1.25rem;
  border-top: 1px solid #e9ecef;
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
}
</style>
