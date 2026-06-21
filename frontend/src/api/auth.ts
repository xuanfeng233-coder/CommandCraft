/**
 * Auth API — SSO via BraynLabs + device management.
 * Login/register happens on BraynLabs; this module only handles
 * session checking, logout, and device management.
 */

import { getApiBase } from '@/utils/api-base'

export interface UserInfo {
  user_id: number
  username: string
  email: string | null
  email_verified: boolean
}

export interface DeviceInfo {
  token: string
  user_agent: string
  ip_addr: string
  created_at: string
  last_active_at: string
  is_current: boolean
}

async function authFetch(url: string, options: RequestInit = {}): Promise<Response> {
  const base = getApiBase()
  return fetch(`${base}${url}`, {
    ...options,
    credentials: 'same-origin',
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
  })
}

export async function logout(): Promise<void> {
  await authFetch('/api/auth/logout', { method: 'POST' })
}

export async function fetchMe(): Promise<UserInfo | null> {
  const res = await authFetch('/api/auth/me')
  if (!res.ok) return null
  const data = await res.json()
  return data.user ?? null
}

export async function listDevices(): Promise<DeviceInfo[]> {
  const res = await authFetch('/api/auth/devices')
  if (!res.ok) return []
  const data = await res.json()
  return data.devices ?? []
}

export async function kickDevice(token: string): Promise<void> {
  const res = await authFetch('/api/auth/kick', {
    method: 'POST',
    body: JSON.stringify({ token }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: '操作失败' }))
    throw new Error(err.detail || '操作失败')
  }
}
