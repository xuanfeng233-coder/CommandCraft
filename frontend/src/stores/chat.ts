import { ref } from 'vue'
import { defineStore } from 'pinia'
import { sendMessage as sendSSEMessage, listSessions, getSession, deleteSession } from '@/api/chat'
import { useEditorStore } from '@/stores/editor'
import type { ChatMessage, CommandOutput, CommandTemplate, ParameterQuestion, ProjectResult, SessionSummary, TaskItem } from '@/types'

function generateId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2)
}

const SESSION_KEY = 'mcbe-ai-session-id'

export const useChatStore = defineStore('chat', () => {
  const messages = ref<ChatMessage[]>([])
  const sessionId = ref<string | null>(
    localStorage.getItem(SESSION_KEY)
  )
  const isLoading = ref(false)
  const currentThinking = ref('')
  const currentStep = ref('')

  let abortController: AbortController | null = null

  function addUserMessage(text: string): ChatMessage {
    const msg: ChatMessage = {
      id: generateId(),
      role: 'user',
      content: text,
      timestamp: Date.now(),
    }
    messages.value.push(msg)
    return msg
  }

  function createAssistantPlaceholder(): ChatMessage {
    const msg: ChatMessage = {
      id: generateId(),
      role: 'assistant',
      content: '',
      timestamp: Date.now(),
    }
    messages.value.push(msg)
    return msg
  }

  function updateLastAssistant(updater: (msg: ChatMessage) => void) {
    for (let i = messages.value.length - 1; i >= 0; i--) {
      if (messages.value[i].role === 'assistant') {
        updater(messages.value[i])
        return
      }
    }
  }

  async function sendMessage(text: string, taskId?: string | null) {
    if (isLoading.value) return
    if (!text.trim()) return

    isLoading.value = true
    currentThinking.value = ''
    currentStep.value = ''

    addUserMessage(text)
    createAssistantPlaceholder()

    abortController = new AbortController()

    try {
      await sendSSEMessage(
        text,
        sessionId.value,
        {
          onThinking(thinkingText: string) {
            currentThinking.value += thinkingText
            // Extract step messages (lines starting with "正在")
            const lines = thinkingText.split('\n')
            for (const line of lines) {
              const trimmed = line.trim()
              if (trimmed.startsWith('正在')) {
                currentStep.value = trimmed
              }
            }
            updateLastAssistant((msg) => {
              msg.thinking = currentThinking.value
              if (currentStep.value) {
                msg.step = currentStep.value
                if (!msg.steps) msg.steps = []
                if (msg.steps[msg.steps.length - 1] !== currentStep.value) {
                  msg.steps.push(currentStep.value)
                }
              }
            })
          },

          onTaskList(data: { project_name: string; overview: string; tasks: TaskItem[] }) {
            updateLastAssistant((msg) => {
              msg.taskListMeta = {
                project_name: data.project_name,
                overview: data.overview,
              }
              msg.subTasks = data.tasks.map((t) => ({
                task_id: t.task_id,
                description: t.description,
                depends_on: t.depends_on || [],
                status: (t.status || (t.depends_on && t.depends_on.length > 0 ? 'blocked' : 'pending')) as TaskItem['status'],
              }))
            })
          },

          onTaskUpdate(data: { task_id: string; status: string; result?: Record<string, unknown>; error?: string }) {
            updateLastAssistant((msg) => {
              if (!msg.subTasks) return
              const task = msg.subTasks.find((t) => t.task_id === data.task_id)
              if (!task) return

              task.status = data.status as TaskItem['status']

              if (data.status === 'failed') {
                task.error = data.error || '生成失败'
              }

              if (data.result) {
                const result = data.result
                const resultType = result.type as string

                if (resultType === 'single_command' || resultType === 'execute_chain' || resultType === 'selector' || resultType === 'rawtext') {
                  task.result = {
                    type: 'single_command',
                    command: result.command as CommandOutput,
                  }
                  // Don't auto-insert here — wait for final summary to insert all at once
                } else if (resultType === 'conversation') {
                  task.result = {
                    type: 'conversation',
                    questions: result.questions as ParameterQuestion[],
                    current_progress: result.current_progress as string | undefined,
                  }
                } else if (resultType === 'project') {
                  // Don't auto-insert here — wait for final summary to insert all at once
                  task.result = { type: 'project' }
                }
              }
            })
          },

          onTaskThinking(data: { task_id: string; text: string }) {
            // Append to thinking for now
            currentThinking.value += data.text
            updateLastAssistant((msg) => {
              msg.thinking = currentThinking.value
            })
          },

          // Backward compat — these are now handled by onTaskList/onTaskUpdate
          onSubTaskList(tasks: TaskItem[]) {
            updateLastAssistant((msg) => {
              if (!msg.subTasks) {
                msg.subTasks = tasks.map((t) => ({
                  task_id: t.task_id,
                  description: t.description,
                  status: 'pending' as const,
                }))
              }
            })
          },

          onSubTaskUpdate(_data: { task_id: string; status: string; result?: Record<string, unknown>; error?: string }) {
            // Handled by onTaskUpdate — backward compat only
          },

          onContent(data: Record<string, unknown>) {
            updateLastAssistant((msg) => {
              let msgType = data.type as string | undefined
              // Normalize non-standard types to single_command
              if (msgType === 'execute_chain' || msgType === 'selector' || msgType === 'rawtext') {
                msgType = 'single_command'
              }
              if (data.thinking) {
                msg.thinking = data.thinking as string
              }

              // If subTasks are present, this is a decomposed project summary.
              // Insert all commands into editor now (not per sub-task).
              if (msg.subTasks && msg.subTasks.length > 0 && msgType === 'project') {
                msg.type = 'project'
                msg.project = data.project as ProjectResult
                msg.content = (data.message as string) ?? ''
                if (msg.project?.phases) {
                  const editor = useEditorStore()
                  for (const phase of msg.project.phases) {
                    for (const task of phase.tasks) {
                      for (const block of task.command_blocks) {
                        if (block.command) {
                          editor.insertCommand(block.command)
                        }
                      }
                    }
                  }
                }
                return
              }

              if (msgType === 'single_command') {
                msg.type = 'single_command'
                msg.command = data.command as CommandOutput
                msg.content = (data.message as string) ?? ''
                // Auto-insert generated command into editor
                if (msg.command?.command) {
                  const editor = useEditorStore()
                  editor.insertCommand(msg.command.command)
                }
              } else if (msgType === 'conversation') {
                msg.type = 'conversation'
                msg.questions = data.questions as ParameterQuestion[]
                msg.content = (data.message as string) ?? ''
                // Store template metadata from template fast path
                if (data.template) {
                  msg.template = data.template as CommandTemplate
                }
              } else if (msgType === 'project') {
                msg.type = 'project'
                msg.project = data.project as ProjectResult
                msg.content = (data.message as string) ?? ''
                // Auto-insert all project commands into editor
                if (msg.project?.phases) {
                  const editor = useEditorStore()
                  for (const phase of msg.project.phases) {
                    for (const task of phase.tasks) {
                      for (const block of task.command_blocks) {
                        if (block.command) {
                          editor.insertCommand(block.command)
                        }
                      }
                    }
                  }
                }
              } else {
                // Fallback: treat as plain text content
                msg.content += (data.message as string) ?? ''
              }
            })
          },

          onDone(data: Record<string, unknown>) {
            if (data.session_id) {
              sessionId.value = data.session_id as string
              localStorage.setItem(SESSION_KEY, sessionId.value)
            }
          },

          onError(err: string) {
            updateLastAssistant((msg) => {
              msg.type = 'error'
              msg.content = err
            })
          },
        },
        abortController.signal,
        taskId,
      )
    } catch (err: unknown) {
      // Handle abort or network errors
      if (err instanceof DOMException && err.name === 'AbortError') {
        // User cancelled, no action needed
      } else {
        const errorMessage =
          err instanceof Error ? err.message : 'Unknown error'
        updateLastAssistant((msg) => {
          msg.type = 'error'
          msg.content = `Request failed: ${errorMessage}`
        })
      }
    } finally {
      isLoading.value = false
      currentThinking.value = ''
      currentStep.value = ''
      abortController = null
    }
  }

  function clearChat() {
    messages.value = []
    sessionId.value = null
    localStorage.removeItem(SESSION_KEY)
    isLoading.value = false
    currentThinking.value = ''
    if (abortController) {
      abortController.abort()
      abortController = null
    }
  }

  // --- Session management ---

  const sessions = ref<SessionSummary[]>([])
  const sessionsLoading = ref(false)

  async function fetchSessions() {
    sessionsLoading.value = true
    try {
      sessions.value = await listSessions()
    } catch {
      sessions.value = []
    } finally {
      sessionsLoading.value = false
    }
  }

  async function loadSession(id: string) {
    if (isLoading.value) return
    try {
      const data = await getSession(id)
      // Convert DB messages to ChatMessage format
      messages.value = data.messages.map((m) => ({
        id: String(m.id),
        role: m.role,
        content: m.content,
        type: (m.msg_type as ChatMessage['type']) || undefined,
        command: m.command || undefined,
        questions: m.questions || undefined,
        thinking: m.thinking || undefined,
        timestamp: new Date(m.created_at).getTime(),
      }))
      sessionId.value = id
      localStorage.setItem(SESSION_KEY, id)
    } catch {
      // If session not found, start fresh
      clearChat()
    }
  }

  async function removeSession(id: string) {
    try {
      await deleteSession(id)
      sessions.value = sessions.value.filter((s) => s.id !== id)
      if (sessionId.value === id) {
        clearChat()
      }
    } catch {
      // ignore
    }
  }

  return {
    messages,
    sessionId,
    isLoading,
    currentThinking,
    currentStep,
    sessions,
    sessionsLoading,
    sendMessage,
    clearChat,
    fetchSessions,
    loadSession,
    removeSession,
  }
})
