<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { McModal, McButton } from '@/components/mc-ui'
import { useSubscriptionStore } from '@/stores/subscription'
import type { WxpayOrder } from '@/api/subscription'

const props = defineProps<{
  show: boolean
  planId: string
  planName: string
  amount: string
}>()

const emit = defineEmits<{
  'update:show': [val: boolean]
  'success': []
}>()

const subStore = useSubscriptionStore()

const order = ref<WxpayOrder | null>(null)
const error = ref('')
const creating = ref(false)
const remainingSeconds = ref(0)
const copied = ref(false)
let abortController: AbortController | null = null
let countdownTimer: ReturnType<typeof setInterval> | null = null

const status = computed(() => order.value?.status ?? 'pending')
const isActivated = computed(() => order.value?.activated ?? false)
const isUnderpaid = computed(
  () => status.value === 'amount_mismatch' && order.value?.amount_diff_kind === 'underpaid',
)
const isOverpaid = computed(
  () => status.value === 'amount_mismatch' && order.value?.amount_diff_kind === 'overpaid',
)
const isSuccess = computed(
  () => isActivated.value && (status.value === 'paid' || isOverpaid.value),
)

const remainingDisplay = computed(() => {
  const s = Math.max(0, remainingSeconds.value)
  const m = Math.floor(s / 60)
  const ss = s % 60
  return `${m}:${ss.toString().padStart(2, '0')}`
})

const amountDiffAbs = computed(() => {
  const raw = order.value?.amount_diff
  if (!raw) return ''
  const n = Number(raw)
  if (Number.isNaN(n)) return raw
  return Math.abs(n).toFixed(2)
})

watch(
  () => props.show,
  (val) => {
    if (val) {
      void start()
    } else {
      stop()
    }
  },
  { immediate: false },
)

onMounted(() => {
  if (props.show) void start()
})

onBeforeUnmount(() => {
  stop()
})

async function start() {
  reset()
  creating.value = true
  try {
    const created = await subStore.createOrder(props.planId)
    order.value = created
    creating.value = false
    startCountdown(created.expires_at)
    void runPolling(created.order_id)
  } catch (e: unknown) {
    creating.value = false
    error.value = e instanceof Error ? e.message : '下单失败'
  }
}

async function runPolling(orderId: string) {
  abortController = new AbortController()
  try {
    await subStore.pollOrder(
      orderId,
      (o) => {
        order.value = o
        if (o.status === 'paid' || o.status === 'amount_mismatch') {
          if (o.activated) {
            void subStore.fetchStatus()
            // Auto-close on success after a moment so the user sees the state.
            setTimeout(() => {
              emit('success')
              emit('update:show', false)
            }, 1800)
          }
        }
      },
      abortController.signal,
    )
  } catch (e) {
    if ((e as Error)?.name !== 'AbortError') {
      error.value = e instanceof Error ? e.message : '轮询失败'
    }
  }
}

function reset() {
  order.value = null
  error.value = ''
  copied.value = false
  remainingSeconds.value = 0
}

function stop() {
  abortController?.abort()
  abortController = null
  if (countdownTimer) {
    clearInterval(countdownTimer)
    countdownTimer = null
  }
}

function startCountdown(expiresAtIso: string) {
  const expiresAt = new Date(expiresAtIso).getTime()
  const tick = () => {
    remainingSeconds.value = Math.floor((expiresAt - Date.now()) / 1000)
  }
  tick()
  countdownTimer = setInterval(tick, 1000)
}

async function copyOrderId() {
  if (!order.value) return
  try {
    await navigator.clipboard.writeText(order.value.order_id)
    copied.value = true
    setTimeout(() => (copied.value = false), 1500)
  } catch {
    // Clipboard not available — silently ignore.
  }
}

async function cancel() {
  if (order.value && status.value === 'pending') {
    try {
      await subStore.cancelOrder(order.value.order_id)
    } catch {
      // ignore — closing is the user's intent
    }
  }
  emit('update:show', false)
}

async function retry() {
  await start()
}
</script>

