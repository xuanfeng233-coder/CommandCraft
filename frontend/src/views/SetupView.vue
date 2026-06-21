<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { McButton, McInput, McCard } from '@/components/mc-ui'
import AuthModal from '@/components/AuthModal.vue'
import PaymentDialog from '@/components/PaymentDialog.vue'
import { useSettingsStore } from '@/stores/settings'
import { useSubscriptionStore } from '@/stores/subscription'
import { useAuthStore } from '@/stores/auth'
import { getPlans, type PlanInfo } from '@/api/subscription'
import type { ProviderInfo, LLMSettings } from '@/types'

const router = useRouter()
const settingsStore = useSettingsStore()
const subStore = useSubscriptionStore()
const authStore = useAuthStore()

const step = ref(1)
const subscriptionMode = ref(false)
const selectedProvider = ref<ProviderInfo | null>(null)
const apiKey = ref('')
const selectedModel = ref('')
const customBaseUrl = ref('')
const customModel = ref('')
const verifying = ref(false)
const verifyResult = ref<{ ok: boolean; latency_ms: number; error: string } | null>(null)

// Subscription mode state
const plans = ref<PlanInfo[]>([])
const paymentDialog = ref<{ show: boolean; planId: string; planName: string; amount: string }>({
  show: false,
  planId: '',
  planName: '',
  amount: '',
})

onMounted(async () => {
  await settingsStore.fetchProviders()
  authStore.checkSession()
})

const providers = computed(() => settingsStore.providerList)

const totalSteps = computed(() => subscriptionMode.value ? 2 : 4)

function selectProvider(p: ProviderInfo) {
  selectedProvider.value = p
  selectedModel.value = p.default_model
  customBaseUrl.value = p.base_url
  step.value = 2
}

async function enterSubscriptionMode() {
  if (!authStore.isLoggedIn) {
    authStore.showAuthModal = true
    return
  }
  subscriptionMode.value = true
  step.value = 2
  await subStore.fetchStatus()
  if (plans.value.length === 0) {
    try {
      plans.value = await getPlans()
    } catch { /* ignore */ }
  }
}

function startSubscribe(plan: PlanInfo) {
  paymentDialog.value = {
    show: true,
    planId: plan.id,
    planName: plan.name,
    amount: plan.price_cny,
  }
}

function backToStep1() {
  subscriptionMode.value = false
  step.value = 1
}

function modelList(): string[] {
  if (!selectedProvider.value) return []
  if (selectedProvider.value.models.length > 0) return selectedProvider.value.models
  return []
}

function buildConfig(): LLMSettings {
  const p = selectedProvider.value!
  return {
    provider_id: p.id,
    api_key: apiKey.value,
    base_url: p.id === 'custom' ? customBaseUrl.value : p.base_url,
    model: p.requires_endpoint_id || p.id === 'custom' ? customModel.value : selectedModel.value,
    temperature: 0.6,
  }
}

async function doVerify() {
  verifying.value = true
  verifyResult.value = null
  try {
    const result = await settingsStore.verify(buildConfig())
    verifyResult.value = result
  } catch (e: unknown) {
    verifyResult.value = { ok: false, latency_ms: 0, error: String(e) }
  } finally {
    verifying.value = false
  }
}

async function finish() {
  await settingsStore.save(buildConfig())
  router.push('/')
}

async function finishSubscription() {
  // Save subscription mode flag to localStorage so router guard allows entry
  const subConfig: LLMSettings = {
    provider_id: 'subscription',
    api_key: '',
    base_url: '',
    model: '',
    temperature: 0.6,
    subscription_mode: true,
  }
  await settingsStore.save(subConfig)
  router.push('/')
}

function skipSetup() {
  settingsStore.skip()
  router.push('/')
}

const providerLinks: Record<string, string> = {
  deepseek: 'https://platform.deepseek.com/api_keys',
  qwen: 'https://dashscope.console.aliyun.com/apiKey',
  glm: 'https://open.bigmodel.cn/usercenter/apikeys',
  kimi: 'https://platform.moonshot.cn/console/api-keys',
  doubao: 'https://console.volcengine.com/ark/region:ark+cn-beijing/apiKey',
  openai: 'https://platform.openai.com/api-keys',
  gemini: 'https://aistudio.google.com/apikey',
}
</script>

