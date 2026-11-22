<script setup lang="ts">
import { NConfigProvider, zhCN, dateZhCN } from 'naive-ui'
import WorkspaceLayout from './layouts/WorkspaceLayout.vue'
const themeOverrides = {
  common: { primaryColor: '#2563eb', primaryColorHover: '#1d4ed8', borderRadius: '8px', fontFamily: 'Inter, "Segoe UI", "Microsoft YaHei", sans-serif' },
}
</script>

<template>
  <NConfigProvider :locale="zhCN" :date-locale="dateZhCN" :theme-overrides="themeOverrides">
    <WorkspaceLayout />
  </NConfigProvider>
</template>
