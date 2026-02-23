import type { SessionSummary, SessionMessage, TaskItem } from '@/types'
import { getDeviceFingerprint } from '@/utils/fingerprint'

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

/**
 * Parse SSE lines from a text chunk.
 * sse_starlette uses \r\n line endings:
 *   event: <event_name>\r\n
 *   data: <json_string>\r\n
 *   \r\n   (blank line = event boundary)
 */
function parseSSELines(
  buffer: string,
  callbacks: SSECallbacks
): string {
  // Normalise \r\n → \n so we can split uniformly
  const normalised = buffer.replace(/\r\n/g, '\n')

  // Split on double newlines (SSE event boundary)
  const parts = normalised.split('\n\n')
  // Last part may be incomplete, keep it as remaining buffer
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
        // Backward compat
        callbacks.onSubTaskList?.((parsed.tasks as TaskItem[]) ?? [])
        break
      case 'task_update':
        callbacks.onTaskUpdate?.(parsed as { task_id: string; status: string; result?: Record<string, unknown>; error?: string })
        // Backward compat
        callbacks.onSubTaskUpdate?.(parsed as { task_id: string; status: string; result?: Record<string, unknown>; error?: string })
        break
      case 'task_thinking':
        callbacks.onTaskThinking?.(parsed as { task_id: string; text: string })
        break
      case 'summary':
        // Summary is emitted as content for rendering
        callbacks.onContent(parsed)
        break
      // Legacy events (backward compat)
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

/**
 * Send a chat message via POST and handle SSE stream response.
 * Uses fetch + ReadableStream to support POST-based SSE.
 */
export async function sendMessage(
  message: string,
  sessionId: string | null,
  callbacks: SSECallbacks,
  signal?: AbortSignal,
  taskId?: string | null,
): Promise<void> {
  const payload: Record<string, unknown> = {
    message,
    session_id: sessionId,
  }
  if (taskId) {
    payload.task_id = taskId
  }

  const fp = await getDeviceFingerprint()

  const response = await fetch('/api/chat', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      'X-Device-Fp': fp,
    },
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

    // Process any remaining data in the buffer
    if (buffer.trim()) {
      parseSSELines(buffer + '\r\n\r\n', callbacks)
    }
  } finally {
    reader.releaseLock()
  }
}

// --- Session API ---

export async function listSessions(limit = 50): Promise<SessionSummary[]> {
  const res = await fetch(`/api/chat/history?limit=${limit}`)
  if (!res.ok) throw new Error(`Failed to list sessions: ${res.status}`)
  const data = await res.json()
  return data.sessions
}

export async function getSession(sessionId: string): Promise<{
  session: SessionSummary
  messages: SessionMessage[]
}> {
  const res = await fetch(`/api/chat/${sessionId}`)
  if (!res.ok) throw new Error(`Failed to get session: ${res.status}`)
  return res.json()
}

export async function deleteSession(sessionId: string): Promise<void> {
  const res = await fetch(`/api/chat/${sessionId}`, { method: 'DELETE' })
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
