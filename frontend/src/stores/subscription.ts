import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import {
  getSubscriptionStatus,
  createOrder as apiCreateOrder,
  getOrder as apiGetOrder,
  cancelOrder as apiCancelOrder,
  type SubscriptionStatus,
  type WxpayOrder,
} from '@/api/subscription'
import { useAuthStore } from '@/stores/auth'

const TERMINAL_STATUSES = new Set(['paid', 'amount_mismatch', 'expired', 'cancelled'])

export const useSubscriptionStore = defineStore('subscription', () => {
  const status = ref<SubscriptionStatus | null>(null)
  const loading = ref(false)

  const isActive = computed(() => status.value?.active ?? false)

  const planName = computed(() => status.value?.plan?.plan_name ?? '')

  const dailyUsed = computed(() => status.value?.usage?.daily ?? 0)
  const dailyLimit = computed(() => status.value?.plan?.daily_limit ?? 0)
  const monthlyUsed = computed(() => status.value?.usage?.monthly ?? 0)
  const monthlyLimit = computed(() => status.value?.plan?.monthly_limit ?? 0)

  const usageText = computed(() => {
    if (!isActive.value) return ''
    return `${dailyUsed.value}/${dailyLimit.value}`
  })

  async function fetchStatus() {
    try {
      status.value = await getSubscriptionStatus()
    } catch {
      // Silently fail — subscription is optional
    }
  }

  async function createOrder(planId: string): Promise<WxpayOrder> {
    const authStore = useAuthStore()
    if (!authStore.isLoggedIn) {
      authStore.showAuthModal = true
      throw new Error('请先登录后再订阅')
    }

    loading.value = true
    try {
      return await apiCreateOrder(planId)
    } finally {
      loading.value = false
    }
  }

  /**
   * Poll an order until it reaches a terminal state, the abort signal fires,
   * or `expires_at` passes. The callback is invoked on every successful fetch
   * (including the first), so the UI can update its state machine live.
   */
  async function pollOrder(
    orderId: string,
    onUpdate: (order: WxpayOrder) => void,
    signal?: AbortSignal,
  ): Promise<WxpayOrder> {
    let last: WxpayOrder | null = null
    const start = Date.now()
    let interval = 3000  // 3s for the first minute, then 5s.

    while (true) {
      if (signal?.aborted) {
        throw new DOMException('Polling aborted', 'AbortError')
      }
      try {
        const order = await apiGetOrder(orderId)
        last = order
        onUpdate(order)
        if (TERMINAL_STATUSES.has(order.status)) {
          // After paid/mismatch we need one more fetch to confirm activation
          // since the backend may activate asynchronously. The caller decides
          // whether to keep polling for `activated`. Here we return immediately.
          return order
        }
      } catch (e) {
        // Transient errors — keep polling unless aborted.
        if (signal?.aborted) throw e
      }

      if (Date.now() - start > 60_000) interval = 5000
      await sleep(interval, signal)
    }

    // Unreachable — TypeScript happiness.
    return last as WxpayOrder
  }

  async function cancelOrder(orderId: string): Promise<WxpayOrder> {
    return apiCancelOrder(orderId)
  }

  return {
    status,
    loading,
    isActive,
    planName,
    dailyUsed,
    dailyLimit,
    monthlyUsed,
    monthlyLimit,
    usageText,
    fetchStatus,
    createOrder,
    pollOrder,
    cancelOrder,
  }
})

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException('Aborted', 'AbortError'))
      return
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort)
      resolve()
    }, ms)
    const onAbort = () => {
      clearTimeout(timer)
      reject(new DOMException('Aborted', 'AbortError'))
    }
    signal?.addEventListener('abort', onAbort, { once: true })
  })
}
