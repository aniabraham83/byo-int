<template>
  <div>
    <button class="mobile-menu-btn btn btn-primary" type="button" @click="toggleMobileSidebar">
      ☰
    </button>

    <div v-if="isMobileOpen" class="sidebar-backdrop" @click="closeMobileSidebar"></div>

    <aside class="sidebar-shell" :class="{ collapsed: isCollapsed, 'mobile-open': isMobileOpen }">
      <div class="sidebar-header">
        <div class="brand-wrap">
          <div class="brand-mark">BI</div>
          <div v-if="!isCollapsed" class="brand-text">
            <div class="brand-title">BYO-INT</div>
            <div class="brand-subtitle">Your Intel, Your Way</div>
          </div>
        </div>
        <button class="btn btn-sm btn-outline-secondary collapse-btn d-none d-lg-inline-flex" type="button" @click="toggleCollapse">
          {{ isCollapsed ? '»' : '«' }}
        </button>
      </div>

      <div class="sidebar-user" v-if="username && !isCollapsed" v-show="username">
        <div class="user-avatar">👤</div>
        <div>
          <div class="user-label">Signed in as</div>
          <div class="user-name">{{ username }}</div>
        </div>
      </div>

      <nav class="sidebar-nav" v-if="username">
        <router-link
          to="/"
          class="sidebar-link top-link"
          :class="{ active: $route.path === '/' }"
          @click="closeMobileSidebar"
        >
          <span class="link-icon">🏠</span>
          <span v-if="!isCollapsed">Summary</span>
        </router-link>

        <router-link
          to="/architecture"
          class="sidebar-link top-link"
          :class="{ active: $route.path === '/architecture' }"
          @click="closeMobileSidebar"
        >
          <span class="link-icon">🗺️</span>
          <span v-if="!isCollapsed">Architecture</span>
        </router-link>

        <div v-for="group in navGroups" :key="group.label" class="nav-group">
          <button
            type="button"
            class="group-toggle"
            :class="{ active: isGroupActive(group) }"
            @click="toggleGroup(group.label)"
          >
            <span class="group-heading-wrap">
              <span class="link-icon">{{ group.icon }}</span>
              <span v-if="!isCollapsed" class="group-heading-text">
                <span class="group-label">{{ group.label }}</span>
                <small class="group-description">{{ group.description }}</small>
              </span>
            </span>
            <span v-if="!isCollapsed" class="group-caret">{{ isGroupOpen(group.label) ? '▾' : '▸' }}</span>
          </button>

          <div v-show="isGroupOpen(group.label) && !isCollapsed" class="group-items">
            <router-link
              v-for="item in group.items"
              :key="item.to"
              :to="item.to"
              class="sidebar-link child-link"
              :class="{ active: $route.path === item.to }"
              @click="closeMobileSidebar"
            >
              <span class="link-icon small-icon">{{ item.icon }}</span>
              <span>
                <span class="child-title">{{ item.label }}</span>
                <small class="child-help">{{ item.helpText }}</small>
              </span>
            </router-link>
          </div>
        </div>
      </nav>

      <div class="sidebar-footer">
        <button v-if="username" class="btn btn-outline-danger w-100" @click="logout">
          <span v-if="isCollapsed">⇦</span>
          <span v-else>Logout</span>
        </button>
        <router-link v-else to="/login" class="btn btn-outline-primary w-100" @click="closeMobileSidebar">
          <span v-if="isCollapsed">⇥</span>
          <span v-else>Login</span>
        </router-link>
      </div>
    </aside>
  </div>
