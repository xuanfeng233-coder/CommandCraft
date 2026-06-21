import { getProvider } from './providers'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ChatMessage {
  role: 'system' | 'user' | 'assistant' | 'tool'
  content: string | null
  thinking?: string | null
  tool_calls?: ToolCall[]
  tool_call_id?: string
  name?: string
}

export interface ToolCall {
  id: string
  type: 'function'
  function: {
    name: string
    arguments: Record<string, any>
  }
}

export interface ToolDefinition {
  type: 'function'
  function: {
    name: string
    description: string
    parameters: Record<string, any>
  }
}

export interface ChatResponse {
  message: {
    role: string
    content: string | null
    thinking: string | null
  }
}

export interface ToolResponse {
  message: {
    role: string
    content: string | null
    thinking: string | null
    tool_calls: ToolCall[] | null
  }
}

export type StreamChunk =
  | { thinking: string }
  | { content: string }
  | { done: 'true' }

export interface HealthStatus {
  apiOk: boolean
  modelOk: boolean
}

interface LLMConfig {
  apiKey: string
  baseUrl: string
  model: string
  providerId: string
  thinkingField: string
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Extract thinking content from `<think>...</think>` tags and return
 * the cleaned content plus extracted thinking.
 */
function extractThinkTags(text: string): { content: string; thinking: string } {
  const regex = /<think>([\s\S]*?)<\/think>/g
  const thinkParts: string[] = []
  const cleaned = text.replace(regex, (_match, inner) => {
    thinkParts.push(inner.trim())
    return ''
  })
  return {
    content: cleaned.trim(),
    thinking: thinkParts.join('\n'),
  }
}

/**
 * Prepare messages for the API: serialise tool_call arguments to JSON strings
 * and ensure tool messages carry a tool_call_id.
 */
function prepMessages(messages: ChatMessage[]): Record<string, any>[] {
  return messages.map((msg) => {
    const out: Record<string, any> = {
      role: msg.role,
      content: msg.content,
    }

    if (msg.role === 'tool') {
      if (msg.tool_call_id) out.tool_call_id = msg.tool_call_id
      if (msg.name) out.name = msg.name
    }

    if (msg.tool_calls && msg.tool_calls.length > 0) {
      out.tool_calls = msg.tool_calls.map((tc) => ({
        id: tc.id,
        type: tc.type,
        function: {
          name: tc.function.name,
          arguments:
            typeof tc.function.arguments === 'string'
              ? tc.function.arguments
              : JSON.stringify(tc.function.arguments),
        },
      }))
    }

    return out
  })
}

// ---------------------------------------------------------------------------
// LLMClient
// ---------------------------------------------------------------------------

export class LLMClient {
  private config: LLMConfig = {
    apiKey: '',
    baseUrl: '',
    model: '',
    providerId: '',
    thinkingField: '',
  }

  private defaultTemperature = 0.6

  // ── Configuration ──────────────────────────────────────────────────────

  configure(opts: {
    apiKey: string
    baseUrl: string
    model: string
    providerId?: string
    thinkingField?: string
  }): void {
    this.config.apiKey = opts.apiKey
    this.config.baseUrl = opts.baseUrl.replace(/\/+$/, '')
    this.config.model = opts.model
    this.config.providerId = opts.providerId ?? ''

    if (opts.thinkingField !== undefined) {
      this.config.thinkingField = opts.thinkingField
    } else if (opts.providerId) {
      const provider = getProvider(opts.providerId)
      this.config.thinkingField = provider?.thinking_field ?? ''
    }
  }

  get isConfigured(): boolean {
    return !!(this.config.apiKey && this.config.baseUrl && this.config.model)
  }

  // ── Private fetch wrapper ──────────────────────────────────────────────

  private get endpoint(): string {
    return `${this.config.baseUrl}/chat/completions`
  }

