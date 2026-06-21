import type { Router } from 'vue-router'

type SeoMeta = { title: string; description: string; canonical: string }

const DEFAULT: SeoMeta = {
  title: 'Minecraft 命令生成器｜中文描述自动生成 - CommandCraft（基岩版/Java 版）',
  description:
    '不会写 Minecraft 命令？直接用中文说想要的效果，AI 自动生成可用命令，支持基岩版 / Java 版，一键导出 .mcfunction，再也不用背命令表。',
  canonical: 'https://commandcraft.cn/',
}

const ROUTE_META: Record<string, SeoMeta> = {
  chat: DEFAULT,
  setup: {
    title: '开始使用 - CommandCraft｜选模型或直接试用',
    description: '可以用我们的免费试用次数直接开始，也可以填自己的 DeepSeek / Qwen / GLM / Kimi / Gemini API Key 使用。',
    canonical: 'https://commandcraft.cn/setup',
  },
}

function upsertMeta(selector: string, attr: 'name' | 'property', key: string, value: string) {
  let el = document.head.querySelector<HTMLMetaElement>(selector)
  if (!el) {
    el = document.createElement('meta')
    el.setAttribute(attr, key)
    document.head.appendChild(el)
  }
  el.setAttribute('content', value)
}

function upsertCanonical(href: string) {
  let el = document.head.querySelector<HTMLLinkElement>('link[rel="canonical"]')
  if (!el) {
    el = document.createElement('link')
    el.setAttribute('rel', 'canonical')
    document.head.appendChild(el)
  }
  el.setAttribute('href', href)
}

export function installSeoGuard(router: Router) {
  router.afterEach((to) => {
    const name = (to.name as string) || 'chat'
    const meta = ROUTE_META[name] || DEFAULT
    document.title = meta.title
    upsertMeta('meta[name="description"]', 'name', 'description', meta.description)
    upsertMeta('meta[property="og:title"]', 'property', 'og:title', meta.title)
    upsertMeta('meta[property="og:description"]', 'property', 'og:description', meta.description)
    upsertMeta('meta[property="og:url"]', 'property', 'og:url', meta.canonical)
    upsertMeta('meta[name="twitter:title"]', 'name', 'twitter:title', meta.title)
    upsertMeta('meta[name="twitter:description"]', 'name', 'twitter:description', meta.description)
    upsertCanonical(meta.canonical)
  })
}
