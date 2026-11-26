<template>
  <div class="container mt-4 pb-5">
    <div class="d-flex justify-content-between align-items-center mb-4">
      <div>
        <h2 class="mb-1">Feed: {{ outputname }}</h2>
        <p class="text-muted mb-0">Vue-rendered EDL feed output</p>
      </div>
      <button class="btn btn-primary" @click="fetchFeed" :disabled="loading">
        <span v-if="loading" class="spinner-border spinner-border-sm me-2"></span>
        Refresh
      </button>
    </div>

    <div v-if="loading" class="mt-3">
      <div class="spinner-border text-primary" role="status">
        <span class="visually-hidden">Loading...</span>
      </div>
    </div>

    <div v-else-if="error" class="alert alert-danger">{{ error }}</div>

    <div v-else>
      <div class="card">
        <div class="card-header d-flex justify-content-between align-items-center">
          <div>
            <strong>{{ feed.name || outputname }}</strong>
            <span class="ms-2 text-muted">Source: {{ feed.source_name || '-' }}</span>
          </div>
          <div>
            <span class="badge bg-info me-2">{{ feed.type || '-' }}</span>
            <span class="badge bg-secondary">Count: {{ feed.indicator_count || 0 }}</span>
          </div>
        </div>
        <div class="card-body">
          <div class="small text-muted mb-2" v-if="feed.filter_search">Filter: {{ feed.filter_search }}</div>
          <div class="feed-html" v-html="feed.edl || ''"></div>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { apiFetch } from '@/api'

export default {
  name: 'FeedViewPage',
  data() {
    return {
      outputname: '',
      feed: {},
      loading: false,
      error: ''
    }
  },
  async mounted() {
    this.outputname = (this.$route.params.outputname || '').toString()
    await this.fetchFeed()
  },
  watch: {
    '$route.params.outputname': {
      immediate: false,
      async handler(val) {
        this.outputname = (val || '').toString()
        await this.fetchFeed()
      }
    }
  },
  methods: {
    async fetchFeed() {
      if (!this.outputname) {
        this.error = 'Missing output name.'
        this.feed = {}
        return
      }

      this.loading = true
      this.error = ''
      try {
        const res = await apiFetch(`/api/feeds/${encodeURIComponent(this.outputname)}`)
        const data = await res.json()

        if (!res.ok) {
          this.error = data.message || 'Failed to load feed'
          this.feed = {}
          return
        }

        this.feed = data.feed || {}
      } catch (e) {
        this.error = 'Network error while loading feed'
        this.feed = {}
      } finally {
        this.loading = false
      }
    }
  }
}
</script>

<style scoped>
.feed-html {
  background: #fff;
  border: 1px solid #e9ecef;
  border-radius: 6px;
  padding: 0.75rem;
  max-height: 70vh;
  overflow: auto;
  font-family: monospace;
  font-size: 0.85rem;
  line-height: 1.4;
}
</style>
