const API_BASE = process.env.VUE_APP_API_BASE || ''

export function apiUrl(path) {
  if (/^https?:\/\//i.test(path)) {
    return path
  }

  return `${API_BASE}${path}`
}

export function apiFetch(path, options = {}) {
  const { headers = {}, credentials = 'include', ...rest } = options

  return fetch(apiUrl(path), {
    credentials,
    headers,
    ...rest
  })
}

export async function fetchCurrentUser() {
  try {
    const res = await apiFetch('/api/whoami')
    if (!res.ok) {
      return null
    }

    const data = await res.json()
    return data.user || null
  } catch (e) {
    return null
  }
}

export async function fetchCurrentIdentity() {
  const res = await apiFetch('/api/whoami')
  const data = await res.json().catch(() => ({}))

  if (!res.ok) {
    throw new Error(data.message || 'Failed to fetch current identity.')
  }

  return {
    user: data.user || null,
    roles: Array.isArray(data.roles) ? data.roles : [],
    pageAccessMap: (data.page_access_map && typeof data.page_access_map === 'object') ? data.page_access_map : {}
  }
}

export async function logoutSession() {
  try {
    await apiFetch('/api/logout', { method: 'POST' })
  } catch (e) {
    // ignore logout network failures and continue local navigation
  }
}

export async function fetchSsoConfig() {
  try {
    const res = await apiFetch('/api/auth/sso/config')
    if (!res.ok) {
      return { enabled: false }
    }

    return await res.json()
  } catch (e) {
    return { enabled: false }
  }
}

export async function rotateCurrentUserApiKey() {
  const res = await apiFetch('/api/users/me/apikey', {
    method: 'POST'
  })

  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new Error(data.message || 'Failed to generate API key.')
  }

  return data
}

export async function grantUserRole(username, role) {
  const res = await apiFetch(`/api/users/${encodeURIComponent(username)}/roles/grant`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ role })
  })

  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new Error(data.message || 'Failed to grant role.')
  }

  return data
}

export async function revokeUserRole(username, role) {
  const res = await apiFetch(`/api/users/${encodeURIComponent(username)}/roles/revoke`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ role })
  })

  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new Error(data.message || 'Failed to revoke role.')
  }

  return data
}

  // Phase 6: Metrics & Observability helpers
  export async function fetchDatapullMetrics({ source_name = '', time_range_minutes = '1440' } = {}) {
    const params = new URLSearchParams()
    if (source_name) params.append('source_name', source_name)
    params.append('time_range_minutes', time_range_minutes)

    const res = await apiFetch(`/api/datapull/metrics?${params.toString()}`)
    const data = await res.json().catch(() => ({}))

    if (!res.ok) {
      throw new Error(data.error || data.message || 'Failed to fetch metrics.')
    }

    return data
  }

  export async function fetchDatapullMetricsBySource({ time_range_minutes = '1440', limit = 50 } = {}) {
    const params = new URLSearchParams()
    params.append('time_range_minutes', time_range_minutes)
    params.append('limit', limit)

    const res = await apiFetch(`/api/datapull/metrics/by-source?${params.toString()}`)
    const data = await res.json().catch(() => ({}))

    if (!res.ok) {
      throw new Error(data.error || data.message || 'Failed to fetch per-source metrics.')
    }

    return data
  }
export async function fetchDashboardMetrics() {
  const res = await apiFetch('/api/dashboard/metrics')
  const data = await res.json().catch(() => ({}))

  if (!res.ok) {
    throw new Error(data.message || 'Failed to fetch dashboard metrics.')
  }

  return data
}

export async function fetchDashboardFlow() {
  const res = await apiFetch('/api/dashboard/flow')
  const data = await res.json().catch(() => ({}))

  if (!res.ok) {
    throw new Error(data.message || 'Failed to fetch dashboard flow.')
  }

  return data
}

export async function fetchDatapullQueueStatus() {
  const res = await apiFetch('/api/datapull/queue-status')
  const data = await res.json().catch(() => ({}))

  if (!res.ok) {
    throw new Error(data.error || data.message || 'Failed to fetch queue status.')
  }

  return data
}

export async function fetchDatapullJobs({ status = '', sourceName = '', limit = 100 } = {}) {
  const params = new URLSearchParams()
  if (status) {
    params.set('status', status)
  }
  if (sourceName) {
    params.set('source_name', sourceName)
  }
  params.set('limit', String(limit))

  const res = await apiFetch(`/api/datapull/jobs?${params.toString()}`)
  const data = await res.json().catch(() => ({}))

  if (!res.ok) {
    throw new Error(data.error || data.message || 'Failed to fetch datapull jobs.')
  }

  return Array.isArray(data.jobs) ? data.jobs : []
}

