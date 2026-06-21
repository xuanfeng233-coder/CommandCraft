<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { McModal, McButton, McInput } from '@/components/mc-ui'
import PaymentDialog from '@/components/PaymentDialog.vue'
import { useSettingsStore } from '@/stores/settings'
import { useSubscriptionStore } from '@/stores/subscription'
import { getPlans, type PlanInfo } from '@/api/subscription'
import { useAuthStore } from '@/stores/auth'
import type { LLMSettings, ProviderInfo } from '@/types'

const props = defineProps<{
  show: boolean
  initialTab?: 'model' | 'subscription'
}>()
const emit = defineEmits<{ 'update:show': [val: boolean] }>()

const settingsStore = useSettingsStore()
const subStore = useSubscriptionStore()
const authStore = useAuthStore()

const activeTab = ref<'model' | 'subscription'>('model')

// --- Model config state ---
const form = ref<LLMSettings>({
  provider_id: '',
  api_key: '',
  base_url: '',
  model: '',
  temperature: 0.6,
})

const verifying = ref(false)
const verifyResult = ref<{ ok: boolean; latency_ms: number; error: string } | null>(null)

// --- Subscription state ---
const plans = ref<PlanInfo[]>([])
const paymentDialog = ref<{ show: boolean; planId: string; planName: string; amount: string }>({
  show: false,
  planId: '',
  planName: '',
  amount: '',
})
const subscribeError = ref('')

watch(() => props.show, async (val) => {
  if (val) {
    // Set initial tab
    activeTab.value = props.initialTab || 'model'

    // Model config init
    form.value = { ...settingsStore.config }
    verifyResult.value = null
    if (settingsStore.providerList.length === 0) {
      settingsStore.fetchProviders()
    }

    // Subscription init
    subscribeError.value = ''
    await subStore.fetchStatus()
    if (plans.value.length === 0) {
      try {
        plans.value = await getPlans()
      } catch { /* ignore */ }
    }
  }
})

// --- Model config methods ---
const selectedProvider = computed<ProviderInfo | undefined>(() =>
  settingsStore.providerList.find(p => p.id === form.value.provider_id)
)

function onProviderChange(id: string) {
  form.value.provider_id = id
  const p = settingsStore.providerList.find(pr => pr.id === id)
  if (p) {
    form.value.base_url = p.base_url
    form.value.model = p.default_model
  }
  verifyResult.value = null
}

async function testConnection() {
  verifying.value = true
  verifyResult.value = null
  try {
    verifyResult.value = await settingsStore.verify(form.value)
  } catch (e: unknown) {
    verifyResult.value = { ok: false, latency_ms: 0, error: String(e) }
  } finally {
    verifying.value = false
  }
}

async function save() {
  await settingsStore.save(form.value)
  emit('update:show', false)
}

// --- Subscription methods ---
function startSubscribe(plan: PlanInfo) {
  subscribeError.value = ''
  if (!authStore.isLoggedIn) {
    authStore.showAuthModal = true
    return
  }
  paymentDialog.value = {
    show: true,
    planId: plan.id,
    planName: plan.name,
    amount: plan.price_cny,
  }
}

function onPaymentSuccess() {
  if (subStore.isActive) {
    settingsStore.markSubscriptionActive()
  }
}

const expiresFormatted = computed(() => {
  if (!subStore.status?.plan?.expires_at) return ''
  const d = new Date(subStore.status.plan.expires_at)
  return d.toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' })
})

const dailyPercent = computed(() => {
  if (!subStore.dailyLimit) return 0
  return Math.min(100, Math.round((subStore.dailyUsed / subStore.dailyLimit) * 100))
})

const monthlyPercent = computed(() => {
  if (!subStore.monthlyLimit) return 0
  return Math.min(100, Math.round((subStore.monthlyUsed / subStore.monthlyLimit) * 100))
})
</script>

