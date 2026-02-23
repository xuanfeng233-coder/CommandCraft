import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import {
  getSubscriptionStatus,
  redeemCode as apiRedeemCode,
  type SubscriptionStatus,
  type RedeemResult,
} from '@/api/subscription'

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

  async function redeem(code: string): Promise<RedeemResult> {
    loading.value = true
    try {
      const result = await apiRedeemCode(code)
      // Refresh status after redeem
      await fetchStatus()
      return result
    } finally {
      loading.value = false
    }
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
    redeem,
  }
})