export async function fetchDeadLetterJobs(limit = 100) {
  const params = new URLSearchParams()
  params.set('limit', String(limit))

  const res = await apiFetch(`/api/datapull/dead-letter-queue?${params.toString()}`)
  const data = await res.json().catch(() => ({}))

  if (!res.ok) {
    throw new Error(data.error || data.message || 'Failed to fetch dead-letter jobs.')
  }

  return Array.isArray(data.dead_letters) ? data.dead_letters : []
}

export async function fetchDatapullJob(jobId) {
  const res = await apiFetch(`/api/datapull/job/${encodeURIComponent(jobId)}`)
  const data = await res.json().catch(() => ({}))

  if (!res.ok) {
    throw new Error(data.error || data.message || `Failed to fetch job ${jobId}.`)
  }

  return data.job || null
}

export async function requeueDeadLetterJob(jobId) {
  const res = await apiFetch('/api/datapull/dead-letter-queue/requeue', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ job_id: jobId })
  })

  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new Error(data.error || data.message || 'Failed to requeue dead-letter job.')
  }

  return data
}

export async function fetchWorkerScalingConfig() {
  const res = await apiFetch('/api/configuration/workers')
  const data = await res.json().catch(() => ({}))

  if (!res.ok) {
    throw new Error(data.message || 'Failed to fetch worker scaling config.')
  }

  return data
}

export async function updateWorkerScalingConfig(workerScaling) {
  const res = await apiFetch('/api/configuration/workers/update', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      worker_scaling: workerScaling
    })
  })

  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new Error(data.message || 'Failed to update worker scaling config.')
  }

  return data
}

export async function fetchAuditLogs({ limit = 100, skip = 0, method = '', path = '', user = '', status_code = '' } = {}) {
  const params = new URLSearchParams()
  params.set('limit', String(limit))
  params.set('skip', String(skip))
  if (method) params.set('method', method)
  if (path) params.set('path', path)
  if (user) params.set('user', user)
  if (status_code) params.set('status_code', String(status_code))

  const res = await apiFetch(`/api/audit-logs?${params.toString()}`)
  const data = await res.json().catch(() => ({}))

  if (!res.ok) {
    throw new Error(data.message || 'Failed to fetch audit logs.')
  }

  return data
}

export async function fetchPlatformChangeLogs({ limit = 100, skip = 0, action = '', source = '', actor = '', entity = '', search = '' } = {}) {
  const params = new URLSearchParams()
  params.set('limit', String(limit))
  params.set('skip', String(skip))
  if (action) params.set('action', action)
  if (source) params.set('source', source)
  if (actor) params.set('actor', actor)
  if (entity) params.set('entity', entity)
  if (search) params.set('search', search)

  const res = await apiFetch(`/api/platform-change-logs?${params.toString()}`)
  const data = await res.json().catch(() => ({}))

  if (!res.ok) {
    throw new Error(data.message || 'Failed to fetch platform change logs.')
  }

  return data
}

export async function applyWorkerScaling(desiredWorkerCount) {
  const res = await apiFetch('/api/configuration/workers/apply', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      desired_worker_count: desiredWorkerCount
    })
  })

  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new Error(data.message || 'Failed to apply worker scaling.')
  }

  return data
}

// Output Guardrails API
export async function fetchOutputGuardrails() {
  const res = await apiFetch('/api/output-guardrails')
  const data = await res.json().catch(() => ({}))

  if (!res.ok) {
    throw new Error(data.message || 'Failed to fetch guardrails.')
  }

  return data.guardrails || []
}

export async function createOutputGuardrail(guardrail) {
  const res = await apiFetch('/api/output-guardrails', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(guardrail)
  })

  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new Error(data.message || 'Failed to create guardrail.')
  }

  return data.guardrail
}

export async function updateOutputGuardrail(ruleId, updates) {
  const res = await apiFetch(`/api/output-guardrails/${ruleId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(updates)
  })

  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new Error(data.message || 'Failed to update guardrail.')
  }

  return data
}

export async function deleteOutputGuardrail(ruleId) {
  const res = await apiFetch(`/api/output-guardrails/${ruleId}`, {
    method: 'DELETE'
  })

  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new Error(data.message || 'Failed to delete guardrail.')
  }

  return data
}