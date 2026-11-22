<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NAlert, NButton, NInput, NSelect } from 'naive-ui'
import { getHistory } from '../api'
import { ApiError } from '../../../shared/api/client'
import type { HistoryAdjustment, HistoryResponse } from '../types'
import HistoryChart from '../components/HistoryChart.vue'
const route = useRoute(), router = useRouter()
const symbol = ref(''), limit = ref(120), adjustment = ref<HistoryAdjustment>('raw')
const result = ref<HistoryResponse | null>(null), error = ref(''), loading = ref(false)
let revision = 0, controller: AbortController | undefined
const limits = [60, 120, 250, 640].map(value => ({ label: `${value} 根`, value }))
const adjustments = [{ label: '不复权', value: 'raw' }, { label: '前复权', value: 'qfq' }, { label: '后复权', value: 'hfq' }]
const adjustmentLabels = { raw: '不复权', qfq: '前复权', hfq: '后复权' }
async function load(value: string) {
  const current = ++revision
  controller?.abort(); controller = new AbortController()
  result.value = null; error.value = ''; loading.value = false
  symbol.value = value.trim().toUpperCase()
  if (!symbol.value) return
  if (!/^(CN:\d{6}|HK:\d{5}|US:[A-Z][A-Z0-9.-]*)$/.test(symbol.value)) { error.value = '请输入标准证券代码，例如 CN:600519、HK:00700 或 US:AAPL。'; return }
  loading.value = true
  try {
    const data = await getHistory(symbol.value, limit.value, adjustment.value, { signal: controller.signal })
    if (current !== revision) return
    const valid = data.bars.every(bar => /^\d{4}-\d{2}-\d{2}$/.test(bar.date) && [bar.open, bar.high, bar.low, bar.close].every(value => value.trim() !== '' && Number.isFinite(Number(value)) && Number(value) > 0) && bar.volume.trim() !== '' && Number.isFinite(Number(bar.volume)) && Number(bar.volume) >= 0)
    const ordered = data.bars.every((bar, index) => index === 0 || bar.date > data.bars[index - 1]!.date)
    if (!valid || !ordered) throw new Error('历史数据格式异常，无法绘制日线，请稍后重试。')
    result.value = data
  } catch (cause) {
    if (current !== revision) return
    error.value = cause instanceof ApiError ? `${cause.message}（${cause.code}；请求 ID：${cause.requestId}）` : cause instanceof Error ? cause.message : '历史日线读取失败，请稍后重试。'
  } finally { if (current === revision) loading.value = false }
}
async function lookup(value = symbol.value) {
  const next = value.trim().toUpperCase()
  if (route.query.symbol !== next) await router.push({ path: '/market/history', query: next ? { symbol: next } : {} })
  else await load(next)
}
watch(() => route.query.symbol, value => { void load(typeof value === 'string' ? value : '') }, { immediate: true })
onBeforeUnmount(() => { ++revision; controller?.abort() })
function time(value: string) {
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : `${parsed.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })} GMT+8`
}
</script>
<template>
  <div class="business-page history-page">
    <section class="page-heading"><div><div class="eyebrow">MARKET HISTORY</div><h1>历史日线</h1><p>公共历史数据，只读观察；历史数据不是实时行情。休市期间仍可查询。</p></div></section>
    <section class="panel business-panel">
      <form class="toolbar history-form" @submit.prevent="lookup()">
        <NInput v-model:value="symbol" placeholder="CN:600519、HK:00700、US:AAPL" aria-label="历史证券代码" />
        <NSelect v-model:value="limit" :options="limits" aria-label="历史根数" />
        <NSelect v-model:value="adjustment" :options="adjustments" aria-label="复权方式" />
        <NButton type="primary" attr-type="submit" :loading="loading" :disabled="!symbol.trim()">查询历史日线</NButton>
      </form>
      <div class="sample-actions"><span>示例代码</span><NButton v-for="sample in ['CN:600519', 'HK:00700', 'US:AAPL']" :key="sample" text @click="lookup(sample)">{{ sample }}</NButton></div>
      <p class="muted">周期：日线 · 排除交易所当地日期为今天的 Bar · 成交量保留原始口径 · 美股暂不支持后复权</p>
    </section>
    <NAlert v-if="error" type="error" title="历史日线读取失败" role="alert">{{ error }}</NAlert>
    <p v-if="loading" class="small-empty" role="status">正在读取历史日线…</p>
    <section v-if="result" class="panel business-panel">
      <h2>{{ result.symbol }} · 历史日线</h2>
      <div class="history-meta"><span>历史截至 {{ result.latest_date || '暂无日期' }}</span><span>实际 {{ result.actual_count }} 根 / 请求 {{ result.requested_limit }} 根</span><span>来源 {{ result.source }}</span><span>{{ adjustmentLabels[result.adjustment] }} · {{ result.market }} · {{ result.currency }}</span><span>采集时间 {{ time(result.checked_at) }}</span><span>数据截至 {{ result.data_as_of || '暂无日期' }}</span></div>
      <NAlert v-if="!result.history_complete || result.actual_count < result.requested_limit" type="warning">历史覆盖不足：{{ result.coverage_reason || '数据源返回的历史根数少于请求根数。' }}</NAlert>
      <details class="history-source-details"><summary>数据来源与口径说明</summary><p v-for="warning in result.warnings || []" :key="warning">{{ warning }}</p></details>
      <HistoryChart v-if="result.bars.length" :key="`${result.symbol}-${result.adjustment}-${result.requested_limit}-${result.checked_at}`" :bars="result.bars" />
      <p v-else class="small-empty">暂无可用历史日线，请更换标的或稍后重试。</p>
      <p class="muted">仅用于观察。历史数据不是实时行情，不拼接当前报价。</p>
    </section>
    <p v-else-if="!loading && !error" class="small-empty">输入标准证券代码或点击示例，查询历史日线。</p>
  </div>
</template>
<style scoped>
.history-form { display: grid; grid-template-columns: minmax(220px, 1fr) 120px 140px auto; }
.history-meta { display: flex; flex-wrap: wrap; gap: 10px 24px; margin: 16px 0; color: #596579; font-size: 13px; }
.history-source-details { margin: 12px 0 18px; color: #596579; font-size: 12px; line-height: 1.8; }
.history-source-details summary { cursor: pointer; }
.history-source-details p { margin: 6px 0; }
@media (max-width: 760px) { .history-form { grid-template-columns: 1fr 1fr; } .history-form > :first-child { grid-column: 1 / -1; } }
</style>
