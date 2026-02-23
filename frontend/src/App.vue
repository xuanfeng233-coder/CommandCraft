<script setup lang="ts">
import { onMounted } from 'vue'
import { RouterView } from 'vue-router'
import { McToastContainer } from '@/components/mc-ui'
import { useSettingsStore } from '@/stores/settings'
import { useSubscriptionStore } from '@/stores/subscription'

const settingsStore = useSettingsStore()
const subscriptionStore = useSubscriptionStore()

onMounted(async () => {
  settingsStore.loadFromStorage()
  if (settingsStore.isConfigured) {
    await settingsStore.pushToBackend()
  }
  // Always check subscription — re-syncs after localStorage clear
  await subscriptionStore.fetchStatus()
  if (subscriptionStore.isActive && !settingsStore.config.subscription_mode) {
    settingsStore.markSubscriptionActive()
  }
})
</script>

<template>
  <McToastContainer />
  <RouterView />
</template>
