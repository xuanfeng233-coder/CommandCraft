<script setup lang="ts">
import { ref, watch } from 'vue'
import { McModal, McButton } from '@/components/mc-ui'
import { useAuthStore } from '@/stores/auth'
import { listDevices, kickDevice, type DeviceInfo } from '@/api/auth'

const props = defineProps<{ show: boolean }>()
const emit = defineEmits<{ 'update:show': [val: boolean] }>()

const authStore = useAuthStore()

// Device management state (shown after login if device limit hit via ?sso_error=device_limit)
const showDevices = ref(false)
const deviceList = ref<DeviceInfo[]>([])
const kickingToken = ref('')
const error = ref('')

watch(() => props.show, async (val) => {
  if (val) {
    error.value = ''
    showDevices.value = false
    // Check if redirected back with sso_error
    const params = new URLSearchParams(window.location.search)
    const ssoError = params.get('sso_error')
    if (ssoError === 'device_limit' && authStore.isLoggedIn) {
      showDevices.value = true
      deviceList.value = await listDevices()
    } else if (ssoError === 'device_limit') {
      error.value = '已达到最大设备数限制，请先在 BraynLabs 账户中退出其他设备'
    } else if (ssoError) {
      error.value = '登录失败，请重试'
    }
    // Clean URL
    if (ssoError) {
      window.history.replaceState({}, '', window.location.pathname)
    }
  }
})

function goLogin() {
  authStore.redirectToLogin()
}

async function handleKick(token: string) {
  kickingToken.value = token
  try {
    await kickDevice(token)
    deviceList.value = deviceList.value.filter((d) => d.token !== token)
    if (deviceList.value.length === 0) {
      showDevices.value = false
    }
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : '踢出失败'
  } finally {
    kickingToken.value = ''
  }
}

function formatUA(ua: string): string {
  if (ua.includes('iPhone')) return 'iPhone'
  if (ua.includes('iPad') || (ua.includes('Macintosh') && 'ontouchend' in document)) return 'iPad'
  if (ua.includes('Android')) return ua.includes('Mobile') ? 'Android 手机' : 'Android 平板'
  if (ua.includes('Windows')) return 'Windows'
  if (ua.includes('Macintosh') || ua.includes('Mac OS')) return 'macOS'
  if (ua.includes('Linux')) return 'Linux'
  if (ua.includes('Mobile')) return '移动设备'
  return '未知设备'
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  } catch { return iso }
}
</script>

<template>
  <McModal :show="show" @update:show="emit('update:show', $event)">
    <div class="auth-panel">
      <div class="auth-header">
        <h2>登录</h2>
        <button class="close-btn" @click="emit('update:show', false)">&times;</button>
      </div>

      <!-- Device management (when device limit hit) -->
      <div v-if="showDevices" class="device-section">
        <p class="device-hint">已达到最大设备数限制，请踢出一个设备后重新登录</p>
        <div class="device-list">
          <div v-for="device in deviceList" :key="device.token" class="device-item">
            <div class="device-info">
              <span class="device-name">{{ formatUA(device.user_agent) }}</span>
              <span class="device-time">最后活跃: {{ formatTime(device.last_active_at) }}</span>
              <span class="device-ip">IP: {{ device.ip_addr }}</span>
            </div>
            <McButton size="small" :loading="kickingToken === device.token" @click="handleKick(device.token)">踢出</McButton>
          </div>
        </div>
        <McButton variant="primary" class="retry-btn" @click="goLogin">重新登录</McButton>
      </div>

      <!-- Normal: redirect to BraynLabs -->
      <div v-else class="auth-form">
        <p class="auth-desc">使用 BraynLabs 账户登录 CommandCraft</p>

        <div v-if="error" class="msg-error">{{ error }}</div>

        <McButton variant="primary" class="login-btn" @click="goLogin">
          前往 BraynLabs 登录
        </McButton>

        <p class="register-hint">
          没有账户？点击上方按钮即可注册
        </p>
      </div>
    </div>
  </McModal>
</template>

<style scoped>
.auth-panel { padding: 24px; min-width: 360px; max-width: 440px; }
.auth-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.auth-header h2 { margin: 0; font-family: var(--mc-font-title); color: var(--mc-gold); font-size: 18px; }
.close-btn { background: none; border: none; color: #fff; font-size: 24px; cursor: pointer; padding: 0 4px; }
.close-btn:hover { color: var(--mc-text-primary); }

.auth-form { display: flex; flex-direction: column; gap: 14px; }
.auth-desc { font-size: 14px; color: var(--mc-text-secondary); text-align: center; margin: 0; }

.login-btn { width: 100%; margin-top: 8px; }
.msg-error { font-size: 12px; color: var(--mc-red); }

.register-hint { text-align: center; margin-top: 12px; font-size: 13px; color: var(--mc-text-dim); }

.device-section { display: flex; flex-direction: column; gap: 12px; }
.device-hint { color: var(--mc-red); font-size: 13px; margin: 0; }
.device-list { display: flex; flex-direction: column; gap: 8px; }
.device-item { display: flex; align-items: center; justify-content: space-between; padding: 8px 12px; border: 1px solid var(--mc-border); background: var(--mc-bg-main); }
.device-info { display: flex; flex-direction: column; gap: 2px; }
.device-name { font-size: 13px; color: var(--mc-text-primary); }
.device-time, .device-ip { font-size: 11px; color: var(--mc-text-dim); }
.retry-btn { margin-top: 8px; width: 100%; }

@media (max-width: 440px) { .auth-panel { min-width: unset; padding: 16px; } }
</style>