  private buildHeaders(): Record<string, string> {
    return {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${this.config.apiKey}`,
    }
  }

  private async request(
    body: Record<string, any>,
    stream: false,
  ): Promise<any>
  private async request(
    body: Record<string, any>,
    stream: true,
  ): Promise<ReadableStream<Uint8Array>>
  private async request(
    body: Record<string, any>,
    stream: boolean,
  ): Promise<any | ReadableStream<Uint8Array>> {
    const response = await fetch(this.endpoint, {
      method: 'POST',
      headers: this.buildHeaders(),
      body: JSON.stringify(body),
    })

    if (!response.ok) {
      let detail = ''
      try {
        const errJson = await response.json()
        detail = errJson.error?.message ?? JSON.stringify(errJson)
      } catch {
        detail = await response.text().catch(() => '')
      }
      throw new Error(
        `LLM API 错误 (${response.status}): ${detail || response.statusText}`,
      )
    }

    if (stream) {
      if (!response.body) throw new Error('响应流不可用')
      return response.body
    }
    return response.json()
  }

  // ── Thinking extraction helper ─────────────────────────────────────────

  private extractThinking(choice: any): { content: string | null; thinking: string | null } {
    const msg = choice.message ?? choice.delta ?? {}
    let content: string | null = msg.content ?? null
    let thinking: string | null = null

    // 1) Check provider-specific thinking field (e.g. reasoning_content)
    if (this.config.thinkingField && msg[this.config.thinkingField]) {
      thinking = msg[this.config.thinkingField]
    }

    // 2) Fallback: parse <think>...</think> from content
    if (!thinking && content) {
      const extracted = extractThinkTags(content)
      if (extracted.thinking) {
        thinking = extracted.thinking
        content = extracted.content || null
      }
    }

    return { content, thinking }
  }

  // ── chat() — non-streaming ─────────────────────────────────────────────

  async chat(
    messages: ChatMessage[],
    opts?: { temperature?: number },
  ): Promise<ChatResponse> {
    const body: Record<string, any> = {
      model: this.config.model,
      messages: prepMessages(messages),
      temperature: opts?.temperature ?? this.defaultTemperature,
      stream: false,
    }

    const data = await this.request(body, false)
    const choice = data.choices?.[0]
    if (!choice) throw new Error('LLM 返回空响应')

    const { content, thinking } = this.extractThinking(choice)

    return {
      message: {
        role: choice.message.role,
        content,
        thinking,
      },
    }
  }

  // ── chatStream() — SSE streaming ───────────────────────────────────────

  async *chatStream(
    messages: ChatMessage[],
    opts?: { temperature?: number },
  ): AsyncGenerator<StreamChunk> {
    const body: Record<string, any> = {
      model: this.config.model,
      messages: prepMessages(messages),
      temperature: opts?.temperature ?? this.defaultTemperature,
      stream: true,
    }

    const stream = await this.request(body, true)
    const reader = stream.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    // Track whether we're inside a <think> block while streaming
    let inThinkTag = false
    let thinkBuffer = ''

    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        // Keep the last (potentially incomplete) line in the buffer
        buffer = lines.pop() ?? ''

        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed || !trimmed.startsWith('data:')) continue

          const payload = trimmed.slice(5).trim()
          if (payload === '[DONE]') {
            yield { done: 'true' }
            return
          }

          let parsed: any
          try {
            parsed = JSON.parse(payload)
          } catch {
            continue
          }

          const delta = parsed.choices?.[0]?.delta
          if (!delta) continue

          // Provider-specific thinking field (e.g. reasoning_content)
          if (this.config.thinkingField && delta[this.config.thinkingField]) {
            yield { thinking: delta[this.config.thinkingField] }
          }

          if (delta.content) {
            // Handle <think> tags that may appear mid-stream
            let text = delta.content as string

            while (text.length > 0) {
              if (inThinkTag) {
                const closeIdx = text.indexOf('</think>')
                if (closeIdx === -1) {
                  thinkBuffer += text
                  text = ''
                } else {
                  thinkBuffer += text.slice(0, closeIdx)
                  if (thinkBuffer) yield { thinking: thinkBuffer }
                  thinkBuffer = ''
                  inThinkTag = false
                  text = text.slice(closeIdx + 8) // skip </think>
                }
              } else {
                const openIdx = text.indexOf('<think>')
                if (openIdx === -1) {
                  yield { content: text }
                  text = ''
                } else {
                  if (openIdx > 0) yield { content: text.slice(0, openIdx) }
                  inThinkTag = true
                  text = text.slice(openIdx + 7) // skip <think>
                }
              }
            }
          }
        }
      }

      // Flush remaining think buffer
      if (thinkBuffer) yield { thinking: thinkBuffer }
    } finally {
      reader.releaseLock()
    }

    yield { done: 'true' }
  }

  // ── chatWithTools() — tool calling ─────────────────────────────────────

  async chatWithTools(
    messages: ChatMessage[],
    tools: ToolDefinition[],
    opts?: { temperature?: number },
  ): Promise<ToolResponse> {
    const body: Record<string, any> = {
      model: this.config.model,
      messages: prepMessages(messages),
      temperature: opts?.temperature ?? this.defaultTemperature,
      stream: false,
    }

    if (tools.length > 0) {
      body.tools = tools
      body.tool_choice = 'auto'
    }

    const data = await this.request(body, false)
    const choice = data.choices?.[0]
    if (!choice) throw new Error('LLM 返回空响应')

    const { content, thinking } = this.extractThinking(choice)

    let toolCalls: ToolCall[] | null = null
    if (choice.message.tool_calls && choice.message.tool_calls.length > 0) {
      toolCalls = choice.message.tool_calls.map((tc: any) => {
        let args: Record<string, any> = {}
        if (tc.function.arguments) {
          try {
            args =
              typeof tc.function.arguments === 'string'
                ? JSON.parse(tc.function.arguments)
                : tc.function.arguments
          } catch {
            args = { _raw: tc.function.arguments }
          }
        }
        return {
          id: tc.id,
          type: 'function' as const,
          function: {
            name: tc.function.name,
            arguments: args,
          },
        }
      })
    }

    return {
      message: {
        role: choice.message.role,
        content,
        thinking,
        tool_calls: toolCalls,
      },
    }
  }

  // ── checkHealth() ──────────────────────────────────────────────────────

  async checkHealth(): Promise<HealthStatus> {
    const status: HealthStatus = { apiOk: false, modelOk: false }

    if (!this.isConfigured) return status

    try {
      // Minimal request to verify API key and model
      const body = {
        model: this.config.model,
        messages: [{ role: 'user', content: 'hi' }],
        max_tokens: 1,
        stream: false,
      }

      const response = await fetch(this.endpoint, {
        method: 'POST',
        headers: this.buildHeaders(),
        body: JSON.stringify(body),
      })

      status.apiOk = response.status !== 401 && response.status !== 403
      status.modelOk = response.ok

      return status
    } catch {
      return status
    }
  }
}

export const llmClient = new LLMClient()
