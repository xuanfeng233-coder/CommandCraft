import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'node:path'
import { copyFileSync, mkdirSync, readdirSync, statSync } from 'node:fs'

// Copy knowledge_base to public/ for static serving
function copyKnowledgeBase() {
  return {
    name: 'copy-knowledge-base',
    buildStart() {
      const src = resolve(__dirname, '../knowledge_base')
      const dest = resolve(__dirname, 'public/knowledge_base')
      copyDirSync(src, dest)
    },
  }
}

function copyDirSync(src: string, dest: string) {
  try {
    mkdirSync(dest, { recursive: true })
    for (const entry of readdirSync(src)) {
      const srcPath = resolve(src, entry)
      const destPath = resolve(dest, entry)
      const stat = statSync(srcPath)
      if (stat.isDirectory()) {
        copyDirSync(srcPath, destPath)
      } else {
        copyFileSync(srcPath, destPath)
      }
    }
  } catch {
    console.warn('[vite] Could not copy knowledge_base:', src)
  }
}

export default defineConfig({
  plugins: [vue(), copyKnowledgeBase()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
