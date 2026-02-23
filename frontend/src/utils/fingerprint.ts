/**
 * Lightweight device fingerprint generator.
 * Combines browser/hardware signals and hashes with SHA-256.
 * Cached in localStorage for consistency across sessions.
 */

const FP_STORAGE_KEY = 'mcbe-ai-device-fp'

let cachedFp: string | null = null

function getCanvasFingerprint(): string {
  try {
    const canvas = document.createElement('canvas')
    canvas.width = 200
    canvas.height = 50
    const ctx = canvas.getContext('2d')
    if (!ctx) return ''
    ctx.textBaseline = 'top'
    ctx.font = '14px Arial'
    ctx.fillStyle = '#f60'
    ctx.fillRect(125, 1, 62, 20)
    ctx.fillStyle = '#069'
    ctx.fillText('MCBE-AI-FP', 2, 15)
    ctx.fillStyle = 'rgba(102, 204, 0, 0.7)'
    ctx.fillText('MCBE-AI-FP', 4, 17)
    return canvas.toDataURL()
  } catch {
    return ''
  }
}

function getWebGLRenderer(): string {
  try {
    const canvas = document.createElement('canvas')
    const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl')
    if (!gl) return ''
    const webgl = gl as WebGLRenderingContext
    const debugInfo = webgl.getExtension('WEBGL_debug_renderer_info')
    if (!debugInfo) return ''
    return webgl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL) || ''
  } catch {
    return ''
  }
}

async function computeFingerprint(): Promise<string> {
  const signals = [
    navigator.userAgent,
    `${screen.width}x${screen.height}x${screen.colorDepth}`,
    navigator.language,
    Intl.DateTimeFormat().resolvedOptions().timeZone,
    String(navigator.hardwareConcurrency || ''),
    getCanvasFingerprint(),
    getWebGLRenderer(),
  ]

  const raw = signals.join('|||')
  const encoder = new TextEncoder()
  const data = encoder.encode(raw)
  const hashBuffer = await crypto.subtle.digest('SHA-256', data)
  const hashArray = Array.from(new Uint8Array(hashBuffer))
  return hashArray.map(b => b.toString(16).padStart(2, '0')).join('')
}

/**
 * Get (or compute & cache) the device fingerprint.
 */
export async function getDeviceFingerprint(): Promise<string> {
  if (cachedFp) return cachedFp

  // Check localStorage
  const stored = localStorage.getItem(FP_STORAGE_KEY)
  if (stored) {
    cachedFp = stored
    return stored
  }

  // Compute new fingerprint
  const fp = await computeFingerprint()
  localStorage.setItem(FP_STORAGE_KEY, fp)
  cachedFp = fp
  return fp
}
