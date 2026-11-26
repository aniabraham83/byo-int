<template>
  <div class="app-shell" :class="{ 'sidebar-collapsed': sidebarCollapsed }">
    <nav-header-1 @toggle-collapse="handleSidebarToggle" />
    <main class="app-content">
      <router-view />
    </main>
  </div>
</template>

<script>
import Navheader1 from '@/components/nav-header_main.vue'
export default {
  name: 'App',
  data() {
    return {
      sidebarCollapsed: false
    }
  },
  components: {
    'nav-header-1': Navheader1
  },
  methods: {
    handleSidebarToggle(isCollapsed) {
      this.sidebarCollapsed = !!isCollapsed
    }
  }
}
</script>

<style>
body {
  background: #f8fafc;
}

#app {
  min-height: 100vh;
}

.app-shell {
  min-height: 100vh;
}

.app-content {
  margin-left: 280px;
  min-height: 100vh;
  padding: 1.5rem;
  transition: margin-left 0.2s ease;
}

.app-shell.sidebar-collapsed .app-content {
  margin-left: 92px;
}

@media (max-width: 991.98px) {
  .app-content,
  .app-shell.sidebar-collapsed .app-content {
    margin-left: 0;
    padding: 4.5rem 1rem 1rem;
  }
}
</style>