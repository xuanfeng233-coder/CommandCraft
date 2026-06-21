import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import {
  startBuild as apiStartBuild,
  clarifyBuild as apiClarifyBuild,
  confirmBuild as apiConfirmBuild,
  updatePlan as apiUpdatePlan,
  type BuildSSECallbacks,
} from '@/api/build'
import { useEditorStore } from '@/stores/editor'
import { useSubscriptionStore } from '@/stores/subscription'
import type { TaskItem } from '@/types'

export type BuildPhase = 'idle' | 'planning' | 'clarifying' | 'reviewing' | 'executing' | 'completed' | 'error'

export interface ClarifyQuestion {
  key: string
  question: string
}

export interface StepStatus {
  index: number
  status: string
  error?: string
  resultSummary?: string
}

export const useBuildStore = defineStore('build', () => {
  const phase = ref<BuildPhase>('idle')
  const projectId = ref<string | null>(null)
  const isLoading = ref(false)
  const thinking = ref('')
  const errorMessage = ref('')

  // Clarify phase
  const clarifySummary = ref('')
  const clarifyQuestions = ref<ClarifyQuestion[]>([])
  const suggestedSteps = ref<string[]>([])

  // Plan/Review phase
  const planContent = ref('')

  // Execution phase
  const steps = ref<StepStatus[]>([])
  const tasks = ref<TaskItem[]>([])
  const currentStepIndex = ref(0)
  const completedCommands = ref<string[]>([])

  // Search activity
  const searchActivities = ref<{ query: string; status: string; count?: number }[]>([])

  let abortController: AbortController | null = null

  const subStore = useSubscriptionStore()

  const canBuild = computed(() => {
    const s = subStore.status
    if (!s) return false
    return s.build_limit > 0
  })

  const buildUsageText = computed(() => {
    const s = subStore.status
    if (!s) return ''
    return `${s.build_usage ?? 0}/${s.build_limit ?? 0}`
  })

  function reset() {
    phase.value = 'idle'
    projectId.value = null
    isLoading.value = false
    thinking.value = ''
    errorMessage.value = ''
    clarifySummary.value = ''
    clarifyQuestions.value = []
    suggestedSteps.value = []
    planContent.value = ''
    steps.value = []
    tasks.value = []
    currentStepIndex.value = 0
    completedCommands.value = []
    searchActivities.value = []
    if (abortController) {
      abortController.abort()
      abortController = null
    }
  }

  function _makeCallbacks(): BuildSSECallbacks {
    return {
      onPhase(data) {
        const p = data.phase as BuildPhase
        phase.value = p
        if (data.project_id) projectId.value = data.project_id

        if (p === 'completed' && data.commands) {
          completedCommands.value = data.commands as string[]
          const editor = useEditorStore()
          for (const cmd of data.commands as string[]) {
            editor.insertCommand(cmd)
          }
        }
      },

      onClarify(data) {
        phase.value = 'clarifying'
        projectId.value = data.project_id
        clarifySummary.value = data.summary
        clarifyQuestions.value = data.questions
        suggestedSteps.value = data.suggested_steps
      },

      onPlan(data) {
        planContent.value = data.markdown_content
        phase.value = 'reviewing'
      },

      onStepUpdate(data) {
        currentStepIndex.value = data.step_index
        const existing = steps.value.find((s) => s.index === data.step_index)
        if (existing) {
          existing.status = data.status
          existing.error = data.error
          existing.resultSummary = data.result_summary
        } else {
          steps.value.push({
            index: data.step_index,
            status: data.status,
            error: data.error,
            resultSummary: data.result_summary,
          })
        }
      },

      onThinking(text) {
        thinking.value += text
      },

      onTaskList(data) {
        if (data) {
          tasks.value = (data.tasks || []).map((t: TaskItem) => ({
            task_id: t.task_id,
            description: t.description,
            depends_on: t.depends_on || [],
            status: t.status || 'pending',
          }))
        }
      },

      onTaskUpdate(data) {
        if (data) {
          const task = tasks.value.find((t) => t.task_id === data.task_id)
          if (task) {
            task.status = data.status as TaskItem['status']
            if (data.error) task.error = data.error as string
          }
        }
      },

      onSearchActivity(data) {
        if (data) {
          const existing = searchActivities.value.find((a) => a.query === data.query)
          if (existing) {
            existing.status = data.status
            existing.count = data.results_count
          } else {
            searchActivities.value.push({
              query: data.query,
              status: data.status,
              count: data.results_count,
            })
          }
        }
      },

      onDone() {
        isLoading.value = false
      },

      onError(err) {
        errorMessage.value = err
        isLoading.value = false
        if (phase.value === 'idle' || phase.value === 'planning') {
          phase.value = 'error'
        }
      },
    }
  }

  async function start(message: string) {
    reset()
    isLoading.value = true
    phase.value = 'planning'
    abortController = new AbortController()

    try {
      await apiStartBuild(message, null, _makeCallbacks(), abortController.signal)
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return
      errorMessage.value = err instanceof Error ? err.message : 'Unknown error'
      phase.value = 'error'
    } finally {
      isLoading.value = false
      abortController = null
    }
  }

  async function submitClarify(answers: Record<string, string>) {
    if (!projectId.value) return
    isLoading.value = true
    thinking.value = ''
    abortController = new AbortController()

    try {
      await apiClarifyBuild(projectId.value, answers, _makeCallbacks(), abortController.signal)
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return
      errorMessage.value = err instanceof Error ? err.message : 'Unknown error'
    } finally {
      isLoading.value = false
      abortController = null
    }
  }

  async function confirmPlan(editedPlan?: string) {
    if (!projectId.value) return
    isLoading.value = true
    thinking.value = ''
    tasks.value = []
    steps.value = []
    abortController = new AbortController()

    try {
      await apiConfirmBuild(
        projectId.value,
        editedPlan ?? planContent.value,
        _makeCallbacks(),
        abortController.signal,
      )
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return
      errorMessage.value = err instanceof Error ? err.message : 'Unknown error'
    } finally {
      isLoading.value = false
      abortController = null
    }
  }

  async function savePlan(content: string) {
    if (!projectId.value) return
    planContent.value = content
    await apiUpdatePlan(projectId.value, content)
  }

  function cancel() {
    if (abortController) {
      abortController.abort()
      abortController = null
    }
    isLoading.value = false
  }

  return {
    phase,
    projectId,
    isLoading,
    thinking,
    errorMessage,
    clarifySummary,
    clarifyQuestions,
    suggestedSteps,
    planContent,
    steps,
    tasks,
    currentStepIndex,
    completedCommands,
    searchActivities,
    canBuild,
    buildUsageText,
    reset,
    start,
    submitClarify,
    confirmPlan,
    savePlan,
    cancel,
  }
})