<template>
  <div class="setup-page mc-tex-dirt">
    <div class="setup-container">
      <img src="/images/logo.png" alt="CommandCraft — AI 命令生成器" class="setup-logo" />
      <h1 class="setup-title">CommandCraft</h1>
      <p class="setup-subtitle">Minecraft 命令 AI 生成器 — 首次使用请配置模型</p>

      <div class="steps-indicator">
        <span
          v-for="s in totalSteps"
          :key="s"
          class="step-dot"
          :class="{ active: s === step, done: s < step }"
        />
      </div>

      <!-- Step 1: Select Provider OR Subscription -->
      <div v-if="step === 1" class="step-content">
        <h2 class="step-heading">选择 AI 提供商</h2>
        <div class="provider-grid">
          <McCard
            v-for="p in providers"
            :key="p.id"
            class="provider-card"
            @click="selectProvider(p)"
          >
            <div class="provider-name">{{ p.name }}</div>
            <div v-if="p.free_tier" class="provider-badge">免费</div>
          </McCard>
        </div>

        <div class="divider-or">
          <span class="divider-line" />
          <span class="divider-text">或</span>
          <span class="divider-line" />
        </div>

        <McCard class="subscription-card" @click="enterSubscriptionMode">
          <div class="subscription-card-inner">
            <div class="subscription-card-title">使用订阅</div>
            <div class="subscription-card-desc">
              兑换订阅码，使用开发者提供的模型，无需自行配置
            </div>
          </div>
          <div class="provider-badge sub-badge">免配置</div>
        </McCard>

        <div class="skip-link-row">
          <a class="skip-link" @click="skipSetup">暂时跳过，先使用命令编辑器</a>
        </div>
      </div>

      <!-- Step 2 (API Key mode): Enter API Key -->
      <div v-if="step === 2 && !subscriptionMode" class="step-content">
        <h2 class="step-heading">输入 API Key</h2>
        <p class="step-desc">提供商: {{ selectedProvider?.name }}</p>
        <div class="form-group">
          <McInput
            :model-value="apiKey"
            @update:model-value="apiKey = $event"
            placeholder="sk-..."
            class="api-key-input"
          />
          <a
            v-if="selectedProvider && providerLinks[selectedProvider.id]"
            :href="providerLinks[selectedProvider.id]"
            target="_blank"
            class="help-link"
          >
            如何获取 API Key?
          </a>
        </div>

        <!-- Custom provider: base URL -->
        <div v-if="selectedProvider?.id === 'custom'" class="form-group">
          <label class="form-label">API Base URL</label>
          <McInput
            :model-value="customBaseUrl"
            @update:model-value="customBaseUrl = $event"
            placeholder="https://api.example.com/v1"
          />
        </div>

        <div class="step-actions">
          <McButton @click="step = 1">上一步</McButton>
          <McButton variant="primary" :disabled="!apiKey.trim()" @click="step = 3">
            下一步
          </McButton>
        </div>
      </div>

      <!-- Step 2 (Subscription mode): Pick a plan and pay -->
      <div v-if="step === 2 && subscriptionMode" class="step-content">
        <h2 class="step-heading">使用订阅</h2>
        <p class="sub-desc">
          微信扫码付款，付款备注填写订单号，订阅自动激活。
        </p>

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
              <li v-if="plan.build_monthly > 0">Build {{ plan.build_monthly }} 次/月</li>
              <li v-else class="dim">不含 Build 模式</li>
            </ul>
            <McButton variant="primary" class="plan-card-btn" @click="startSubscribe(plan)">
              立即订阅
            </McButton>
          </div>
        </div>

        <div v-if="subStore.isActive" class="sub-section status-active">
          <div class="plan-badge">{{ subStore.planName }}</div>
          <span class="status-hint">订阅已激活，可以开始使用</span>
        </div>

        <div class="step-actions">
          <McButton @click="backToStep1">上一步</McButton>
          <McButton
            variant="primary"
            :disabled="!subStore.isActive"
            @click="finishSubscription"
          >
            开始使用
          </McButton>
        </div>
      </div>

      <!-- Step 3: Select Model -->
      <div v-if="step === 3" class="step-content">
        <h2 class="step-heading">选择模型</h2>

        <!-- Normal providers with model list -->
        <div v-if="modelList().length > 0" class="model-list">
          <McCard
            v-for="m in modelList()"
            :key="m"
            class="model-card"
            :class="{ selected: selectedModel === m }"
            @click="selectedModel = m"
          >
            {{ m }}
          </McCard>
        </div>

        <!-- Providers that need manual input (doubao, custom) -->
        <div v-else class="form-group">
          <label class="form-label">
            {{ selectedProvider?.requires_endpoint_id ? '输入接入点 ID (Endpoint ID)' : '输入模型名称' }}
          </label>
          <McInput
            :model-value="customModel"
            @update:model-value="customModel = $event"
            :placeholder="selectedProvider?.requires_endpoint_id ? 'ep-xxxxx' : 'model-name'"
          />
        </div>

        <div class="step-actions">
          <McButton @click="step = 2">上一步</McButton>
          <McButton
            variant="primary"
            :disabled="!selectedModel && !customModel.trim()"
            @click="step = 4; doVerify()"
          >
            验证连接
          </McButton>
        </div>
      </div>

      <!-- Step 4: Verify & Finish -->
      <div v-if="step === 4" class="step-content">
        <h2 class="step-heading">验证连接</h2>

        <div v-if="verifying" class="verify-status">
          <div class="verify-spinner" />
          <span>正在连接...</span>
        </div>

        <div v-else-if="verifyResult" class="verify-status">
          <div v-if="verifyResult.ok" class="verify-success">
            <span class="verify-icon">&#10003;</span>
            <span>连接成功！延迟: {{ verifyResult.latency_ms }}ms</span>
          </div>
          <div v-else class="verify-fail">
            <span class="verify-icon">&#10007;</span>
            <span>{{ verifyResult.error || '连接失败' }}</span>
          </div>
        </div>

        <div class="step-actions">
          <McButton @click="step = 3">上一步</McButton>
          <McButton v-if="verifyResult && !verifyResult.ok" @click="doVerify()">
            重试
          </McButton>
          <McButton
            variant="primary"
            :disabled="!verifyResult?.ok"
            @click="finish"
          >
            开始使用
          </McButton>
        </div>
      </div>
    </div>
    <AuthModal v-model:show="authStore.showAuthModal" />
    <PaymentDialog
      v-model:show="paymentDialog.show"
      :plan-id="paymentDialog.planId"
      :plan-name="paymentDialog.planName"
      :amount="paymentDialog.amount"
    />
  </div>
