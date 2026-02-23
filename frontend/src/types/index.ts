export interface CommandValidation {
  valid: boolean
  error_count: number
}

export interface CommandParamDef {
  name: string
  type: string
  required: boolean
  description: string
  default?: string
  range?: string
  options?: QuestionOption[]
}

export interface CommandTemplate {
  command_name: string
  params: Record<string, string>
  param_defs: CommandParamDef[]
}

export interface CommandOutput {
  command: string
  explanation: string
  variants: string[]
  warnings: string[]
  validation?: CommandValidation
  template?: CommandTemplate
}

export interface QuestionOption {
  value: string
  label: string
}

export interface ParameterQuestion {
  param: string
  question: string
  options: QuestionOption[]
  default: string | null
}

// --- Project Mode Types ---

export interface CommandBlockEntry {
  type: 'impulse' | 'chain' | 'repeating'
  conditional: boolean
  needs_redstone: boolean
  command: string
  comment: string
}

export interface ProjectTask {
  task_id: string
  description: string
  commands: string[]
  command_blocks: CommandBlockEntry[]
  dependencies: string[]
}

export interface ProjectPhase {
  phase_name: string
  description: string
  tasks: ProjectTask[]
}

export interface BlockPosition {
  x: number
  y: number
  z: number
}

export interface BlockLayoutEntry {
  position: BlockPosition
  direction: string
  block_type: string
  conditional: boolean
  auto: boolean
  command: string
  custom_name: string
  group_id: string
}

export interface BlockGroup {
  group_id: string
  name: string
  description: string
  trigger_method: string
}

export interface BlockDimensions {
  width: number
  height: number
  depth: number
}

export interface ProjectResult {
  project_name: string
  overview: string
  phases: ProjectPhase[]
  layout: BlockLayoutEntry[]
  groups: BlockGroup[]
  dimensions: BlockDimensions
}

// --- Task Types ---

export type TaskStatus = 'pending' | 'retrieving' | 'generating' | 'validating' | 'paused' | 'completed' | 'failed' | 'blocked'

export interface TaskItem {
  task_id: string
  description: string
  status: TaskStatus
  depends_on?: string[]
  result?: {
    type: string
    command?: CommandOutput
    questions?: ParameterQuestion[]
    current_progress?: string
  }
  error?: string
}

// Backward compat aliases
export type SubTaskStatus = TaskStatus
export type SubTaskItem = TaskItem

// --- Chat Types ---

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  type?: 'single_command' | 'conversation' | 'project' | 'error'
  command?: CommandOutput
  questions?: ParameterQuestion[]
  project?: ProjectResult
  template?: CommandTemplate
  thinking?: string
  step?: string
  steps?: string[]
  answered?: boolean
  subTasks?: TaskItem[]
  taskListMeta?: { project_name: string; overview: string }
  timestamp: number
}

export interface SSEData {
  event: 'thinking' | 'content' | 'done' | 'error' | 'task_list' | 'task_update' | 'task_thinking' | 'summary' | 'subtask_list' | 'subtask_update'
  data: Record<string, unknown>
}

// --- LLM Settings Types ---

export interface ProviderInfo {
  id: string
  name: string
  base_url: string
  default_model: string
  models: string[]
  supports_thinking: boolean
  free_tier: boolean
  requires_endpoint_id: boolean
}

export interface LLMSettings {
  provider_id: string
  api_key: string
  base_url: string
  model: string
  temperature: number
  subscription_mode?: boolean
  setup_skipped?: boolean
}

// --- Session Types ---

export interface SessionSummary {
  id: string
  title: string
  created_at: string
  updated_at: string
}

export interface SessionMessage {
  id: number
  session_id: string
  role: 'user' | 'assistant'
  content: string
  msg_type: string | null
  command: CommandOutput | null
  questions: ParameterQuestion[] | null
  thinking: string | null
  created_at: string
}
