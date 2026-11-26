<template>
  <div class="container mt-4 pb-5">
    <div class="d-flex justify-content-between align-items-center mb-4">
      <div>
        <h2 class="mb-1">Indicator Detail</h2>
        <p class="text-muted mb-0">Detailed view for a single indicator and its source metadata.</p>
      </div>
      <div class="d-flex gap-2">
        <router-link to="/indicators" class="btn btn-outline-secondary">Back to Indicators</router-link>
        <button
          v-if="indicator"
          class="btn btn-outline-success"
          @click="openEnrichmentSelectModal"
          :disabled="enriching"
        >
          <span v-if="enriching" class="spinner-border spinner-border-sm me-1"></span>
          🧬 Run Enrichments
        </button>
        <button class="btn btn-primary" @click="fetchIndicatorDetail" :disabled="loading">
          <span v-if="loading" class="spinner-border spinner-border-sm me-2"></span>
          Refresh
        </button>
      </div>
    </div>

    <div v-if="loading" class="mt-3">
      <div class="spinner-border text-primary" role="status">
        <span class="visually-hidden">Loading...</span>
      </div>
    </div>

    <div v-else-if="error" class="alert alert-danger">{{ error }}</div>

    <div v-else-if="!indicator" class="alert alert-info">Indicator not found.</div>

    <div v-if="showEnrichmentSelectModal" class="modal-overlay" @click.self="closeEnrichmentSelectModal">
      <div class="modal-content" style="max-width:520px;">
        <div class="modal-header">
          <h5 class="modal-title">Select Enrichments</h5>
          <button type="button" class="btn-close" @click="closeEnrichmentSelectModal"></button>
        </div>
        <div class="modal-body">
          <input
            v-model="enrichmentSearchQuery"
            type="text"
            class="form-control mb-2"
            placeholder="Search enrichments..."
          >
          <div class="border rounded p-2" style="max-height:220px; overflow-y:auto;">
            <div v-if="filteredEnrichmentOptions.length === 0" class="text-muted small">No enrichments found.</div>
            <div v-for="enrichment in filteredEnrichmentOptions" :key="enrichment.enrich_name" class="form-check">
              <input
                :id="`detail_enrich_${enrichment.enrich_name}`"
                v-model="selectedEnrichmentNames"
                class="form-check-input"
                type="checkbox"
                :value="enrichment.enrich_name"
              >
              <label class="form-check-label" :for="`detail_enrich_${enrichment.enrich_name}`">{{ enrichment.enrich_name }}</label>
            </div>
          </div>
          <div v-if="selectedEnrichmentNames.length" class="mt-2 d-flex flex-wrap gap-1">
            <span v-for="name in selectedEnrichmentNames" :key="`detail_selected_${name}`" class="badge bg-secondary d-inline-flex align-items-center">
              {{ name }}
              <button type="button" class="btn-close btn-close-white ms-1" style="font-size:0.6rem;" @click="selectedEnrichmentNames = selectedEnrichmentNames.filter(n => n !== name)"></button>
            </span>
            <button type="button" class="btn btn-sm btn-outline-secondary" @click="selectedEnrichmentNames = []">Clear all</button>
          </div>
          <div class="form-text mt-2">Pick one or more enrichments to run for this indicator.</div>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" @click="closeEnrichmentSelectModal">Cancel</button>
          <button type="button" class="btn btn-success" @click="runSelectedEnrichments" :disabled="selectedEnrichmentNames.length === 0 || runningSelectedEnrichment">
            <span v-if="runningSelectedEnrichment" class="spinner-border spinner-border-sm me-1"></span>
            Run
          </button>
        </div>
      </div>
    </div>

    <div v-else>
      <div class="row g-3 mb-4">
        <div class="col-md-6">
          <div class="card h-100">
            <div class="card-header"><strong>Core Info</strong></div>
            <div class="card-body">
              <div class="mb-2"><strong>Value:</strong> <span class="text-break">{{ indicator.value }}</span></div>
              <div class="mb-2"><strong>Type:</strong> {{ indicator.type || '-' }}</div>
              <div class="mb-2"><strong>Active:</strong>
                <span v-if="indicator.active" class="badge bg-success">Yes</span>
                <span v-else class="badge bg-secondary">No</span>
              </div>
              <div class="mb-2"><strong>Max BR Score:</strong> {{ indicator.max_br_score ?? '-' }}</div>
              <div class="mb-2"><strong>Source Count:</strong> {{ indicator.source_count ?? 0 }}</div>
              <div class="mb-0"><strong>Last Seen:</strong> {{ formatDate(indicator.last_seen) }}</div>
            </div>
          </div>
        </div>

        <div class="col-md-6">
          <div class="card h-100">
            <div class="card-header"><strong>Query Context</strong></div>
            <div class="card-body">
              <div class="mb-2"><strong>Lookup Value:</strong> <span class="text-break">{{ lookup.value || '-' }}</span></div>
              <div class="mb-2"><strong>Lookup Type:</strong> {{ lookup.type || '-' }}</div>
              <div class="mb-0 text-muted small">Tip: open this page from the Indicators list to prefill query parameters.</div>
            </div>
          </div>
        </div>
      </div>

      <div v-if="indicator.enrichment_data && Object.keys(indicator.enrichment_data).length" class="card mb-3">
        <div class="card-header d-flex justify-content-between align-items-center">
          <strong>🧬 Enrichment Data</strong>
          <span class="badge bg-success">{{ Object.keys(indicator.enrichment_data).length }} field(s)</span>
        </div>
        <div class="card-body">
          <div class="row g-2">
            <div v-for="(val, key) in indicator.enrichment_data" :key="key" class="col-md-4 col-sm-6">
              <div class="border rounded p-2 h-100 bg-light">
                <div class="text-muted small text-uppercase fw-semibold mb-1" style="font-size:0.7rem;letter-spacing:0.05em;">{{ key }}</div>
                <div class="fw-medium">{{ val && val.value !== null && val.value !== undefined && val.value !== '' ? val.value : '—' }}</div>
                <div class="text-muted small mt-1">Updated: {{ formatDate(val ? val.updated_at : null) }}</div>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div v-else-if="indicator" class="card mb-3">
        <div class="card-header d-flex justify-content-between align-items-center">
          <strong>🧬 Enrichment Data</strong>
          <span class="badge bg-secondary">None</span>
        </div>
        <div class="card-body text-muted small">
          No enrichment data yet. Click <strong>Run Enrichments</strong> to apply configured enrichments for this indicator type.
        </div>
      </div>

      <div v-if="enrichMessage" class="alert mb-3" :class="enrichError ? 'alert-danger' : 'alert-success'" style="position:relative;">
        {{ enrichMessage }}
        <button type="button" class="btn-close" style="position:absolute;right:0.75rem;top:0.75rem;font-size:0.75rem;" @click="enrichMessage=''"></button>
      </div>

      <div class="card">
        <div class="card-header"><strong>Sources</strong></div>
        <div class="card-body p-0">
          <div v-if="!Array.isArray(indicator.sources) || indicator.sources.length === 0" class="p-3 text-muted">No sources available for this indicator.</div>
          <div v-if="tagEditor.error" class="px-3 pt-3">
            <div class="alert alert-danger py-2 mb-0">{{ tagEditor.error }}</div>
          </div>
          <div v-else class="table-responsive">
            <table class="table table-striped table-hover mb-0">
              <thead class="table-light">
                <tr>
                  <th>Source Name</th>
                  <th>Last Update Time</th>
                  <th>Last Status</th>
                  <th>BR Score</th>
                  <th>Tag</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(source, index) in indicator.sources" :key="`${source.source_name || 'source'}_${index}`">
                  <td>{{ source.source_name || '-' }}</td>
                  <td>{{ formatDate(source.lastupdate_time) }}</td>
                  <td>
                    <span v-if="source.last_update_status === true" class="badge bg-success">Active</span>
                    <span v-else-if="source.last_update_status === false" class="badge bg-secondary">Inactive</span>
                    <span v-else class="badge bg-light text-dark">Unknown</span>
                  </td>
                  <td>{{ source.br_score ?? '-' }}</td>
                  <td>
                    <div v-if="isEditingSourceTag(source)" class="d-flex gap-2 align-items-center">
                      <div class="w-100">
                        <div v-if="tagEditor.tags.length" class="d-flex flex-wrap gap-1 mb-2">
                          <span v-for="tag in tagEditor.tags" :key="tag" class="badge bg-warning text-dark d-inline-flex align-items-center">
                            {{ tag }}
                            <button type="button" class="btn-close ms-1" style="font-size:0.55rem;" @click="removeTagFromEditor(tag)"></button>
                          </span>
                        </div>
                        <div class="d-flex gap-2">
                          <select v-model="tagEditor.selectedTag" class="form-select form-select-sm">
                            <option value="">-- Select Tag --</option>
                            <option v-for="tag in availableTags.filter(t => !tagEditor.tags.includes(t))" :key="tag" :value="tag">{{ tag }}</option>
                          </select>
                          <button type="button" class="btn btn-sm btn-outline-secondary" @click="addTagToEditor">Add</button>
                        </div>
                      </div>
                    </div>
                    <div v-else>
                      <span v-if="getSourceTags(source).length === 0">-</span>
                      <span v-else class="d-flex flex-wrap gap-1">
                        <span v-for="tag in getSourceTags(source)" :key="tag" class="badge bg-warning text-dark">{{ tag }}</span>
                      </span>
                    </div>
                  </td>
                  <td>
                    <div v-if="isEditingSourceTag(source)" class="d-flex gap-2">
                      <button type="button" class="btn btn-sm btn-success" @click="saveTagEdit" :disabled="tagEditor.saving">
                        <span v-if="tagEditor.saving" class="spinner-border spinner-border-sm me-1"></span>
                        Save Tags
                      </button>
                      <button type="button" class="btn btn-sm btn-outline-secondary" @click="cancelTagEdit" :disabled="tagEditor.saving">Cancel</button>
                    </div>
                    <button v-else type="button" class="btn btn-sm btn-outline-primary" @click="startTagEdit(source)">Manage Tags</button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { apiFetch } from '@/api'