<template>
  <McModal :show="show" @update:show="emit('update:show', $event)">
    <div class="settings-modal">
      <h2 class="settings-title">设置</h2>

      <!-- Tab bar -->
      <div class="tab-bar">
        <button
          class="tab-btn"
          :class="{ active: activeTab === 'model' }"
          @click="activeTab = 'model'"
        >
          模型配置
        </button>
        <button
          class="tab-btn"
          :class="{ active: activeTab === 'subscription' }"
          @click="activeTab = 'subscription'"
        >
          订阅服务
        </button>
      </div>

      <!-- ===== Model Config Tab ===== -->
      <div v-if="activeTab === 'model'" class="tab-content">
        <!-- Provider selector -->
        <div class="form-group">
          <label class="form-label">AI 提供商</label>
          <div class="provider-chips">
            <button
              v-for="p in settingsStore.providerList"
              :key="p.id"
              class="chip"
              :class="{ active: form.provider_id === p.id }"
              @click="onProviderChange(p.id)"
            >
              {{ p.name }}
            </button>
          </div>
        </div>

        <!-- API Key -->
        <div class="form-group">
          <label class="form-label">API Key</label>
          <McInput
            :model-value="form.api_key"
            @update:model-value="form.api_key = $event; verifyResult = null"
            placeholder="sk-..."
            class="api-key-input"
          />
        </div>

        <!-- Base URL (for custom provider) -->
        <div v-if="form.provider_id === 'custom'" class="form-group">
          <label class="form-label">API Base URL</label>
          <McInput
            :model-value="form.base_url"
            @update:model-value="form.base_url = $event"
            placeholder="https://api.example.com/v1"
          />
        </div>

        <!-- Model -->
        <div class="form-group">
          <label class="form-label">模型</label>
          <div v-if="selectedProvider && selectedProvider.models.length > 0" class="model-chips">
            <button
              v-for="m in selectedProvider.models"
              :key="m"
              class="chip"
              :class="{ active: form.model === m }"
              @click="form.model = m; verifyResult = null"
            >
              {{ m }}
            </button>
          </div>
          <McInput
            v-else
            :model-value="form.model"
            @update:model-value="form.model = $event; verifyResult = null"
            :placeholder="selectedProvider?.requires_endpoint_id ? 'ep-xxxxx' : '模型名称'"
          />
        </div>

        <!-- Verify / Result -->
        <div v-if="verifyResult" class="verify-result" :class="verifyResult.ok ? 'ok' : 'fail'">
          {{ verifyResult.ok ? `连接成功 (${verifyResult.latency_ms}ms)` : verifyResult.error }}
        </div>

        <!-- Actions -->
        <div class="settings-actions">
          <McButton @click="testConnection()" :loading="verifying">
            测试连接
          </McButton>
          <McButton variant="primary" @click="save" :disabled="!form.api_key || !form.model">
            保存
          </McButton>
        </div>
      </div>

      <!-- ===== Subscription Tab ===== -->
      <div v-if="activeTab === 'subscription'" class="tab-content">
        <!-- Status Section -->
        <div class="sub-section">
          <h3>当前状态</h3>
          <div v-if="subStore.isActive" class="status-active">
            <div class="plan-badge">{{ subStore.planName }}</div>
            <div class="status-info">
              <span>到期时间: {{ expiresFormatted }}</span>
            </div>
            <div class="usage-bars">
              <div class="usage-row">
                <span class="usage-label">今日用量</span>
                <div class="progress-bar">
                  <div class="progress-fill" :style="{ width: dailyPercent + '%' }" />
                </div>
                <span class="usage-text">{{ subStore.dailyUsed }}/{{ subStore.dailyLimit }}</span>
              </div>
              <div class="usage-row">
                <span class="usage-label">本月用量</span>
                <div class="progress-bar">
                  <div class="progress-fill" :style="{ width: monthlyPercent + '%' }" />
                </div>
                <span class="usage-text">{{ subStore.monthlyUsed }}/{{ subStore.monthlyLimit }}</span>
              </div>
            </div>
          </div>
          <div v-else class="status-inactive">
            <span>暂无活跃订阅</span>
          </div>
        </div>

        <!-- Subscribe Section -->
        <div class="sub-section">
          <h3>立即订阅</h3>
          <p class="sub-desc">微信扫码付款，付款备注填写订单号，订阅自动激活，无需输入兑换码。</p>
          <div v-if="subscribeError" class="msg-error">{{ subscribeError }}</div>
          <div class="plan-cards">
            <div
              v-for="plan in plans"
              :key="plan.id"
              class="plan-card"
              :class="{ current: subStore.isActive && subStore.status?.plan?.plan === plan.id }"
            >
              <div class="plan-card-name">{{ plan.name }}</div>
              <div class="plan-card-price">¥{{ plan.price_cny }}<span class="plan-card-unit">/{{ plan.duration_days }}天</span></div>
              <ul class="plan-card-list">
                <li>每日 {{ plan.daily_limit }} 次</li>
                <li>每月 {{ plan.monthly_limit }} 次</li>
                <li v-if="plan.build_monthly > 0">Build 模式 {{ plan.build_monthly }} 次/月</li>
                <li v-else class="dim">不含 Build 模式</li>
              </ul>
              <McButton
                variant="primary"
                class="plan-card-btn"
                @click="startSubscribe(plan)"
              >
                立即订阅
              </McButton>
            </div>
          </div>
        </div>
      </div>
    </div>
  </McModal>

  <PaymentDialog
    v-model:show="paymentDialog.show"
    :plan-id="paymentDialog.planId"
    :plan-name="paymentDialog.planName"
    :amount="paymentDialog.amount"
    @success="onPaymentSuccess"
  />
</template>

<style scoped>
.settings-modal {
  width: 500px;
  max-width: 90vw;
  padding: 24px;
}

