<script setup lang="ts">
import { computed } from 'vue'
import { NAlert, NButton, NIcon, NSkeleton } from 'naive-ui'
import { Server, Database, Layers, Cpu, ArrowUpRight, Check, CircleDashed, ChartNoAxesCombined, Bell, Info, PlugZap } from 'lucide-vue-next'
import { useSystemStore } from '../stores/system'
import { ApiError } from '../../../shared/api/client'
import ServiceStatusCard from '../components/ServiceStatusCard.vue'
const system = useSystemStore()
const services = [
  { key: 'api', label: 'API 服务', subtitle: 'HTTP API', icon: Server },
  { key: 'mysql', label: 'MySQL', subtitle: '关系型数据库', icon: Database },
  { key: 'redis', label: 'Redis', subtitle: '缓存与任务队列', icon: Layers },
  { key: 'worker', label: 'Worker', subtitle: '后台任务执行器', icon: Cpu },
] as const
const foundations = computed(() => system.modules.filter(item => item.status === 'foundation'))
const planned = computed(() => system.modules.filter(item => item.status === 'planned'))
const checkedAt = computed(() => {
  if (!system.status?.checked_at) return '尚未检查'
  const date = new Date(system.status.checked_at)
  return Number.isNaN(date.getTime()) ? '检查时间不可用' : date.toLocaleString('zh-CN', { hour12: false })
})
const overall = computed(() => {
  if (system.error) return '服务连接异常'
  if (!system.status) return '等待系统检查'
  return { healthy: '基础服务运行正常', degraded: '部分依赖暂不可用', unhealthy: '系统当前不可用' }[system.status.status]
})
</script>

<template>
  <div class="overview-page">
    <section class="page-heading"><div><div class="eyebrow">SYSTEM OVERVIEW</div><h1>系统概览<span class="heading-tag">基础工程</span></h1><p>掌握服务健康状态，查看工作台能力接入进度。</p></div><span class="environment-tag"><span class="status-dot blue"></span> 本地工作空间</span></section>
    <section class="foundation-banner">
      <div class="banner-art" aria-hidden="true"><NIcon :component="PlugZap" size="30" /></div>
      <div><div class="banner-title">基础已就位，洞察从真实数据开始。<span>PHASE 0</span></div><p>当前为基础工程阶段。行情采集、指标计算与预警任务尚未启用，不展示模拟报价或投资表现。</p></div>
    </section>
    <NAlert v-if="system.error" type="error" title="无法获取系统状态" class="feedback-alert">
      {{ system.error.message }}<span v-if="system.error instanceof ApiError" class="request-id">请求 ID：{{ system.error.requestId }}</span>
      <div class="retry-action"><NButton size="small" :loading="system.loading" @click="system.refresh()">重新连接</NButton></div>
    </NAlert>
    <NAlert v-else-if="system.status && system.status.status !== 'healthy'" type="warning" title="依赖服务降级" class="feedback-alert">API 仍可响应。请查看下方依赖检查结果；相关能力需在服务恢复后启用。</NAlert>
    <section aria-labelledby="service-title">
      <div class="section-heading"><h2 id="service-title">服务健康状态 <span class="section-count">04</span></h2><span class="check-time">最近检查：{{ checkedAt }}</span></div>
      <div class="health-summary"><span class="status-dot" :class="!system.status || system.error ? 'gray' : system.status.status === 'healthy' ? 'green' : 'amber'"></span>{{ overall }}<span v-if="system.loading" class="muted"> · 正在刷新</span></div>
      <div class="service-grid"><ServiceStatusCard v-for="service in services" :key="service.key" :label="service.label" :subtitle="service.subtitle" :icon="service.icon" :component="system.status?.components[service.key]" :stale="!!system.error" /></div>
    </section>
    <div class="overview-columns">
      <section class="panel module-panel" aria-labelledby="modules-title">
        <div class="panel-heading"><div><h2 id="modules-title">功能模块</h2><p>从基础能力逐步扩展工作空间</p></div><span class="panel-counter">{{ system.modules.length.toString().padStart(2, '0') }}</span></div>
        <NAlert v-if="system.modulesError" type="warning" title="模块目录暂不可用">{{ system.modulesError.message }}<span v-if="system.modules.length"> · 下方保留上次成功获取的目录</span></NAlert>
        <div v-if="system.loading && !system.modules.length" class="module-skeleton"><NSkeleton text :repeat="5" /></div>
        <div v-else-if="!system.modules.length" class="small-empty"><NIcon :component="Layers" size="28" /><strong>等待模块目录</strong><p>连接 API 后显示服务端的实际模块配置。</p></div>
        <template v-else>
          <div class="module-group-label">已接入基础能力 <span>{{ foundations.length }}</span></div>
          <div v-for="item in foundations" :key="item.name" class="module-row"><span class="module-symbol enabled"><NIcon :component="Check" size="15" /></span><div><strong>{{ item.label }}</strong><p>{{ item.description }}</p></div><span class="module-tag enabled">基础已接入</span></div>
          <div v-if="!foundations.length" class="module-none">暂无已接入基础能力</div>
          <div class="module-group-label planned-label">待启用模块 <span>{{ planned.length }}</span></div>
          <div v-for="item in planned" :key="item.name" class="module-row"><span class="module-symbol"><NIcon :component="CircleDashed" size="15" /></span><div><strong>{{ item.label }}</strong><p>{{ item.description }}</p></div><span class="module-tag">待启用 · {{ item.tier }}</span></div>
        </template>
      </section>
      <div class="right-column">
        <section class="panel data-panel"><div class="panel-heading"><div><h2>行情数据</h2><p>数据连接与采集状态</p></div><span class="module-tag">未启用</span></div><div class="data-empty"><span class="empty-illustration"><NIcon :component="ChartNoAxesCombined" size="33" /></span><h3>尚未接入行情数据</h3><p>行情采集任务启用后，<br>这里将展示真实的数据接入状态。</p><NButton disabled>查看行情看板<template #icon><NIcon :component="ArrowUpRight" /></template></NButton></div><div class="panel-note"><NIcon :component="Info" size="14" /> 当前无行情采集任务运行</div></section>
        <section class="panel alert-panel"><span class="alert-icon"><NIcon :component="Bell" size="23" /></span><div><h3>预警尚未启用</h3><p>依赖行情与指标能力，当前不会触发或发送通知。</p><NButton text disabled>管理预警规则 <NIcon :component="ArrowUpRight" size="14" /></NButton></div></section>
        <section v-if="system.status?.tasks.length" class="task-note"><span class="eyebrow">后台任务</span><div v-for="task in system.status.tasks" :key="task.name"><strong>{{ task.name }}</strong><span>未启用</span><p>{{ task.detail }}</p></div></section>
      </div>
    </div>
  </div>
</template>