<template>
  <McModal :show="show" @update:show="emit('update:show', $event)">
    <div class="payment-dialog">
      <h2 class="payment-title">订阅 {{ planName }}</h2>

      <!-- Loading: order being created -->
      <div v-if="creating" class="state-row">
        <div class="spinner" />
        <span>正在创建订单...</span>
      </div>

      <!-- Error before order created -->
      <div v-else-if="error && !order" class="error-block">
        <p class="error-text">{{ error }}</p>
        <McButton variant="primary" @click="retry">重试</McButton>
        <McButton @click="emit('update:show', false)">关闭</McButton>
      </div>

      <!-- Order ready: pending / paid / mismatch / expired -->
      <div v-else-if="order" class="payment-body">
        <!-- Success state -->
        <div v-if="isSuccess" class="result success">
          <div class="result-icon">✓</div>
          <h3>支付成功</h3>
          <p v-if="isOverpaid">感谢支持！多付 ¥{{ amountDiffAbs }} 已记入打赏，订阅已激活。</p>
          <p v-else>{{ planName }} 套餐已激活，正在为你刷新...</p>
        </div>

        <!-- Underpaid: not activated -->
        <div v-else-if="isUnderpaid" class="result warn">
          <div class="result-icon">!</div>
          <h3>金额不足</h3>
          <p>您少付了 ¥{{ amountDiffAbs }}，订阅未激活。</p>
          <p class="result-sub">请补足金额或联系客服处理。</p>
          <McButton @click="emit('update:show', false)">关闭</McButton>
        </div>

        <!-- Expired / cancelled -->
        <div v-else-if="status === 'expired' || status === 'cancelled'" class="result warn">
          <div class="result-icon">×</div>
          <h3>{{ status === 'expired' ? '订单已过期' : '订单已取消' }}</h3>
          <p>请重新下单。</p>
          <div class="action-row">
            <McButton variant="primary" @click="retry">重新下单</McButton>
            <McButton @click="emit('update:show', false)">关闭</McButton>
          </div>
        </div>

        <!-- Pending: show QR + order id + amount -->
        <div v-else class="pending-grid">
          <div class="qr-box">
            <img src="/images/payment.png" alt="微信收款二维码" class="qr-image" />
            <div class="qr-caption">微信扫码付款</div>
          </div>

          <div class="info-box">
            <div class="info-row">
              <span class="info-label">金额</span>
              <span class="info-amount">¥{{ amount }}</span>
            </div>
            <div class="info-row">
              <span class="info-label">订单号</span>
              <span class="order-id" @click="copyOrderId" :title="copied ? '已复制' : '点击复制'">
                {{ order.order_id }}
                <span class="copy-hint">{{ copied ? '✓ 已复制' : '点击复制' }}</span>
              </span>
            </div>
            <div class="hint-block">
              <p class="hint-strong">{{ order.payment_remark_hint }}</p>
              <p class="hint-sub">扫码 → 输入金额 → <b>付款备注里写订单号</b> → 自动激活</p>
            </div>
            <div class="status-row">
              <div class="spinner" />
              <span>等待付款 · 剩余 {{ remainingDisplay }}</span>
            </div>
            <div class="action-row">
              <McButton @click="cancel">取消订单</McButton>
            </div>
          </div>
        </div>
      </div>
    </div>
  </McModal>
</template>

<style scoped>
.payment-dialog {
  width: 560px;
  max-width: 92vw;
  padding: 24px;
}

.payment-title {
  font-family: var(--mc-font-title);
  color: var(--mc-gold);
  font-size: 18px;
  margin: 0 0 16px;
}

.state-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 24px 0;
  color: var(--mc-text-secondary);
  font-size: 13px;
  justify-content: center;
}

.error-block {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 16px 0;
}

.error-text {
  color: var(--mc-red);
  font-size: 13px;
}

/* Pending layout */
.pending-grid {
  display: grid;
  grid-template-columns: 200px 1fr;
  gap: 24px;
  align-items: start;
}

.qr-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.qr-image {
  width: 200px;
  height: 200px;
  object-fit: contain;
  background: #fff;
  border: 2px solid var(--mc-border);
  padding: 4px;
  image-rendering: pixelated;
}

.qr-caption {
  font-size: 12px;
  color: var(--mc-text-secondary);
}

.info-box {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.info-row {
  display: flex;
  align-items: baseline;
  gap: 12px;
}

.info-label {
  width: 60px;
  font-size: 12px;
  color: var(--mc-text-secondary);
  flex-shrink: 0;
}

.info-amount {
  font-family: var(--mc-font-mono);
  font-size: 22px;
  color: var(--mc-gold);
  font-weight: bold;
}

.order-id {
  font-family: var(--mc-font-mono);
  font-size: 24px;
  color: var(--mc-text-primary);
  letter-spacing: 4px;
  cursor: pointer;
  user-select: all;
  transition: color 150ms;
  display: inline-flex;
  align-items: baseline;
  gap: 10px;
}

.order-id:hover {
  color: var(--mc-gold);
}

.copy-hint {
  font-size: 11px;
  letter-spacing: 0;
  color: var(--mc-text-dim);
}

.hint-block {
  background: var(--mc-bg-deep, var(--mc-bg-main));
  border: 1px solid var(--mc-border);
  padding: 8px 10px;
  margin-top: 4px;
}

.hint-strong {
  margin: 0 0 4px;
  font-size: 13px;
  color: var(--mc-gold);
}

.hint-sub {
  margin: 0;
  font-size: 12px;
  color: var(--mc-text-secondary);
  line-height: 1.5;
}

.status-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--mc-text-secondary);
}

.spinner {
  width: 16px;
  height: 16px;
  border: 2px solid var(--mc-border);
  border-top-color: var(--mc-gold);
  animation: payment-spin 0.7s linear infinite;
  flex-shrink: 0;
}

@keyframes payment-spin {
  to { transform: rotate(360deg); }
}

.action-row {
  display: flex;
  gap: 8px;
}

/* Result states */
.result {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: 8px;
  padding: 24px 8px;
}

.result h3 {
  margin: 0;
  font-family: var(--mc-font-title);
  font-size: 16px;
  color: var(--mc-text-primary);
}

.result p {
  margin: 0;
  font-size: 13px;
  color: var(--mc-text-secondary);
}

.result-sub {
  font-size: 12px;
  color: var(--mc-text-dim);
}

.result-icon {
  width: 56px;
  height: 56px;
  border-radius: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 32px;
  font-family: var(--mc-font-title);
  margin-bottom: 4px;
}

.result.success .result-icon {
  background: var(--mc-green);
  color: #fff;
}

.result.warn .result-icon {
  background: var(--mc-red);
  color: #fff;
}

@media (max-width: 580px) {
  .pending-grid {
    grid-template-columns: 1fr;
  }
  .qr-box {
    align-self: center;
  }
}
</style>