</template>
  
  <script>
  import { fetchCurrentIdentity, logoutSession } from '@/api'

  export default {
    name: 'nav-header-1',
    emits: ['toggle-collapse'],
    data() {
      return {
        username: '',
        userRoles: [],
        pageAccessMap: {},
        navGroupsTemplate: [],
        isCollapsed: false,
        isMobileOpen: false,
        openGroups: {},
        navGroups: [
          {
            icon: '🛰️',
            label: 'Data Collection',
            description: 'Datapull operations',
            items: [
              {
                icon: '🔄',
                label: 'Datapull Workflows',
                to: '/datapulls',
                helpText: 'Create and manage collection workflows'
              },
              {
                icon: '🧩',
                label: 'Datapull Templates',
                to: '/datapull-templates',
                helpText: 'Configure reusable datapull templates'
              },
              {
                icon: '⏱️',
                label: 'Scheduled Jobs',
                to: '/scheduled-jobs',
                helpText: 'Monitor recurring collection jobs'
              },
              {
                icon: '🩺',
                label: 'Worker Health',
                to: '/worker-health',
                helpText: 'Inspect queue depth and worker status'
              },
              {
                icon: '📏',
                label: 'Worker Scaling',
                to: '/worker-scaling',
                helpText: 'Set desired worker count and trigger scaling'
              },
              {
                icon: '📚',
                label: 'Datapull Jobs',
                to: '/datapull-jobs',
                helpText: 'Track job envelopes, retries, and failures'
              }
                ,{
                  icon: '📊',
                  label: 'Metrics',
                  to: '/metrics',
                  helpText: 'Monitor job completion rates, latency, and failures'
                }
            ]
          },
          {
            icon: '📈',
            label: 'Data Insights',
            description: 'Indicators and outputs',
            items: [
              {
                icon: '🧠',
                label: 'Indicators',
                to: '/indicators',
                helpText: 'Review and manage indicators'
              },
              {
                icon: '📦',
                label: 'Outputs',
                to: '/outputs',
                helpText: 'Manage output feeds and views'
              },
              {
                icon: '🧾',
                label: 'Indicator Logs',
                to: '/indicator-logs',
                helpText: 'Review indicator create/update/delete logs'
              }
            ]
          },
          {
            icon: '⚙️',
            label: 'Administration',
            description: 'Access and platform settings',
            items: [
              {
                icon: '👥',
                label: 'Users',
                to: '/users',
                helpText: 'Create and update application users'
              },
              {
                icon: '🏷️',
                label: 'Tags',
                to: '/tags',
                helpText: 'Display and create configuration tags'
              },
              {
                icon: '🧱',
                label: 'Data Types',
                to: '/data-types',
                helpText: 'View and add data type options'
              },
              {
                icon: '🔐',
                label: 'Secrets',
                to: '/secrets',
                helpText: 'Manage encrypted datapull secrets'
              },
              {
                icon: '🧬',
                label: 'Data Enrichments',
                to: '/data-enrichments',
                helpText: 'Configure enrichment functions and outputs'
              },
              {
                icon: '✅',
                label: 'Support Matrix',
                to: '/support-matrix',
                helpText: 'Tested integrations and custom snippet recipes'
              },
              {
                icon: '🛠️',
                label: 'Configuration',
                to: '/configuration',
                helpText: 'View and edit core basic configuration'
              },
              {
                icon: '📋',
                label: 'Audit Logs',
                to: '/audit-logs',
                helpText: 'Review all API requests and access history'
              },
              {
                icon: '🧾',
                label: 'Platform Change Logs',
                to: '/platform-change-logs',
                helpText: 'Track create/update/delete actions by user and source'
              }
            ]
          }
        ]
      }
    },
    async mounted() {
      this.navGroupsTemplate = JSON.parse(JSON.stringify(this.navGroups))
      this.initializeOpenGroups()
      this.notifyCollapsedState()
      await this.syncUser()
      this.$watch(
        () => this.$route.fullPath,
        async () => {
          this.ensureActiveGroupVisible()
          this.closeMobileSidebar()
          await this.syncUser();
        }
      );
    },
    methods: {
      initializeOpenGroups() {
        const nextState = {}
        this.navGroups.forEach((group) => {
          nextState[group.label] = this.isGroupActive(group)
        })
        this.openGroups = nextState
      },
      ensureActiveGroupVisible() {
        this.navGroups.forEach((group) => {
          if (this.isGroupActive(group)) {
            this.openGroups[group.label] = true
          }
        })
      },
      notifyCollapsedState() {
        this.$emit('toggle-collapse', this.isCollapsed)
      },
      toggleCollapse() {
        this.isCollapsed = !this.isCollapsed
        this.notifyCollapsedState()
      },
      toggleMobileSidebar() {
        this.isMobileOpen = !this.isMobileOpen
      },
      closeMobileSidebar() {
        this.isMobileOpen = false
      },
      toggleGroup(label) {
        if (this.isCollapsed) {
          this.isCollapsed = false
          this.notifyCollapsedState()
        }
        this.openGroups = {
          ...this.openGroups,
          [label]: !this.openGroups[label]
        }
      },
      isGroupOpen(label) {
        return !!this.openGroups[label]
      },
      isGroupActive(group) {
        return group.items.some((item) => item.to === this.$route.path)
      },
      hasAccess(path) {
        const requiredRole = String((this.pageAccessMap || {})[path] || '').trim().toLowerCase()
        if (!requiredRole) {
          return true
        }
        const normalizedRoles = (Array.isArray(this.userRoles) ? this.userRoles : []).map((r) => String(r || '').trim().toLowerCase())
        return normalizedRoles.includes(requiredRole)
      },
      async syncUser() {
        try {
          const identity = await fetchCurrentIdentity()
          this.username = identity && identity.user ? identity.user : ''
          this.userRoles = identity && Array.isArray(identity.roles) ? identity.roles : []
          this.pageAccessMap = identity && identity.pageAccessMap ? identity.pageAccessMap : {}

          const sourceGroups = this.navGroupsTemplate.length ? this.navGroupsTemplate : this.navGroups
          this.navGroups = sourceGroups.map((group) => ({
            ...group,
            items: (group.items || []).filter((item) => this.hasAccess(item.to))
          }))
        } catch (e) {
          this.username = ''
          this.userRoles = []
          this.pageAccessMap = {}
        }
      },
      async logout() {
        await logoutSession();
        this.username = '';
        this.$router.push('/login');
      }
    }
  }
  </script>

  <style scoped>