.settings-title {
  font-family: var(--mc-font-title);
  color: var(--mc-gold);
  font-size: 18px;
  margin-bottom: 16px;
}

/* Tab bar */
.tab-bar {
  display: flex;
  gap: 0;
  margin-bottom: 20px;
  border-bottom: 2px solid var(--mc-border);
}

.tab-btn {
  flex: 1;
  background: none;
  border: none;
  border-bottom: 3px solid transparent;
  color: var(--mc-text-dim);
  font-family: var(--mc-font-title);
  font-size: 13px;
  padding: 8px 16px;
  cursor: pointer;
  transition: color 150ms, border-color 150ms;
  margin-bottom: -2px;
}

.tab-btn:hover {
  color: var(--mc-text-primary);
}

.tab-btn.active {
  color: var(--mc-gold);
  border-bottom-color: var(--mc-gold);
}

/* Tab content */
.tab-content {
  min-height: 200px;
}

/* Model config styles */
.form-group {
  margin-bottom: 16px;
}

.form-label {
  display: block;
  font-size: 13px;
  color: var(--mc-text-secondary);
  margin-bottom: 6px;
}

.provider-chips,
.model-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.chip {
  background: var(--mc-bg-main);
  color: var(--mc-text-primary);
  border: 2px solid var(--mc-border);
  padding: 5px 12px;
  font-family: var(--mc-font-mono);
  font-size: 12px;
  cursor: pointer;
  transition: border-color 150ms;
}

.chip:hover {
  border-color: var(--mc-gold);
}

.chip.active {
  border-color: var(--mc-gold);
  color: var(--mc-gold);
}

.verify-result {
  padding: 8px 12px;
  font-size: 13px;
  margin-bottom: 12px;
}

.verify-result.ok {
  color: var(--mc-green);
}

.verify-result.fail {
  color: var(--mc-red);
}

.api-key-input :deep(.mc-input) {
  -webkit-text-security: disc;
}

.settings-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}

/* Subscription styles */
.sub-section {
  margin-bottom: 20px;
}

.sub-section h3 {
  margin: 0 0 8px;
  font-family: var(--mc-font-title);
  color: var(--mc-text-primary);
  font-size: 14px;
}

.sub-desc {
  margin: 0 0 10px;
  font-size: 12px;
  color: var(--mc-text-secondary);
  line-height: 1.5;
}

.status-active {
  background: rgba(85, 255, 85, 0.06);
  border: 1px solid var(--mc-green);
  padding: 12px;
}

.plan-badge {
  display: inline-block;
  background: var(--mc-gold);
  color: #1a1a2e;
  font-family: var(--mc-font-title);
  font-size: 13px;
  padding: 2px 10px;
  margin-bottom: 8px;
}

.status-info {
  font-size: 12px;
  color: var(--mc-text-secondary);
  margin-bottom: 10px;
}

.usage-bars {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.usage-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.usage-label {
  font-size: 12px;
  color: #ffffff;
  width: 60px;
  flex-shrink: 0;
}

.progress-bar {
  flex: 1;
  height: 8px;
  background: var(--mc-bg-main);
  border: 1px solid var(--mc-border);
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: var(--mc-green);
  transition: width 300ms;
}

.usage-text {
  font-size: 12px;
  color: var(--mc-text-secondary);
  font-family: var(--mc-font-mono);
  width: 70px;
  text-align: right;
  flex-shrink: 0;
}

.status-inactive {
  padding: 12px;
  text-align: center;
  color: #ffffff;
  font-size: 13px;
  border: 1px solid var(--mc-border);
}

.msg-error {
  margin-top: 6px;
  margin-bottom: 8px;
  font-size: 12px;
  color: var(--mc-red);
}

.plan-cards {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
  margin-top: 8px;
}

.plan-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  border: 2px solid var(--mc-border);
  background: var(--mc-bg-main);
  transition: border-color 150ms;
}

.plan-card:hover {
  border-color: var(--mc-gold);
}

.plan-card.current {
  border-color: var(--mc-green);
  background: rgba(85, 255, 85, 0.06);
}

.plan-card-name {
  font-family: var(--mc-font-title);
  font-size: 14px;
  color: var(--mc-gold);
}

.plan-card-price {
  font-family: var(--mc-font-mono);
  font-size: 22px;
  color: var(--mc-text-primary);
  font-weight: bold;
}

.plan-card-unit {
  font-size: 11px;
  color: var(--mc-text-dim);
  font-weight: normal;
  margin-left: 4px;
}

.plan-card-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
  font-size: 12px;
  color: var(--mc-text-secondary);
  flex: 1;
}

.plan-card-list .dim {
  color: var(--mc-text-dim);
}

.plan-card-btn {
  width: 100%;
}

@media (max-width: 580px) {
  .plan-cards {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 520px) {
  .settings-modal {
    padding: 16px;
  }
}
</style>
