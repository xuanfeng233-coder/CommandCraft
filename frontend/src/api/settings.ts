/**
 * Settings API — calls backend /api/settings/*
 */

import type { ProviderInfo, LLMSettings } from '@/types'

export async function getProviders(): Promise<ProviderInfo[]> {
  const resp = await fetch('/api/settings/providers')
  if (!resp.ok) throw new Error('Failed to fetch providers')
  return resp.json()
}

export async function postConfig(config: LLMSettings): Promise<void> {
  const resp = await fetch('/api/settings/config', {
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
  const resp = await fetch('/api/settings/verify', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  })
  if (!resp.ok) throw new Error('Verification request failed')
  return resp.json()
}

/**
 * Load saved settings — no-op in web mode (backend manages config).
 */
export function loadSavedSettings(): LLMSettings | null {
  return null
}
