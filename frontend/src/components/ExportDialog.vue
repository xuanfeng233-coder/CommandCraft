<script setup lang="ts">
import { ref, computed } from 'vue'
import { McModal, McCard, McButton, McInput, McRadioGroup, McRadio } from '@/components/mc-ui'
import { toast } from '@/composables/useToast'
import { exportMcfunction, exportMcstructure } from '@/api/chat'
import type { CommandOutput, ProjectResult } from '@/types'

const props = defineProps<{
  show: boolean
  command?: CommandOutput
  project?: ProjectResult
}>()

const emit = defineEmits<{
  (e: 'update:show', val: boolean): void
}>()

const filename = ref('output')
const format = ref<'mcfunction' | 'mcstructure'>('mcfunction')
const exporting = ref(false)

const canExportStructure = computed(() => {
  return props.project && props.project.layout && props.project.layout.length > 0
})

function downloadBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

async function handleExport() {
  exporting.value = true
  try {
    const fname = filename.value.trim() || 'output'
    if (format.value === 'mcfunction') {
      const blob = await exportMcfunction(
        props.project ? (props.project as unknown as Record<string, unknown>) : undefined,
        props.command?.command,
        props.command?.explanation,
        fname,
      )
      downloadBlob(blob, `${fname}.mcfunction`)
    } else {
      if (!props.project) {
        toast.warning('.mcstructure 导出需要项目数据')
        return
      }
      const blob = await exportMcstructure(
        props.project as unknown as Record<string, unknown>,
        fname,
      )
      downloadBlob(blob, `${fname}.mcstructure`)
    }
    toast.success('导出成功')
    emit('update:show', false)
  } catch (err: unknown) {
    const errMsg = err instanceof Error ? err.message : '导出失败'
    toast.error(errMsg)
  } finally {
    exporting.value = false
  }
}
</script>

<template>
  <McModal :show="show" @update:show="emit('update:show', $event)">
    <McCard title="导出" style="width: 400px">
      <div class="export-form">
        <div class="field">
          <div class="label">文件名</div>
          <McInput v-model:model-value="filename" placeholder="output" />
        </div>

        <div class="field">
          <div class="label">格式</div>
          <McRadioGroup v-model:model-value="format">
            <McRadio value="mcfunction">.mcfunction</McRadio>
            <McRadio value="mcstructure" :disabled="!canExportStructure">
              .mcstructure
            </McRadio>
          </McRadioGroup>
          <div v-if="!canExportStructure" class="hint">
            .mcstructure 仅在有命令方块布局时可用
          </div>
        </div>
      </div>

      <template #action>
        <McButton @click="emit('update:show', false)">取消</McButton>
        <McButton
          variant="primary"
          :loading="exporting"
          @click="handleExport"
        >
          导出
        </McButton>
      </template>
    </McCard>
  </McModal>
</template>

<style scoped>
.export-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.label {
  font-size: 13px;
  color: var(--mc-text-secondary);
  margin-bottom: 6px;
}

.hint {
  font-size: 12px;
  color: var(--mc-text-dim);
  margin-top: 4px;
}
</style>