export default {
  name: 'IndicatorDetailPage',
  computed: {
    filteredEnrichmentOptions() {
      const q = this.enrichmentSearchQuery.toLowerCase()
      if (!q) return this.enrichmentOptions
      return this.enrichmentOptions.filter(e => String(e.enrich_name || '').toLowerCase().includes(q))
    }
  },
  data() {
    return {
      loading: false,
      error: '',
      indicator: null,
      lookup: {
        value: '',
        type: ''
      },
      enriching: false,
      enrichMessage: '',
      enrichError: false,
      enrichmentOptions: [],
      showEnrichmentSelectModal: false,
      enrichmentSearchQuery: '',
      selectedEnrichmentNames: [],
      runningSelectedEnrichment: false,
      availableTags: [],
      tagEditor: {
        sourceName: '',
        tags: [],
        selectedTag: '',
        saving: false,
        error: ''
      }
    }
  },
  async mounted() {
    this.syncLookupFromRoute()
    await this.fetchEnrichmentOptions()
    await this.fetchAvailableTags()
    await this.fetchIndicatorDetail()
  },
  watch: {
    '$route.query': {
      immediate: false,
      async handler() {
        this.syncLookupFromRoute()
        await this.fetchIndicatorDetail()
      }
    }
  },
  methods: {
    async fetchAvailableTags() {
      try {
        const res = await apiFetch('/api/tags')
        if (!res.ok) {
          this.availableTags = []
          return
        }
        const data = await res.json()
        this.availableTags = Array.isArray(data.tags)
          ? data.tags.map(t => String(t.tag || '').trim()).filter(Boolean)
          : []
      } catch (e) {
        this.availableTags = []
      }
    },
    async fetchEnrichmentOptions() {
      try {
        const res = await apiFetch('/api/data_enrichments')
        if (!res.ok) {
          this.enrichmentOptions = []
          return
        }
        const data = await res.json()
        const enrichments = Array.isArray(data.enrichments)
          ? data.enrichments
          : (Array.isArray(data.data_enrichments) ? data.data_enrichments : [])
        this.enrichmentOptions = enrichments.filter(e => !!e.enabled)
      } catch (e) {
        this.enrichmentOptions = []
      }
    },
    openEnrichmentSelectModal() {
      this.enrichmentSearchQuery = ''
      this.selectedEnrichmentNames = []
      this.showEnrichmentSelectModal = true
    },
    isEditingSourceTag(source) {
      return this.tagEditor.sourceName && this.tagEditor.sourceName === source.source_name
    },
    getSourceTags(source) {
      const rawTags = source && (source.tag ?? source.tags)
      if (Array.isArray(rawTags)) {
        return rawTags.map(tag => String(tag).trim()).filter(Boolean)
      }
      if (rawTags === null || rawTags === undefined || rawTags === '') {
        return []
      }
      return String(rawTags)
        .split(',')
        .map(tag => tag.trim())
        .filter(Boolean)
    },
    startTagEdit(source) {
      this.tagEditor = {
        sourceName: String(source.source_name || '').trim(),
        tags: this.getSourceTags(source),
        selectedTag: '',
        saving: false,
        error: ''
      }
    },
    cancelTagEdit() {
      this.tagEditor = {
        sourceName: '',
        tags: [],
        selectedTag: '',
        saving: false,
        error: ''
      }
    },
    addTagToEditor() {
      const newTag = String(this.tagEditor.selectedTag || '').trim()
      if (!newTag) {
        return
      }
      if (!this.tagEditor.tags.includes(newTag)) {
        this.tagEditor.tags = [...this.tagEditor.tags, newTag]
      }
      this.tagEditor.selectedTag = ''
    },
    removeTagFromEditor(tagName) {
      this.tagEditor.tags = this.tagEditor.tags.filter(tag => tag !== tagName)
    },
    async saveTagEdit() {
      if (!this.indicator || !this.tagEditor.sourceName) {
        return
      }

      this.tagEditor.saving = true
      this.tagEditor.error = ''
      try {
        const res = await apiFetch('/api/indicators/tag', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            value: this.indicator.value,
            type: this.indicator.type,
            source_name: this.tagEditor.sourceName,
             tags: this.tagEditor.tags
          })
        })
        const data = await res.json().catch(() => ({}))
        if (!res.ok) {
          this.tagEditor.error = data.message || 'Failed to update tag.'
          return
        }

        this.cancelTagEdit()
        await this.fetchIndicatorDetail()
      } catch (e) {
        this.tagEditor.error = 'Network error while updating tag.'
      } finally {
        this.tagEditor.saving = false
      }
    },
    closeEnrichmentSelectModal() {
      this.showEnrichmentSelectModal = false
      this.enrichmentSearchQuery = ''
      this.selectedEnrichmentNames = []
    },
    async runSelectedEnrichments() {
      if (!this.selectedEnrichmentNames.length) return
      await this.runEnrichments([...this.selectedEnrichmentNames])
      if (!this.enrichError) {
        this.closeEnrichmentSelectModal()
      }
    },
    syncLookupFromRoute() {
      this.lookup.value = String(this.$route.query.value || '').trim()
      this.lookup.type = String(this.$route.query.type || '').trim()
    },
    formatDate(value) {
      if (!value) return '-'
      const date = new Date(value)
      if (Number.isNaN(date.getTime())) return String(value)
      return date.toLocaleString()
    },
    async runEnrichments(selectedEnrichments = []) {
      if (!this.indicator) return
      this.enriching = true
      this.runningSelectedEnrichment = true
      this.enrichMessage = ''
      this.enrichError = false
      try {
        const res = await apiFetch('/api/indicators/enrich', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ value: this.indicator.value, type: this.indicator.type, selected_enrichments: selectedEnrichments })
        })
        const data = await res.json()
        this.enrichError = !res.ok
        this.enrichMessage = data.message || (res.ok ? 'Enrichment applied.' : 'Error running enrichments.')
        if (res.ok) await this.fetchIndicatorDetail()
      } catch (e) {
        this.enrichError = true
        this.enrichMessage = 'Network error while running enrichments.'
      } finally {
        this.enriching = false
        this.runningSelectedEnrichment = false
      }
    },
    async fetchIndicatorDetail() {
      if (!this.lookup.value) {
        this.error = 'Missing indicator value in query parameters.'
        this.indicator = null
        return
      }

      this.loading = true
      this.error = ''
      try {
        const params = new URLSearchParams({ value: this.lookup.value })
        if (this.lookup.type) {
          params.append('type', this.lookup.type)
        }

        const res = await apiFetch(`/api/indicators/detail?${params.toString()}`)
        const data = await res.json()

        if (!res.ok) {
          this.error = data.message || 'Failed to fetch indicator detail.'
          this.indicator = null
          return
        }

        this.indicator = data.indicator || null
      } catch (e) {
        this.error = 'Network error while fetching indicator detail.'
        this.indicator = null
      } finally {
        this.loading = false
      }
    }
  }
}
</script>

<style scoped>
.card-header {
  background-color: #f8f9fa;
}
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
  max-width: 600px;
  width: 90%;
  max-height: 90vh;
  overflow-y: auto;
}
.modal-header {
  padding: 1.5rem;
  border-bottom: 1px solid #e9ecef;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.modal-title {
  font-size: 1.25rem;
  font-weight: 600;
  margin: 0;
}
.btn-close {
  background: none;
  border: none;
  font-size: 1.5rem;
  cursor: pointer;
  color: #666;
}
.btn-close:hover {
  color: #000;
}
.modal-body {
  padding: 1.5rem;
}
.modal-footer {
  padding: 1.5rem;
  border-top: 1px solid #e9ecef;
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
}
</style>