</template>

<style scoped>
.setup-page {
  height: 100vh;
  height: 100dvh;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 16px;
  padding-bottom: calc(16px + env(safe-area-inset-bottom, 0px));
  overflow-y: auto;
}

.setup-container {
  max-width: 480px;
  width: 100%;
  margin: auto 0;
}

.setup-logo {
  display: block;
  margin: 0 auto 8px;
  width: 96px;
  height: 96px;
  image-rendering: pixelated;
  border-radius: 8px;
}

.setup-title {
  text-align: center;
  font-family: var(--mc-font-title);
  font-size: 22px;
  color: var(--mc-gold);
  text-shadow: 2px 2px 0 rgba(0, 0, 0, 0.5);
  margin: 0 0 4px;
}

.setup-subtitle {
  text-align: center;
  color: var(--mc-text-secondary);
  font-size: 13px;
  margin-bottom: 14px;
}

.steps-indicator {
  display: flex;
  justify-content: center;
  gap: 6px;
  margin-bottom: 14px;
}

.step-dot {
  width: 8px;
  height: 8px;
  border: 2px solid var(--mc-border);
  background: transparent;
}

.step-dot.active {
  background: var(--mc-gold);
  border-color: var(--mc-gold);
}

.step-dot.done {
  background: var(--mc-green);
  border-color: var(--mc-green);
}

.step-content {
  background: var(--mc-bg-card);
  border: 2px solid var(--mc-border);
  padding: 16px 18px;
}

.step-heading {
  font-family: var(--mc-font-title);
  color: var(--mc-text-primary);
  font-size: 15px;
  margin-bottom: 10px;
}

.step-desc {
  color: var(--mc-text-secondary);
  font-size: 13px;
  margin-bottom: 12px;
}

.provider-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(100px, 1fr));
  gap: 8px;
}

.provider-card {
  cursor: pointer;
  text-align: center;
  padding: 10px 6px;
  position: relative;
  transition: border-color 150ms;
}

.provider-card:hover {
  border-color: var(--mc-gold);
}

.provider-name {
  font-family: var(--mc-font-title);
  font-size: 13px;
}

.provider-badge {
  position: absolute;
  top: 4px;
  right: 4px;
  background: var(--mc-green);
  color: #fff;
  font-size: 10px;
  padding: 1px 6px;
  font-family: var(--mc-font-mono);
}

/* Divider */
.divider-or {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 12px 0;
}

.divider-line {
  flex: 1;
  height: 1px;
  background: var(--mc-border);
}

.divider-text {
  color: var(--mc-text-secondary);
  font-size: 13px;
  flex-shrink: 0;
}

