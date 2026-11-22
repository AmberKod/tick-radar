<script setup lang="ts">
import type { Component } from 'vue'
import { NIcon } from 'naive-ui'
import type { SystemComponent } from '../types'
defineProps<{ label: string; subtitle: string; icon: Component; component?: SystemComponent; stale?: boolean }>()
const labels = { healthy: '运行正常', unhealthy: '不可用', stale: '心跳过期', unknown: '状态未知' }
</script>

<template>
  <article class="service-card">
    <div class="service-card-heading"><span class="service-icon"><NIcon :component="icon" size="21" /></span><span class="service-state" :class="stale ? 'unknown' : component?.status || 'unknown'"><span class="status-dot"></span>{{ stale ? '待重新检查' : component ? labels[component.status] : '等待检查' }}</span></div>
    <h3>{{ label }}</h3><p class="service-subtitle">{{ subtitle }}</p>
    <div class="service-detail">{{ stale ? '上次结果已保留，当前连接不可用' : component?.detail || (component?.status === 'healthy' ? '服务检查已通过' : '连接后显示真实运行状态') }}</div>
  </article>
</template>
