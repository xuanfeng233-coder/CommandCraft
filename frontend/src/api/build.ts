import { getDeviceFingerprint } from '@/utils/fingerprint'
import { getApiBase } from '@/utils/api-base'

export interface BuildSSECallbacks {
  onPhase: (data: { phase: string; project_id: string; plan_content?: string; commands?: string[] }) => void
  onClarify: (data: { project_id: string; summary: string; questions: { question: string; key: string }[]; suggested_steps: string[] }) => void
  onPlan: (data: { markdown_content: string }) => void
  onStepUpdate: (data: { step_index: number; status: string; error?: string; result_summary?: string; retry?: number }) => void
  onThinking: (text: string) => void
  onTaskList?: (data: any) => void
  onTaskUpdate?: (data: any) => void
  onSearchActivity?: (data: { query: string; status: string; results_count?: number }) => void
  onDone: (data: { project_id: string }) => void
  onError: (err: string) => void
}

/**
 * Parse SSE lines from a text chunk.
 * sse_starlette uses \r\n line endings:
 *   event: <event_name>\r\n
 *   data: <json_string>\r\n
 *   \r\n   (blank line = event boundary)
 */
function parseBuildSSELines(
  buffer: string,
  callbacks: BuildSSECallbacks,
): string {
  // Normalise \r\n -> \n so we can split uniformly
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
      case 'build_phase':
        callbacks.onPhase(parsed as any)
        break
      case 'build_clarify':
        callbacks.onClarify(parsed as any)
        break
      case 'build_plan':
        callbacks.onPlan(parsed as any)
        break
      case 'build_step_update':
        callbacks.onStepUpdate(parsed as any)
        break
      case 'thinking':
        callbacks.onThinking((parsed.text as string) ?? '')
        break
      case 'task_list':
        callbacks.onTaskList?.(parsed)
        break
      case 'task_update':
        callbacks.onTaskUpdate?.(parsed)
        break
      case 'search_activity':
        callbacks.onSearchActivity?.(parsed as any)
        break
      case 'done':
        callbacks.onDone(parsed as any)
        break
      case 'error':
        callbacks.onError((parsed.message as string) ?? 'Unknown error')
        break
      default:
        break
    }
  }

  return remaining
}

/**
 * Read an SSE stream from a fetch Response and dispatch to callbacks.
 */
async function readSSEStream(
  response: Response,
  callbacks: BuildSSECallbacks,
): Promise<void> {
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
      buffer = parseBuildSSELines(buffer, callbacks)
    }

    // Process any remaining data in the buffer
    if (buffer.trim()) {
      parseBuildSSELines(buffer + '\r\n\r\n', callbacks)
    }
  } finally {
    reader.releaseLock()
  }
}

/**
 * POST an SSE-streaming build endpoint.
 */
async function postBuildSSE(
  url: string,
  payload: Record<string, unknown>,
  callbacks: BuildSSECallbacks,
  signal?: AbortSignal,
): Promise<void> {
  const fp = await getDeviceFingerprint()

  const edition = localStorage.getItem('mc-edition') || 'bedrock'

  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      'X-Device-Fp': fp,
      'X-MC-Edition': edition,
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

  await readSSEStream(response, callbacks)
}

// --- Build SSE endpoints ---

/**
 * Start a new build project. Returns SSE stream.
 */
export async function startBuild(
  message: string,
  sessionId: string | null,
  callbacks: BuildSSECallbacks,
  signal?: AbortSignal,
): Promise<void> {
  const payload: Record<string, unknown> = { message }
  if (sessionId) {
    payload.session_id = sessionId
  }
  await postBuildSSE(`${getApiBase()}/api/build/start`, payload, callbacks, signal)
}

/**
 * Submit clarification answers. Returns SSE stream.
 */
export async function clarifyBuild(
  projectId: string,
  answers: Record<string, string>,
  callbacks: BuildSSECallbacks,
  signal?: AbortSignal,
): Promise<void> {
  await postBuildSSE(`${getApiBase()}/api/build/${projectId}/clarify`, { answers }, callbacks, signal)
}

/**
 * Confirm the plan and start execution. Returns SSE stream.
 */
export async function confirmBuild(
  projectId: string,
  planContent: string | undefined,
  callbacks: BuildSSECallbacks,
  signal?: AbortSignal,
): Promise<void> {
  const payload: Record<string, unknown> = {}
  if (planContent !== undefined) {
    payload.plan_content = planContent
  }
  await postBuildSSE(`${getApiBase()}/api/build/${projectId}/confirm`, payload, callbacks, signal)
}

// --- Build REST endpoints ---

/**
 * Update the plan content for a build project.
 */
export async function updatePlan(
  projectId: string,
  planContent: string | undefined,
): Promise<{ success: boolean }> {
  const fp = await getDeviceFingerprint()
  const payload: Record<string, unknown> = {}
  if (planContent !== undefined) {
    payload.plan_content = planContent
  }
  const res = await fetch(`${getApiBase()}/api/build/${projectId}/plan`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
      'X-Device-Fp': fp,
    },
    credentials: 'same-origin',
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(`Failed to update plan: ${res.status}`)
  return res.json()
}

/**
 * Get a build project's info and plan content.
 */
export async function getBuildProject(projectId: string): Promise<any> {
  const fp = await getDeviceFingerprint()
  const res = await fetch(`${getApiBase()}/api/build/${projectId}`, {
    headers: { 'X-Device-Fp': fp },
    credentials: 'same-origin',
  })
  if (!res.ok) throw new Error(`Failed to get build project: ${res.status}`)
  return res.json()
}

/**
 * List all build projects for the current device.
 */
export async function listBuildProjects(): Promise<{ projects: any[] }> {
  const fp = await getDeviceFingerprint()
  const res = await fetch(`${getApiBase()}/api/build`, {
    headers: { 'X-Device-Fp': fp },
    credentials: 'same-origin',
  })
  if (!res.ok) throw new Error(`Failed to list build projects: ${res.status}`)
  return res.json()
}

/**
 * Delete a build project.
 */
export async function deleteBuildProject(projectId: string): Promise<void> {
  const fp = await getDeviceFingerprint()
  const res = await fetch(`${getApiBase()}/api/build/${projectId}`, {
    method: 'DELETE',
    headers: { 'X-Device-Fp': fp },
    credentials: 'same-origin',
  })
  if (!res.ok) throw new Error(`Failed to delete build project: ${res.status}`)
}
