import { getDeviceFingerprint } from '@/utils/fingerprint'

export interface PlanInfo {
  id: string
  name: string
  daily_limit: number
  monthly_limit: number
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
  code: string
}

export interface SubscriptionStatus {
  active: boolean
  plan: SubscriptionPlan | null
  usage: { daily: number; monthly: number }
  subscriptions: SubscriptionRecord[]
}

export interface RedeemResult {
  success: boolean
  plan: string
  plan_name: string
  starts_at: string
  expires_at: string
  message: string
}

export async function redeemCode(code: string): Promise<RedeemResult> {
  const fp = await getDeviceFingerprint()
  const res = await fetch('/api/subscription/redeem', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code, device_fp: fp }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: '兑换失败' }))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

export async function getSubscriptionStatus(): Promise<SubscriptionStatus> {
  const fp = await getDeviceFingerprint()
  const res = await fetch(`/api/subscription/status?device_fp=${encodeURIComponent(fp)}`)
  if (!res.ok) throw new Error(`Failed to get status: ${res.status}`)
  return res.json()
}

export async function getPlans(): Promise<PlanInfo[]> {
  const res = await fetch('/api/subscription/plans')
  if (!res.ok) throw new Error(`Failed to get plans: ${res.status}`)
  const data = await res.json()
  return data.plans
}
