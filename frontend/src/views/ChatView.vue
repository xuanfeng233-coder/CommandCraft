<script setup lang="ts">
import { ref, computed, onBeforeUnmount, onMounted } from 'vue'
import { McNav, McButton, McInput, McModal } from '@/components/mc-ui'
import ChatPanel from '@/components/ChatPanel.vue'
import BuildPanel from '@/components/BuildPanel.vue'
import HistoryPanel from '@/components/HistoryPanel.vue'
import ExportDialog from '@/components/ExportDialog.vue'
import ModelStatus from '@/components/ModelStatus.vue'
import SettingsModal from '@/components/SettingsModal.vue'
import AuthModal from '@/components/AuthModal.vue'
import McCommandEditor from '@/editor/McCommandEditor.vue'
import { useChatStore } from '@/stores/chat'
import { useBuildStore } from '@/stores/build'
import { useSettingsStore } from '@/stores/settings'
import { useSubscriptionStore } from '@/stores/subscription'
import { useAuthStore } from '@/stores/auth'
import { useKnowledgeCache } from '@/stores/knowledge-cache'
import { storeToRefs } from 'pinia'

const chatStore = useChatStore()
const buildStore = useBuildStore()
const settingsStore = useSettingsStore()
const subStore = useSubscriptionStore()
const authStore = useAuthStore()
const knowledgeCache = useKnowledgeCache()
const { messages, isLoading } = storeToRefs(chatStore)
const { canBuild } = storeToRefs(buildStore)

// --- Edition toggle ---
const edition = ref<'bedrock' | 'java'>(
  (localStorage.getItem('mc-edition') as 'bedrock' | 'java') || 'bedrock'
)

function toggleEdition() {
  edition.value = edition.value === 'bedrock' ? 'java' : 'bedrock'
  localStorage.setItem('mc-edition', edition.value)
  knowledgeCache.reload(edition.value)
}

const showSettings = ref(false)
const settingsInitialTab = ref<'model' | 'subscription'>('model')
const showConfigPrompt = ref(false)

// Check auth session on mount
onMounted(() => {
  authStore.checkSession()
})

const inputText = ref('')
const showHistory = ref(false)
const showExport = ref(false)
const showBuild = ref(false)
const mobileTab = ref<'chat' | 'editor'>('chat')

// --- Mobile navbar toggle via menu button ---
const navHidden = ref(true)

function toggleNav() {
  navHidden.value = !navHidden.value
}

function hideNav() {
  navHidden.value = true
}

// --- Draggable divider ---
const EDITOR_WIDTH_KEY = 'mcbe-ai-editor-width'
const editorWidth = ref(
  parseInt(localStorage.getItem(EDITOR_WIDTH_KEY) || '480', 10)
)
const isDragging = ref(false)

const gridColumns = computed(() => `1fr 4px ${editorWidth.value}px`)

function onDividerMouseDown(e: MouseEvent) {
  e.preventDefault()
  isDragging.value = true
  document.addEventListener('mousemove', onDividerMouseMove)
  document.addEventListener('mouseup', onDividerMouseUp)
}

function onDividerMouseMove(e: MouseEvent) {
  const maxWidth = window.innerWidth * 0.6
  const newWidth = window.innerWidth - e.clientX
  editorWidth.value = Math.max(280, Math.min(newWidth, maxWidth))
}

function onDividerMouseUp() {
  isDragging.value = false
  document.removeEventListener('mousemove', onDividerMouseMove)
  document.removeEventListener('mouseup', onDividerMouseUp)
  localStorage.setItem(EDITOR_WIDTH_KEY, String(editorWidth.value))
}

onBeforeUnmount(() => {
  document.removeEventListener('mousemove', onDividerMouseMove)
  document.removeEventListener('mouseup', onDividerMouseUp)
})

async function handleSend() {
  const text = inputText.value.trim()
  if (!text) return

  // Check if configured or subscribed
  if (!settingsStore.isConfigured) {
    // Try subscription check as fallback
    if (!subStore.isActive) {
      await subStore.fetchStatus()
    }
    if (subStore.isActive) {
      settingsStore.markSubscriptionActive()
    } else {
      showConfigPrompt.value = true
      return
    }
  }

  inputText.value = ''
  chatStore.sendMessage(text)
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}

function handleExample(text: string) {
  inputText.value = text
  handleSend()
}

function handleClearChat() {
  chatStore.clearChat()
}

function openSettings(tab: 'model' | 'subscription' = 'model') {
  settingsInitialTab.value = tab
  showSettings.value = true
}

