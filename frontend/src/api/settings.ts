import type { ProviderInfo, LLMSettings } from '@/types'

const API_BASE = '/api/settings'

export async function getProviders(): Promise<ProviderInfo[]> {
  const resp = await fetch(`${API_BASE}/providers`)
  if (!resp.ok) throw new Error('Failed to fetch providers')
  return resp.json()
}

export async function postConfig(config: LLMSettings): Promise<void> {
  const resp = await fetch(`${API_BASE}/config`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  })
  if (!resp.ok) throw new Error('Failed to save config')
}

export interface VerifyResult {
  ok: boolean
  latency_ms: number
  error: string
  model: string
}

export async function verifyConfig(config: LLMSettings): Promise<VerifyResult> {
  const resp = await fetch(`${API_BASE}/verify`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  })
  if (!resp.ok) throw new Error('Verification request failed')
  return resp.json()
}
