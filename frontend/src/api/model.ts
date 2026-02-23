const API_BASE = '/api'

export interface HealthData {
  status: string
  provider_name: string
  model_name: string
  rag_index_status: Record<string, boolean> | null
}

export async function getHealth(): Promise<HealthData> {
  const resp = await fetch(`${API_BASE}/health`)
  if (!resp.ok) throw new Error('Health check failed')
  return resp.json()
}
