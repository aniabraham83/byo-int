<template>
  <div class="container mt-4 pb-5">
    <div class="d-flex justify-content-between align-items-center mb-4">
      <div>
        <h2 class="mb-1">Datapull Templates</h2>
        <p class="text-muted">Manage and create datapull templates</p>
      </div>
      <button class="btn btn-primary btn-lg" @click="openAddModal" title="Add new template">
        <i class="me-2">+</i> New Template
      </button>
    </div>

    <div v-if="loading" class="mt-3">
      <div class="spinner-border text-primary" role="status">
        <span class="visually-hidden">Loading...</span>
      </div>
    </div>

    <div v-else>
      <div v-if="templates.length === 0" class="alert alert-info">
        <i class="me-2">ℹ️</i> No templates found. <a href="#" @click.prevent="openAddModal">Create one</a>
      </div>
      <div v-else class="table-responsive">
        <table class="table table-striped table-hover">
          <thead class="table-light">
            <tr>
              <th>Name</th>
              <th>Info</th>
              <th>Type</th>
              <th>Description</th>
              <th>Function Mapping</th>
              <th>Fields (Required?)</th>
              <th>Created</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="tpl in templates" :key="tpl.template_name + tpl.created_at">
              <td>{{ tpl.template_name }}</td>
              <td>
                <button
                  type="button"
                  class="btn btn-outline-secondary btn-sm"
                  title="View template info"
                  @click="openTemplateInfo(tpl)"
                >
                  i
                </button>
              </td>
              <td>{{ tpl.template_type }}</td>
              <td>{{ tpl.description }}</td>
              <td><code>{{ tpl.function_mapping }}</code></td>
              <td>
                <span v-if="Array.isArray(tpl.ufield_args) && tpl.ufield_args.length">
                  <ul class="mb-0 ps-3">
                    <li v-for="(arg, idx) in tpl.ufield_args" :key="idx">
                      <span>{{ arg.field_name }}</span>
                      <span v-if="arg.mandatory === true || arg.mandatory === 'true'" class="text-danger">(required)</span>
                      <span v-else class="text-muted">(optional)</span>
                    </li>
                  </ul>
                </span>
                <span v-else class="text-muted">—</span>
              </td>
              <td><small>{{ tpl.created_at }}</small></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Add Template Modal -->
    <div v-if="showAddModal" class="modal-overlay" @click.self="closeAddModal">
      <div class="modal-content">
        <div class="modal-header">
          <h5 class="modal-title">Create New Datapull Template</h5>
          <button type="button" class="btn-close" @click="closeAddModal"></button>
        </div>
        <div class="modal-body">
          <form @submit.prevent="submitNewTemplate">
            <div class="mb-3">
              <label class="form-label">Template Name</label>
              <input v-model="formData.template_name" type="text" class="form-control" required>
            </div>
            <div class="mb-3">
              <label class="form-label">Template Type</label>
              <select v-model="formData.template_type" class="form-select" required>
                <option value="">-- Select a type --</option>
                <option value="builtin">Built-in</option>
                <option value="Custom">Custom</option>
              </select>
            </div>
            <div class="mb-3">
              <label class="form-label">Description</label>
              <input v-model="formData.description" type="text" class="form-control">
            </div>
            <div class="mb-3">
              <label class="form-label">Info</label>
              <textarea
                v-model="formData.info"
                class="form-control"
                rows="4"
                placeholder="Explain what this template extracts and how it turns source content into indicators"
              ></textarea>
              <div class="form-text">This text appears behind the info button for each template.</div>
            </div>
            <div v-if="formData.template_type === 'builtin'" class="mb-3">
              <label class="form-label">Function Mapping</label>
              <input v-model="formData.function_mapping" type="text" class="form-control" placeholder="e.g. url_scraper_v1">
            </div>
            <div v-if="formData.template_type === 'Custom'" class="mb-3">
              <label class="form-label">Python Snippet</label>
              <textarea
                v-model="formData.python_snippet"
                class="form-control"
                rows="8"
                placeholder="Write Python snippet here"
              ></textarea>
            </div>
            <div v-if="formData.template_type === 'Custom'" class="alert alert-info small">
              <div><strong>Custom template guidance</strong></div>
              <div>Fields added in <strong>ufield_args</strong> are available in snippet code as variables (for example, <strong>url</strong>) and also via <strong>template_args</strong>/<strong>kwargs</strong>.</div>
              <div class="mt-1">Your snippet must produce <strong>result_list</strong> (array of values or objects like <strong>{ value, dtype }</strong>) so indicators can be written.</div>
              <div class="mt-2">
                <button type="button" class="btn btn-sm btn-outline-primary" @click="applyCustomSnippetExample">
                  Use example snippet
                </button>
              </div>
              <pre class="mt-2 mb-0 p-2 bg-light border rounded" style="white-space: pre-wrap; font-size: 0.75rem;">{{ customSnippetExample }}</pre>
            </div>
            <div v-if="formData.template_type === 'Custom'" class="mb-3">
              <label class="form-label">Fields (ufield_args)</label>
              <div
                v-for="(field, idx) in formData.ufield_args"
                :key="idx"
                class="d-flex align-items-center gap-2 mb-2"
              >
                <input
                  v-model="field.field_name"
                  type="text"
                  class="form-control"
                  placeholder="Field name"
                >
                <button type="button" class="btn btn-outline-danger btn-sm" @click="removeCustomField(idx)">
                  Remove
                </button>
              </div>
              <button type="button" class="btn btn-outline-primary btn-sm" @click="addCustomField">
                + Add Field
              </button>
            </div>

            <!-- Test Snippet panel (Custom only) -->
            <div v-if="formData.template_type === 'Custom'" class="mb-3 border rounded p-3 bg-light">
              <div class="d-flex justify-content-between align-items-center mb-2">
                <strong>Test Snippet</strong>
                <button type="button" class="btn btn-outline-secondary btn-sm" @click="showTestPanel = !showTestPanel">
                  {{ showTestPanel ? 'Hide' : 'Show' }}
                </button>
              </div>
              <div v-if="showTestPanel">
                <p class="text-muted small mb-2">Provide sample values for each field and run a dry-run test (nothing is saved).</p>
                <div v-if="formData.ufield_args.length === 0" class="text-muted small mb-2">
                  Add fields above to provide sample values.
                </div>
                <div
                  v-for="(field, idx) in formData.ufield_args.filter(f => f.field_name && f.field_name.trim())"
                  :key="'test-' + idx"
                  class="d-flex align-items-center gap-2 mb-2"
                >
                  <label class="form-label mb-0 text-nowrap" style="min-width: 120px;">{{ field.field_name }}</label>
                  <input
                    v-model="testKwargs[field.field_name]"
                    type="text"
                    class="form-control form-control-sm"
                    :placeholder="'Sample value for ' + field.field_name"
                  >
                </div>
                <button
                  type="button"
                  class="btn btn-outline-primary btn-sm mt-1"
                  @click="runSnippetTest"
                  :disabled="testingSnippet || !formData.python_snippet.trim()"
                >
                  <span v-if="testingSnippet" class="spinner-border spinner-border-sm me-1"></span>
                  {{ testingSnippet ? 'Running...' : 'Run Test' }}
                </button>
                <div v-if="testSnippetResult" class="mt-3 alert" :class="testSnippetResult.error ? 'alert-warning' : 'alert-info'">
                  <div v-if="testSnippetResult.error">
                    <strong>Error:</strong> {{ testSnippetResult.error }}
                  </div>
                  <div v-else>
                    <div class="mb-1"><strong>Preview</strong> ({{ testSnippetResult.total }} total{{ testSnippetResult.truncated ? ', showing first 20' : '' }}):</div>
                    <div class="text-muted small mb-1">{{ testSnippetResult.log }}</div>
                    <pre class="text-break mb-0" style="font-size: 0.78rem; max-height: 200px; overflow-y: auto;">{{ JSON.stringify(testSnippetResult.preview, null, 2) }}</pre>
                  </div>
                </div>
              </div>
            </div>
            <div v-if="message" class="alert alert-warning small">{{ message }}</div>
          </form>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" @click="closeAddModal">Cancel</button>
          <button type="button" class="btn btn-primary" @click="submitNewTemplate" :disabled="isSubmitting">
            <span v-if="isSubmitting" class="spinner-border spinner-border-sm me-2"></span>
            {{ isSubmitting ? 'Creating...' : 'Create Template' }}
          </button>
        </div>
      </div>
    </div>

    <!-- Template Info Modal -->
    <div v-if="showInfoModal" class="modal-overlay" @click.self="closeTemplateInfo">
      <div class="modal-content">
        <div class="modal-header">
          <h5 class="modal-title">{{ selectedTemplate?.template_name || 'Template Info' }}</h5>
          <button type="button" class="btn-close" @click="closeTemplateInfo"></button>
        </div>
        <div class="modal-body">
          <div class="mb-2">
            <span class="badge bg-secondary me-2">{{ selectedTemplate?.template_type || 'unknown' }}</span>
            <span v-if="selectedTemplate?.description" class="text-muted">{{ selectedTemplate.description }}</span>
          </div>
          <div class="border rounded bg-light p-3" style="white-space: pre-wrap;">
            {{ selectedTemplateInfoText }}
          </div>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" @click="closeTemplateInfo">Close</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { apiFetch } from '@/api'

