<script setup lang="ts">
defineProps<{
  title?: string
}>()
</script>

<template>
  <div class="mc-card mc-tex-oak">
    <div v-if="title || $slots.header || $slots['header-extra']" class="mc-card-header">
      <div class="mc-card-header-left">
        <slot name="header">
          <span class="mc-card-title">{{ title }}</span>
        </slot>
      </div>
      <div v-if="$slots['header-extra']" class="mc-card-header-right">
        <slot name="header-extra" />
      </div>
    </div>
    <div class="mc-card-body">
      <slot />
    </div>
    <div v-if="$slots.action" class="mc-card-action">
      <slot name="action" />
    </div>
  </div>
</template>

<style scoped>
.mc-card {
  border: 2px solid var(--mc-border);
  box-shadow: var(--mc-shadow-raised);
  color: var(--mc-text-primary);
}

.mc-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border-bottom: 2px solid var(--mc-border);
  background-color: rgba(0,0,0,0.15);
}

.mc-card-header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.mc-card-header-right {
  flex-shrink: 0;
}

.mc-card-title {
  font-family: var(--mc-font-title);
  font-size: 14px;
  font-weight: bold;
}

.mc-card-body {
  padding: 12px;
}

.mc-card-action {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 8px 12px;
  border-top: 2px solid var(--mc-border);
  background-color: rgba(0,0,0,0.1);
}
</style>
