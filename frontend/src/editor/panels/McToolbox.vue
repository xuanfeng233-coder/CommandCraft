<script setup lang="ts">
import { ref } from 'vue'

const emit = defineEmits<{
  select: [value: string]
}>()

const activeTab = ref<'color' | 'symbol' | 'json'>('color')

const COLOR_CODES = [
  { code: '§0', color: '#000000', name: '黑色' },
  { code: '§1', color: '#0000AA', name: '深蓝' },
  { code: '§2', color: '#00AA00', name: '深绿' },
  { code: '§3', color: '#00AAAA', name: '深青' },
  { code: '§4', color: '#AA0000', name: '深红' },
  { code: '§5', color: '#AA00AA', name: '紫色' },
  { code: '§6', color: '#FFAA00', name: '金色' },
  { code: '§7', color: '#AAAAAA', name: '灰色' },
  { code: '§8', color: '#555555', name: '深灰' },
  { code: '§9', color: '#5555FF', name: '蓝色' },
  { code: '§a', color: '#55FF55', name: '绿色' },
  { code: '§b', color: '#55FFFF', name: '青色' },
  { code: '§c', color: '#FF5555', name: '红色' },
  { code: '§d', color: '#FF55FF', name: '粉红' },
  { code: '§e', color: '#FFFF55', name: '黄色' },
  { code: '§f', color: '#FFFFFF', name: '白色' },
  { code: '§g', color: '#DDD605', name: '硬币金' },
]

const FORMAT_CODES = [
  { code: '§k', name: '随机字符', desc: 'Obfuscated' },
  { code: '§l', name: '粗体', desc: 'Bold' },
  { code: '§o', name: '斜体', desc: 'Italic' },
  { code: '§r', name: '重置格式', desc: 'Reset' },
]

const SPECIAL_SYMBOLS = [
  { char: '\uE102', code: 'E102', name: '硬币 (Minecoin)' },
  { char: '\uE105', code: 'E105', name: '代币 (Token)' },
  { char: '\uE10C', code: 'E10C', name: '红心 (Heart)' },
  { char: '\uE100', code: 'E100', name: '食物 (Food)' },
  { char: '\uE101', code: 'E101', name: '盔甲 (Armor)' },
  { char: '\uE106', code: 'E106', name: '空心星 (Hollow Star)' },
  { char: '\uE107', code: 'E107', name: '实心星 (Solid Star)' },
  { char: '\uE108', code: 'E108', name: '木镐 (Pickaxe)' },
  { char: '\uE109', code: 'E109', name: '木剑 (Sword)' },
  { char: '\uE10A', code: 'E10A', name: '工作台 (Crafting Table)' },
  { char: '\uE10B', code: 'E10B', name: '熔炉 (Furnace)' },
  { char: '\uE103', code: 'E103', name: '代码构建器 (Agent)' },
  { char: '\uE104', code: 'E104', name: '沉浸式阅读器' },
  { char: '\uE0A0', code: 'E0A0', name: '可合成-开' },
  { char: '\uE0A1', code: 'E0A1', name: '可合成-关' },
  // Xbox 按键
  { char: '\uE000', code: 'E000', name: 'Xbox A键' },
  { char: '\uE001', code: 'E001', name: 'Xbox B键' },
  { char: '\uE002', code: 'E002', name: 'Xbox X键' },
  { char: '\uE003', code: 'E003', name: 'Xbox Y键' },
  { char: '\uE004', code: 'E004', name: 'Xbox LB' },
  { char: '\uE005', code: 'E005', name: 'Xbox RB' },
  { char: '\uE006', code: 'E006', name: 'Xbox LT' },
  { char: '\uE007', code: 'E007', name: 'Xbox RT' },
  // 鼠标按键
  { char: '\uE060', code: 'E060', name: '鼠标左键' },
  { char: '\uE061', code: 'E061', name: '鼠标右键' },
  { char: '\uE062', code: 'E062', name: '鼠标中键' },
  // PS 按键
  { char: '\uE020', code: 'E020', name: 'PS ×键' },
  { char: '\uE021', code: 'E021', name: 'PS ○键' },
  { char: '\uE022', code: 'E022', name: 'PS □键' },
  { char: '\uE023', code: 'E023', name: 'PS △键' },
  // NS 按键
  { char: '\uE040', code: 'E040', name: 'NS A键' },
  { char: '\uE041', code: 'E041', name: 'NS B键' },
  { char: '\uE042', code: 'E042', name: 'NS X键' },
  { char: '\uE043', code: 'E043', name: 'NS Y键' },
  // 触屏按键
  { char: '\uE014', code: 'E014', name: '跳跃 (Touch)' },
  { char: '\uE015', code: 'E015', name: '攻击 (Touch)' },
  { char: '\uE016', code: 'E016', name: '摇杆 (Touch)' },
  { char: '\uE017', code: 'E017', name: '准心 (Touch)' },
  { char: '\uE018', code: 'E018', name: '交互 (Touch)' },
  { char: '\uE019', code: 'E019', name: '潜行 (Touch)' },
  { char: '\uE01A', code: 'E01A', name: '冲刺 (Touch)' },
]