const latestCommandMessage = computed(() => {
  for (let i = messages.value.length - 1; i >= 0; i--) {
    const msg = messages.value[i]
    if (msg.role === 'assistant' && msg.command) return msg
  }
  return null
})

const latestProjectMessage = computed(() => {
  for (let i = messages.value.length - 1; i >= 0; i--) {
    const msg = messages.value[i]
    if (msg.role === 'assistant' && msg.project) return msg
  }
  return null
})
</script>

<template>
  <div
    class="app-layout"
    :class="{ [`mobile-${mobileTab}`]: true, 'is-dragging': isDragging, 'nav-hidden': navHidden }"
    :style="{ gridTemplateColumns: gridColumns }"
  >
    <!-- Mobile menu button (visible only on mobile when nav is hidden) -->
    <button v-if="navHidden && mobileTab === 'chat'" class="mobile-menu-btn" @click.stop="toggleNav">☰</button>
    <!-- Mobile backdrop (click to close nav) -->
    <div v-if="!navHidden" class="mobile-nav-backdrop" @click="hideNav" />

    <!-- Row 1: Navbar -->
    <McNav class="nav-bar">
      <div class="nav-left">
        <img src="/images/logo.png" alt="CommandCraft" class="nav-logo" />
        <span class="nav-title">CommandCraft</span>
      </div>
      <div class="nav-center">
        <button class="edition-toggle" @click="toggleEdition" :title="edition === 'bedrock' ? '切换到 Java 版' : '切换到基岩版'">
          <span :class="['edition-chip', { active: edition === 'bedrock' }]">基岩版</span>
          <span :class="['edition-chip', { active: edition === 'java' }]">Java版</span>
        </button>
      </div>
      <div class="nav-right">
        <ModelStatus @open-settings="openSettings('model')" />
        <McButton size="small" @click="openSettings('model')">
          设置
        </McButton>
        <McButton size="small" @click="showHistory = true">
          历史
        </McButton>
        <McButton
          v-if="canBuild"
          size="small"
          @click="showBuild = !showBuild"
          :class="{ 'btn-active': showBuild }"
        >
          构建
        </McButton>
        <McButton
          v-if="latestCommandMessage || latestProjectMessage"
          size="small"
          @click="showExport = true"
        >
          导出
        </McButton>
        <McButton
          size="small"
          @click="handleClearChat"
          :disabled="messages.length === 0"
        >
          新对话
        </McButton>
        <McButton
          v-if="authStore.isLoggedIn"
          size="small"
          class="user-btn"
          @click="authStore.logout()"
        >
          {{ authStore.username }}
        </McButton>
        <McButton
          v-else
          size="small"
          @click="authStore.showAuthModal = true"
        >
          登录
        </McButton>
      </div>
    </McNav>

    <!-- Row 2: Chat or Build panel -->
    <div class="chat-area mc-tex-dirt">
      <BuildPanel v-if="showBuild" />
      <ChatPanel v-else @example="handleExample" />
    </div>

    <!-- Row 2: Divider (drag to resize) -->
    <div class="panel-divider mc-tex-bedrock" @mousedown="onDividerMouseDown" />

    <!-- Row 2: Command Editor panel -->
    <div class="editor-area">
      <McCommandEditor />
    </div>

    <!-- Mobile tab bar -->
    <div class="mobile-tabs">
      <button
        class="mobile-tab"
        :class="{ active: mobileTab === 'chat' }"
        @click="mobileTab = 'chat'"
      >
        对话
      </button>
      <button
        class="mobile-tab"
        :class="{ active: mobileTab === 'editor' }"
        @click="mobileTab = 'editor'"
      >
        编辑器
      </button>
    </div>

    <!-- Row 3: Input bar (hidden in build mode) -->
    <div v-if="!showBuild" class="input-bar mc-tex-dark-oak">
      <div class="input-container">
        <div class="input-wrapper">
          <McInput
            :model-value="inputText"
            type="textarea"
            :autosize="{ minRows: 1, maxRows: 4 }"
            placeholder="输入你的命令需求..."
            :disabled="isLoading"
            @update:model-value="inputText = $event"
            @keydown="handleKeydown"
            class="input-field"
          />
        </div>
        <McButton
          variant="primary"
          :loading="isLoading"
          :disabled="!inputText.trim() && !isLoading"
          @click="handleSend"
        >
          发送
        </McButton>
      </div>
    </div>

    <!-- Overlays -->
    <HistoryPanel v-model:show="showHistory" />
    <ExportDialog
      v-model:show="showExport"
      :command="latestCommandMessage?.command"
      :project="latestProjectMessage?.project"
    />
    <SettingsModal v-model:show="showSettings" :initial-tab="settingsInitialTab" />
    <AuthModal v-model:show="authStore.showAuthModal" />

    <!-- Config prompt for unconfigured users -->
    <McModal :show="showConfigPrompt" @update:show="showConfigPrompt = $event">
      <div class="config-prompt">
        <h3 class="config-prompt-title">需要配置 AI 模型</h3>
        <p class="config-prompt-desc">
          使用 AI 命令生成功能需要先配置模型。你可以自行配置 API Key，或使用订阅服务。
        </p>
        <p class="config-prompt-hint">命令编辑器无需配置，可继续使用。</p>
        <div class="config-prompt-actions">
          <McButton @click="showConfigPrompt = false">取消</McButton>
          <McButton @click="showConfigPrompt = false; authStore.isLoggedIn ? openSettings('subscription') : (authStore.showAuthModal = true)">
            使用订阅
          </McButton>
          <McButton variant="primary" @click="showConfigPrompt = false; openSettings('model')">
            配置模型
          </McButton>
        </div>
      </div>
    </McModal>
  </div>
