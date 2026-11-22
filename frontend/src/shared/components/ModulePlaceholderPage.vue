<script setup lang="ts">
import { NButton, NIcon } from 'naive-ui'
import { ArrowLeft, LockKeyhole, Check } from 'lucide-vue-next'
import type { WorkspaceModule } from '../../app/router/modules'
defineProps<{ module: WorkspaceModule }>()
</script>

<template>
  <div class="placeholder-page">
    <section class="page-heading"><div><div class="eyebrow">{{ module.english.toUpperCase() }}</div><h1>{{ module.label }}<span class="heading-tag">待启用</span></h1><p>{{ module.description }}</p></div></section>
    <section class="panel placeholder-panel"><span class="placeholder-icon"><NIcon :component="module.icon" size="40" /></span><span class="placeholder-phase"><NIcon :component="LockKeyhole" size="13" /> 尚未启用</span><h2>{{ module.label }}正在规划中</h2><p>当前处于阶段 0，已完成工作台基础结构。<br>相关服务与数据接入后，将逐步开放以下能力。</p><div class="scope-list"><div v-for="scope in module.scope" :key="scope"><NIcon :component="Check" size="15" />{{ scope }}<span>规划范围</span></div></div><RouterLink to="/"><NButton><template #icon><NIcon :component="ArrowLeft" /></template>返回系统概览</NButton></RouterLink></section>
  </div>
</template>
