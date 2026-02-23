import { reactive } from 'vue'

export interface ToastItem {
  id: number
  type: 'success' | 'error' | 'info' | 'warning'
  message: string
}

let nextId = 0
const queue = reactive<ToastItem[]>([])

function add(type: ToastItem['type'], message: string, duration = 3000) {
  const id = nextId++
  queue.push({ id, type, message })
  setTimeout(() => {
    const idx = queue.findIndex((t) => t.id === id)
    if (idx !== -1) queue.splice(idx, 1)
  }, duration)
}

export const toast = {
  success: (msg: string) => add('success', msg),
  error: (msg: string) => add('error', msg),
  info: (msg: string) => add('info', msg),
  warning: (msg: string) => add('warning', msg),
}

export function useToast() {
  return { queue, toast }
}