const RAWTEXT_TEMPLATES = [
  {
    label: '纯文本',
    json: '{"rawtext":[{"text":"在此输入"}]}',
    desc: '最基本的文本显示',
  },
  {
    label: '带颜色文本',
    json: '{"rawtext":[{"text":"§e黄色文本§r"}]}',
    desc: '使用 §颜色代码 着色',
  },
  {
    label: '显示玩家名',
    json: '{"rawtext":[{"selector":"@a"}]}',
    desc: '显示匹配的实体名称',
  },
  {
    label: '显示分数',
    json: '{"rawtext":[{"score":{"name":"@s","objective":"计分板名"}}]}',
    desc: '显示计分板分数值',
  },
  {
    label: '翻译文本',
    json: '{"rawtext":[{"translate":"chat.type.text","with":{"rawtext":[{"selector":"@s"},{"text":"消息"}]}}]}',
    desc: '翻译键+参数替换',
  },
  {
    label: '组合示例',
    json: '{"rawtext":[{"text":"§l玩家 "},{"selector":"@s"},{"text":" 的分数: §e"},{"score":{"name":"@s","objective":"kills"}}]}',
    desc: '文本+选择器+分数组合',
  },
]

function copyToClipboard(text: string) {
  navigator.clipboard.writeText(text)
}
</script>

<template>
  <div class="toolbox">
    <div class="toolbox-tabs">
      <button
        class="toolbox-tab"
        :class="{ active: activeTab === 'color' }"
        @click="activeTab = 'color'"
      >
        颜色代码
      </button>
      <button
        class="toolbox-tab"
        :class="{ active: activeTab === 'symbol' }"
        @click="activeTab = 'symbol'"
      >
        特殊符号
      </button>
      <button
        class="toolbox-tab"
        :class="{ active: activeTab === 'json' }"
        @click="activeTab = 'json'"
      >
        JSON模板
      </button>
    </div>

    <div class="toolbox-content">
      <!-- Color codes tab -->
      <div v-if="activeTab === 'color'" class="color-section">
        <div class="section-label">颜色 (点击插入编辑器)</div>
        <div class="color-grid">
          <button
            v-for="c in COLOR_CODES"
            :key="c.code"
            class="color-item"
            :title="`${c.code} ${c.name} — 点击插入`"
            @click="emit('select', c.code)"
          >
            <span class="color-swatch" :style="{ background: c.color }" />
            <span class="color-code">{{ c.code }}</span>
          </button>
        </div>
        <div class="section-label">格式</div>
        <div class="color-grid">
          <button
            v-for="f in FORMAT_CODES"
            :key="f.code"
            class="format-item"
            :title="`${f.code} ${f.name} (${f.desc}) — 点击插入`"
            @click="emit('select', f.code)"
          >
            <span class="format-code">{{ f.code }}</span>
            <span class="format-name">{{ f.name }}</span>
          </button>
        </div>
        <div class="section-hint">
          提示: 基岩版不支持 §m(删除线) 和 §n(下划线)
        </div>
      </div>

      <!-- Special symbols tab -->
      <div v-if="activeTab === 'symbol'" class="symbol-section">
        <div class="section-label">
          特殊符号 (点击插入, 仅游戏内可见)
        </div>
        <div class="symbol-grid">
          <button
            v-for="s in SPECIAL_SYMBOLS"
            :key="s.code"
            class="symbol-item"
            :title="`U+${s.code} ${s.name} — 点击插入Unicode字符`"
            @click="emit('select', s.char)"
          >
            <span class="symbol-code">{{ s.code }}</span>
            <span class="symbol-name">{{ s.name }}</span>
          </button>
        </div>
        <div class="section-hint">
          这些字符使用 Minecraft 私有 Unicode 区段, 在游戏内显示为图标
        </div>
      </div>

      <!-- JSON templates tab -->
      <div v-if="activeTab === 'json'" class="json-section">
        <div class="section-label">Rawtext JSON 模板 (用于 tellraw / titleraw)</div>
        <div class="json-list">
          <div
            v-for="t in RAWTEXT_TEMPLATES"
            :key="t.label"
            class="json-item"
          >
            <div class="json-header">
              <span class="json-label">{{ t.label }}</span>
              <span class="json-desc">{{ t.desc }}</span>
            </div>
            <div class="json-actions">
              <code class="json-preview">{{ t.json }}</code>
              <div class="json-buttons">
                <button
                  class="json-btn"
                  title="插入到编辑器"
                  @click="emit('select', t.json)"
                >
                  插入
                </button>
                <button
                  class="json-btn"
                  title="复制到剪贴板"
                  @click="copyToClipboard(t.json)"
                >
                  复制
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.toolbox {
  display: flex;
  flex-direction: column;
  max-height: 240px;
  overflow: hidden;
}

