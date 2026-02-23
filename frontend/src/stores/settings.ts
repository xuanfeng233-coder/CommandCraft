import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { getProviders, postConfig, verifyConfig } from '@/api/settings'
import type { ProviderInfo, LLMSettings } from '@/types'

const STORAGE_KEY = 'mcbe-ai-llm-config'

export const useSettingsStore = defineStore('settings', () => {
  const providerList = ref<ProviderInfo[]>([])
  const config = ref<LLMSettings>({
    provider_id: '',
    api_key: '',
    base_url: '',
    model: '',
    temperature: 0.6,
  })

  const isConfigured = computed(() =>
    Boolean(config.value.api_key && config.value.model) || Boolean(config.value.subscription_mode)
  )

  const isSkipped = computed(() => Boolean(config.value.setup_skipped))

  function loadFromStorage() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY)
      if (raw) {
        const parsed = JSON.parse(raw) as LLMSettings
        config.value = parsed
      }
    } catch {
      // corrupt data — ignore
    }
  }

  function saveToStorage() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(config.value))
  }

  async function fetchProviders() {
    try {
      providerList.value = await getProviders()
    } catch {
      providerList.value = []
    }
  }

  async function save(newConfig: LLMSettings) {
    config.value = { ...newConfig }
    saveToStorage()
    await postConfig(newConfig)
  }

  async function pushToBackend() {
    if (!isConfigured.value) return
    await postConfig(config.value)
  }

  async function verify(testConfig: LLMSettings) {
    return verifyConfig(testConfig)
  }

  function skip() {
    config.value = {
      provider_id: '',
      api_key: '',
      base_url: '',
      model: '',
      temperature: 0.6,
      setup_skipped: true,
    }
    saveToStorage()
  }

  function markSubscriptionActive() {
    config.value.subscription_mode = true
    saveToStorage()
  }

  function clearSubscriptionMode() {
    config.value.subscription_mode = false
    saveToStorage()
  }

  function clear() {
    config.value = {
      provider_id: '',
      api_key: '',
      base_url: '',
      model: '',
      temperature: 0.6,
    }
    localStorage.removeItem(STORAGE_KEY)
  }

  return {
    providerList,
    config,
    isConfigured,
    isSkipped,
    loadFromStorage,
    fetchProviders,
    save,
    skip,
    pushToBackend,
    verify,
    clear,
    markSubscriptionActive,
    clearSubscriptionMode,
  }
})
