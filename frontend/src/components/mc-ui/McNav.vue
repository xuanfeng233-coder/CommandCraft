<script setup lang="ts">
</script>

<template>
  <nav class="mc-nav mc-tex-stone">
    <slot />
  </nav>
</template>

<style scoped>
.mc-nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  border-bottom: 2px solid var(--mc-border);
  position: relative;
  color: var(--mc-text-primary);
  min-height: 48px;
}

/* Grass strip on bottom */
.mc-nav::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: -4px;
  height: 4px;
  background-image: url('/textures/grass_block_top.png');
  background-size: 64px 64px;
  background-repeat: repeat;
  z-index: 1;
}
</style>
