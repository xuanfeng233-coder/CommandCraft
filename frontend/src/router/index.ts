import { createRouter, createWebHistory } from 'vue-router'

const STORAGE_KEY = 'mcbe-ai-llm-config'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'chat',
      component: () => import('@/views/ChatView.vue'),
    },
    {
      path: '/setup',
      name: 'setup',
      component: () => import('@/views/SetupView.vue'),
    },
  ],
})

router.beforeEach((to) => {
  const raw = localStorage.getItem(STORAGE_KEY)
  let configured = false
  if (raw) {
    const parsed = JSON.parse(raw)
    configured = Boolean(parsed.api_key) || Boolean(parsed.subscription_mode) || Boolean(parsed.setup_skipped)
  }

  if (!configured && to.name !== 'setup') {
    return { name: 'setup' }
  }
})

export default router
