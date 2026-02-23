<script setup lang="ts">
import { ref } from 'vue'
import { McCard, McButton, McCollapse, McCollapseItem, McTag } from '@/components/mc-ui'
import BlockLayoutViewer from './BlockLayoutViewer.vue'
import { useEditorStore } from '@/stores/editor'
import type { ProjectResult } from '@/types'

const props = defineProps<{
  project: ProjectResult
}>()

const editorStore = useEditorStore()

const expandedPhases = ref<string[]>(
  props.project.phases.map((_, i) => `phase-${i}`)
)

function insertAllCommands() {
  for (const phase of props.project.phases) {
    for (const task of phase.tasks) {
      for (const block of task.command_blocks) {
        if (block.command) {
          editorStore.insertCommand(block.command)
        }
      }
    }
  }
}
</script>

<template>
  <div class="project-card">
    <McCard>
      <template #header>
        <span class="project-title">{{ project.project_name || '项目方案' }}</span>
      </template>
      <template #header-extra>
        <McButton size="small" @click="insertAllCommands">
          全部插入编辑器
        </McButton>
      </template>

      <div v-if="project.overview" class="project-overview">
        {{ project.overview }}
      </div>

      <div class="mc-divider" />

      <McCollapse v-model:expanded-names="expandedPhases">
        <McCollapseItem
          v-for="(phase, phaseIdx) in project.phases"
          :key="phaseIdx"
          :name="`phase-${phaseIdx}`"
        >
          <template #header>
            <span class="phase-header">
              {{ phase.phase_name }}
              <McTag size="tiny" type="default">
                {{ phase.tasks.length }} 个任务
              </McTag>
            </span>
          </template>

          <div v-if="phase.description" class="phase-desc">{{ phase.description }}</div>

          <div class="tasks-list">
            <div v-for="task in phase.tasks" :key="task.task_id" class="task-item">
              <div class="task-header">
                <McTag size="tiny" type="info">{{ task.task_id }}</McTag>
                <span class="task-desc">{{ task.description }}</span>
              </div>

              <div v-if="task.dependencies.length > 0" class="task-deps">
                依赖:
                <McTag
                  v-for="dep in task.dependencies"
                  :key="dep"
                  size="tiny"
                  type="warning"
                >
                  {{ dep }}
                </McTag>
              </div>

              <div v-if="task.command_blocks.length > 0" class="command-blocks-list">
                <div
                  v-for="(block, bIdx) in task.command_blocks"
                  :key="bIdx"
                  class="block-item"
                >
                  <div class="block-tags">
                    <McTag
                      :type="block.type === 'repeating' ? 'info' : block.type === 'impulse' ? 'warning' : 'success'"
                      size="tiny"
                    >
                      {{ block.type === 'repeating' ? '循环' : block.type === 'impulse' ? '脉冲' : '连锁' }}
                    </McTag>
                    <McTag v-if="block.conditional" size="tiny" type="default">条件</McTag>
                  </div>
                  <code class="block-command">{{ block.command }}</code>
                  <div v-if="block.comment" class="block-comment">{{ block.comment }}</div>
                </div>
              </div>
            </div>
          </div>
        </McCollapseItem>
      </McCollapse>
    </McCard>

    <BlockLayoutViewer
      v-if="project.layout && project.layout.length > 0"
      :layout="project.layout"
      :groups="project.groups || []"
      :dimensions="project.dimensions || { width: 0, height: 0, depth: 0 }"
    />
  </div>
</template>

<style scoped>
.project-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.project-title {
  font-family: var(--mc-font-title);
  font-size: 16px;
  font-weight: bold;
  color: var(--mc-gold);
}

.project-overview {
  font-size: 13px;
  line-height: 1.6;
  color: var(--mc-text-primary);
}

.mc-divider {
  height: 2px;
  background: var(--mc-border);
  margin: 12px 0;
}

.phase-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 500;
}

.phase-desc {
  font-size: 12px;
  color: var(--mc-text-secondary);
  margin-bottom: 8px;
}

.tasks-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.task-item {
  padding: 8px;
  background: rgba(0,0,0,0.15);
  border: 2px solid var(--mc-border);
}

.task-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.task-desc {
  font-size: 13px;
  font-weight: 500;
}

.task-deps {
  font-size: 11px;
  color: var(--mc-text-dim);
  margin-bottom: 6px;
  display: flex;
  align-items: center;
  gap: 4px;
}

.command-blocks-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.block-item {
  padding: 6px 8px;
  background: rgba(0,0,0,0.1);
  border: 1px solid var(--mc-border);
}

.block-tags {
  display: flex;
  gap: 4px;
  align-items: center;
}

.block-command {
  display: block;
  font-family: var(--mc-font-mono);
  font-size: 12px;
  color: var(--mc-text-primary);
  margin-top: 4px;
  padding: 4px 6px;
  background: var(--mc-bg-deep);
  word-break: break-all;
}

.block-comment {
  font-size: 11px;
  color: var(--mc-text-dim);
  margin-top: 2px;
}
</style>
