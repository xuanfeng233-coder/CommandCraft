<script setup lang="ts">
import { computed } from 'vue'
import { McCard, McTag, McTooltip } from '@/components/mc-ui'
import type { BlockLayoutEntry, BlockGroup, BlockDimensions } from '@/types'

const props = defineProps<{
  layout: BlockLayoutEntry[]
  groups: BlockGroup[]
  dimensions: BlockDimensions
}>()

const blockColors: Record<string, string> = {
  repeating_command_block: '#5b3c8e',
  chain_command_block: '#1e8e3e',
  command_block: '#c67635',
}

const blockLabels: Record<string, string> = {
  repeating_command_block: 'R',
  chain_command_block: 'C',
  command_block: 'I',
}

const blockTypeNames: Record<string, string> = {
  repeating_command_block: '循环',
  chain_command_block: '连锁',
  command_block: '脉冲',
}

const rows = computed(() => {
  const rowMap = new Map<number, BlockLayoutEntry[]>()
  for (const block of props.layout) {
    const z = block.position.z
    if (!rowMap.has(z)) rowMap.set(z, [])
    rowMap.get(z)!.push(block)
  }
  for (const blocks of rowMap.values()) {
    blocks.sort((a, b) => a.position.x - b.position.x)
  }
  return [...rowMap.entries()].sort((a, b) => a[0] - b[0])
})

const groupMap = computed(() => {
  const map = new Map<string, BlockGroup>()
  for (const g of props.groups) map.set(g.group_id, g)
  return map
})

function getGroupName(groupId: string): string {
  return groupMap.value.get(groupId)?.name || groupId
}

function getGroupTrigger(groupId: string): string {
  return groupMap.value.get(groupId)?.trigger_method || ''
}
</script>

<template>
  <McCard class="layout-viewer">
    <template #header>
      <span class="card-title">命令方块布局</span>
      <McTag size="tiny" type="info">
        {{ layout.length }} 个方块
      </McTag>
    </template>

    <div class="layout-grid">
      <div v-for="[z, blocks] in rows" :key="z" class="layout-row">
        <div class="row-label">
          <span class="group-name">{{ getGroupName(blocks[0]?.group_id || '') }}</span>
          <span v-if="getGroupTrigger(blocks[0]?.group_id || '')" class="group-trigger">
            {{ getGroupTrigger(blocks[0]?.group_id || '') }}
          </span>
        </div>
        <div class="blocks-row">
          <McTooltip v-for="block in blocks" :key="`${block.position.x}-${z}`">
            <template #trigger>
              <div
                class="block-cell"
                :class="{ conditional: block.conditional }"
                :style="{ backgroundColor: blockColors[block.block_type] || '#888' }"
              >
                <span class="block-letter">{{ blockLabels[block.block_type] || '?' }}</span>
              </div>
            </template>
            <div class="tooltip-content">
              <div><strong>{{ blockTypeNames[block.block_type] || block.block_type }}</strong></div>
              <div class="tooltip-cmd">{{ block.command }}</div>
              <div v-if="block.custom_name" class="tooltip-note">{{ block.custom_name }}</div>
              <div v-if="block.conditional" class="tooltip-note">条件模式</div>
              <div class="tooltip-pos">位置: ({{ block.position.x }}, {{ block.position.y }}, {{ block.position.z }})</div>
            </div>
          </McTooltip>
          <div class="direction-arrow">→</div>
        </div>
      </div>
    </div>

    <div class="layout-legend">
      <span class="legend-item">
        <span class="legend-dot" style="background-color: #c67635;" />脉冲
      </span>
      <span class="legend-item">
        <span class="legend-dot" style="background-color: #1e8e3e;" />连锁
      </span>
      <span class="legend-item">
        <span class="legend-dot" style="background-color: #5b3c8e;" />循环
      </span>
      <span class="legend-item">
        尺寸: {{ dimensions.width }} x {{ dimensions.height }} x {{ dimensions.depth }}
      </span>
    </div>
  </McCard>
</template>

<style scoped>
.layout-viewer {
  margin: 4px 0;
}

.card-title {
  font-family: var(--mc-font-title);
  font-size: 14px;
  font-weight: bold;
}

.layout-grid {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.layout-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.row-label {
  display: flex;
  align-items: center;
  gap: 8px;
}

.group-name {
  font-size: 12px;
  font-weight: 500;
  color: var(--mc-text-secondary);
}

.group-trigger {
  font-size: 11px;
  color: var(--mc-text-dim);
}

.blocks-row {
  display: flex;
  align-items: center;
  gap: 2px;
}

.block-cell {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: transform 150ms;
  position: relative;
  border: 2px solid rgba(255,255,255,0.15);
  box-shadow: var(--mc-shadow-raised-sm);
}

.block-cell:hover {
  transform: scale(1.15);
  z-index: 1;
}

.block-cell.conditional {
  border: 2px dashed rgba(255, 255, 255, 0.6);
}

.block-letter {
  color: #fff;
  font-size: 14px;
  font-weight: bold;
  font-family: var(--mc-font-mono);
}

.direction-arrow {
  color: var(--mc-text-dim);
  font-size: 16px;
  margin-left: 4px;
}

.tooltip-content {
  max-width: 300px;
}

.tooltip-cmd {
  font-family: var(--mc-font-mono);
  font-size: 12px;
  margin-top: 4px;
  word-break: break-all;
}

.tooltip-note {
  font-size: 11px;
  color: var(--mc-text-dim);
  margin-top: 2px;
}

.tooltip-pos {
  font-size: 11px;
  color: var(--mc-text-dim);
  margin-top: 4px;
}

.layout-legend {
  display: flex;
  gap: 16px;
  margin-top: 12px;
  padding-top: 8px;
  border-top: 2px solid var(--mc-border);
  font-size: 12px;
  color: var(--mc-text-dim);
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 4px;
}

.legend-dot {
  width: 10px;
  height: 10px;
  display: inline-block;
}
</style>
