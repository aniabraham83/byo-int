<template>
  <div class="container mt-4 pb-5">
    <div class="d-flex justify-content-between align-items-center mb-4">
      <div>
        <h2 class="mb-1">Secrets</h2>
        <p class="text-muted mb-0">Manage encrypted datapull secrets. Secret values are never displayed.</p>
      </div>
      <div class="d-flex gap-2">
        <button class="btn btn-success" @click="openCreateModal">
          <i class="me-2">+</i> New Secret
        </button>
        <button class="btn btn-primary" @click="fetchSecrets" :disabled="loading">
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
      <div v-if="secrets.length === 0" class="alert alert-info">No secrets found.</div>

      <div v-else class="table-responsive">
        <table class="table table-striped table-hover align-middle">
          <thead class="table-light">
            <tr>
              <th>Name</th>
              <th>Secret Ref</th>
              <th>Description</th>
              <th>Version</th>
              <th>Active</th>
              <th>Where Used</th>
              <th>Updated</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="secret in secrets" :key="secret.secret_ref">
              <td><strong>{{ secret.name }}</strong></td>
              <td><code>{{ secret.secret_ref }}</code></td>
              <td>{{ secret.description || '-' }}</td>
              <td>{{ secret.version || 1 }}</td>
              <td>
                <span v-if="secret.active" class="badge bg-success">Active</span>
                <span v-else class="badge bg-secondary">Inactive</span>
              </td>
              <td>
                <span class="badge" :class="(secret.where_used_count || 0) > 0 ? 'bg-warning text-dark' : 'bg-light text-dark'">
                  {{ secret.where_used_count || 0 }} workflow(s)
                </span>
                <div v-if="(secret.where_used_sources || []).length" class="small text-muted mt-1">
                  {{ (secret.where_used_sources || []).slice(0, 3).join(', ') }}<span v-if="(secret.where_used_sources || []).length > 3"> +{{ (secret.where_used_sources || []).length - 3 }} more</span>
                </div>
              </td>
              <td>{{ formatDate(secret.updated_at) }}</td>
              <td>
                <div class="d-flex gap-2">
                  <button class="btn btn-sm btn-outline-primary" @click="openRotateModal(secret)" :disabled="!secret.active">Rotate</button>
                  <button class="btn btn-sm btn-outline-danger" @click="confirmDeleteSecret(secret)" :disabled="!secret.active || deletingSecretRef === secret.secret_ref || (secret.where_used_count || 0) > 0" :title="(secret.where_used_count || 0) > 0 ? 'Secret is in use by workflows' : 'Deactivate secret'">
                    <span v-if="deletingSecretRef === secret.secret_ref" class="spinner-border spinner-border-sm"></span>
                    <span v-else>Delete</span>
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div v-if="showCreateModal" class="modal-overlay" @click.self="closeCreateModal">
      <div class="modal-content" style="max-width: 520px;">
        <div class="modal-header">
          <h5 class="modal-title">Create Secret</h5>
          <button type="button" class="btn-close" @click="closeCreateModal"></button>
        </div>
        <div class="modal-body">
          <form @submit.prevent="submitCreateSecret">
            <div class="mb-3">
              <label class="form-label">Name</label>
              <input v-model.trim="createForm.name" type="text" class="form-control" required>
            </div>
            <div class="mb-3">
              <label class="form-label">Description</label>
              <input v-model.trim="createForm.description" type="text" class="form-control" placeholder="Optional">
            </div>
            <div class="mb-3">
              <label class="form-label">Secret Value</label>
              <input v-model="createForm.value" type="password" class="form-control" required autocomplete="new-password">
            </div>
          </form>
          <div class="alert alert-warning small mb-0">Secret values are write-only and will not be shown after save.</div>
          <div v-if="formError" class="alert alert-danger mt-2 mb-0">{{ formError }}</div>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" @click="closeCreateModal">Cancel</button>
          <button type="button" class="btn btn-primary" @click="submitCreateSecret" :disabled="submitting">
            <span v-if="submitting" class="spinner-border spinner-border-sm me-2"></span>
            {{ submitting ? 'Creating...' : 'Create Secret' }}
          </button>
        </div>
      </div>
    </div>

    <div v-if="showRotateModal" class="modal-overlay" @click.self="closeRotateModal">
      <div class="modal-content" style="max-width: 520px;">
        <div class="modal-header">
          <h5 class="modal-title">Rotate Secret</h5>
          <button type="button" class="btn-close" @click="closeRotateModal"></button>
        </div>
        <div class="modal-body">
          <div class="mb-3">
            <label class="form-label">Secret</label>
            <input :value="`${rotateForm.name} (${rotateForm.secret_ref})`" type="text" class="form-control" disabled>
          </div>
          <form @submit.prevent="submitRotateSecret">
            <div class="mb-3">
              <label class="form-label">New Secret Value</label>
              <input v-model="rotateForm.value" type="password" class="form-control" required autocomplete="new-password">
            </div>
          </form>
          <div class="alert alert-warning small mb-0">Only the new value is accepted; current value is never retrievable.</div>
          <div v-if="formError" class="alert alert-danger mt-2 mb-0">{{ formError }}</div>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" @click="closeRotateModal">Cancel</button>
          <button type="button" class="btn btn-primary" @click="submitRotateSecret" :disabled="submitting">
            <span v-if="submitting" class="spinner-border spinner-border-sm me-2"></span>
            {{ submitting ? 'Rotating...' : 'Rotate Secret' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { apiFetch } from '@/api'

export default {
  name: 'SecretsPage',
  data() {
    return {
      secrets: [],
      loading: false,
      error: '',
      message: '',
      messageType: 'success',
      submitting: false,
      formError: '',
      deletingSecretRef: '',
      showCreateModal: false,
      showRotateModal: false,
      createForm: {
        name: '',
        description: '',
        value: ''
      },
      rotateForm: {
        secret_ref: '',
        name: '',
        value: ''
      }
    }
  },
  async mounted() {
    await this.fetchSecrets()
  },
  methods: {
    clearFlash() {
      this.message = ''
      this.messageType = 'success'
      this.formError = ''
    },
    formatDate(value) {
      if (!value) return '-'
      const date = new Date(value)
      if (Number.isNaN(date.getTime())) return value
      return date.toLocaleString()
    },
    async fetchSecrets() {
      this.loading = true
      this.error = ''
      try {
        const res = await apiFetch('/api/secrets?include_usage=true')
        const data = await res.json()
        if (!res.ok) {
          this.error = data.message || 'Failed to fetch secrets.'
          this.secrets = []
          return
        }
        this.secrets = Array.isArray(data.secrets) ? data.secrets : []
      } catch (e) {
        this.error = 'Network error while fetching secrets.'
        this.secrets = []
      } finally {
        this.loading = false
      }
    },
    openCreateModal() {
      this.clearFlash()
      this.createForm = { name: '', description: '', value: '' }
      this.showCreateModal = true
    },
    closeCreateModal() {
      this.showCreateModal = false
      this.submitting = false
      this.formError = ''
      this.createForm = { name: '', description: '', value: '' }
    },
    openRotateModal(secret) {
      this.clearFlash()
      this.rotateForm = {
        secret_ref: secret.secret_ref,
        name: secret.name,
        value: ''
      }
      this.showRotateModal = true
    },
    closeRotateModal() {
      this.showRotateModal = false
      this.submitting = false
      this.formError = ''
      this.rotateForm = { secret_ref: '', name: '', value: '' }
    },
    async submitCreateSecret() {
      if (!this.createForm.name || !this.createForm.value) {
        this.formError = 'Name and secret value are required.'
        return
      }
      this.submitting = true
      this.formError = ''
      try {
        const res = await apiFetch('/api/secrets/create', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: this.createForm.name,
            description: this.createForm.description || null,
            value: this.createForm.value
          })
        })
        const data = await res.json()
        if (!res.ok) {
          this.formError = data.message || 'Failed to create secret.'
          return
        }
        this.message = data.message || 'Secret created successfully.'
        this.messageType = 'success'
        this.closeCreateModal()
        await this.fetchSecrets()
      } catch (e) {
        this.formError = 'Network error while creating secret.'
      } finally {
        this.submitting = false
      }
    },
    async submitRotateSecret() {
      if (!this.rotateForm.secret_ref || !this.rotateForm.value) {
        this.formError = 'New secret value is required.'
        return
      }
      this.submitting = true
      this.formError = ''
      try {
        const res = await apiFetch('/api/secrets/rotate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            secret_ref: this.rotateForm.secret_ref,
            value: this.rotateForm.value
          })
        })
        const data = await res.json()
        if (!res.ok) {
          this.formError = data.message || 'Failed to rotate secret.'
          return
        }
        this.message = data.message || 'Secret rotated successfully.'
        this.messageType = 'success'
        this.closeRotateModal()
        await this.fetchSecrets()
      } catch (e) {
        this.formError = 'Network error while rotating secret.'
      } finally {
        this.submitting = false
      }
    },
    async confirmDeleteSecret(secret) {
      if (!secret || !secret.secret_ref) return
      if (!confirm(`Deactivate secret '${secret.name}'?`)) return

      this.deletingSecretRef = secret.secret_ref
      this.clearFlash()
      try {
        const res = await apiFetch(`/api/secrets/${encodeURIComponent(secret.secret_ref)}`, {
          method: 'DELETE'
        })
        const data = await res.json().catch(() => ({}))
        if (!res.ok) {
          this.message = data.message || 'Failed to deactivate secret.'
          this.messageType = 'error'
          return
        }

        this.message = data.message || 'Secret deactivated successfully.'
        this.messageType = 'success'
        await this.fetchSecrets()
      } catch (e) {
        this.message = 'Network error while deactivating secret.'
        this.messageType = 'error'
      } finally {
        this.deletingSecretRef = ''
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
