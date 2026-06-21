export interface ProviderInfo {
  id: string
  name: string
  base_url: string
  default_model: string
  models: string[]
  supports_thinking: boolean
  thinking_field: string
  supports_tools: boolean
  free_tier: boolean
  requires_endpoint_id: boolean
}

export const PROVIDERS: Record<string, ProviderInfo> = {
  deepseek: {
    id: 'deepseek', name: 'DeepSeek', base_url: 'https://api.deepseek.com',
    default_model: 'deepseek-chat', models: ['deepseek-chat', 'deepseek-reasoner'],
    supports_thinking: true, thinking_field: 'reasoning_content', supports_tools: true,
    free_tier: false, requires_endpoint_id: false,
  },
  qwen: {
    id: 'qwen', name: '通义千问', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    default_model: 'qwen-plus', models: ['qwen-turbo', 'qwen-plus', 'qwen-max'],
    supports_thinking: false, thinking_field: '', supports_tools: true,
    free_tier: false, requires_endpoint_id: false,
  },
  glm: {
    id: 'glm', name: '智谱 GLM', base_url: 'https://open.bigmodel.cn/api/paas/v4',
    default_model: 'glm-4-flash', models: ['glm-4-flash', 'glm-4', 'glm-4-plus'],
    supports_thinking: false, thinking_field: '', supports_tools: false,
    free_tier: true, requires_endpoint_id: false,
  },
  kimi: {
    id: 'kimi', name: 'Kimi', base_url: 'https://api.moonshot.cn/v1',
    default_model: 'moonshot-v1-32k', models: ['moonshot-v1-8k', 'moonshot-v1-32k', 'moonshot-v1-128k'],
    supports_thinking: false, thinking_field: '', supports_tools: true,
    free_tier: false, requires_endpoint_id: false,
  },
  doubao: {
    id: 'doubao', name: '豆包', base_url: 'https://ark.cn-beijing.volces.com/api/v3',
    default_model: '', models: [],
    supports_thinking: false, thinking_field: '', supports_tools: true,
    free_tier: false, requires_endpoint_id: true,
  },
  openai: {
    id: 'openai', name: 'ChatGPT', base_url: 'https://api.openai.com/v1',
    default_model: 'gpt-4o-mini', models: ['gpt-4o', 'gpt-4o-mini'],
    supports_thinking: false, thinking_field: '', supports_tools: true,
    free_tier: false, requires_endpoint_id: false,
  },
  gemini: {
    id: 'gemini', name: 'Gemini', base_url: 'https://generativelanguage.googleapis.com/v1beta/openai/',
    default_model: 'gemini-2.0-flash', models: ['gemini-2.0-flash', 'gemini-2.5-flash-preview-05-20'],
    supports_thinking: false, thinking_field: '', supports_tools: true,
    free_tier: false, requires_endpoint_id: false,
  },
  custom: {
    id: 'custom', name: '自定义', base_url: '', default_model: '', models: [],
    supports_thinking: false, thinking_field: '', supports_tools: true,
    free_tier: false, requires_endpoint_id: false,
  },
}

export function getProvider(id: string): ProviderInfo | undefined {
  return PROVIDERS[id]
}

export function listProviders(): ProviderInfo[] {
  return Object.values(PROVIDERS)
}