/* Subscription card */
.subscription-card {
  cursor: pointer;
  padding: 10px 14px;
  position: relative;
  transition: border-color 150ms;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.subscription-card:hover {
  border-color: var(--mc-gold);
}

.subscription-card-title {
  font-family: var(--mc-font-title);
  font-size: 13px;
  color: var(--mc-gold);
  margin-bottom: 2px;
}

.subscription-card-desc {
  font-size: 11px;
  color: var(--mc-text-secondary);
  line-height: 1.4;
}

.sub-badge {
  position: static;
  flex-shrink: 0;
  margin-left: 12px;
  background: var(--mc-gold);
}

/* Subscription step */
.sub-section {
  margin-bottom: 16px;
}

.sub-heading {
  font-family: var(--mc-font-title);
  color: var(--mc-text-primary);
  font-size: 14px;
  margin: 0 0 8px;
}

.sub-desc {
  margin: 0 0 10px;
  font-size: 12px;
  color: var(--mc-text-secondary);
  line-height: 1.5;
}

.plan-cards {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  margin-bottom: 12px;
}

.plan-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px;
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
  font-size: 13px;
  color: var(--mc-gold);
}

.plan-card-price {
  font-family: var(--mc-font-mono);
  font-size: 18px;
  color: var(--mc-text-primary);
  font-weight: bold;
}

.plan-card-unit {
  font-size: 10px;
  color: var(--mc-text-dim);
  font-weight: normal;
  margin-left: 3px;
}

.plan-card-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 11px;
  color: var(--mc-text-secondary);
  flex: 1;
}

.plan-card-list .dim {
  color: var(--mc-text-dim);
}

.plan-card-btn {
  width: 100%;
}

.status-active {
  background: rgba(85, 255, 85, 0.06);
  border: 1px solid var(--mc-green);
  padding: 12px;
  display: flex;
  align-items: center;
  gap: 10px;
}

.plan-badge {
  display: inline-block;
  background: var(--mc-gold);
  color: #1a1a2e;
  font-family: var(--mc-font-title);
  font-size: 13px;
  padding: 2px 10px;
  flex-shrink: 0;
}

.status-hint {
  font-size: 13px;
  color: var(--mc-green);
}

.form-group {
  margin-bottom: 16px;
}

.form-label {
  display: block;
  font-size: 13px;
  color: var(--mc-text-secondary);
  margin-bottom: 6px;
}

.help-link {
  display: inline-block;
  margin-top: 8px;
  font-size: 12px;
  color: var(--mc-gold);
  text-decoration: underline;
}

.model-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 16px;
}

.model-card {
  cursor: pointer;
  padding: 10px 16px;
  font-family: var(--mc-font-mono);
  font-size: 13px;
  transition: border-color 150ms;
}

.model-card:hover {
  border-color: var(--mc-gold);
}

.model-card.selected {
  border-color: var(--mc-gold);
  color: var(--mc-gold);
}

.step-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  margin-top: 14px;
}

.verify-status {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  font-size: 14px;
}

.verify-spinner {
  width: 20px;
  height: 20px;
  border: 3px solid var(--mc-border);
  border-top-color: var(--mc-gold);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.verify-success {
  color: var(--mc-green);
  display: flex;
  align-items: center;
  gap: 8px;
}

.verify-fail {
  color: var(--mc-red);
  display: flex;
  align-items: center;
  gap: 8px;
}

.verify-icon {
  font-size: 20px;
  font-weight: bold;
}

.skip-link-row {
  text-align: center;
  margin-top: 12px;
}

.skip-link {
  font-size: 12px;
  color: var(--mc-text-dim);
  text-decoration: underline;
  cursor: pointer;
}

.skip-link:hover {
  color: var(--mc-text-secondary);
}

.api-key-input :deep(.mc-input) {
  -webkit-text-security: disc;
}

@media (max-width: 768px) {
  .provider-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  .plan-cards {
    grid-template-columns: 1fr;
  }
}

/* Landscape compact: short viewport */
@media (max-height: 500px) {
  .setup-logo {
    width: 64px;
    height: 64px;
    margin-bottom: 4px;
  }
  .setup-subtitle {
    margin-bottom: 6px;
    font-size: 12px;
  }
  .steps-indicator {
    margin-bottom: 6px;
  }
  .step-content {
    padding: 10px 14px;
  }
  .step-heading {
    font-size: 14px;
    margin-bottom: 6px;
  }
  .provider-grid {
    gap: 4px;
  }
  .provider-card {
    padding: 6px 4px;
  }
  .provider-name {
    font-size: 12px;
  }
  .divider-or {
    margin: 6px 0;
  }
  .subscription-card {
    padding: 6px 10px;
  }
  .subscription-card-desc {
    font-size: 10px;
  }
  .skip-link-row {
    margin-top: 6px;
  }
  .step-actions {
    margin-top: 8px;
  }
  .sub-section {
    margin-bottom: 10px;
  }
  .verify-status {
    padding: 10px;
  }
}
</style>
