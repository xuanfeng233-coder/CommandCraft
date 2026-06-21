/**
 * Chat API — calls backend /api/chat via SSE streaming.
 */

import type { SessionSummary, SessionMessage, TaskItem } from '@/types'

export interface SSECallbacks {
  onThinking: (text: string) => void
  onContent: (data: Record<string, unknown>) => void
  onDone: (data: Record<string, unknown>) => void
  onError: (err: string) => void
  onTaskList?: (data: { project_name: string; overview: string; tasks: TaskItem[] }) => void
  onTaskUpdate?: (data: { task_id: string; status: string; result?: Record<string, unknown>; error?: string }) => void
  onTaskThinking?: (data: { task_id: string; text: string }) => void
  // Backward compat
  onSubTaskList?: (tasks: TaskItem[]) => void
  onSubTaskUpdate?: (data: { task_id: string; status: string; result?: Record<string, unknown>; error?: string }) => void
}

// ---------------------------------------------------------------------------
// SSE parser
// ---------------------------------------------------------------------------

function parseSSELines(
  buffer: string,
  callbacks: SSECallbacks,
): string {
  const normalised = buffer.replace(/\r\n/g, '\n')
  const parts = normalised.split('\n\n')
  const remaining = parts.pop() ?? ''

  for (const part of parts) {
    const trimmed = part.trim()
    if (!trimmed) continue

    let eventName = ''
    let dataStr = ''

    const lines = trimmed.split('\n')
    for (const line of lines) {
      const cleaned = line.trim()
      if (cleaned.startsWith('event:')) {
        eventName = cleaned.slice(6).trim()
      } else if (cleaned.startsWith('data:')) {
        dataStr = cleaned.slice(5).trim()
      }
    }

    if (!eventName || !dataStr) continue

    let parsed: Record<string, unknown>
    try {
      parsed = JSON.parse(dataStr)
    } catch {
      callbacks.onError(`Failed to parse SSE data: ${dataStr}`)
      continue
    }

    switch (eventName) {
      case 'thinking':
        callbacks.onThinking((parsed.text as string) ?? '')
        break
      case 'content':
        callbacks.onContent(parsed)
        break
      case 'done':
        callbacks.onDone(parsed)
        break
      case 'error':
        callbacks.onError((parsed.message as string) ?? 'Unknown error')
        break
      case 'task_list':
        callbacks.onTaskList?.(parsed as { project_name: string; overview: string; tasks: TaskItem[] })
        callbacks.onSubTaskList?.((parsed.tasks as TaskItem[]) ?? [])
        break
      case 'task_update':
        callbacks.onTaskUpdate?.(parsed as { task_id: string; status: string; result?: Record<string, unknown>; error?: string })
        callbacks.onSubTaskUpdate?.(parsed as { task_id: string; status: string; result?: Record<string, unknown>; error?: string })
        break
      case 'task_thinking':
        callbacks.onTaskThinking?.(parsed as { task_id: string; text: string })
        break
      case 'summary':
        callbacks.onContent(parsed)
        break
      case 'subtask_list':
        callbacks.onSubTaskList?.((parsed.tasks as TaskItem[]) ?? [])
        break
      case 'subtask_update':
        callbacks.onSubTaskUpdate?.(parsed as { task_id: string; status: string; result?: Record<string, unknown>; error?: string })
        break
      default:
        break
    }
  }

  return remaining
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export async function sendMessage(
  message: string,
  sessionId: string | null,
  callbacks: SSECallbacks,
  signal?: AbortSignal,
  taskId?: string | null,
  edition?: string,
): Promise<void> {
  const payload: Record<string, unknown> = {
    message,
    session_id: sessionId,
    edition: edition || 'bedrock',
  }
  if (taskId) {
    payload.task_id = taskId
  }

  const { getDeviceFingerprint } = await import('@/utils/fingerprint')
  const fp = await getDeviceFingerprint()

  const response = await fetch('/api/chat', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      'X-Device-Fp': fp,
    },
    credentials: 'same-origin',
    body: JSON.stringify(payload),
    signal,
  })

  if (!response.ok) {
    const errorText = await response.text().catch(() => 'Unknown error')
    callbacks.onError(`HTTP ${response.status}: ${errorText}`)
    return
  }

  const body = response.body
  if (!body) {
    callbacks.onError('Response body is null')
    return
  }

  const reader = body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      buffer = parseSSELines(buffer, callbacks)
    }

    if (buffer.trim()) {
      parseSSELines(buffer + '\r\n\r\n', callbacks)
    }
  } finally {
    reader.releaseLock()
  }
}

// --- Session API ---

export async function listSessions(limit = 50): Promise<SessionSummary[]> {
  const { getDeviceFingerprint } = await import('@/utils/fingerprint')
  const fp = await getDeviceFingerprint()
  const res = await fetch(`/api/chat/history?limit=${limit}`, {
    headers: { 'X-Device-Fp': fp },
    credentials: 'same-origin',
  })
  if (!res.ok) throw new Error(`Failed to list sessions: ${res.status}`)
  const data = await res.json()
  return data.sessions
}

export async function getSession(sessionId: string): Promise<{
  session: SessionSummary
  messages: SessionMessage[]
}> {
  const { getDeviceFingerprint } = await import('@/utils/fingerprint')
  const fp = await getDeviceFingerprint()
  const res = await fetch(`/api/chat/${sessionId}`, {
    headers: { 'X-Device-Fp': fp },
    credentials: 'same-origin',
  })
  if (!res.ok) throw new Error(`Failed to get session: ${res.status}`)
  return res.json()
}

export async function deleteSession(sessionId: string): Promise<void> {
  const { getDeviceFingerprint } = await import('@/utils/fingerprint')
  const fp = await getDeviceFingerprint()
  const res = await fetch(`/api/chat/${sessionId}`, {
    method: 'DELETE',
    headers: { 'X-Device-Fp': fp },
    credentials: 'same-origin',
  })
  if (!res.ok) throw new Error(`Failed to delete session: ${res.status}`)
}

// --- Export API ---

export async function exportMcfunction(
  project?: Record<string, unknown>,
  command?: string,
  explanation?: string,
  filename = 'output',
): Promise<Blob> {
  const res = await fetch('/api/export/mcfunction', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project, command, explanation, filename }),
  })
  if (!res.ok) throw new Error(`Export failed: ${res.status}`)
  return res.blob()
}

export async function exportMcstructure(
  project: Record<string, unknown>,
  filename = 'output',
): Promise<Blob> {
  const res = await fetch('/api/export/mcstructure', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project, filename }),
  })
  if (!res.ok) throw new Error(`Export failed: ${res.status}`)
  return res.blob()
}