export default {
  name: 'DatapullTemplates',
  data() {
    return {
      templates: [],
      loading: false,
      showAddModal: false,
      showInfoModal: false,
      isSubmitting: false,
      message: '',
      showTestPanel: false,
      testingSnippet: false,
      testKwargs: {},
      testSnippetResult: null,
      selectedTemplate: null,
      customSnippetExample: [
        "target_url = url if 'url' in locals() else template_args.get('url')",
        "if not target_url:",
        "    raise ValueError('Missing required ufield arg: url')",
        "",
        "response = requests.get(target_url, timeout=30)",
        "response.raise_for_status()",
        "",
        "result_list = []",
        "for line in response.text.splitlines():",
        "    value = line.strip()",
        "    if value and not value.startswith('#'):",
        "        result_list.append(value)"
      ].join('\n'),
      formData: {
        template_name: '',
        template_type: '',
        description: '',
        info: '',
        function_mapping: '',
        python_snippet: '',
        ufield_args: []
      }
    }
  },
  computed: {
    selectedTemplateInfoText() {
      const info = (this.selectedTemplate && this.selectedTemplate.info) ? String(this.selectedTemplate.info).trim() : '';
      return info || 'No info has been provided for this template yet.';
    }
  },
  methods: {
    openAddModal() {
      this.showAddModal = true;
      this.resetForm();
    },
    closeAddModal() {
      this.showAddModal = false;
      this.resetForm();
    },
    resetForm() {
      this.formData = {
        template_name: '',
        template_type: '',
        description: '',
        info: '',
        function_mapping: '',
        python_snippet: '',
        ufield_args: []
      };
      this.message = '';
      this.showTestPanel = false;
      this.testKwargs = {};
      this.testSnippetResult = null;
    },
    openTemplateInfo(template) {
      this.selectedTemplate = template || null;
      this.showInfoModal = true;
    },
    closeTemplateInfo() {
      this.showInfoModal = false;
      this.selectedTemplate = null;
    },
    addCustomField() {
      this.formData.ufield_args.push({ field_name: '', mandatory: false });
    },
    removeCustomField(index) {
      this.formData.ufield_args.splice(index, 1);
    },
    applyCustomSnippetExample() {
      this.formData.python_snippet = this.customSnippetExample;
    },
    async runSnippetTest() {
      this.testSnippetResult = null;
      if (!this.formData.python_snippet.trim()) return;
      this.testingSnippet = true;
      try {
        const kwargs = {};
        for (const field of this.formData.ufield_args) {
          const name = (field.field_name || '').trim();
          if (name) kwargs[name] = this.testKwargs[name] || '';
        }
        const res = await apiFetch('/api/datapull_templates/test', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ snippet_code: this.formData.python_snippet, kwargs })
        });
        const data = await res.json();
        if (!res.ok) {
          this.testSnippetResult = { error: data.message || 'Test failed' };
        } else {
          this.testSnippetResult = {
            preview: data.preview,
            total: data.total,
            log: data.log,
            truncated: data.truncated
          };
        }
      } catch (e) {
        this.testSnippetResult = { error: 'Network error: ' + e.message };
      } finally {
        this.testingSnippet = false;
      }
    },
    async fetchTemplates() {
      this.loading = true;
      try {
        const res = await apiFetch('/api/datapull_templates', {
          method: 'GET'
        });
        if (res.ok) {
          const data = await res.json();
          this.templates = Array.isArray(data.templates) ? data.templates : [];

        } else {
          this.templates = [];
        }
      } catch (e) {
        this.templates = [];
      } finally {
        this.loading = false;
      }
    },

    async submitNewTemplate() {
      this.isSubmitting = true;
      this.message = '';
      try {
        const payload = {
          ...this.formData,
          function_mapping: this.formData.template_type === 'builtin' ? this.formData.function_mapping : '',
          python_snippet: this.formData.template_type === 'Custom' ? this.formData.python_snippet : '',
          snippet_code: this.formData.template_type === 'Custom' ? this.formData.python_snippet : '',
          info: this.formData.info,
          ufield_args: this.formData.template_type === 'Custom'
            ? this.formData.ufield_args.filter((f) => (f.field_name || '').trim()).map((f) => ({ field_name: f.field_name.trim(), mandatory: false }))
            : []
        };
        const res = await apiFetch('/api/datapull_templates/create', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (res.ok) {
          this.message = 'Template created!';
          this.closeAddModal();
          await this.fetchTemplates();
        } else {
          this.message = data.message || 'Error creating template.';
        }
      } catch (e) {
        this.message = 'Error connecting to server.';
      } finally {
        this.isSubmitting = false;
      }
    }
  },
  mounted() {
    this.fetchTemplates();
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

  .table-responsive {
    border-radius: 8px;
    overflow: hidden;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
  }

  .table-hover tbody tr:hover {
    background-color: #f8f9fa;
  }

  .btn-lg {
    padding: 0.75rem 1.5rem;
    font-size: 1rem;
    border-radius: 8px;
    transition: all 0.3s ease;
  }

  .btn-lg:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  }

  code {
    background-color: #f5f5f5;
    padding: 0.2rem 0.4rem;
    border-radius: 4px;
    font-size: 0.85rem;
  }

  @media (max-width: 768px) {
    .modal-content {
      width: 95%;
    }
    .d-flex {
      flex-direction: column;
      gap: 1rem;
    }
    .btn-lg {
      width: 100%;
    }
  }
</style>
