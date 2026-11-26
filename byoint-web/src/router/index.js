import { createWebHistory, createRouter } from "vue-router";

import Home from '@/components/Home.vue'
import Auth from '@/components/Auth.vue'
import Indicators from '@/components/Indicators.vue'
import IndicatorDetail from '@/components/IndicatorDetail.vue'
import DataPullWorkflows from '@/components/DataPullWorkflows.vue'
import ScheduledJobs from '@/components/ScheduledJobs.vue'
import WorkerHealth from '@/components/WorkerHealth.vue'
import WorkerScaling from '@/components/WorkerScaling.vue'
import AuditLogs from '@/components/AuditLogs.vue'
import PlatformChangeLogs from '@/components/PlatformChangeLogs.vue'
import DatapullJobs from '@/components/DatapullJobs.vue'
import Outputs from '@/components/Outputs.vue'
import OutputsEDL from '@/components/OutputsEDL.vue'
import Users from '@/components/Users.vue'
import Tags from '@/components/Tags.vue'
import DataTypes from '@/components/DataTypes.vue'
import Secrets from '@/components/Secrets.vue'
import DataEnrichments from '@/components/DataEnrichments.vue'
import IndicatorLogs from '@/components/IndicatorLogs.vue'
import Configuration from '@/components/Configuration.vue'
import { fetchCurrentIdentity } from '@/api'

import DatapullTemplates from '@/components/DatapullTemplates.vue'
import SupportMatrix from '@/components/SupportMatrix.vue'
import Architecture from '@/components/Architecture.vue'

import Metrics from '@/components/Metrics.vue'

const routes = [
  {
    path: "/",
    name: "Home",
    component: Home,
  }
  ,{
    path: "/architecture",
    name: "Architecture",
    component: Architecture,
  }
  ,{
    path: "/login",
    name: "Login",
    component: Auth
  }
  ,{
    path: "/indicators",
    name: "Indicators",
    component: Indicators
  }
  ,{
    path: "/indicators/detail",
    name: "IndicatorDetail",
    component: IndicatorDetail
  }
  ,{
    path: "/datapulls",
    name: "DatapullWorkflows",
    component: DataPullWorkflows
  }
  ,{
    path: "/scheduled-jobs",
    name: "ScheduledJobs",
    component: ScheduledJobs
  }
  ,{
    path: "/worker-health",
    name: "WorkerHealth",
    component: WorkerHealth
  }
  ,{
    path: "/worker-scaling",
    name: "WorkerScaling",
    component: WorkerScaling
  }
  ,{
    path: "/audit-logs",
    name: "AuditLogs",
    component: AuditLogs
  }
  ,{
    path: "/platform-change-logs",
    name: "PlatformChangeLogs",
    component: PlatformChangeLogs
  }
  ,{
    path: "/datapull-jobs",
    name: "DatapullJobs",
    component: DatapullJobs
  }
  ,{
    path: "/datapull-templates",
    name: "DatapullTemplates",
    component: DatapullTemplates
  }
  ,{
    path: "/support-matrix",
    name: "SupportMatrix",
    component: SupportMatrix
  }
  ,{
    path: "/outputs",
    name: "Outputs",
    component: Outputs
  }
  ,{
    path: "/outputs-details",
    name: "OutputsDetails",
    component: OutputsEDL
  }
  ,{
    path: "/users",
    name: "Users",
    component: Users
  }
  ,{
    path: "/tags",
    name: "Tags",
    component: Tags
  }
  ,{
    path: "/data-types",
    name: "DataTypes",
    component: DataTypes
  }
  ,{
    path: "/secrets",
    name: "Secrets",
    component: Secrets
  }
  ,{
    path: "/data-enrichments",
    name: "DataEnrichments",
    component: DataEnrichments
  }
  ,{
    path: "/configuration",
    name: "Configuration",
    component: Configuration
  }
  ,{
    path: "/indicator-logs",
    name: "IndicatorLogs",
    component: IndicatorLogs
  }
    ,{
      path: "/metrics",
      name: "Metrics",
      component: Metrics
    }
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

// Global navigation guard for authentication
router.beforeEach(async (to) => {
  const publicPages = ['/login'];
  const authRequired = !publicPages.includes(to.path);
  let identity = null
  try {
    identity = await fetchCurrentIdentity()
  } catch (e) {
    identity = null
  }

  const user = identity ? identity.user : null
  const roles = identity && Array.isArray(identity.roles) ? identity.roles : []
  const pageAccessMap = identity && identity.pageAccessMap ? identity.pageAccessMap : {}

  if (authRequired && !user) {
    return '/login';
  }

  if (!authRequired && user) {
    return '/';
  }

  if (authRequired && user) {
    const requiredRole = String(pageAccessMap[to.path] || '').trim().toLowerCase()
    if (requiredRole && !roles.map((r) => String(r || '').trim().toLowerCase()).includes(requiredRole)) {
      return '/'
    }
  }

  return true;
});

export default router;