</template>

<style scoped>
.app-layout {
  display: grid;
  grid-template-rows: auto 1fr auto;
  /* grid-template-columns set via inline style (gridColumns) */
  height: 100vh;
  overflow: hidden;
}

.app-layout.is-dragging {
  user-select: none;
  cursor: col-resize;
}

/* Row 1: Nav spans all columns */
.nav-bar {
  grid-column: 1 / -1;
}

.nav-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.nav-logo {
  height: 32px;
  width: 32px;
  image-rendering: pixelated;
  border-radius: 4px;
}

.nav-title {
  font-family: var(--mc-font-title);
  font-size: 15px;
  color: var(--mc-gold);
  text-shadow: 1px 1px 0 rgba(0, 0, 0, 0.5);
  white-space: nowrap;
}

.nav-center {
  display: flex;
  align-items: center;
  justify-content: center;
}

.nav-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.edition-toggle {
  display: flex;
  align-items: center;
  gap: 0;
  padding: 0;
  border: 2px solid var(--mc-border);
  cursor: pointer;
  background: transparent;
  overflow: hidden;
}

.edition-toggle:hover {
  border-color: var(--mc-gold);
}

.edition-chip {
  font-family: var(--mc-font-title);
  font-size: 12px;
  padding: 3px 10px;
  color: var(--mc-text-dim);
  transition: all 0.15s;
  white-space: nowrap;
}

.edition-chip.active {
  color: #fff;
  background: rgba(255, 170, 0, 0.25);
  color: var(--mc-gold);
}

:deep(.btn-active.mc-btn) {
  border-color: var(--mc-gold);
  color: var(--mc-gold);
}

