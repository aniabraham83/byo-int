<template>
  <div class="container mt-4 pb-5">
    <div class="d-flex justify-content-between align-items-center mb-4">
      <div>
        <h2 class="mb-1">Outputs</h2>
        <p class="text-muted">View records from byoint_core_data.outputs</p>
      </div>
      <div class="d-flex gap-2">
        <router-link to="/outputs-details" class="btn btn-outline-info">
          View Output Details
        </router-link>
        <button class="btn btn-warning" @click.stop="openGuardrailsModal">
          🛡️ Guardrails
        </button>
        <button class="btn btn-success" @click="openAddModal">
          <i class="me-2">+</i> New Output
        </button>
        <button class="btn btn-primary" @click="fetchOutputs" :disabled="loading">
          <span v-if="loading" class="spinner-border spinner-border-sm me-2"></span>
          Refresh
        </button>
      </div>
    </div>

    <!-- Guardrails Modal -->
    <guardrails-modal :is-open="showGuardrailsModal" @close="showGuardrailsModal = false" />

    <!-- Add Output Modal -->
    <div v-if="showAddModal" class="modal-overlay" @click.self="closeAddModal">
      <div class="modal-content" style="max-width: 520px;">
        <div class="modal-header">
          <h5 class="modal-title">Create New Output</h5>
          <button type="button" class="btn-close" @click="closeAddModal"></button>
        </div>
        <div class="modal-body">
          <form @submit.prevent="submitNewOutput">
            <div class="mb-3">
              <label class="form-label">Name</label>
              <input v-model="newOutput.name" type="text" class="form-control" required>
            </div>
            <div class="mb-3">
              <label class="form-label">Source Type</label>
              <select v-model="newOutput.output_sourcetype" class="form-select" required @change="onOutputSourceTypeChange">
                <option value="">-- Select Source Type --</option>
                <option v-for="type in outputSourceTypeOptions" :key="type" :value="type">{{ type }}</option>
              </select>
            </div>
            <div class="mb-3">
              <label class="form-label">Sources</label>
              <input
                v-model="sourceSearchQuery"
                type="text"
                class="form-control mb-2"
                placeholder="Search sources..."
                :disabled="!newOutput.output_sourcetype"
              >
              <div class="border rounded p-2" style="max-height: 180px; overflow-y: auto;">
                <div v-if="!newOutput.output_sourcetype" class="text-muted small">
                  Select Source Type first.
                </div>
                <div v-else-if="filteredAvailableSources.length === 0" class="text-muted small">
                  No sources found.
                </div>
                <div v-else>
                  <div v-for="source in filteredAvailableSources" :key="source" class="form-check">
                    <input
                      :id="`source_${source}`"
                      v-model="newOutput.source_name"
                      class="form-check-input"
                      type="checkbox"
                      :value="source"
                    >
                    <label class="form-check-label" :for="`source_${source}`">{{ source }}</label>
                  </div>
                </div>
              </div>
              <div v-if="newOutput.source_name.length" class="mt-2 d-flex flex-wrap gap-2">
                <span v-for="source in newOutput.source_name" :key="`selected_${source}`" class="badge bg-secondary d-inline-flex align-items-center">
                  {{ source }}
                  <button type="button" class="btn-close btn-close-white ms-2" style="font-size: 0.6rem;" aria-label="Remove" @click="removeSelectedSource(source)"></button>
                </span>
                <button type="button" class="btn btn-sm btn-outline-secondary" @click="clearSelectedSources">
                  Clear all
                </button>
              </div>
              <div class="form-text" v-if="!newOutput.output_sourcetype">Select Source Type first.</div>
              <div class="form-text" v-else>Select one or more sources.</div>
            </div>
            <div class="mb-3">
              <label class="form-label">Type</label>
              <select v-model="newOutput.type" class="form-select" required @change="onOutputTypeChange">
                <option value="">-- Select Output Type --</option>
                <option value="edl_feed">edl_feed</option>
                <option value="json">json</option>
                <option value="mcp">mcp</option>
              </select>
              <div class="form-text">Use <strong>edl_feed</strong> for plain-text EDL output, <strong>json</strong> for authenticated JSON output, or <strong>mcp</strong> to expose the feed as an authenticated MCP server for AI agents.</div>
            </div>
            <div class="mb-3">
              <label class="form-label">Output Category</label>
              <div class="input-group">
                <select v-model="newOutput.output_category" class="form-select">
                  <option v-for="category in outputCategoryOptions" :key="category" :value="category">{{ category }}</option>
                </select>
                <button type="button" class="btn btn-outline-secondary" @click="toggleAddCategoryInput">
                  {{ showAddCategoryInput ? 'Cancel' : 'New' }}
                </button>
              </div>
              <div class="form-text">Choose an existing category or click New to add one from core basicconfigs.</div>
              <div v-if="showAddCategoryInput" class="mt-2">
                <div class="input-group input-group-sm">
                  <input v-model="newOutputCategory" type="text" class="form-control" placeholder="New output category">
                  <button type="button" class="btn btn-outline-primary" @click="submitNewOutputCategory" :disabled="addCategoryLoading">
                    <span v-if="addCategoryLoading" class="spinner-border spinner-border-sm me-1"></span>
                    Add
                  </button>
                </div>
                <div v-if="addCategoryError" class="text-danger small mt-1">{{ addCategoryError }}</div>
              </div>
            </div>
            <div class="mb-3">
              <label class="form-label">Filter Search</label>
              <div class="form-check mb-2">
                <input v-model="useFilterBuilder" class="form-check-input" type="checkbox" id="useFilterBuilder">
                <label class="form-check-label" for="useFilterBuilder">Use filter builder (type-based)</label>
              </div>

              <div v-if="useFilterBuilder" class="border rounded p-2 mb-2">
                <div v-if="!newOutput.source_name || newOutput.source_name.length === 0" class="text-muted small py-1">
                  Select one or more sources above to see applicable filter options.
                </div>
                <div v-else>
                  <div class="row g-2">
                    <div class="col-12">
                      <label class="form-label small mb-1">Filter Types (AND)</label>
                      <div class="d-flex flex-wrap gap-3">
                        <div class="form-check">
                          <input
                            id="builder_filtertype_enrichment"
                            v-model="filterBuilder.selectedFilterTypes"
                            class="form-check-input"
                            type="checkbox"
                            value="enrichment"
                            @change="onFilterTypesChange"
                          >
                          <label class="form-check-label small" for="builder_filtertype_enrichment">Data Enrichment</label>
                        </div>
                        <div class="form-check">
                          <input
                            id="builder_filtertype_tag"
                            v-model="filterBuilder.selectedFilterTypes"
                            class="form-check-input"
                            type="checkbox"
                            value="tag"
                            @change="onFilterTypesChange"
                          >
                          <label class="form-check-label small" for="builder_filtertype_tag">Source Tag</label>
                        </div>
                        <div class="form-check">
                          <input
                            id="builder_filtertype_brscore"
                            v-model="filterBuilder.selectedFilterTypes"
                            class="form-check-input"
                            type="checkbox"
                            value="br_score"
                            @change="onFilterTypesChange"
                          >
                          <label class="form-check-label small" for="builder_filtertype_brscore">BR Score</label>
                        </div>
                      </div>
                    </div>
                  </div>

                  <div v-if="filterBuilder.selectedFilterTypes.includes('enrichment')" class="mt-2">
                    <label class="form-label small mb-1">Available Enrichments (optional)</label>
                    <div class="border rounded p-2" style="max-height: 170px; overflow-y: auto;">
                      <div v-if="enrichmentFilterOptions.length === 0" class="text-muted small">No available enrichments found for selected sources.</div>
                      <div v-else>
                        <div v-for="enrichment in enrichmentFilterOptions" :key="`builder_enrichment_name_${enrichment}`" class="form-check">
                          <input
                            :id="`builder_enrichment_name_${enrichment}`"
                            v-model="filterBuilder.selectedEnrichmentNames"
                            class="form-check-input"
                            type="checkbox"
                            :value="enrichment"
                            @change="onSelectedEnrichmentsChange"
                          >
                          <label class="form-check-label small" :for="`builder_enrichment_name_${enrichment}`">{{ enrichment }}</label>
                        </div>
                      </div>
                    </div>
                  </div>

                  <div v-if="filterBuilder.selectedFilterTypes.includes('enrichment')" class="mt-2">
                    <label class="form-label small mb-1">Enrichment Values (optional)</label>
                    <div v-if="filterBuilder.selectedEnrichmentNames.length === 0" class="text-muted small">Select one or more enrichments to view values.</div>
                    <div v-else class="border rounded p-2" style="max-height: 170px; overflow-y: auto;">
                      <div v-if="filteredEnrichmentValueOptions.length === 0" class="text-muted small">No enrichment values found for selected enrichments.</div>
                      <div v-else>
                        <div v-for="option in filteredEnrichmentValueOptions" :key="`builder_enrichment_value_${option}`" class="form-check">
                          <input
                            :id="`builder_enrichment_value_${option}`"
                            v-model="filterBuilder.selectedEnrichmentValues"
                            class="form-check-input"
                            type="checkbox"
                            :value="option"
                            @change="applyFilterBuilder"
                          >
                          <label class="form-check-label small" :for="`builder_enrichment_value_${option}`">{{ option }}</label>
                        </div>
                      </div>
                    </div>
                  </div>

                  <div v-if="filterBuilder.selectedFilterTypes.includes('tag')" class="mt-2">
                    <label class="form-label small mb-1">Source Tags (include)</label>
                    <div class="border rounded p-2" style="max-height: 170px; overflow-y: auto;">
                      <div v-if="tagOptions.length === 0" class="text-muted small">No source tags found for selected sources.</div>
                      <div v-else>
                        <div v-for="option in tagOptions" :key="`builder_tag_option_${option}`" class="form-check">
                          <input
                            :id="`builder_tag_option_${option}`"
                            v-model="filterBuilder.selectedTags"
                            class="form-check-input"
                            type="checkbox"
                            :value="option"
                            @change="onIncludedTagChange(option)"
                          >
                          <label class="form-check-label small" :for="`builder_tag_option_${option}`">{{ option }}</label>
                        </div>
                      </div>
                    </div>
                  </div>

                  <div v-if="filterBuilder.selectedFilterTypes.includes('tag')" class="mt-2">
                    <label class="form-label small mb-1">Source Tags (exclude / NOT)</label>
                    <div class="border rounded p-2" style="max-height: 170px; overflow-y: auto;">
                      <div v-if="tagOptions.length === 0" class="text-muted small">No source tags found for selected sources.</div>
                      <div v-else>
                        <div v-for="option in tagOptions" :key="`builder_tag_exclude_option_${option}`" class="form-check">
                          <input
                            :id="`builder_tag_exclude_option_${option}`"
                            v-model="filterBuilder.excludedTags"
                            class="form-check-input"
                            type="checkbox"
                            :value="option"
                            @change="onExcludedTagChange(option)"
                          >
                          <label class="form-check-label small" :for="`builder_tag_exclude_option_${option}`">NOT {{ option }}</label>
                        </div>
                      </div>
                    </div>
                  </div>

                  <div v-if="filterBuilder.selectedFilterTypes.includes('br_score')" class="mt-2">
                    <label class="form-label small mb-1">BR Scores (optional)</label>
                    <div class="border rounded p-2" style="max-height: 170px; overflow-y: auto;">
                      <div v-if="brScoreOptions.length === 0" class="text-muted small">No BR scores found for selected sources.</div>
                      <div v-else>
                        <div v-for="option in brScoreOptions" :key="`builder_brscore_option_${option}`" class="form-check">
                          <input
                            :id="`builder_brscore_option_${option}`"
                            v-model="filterBuilder.selectedBrScores"
                            class="form-check-input"
                            type="checkbox"
                            :value="option"
                            @change="applyFilterBuilder"
                          >
                          <label class="form-check-label small" :for="`builder_brscore_option_${option}`">{{ option }}</label>
                        </div>
                      </div>
                    </div>
                  </div>

                <div class="d-flex align-items-center gap-2 mt-2">
                  <button type="button" class="btn btn-sm btn-outline-primary" @click="applyFilterBuilder">
                    Generate Filter
                  </button>
                  <button type="button" class="btn btn-sm btn-outline-dark" @click="toggleMongoQueryPreview">
                    {{ showMongoQueryPreview ? 'Hide Mongo Query' : 'Show Mongo Query' }}
                  </button>
                  <button type="button" class="btn btn-sm btn-outline-secondary" @click="clearFilterBuilderSelections">
                    Clear Builder
                  </button>
                  <span class="small text-muted" v-if="filterBuilderSelectionCount > 0">
                    Selected {{ filterBuilderSelectionCount }} criteria
                  </span>
                </div>

                <div v-if="showMongoQueryPreview" class="mt-2">
                  <label class="form-label small mb-1">Mongo Query Preview (indicators)</label>
                  <div v-if="mongoQueryPreviewLoading" class="text-muted small">Loading query preview...</div>
                  <div v-else-if="mongoQueryPreviewError" class="text-danger small">{{ mongoQueryPreviewError }}</div>
                  <pre v-else class="small border rounded p-2 mb-0" style="max-height: 220px; overflow:auto; background:#f8f9fa;">{{ mongoQueryPreviewText }}</pre>
                </div>
                </div><!-- end v-else (sources selected) -->
              </div>

              <textarea
                v-model="newOutput.filter_search"
                class="form-control"
                rows="3"
                placeholder="Optional filter string or JSON"
              ></textarea>
              <div class="form-text">Builder generates selected_enrichments (+ optional selected_enrichment_values), selected_tags, selected_tags_not, and selected_br_scores.</div>
            </div>
            <div class="mb-3">
              <label class="form-label">Enabled</label>
              <div class="form-check">
                <input v-model="newOutput.enabled" type="checkbox" class="form-check-input" id="newOutputEnabled">
                <label class="form-check-label" for="newOutputEnabled">Enabled</label>
              </div>
            </div>
            <div class="mb-3">
              <label class="form-label">Feed Authentication</label>
              <div class="form-check">
                <input v-model="newOutput.feed_authentication_status" type="checkbox" class="form-check-input" id="newOutputFeedAuth" :disabled="requiresFeedAuth(newOutput.type)">
                <label class="form-check-label" for="newOutputFeedAuth">Require authentication to access this feed</label>
              </div>
              <div class="form-text">
                <span v-if="newOutput.type === 'json'">JSON feeds always require a valid API key.</span>
                <span v-else-if="newOutput.type === 'mcp'">MCP outputs always require a valid API key (sent as a Bearer token).</span>
                <span v-else>When enabled, the <code>/feeds/</code> URL for this output will require a valid API key.</span>
              </div>
            </div>
          </form>
          <div v-if="addError" class="alert alert-danger mt-2 mb-0">{{ addError }}</div>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" @click="closeAddModal">Cancel</button>
          <button type="button" class="btn btn-primary" @click="submitNewOutput" :disabled="addLoading">
            <span v-if="addLoading" class="spinner-border spinner-border-sm me-2"></span>
            {{ addLoading ? 'Creating...' : 'Create Output' }}
          </button>
        </div>
      </div>
    </div>

    <div v-if="loading" class="mt-3">
      <div class="spinner-border text-primary" role="status">
        <span class="visually-hidden">Loading...</span>
      </div>
    </div>

    <div v-else-if="error" class="alert alert-danger">
      {{ error }}
    </div>

    <div v-else>
      <div v-if="outputs.length === 0" class="alert alert-info">
        No output records found.
      </div>

      <div v-else class="table-responsive">
        <table class="table table-striped table-hover">
          <thead class="table-light">
            <tr>
              <th>Name</th>
              <th>Source</th>
              <th>Source Type</th>
              <th>Type</th>
              <th>Filter Search</th>
              <th>Enabled</th>
              <th>Feed Auth</th>
              <th>Details</th>
              <th>Feed</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in outputs" :key="row._id || row.creation_time || JSON.stringify(row)">
              <td><strong>{{ row.name || '-' }}</strong></td>
              <td><strong>{{ formatSourceDisplay(row) }}</strong></td>
              <td>{{ row.output_sourcetype || '-' }}</td>
              <td><span class="badge bg-info">{{ row.type || row.output_type || '-' }}</span></td>
              <td>{{ row.filter_search || '-' }}</td>
              <td>
                <span v-if="row.enabled" class="badge bg-success">Yes</span>
                <span v-else class="badge bg-secondary">No</span>
              </td>
              <td>
                <span v-if="row.feed_authentication_status" class="badge bg-warning text-dark">Required</span>
                <span v-else class="badge bg-secondary">None</span>
              </td>
              <td>
                <router-link
                  :to="{ path: '/outputs-details', query: { name: row.name || '' } }"
                  class="btn btn-sm btn-outline-primary"
                >
                  View
                </router-link>
              </td>
              <td>
                <button
                  v-if="row.name && row.type === 'mcp'"
                  type="button"
                  class="btn btn-sm btn-outline-success"
                  :title="mcpUrl(row.name)"
                  @click="copyMcpUrl(row.name)"
                >
                  {{ copiedMcpName === row.name ? 'Copied!' : 'Copy MCP URL' }}
                </button>
                <a
                  v-else-if="row.name"
                  :href="feedUrl(row.name)"
                  class="btn btn-sm btn-outline-success"
                  target="_blank"
                  rel="noopener"
                >
                  Open Feed
                </a>
                <span v-else class="text-muted">-</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script>
