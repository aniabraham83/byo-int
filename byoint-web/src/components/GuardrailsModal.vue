<template>
  <div v-if="isOpen" class="modal-overlay">
    <div class="modal-content" @click.stop>
      <div class="modal-header">
        <h5>Output Guardrails Manager</h5>
        <button type="button" class="btn-close" @click="close"></button>
      </div>

      <div class="modal-body">
        <!-- Add new rule form -->
        <div class="guardrail-form mb-4 p-3 bg-light rounded">
          <h6 class="mb-3">Add New Guardrail Rule</h6>
          <div class="row g-2">
            <div class="col-md-3">
              <select v-model="newRule.action" class="form-select form-select-sm">
                <option value="">Action</option>
                <option value="disallow">Disallow</option>
              </select>
            </div>
            <div class="col-md-3">
              <input v-model="newRule.output_category" type="text" class="form-control form-control-sm" placeholder="Category (e.g., Blocklist)" />
            </div>
            <div class="col-md-2">
              <input v-model="newRule.tag" type="text" class="form-control form-control-sm" placeholder="Tag" />
            </div>
            <div class="col-md-3">
              <input v-model="newRule.description" type="text" class="form-control form-control-sm" placeholder="Description (optional)" />
            </div>
            <div class="col-md-1">
              <button @click="addRule" class="btn btn-sm btn-primary w-100" :disabled="addLoading">
                <span v-if="addLoading" class="spinner-border spinner-border-sm me-1"></span>
                Add
              </button>
            </div>
          </div>
          <div v-if="formError" class="text-danger small mt-2">{{ formError }}</div>
        </div>

        <!-- Guardrails table -->
        <div class="table-responsive">
          <table class="table table-sm table-hover">
            <thead class="table-light">
              <tr>
                <th>Action</th>
                <th>Category</th>
                <th>Tag</th>
                <th>Description</th>
                <th class="text-center" style="width: 80px;">Actions</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="guardrails.length === 0">
                <td colspan="5" class="text-center text-muted py-3">No guardrails configured yet.</td>
              </tr>
              <tr v-for="rule in nonEditingGuardrails" :key="rule._id">
                <td>
                  <span :class="['badge', 'bg-danger']">
                    {{ rule.action }}
                  </span>
                </td>
                <td>{{ rule.output_category }}</td>
                <td><code class="text-primary">{{ rule.tag }}</code></td>
                <td class="text-muted small">{{ rule.description || '—' }}</td>
                <td class="text-center">
                  <button @click="startEdit(rule)" class="btn btn-xs btn-warning me-1" title="Edit">✎</button>
                  <button @click="deleteRule(rule._id)" class="btn btn-xs btn-danger" title="Delete" :disabled="deleting">✕</button>
                </td>
              </tr>

              <!-- Edit row -->
              <tr v-for="rule in editingGuardrails" :key="`edit_${rule._id}`">
                <td>
                  <select v-model="editing[rule._id].action" class="form-select form-select-sm">
                    <option value="disallow">Disallow</option>
                  </select>
                </td>
                <td>
                  <input v-model="editing[rule._id].output_category" type="text" class="form-control form-control-sm" />
                </td>
                <td>
                  <input v-model="editing[rule._id].tag" type="text" class="form-control form-control-sm" />
                </td>
                <td>
                  <input v-model="editing[rule._id].description" type="text" class="form-control form-control-sm" />
                </td>
                <td class="text-center">
                  <button @click="saveEdit(rule._id)" class="btn btn-xs btn-success me-1" :disabled="saving">Save</button>
                  <button @click="cancelEdit(rule._id)" class="btn btn-xs btn-secondary">Cancel</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="modal-footer">
        <button type="button" class="btn btn-secondary" @click="close">Close</button>
      </div>
    </div>
  </div>
</template>

<script>
import { fetchOutputGuardrails, createOutputGuardrail, updateOutputGuardrail, deleteOutputGuardrail } from '@/api'

export default {
  name: 'GuardrailsModal',
  props: {
    isOpen: { type: Boolean, default: false }
  },
  data() {
    return {
      guardrails: [],
      newRule: {
        action: 'disallow',
        output_category: '',
        tag: '',
        description: ''
      },
      editing: {},
      addLoading: false,
      formError: '',
      saving: false,
      deleting: false,
      loading: false,
      openedAt: 0
    }
  },
  watch: {
    isOpen(val) {
      if (val) {
        this.openedAt = Date.now()
        this.loadGuardrails()
      }
    }
  },
  computed: {
    nonEditingGuardrails() {
      return this.guardrails.filter(rule => !this.isEditing(rule._id))
    },
    editingGuardrails() {
      return this.guardrails.filter(rule => this.isEditing(rule._id))
    }
  },
  methods: {
    async loadGuardrails() {
      this.loading = true
      try {
        this.guardrails = await fetchOutputGuardrails()
      } catch (e) {
        console.error('Failed to load guardrails:', e)
      } finally {
        this.loading = false
      }
    },

    async addRule() {
      this.formError = ''

      if (!this.newRule.action) {
        this.formError = 'Action is required'
        return
      }
      if (!this.newRule.output_category) {
        this.formError = 'Category is required'
        return
      }
      if (!this.newRule.tag) {
        this.formError = 'Tag is required'
        return
      }

      this.addLoading = true
      try {
        const rule = await createOutputGuardrail(this.newRule)
        this.guardrails.push(rule)
        this.newRule = { action: 'disallow', output_category: '', tag: '', description: '' }
      } catch (e) {
        this.formError = e.message
      } finally {
        this.addLoading = false
      }
    },

    startEdit(rule) {
      this.editing[rule._id] = { ...rule }
    },

    isEditing(ruleId) {
      return ruleId in this.editing
    },

    async saveEdit(ruleId) {
      this.saving = true
      try {
        const updates = this.editing[ruleId]
        await updateOutputGuardrail(ruleId, updates)
        const idx = this.guardrails.findIndex(r => r._id === ruleId)
        if (idx >= 0) {
          this.guardrails[idx] = { ...updates, _id: ruleId }
        }
        delete this.editing[ruleId]
      } catch (e) {
        alert(`Failed to update: ${e.message}`)
      } finally {
        this.saving = false
      }
    },

    cancelEdit(ruleId) {
      delete this.editing[ruleId]
    },

    async deleteRule(ruleId) {
      if (!confirm('Delete this guardrail rule?')) return

      this.deleting = true
      try {
        await deleteOutputGuardrail(ruleId)
        this.guardrails = this.guardrails.filter(r => r._id !== ruleId)
      } catch (e) {
        alert(`Failed to delete: ${e.message}`)
      } finally {
        this.deleting = false
      }
    },

    close() {
      if (Date.now() - this.openedAt < 200) {
        return
      }
      this.$emit('close')
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
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal-content {
  background: white;
  border-radius: 8px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
  max-width: 900px;
  width: 90%;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px;
  border-bottom: 1px solid #dee2e6;
}

.modal-header h5 {
  margin: 0;
}

.modal-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 16px;
  border-top: 1px solid #dee2e6;
}

.guardrail-form {
  border: 1px solid #dee2e6;
}

.btn-xs {
  padding: 0.25rem 0.5rem;
  font-size: 0.75rem !important;
}

.table-responsive {
  max-height: 50vh;
  overflow-y: auto;
}

table code {
  font-size: 0.85em;
}

.btn-close {
  padding: 0.25rem 0.5rem;
  cursor: pointer;
  background: none;
  border: none;
  font-size: 1.25rem;
  color: #888;
}

.btn-close:hover {
  color: #333;
}
</style>
