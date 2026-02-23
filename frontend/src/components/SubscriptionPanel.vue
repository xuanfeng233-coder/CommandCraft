<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { McModal, McButton, McInput } from '@/components/mc-ui'
import { useSubscriptionStore } from '@/stores/subscription'
import { getPlans, type PlanInfo } from '@/api/subscription'

const props = defineProps<{ show: boolean }>()
const emit = defineEmits<{ 'update:show': [val: boolean] }>()

const subStore = useSubscriptionStore()

const redeemCode = ref('')
const redeemError = ref('')
const redeemSuccess = ref('')
const plans = ref<PlanInfo[]>([])

watch(() => props.show, async (val) => {
  if (val) {
    redeemCode.value = ''
    redeemError.value = ''
    redeemSuccess.value = ''
    await subStore.fetchStatus()
    if (plans.value.length === 0) {
      try {
        plans.value = await getPlans()
      } catch { /* ignore */ }
    }
  }
})

async function handleRedeem() {
  const code = redeemCode.value.trim()
  if (!code) return

  redeemError.value = ''
  redeemSuccess.value = ''

  try {
    const result = await subStore.redeem(code)
    redeemSuccess.value = result.message
    redeemCode.value = ''
  } catch (e: unknown) {
    redeemError.value = e instanceof Error ? e.message : '兑换失败'
  }
}

const expiresFormatted = computed(() => {
  if (!subStore.status?.plan?.expires_at) return ''
  const d = new Date(subStore.status.plan.expires_at)
  return d.toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' })
})

function openPurchasePage() {
  window.open('https://afdian.com/a/brayn', '_blank')
}

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
    <div class="sub-panel">
      <div class="sub-header">
        <h2>订阅服务</h2>
        <button class="close-btn" @click="emit('update:show', false)">&times;</button>
      </div>

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

      <!-- Purchase Section -->
      <div class="sub-section">
        <h3>购买兑换码</h3>
        <p class="sub-desc">在爱发电购买兑换码，即可使用开发者提供的 DeepSeek 模型，无需自行配置 API Key。</p>
        <McButton
          variant="primary"
          @click="openPurchasePage"
        >
          前往爱发电购买
        </McButton>
      </div>

      <!-- Redeem Section -->
      <div class="sub-section">
        <h3>兑换</h3>
        <div class="redeem-row">
          <McInput
            :model-value="redeemCode"
            @update:model-value="redeemCode = $event"
            placeholder="输入兑换码"
            class="redeem-input"
            @keydown.enter="handleRedeem"
          />
          <McButton
            variant="primary"
            :loading="subStore.loading"
            :disabled="!redeemCode.trim()"
            @click="handleRedeem"
          >
            兑换
          </McButton>
        </div>
        <div v-if="redeemError" class="msg-error">{{ redeemError }}</div>
        <div v-if="redeemSuccess" class="msg-success">{{ redeemSuccess }}</div>
      </div>

      <!-- Plan Comparison -->
      <div class="sub-section">
        <h3>套餐对比</h3>
        <table class="plan-table">
          <thead>
            <tr>
              <th>套餐</th>
              <th>每日次数</th>
              <th>每月次数</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="plan in plans" :key="plan.id"
                :class="{ 'current-plan': subStore.isActive && subStore.status?.plan?.plan === plan.id }">
              <td class="plan-name">{{ plan.name }}</td>
              <td>{{ plan.daily_limit }}</td>
              <td>{{ plan.monthly_limit }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </McModal>
</template>

<style scoped>
.sub-panel {
  padding: 24px;
  min-width: 400px;
  max-width: 520px;
}

.sub-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.sub-header h2 {
  margin: 0;
  font-family: var(--mc-font-title);
  color: var(--mc-gold);
  font-size: 18px;
}

.close-btn {
  background: none;
  border: none;
  color: #ffffff;
  font-size: 24px;
  cursor: pointer;
  padding: 0 4px;
}

.close-btn:hover {
  color: var(--mc-text-primary);
}

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

/* Status */
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

/* Redeem */
.redeem-row {
  display: flex;
  gap: 8px;
  align-items: flex-start;
}

.redeem-input {
  flex: 1;
}

.msg-error {
  margin-top: 6px;
  font-size: 12px;
  color: var(--mc-red);
}

.msg-success {
  margin-top: 6px;
  font-size: 12px;
  color: var(--mc-green);
}

/* Plan table */
.plan-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.plan-table th,
.plan-table td {
  padding: 6px 12px;
  text-align: center;
  border: 1px solid var(--mc-border);
}

.plan-table th {
  background: var(--mc-bg-main);
  color: #ffffff;
  font-family: var(--mc-font-title);
  font-weight: normal;
}

.plan-table .plan-name {
  font-family: var(--mc-font-title);
  color: var(--mc-gold);
}

.plan-table .current-plan {
  background: rgba(255, 170, 0, 0.08);
}

@media (max-width: 520px) {
  .sub-panel {
    min-width: unset;
    padding: 16px;
  }
}
</style>