.toolbox-tabs {
  display: flex;
  gap: 0;
  border-bottom: 2px solid var(--mc-border);
  flex-shrink: 0;
}

.toolbox-tab {
  flex: 1;
  background: var(--mc-bg-deep);
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--mc-text-dim);
  font-family: var(--mc-font-title);
  font-size: 12px;
  padding: 5px 8px;
  cursor: pointer;
  transition: all 0.15s;
}

.toolbox-tab:hover {
  color: var(--mc-text-primary);
  background: var(--mc-bg-hover);
}

.toolbox-tab.active {
  color: var(--mc-gold);
  border-bottom-color: var(--mc-gold);
  background: var(--mc-bg-card);
}

.toolbox-content {
  overflow-y: auto;
  padding: 6px 8px;
  scrollbar-width: thin;
  scrollbar-color: var(--mc-border) transparent;
}

.section-label {
  font-family: var(--mc-font-title);
  font-size: 11px;
  color: var(--mc-text-secondary);
  margin-bottom: 4px;
  margin-top: 4px;
}

.section-hint {
  font-size: 10px;
  color: var(--mc-text-dim);
  margin-top: 6px;
  font-style: italic;
}

/* Color grid */
.color-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 3px;
}

.color-item {
  display: flex;
  align-items: center;
  gap: 4px;
  background: var(--mc-bg-deep);
  border: 1px solid var(--mc-border);
  color: var(--mc-text-primary);
  padding: 3px 6px;
  font-family: var(--mc-font-mono);
  font-size: 11px;
  cursor: pointer;
}

.color-item:hover {
  border-color: var(--mc-gold);
  background: var(--mc-bg-hover);
}

.color-swatch {
  display: inline-block;
  width: 12px;
  height: 12px;
  border: 1px solid rgba(255, 255, 255, 0.2);
  flex-shrink: 0;
}

.color-code {
  color: var(--mc-syn-command);
}

.format-item {
  display: flex;
  align-items: center;
  gap: 4px;
  background: var(--mc-bg-deep);
  border: 1px solid var(--mc-border);
  color: var(--mc-text-primary);
  padding: 3px 8px;
  font-family: var(--mc-font-mono);
  font-size: 11px;
  cursor: pointer;
}

.format-item:hover {
  border-color: var(--mc-gold);
  background: var(--mc-bg-hover);
}

.format-code {
  color: var(--mc-syn-command);
}

.format-name {
  color: var(--mc-text-dim);
  font-size: 10px;
}

/* Symbol grid */
.symbol-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 3px;
}

.symbol-item {
  display: flex;
  align-items: center;
  gap: 4px;
  background: var(--mc-bg-deep);
  border: 1px solid var(--mc-border);
  color: var(--mc-text-primary);
  padding: 3px 6px;
  font-family: var(--mc-font-mono);
  font-size: 11px;
  cursor: pointer;
  max-width: 180px;
}

.symbol-item:hover {
  border-color: var(--mc-gold);
  background: var(--mc-bg-hover);
}

.symbol-code {
  color: var(--mc-syn-param);
  font-size: 10px;
  flex-shrink: 0;
}

.symbol-name {
  color: var(--mc-text-dim);
  font-size: 10px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* JSON templates */
.json-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.json-item {
  background: var(--mc-bg-deep);
  border: 1px solid var(--mc-border);
  padding: 6px 8px;
}

.json-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.json-label {
  font-family: var(--mc-font-title);
  font-size: 12px;
  color: var(--mc-text-primary);
}

.json-desc {
  font-size: 10px;
  color: var(--mc-text-dim);
}

.json-actions {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.json-preview {
  display: block;
  font-family: var(--mc-font-mono);
  font-size: 10px;
  color: var(--mc-syn-string);
  background: rgba(0, 0, 0, 0.3);
  padding: 4px 6px;
  overflow-x: auto;
  white-space: nowrap;
  scrollbar-width: thin;
}

.json-buttons {
  display: flex;
  gap: 4px;
}

.json-btn {
  background: var(--mc-bg-card);
  border: 1px solid var(--mc-border);
  color: var(--mc-text-secondary);
  font-family: var(--mc-font-body);
  font-size: 11px;
  padding: 2px 10px;
  cursor: pointer;
}

.json-btn:hover {
  border-color: var(--mc-gold);
  color: var(--mc-gold);
}
</style>
