<template>
  <div class="container mt-4">
    <h2>Indicators</h2>

    <!-- Search Bar -->
    <div class="mb-3">
      <div class="input-group input-group-lg">
        <span class="input-group-text bg-white"><i>🔍</i></span>
        <input
          v-model="search"
          @input="onSearch"
          type="text"
          class="form-control"
          placeholder="Search indicators by value, type, or source..."
          autofocus
        />
        <button v-if="search" class="btn btn-outline-secondary" @click="search=''; onSearch()">✕</button>
      </div>
    </div>

    <div class="mb-3">
      <div class="card border-0 shadow-sm">
        <div class="card-body py-3">
          <div class="d-flex flex-column flex-md-row gap-2 align-items-md-center">
            <div class="fw-semibold text-muted small">Indicator Timeline Lookup</div>
            <div class="input-group">
              <span class="input-group-text bg-white">⏱</span>
              <input
                v-model.trim="timelineQuery"
                type="text"
                class="form-control"
                placeholder="Enter indicator value to view timeline..."
                @keyup.enter="openTimelineFromInput"
              />
              <button class="btn btn-outline-primary" @click="openTimelineFromInput" :disabled="!timelineQuery || timelineLoading">View Timeline</button>
            </div>
          </div>
          <div v-if="timelineInlineError" class="text-danger small mt-2">{{ timelineInlineError }}</div>
        </div>
      </div>
    </div>

    <div v-if="loading" class="text-center my-4">Loading...</div>
    <div v-if="error" class="alert alert-danger">{{ error }}</div>

    <!-- Actions and Filters -->
    <div class="mb-3">
      <div class="d-flex gap-2 align-items-center flex-wrap">
        <button class="btn btn-primary" @click="showAddModal = true"><i class="me-2">+</i> New Indicator</button>
        <button class="btn btn-primary" @click="openBulkAddModal"><i class="me-2">📋</i> Bulk Add</button>
        <button class="btn btn-outline-primary" @click="openImportUrlModal"><i class="me-2">🌐</i> Import from URL</button>
        <button class="btn btn-outline-success" @click="openEnrichmentSelectModal('bulk')" :disabled="bulkEnriching || !filteredIndicators.length">
          <span v-if="bulkEnriching" class="spinner-border spinner-border-sm me-1"></span>
          🧬 Run Enrichments
        </button>
        <select v-model="activeStatus" @change="onStatusChange" class="form-select" style="width: 150px;">
          <option value="all">All Status</option>
          <option value="active">Active</option>
          <option value="inactive">Inactive</option>
        </select>
        <select v-model="sourceFilter" @change="onSourceChange" class="form-select" style="width: 200px;">
          <option value="all">All Sources</option>
          <option v-for="source in allSources" :key="source" :value="source">{{ source }}</option>
        </select>
      </div>
      <div v-if="bulkEnrichResult" class="mt-2">
        <div :class="bulkEnrichResult.error ? 'alert alert-danger' : 'alert alert-success'" class="py-2 mb-0 small">
          {{ bulkEnrichResult.message }}
          <button type="button" class="btn-close float-end" style="font-size:0.7rem;" @click="bulkEnrichResult = null"></button>
        </div>
      </div>
    </div>

    <div v-if="showEnrichmentSelectModal" class="modal-overlay enrichment-modal-overlay" @click.self="closeEnrichmentSelectModal">
      <div class="modal-content" style="max-width: 520px;">
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
          <div class="border rounded p-2" style="max-height: 220px; overflow-y: auto;">
            <div v-if="filteredEnrichmentOptions.length === 0" class="text-muted small">No enrichments found.</div>
            <div v-for="enrichment in filteredEnrichmentOptions" :key="enrichment.enrich_name" class="form-check">
              <input
                :id="`run_enrich_${enrichment.enrich_name}`"
                v-model="selectedEnrichmentNames"
                class="form-check-input"
                type="checkbox"
                :value="enrichment.enrich_name"
              >
              <label class="form-check-label" :for="`run_enrich_${enrichment.enrich_name}`">{{ enrichment.enrich_name }}</label>
            </div>
          </div>
          <div v-if="selectedEnrichmentNames.length" class="mt-2 d-flex flex-wrap gap-1">
            <span v-for="name in selectedEnrichmentNames" :key="`selected_run_${name}`" class="badge bg-secondary d-inline-flex align-items-center">
              {{ name }}
              <button type="button" class="btn-close btn-close-white ms-1" style="font-size:0.6rem;" @click="selectedEnrichmentNames = selectedEnrichmentNames.filter(n => n !== name)"></button>
            </span>
            <button type="button" class="btn btn-sm btn-outline-secondary" @click="selectedEnrichmentNames = []">Clear all</button>
          </div>
          <div class="form-text mt-2">Pick one or more enrichments to run.</div>
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

    <!-- Add Indicator Modal -->
    <div v-if="showAddModal" class="modal-overlay" @click.self="closeAddModal">
      <div class="modal-content" style="max-width:400px;">
        <div class="modal-header">
          <h5 class="modal-title">Add New Indicator</h5>
          <button type="button" class="btn-close" @click="closeAddModal"></button>
        </div>
        <div class="modal-body">
          <form @submit.prevent="submitNewIndicator">
            <div class="mb-3">
              <label class="form-label">Value</label>
              <input v-model="newIndicator.value" type="text" class="form-control" required>
            </div>
            <div class="mb-3">
              <label class="form-label">Type</label>
              <select v-model="newIndicator.type" class="form-select" required @change="onNewIndicatorTypeChange">
                <option value="">-- Select Type --</option>
                <option v-for="dt in dataTypes" :key="dt" :value="dt">{{ dt }}</option>
              </select>
            </div>
            <div class="mb-3">
              <label class="form-label">Source Name</label>
              <div v-if="!newIndicator.type" class="alert alert-info small">
                Select a type to load source names.
              </div>
              <div v-else-if="sourceNames.length === 0" class="alert alert-warning small">
                No static sources found for selected type.
              </div>
              <select v-model="newIndicator.source_name" class="form-select" required :disabled="!newIndicator.type || sourceNames.length === 0">
                <option value="">-- Select Source --</option>
                <option v-for="sn in sourceNames" :key="sn" :value="sn">{{ sn }}</option>
              </select>
            </div>
            <div class="mb-3">
              <label class="form-label">Comment (optional)</label>
              <textarea
                v-model.trim="newIndicator.comment"
                class="form-control"
                rows="2"
                maxlength="2000"
                placeholder="Add context for this manual/static entry..."
              ></textarea>
              <div class="form-text">{{ (newIndicator.comment || '').length }}/2000</div>
            </div>
            <div v-if="addError" class="alert alert-danger small">{{ addError }}</div>
          </form>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" @click="closeAddModal">Cancel</button>
          <button type="button" class="btn btn-primary" @click="submitNewIndicator" :disabled="addLoading || !newIndicator.type || sourceNames.length === 0">
            <span v-if="addLoading" class="spinner-border spinner-border-sm me-2"></span>
            {{ addLoading ? 'Adding...' : 'Add Indicator' }}
          </button>
        </div>
      </div>
    </div>

    <!-- Bulk Add Indicators Modal -->
    <div v-if="showBulkAddModal" class="modal-overlay" @click.self="closeBulkAddModal">
      <div class="modal-content" style="max-width:500px;">
        <div class="modal-header">
          <h5 class="modal-title">Bulk Add Indicators</h5>
          <button type="button" class="btn-close" @click="closeBulkAddModal" :disabled="bulkAddLoading"></button>
        </div>
        <div class="modal-body">
          <div class="mb-3">
            <label class="form-label">Type</label>
            <select v-model="bulkAddType" class="form-select" required @change="onBulkAddTypeChange" :disabled="bulkAddLoading">
              <option value="">-- Select Type --</option>
              <option v-for="dt in dataTypes" :key="dt" :value="dt">{{ dt }}</option>
            </select>
          </div>
          <div class="mb-3">
            <label class="form-label">Source Name</label>
            <div v-if="!bulkAddType" class="alert alert-info small">
              Select a type to load source names.
            </div>
            <div v-else-if="bulkAddSourceNames.length === 0" class="alert alert-warning small">
              No static sources found for selected type.
            </div>
            <select v-model="bulkAddSourceName" class="form-select" required :disabled="!bulkAddType || bulkAddSourceNames.length === 0 || bulkAddLoading">
              <option value="">-- Select Source --</option>
              <option v-for="sn in bulkAddSourceNames" :key="sn" :value="sn">{{ sn }}</option>
            </select>
          </div>
          <div class="mb-3">
            <label class="form-label">Indicator Values (one per line)</label>
            <textarea 
              v-model="bulkAddInput" 
              class="form-control" 
              rows="6" 
              placeholder="192.168.1.1&#10;10.0.0.5&#10;172.16.0.1"
              :disabled="!bulkAddType || !bulkAddSourceName || bulkAddLoading"
            ></textarea>
          </div>
          <div class="mb-3">
            <label class="form-label">Comment Update (optional)</label>
            <textarea
              v-model.trim="bulkAddComment"
              class="form-control"
              rows="2"
              maxlength="2000"
              placeholder="Apply this source comment to all indicators in this bulk update..."
              :disabled="bulkAddLoading"
            ></textarea>
            <div class="form-text">{{ (bulkAddComment || '').length }}/2000</div>
          </div>
          <div v-if="bulkAddError" class="alert alert-danger small">{{ bulkAddError }}</div>
          <div v-if="bulkAddResults" :class="bulkAddResults.error_count > 0 ? 'alert alert-warning' : 'alert alert-success'" class="small">
            <strong>Results:</strong>
            <ul class="mb-0 mt-2">
              <li v-if="bulkAddResults.ok_count > 0"><span class="text-success">✓ Added: {{ bulkAddResults.ok_count }}</span></li>
              <li v-if="bulkAddResults.error_count > 0"><span class="text-danger">✗ Errors: {{ bulkAddResults.error_count }}</span></li>
              <li v-if="bulkAddResults.skipped_count > 0"><span class="text-warning">⊘ Skipped: {{ bulkAddResults.skipped_count }}</span></li>
            </ul>
            <div v-if="bulkAddResults.results && bulkAddResults.results.length > 0" class="mt-2 text-muted smaller">
              <details>
                <summary>Details</summary>
                <div class="mt-1">
                  <div v-for="(r, i) in bulkAddResults.results" :key="i" class="mb-1">
                    <span :class="{
                      'text-success': r.status === 'ok',
                      'text-danger': r.status === 'error',
                      'text-warning': r.status === 'skipped'
                    }">
                      {{ r.value }} — {{ r.status }}
                      <span v-if="r.message" class="small">{{ r.message }}</span>
                    </span>
                  </div>
                </div>
              </details>
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" @click="closeBulkAddModal" :disabled="bulkAddLoading">Cancel</button>
          <button type="button" class="btn btn-primary" @click="submitBulkAdd" :disabled="bulkAddLoading || !bulkAddType || !bulkAddSourceName || !bulkAddInput.trim()">
            <span v-if="bulkAddLoading" class="spinner-border spinner-border-sm me-2"></span>
            {{ bulkAddLoading ? 'Adding...' : 'Add Indicators' }}
          </button>
        </div>
      </div>
    </div>

    <!-- Import Indicators From URL Modal -->
    <div v-if="showImportUrlModal" class="modal-overlay" @click.self="closeImportUrlModal">
      <div class="modal-content" style="max-width:820px;">
        <div class="modal-header">
          <h5 class="modal-title">Import Indicators from URL</h5>
          <button type="button" class="btn-close" @click="closeImportUrlModal" :disabled="importUrlLoading || importAddLoading"></button>
        </div>
        <div class="modal-body">
          <div class="row g-3">
            <div class="col-12">
              <label class="form-label">Web URL</label>
              <input
                v-model.trim="importUrl"
                type="url"
                class="form-control"
                placeholder="https://example.com/ioc-list"
                :disabled="importUrlLoading || importAddLoading"
              >
            </div>
            <div class="col-md-4">
              <label class="form-label">Indicator Type</label>
              <select v-model="importType" class="form-select" @change="onImportTypeChange" :disabled="importUrlLoading || importAddLoading">
                <option value="">-- Select Type --</option>
                <option v-for="dt in dataTypes" :key="`import_type_${dt}`" :value="dt">{{ dt }}</option>
              </select>
            </div>
            <div class="col-md-4">
              <label class="form-label">Source Name</label>
              <select v-model="importSourceName" class="form-select" :disabled="!importType || importImportSourceNamesLoading || importUrlLoading || importAddLoading">
                <option value="">-- Select Source --</option>
                <option v-for="sn in importSourceNames" :key="`import_source_${sn}`" :value="sn">{{ sn }}</option>
              </select>
              <div v-if="importImportSourceNamesLoading" class="form-text">Loading source names...</div>
            </div>
            <div class="col-md-4">
              <label class="form-label">Comment (optional)</label>
              <input
                v-model.trim="importComment"
                type="text"
                class="form-control"
                maxlength="2000"
                :disabled="importUrlLoading || importAddLoading"
                placeholder="Apply to all imported entries"
              >
            </div>
          </div>

          <div class="mt-3 d-flex gap-2 align-items-center">
            <button
              type="button"
              class="btn btn-primary"
              @click="detectIndicatorsFromUrl"
              :disabled="importUrlLoading || importAddLoading || !importUrl || !importType"
            >
              <span v-if="importUrlLoading" class="spinner-border spinner-border-sm me-1"></span>
              {{ importUrlLoading ? 'Detecting...' : 'Detect Indicators' }}
            </button>
            <span class="text-muted small" v-if="importDetectedCount !== null">
              Detected: {{ importDetectedCount }}
            </span>
          </div>

          <div v-if="importError" class="alert alert-danger py-2 mt-3 mb-0">{{ importError }}</div>

          <div v-if="importPreviewIndicators.length" class="mt-3">
            <div class="d-flex justify-content-between align-items-center mb-2">
              <strong class="small">Detected Indicators</strong>
              <div class="d-flex align-items-center gap-2">
                <button type="button" class="btn btn-sm btn-outline-secondary" @click="selectAllImportPreview" :disabled="importAddLoading">Select All</button>
                <button type="button" class="btn btn-sm btn-outline-secondary" @click="clearImportPreviewSelection" :disabled="importAddLoading">Clear</button>
                <span class="small text-muted">Selected: {{ importSelectedIndicators.length }}</span>
              </div>
            </div>
            <div class="table-responsive" style="max-height:300px; overflow-y:auto;">
              <table class="table table-sm table-striped mb-0">
                <thead class="table-light">
                  <tr>
                    <th style="width:40px;"></th>
                    <th>Value</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="indicatorValue in importPreviewIndicators" :key="`import_preview_${indicatorValue}`">
                    <td>
                      <input
                        v-model="importSelectedIndicators"
                        class="form-check-input"
                        type="checkbox"
                        :value="indicatorValue"
                        :disabled="importAddLoading"
                      >
                    </td>
                    <td class="text-break">{{ indicatorValue }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <div v-if="importResultMessage" :class="importResultError ? 'alert alert-danger' : 'alert alert-success'" class="py-2 mt-3 mb-0 small">
            {{ importResultMessage }}
          </div>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" @click="closeImportUrlModal" :disabled="importUrlLoading || importAddLoading">Cancel</button>
          <button
            type="button"
            class="btn btn-success"
            @click="submitImportSelected"
            :disabled="importUrlLoading || importAddLoading || !importSourceName || importSelectedIndicators.length === 0"
          >
            <span v-if="importAddLoading" class="spinner-border spinner-border-sm me-1"></span>
            {{ importAddLoading ? 'Adding...' : 'Add Selected Indicators' }}
          </button>
        </div>
      </div>
    </div>

    <!-- Indicator Detail Modal -->
    <div v-if="showDetailModal" class="modal-overlay" @click.self="closeDetailModal">
      <div class="modal-content" style="max-width:720px;">
        <div class="modal-header">
          <div>
            <h5 class="modal-title mb-0">Indicator Detail</h5>
            <p class="text-muted small mb-0" v-if="detailIndicator">{{ detailIndicator.value }}</p>
          </div>
          <button type="button" class="btn-close" @click="closeDetailModal"></button>
        </div>
        <div class="modal-body">
          <div v-if="detailLoading" class="text-center py-4">
            <div class="spinner-border text-primary" role="status"><span class="visually-hidden">Loading...</span></div>
          </div>
          <div v-else-if="detailError" class="alert alert-danger">{{ detailError }}</div>
          <div v-else-if="!detailIndicator" class="alert alert-info">Indicator not found.</div>
          <div v-else>
            <div class="row g-3 mb-3">
              <div class="col-md-6">
                <div class="card h-100">
                  <div class="card-header py-2"><strong>Core Info</strong></div>
                  <div class="card-body py-2">
                    <div class="mb-1"><strong>Value:</strong> <span class="text-break">{{ detailIndicator.value }}</span></div>
                    <div class="mb-1"><strong>Type:</strong> {{ detailIndicator.type || '-' }}</div>
                    <div class="mb-1"><strong>Active:</strong>
                      <span v-if="detailIndicator.active" class="badge bg-success">Yes</span>
                      <span v-else class="badge bg-secondary">No</span>
                    </div>
                    <div class="mb-1"><strong>Max BR Score:</strong> {{ detailIndicator.max_br_score ?? '-' }}</div>
                    <div class="mb-1"><strong>Source Count:</strong> {{ detailIndicator.source_count ?? 0 }}</div>
                    <div class="mb-0"><strong>Last Seen:</strong> {{ formatDetailDate(detailIndicator.last_seen) }}</div>
                  </div>
                </div>
              </div>
              <div class="col-md-6">
                <div class="card h-100">
                  <div class="card-header py-2"><strong>Sources Summary</strong></div>
                  <div class="card-body py-2">
                    <div v-if="!Array.isArray(detailIndicator.sources) || detailIndicator.sources.length === 0" class="text-muted small">No sources.</div>
                    <ul v-else class="list-unstyled mb-0">
                      <li v-for="(s, si) in detailIndicator.sources" :key="si" class="mb-1">
                        <span class="fw-medium">{{ s.source_name || '-' }}</span>
                        <span class="text-muted small ms-2">{{ formatDetailDate(s.lastupdate_time) }}</span>
                        <span v-if="s.br_score != null" class="badge bg-info text-dark ms-1">{{ s.br_score }}</span>
                        <span v-if="getSourceTags(s).length" class="d-inline-flex flex-wrap gap-1 ms-1">
                          <span v-for="tag in getSourceTags(s)" :key="tag" class="badge bg-warning text-dark">{{ tag }}</span>
                        </span>
                      </li>
                    </ul>
                  </div>
                </div>
              </div>
            </div>
            <div class="card">
              <div class="card-header py-2"><strong>Source Details</strong></div>
              <div class="card-body p-0">
                <div v-if="!Array.isArray(detailIndicator.sources) || detailIndicator.sources.length === 0" class="p-3 text-muted small">No sources available.</div>
                <div v-if="tagEditor.error" class="px-3 pt-3">
                  <div class="alert alert-danger py-2 mb-0">{{ tagEditor.error }}</div>
                </div>
                <div v-else class="table-responsive">
                  <table class="table table-sm table-striped mb-0">
                    <thead class="table-light">
                      <tr><th>Source Name</th><th>Last Update</th><th>Status</th><th>BR Score</th><th>Tag</th><th>Actions</th></tr>
                    </thead>
                    <tbody>
                      <tr v-for="(source, si) in detailIndicator.sources" :key="si">
                        <td>{{ source.source_name || '-' }}</td>
                        <td>{{ formatDetailDate(source.lastupdate_time) }}</td>
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

            <div class="card mt-3">
              <div class="card-header py-2"><strong>Comments</strong></div>
              <div class="card-body">
                <div class="row g-2 mb-3">
                  <div class="col-md-4">
                    <label class="form-label small mb-1">Source Scope</label>
                    <select v-model="commentForm.source_name" class="form-select form-select-sm" :disabled="commentSubmitting || !detailIndicator">
                      <option value="">-- Select Source --</option>
                      <option
                        v-for="source in (detailIndicator && Array.isArray(detailIndicator.sources) ? detailIndicator.sources : [])"
                        :key="`comment_scope_${source.source_name}`"
                        :value="source.source_name"
                      >
                        {{ source.source_name }}
                      </option>
                    </select>
                  </div>
                  <div class="col-md-8">
                    <label class="form-label small mb-1">Add Comment</label>
                    <textarea
                      v-model.trim="commentForm.text"
                      class="form-control form-control-sm"
                      rows="2"
                      maxlength="2000"
                      placeholder="Add context for static/manual entries or any indicator..."
                      :disabled="commentSubmitting || !detailIndicator"
                    ></textarea>
                  </div>
                </div>

                <div class="d-flex justify-content-between align-items-center mb-2">
                  <small class="text-muted">{{ commentForm.text.length }}/2000</small>
                  <button
                    type="button"
                    class="btn btn-sm btn-outline-primary"
                    @click="submitIndicatorComment"
                    :disabled="commentSubmitting || !detailIndicator || !commentForm.text || !commentForm.source_name"
                  >
                    <span v-if="commentSubmitting" class="spinner-border spinner-border-sm me-1"></span>
                    {{ commentSubmitting ? 'Saving...' : 'Save Comment' }}
                  </button>
                </div>

                <div v-if="commentError" class="alert alert-danger py-2 small">{{ commentError }}</div>

                <div v-if="!detailIndicator || !Array.isArray(detailIndicator.comments) || detailIndicator.comments.length === 0" class="text-muted small">
                  No comments yet.
                </div>
                <div v-else class="table-responsive">
                  <table class="table table-sm table-striped mb-0">
                    <thead class="table-light">
                      <tr>
                        <th>When</th>
                        <th>By</th>
                        <th>Scope</th>
                        <th>Comment</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="(comment, ci) in detailIndicator.comments" :key="`indicator_comment_${ci}`">
                        <td class="small">{{ formatDetailDate(comment.created_at) }}</td>
                        <td class="small">{{ comment.created_by || 'Unknown' }}</td>
                        <td class="small">{{ comment.source_name || 'General' }}</td>
                        <td class="small text-break">{{ comment.comment }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <router-link
            :to="{ path: '/indicators/detail', query: { value: (detailIndicator && detailIndicator.value) || '', type: (detailIndicator && detailIndicator.type) || '' } }"
            class="btn btn-outline-primary me-auto"
            @click="closeDetailModal"
          >🔗 Open Full Detail Page</router-link>
          <button
            v-if="detailIndicator"
            class="btn btn-outline-success"
            :disabled="enrichingRow[detailIndicator.value + '|' + detailIndicator.type]"
            @click="openEnrichmentSelectModal('single', detailIndicator)"
          >
            <span v-if="enrichingRow[detailIndicator.value + '|' + detailIndicator.type]" class="spinner-border spinner-border-sm me-1"></span>
            🧬 Run Enrichments
          </button>
          <div v-if="detailIndicator && enrichRowResult[detailIndicator.value + '|' + detailIndicator.type]" class="me-2">
            <span :class="enrichRowResult[detailIndicator.value + '|' + detailIndicator.type].ok ? 'badge bg-success' : 'badge bg-danger'">
              {{ enrichRowResult[detailIndicator.value + '|' + detailIndicator.type].ok ? 'Enrichment applied ✓' : enrichRowResult[detailIndicator.value + '|' + detailIndicator.type].message }}
            </span>
          </div>
          <button class="btn btn-secondary" @click="closeDetailModal">Close</button>
        </div>
      </div>
    </div>

    <!-- Indicator Timeline Modal -->
    <div v-if="showTimelineModal" class="modal-overlay" @click.self="closeTimelineModal">
      <div class="modal-content" style="max-width:900px;">
        <div class="modal-header">
          <div>
            <h5 class="modal-title mb-0">Indicator Timeline</h5>
            <p class="text-muted small mb-0" v-if="timelineIndicator">{{ timelineIndicator.value }} <span v-if="timelineIndicator.type">({{ timelineIndicator.type }})</span></p>
          </div>
          <button type="button" class="btn-close" @click="closeTimelineModal"></button>
        </div>
        <div class="modal-body">
          <div class="input-group mb-3">
            <span class="input-group-text bg-white">🔎</span>
            <input
              v-model.trim="timelineQuery"
              type="text"
              class="form-control"
              placeholder="Search another indicator..."
              @keyup.enter="openTimelineFromInput"
            >
            <button class="btn btn-outline-primary" @click="openTimelineFromInput" :disabled="!timelineQuery || timelineLoading">Search</button>
          </div>

          <div v-if="timelineLoading" class="text-center py-4">
            <div class="spinner-border text-primary" role="status"><span class="visually-hidden">Loading...</span></div>
          </div>
          <div v-else-if="timelineError" class="alert alert-danger">{{ timelineError }}</div>
          <div v-else>
            <div class="row g-3 mb-3" v-if="timelineSummary">
              <div class="col-md-6">
                <div class="card h-100">
                  <div class="card-header py-2"><strong>First Added</strong></div>
                  <div class="card-body py-2 small">
                    <div class="mb-1"><strong>When:</strong> {{ formatDetailDate(timelineSummary.first_added_at) }}</div>
                    <div class="mb-1"><strong>How:</strong> {{ timelineSummary.first_added_via === 'static' ? 'Static' : 'Source Datapull' }}</div>
                    <div class="mb-1"><strong>Source:</strong> {{ timelineSummary.first_added_source || '-' }}</div>
                    <div class="mb-0"><strong>Added By:</strong> {{ timelineSummary.first_added_by || (timelineSummary.first_added_via === 'static' ? 'Unknown' : 'System') }}</div>
                  </div>
                </div>
              </div>
              <div class="col-md-6">
                <div class="card h-100">
                  <div class="card-header py-2"><strong>Current Snapshot</strong></div>
                  <div class="card-body py-2 small">
                    <div class="mb-1"><strong>First Seen:</strong> {{ formatDetailDate(timelineIndicator && timelineIndicator.firstupdate_time) }}</div>
                    <div class="mb-1"><strong>Last Seen:</strong> {{ formatDetailDate(timelineIndicator && timelineIndicator.last_seen) }}</div>
                    <div class="mb-1"><strong>Sources:</strong> {{ Array.isArray(timelineIndicator && timelineIndicator.sources) ? timelineIndicator.sources.length : 0 }}</div>
                    <div class="mb-0"><strong>Events:</strong> {{ timelineEvents.length }}</div>
                  </div>
                </div>
              </div>
            </div>

            <div class="card">
              <div class="card-header py-2"><strong>Action Timeline</strong></div>
              <div class="card-body p-0">
                <div v-if="!timelineEvents.length" class="p-3 text-muted small">No timeline events found for this indicator.</div>
                <div v-else class="table-responsive">
                  <table class="table table-sm table-striped mb-0">
                    <thead class="table-light">
                      <tr>
                        <th>Timestamp</th>
                        <th>Action</th>
                        <th>Method</th>
                        <th>Source</th>
                        <th>Actor</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="(event, ei) in timelineEvents" :key="`timeline_evt_${ei}`">
                        <td>{{ formatDetailDate(event.timestamp) }}</td>
                        <td><span class="badge bg-light text-dark text-uppercase">{{ event.action || '-' }}</span></td>
                        <td>{{ event.via === 'static' ? 'Static' : 'Source Datapull' }}</td>
                        <td>{{ event.source || '-' }}</td>
                        <td>{{ event.actor || (event.via === 'static' ? 'Unknown' : 'System') }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-secondary" @click="closeTimelineModal">Close</button>
        </div>
      </div>
    </div>

    <table v-if="!loading && filteredIndicators.length" class="table table-striped">
      <thead>
        <tr>
          <th @click="toggleSort('value')" style="cursor: pointer; user-select: none;">
            Value
            <span v-if="sortField === 'value'" class="ms-1">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
          </th>
          <th @click="toggleSort('type')" style="cursor: pointer; user-select: none;">
            Type
            <span v-if="sortField === 'type'" class="ms-1">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
          </th>
          <th @click="toggleSort('max_br_score')" style="cursor: pointer; user-select: none;">
            Max BR Score
            <span v-if="sortField === 'max_br_score'" class="ms-1">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
          </th>
          <th>Sources</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(i, idx) in filteredIndicators" :key="idx">
          <td>
            <a href="#" class="text-decoration-none fw-medium" @click.prevent="openDetailModal(i)">
              {{ i.value }}
            </a>
          </td>
          <td>{{ i.type }}</td>
          <td>{{ i.max_br_score !== null && i.max_br_score !== undefined ? i.max_br_score : '-' }}</td>
          <td>
            <ul class="mb-0">
              <li v-for="(s,si) in i.sources" :key="si">{{ s.source_name }} ({{ s.lastupdate_time || '' }})</li>
            </ul>
          </td>
          <td class="text-end" style="white-space:nowrap;">
            <button
              class="btn btn-sm btn-outline-primary me-1"
              @click.stop="openTimelineFromRow(i)"
              title="View timeline"
            >⏱</button>
            <button
              class="btn btn-sm btn-outline-success"
              :disabled="enrichingRow[i.value + '|' + i.type]"
              @click.stop="openEnrichmentSelectModal('single', i)"
              title="Run enrichments for this indicator"
            >
              <span v-if="enrichingRow[i.value + '|' + i.type]" class="spinner-border spinner-border-sm"></span>
              <span v-else>🧬</span>
            </button>
            <span
              v-if="enrichRowResult[i.value + '|' + i.type]"
              :class="enrichRowResult[i.value + '|' + i.type].ok ? 'badge bg-success ms-1' : 'badge bg-danger ms-1'"
            >{{ enrichRowResult[i.value + '|' + i.type].ok ? '✓' : '✗' }}</span>
          </td>
        </tr>
      </tbody>
    </table>
    <div v-if="!loading && !filteredIndicators.length" class="text-muted">No indicators available.</div>
    <nav v-if="pages > 1" class="mt-3">
      <ul class="pagination">
        <li class="page-item" :class="{ disabled: page === 1 }"><button class="page-link" @click="prevPage">Previous</button></li>
        <li v-for="p in Math.min(pages, 7)" :key="p" class="page-item" :class="{ active: p === page }"><button class="page-link" @click="gotoPage(p)">{{ p }}</button></li>
        <li class="page-item" :class="{ disabled: page === pages }"><button class="page-link" @click="nextPage">Next</button></li>
      </ul>
      <div class="small text-muted mt-1">Page {{ page }} of {{ pages }} — {{ total }} total</div>
    </nav>
  </div>
</template>

<script>
import { apiFetch } from '@/api'

export default {
  name: 'IndicatorsPage',
  computed: {
    filteredEnrichmentOptions() {
      const q = this.enrichmentSearchQuery.toLowerCase()
      if (!q) return this.enrichmentOptions
      return this.enrichmentOptions.filter(e => String(e.enrich_name || '').toLowerCase().includes(q))
    }
  },
  data() {
    return {
      indicators: [],
      loading: false,
      error: null,
      page: 1,
      pages: 1,
      limit: 25,
      total: 0,
      search: '',
      activeStatus: 'all',
      sourceFilter: 'all',
      filteredIndicators: [],
      showAddModal: false,
      addLoading: false,
      addError: '',
      newIndicator: {
        value: '',
        type: '',
        source_name: '',
        comment: ''
      },
      dataTypes: [],
      sourceNames: [],
      allSources: [],
      sortField: 'max_br_score',
      sortDirection: 'desc',
      showDetailModal: false,
      detailLoading: false,
      detailError: '',
      detailIndicator: null,
      commentSubmitting: false,
      commentError: '',
      commentForm: {
        text: '',
        source_name: ''
      },
      enrichingRow: {},
      enrichRowResult: {},
      bulkEnriching: false,
      bulkEnrichResult: null,
      enrichmentOptions: [],
      showEnrichmentSelectModal: false,
      enrichmentSearchQuery: '',
      selectedEnrichmentNames: [],
      pendingEnrichmentMode: 'single',
      pendingEnrichmentIndicator: null,
      runningSelectedEnrichment: false,
      availableTags: [],
      tagEditor: {
        sourceName: '',
        tags: [],
        selectedTag: '',
        saving: false,
        error: ''
      },
      showBulkAddModal: false,
      bulkAddInput: '',
      bulkAddComment: '',
      bulkAddLoading: false,
      bulkAddError: '',
      bulkAddResults: null,
      bulkAddType: '',
      bulkAddSourceName: '',
      bulkAddSourceNames: [],
      showImportUrlModal: false,
      importUrl: '',
      importType: '',
      importSourceName: '',
      importSourceNames: [],
      importImportSourceNamesLoading: false,
      importComment: '',
      importUrlLoading: false,
      importAddLoading: false,
      importError: '',
      importDetectedCount: null,
      importPreviewIndicators: [],
      importSelectedIndicators: [],
      importResultMessage: '',
      importResultError: false,
      timelineQuery: '',
      showTimelineModal: false,
      timelineLoading: false,
      timelineError: '',
      timelineInlineError: '',
      timelineIndicator: null,
      timelineSummary: null,
      timelineEvents: []
    }
  },
  async mounted() {
    await this.fetchIndicators(this.page)
    await this.fetchDataTypes()
    await this.fetchAllSources()
    await this.fetchEnrichmentOptions()
    await this.fetchAvailableTags()
  },
  methods: {
    async fetchAvailableTags() {
      try {
        const resp = await apiFetch('/api/tags', { headers: { 'Content-Type': 'application/json' } })
        if (!resp.ok) {
          this.availableTags = []
          return
        }
        const data = await resp.json()
        this.availableTags = Array.isArray(data.tags)
          ? data.tags.map(t => String(t.tag || '').trim()).filter(Boolean)
          : []
      } catch (e) {
        this.availableTags = []
      }
    },
    async fetchEnrichmentOptions() {
      try {
        const resp = await apiFetch('/api/data_enrichments', { headers: { 'Content-Type': 'application/json' } })
        if (!resp.ok) {
          this.enrichmentOptions = []
          return
        }
        const data = await resp.json()
        const enrichments = Array.isArray(data.enrichments)
          ? data.enrichments
          : (Array.isArray(data.data_enrichments) ? data.data_enrichments : [])
        this.enrichmentOptions = enrichments.filter(e => !!e.enabled)
      } catch (e) {
        this.enrichmentOptions = []
      }
    },
    openEnrichmentSelectModal(mode = 'single', indicator = null) {
      this.pendingEnrichmentMode = mode
      this.pendingEnrichmentIndicator = indicator
      this.enrichmentSearchQuery = ''
      this.selectedEnrichmentNames = []
      this.showEnrichmentSelectModal = true
    },
    closeEnrichmentSelectModal() {
      this.showEnrichmentSelectModal = false
      this.enrichmentSearchQuery = ''
      this.selectedEnrichmentNames = []
      this.pendingEnrichmentIndicator = null
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
      if (!this.detailIndicator || !this.tagEditor.sourceName) {
        return
      }

      this.tagEditor.saving = true
      this.tagEditor.error = ''
      try {
        const res = await apiFetch('/api/indicators/tag', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            value: this.detailIndicator.value,
            type: this.detailIndicator.type,
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
        await this.openDetailModal({ value: this.detailIndicator.value, type: this.detailIndicator.type })
      } catch (e) {
        this.tagEditor.error = 'Network error while updating tag.'
      } finally {
        this.tagEditor.saving = false
      }
    },
    async runSelectedEnrichments() {
      if (!this.selectedEnrichmentNames.length) return
      this.runningSelectedEnrichment = true
      try {
        if (this.pendingEnrichmentMode === 'bulk') {
          await this.enrichBulk([...this.selectedEnrichmentNames])
        } else if (this.pendingEnrichmentIndicator) {
          await this.enrichSingle(this.pendingEnrichmentIndicator, [...this.selectedEnrichmentNames])
        }
        this.closeEnrichmentSelectModal()
      } finally {
        this.runningSelectedEnrichment = false
      }
    },
    async fetchSourceNames(selectedType = '') {
      try {
        const params = new URLSearchParams();
        if (selectedType) {
          params.set('type', selectedType);
        }
        const path = params.toString() ? `/api/source_names?${params.toString()}` : '/api/source_names';
        const resp = await apiFetch(path, { headers: { 'Content-Type': 'application/json' } });
        if (resp.ok) {
          const data = await resp.json();
          this.sourceNames = data.source_names || [];
        } else {
          this.sourceNames = [];
        }
      } catch (e) {
        this.sourceNames = [];
      }
    },
    async onNewIndicatorTypeChange() {
      this.newIndicator.source_name = '';
      await this.fetchSourceNames(this.newIndicator.type);
    },
    async fetchAllSources() {
      try {
        const resp = await apiFetch('/api/indicators/sources', { headers: { 'Content-Type': 'application/json' } });
        if (resp.ok) {
          const data = await resp.json();
          this.allSources = data.sources || [];
        } else {
          this.allSources = [];
        }
      } catch (e) {
        this.allSources = [];
      }
    },
    async fetchDataTypes() {
      try {
        const resp = await apiFetch('/api/data_types', { headers: { 'Content-Type': 'application/json' } });
        if (resp.ok) {
          const data = await resp.json();
          this.dataTypes = data.data_types || [];
        } else {
          this.dataTypes = [];
        }
      } catch (e) {
        this.dataTypes = [];
      }
    },
    closeAddModal() {
      this.showAddModal = false;
      this.addError = '';
      this.addLoading = false;
      this.newIndicator = { value: '', type: '', source_name: '', comment: '' };
      this.sourceNames = [];
    },
    async submitNewIndicator() {
      if (!this.newIndicator.value || !this.newIndicator.type || !this.newIndicator.source_name) {
        this.addError = 'All fields are required.';
        return;
      }
      this.addLoading = true;
      this.addError = '';
      try {
        const headers = { 'Content-Type': 'application/json' };
        const resp = await apiFetch('/api/indicators/new', {
          method: 'POST',
          headers,
          body: JSON.stringify({
            value: this.newIndicator.value,
            type: this.newIndicator.type,
            sources: [{
              source_name: this.newIndicator.source_name,
              comment: this.newIndicator.comment || '',
              lastupdate_time: new Date().toISOString()
            }]
          })
        });
        if (!resp.ok) {
          const data = await resp.json();
          this.addError = data.message || 'Failed to add indicator.';
        } else {
          this.closeAddModal();
          await this.fetchIndicators(1);
        }
      } catch (e) {
        this.addError = 'Network error while adding indicator.';
      } finally {
        this.addLoading = false;
      }
    },
    openBulkAddModal() {
      this.showBulkAddModal = true;
      this.bulkAddInput = '';
      this.bulkAddComment = '';
      this.bulkAddError = '';
      this.bulkAddResults = null;
      this.bulkAddType = '';
      this.bulkAddSourceName = '';
      this.bulkAddSourceNames = [];
    },
    closeBulkAddModal() {
      this.showBulkAddModal = false;
      this.bulkAddInput = '';
      this.bulkAddComment = '';
      this.bulkAddError = '';
      this.bulkAddResults = null;
      this.bulkAddType = '';
      this.bulkAddSourceName = '';
      this.bulkAddSourceNames = [];
    },
    openImportUrlModal() {
      this.showImportUrlModal = true
      this.importUrl = ''
      this.importType = ''
      this.importSourceName = ''
      this.importSourceNames = []
      this.importImportSourceNamesLoading = false
      this.importComment = ''
      this.importUrlLoading = false
      this.importAddLoading = false
      this.importError = ''
      this.importDetectedCount = null
      this.importPreviewIndicators = []
      this.importSelectedIndicators = []
      this.importResultMessage = ''
      this.importResultError = false
    },
    closeImportUrlModal() {
      this.showImportUrlModal = false
      this.importError = ''
      this.importResultMessage = ''
      this.importResultError = false
    },
    async onImportTypeChange() {
      this.importSourceName = ''
      this.importSourceNames = []
      this.importError = ''
      this.importDetectedCount = null
      this.importPreviewIndicators = []
      this.importSelectedIndicators = []
      this.importResultMessage = ''
      this.importResultError = false
      if (!this.importType) {
        return
      }
      await this.fetchImportSourceNames(this.importType)
    },
    async fetchImportSourceNames(selectedType = '') {
      this.importImportSourceNamesLoading = true
      try {
        const params = new URLSearchParams()
        if (selectedType) {
          params.set('type', selectedType)
        }
        const path = params.toString() ? `/api/source_names?${params.toString()}` : '/api/source_names'
        const resp = await apiFetch(path, { headers: { 'Content-Type': 'application/json' } })
        if (resp.ok) {
          const data = await resp.json()
          this.importSourceNames = Array.isArray(data.source_names) ? data.source_names : []
        } else {
          this.importSourceNames = []
        }
      } catch (e) {
        this.importSourceNames = []
      } finally {
        this.importImportSourceNamesLoading = false
      }
    },
    async detectIndicatorsFromUrl() {
      if (!this.importUrl || !this.importType) {
        this.importError = 'URL and type are required for preview.'
        return
      }
      this.importUrlLoading = true
      this.importError = ''
      this.importDetectedCount = null
      this.importPreviewIndicators = []
      this.importSelectedIndicators = []
      this.importResultMessage = ''
      this.importResultError = false
      try {
        const resp = await apiFetch('/api/indicators/import-url/preview', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            url: this.importUrl,
            type: this.importType,
            max_results: 2000
          })
        })
        const data = await resp.json().catch(() => ({}))
        if (!resp.ok) {
          this.importError = data.message || 'Failed to detect indicators from URL.'
          return
        }
        this.importPreviewIndicators = Array.isArray(data.detected_indicators) ? data.detected_indicators : []
        this.importDetectedCount = Number.isFinite(data.detected_count) ? data.detected_count : this.importPreviewIndicators.length
        this.importSelectedIndicators = [...this.importPreviewIndicators]
      } catch (e) {
        this.importError = 'Network error while detecting indicators.'
      } finally {
        this.importUrlLoading = false
      }
    },
    selectAllImportPreview() {
      this.importSelectedIndicators = [...this.importPreviewIndicators]
    },
    clearImportPreviewSelection() {
      this.importSelectedIndicators = []
    },
    async submitImportSelected() {
      if (!this.importType || !this.importSourceName) {
        this.importError = 'Type and source name are required.'
        return
      }
      if (!this.importSelectedIndicators.length) {
        this.importError = 'Select at least one detected indicator.'
        return
      }

      this.importAddLoading = true
      this.importError = ''
      this.importResultMessage = ''
      this.importResultError = false

      const nowIso = new Date().toISOString()
      const indicators = this.importSelectedIndicators.map((value) => ({
        value,
        type: this.importType,
        sources: [{
          source_name: this.importSourceName,
          comment: this.importComment || '',
          lastupdate_time: nowIso
        }]
      }))

      try {
        const resp = await apiFetch('/api/indicators/bulk-add', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ indicators })
        })
        const data = await resp.json().catch(() => ({}))
        if (!resp.ok) {
          this.importResultError = true
          this.importResultMessage = data.message || 'Failed to add selected indicators.'
          return
        }

        this.importResultError = false
        this.importResultMessage = data.message || 'Indicators imported successfully.'
        await this.fetchIndicators(1)
      } catch (e) {
        this.importResultError = true
        this.importResultMessage = 'Network error while adding imported indicators.'
      } finally {
        this.importAddLoading = false
      }
    },
    async onBulkAddTypeChange() {
      this.bulkAddSourceName = '';
      await this.fetchBulkAddSourceNames(this.bulkAddType);
    },
    async fetchBulkAddSourceNames(selectedType = '') {
      try {
        const params = new URLSearchParams();
        if (selectedType) {
          params.set('type', selectedType);
        }
        const path = params.toString() ? `/api/source_names?${params.toString()}` : '/api/source_names';
        const resp = await apiFetch(path, { headers: { 'Content-Type': 'application/json' } });
        if (resp.ok) {
          const data = await resp.json();
          this.bulkAddSourceNames = data.source_names || [];
        } else {
          this.bulkAddSourceNames = [];
        }
      } catch (e) {
        this.bulkAddSourceNames = [];
      }
    },
    async submitBulkAdd() {
      if (!this.bulkAddType) {
        this.bulkAddError = 'Please select a type.';
        return;
      }
      if (!this.bulkAddSourceName) {
        this.bulkAddError = 'Please select a source name.';
        return;
      }
      if (!this.bulkAddInput.trim()) {
        this.bulkAddError = 'Please enter at least one indicator value.';
        return;
      }

      // Parse input: each line is a value
      const lines = this.bulkAddInput.split('\n').map(l => l.trim()).filter(l => l.length > 0);
      const indicators = [];

      for (const value of lines) {
        indicators.push({
          value: value,
          type: this.bulkAddType,
          sources: [{
            source_name: this.bulkAddSourceName,
            comment: this.bulkAddComment || '',
            lastupdate_time: new Date().toISOString()
          }]
        });
      }

      this.bulkAddLoading = true;
      this.bulkAddError = '';
      try {
        const headers = { 'Content-Type': 'application/json' };
        const resp = await apiFetch('/api/indicators/bulk-add', {
          method: 'POST',
          headers,
          body: JSON.stringify({ indicators })
        });
        if (!resp.ok) {
          const data = await resp.json();
          this.bulkAddError = data.message || 'Failed to add indicators.';
        } else {
          const data = await resp.json();
          this.bulkAddResults = data;
          await this.fetchIndicators(1);
        }
      } catch (e) {
        this.bulkAddError = 'Network error while adding indicators.';
      } finally {
        this.bulkAddLoading = false;
      }
    },
    async fetchIndicators(page = 1) {
      this.loading = true
      this.error = null
      try {
        const params = new URLSearchParams({ page: String(page), limit: String(this.limit) })
        if (this.search && this.search.trim()) {
          params.append('search', this.search.trim())
        }
        if (this.activeStatus !== 'all') {
          params.append('active', this.activeStatus === 'active' ? 'true' : 'false')
        }
        if (this.sourceFilter !== 'all') {
          params.append('source', this.sourceFilter)
        }
        const resp = await apiFetch(`/api/indicators?${params.toString()}`, { headers: { 'Content-Type': 'application/json' } })
        const data = await resp.json()
        if (!resp.ok) {
          this.error = data.message || 'Failed to fetch indicators.'
        } else {
          this.indicators = data.indicators || []
          this.page = data.page || page
          this.pages = data.pages || 1
          this.total = data.total || 0
          this.filteredIndicators = this.indicators
        }
      } catch (e) {
        this.error = 'Network error while fetching indicators.'
      } finally {
        this.loading = false
      }
    },
    prevPage() {
      if (this.page > 1) this.fetchIndicators(this.page - 1)
    },
    nextPage() {
      if (this.page < this.pages) this.fetchIndicators(this.page + 1)
    },
    gotoPage(p) {
      if (p >= 1 && p <= this.pages) this.fetchIndicators(p)
    },
    onSearch() {
      this.fetchIndicators(1)
    },
    onStatusChange() {
      this.fetchIndicators(1)
    },
    onSourceChange() {
      this.fetchIndicators(1)
    },
    toggleSort(field) {
      if (this.sortField === field) {
        this.sortDirection = this.sortDirection === 'asc' ? 'desc' : 'asc'
      } else {
        this.sortField = field
        this.sortDirection = 'asc'
      }
      this.sortIndicators()
    },
    sortIndicators() {
      const arr = [...this.filteredIndicators]
      arr.sort((a, b) => {
        let aVal = a[this.sortField]
        let bVal = b[this.sortField]
        if (aVal === null || aVal === undefined) aVal = this.sortField === 'max_br_score' ? -Infinity : ''
        if (bVal === null || bVal === undefined) bVal = this.sortField === 'max_br_score' ? -Infinity : ''
        if (typeof aVal === 'string') aVal = aVal.toLowerCase()
        if (typeof bVal === 'string') bVal = bVal.toLowerCase()
        if (aVal < bVal) return this.sortDirection === 'asc' ? -1 : 1
        if (aVal > bVal) return this.sortDirection === 'asc' ? 1 : -1
        return 0
      })
      this.filteredIndicators = arr
    },
    async openDetailModal(indicator) {
      this.showDetailModal = true
      this.detailIndicator = null
      this.detailError = ''
      this.commentError = ''
      this.commentSubmitting = false
      this.commentForm = { text: '', source_name: '' }
      this.detailLoading = true
      try {
        const params = new URLSearchParams({ value: indicator.value })
        if (indicator.type) params.append('type', indicator.type)
        const res = await apiFetch(`/api/indicators/detail?${params.toString()}`)
        const data = await res.json()
        if (!res.ok) {
          this.detailError = data.message || 'Failed to fetch indicator detail.'
        } else {
          this.detailIndicator = data.indicator || null
          const detailSources = this.detailIndicator && Array.isArray(this.detailIndicator.sources) ? this.detailIndicator.sources : []
          this.commentForm.source_name = detailSources.length ? String(detailSources[0].source_name || '').trim() : ''
        }
      } catch (e) {
        this.detailError = 'Network error while fetching indicator detail.'
      } finally {
        this.detailLoading = false
      }
    },
    closeDetailModal() {
      this.showDetailModal = false
      this.detailIndicator = null
      this.detailError = ''
      this.commentError = ''
      this.commentSubmitting = false
      this.commentForm = { text: '', source_name: '' }
    },
    async submitIndicatorComment() {
      if (!this.detailIndicator) {
        return
      }

      const commentText = String(this.commentForm.text || '').trim()
      if (!commentText) {
        this.commentError = 'Please enter a comment.'
        return
      }
      if (!this.commentForm.source_name) {
        this.commentError = 'Please select a source scope.'
        return
      }

      this.commentSubmitting = true
      this.commentError = ''
      try {
        const res = await apiFetch('/api/indicators/comment', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            value: this.detailIndicator.value,
            type: this.detailIndicator.type,
            source_name: this.commentForm.source_name,
            comment: commentText
          })
        })
        const data = await res.json().catch(() => ({}))
        if (!res.ok) {
          this.commentError = data.message || 'Failed to save comment.'
          return
        }

        this.commentForm = { text: '', source_name: this.commentForm.source_name || '' }
        await this.openDetailModal({ value: this.detailIndicator.value, type: this.detailIndicator.type })
      } catch (e) {
        this.commentError = 'Network error while saving comment.'
      } finally {
        this.commentSubmitting = false
      }
    },
    async enrichSingle(indicator, selectedEnrichments = []) {
      const key = indicator.value + '|' + indicator.type
      this.$set ? this.$set(this.enrichingRow, key, true) : (this.enrichingRow = { ...this.enrichingRow, [key]: true })
      this.$set ? this.$set(this.enrichRowResult, key, null) : (this.enrichRowResult = { ...this.enrichRowResult, [key]: null })
      try {
        const res = await apiFetch('/api/indicators/enrich', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ value: indicator.value, type: indicator.type, selected_enrichments: selectedEnrichments })
        })
        const data = await res.json()
        const result = { ok: res.ok, message: data.message || (res.ok ? 'Done' : 'Error') }
        this.enrichingRow = { ...this.enrichingRow, [key]: false }
        this.enrichRowResult = { ...this.enrichRowResult, [key]: result }
        if (res.ok) {
          setTimeout(() => {
            this.enrichRowResult = { ...this.enrichRowResult, [key]: null }
          }, 4000)
        }
      } catch (e) {
        this.enrichingRow = { ...this.enrichingRow, [key]: false }
        this.enrichRowResult = { ...this.enrichRowResult, [key]: { ok: false, message: 'Network error' } }
      }
    },
    async enrichBulk(selectedEnrichments = []) {
      this.bulkEnriching = true
      this.bulkEnrichResult = null
      try {
        const items = this.filteredIndicators.map(i => ({ value: i.value, type: i.type }))
        const res = await apiFetch('/api/indicators/enrich-bulk', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ indicators: items, selected_enrichments: selectedEnrichments })
        })
        const data = await res.json()
        this.bulkEnrichResult = { error: !res.ok, message: data.message || (res.ok ? 'Done' : 'Error') }
        if (res.ok) await this.fetchIndicators(this.page)
      } catch (e) {
        this.bulkEnrichResult = { error: true, message: 'Network error during bulk enrichment.' }
      } finally {
        this.bulkEnriching = false
      }
    },
    formatDetailDate(value) {
      if (!value) return '-'
      const date = new Date(value)
      if (Number.isNaN(date.getTime())) return String(value)
      return date.toLocaleString()
    },
    closeTimelineModal() {
      this.showTimelineModal = false
      this.timelineError = ''
    },
    async openTimelineFromInput() {
      const value = String(this.timelineQuery || '').trim()
      if (!value) {
        this.timelineInlineError = 'Please enter an indicator value.'
        return
      }
      this.timelineInlineError = ''
      this.showTimelineModal = true
      await this.fetchIndicatorTimeline({ value })
    },
    async openTimelineFromRow(indicator) {
      this.timelineQuery = String((indicator && indicator.value) || '').trim()
      this.timelineInlineError = ''
      this.showTimelineModal = true
      await this.fetchIndicatorTimeline({
        value: this.timelineQuery,
        type: String((indicator && indicator.type) || '').trim()
      })
    },
    async fetchIndicatorTimeline({ value, type = '' }) {
      this.timelineLoading = true
      this.timelineError = ''
      this.timelineIndicator = null
      this.timelineSummary = null
      this.timelineEvents = []
      try {
        const params = new URLSearchParams({ value: String(value || '').trim() })
        if (type) {
          params.set('type', String(type).trim())
        }
        const res = await apiFetch(`/api/indicators/timeline?${params.toString()}`)
        const data = await res.json().catch(() => ({}))
        if (!res.ok) {
          this.timelineError = data.message || 'Failed to load indicator timeline.'
          return
        }
        this.timelineIndicator = data.indicator || null
        this.timelineSummary = data.summary || null
        this.timelineEvents = Array.isArray(data.timeline) ? data.timeline : []
      } catch (e) {
        this.timelineError = 'Network error while loading indicator timeline.'
      } finally {
        this.timelineLoading = false
      }
    }
  }
}
</script>

<style scoped>
.table { font-size: 0.95rem; }
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
.enrichment-modal-overlay {
  z-index: 1200;
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
