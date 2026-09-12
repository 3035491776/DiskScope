import { createRouter, createWebHistory } from 'vue-router'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/dashboard' },
    { path: '/dashboard', component: () => import('./views/Dashboard.vue') },
    { path: '/analysis', component: () => import('./views/SpaceAnalysis.vue') },
    { path: '/large-items', component: () => import('./views/LargeItems.vue') },
    { path: '/status', component: () => import('./views/ScanStatus.vue') },
    { path: '/settings', component: () => import('./views/Settings.vue') },
  ],
})
