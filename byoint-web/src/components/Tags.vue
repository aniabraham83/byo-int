<template>
  <div class="container mt-4 pb-5">
    <div class="d-flex justify-content-between align-items-center mb-4">
      <div>
        <h2 class="mb-1">Tags</h2>
        <p class="text-muted mb-0">Display and create tags from the byoint_core_config.tag collection.</p>
      </div>
      <div class="d-flex gap-2">
        <button class="btn btn-success" @click="openCreateModal">
          <i class="me-2">+</i> New Tag
        </button>
        <button class="btn btn-primary" @click="fetchTags" :disabled="loading">
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
      <div v-if="tags.length === 0" class="alert alert-info">No tags found.</div>

      <div v-else class="table-responsive">
        <table class="table table-striped table-hover align-middle">
          <thead class="table-light">
            <tr>
              <th>Tag</th>
              <th>Type</th>
              <th>Description</th>
              <th>Created</th>
              <th>Updated</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="tagItem in tags" :key="tagItem.tag">
              <td><strong>{{ tagItem.tag }}</strong></td>
              <td>{{ tagItem.type || '-' }}</td>
              <td>{{ tagItem.description || '-' }}</td>
              <td>{{ formatDate(tagItem.created_at) }}</td>
              <td>{{ formatDate(tagItem.updated_at) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div v-if="showCreateModal" class="modal-overlay" @click.self="closeCreateModal">
      <div class="modal-content" style="max-width: 520px;">
        <div class="modal-header">
          <h5 class="modal-title">Create Tag</h5>
          <button type="button" class="btn-close" @click="closeCreateModal"></button>
        </div>
        <div class="modal-body">
          <form @submit.prevent="submitCreateTag">
            <div class="mb-3">
              <label class="form-label">Tag</label>
              <input v-model.trim="createForm.tag" type="text" class="form-control" required>
            </div>
            <div class="mb-3">
              <label class="form-label">Description</label>
              <input v-model.trim="createForm.description" type="text" class="form-control" placeholder="Optional">
            </div>
            <div class="mb-3">
              <label class="form-label">Type</label>
              <select v-model="createForm.type" class="form-select">
                <option value="custom">custom</option>
                <option value="builtin" disabled>builtin (disabled)</option>
              </select>
            </div>
          </form>
          <div v-if="formError" class="alert alert-danger mt-2 mb-0">{{ formError }}</div>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" @click="closeCreateModal">Cancel</button>
          <button type="button" class="btn btn-primary" @click="submitCreateTag" :disabled="submitting">
            <span v-if="submitting" class="spinner-border spinner-border-sm me-2"></span>
            {{ submitting ? 'Creating...' : 'Create Tag' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { apiFetch } from '@/api'

export default {
  name: 'TagsPage',
  data() {
    return {
      tags: [],
      loading: false,
      error: '',
      message: '',
      messageType: 'success',
      submitting: false,
      formError: '',
      showCreateModal: false,
      createForm: {
        tag: '',
        description: '',
        type: 'custom'
      }
    }
  },
  async mounted() {
    await this.fetchTags()
  },
  methods: {
    clearFlash() {
      this.message = ''
      this.messageType = 'success'
      this.formError = ''
    },
    formatDate(value) {
      if (!value) {
        return '-'
      }

      const date = new Date(value)
      if (Number.isNaN(date.getTime())) {
        return value
      }

      return date.toLocaleString()
    },
    resetCreateForm() {
      this.createForm = {
        tag: '',
        description: '',
        type: 'custom'
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
    async fetchTags() {
      this.loading = true
      this.error = ''
      try {
        const res = await apiFetch('/api/tags')
        const data = await res.json()
        if (!res.ok) {
          this.error = data.message || 'Failed to fetch tags.'
          this.tags = []
          return
        }

        this.tags = Array.isArray(data.tags) ? data.tags : []
      } catch (e) {
        this.error = 'Network error while fetching tags.'
        this.tags = []
      } finally {
        this.loading = false
      }
    },
    async submitCreateTag() {
      if (!this.createForm.tag) {
        this.formError = 'Tag is required.'
        return
      }

      this.submitting = true
      this.formError = ''
      try {
        const res = await apiFetch('/api/tags', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            tag: this.createForm.tag,
            description: this.createForm.description || null,
            type: this.createForm.type || null
          })
        })
        const data = await res.json()
        if (!res.ok) {
          this.formError = data.message || 'Failed to create tag.'
          return
        }

        this.message = data.message || 'Tag created successfully.'
        this.messageType = 'success'
        this.closeCreateModal()
        await this.fetchTags()
      } catch (e) {
        this.formError = 'Network error while creating tag.'
      } finally {
        this.submitting = false
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
