<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { NButton, NIcon } from 'naive-ui'
import { Radar, RefreshCw, ChevronRight, ArrowUpRight } from 'lucide-vue-next'
import { workspaceModules } from '../router/modules'
import { useSystemStore } from '../../modules/system/stores/system'
import { TokenGate, useAuthStore } from '../../modules/auth'
const auth = useAuthStore()
const route = useRoute()
const system = useSystemStore()
onMounted(() => { void system.refresh() })
onUnmounted(() => system.cancel())
</script>

<template>
  <div class="workspace">
    <aside class="sidebar">
      <RouterLink to="/" class="brand" aria-label="TickRadar 首页">
        <span class="brand-mark"><NIcon :component="Radar" size="24" /></span>
        <span>TickRadar<small>让每一次变化，都有迹可循</small></span>
      </RouterLink>
      <div class="nav-caption">工作空间 <span>WORKSPACE</span></div>
      <nav class="navigation" aria-label="主要导航">
        <RouterLink v-for="module in workspaceModules" :key="module.key" :to="module.path" class="nav-item" :class="{ active: route.path === module.path }" :aria-current="route.path === module.path ? 'page' : undefined">
          <NIcon :component="module.icon" size="19" />
          <span>{{ module.label }}</span><span v-if="!module.enabled" class="nav-dot" aria-label="未启用"></span>
        </RouterLink>
      </nav>
      <div class="sidebar-bottom">
        <div class="phase-label"><span class="status-dot blue"></span> 市场观察</div>
        <p>仅展示接口返回的公共报价。</p>
        <div class="build-version">{{ system.status?.version || '版本待连接' }} <span>OBSERVATION</span></div>
      </div>
    </aside>
    <div class="main-shell">
      <header class="topbar">
        <div class="breadcrumb"><span>工作空间</span><NIcon :component="ChevronRight" size="14" /><strong>{{ route.meta.title }}</strong></div>
        <div class="topbar-actions">
          <NButton v-if="auth.authenticated" size="small" @click="auth.logout()">退出访问</NButton>
          <span class="connection"><span class="status-dot" :class="system.loading ? 'amber' : system.connected ? 'green' : 'gray'"></span>{{ system.loading ? '正在检查' : system.connected ? 'API 已连接' : 'API 未连接' }}</span>
          <NButton size="small" :loading="system.loading" :disabled="system.loading" @click="system.refresh()"><template #icon><NIcon :component="RefreshCw" /></template>刷新状态</NButton>
        </div>
      </header>
      <main id="main-content" class="main-content"><TokenGate v-if="route.meta.private"><RouterView /></TokenGate><RouterView v-else /></main>
      <footer class="workspace-footer"><span>TickRadar <span class="footer-divider">/</span> 市场观察工作台</span><span>报价时效未知 · 预警未启用 <NIcon :component="ArrowUpRight" size="12" /></span></footer>
    </div>
  </div>
</template>
