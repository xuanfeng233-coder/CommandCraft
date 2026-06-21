/**
 * Subscription API — calls backend subscription endpoints.
 */

import { getDeviceFingerprint } from '@/utils/fingerprint'
import { getApiBase } from '@/utils/api-base'

export interface PlanInfo {
  id: string
  name: string
  daily_limit: number
  monthly_limit: number
  build_monthly: number
  price_cny: string
  duration_days: number
}

export interface SubscriptionPlan {
  plan: string
  plan_name: string
  daily_limit: number
  monthly_limit: number
  expires_at: string
}

export interface SubscriptionRecord {
  id: number
  device_fp: string
  plan: string
  starts_at: string
  expires_at: string
  code: string | null
  source: string
  order_id: string | null
}

export interface SubscriptionStatus {
  active: boolean
  plan: SubscriptionPlan | null
  usage: { daily: number; monthly: number }
  build_usage: number
  build_limit: number
  subscriptions: SubscriptionRecord[]
}

export type WxpayOrderStatus =
  | 'pending'
  | 'paid'
  | 'amount_mismatch'
  | 'expired'
  | 'cancelled'

export interface WxpayOrder {
  order_id: string
  status: WxpayOrderStatus
  plan: string
  plan_name?: string
  amount: string
  actual_amount?: string | null
  amount_diff?: string | null
  amount_diff_kind?: 'exact' | 'overpaid' | 'underpaid' | null
  expires_at: string
  paid_at?: string | null
  created_at?: string
  activated: boolean
  subscription_id?: number | null
  payment_remark_hint: string
  qr_image_url: string
}

export async function createOrder(planId: string): Promise<WxpayOrder> {
  const device_fp = await getDeviceFingerprint()
  const base = getApiBase()
  const res = await fetch(`${base}/api/subscription/orders`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    body: JSON.stringify({ plan_id: planId, device_fp }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: '下单失败' }))
    throw new Error(err.detail || '下单失败')
  }
  return res.json()
}

export async function getOrder(orderId: string): Promise<WxpayOrder> {
  const base = getApiBase()
  const res = await fetch(`${base}/api/subscription/orders/${encodeURIComponent(orderId)}`, {
    credentials: 'same-origin',
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: '订单查询失败' }))
    throw new Error(err.detail || '订单查询失败')
  }
  return res.json()
}

export async function cancelOrder(orderId: string): Promise<WxpayOrder> {
  const base = getApiBase()
  const res = await fetch(`${base}/api/subscription/orders/${encodeURIComponent(orderId)}`, {
    method: 'DELETE',
    credentials: 'same-origin',
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: '取消订单失败' }))
    throw new Error(err.detail || '取消订单失败')
  }
  return res.json()
}

export async function getSubscriptionStatus(): Promise<SubscriptionStatus> {
  const device_fp = await getDeviceFingerprint()
  const base = getApiBase()
  const res = await fetch(
    `${base}/api/subscription/status?device_fp=${encodeURIComponent(device_fp)}`,
    { credentials: 'same-origin' },
  )
  if (!res.ok) {
    return {
      active: false,
      plan: null,
      usage: { daily: 0, monthly: 0 },
      build_usage: 0,
      build_limit: 0,
      subscriptions: [],
    }
  }
  return res.json()
}

export async function getPlans(): Promise<PlanInfo[]> {
  const base = getApiBase()
  const res = await fetch(`${base}/api/subscription/plans`)
  if (!res.ok) return []
  const data = await res.json()
  return data.plans ?? []
}
