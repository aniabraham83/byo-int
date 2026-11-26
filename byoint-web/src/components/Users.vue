<template>
  <div class="container mt-4 pb-5">
    <div class="d-flex justify-content-between align-items-center mb-4">
      <div>
        <h2 class="mb-1">User Management</h2>
        <p class="text-muted mb-0">Create and update application users stored in MongoDB.</p>
      </div>
      <div class="d-flex gap-2">
        <button class="btn btn-outline-dark" @click="generateMyApiKey" :disabled="generatingApiKey || !currentUser">
          <span v-if="generatingApiKey" class="spinner-border spinner-border-sm me-2"></span>
          {{ generatingApiKey ? 'Generating...' : 'Generate My API Key' }}
        </button>
        <button class="btn btn-success" @click="openCreateModal">
          <i class="me-2">+</i> New User
        </button>
        <button class="btn btn-primary" @click="fetchUsers" :disabled="loading">
          <span v-if="loading" class="spinner-border spinner-border-sm me-2"></span>
          Refresh
        </button>
      </div>
    </div>

    <div v-if="message" :class="['alert', messageType === 'error' ? 'alert-danger' : 'alert-success']">
      {{ message }}
    </div>

    <div v-if="myApiKey" class="alert alert-warning d-flex flex-column flex-md-row justify-content-between align-items-md-center gap-2">
      <div>
        <div class="fw-semibold">Your new API key (shown once):</div>
        <div class="font-monospace text-break">{{ myApiKey }}</div>
      </div>
      <button class="btn btn-sm btn-outline-secondary" @click="copyApiKey">Copy</button>
    </div>

    <div v-if="loading" class="mt-3">
      <div class="spinner-border text-primary" role="status">
        <span class="visually-hidden">Loading...</span>
      </div>
    </div>

    <div v-else-if="error" class="alert alert-danger">{{ error }}</div>

    <div v-else>
      <div v-if="users.length === 0" class="alert alert-info">No users found.</div>

      <div v-else class="table-responsive">
        <table class="table table-striped table-hover align-middle">
          <thead class="table-light">
            <tr>
              <th>Username</th>
              <th>Email</th>
              <th>Roles</th>
              <th>Created</th>
              <th>Updated</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="user in users" :key="user.username">
              <td><strong>{{ user.username }}</strong></td>
              <td>{{ user.email || '-' }}</td>
              <td>
                <div class="d-flex flex-wrap gap-1">
                  <span
                    v-for="role in userRoles(user.roles)"
                    :key="`${user.username}-${role}`"
                    class="badge role-badge"
                  >
                    {{ role }}
                  </span>
                  <span v-if="userRoles(user.roles).length === 0" class="text-muted">-</span>
                </div>
              </td>
              <td>{{ formatDate(user.created_at) }}</td>
              <td>{{ formatDate(user.updated_at) }}</td>
              <td>
                <button class="btn btn-sm btn-outline-primary" @click="openEditModal(user)">Edit</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div v-if="showCreateModal" class="modal-overlay" @click.self="closeCreateModal">
      <div class="modal-content" style="max-width: 520px;">
        <div class="modal-header">
          <h5 class="modal-title">Create User</h5>
          <button type="button" class="btn-close" @click="closeCreateModal"></button>
        </div>
        <div class="modal-body">
          <form @submit.prevent="submitCreateUser">
            <div class="mb-3">
              <label class="form-label">Username</label>
              <input v-model.trim="createForm.username" type="text" class="form-control" required>
            </div>
            <div class="mb-3">
              <label class="form-label">Email</label>
              <input v-model.trim="createForm.email" type="email" class="form-control" placeholder="Optional">
            </div>
            <div class="mb-3">
              <label class="form-label">Password</label>
              <input v-model="createForm.password" type="password" class="form-control" required>
            </div>
          </form>
          <div v-if="formError" class="alert alert-danger mt-2 mb-0">{{ formError }}</div>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" @click="closeCreateModal">Cancel</button>
          <button type="button" class="btn btn-primary" @click="submitCreateUser" :disabled="submitting">
            <span v-if="submitting" class="spinner-border spinner-border-sm me-2"></span>
            {{ submitting ? 'Creating...' : 'Create User' }}
          </button>
        </div>
      </div>
    </div>

    <div v-if="showEditModal" class="modal-overlay" @click.self="closeEditModal">
      <div class="modal-content" style="max-width: 520px;">
        <div class="modal-header">
          <h5 class="modal-title">Edit User</h5>
          <button type="button" class="btn-close" @click="closeEditModal"></button>
        </div>
        <div class="modal-body">
          <form @submit.prevent="submitEditUser">
            <div class="mb-3">
              <label class="form-label">Username</label>
              <input v-model="editForm.username" type="text" class="form-control" disabled>
            </div>
            <div class="mb-3">
              <label class="form-label">Email</label>
              <input v-model.trim="editForm.email" type="email" class="form-control" placeholder="Optional">
            </div>
            <div class="mb-1">
              <label class="form-label">New Password</label>
              <input v-model="editForm.password" type="password" class="form-control" placeholder="Leave blank to keep current password">
            </div>
            <div class="form-text">Leave password blank to keep the current password.</div>

            <div class="mt-4">
              <h6 class="mb-2">Roles</h6>
              <div v-if="isAdmin" class="d-flex flex-column gap-2">
                <div class="d-flex flex-wrap gap-2" v-if="userRoles(editForm.roles).length > 0">
                  <span
                    v-for="role in userRoles(editForm.roles)"
                    :key="`edit-${editForm.username}-${role}`"
                    class="badge role-badge d-inline-flex align-items-center"
                  >
                    {{ role }}
                    <button
                      type="button"
                      class="btn btn-sm btn-link text-white p-0 ms-2 role-remove-btn"
                      title="Revoke role"
                      @click="revokeRoleFromEditingUser(role)"
                      :disabled="submitting"
                    >
                      x
                    </button>
                  </span>
                </div>
                <div v-else class="text-muted small">No roles assigned.</div>

                <div class="input-group">
                  <input
                    v-model.trim="editForm.newRole"
                    type="text"
                    class="form-control"
                    placeholder="Add role (e.g. admin, ops, analyst)"
                    :disabled="submitting"
                    @keyup.enter="grantRoleToEditingUser"
                  >
                  <button
                    type="button"
                    class="btn btn-outline-primary"
                    @click="grantRoleToEditingUser"
                    :disabled="submitting || !editForm.newRole"
                  >
                    Add Role
                  </button>
                </div>
              </div>
              <div v-else class="text-muted small">Only admins can modify roles.</div>
            </div>
          </form>
          <div v-if="formError" class="alert alert-danger mt-2 mb-0">{{ formError }}</div>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" @click="closeEditModal">Cancel</button>
          <button type="button" class="btn btn-primary" @click="submitEditUser" :disabled="submitting">
            <span v-if="submitting" class="spinner-border spinner-border-sm me-2"></span>
            {{ submitting ? 'Saving...' : 'Save Changes' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { apiFetch, fetchCurrentIdentity, rotateCurrentUserApiKey, grantUserRole, revokeUserRole } from '@/api'

export default {
  name: 'UsersPage',
  data() {
    return {
      users: [],
      loading: false,
      error: '',
      message: '',
      messageType: 'success',
      myApiKey: '',
      currentUser: '',
      currentUserRoles: [],
      generatingApiKey: false,
      submitting: false,
      formError: '',
      showCreateModal: false,
      showEditModal: false,
      createForm: {
        username: '',
        email: '',
        password: ''
      },
      editForm: {
        username: '',
        email: '',
        password: '',
        roles: [],
        newRole: ''
      }
    }
  },
  computed: {
    isAdmin() {
      return this.userRoles(this.currentUserRoles).includes('admin')
    }
  },
  async mounted() {
    await this.fetchCurrentUser()
    await this.fetchUsers()
  },
  methods: {
    async fetchCurrentUser() {
      try {
        const identity = await fetchCurrentIdentity()
        this.currentUser = identity.user || ''
        this.currentUserRoles = this.userRoles(identity.roles)
      } catch (e) {
        this.currentUser = ''
        this.currentUserRoles = []
      }
    },
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
        username: '',
        email: '',
        password: ''
      }
    },
    resetEditForm() {
      this.editForm = {
        username: '',
        email: '',
        password: '',
        roles: [],
        newRole: ''
      }
    },
    userRoles(roles) {
      if (!Array.isArray(roles)) {
        return []
      }
      const normalized = []
      const seen = new Set()
      for (const role of roles) {
        const value = String(role || '').trim().toLowerCase()
        if (!value || seen.has(value)) {
          continue
        }
        seen.add(value)
        normalized.push(value)
      }
      return normalized
    },
    syncUserInList(userDoc) {
      if (!userDoc || !userDoc.username) {
        return
      }

      const idx = this.users.findIndex((u) => u.username === userDoc.username)
      if (idx === -1) {
        return
      }

      this.users.splice(idx, 1, {
        ...this.users[idx],
        ...userDoc,
        roles: this.userRoles(userDoc.roles)
      })
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
    openEditModal(user) {
      this.clearFlash()
      this.editForm = {
        username: user.username || '',
        email: user.email || '',
        password: '',
        roles: this.userRoles(user.roles),
        newRole: ''
      }
      this.showEditModal = true
    },
    closeEditModal() {
      this.showEditModal = false
      this.submitting = false
      this.formError = ''
      this.resetEditForm()
    },
    async fetchUsers() {
      this.loading = true
      this.error = ''
      try {
        const res = await apiFetch('/api/users')
        const data = await res.json()
        if (!res.ok) {
          this.error = data.message || 'Failed to fetch users.'
          this.users = []
          return
        }

        this.users = Array.isArray(data.users) ? data.users : []
        this.users = this.users.map((user) => ({
          ...user,
          roles: this.userRoles(user.roles)
        }))
      } catch (e) {
        this.error = 'Network error while fetching users.'
        this.users = []
      } finally {
        this.loading = false
      }
    },
    async generateMyApiKey() {
      this.generatingApiKey = true
      this.error = ''
      try {
        const data = await rotateCurrentUserApiKey()
        this.myApiKey = data.apikey || ''
        this.message = data.message || 'API key generated successfully.'
        this.messageType = 'success'
      } catch (e) {
        this.error = e.message || 'Failed to generate API key.'
      } finally {
        this.generatingApiKey = false
      }
    },
    async copyApiKey() {
      if (!this.myApiKey) {
        return
      }

      try {
        await navigator.clipboard.writeText(this.myApiKey)
        this.message = 'API key copied to clipboard.'
        this.messageType = 'success'
      } catch (e) {
        this.error = 'Unable to copy API key. Please copy it manually.'
      }
    },
    async submitCreateUser() {
      if (!this.createForm.username || !this.createForm.password) {
        this.formError = 'Username and password are required.'
        return
      }

      this.submitting = true
      this.formError = ''
      try {
        const res = await apiFetch('/api/users', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            username: this.createForm.username,
            email: this.createForm.email || null,
            password: this.createForm.password
          })
        })
        const data = await res.json()
        if (!res.ok) {
          this.formError = data.message || 'Failed to create user.'
          return
        }

        this.message = data.message || 'User created successfully.'
        this.messageType = 'success'
        this.closeCreateModal()
        await this.fetchUsers()
      } catch (e) {
        this.formError = 'Network error while creating user.'
      } finally {
        this.submitting = false
      }
    },
    async submitEditUser() {
      if (!this.editForm.username) {
        this.formError = 'Username is required.'
        return
      }

      if (!this.editForm.email && !this.editForm.password) {
        this.formError = 'Provide a new email and/or password.'
        return
      }

      this.submitting = true
      this.formError = ''
      try {
        const payload = {}
        if (this.editForm.email !== '') {
          payload.email = this.editForm.email
        }
        if (this.editForm.password) {
          payload.password = this.editForm.password
        }

        const res = await apiFetch(`/api/users/${encodeURIComponent(this.editForm.username)}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        })
        const data = await res.json()
        if (!res.ok) {
          this.formError = data.message || 'Failed to update user.'
          return
        }

        this.message = data.message || 'User updated successfully.'
        this.messageType = 'success'
        if (data.user) {
          this.syncUserInList(data.user)
        }
        this.closeEditModal()
        await this.fetchUsers()
      } catch (e) {
        this.formError = 'Network error while updating user.'
      } finally {
        this.submitting = false
      }
    },
    async grantRoleToEditingUser() {
      if (!this.isAdmin) {
        this.formError = 'Only admins can modify roles.'
        return
      }

      const role = String(this.editForm.newRole || '').trim().toLowerCase()
      if (!role) {
        this.formError = 'Role is required.'
        return
      }

      this.submitting = true
      this.formError = ''
      try {
        const data = await grantUserRole(this.editForm.username, role)
        this.message = data.message || 'Role granted successfully.'
        this.messageType = 'success'
        if (data.user) {
          this.editForm.roles = this.userRoles(data.user.roles)
          this.syncUserInList(data.user)
        }
        this.editForm.newRole = ''
      } catch (e) {
        this.formError = e.message || 'Failed to grant role.'
      } finally {
        this.submitting = false
      }
    },
    async revokeRoleFromEditingUser(role) {
      if (!this.isAdmin) {
        this.formError = 'Only admins can modify roles.'
        return
      }

      const normalizedRole = String(role || '').trim().toLowerCase()
      if (!normalizedRole) {
        return
      }

      this.submitting = true
      this.formError = ''
      try {
        const data = await revokeUserRole(this.editForm.username, normalizedRole)
        this.message = data.message || 'Role revoked successfully.'
        this.messageType = 'success'
        if (data.user) {
          this.editForm.roles = this.userRoles(data.user.roles)
          this.syncUserInList(data.user)
        }
      } catch (e) {
        this.formError = e.message || 'Failed to revoke role.'
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

.role-badge {
  background-color: #495057;
}

.role-remove-btn {
  line-height: 1;
  font-size: 0.75rem;
  text-decoration: none;
}
</style>