:deep(.user-btn.mc-btn) {
  color: var(--mc-green);
  border-color: var(--mc-green);
  max-width: 100px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Row 2: Chat area */
.chat-area {
  overflow: hidden;
}

/* Row 2: Divider */
.panel-divider {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: col-resize;
}

/* Row 2: Editor area */
.editor-area {
  overflow: hidden;
}

/* Row 3: Input bar — only chat column on desktop */
.input-bar {
  grid-column: 1 / 2;
  padding: 12px 20px;
  border-top: 2px solid var(--mc-border);
  flex-shrink: 0;
}

.input-container {
  display: flex;
  gap: 8px;
  align-items: flex-end;
  max-width: 100%;
}

.input-wrapper {
  position: relative;
  flex: 1;
}

.input-field {
  flex: 1;
  width: 100%;
}

/* Mobile tab bar — hidden on desktop */
.mobile-tabs {
  display: none;
  grid-column: 1 / -1;
}

/* Mobile menu button & backdrop — hidden on desktop */
.mobile-menu-btn,
.mobile-nav-backdrop {
  display: none;
}

/* ===== Mobile Responsive ===== */
@media (max-width: 768px) {
  /* 3-row grid: content | input | bottom tabs */
  .app-layout {
    grid-template-columns: 1fr !important;
    grid-template-rows: 1fr auto auto;
    height: 100dvh;
    padding-bottom: env(safe-area-inset-bottom, 0px);
  }

  /* Persistent menu button */
  .mobile-menu-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    position: fixed;
    top: 6px;
    left: 6px;
    z-index: 99;
    width: 32px;
    height: 32px;
    border: 2px solid var(--mc-border);
    border-radius: 4px;
    background: var(--mc-bg-card);
    color: var(--mc-text-primary);
    font-size: 16px;
    line-height: 1;
    cursor: pointer;
    opacity: 0.7;
    box-shadow: 0 2px 6px rgba(0,0,0,0.4);
    padding-top: env(safe-area-inset-top, 0px);
  }
  .mobile-menu-btn:active {
    opacity: 1;
  }

  /* Backdrop to close nav */
  .mobile-nav-backdrop {
    display: block;
    position: fixed;
    inset: 0;
    z-index: 99;
    background: rgba(0,0,0,0.3);
  }

  /* Navbar: fixed top, slide in/out via nav-hidden */
  .nav-bar {
    position: fixed;
    top: 0; left: 0; right: 0;
    z-index: 100;
    transform: translateY(0);
    transition: transform 300ms ease;
    padding-top: env(safe-area-inset-top, 0px);
  }
  .app-layout.nav-hidden .nav-bar {
    transform: translateY(-100%);
  }

  /* Hide title text on mobile, keep logo */
  .nav-left {
    gap: 4px;
    order: 1;
  }
  .nav-title { display: none; }
  .nav-logo {
    height: 26px;
    width: 26px;
  }

  /* Edition toggle: centered in first row */
  .nav-center {
    order: 2;
  }
  .edition-toggle {
    border-width: 1px;
  }
  .edition-chip {
    font-size: 11px;
    padding: 2px 7px;
  }

  /* Nav right: second row, full width, scroll horizontally */
  .nav-right {
    order: 3;
    width: 100%;
    gap: 4px;
    flex-wrap: nowrap;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    scrollbar-width: none; /* Firefox */
    padding-bottom: 2px;
  }
  .nav-right::-webkit-scrollbar {
    display: none;
  }
  .nav-right :deep(.mc-btn) {
    font-size: 11px;
    padding: 2px 6px;
    min-height: unset;
    flex-shrink: 0;
  }

  /* Hide divider */
  .panel-divider { display: none; }

  /* Content areas: row 1 */
  .chat-area  { grid-row: 1; grid-column: 1; }
  .editor-area { grid-row: 1; grid-column: 1; }

  /* Tab-based show/hide */
  .app-layout.mobile-chat .chat-area    { display: block; }
  .app-layout.mobile-chat .editor-area  { display: none; }
  .app-layout.mobile-editor .chat-area  { display: none; }
  .app-layout.mobile-editor .editor-area { display: block; }

  /* Input bar: row 2, hidden in editor mode */
  .input-bar {
    grid-row: 2; grid-column: 1;
    padding: 8px 12px;
  }
  .app-layout.mobile-editor .input-bar { display: none; }

  /* Bottom tab bar: row 3 */
  .mobile-tabs {
    display: flex;
    grid-row: 3; grid-column: 1;
    gap: 0;
    border-top: 2px solid var(--mc-border);
    border-bottom: none;
    background: var(--mc-bg-card);
  }
  .mobile-tab {
    flex: 1;
    background: var(--mc-bg-card);
    border: none;
    border-top: 3px solid transparent;
    color: var(--mc-text-dim);
    font-family: var(--mc-font-title);
    font-size: 12px;
    padding: 6px 0;
    cursor: pointer;
  }
  .mobile-tab.active {
    color: var(--mc-gold);
    border-top-color: var(--mc-gold);
    background: var(--mc-bg-main);
  }
  .mobile-tab:hover {
    color: var(--mc-text-primary);
  }
}

/* Config prompt modal */
.config-prompt {
  width: 420px;
  max-width: 90vw;
  padding: 24px 28px;
}

.config-prompt-title {
  font-family: var(--mc-font-title);
  color: var(--mc-gold);
  font-size: 17px;
  margin: 0 0 12px;
}

.config-prompt-desc {
  color: var(--mc-text-primary);
  font-size: 13px;
  line-height: 1.6;
  margin: 0 0 8px;
}

.config-prompt-hint {
  color: var(--mc-text-dim);
  font-size: 12px;
  line-height: 1.5;
  margin: 0 0 20px;
}

.config-prompt-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}

/* Touch-friendly completion dropdown */
@media (pointer: coarse) {
  .editor-area :deep(.cm-tooltip-autocomplete > ul > li) {
    min-height: 44px;
    padding: 8px 12px;
    display: flex;
    align-items: center;
  }
}
</style>
