import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { fetchMe, logout as apiLogout, type UserInfo } from '@/api/auth'

const BRAYNLABS_URL = 'https://braynt.com'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<UserInfo | null>(null)
  const loading = ref(false)
  const showAuthModal = ref(false)

  const isLoggedIn = computed(() => user.value !== null)
  const username = computed(() => user.value?.username ?? '')

  async function checkSession() {
    try {
      user.value = await fetchMe()
    } catch {
      user.value = null
    }
  }

  function redirectToLogin() {
    const callbackUrl = `${window.location.origin}/api/auth/sso/callback`
    const url = `${BRAYNLABS_URL}/?action=login&client_id=commandcraft&redirect=${encodeURIComponent(callbackUrl)}`
    window.location.href = url
  }

  async function logout() {
    await apiLogout()
    user.value = null
  }

  function requireAuth() {
    if (!isLoggedIn.value) {
      showAuthModal.value = true
      return false
    }
    return true
  }

  return {
    user,
    loading,
    showAuthModal,
    isLoggedIn,
    username,
    checkSession,
    redirectToLogin,
    logout,
    requireAuth,
  }
})
