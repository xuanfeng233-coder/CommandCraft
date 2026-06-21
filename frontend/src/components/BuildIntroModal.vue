<script setup lang="ts">
import { McModal, McButton } from '@/components/mc-ui'

defineProps<{
  show: boolean
}>()

const emit = defineEmits<{
  'update:show': [value: boolean]
  confirm: []
}>()

function handleConfirm() {
  localStorage.setItem('build-intro-seen', '1')
  emit('update:show', false)
  emit('confirm')
}
</script>

<template>
  <McModal :show="show" @update:show="emit('update:show', $event)">
    <div class="build-intro">
      <h3 class="build-intro-title">构建模式</h3>
      <div class="build-intro-content">
        <p class="build-intro-desc">
          构建模式专为大型命令方块项目设计，AI 将分步规划、逐步执行、自动审查。
        </p>

        <div class="build-intro-steps">
          <div class="intro-step">
            <span class="intro-step-num">1</span>
            <div>
              <strong>规划阶段</strong>
              <p>AI 分析需求，搜索资料，生成结构化方案</p>
            </div>
          </div>
          <div class="intro-step">
            <span class="intro-step-num">2</span>
            <div>
              <strong>审查阶段</strong>
              <p>你可以在编辑器中修改方案，确认后开始执行</p>
            </div>
          </div>
          <div class="intro-step">
            <span class="intro-step-num">3</span>
            <div>
              <strong>执行阶段</strong>
              <p>AI 逐步执行每个步骤，自动审查完成度</p>
            </div>
          </div>
        </div>

        <p class="build-intro-note">
          构建模式使用 DeepSeek 深度推理模型，仅限 Pro/Ultra 订阅用户使用。
        </p>
      </div>

      <div class="build-intro-actions">
        <McButton @click="emit('update:show', false)">取消</McButton>
        <McButton variant="primary" @click="handleConfirm">
          了解，开始构建
        </McButton>
      </div>
    </div>
  </McModal>
</template>

<style scoped>
.build-intro {
  width: 480px;
  max-width: 90vw;
  padding: 24px 28px;
}

.build-intro-title {
  font-family: var(--mc-font-title);
  color: var(--mc-gold);
  font-size: 18px;
  margin: 0 0 16px;
}

.build-intro-content {
  color: var(--mc-text-primary);
  font-size: 13px;
  line-height: 1.6;
}

.build-intro-desc {
  margin: 0 0 16px;
}

.build-intro-steps {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 16px;
}

.intro-step {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.intro-step-num {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  flex-shrink: 0;
  background: var(--mc-gold);
  color: var(--mc-bg-main);
  font-family: var(--mc-font-title);
  font-size: 13px;
  border-radius: 2px;
}

.intro-step strong {
  color: var(--mc-text-primary);
  font-size: 13px;
}

.intro-step p {
  color: var(--mc-text-dim);
  font-size: 12px;
  margin: 2px 0 0;
}

.build-intro-note {
  color: var(--mc-text-dim);
  font-size: 12px;
  margin: 0;
}

.build-intro-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  margin-top: 20px;
}
</style>