import { apiFetch } from '@/api'
import GuardrailsModal from '@/components/GuardrailsModal.vue'

export default {
  name: 'OutputsPage',
  components: {
    GuardrailsModal
  },
  data() {
    return {
      outputs: [],
      copiedMcpName: '',
      availableSources: [],
      outputCategoryOptions: [],
      outputSourceTypeOptions: [],
      sourceSearchQuery: '',
      useFilterBuilder: false,
      tagOptions: [],
      enrichmentFilterOptions: [],
      brScoreOptions: [],
      enrichmentValueOptions: [],
      enrichmentValueOptionsByField: {},
      showMongoQueryPreview: false,
      mongoQueryPreviewLoading: false,
      mongoQueryPreviewError: '',
      mongoQueryPreview: null,
      filterBuilderSelectionCount: 0,
      filterBuilder: {
        selectedFilterTypes: ['enrichment'],
        selectedTags: [],
        excludedTags: [],
        selectedBrScores: [],
        selectedEnrichmentNames: [],
        selectedEnrichmentValues: []
      },
      loading: false,
      error: '',
      showAddModal: false,
      addLoading: false,
      addCategoryLoading: false,
      addError: '',
      addCategoryError: '',
      showAddCategoryInput: false,
      newOutputCategory: '',
      newOutput: {
        name: '',
        source_name: [],
        type: '',
        output_sourcetype: '',
        filter_search: '',
        enabled: true,
        feed_authentication_status: false,
        output_category: 'general'
      },
      showGuardrailsModal: false
    }
  },
  async mounted() {
    await this.fetchOutputSourceTypeOptions()
    await this.fetchOutputCategories()
    await this.fetchOutputs()
  },
  watch: {
    'newOutput.source_name': {
      deep: true,
      handler(newVal, oldVal) {
        if (!this.showAddModal || !this.useFilterBuilder) return
        const newSorted = [...(newVal || [])].sort().join(',')
        const oldSorted = [...(oldVal || [])].sort().join(',')
        if (newSorted !== oldSorted) {
          this.clearFilterBuilderSelections()
          this.fetchFilterBuilderOptions()
        }
      }
    },
    useFilterBuilder(val) {
      if (val && this.showAddModal) {
        this.fetchFilterBuilderOptions()
      }
    }
  },
  computed: {
    filteredAvailableSources() {
      const query = (this.sourceSearchQuery || '').toString().trim().toLowerCase()
      if (!query) {
        return this.availableSources
      }
      return this.availableSources.filter(source => source.toLowerCase().includes(query))
    },
    filteredEnrichmentValueOptions() {
      const selectedNames = this.filterBuilder.selectedEnrichmentNames || []
      if (!selectedNames.length) {
        return []
      }

      const aggregated = new Set()
      for (const name of selectedNames) {
        const values = this.enrichmentValueOptionsByField[String(name)] || []
        for (const value of values) {
          const text = String(value || '').trim()
          if (text) {
            aggregated.add(text)
          }
        }
      }

      return Array.from(aggregated).sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' }))
    },
    mongoQueryPreviewText() {
      if (!this.mongoQueryPreview || typeof this.mongoQueryPreview !== 'object') {
        return '{}'
      }
      return JSON.stringify(this.mongoQueryPreview, null, 2)
    }
  },
  methods: {
    openGuardrailsModal() {
      this.showGuardrailsModal = true
    },

    formatSources(sourceName) {
      if (Array.isArray(sourceName)) {
        return sourceName.length ? sourceName.join(', ') : '-'
      }
      return sourceName || '-'
    },
    extractSourceNamesFromFilter(filterSearch) {
      const names = []

      const collect = (node) => {
        if (Array.isArray(node)) {
          node.forEach(collect)
          return
        }
        if (node && typeof node === 'object') {
          if (node.source_name) {
            if (Array.isArray(node.source_name)) {
              node.source_name.forEach((value) => {
                const text = String(value || '').trim()
                if (text) names.push(text)
              })
            } else {
              const text = String(node.source_name || '').trim()
              if (text) names.push(text)
            }
          }
          Object.values(node).forEach(collect)
        }
      }

      if (!filterSearch) {
        return []
      }

      if (typeof filterSearch === 'object') {
        collect(filterSearch)
        return [...new Set(names)]
      }

      const raw = String(filterSearch).trim()
      if (!raw) {
        return []
      }

      try {
        const parsed = JSON.parse(raw)
        collect(parsed)
      } catch (e) {
        return []
      }

      return [...new Set(names)]
    },
    formatSourceDisplay(row) {
      const baseSources = this.formatSources(row.source_name)
      const parsedFilterSources = this.extractSourceNamesFromFilter(row.filter_search)

      if (!parsedFilterSources.length) {
        return baseSources
      }

      const mergedSources = new Set()
      if (Array.isArray(row.source_name)) {
        row.source_name.forEach((value) => {
          const text = String(value || '').trim()
          if (text) mergedSources.add(text)
        })
      } else {
        const text = String(row.source_name || '').trim()
        if (text) mergedSources.add(text)
      }
      parsedFilterSources.forEach((source) => mergedSources.add(source))

      const displayValues = Array.from(mergedSources)
      return displayValues.length ? displayValues.join(', ') : '-'
    },
    feedUrl(name) {
      return `/feeds/${encodeURIComponent(name)}`
    },
    mcpUrl(name) {
      return `${window.location.origin}/mcp/${encodeURIComponent(name)}`
    },
    async copyMcpUrl(name) {
      try {
        await navigator.clipboard.writeText(this.mcpUrl(name))
        this.copiedMcpName = name
        setTimeout(() => {
          if (this.copiedMcpName === name) this.copiedMcpName = ''
        }, 2000)
      } catch (e) {
        window.prompt('Copy the MCP URL:', this.mcpUrl(name))
      }
    },
    requiresFeedAuth(type) {
      return type === 'json' || type === 'mcp'
    },
    onOutputTypeChange() {
      if (this.requiresFeedAuth(this.newOutput.type)) {
        this.newOutput.feed_authentication_status = true
      }
    },
    async openAddModal() {
      await this.fetchOutputSourceTypeOptions()
      await this.fetchOutputCategories()
      await this.fetchAvailableSources()
      this.showAddModal = true
      this.addError = ''
    },
    closeAddModal() {
      this.showAddModal = false
      this.addLoading = false
      this.addError = ''
      this.addCategoryLoading = false
      this.addCategoryError = ''
      this.showAddCategoryInput = false
      this.newOutputCategory = ''
      this.availableSources = []
      this.useFilterBuilder = false
      this.tagOptions = []
      this.enrichmentFilterOptions = []
      this.brScoreOptions = []
      this.enrichmentValueOptions = []
      this.enrichmentValueOptionsByField = {}
      this.showMongoQueryPreview = false
      this.mongoQueryPreviewLoading = false
      this.mongoQueryPreviewError = ''
      this.mongoQueryPreview = null
      this.filterBuilderSelectionCount = 0
      this.filterBuilder = {
        selectedFilterTypes: ['enrichment'],
        selectedTags: [],
        excludedTags: [],
        selectedBrScores: [],
        selectedEnrichmentNames: [],
        selectedEnrichmentValues: []
      }
      this.newOutput = {
        name: '',
        source_name: [],
        type: '',
        output_sourcetype: '',
        filter_search: '',
        enabled: true,
        feed_authentication_status: false,
        output_category: 'general'
      }
    },
    async fetchOutputCategories() {
      try {
        const res = await apiFetch('/api/configuration/output-categories')
        const data = await res.json()
        if (!res.ok) {
          this.outputCategoryOptions = ['general', 'blocklist', 'allowlist']
          return
        }

        const categories = Array.isArray(data.output_categories) ? data.output_categories : []
        this.outputCategoryOptions = categories.length ? categories : ['general', 'blocklist', 'allowlist']

        if (!this.outputCategoryOptions.includes(this.newOutput.output_category)) {
          this.newOutput.output_category = this.outputCategoryOptions[0] || 'general'
        }
      } catch (e) {
        this.outputCategoryOptions = ['general', 'blocklist', 'allowlist']
      }
    },
    toggleAddCategoryInput() {
      this.showAddCategoryInput = !this.showAddCategoryInput
      this.addCategoryError = ''
      if (!this.showAddCategoryInput) {
        this.newOutputCategory = ''
      }
    },
    async submitNewOutputCategory() {
      const category = String(this.newOutputCategory || '').trim()
      if (!category) {
        this.addCategoryError = 'Category name is required.'
        return
      }

      this.addCategoryLoading = true
      this.addCategoryError = ''
      try {
        const res = await apiFetch('/api/configuration/output-categories', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ category })
        })
        const data = await res.json()
        if (!res.ok) {
          this.addCategoryError = data.message || 'Failed to add output category.'
          return
        }

        this.outputCategoryOptions = Array.isArray(data.output_categories) ? data.output_categories : this.outputCategoryOptions
        this.newOutput.output_category = data.category || category
        this.newOutputCategory = ''
        this.showAddCategoryInput = false
      } catch (e) {
        this.addCategoryError = 'Network error while adding output category.'
      } finally {
        this.addCategoryLoading = false
      }
    },
    async fetchAvailableSources() {
      if (!this.newOutput.output_sourcetype) {
        this.availableSources = []
        return
      }
      try {
        const sourceType = encodeURIComponent(this.newOutput.output_sourcetype)
        const res = await apiFetch(`/api/outputs/sources?source_type=${sourceType}`)
        const data = await res.json()
        if (!res.ok) {
          this.availableSources = []
          return
        }

        this.availableSources = Array.isArray(data.sources) ? data.sources : []
      } catch (e) {
        this.availableSources = []
      }
    },
    async onOutputSourceTypeChange() {
      this.newOutput.source_name = []
      this.sourceSearchQuery = ''
      await this.fetchAvailableSources()
      this.tagOptions = []
      this.enrichmentFilterOptions = []
      this.brScoreOptions = []
      this.enrichmentValueOptions = []
      this.enrichmentValueOptionsByField = {}
      this.showMongoQueryPreview = false
      this.mongoQueryPreviewLoading = false
      this.mongoQueryPreviewError = ''
      this.mongoQueryPreview = null
      this.clearFilterBuilderSelections()
    },
    onFilterTypesChange() {
      const selectedTypes = this.filterBuilder.selectedFilterTypes || []

      if (!selectedTypes.includes('enrichment')) {
        this.filterBuilder.selectedEnrichmentNames = []
        this.filterBuilder.selectedEnrichmentValues = []
      }
      if (!selectedTypes.includes('tag')) {
        this.filterBuilder.selectedTags = []
        this.filterBuilder.excludedTags = []
      }
      if (!selectedTypes.includes('br_score')) {
        this.filterBuilder.selectedBrScores = []
      }

      this.applyFilterBuilder()
    },
    async toggleMongoQueryPreview() {
      this.showMongoQueryPreview = !this.showMongoQueryPreview
      if (this.showMongoQueryPreview) {
        await this.fetchMongoQueryPreview()
      }
    },
    async fetchMongoQueryPreview() {
      this.mongoQueryPreviewLoading = true
      this.mongoQueryPreviewError = ''
      try {
        const res = await apiFetch('/api/outputs/query_preview', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            source_name: this.newOutput.source_name || [],
            filter_search: this.newOutput.filter_search || '',
            output_category: this.newOutput.output_category || 'general'
          })
        })
        const data = await res.json()
        if (!res.ok) {
          this.mongoQueryPreview = null
          this.mongoQueryPreviewError = data.message || 'Failed to load Mongo query preview.'
          return
        }
        this.mongoQueryPreview = (data && typeof data.query === 'object' && data.query) ? data.query : {}
      } catch (e) {
        this.mongoQueryPreview = null
        this.mongoQueryPreviewError = 'Network error while loading Mongo query preview.'
      } finally {
        this.mongoQueryPreviewLoading = false
      }
    },
    onSelectedEnrichmentsChange() {
      const allowedValues = new Set(this.filteredEnrichmentValueOptions)
      this.filterBuilder.selectedEnrichmentValues = (this.filterBuilder.selectedEnrichmentValues || [])
        .map(value => String(value || '').trim())
        .filter(value => value && allowedValues.has(value))
      this.applyFilterBuilder()
    },
    onIncludedTagChange(tagOption) {
      const tagText = String(tagOption || '').trim()
      if (tagText && (this.filterBuilder.selectedTags || []).includes(tagText)) {
        this.filterBuilder.excludedTags = (this.filterBuilder.excludedTags || []).filter(tag => String(tag || '').trim() !== tagText)
      }
      this.applyFilterBuilder()
    },
    onExcludedTagChange(tagOption) {
      const tagText = String(tagOption || '').trim()
      if (tagText && (this.filterBuilder.excludedTags || []).includes(tagText)) {
        this.filterBuilder.selectedTags = (this.filterBuilder.selectedTags || []).filter(tag => String(tag || '').trim() !== tagText)
      }
      this.applyFilterBuilder()
    },
    removeSelectedSource(source) {
      this.newOutput.source_name = this.newOutput.source_name.filter(item => item !== source)
    },
    clearSelectedSources() {
      this.newOutput.source_name = []
    },
    async fetchFilterBuilderOptions() {
      const sources = this.newOutput.source_name || []
      if (!sources.length) {
        this.tagOptions = []
        this.enrichmentFilterOptions = []
        this.brScoreOptions = []
        this.enrichmentValueOptions = []
        this.enrichmentValueOptionsByField = {}
        return
      }
      try {
        const params = sources.map(s => encodeURIComponent(s)).join(',')
        const res = await apiFetch(`/api/outputs/filter_options?source_names=${params}`)
        const data = await res.json()
        if (!res.ok) {
          this.tagOptions = []
          this.enrichmentFilterOptions = []
          this.brScoreOptions = []
          this.enrichmentValueOptions = []
          this.enrichmentValueOptionsByField = {}
          return
        }
        this.tagOptions = Array.isArray(data.tags) ? data.tags : []
        this.enrichmentFilterOptions = Array.isArray(data.enrichments) ? data.enrichments : []
        this.brScoreOptions = Array.isArray(data.br_scores) ? data.br_scores : []
        this.enrichmentValueOptions = Array.isArray(data.enrichment_values) ? data.enrichment_values : []
        this.enrichmentValueOptionsByField = (data.enrichment_values_by_field && typeof data.enrichment_values_by_field === 'object')
          ? data.enrichment_values_by_field
          : {}
      } catch (e) {
        this.tagOptions = []
        this.enrichmentFilterOptions = []
        this.brScoreOptions = []
        this.enrichmentValueOptions = []
        this.enrichmentValueOptionsByField = {}
      }
    },
    applyFilterBuilder() {
      const selectedTypes = [...new Set((this.filterBuilder.selectedFilterTypes || []).map(v => String(v || '').trim()).filter(Boolean))]
      const generated = {}

      let totalSelectedCriteria = 0

      if (selectedTypes.includes('enrichment')) {
        const selectedEnrichments = [...new Set((this.filterBuilder.selectedEnrichmentNames || []).map(v => String(v || '').trim()).filter(Boolean))]
        const selectedEnrichmentValues = [...new Set((this.filterBuilder.selectedEnrichmentValues || []).map(v => String(v || '').trim()).filter(Boolean))]

        totalSelectedCriteria += selectedEnrichments.length + selectedEnrichmentValues.length

        if (selectedEnrichments.length) {
          generated.selected_enrichments = selectedEnrichments
        }
        if (selectedEnrichmentValues.length) {
          generated.selected_enrichment_values = selectedEnrichmentValues
        }
      }

      if (selectedTypes.includes('tag')) {
        const selectedTags = [...new Set((this.filterBuilder.selectedTags || []).map(v => String(v || '').trim()).filter(Boolean))]
        const excludedTags = [...new Set((this.filterBuilder.excludedTags || []).map(v => String(v || '').trim()).filter(Boolean))]
        totalSelectedCriteria += selectedTags.length + excludedTags.length
        if (selectedTags.length) {
          generated.selected_tags = selectedTags
        }
        if (excludedTags.length) {
          generated.selected_tags_not = excludedTags
        }
      }

      if (selectedTypes.includes('br_score')) {
        const selectedBrScores = [...new Set((this.filterBuilder.selectedBrScores || []).map(v => String(v || '').trim()).filter(Boolean))]
        totalSelectedCriteria += selectedBrScores.length
        if (selectedBrScores.length) {
          generated.selected_br_scores = selectedBrScores
        }
      }

      this.filterBuilderSelectionCount = totalSelectedCriteria

      if (!this.filterBuilderSelectionCount) {
        this.newOutput.filter_search = ''
        if (this.showMongoQueryPreview) {
          this.fetchMongoQueryPreview()
        }
        return
      }

      this.newOutput.filter_search = JSON.stringify(generated)
      if (this.showMongoQueryPreview) {
        this.fetchMongoQueryPreview()
      }
    },
    clearFilterBuilderSelections() {
      this.filterBuilder = {
        selectedFilterTypes: ['enrichment'],
        selectedTags: [],
        excludedTags: [],
        selectedBrScores: [],
        selectedEnrichmentNames: [],
        selectedEnrichmentValues: []
      }
      this.filterBuilderSelectionCount = 0
      this.newOutput.filter_search = ''
      if (this.showMongoQueryPreview) {
        this.fetchMongoQueryPreview()
      }
    },
    async fetchOutputSourceTypeOptions() {
      try {
        const res = await apiFetch('/api/data_types')
        const data = await res.json()
        if (!res.ok) {
          this.outputSourceTypeOptions = []
          return
        }

        this.outputSourceTypeOptions = Array.isArray(data.data_types) ? data.data_types : []
      } catch (e) {
        this.outputSourceTypeOptions = []
      }
    },
    async submitNewOutput() {
      if (!this.newOutput.name || !Array.isArray(this.newOutput.source_name) || this.newOutput.source_name.length === 0 || !this.newOutput.type || !this.newOutput.output_sourcetype) {
        this.addError = 'Please fill in all required fields.'
        return
      }

      this.addLoading = true
      this.addError = ''
      try {
        const headers = {
          'Content-Type': 'application/json'
        }

        const payload = {
          ...this.newOutput,
          feed_authentication_status: this.requiresFeedAuth(this.newOutput.type)
            ? true
            : !!this.newOutput.feed_authentication_status
        }

        const res = await apiFetch('/api/outputs/create', {
          method: 'POST',
          headers,
          body: JSON.stringify(payload)
        })

        const data = await res.json()
        if (!res.ok) {
          this.addError = data.message || 'Failed to create output'
          return
        }

        this.closeAddModal()
        await this.fetchOutputs()
      } catch (e) {
        this.addError = 'Network error while creating output'
      } finally {
        this.addLoading = false
      }
    },
    async fetchOutputs() {
      this.loading = true
      this.error = ''
      try {
        const res = await apiFetch('/api/outputs')
        const data = await res.json()

        if (!res.ok) {
          this.error = data.message || 'Failed to fetch outputs'
          this.outputs = []
          return
        }

        this.outputs = Array.isArray(data.outputs) ? data.outputs : []
      } catch (e) {
        this.error = 'Network error while fetching outputs'
        this.outputs = []
      } finally {
        this.loading = false
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
