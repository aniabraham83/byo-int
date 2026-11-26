<template>
  <div class="container mt-5">
    <div class="row justify-content-center">
      <div class="col-md-6">
        <div class="card">
          <div class="card-body">
            <h3 class="card-title mb-3">Sign in</h3>
            <form @submit.prevent="handleLogin">
              <div class="mb-3">
                <label class="form-label">Username</label>
                <input v-model="username" type="text" class="form-control" required />
              </div>
              <div class="mb-3">
                <label class="form-label">Password</label>
                <input v-model="password" type="password" class="form-control" required />
              </div>
              <div v-if="error" class="alert alert-danger">{{ error }}</div>
              <div class="d-flex justify-content-between align-items-center">
                <button class="btn btn-primary" type="submit">Sign in</button>
                <small class="text-muted">Use local credentials or SSO.</small>
              </div>
            </form>
            <div v-if="ssoEnabled" class="mt-4">
              <div class="text-center text-muted small mb-3">or</div>
              <button class="btn btn-outline-dark w-100" type="button" @click="startSsoLogin">
                Continue with {{ ssoProviderName }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { apiFetch, apiUrl, fetchSsoConfig } from '@/api'

export default {
  name: 'AuthPage',
  data() {
    return {
      username: '',
      password: '',
      error: null,
      ssoEnabled: false,
      ssoProviderName: 'Single Sign-On'
    };
  },
  async mounted() {
    const ssoConfig = await fetchSsoConfig()
    this.ssoEnabled = !!ssoConfig.enabled
    this.ssoProviderName = ssoConfig.provider_name || 'Single Sign-On'

    const queryError = this.$route.query.sso_error
    if (queryError) {
      this.error = String(queryError)
    }
  },
  methods: {
    async handleLogin() {
      this.error = null;
      if (!this.username || !this.password) {
        this.error = 'Username and password are required.';
        return;
      }
      try {
        const resp = await apiFetch('/api/auth', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ user: this.username, password: this.password })
        });
        const data = await resp.json();
        if (!resp.ok) {
          this.error = data.message || 'Authentication failed.';
          return;
        }
        if (data.authenticated) {
          this.$router.push('/');
        } else {
          this.error = 'Login failed.';
        }
      } catch (e) {
        this.error = 'Network error during authentication.';
      }
    },
    startSsoLogin() {
      window.location.href = apiUrl('/api/auth/sso/login')
    }
  }
}
</script>

<style scoped>
.card { box-shadow: 0 2px 6px rgba(0,0,0,.1); }
</style>