.mobile-menu-btn {
  position: fixed;
  top: 1rem;
  left: 1rem;
  z-index: 1045;
  display: none;
}

.sidebar-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.35);
  z-index: 1040;
}

.sidebar-shell {
  position: fixed;
  inset: 0 auto 0 0;
  width: 280px;
  background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
  border-right: 1px solid #e2e8f0;
  box-shadow: 0 8px 30px rgba(15, 23, 42, 0.08);
  z-index: 1042;
  display: flex;
  flex-direction: column;
  transition: width 0.2s ease, transform 0.2s ease;
  overflow: hidden;
}

.sidebar-shell.collapsed {
  width: 92px;
}

.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem;
  border-bottom: 1px solid #e2e8f0;
}

.brand-wrap {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  min-width: 0;
}

.brand-mark {
  width: 42px;
  height: 42px;
  border-radius: 12px;
  background: linear-gradient(135deg, #2563eb, #1d4ed8);
  color: #fff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  letter-spacing: 0.08em;
  flex-shrink: 0;
}

.brand-title {
  font-weight: 700;
  color: #0f172a;
}

.brand-subtitle {
  font-size: 0.78rem;
  color: #64748b;
}

.collapse-btn {
  flex-shrink: 0;
}

.sidebar-user {
  margin: 1rem;
  padding: 0.9rem;
  border-radius: 16px;
  background: #eff6ff;
  display: flex;
  align-items: center;
  gap: 0.8rem;
}

.user-avatar {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: #dbeafe;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.user-label {
  font-size: 0.72rem;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.user-name {
  font-weight: 700;
  color: #0f172a;
}

.sidebar-nav {
  flex: 1;
  overflow-y: auto;
  padding: 0.75rem;
}

.nav-group + .nav-group {
  margin-top: 0.5rem;
}

.top-link,
.group-toggle,
.sidebar-link {
  width: 100%;
  border: 0;
  background: transparent;
  color: #334155;
  border-radius: 14px;
  text-decoration: none;
}

.top-link,
.sidebar-link {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.85rem 0.9rem;
  margin-bottom: 0.35rem;
}

.group-toggle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.85rem 0.9rem;
}

.group-heading-wrap {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  text-align: left;
}

.link-icon {
  width: 1.6rem;
  text-align: center;
  flex-shrink: 0;
}

.small-icon {
  font-size: 0.95rem;
}

.group-heading-text,
.child-title,
.child-help {
  display: block;
}

.group-label {
  font-weight: 700;
}

.group-description,
.child-help {
  color: #64748b;
  line-height: 1.2;
}

.group-items {
  padding-left: 0.75rem;
  margin-top: 0.15rem;
}

.child-link {
  align-items: flex-start;
}

.top-link.active,
.group-toggle.active,
.sidebar-link.active,
.top-link:hover,
.group-toggle:hover,
.sidebar-link:hover {
  background: #e7f1ff;
  color: #0d6efd;
}

.sidebar-link.active .child-help,
.group-toggle.active .group-description {
  color: #2563eb;
}

.sidebar-footer {
  padding: 1rem;
  border-top: 1px solid #e2e8f0;
}

@media (max-width: 991.98px) {
  .mobile-menu-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }

  .sidebar-shell {
    transform: translateX(-100%);
    width: 280px;
  }

  .sidebar-shell.mobile-open {
    transform: translateX(0);
  }

  .sidebar-shell.collapsed {
    width: 280px;
  }
}
</style>