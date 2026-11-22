<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { getCalendarStatuses } from '../api'
import { errorMessage } from '../../../shared/api/client'
import { marketStateLabels, type MarketCalendarStatus } from '../types'

const exchanges = [
  { exchange: 'SSE', name: '上交所', market: 'CN股票 / A股' },
  { exchange: 'SZSE', name: '深交所', market: 'CN股票 / A股' },
  { exchange: 'BSE', name: '北交所', market: 'CN股票 / A股' },
  { exchange: 'HKEX', name: '港交所', market: '中国香港' },
  { exchange: 'NYSE', name: '纽交所', market: '美股' },
  { exchange: 'NASDAQ', name: '纳斯达克', market: '美股' },
  { exchange: 'AMEX', name: '美交所', market: '美股' },
]
const statuses = ref<MarketCalendarStatus[]>([]), checkedAt = ref(''), error = ref(''), loading = ref(false)
const cards = computed(() => exchanges.map(exchange => ({ ...exchange, status: statuses.value.find(status => status.exchange === exchange.exchange) })))
let active = true
let controller: AbortController | undefined
let timer: ReturnType<typeof setInterval> | undefined
function time(value?: string | null) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '时间未知' : `${date.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })} GMT+8`
}
async function refresh() {
  if (!active || controller) return
  const request = new AbortController()
  controller = request; loading.value = true
  try {
    const result = await getCalendarStatuses({ signal: request.signal })
    if (!active || request.signal.aborted) return
    statuses.value = result.statuses; checkedAt.value = result.checked_at; error.value = ''
  } catch (cause) {
    if (!active || request.signal.aborted) return
    statuses.value = []; checkedAt.value = ''; error.value = `交易日历读取失败：${errorMessage(cause)}`
  } finally {
    if (controller === request) controller = undefined
    if (active) loading.value = false
  }
}
onMounted(() => { void refresh(); timer = setInterval(() => { void refresh() }, 30_000) })
onBeforeUnmount(() => { active = false; clearInterval(timer); controller?.abort() })
</script>
<template>
  <section class="panel business-panel calendar-panel" aria-labelledby="calendar-heading" :aria-busy="loading">
    <div class="calendar-heading"><h2 id="calendar-heading">市场交易日历</h2><span class="muted">每 30 秒更新 · 检查时间 {{ time(checkedAt) }}</span></div>
    <p class="calendar-scope">仅覆盖 2026 年常规股票交易；集合竞价、盘前盘后交易与个股停牌不在覆盖范围内。所有下次开市 / 午后复市时间均以 GMT+8 显示。</p>
    <p v-if="error" class="calendar-error" role="alert">{{ error }}</p>
    <div class="calendar-grid">
      <article v-for="card in cards" :key="card.exchange" class="calendar-card" :data-state="card.status?.state || 'UNKNOWN'">
        <div class="calendar-card-heading"><strong>{{ card.name }} <small>{{ card.exchange }}</small></strong><span class="calendar-market">{{ card.market }}</span></div>
        <div class="calendar-state">{{ marketStateLabels[card.status?.state || 'UNKNOWN'] }}<span v-if="card.status?.is_early_close" class="calendar-early">早收日</span></div>
        <p class="calendar-next">下次开市 / 午后复市<br>{{ time(card.status?.next_open) }}</p>
        <details v-if="card.status" class="calendar-details">
          <summary>日历依据与详情</summary>
          <p>原因：{{ card.status.reason || '未提供' }}</p>
          <p>依据：{{ card.status.basis }}</p>
          <p>来源：{{ card.status.calendar_name || '未知' }} · {{ card.status.calendar_version || '版本未知' }}</p>
          <p>覆盖：{{ card.status.coverage_start || '未知' }} 至 {{ card.status.coverage_end || '未知' }}</p>
          <p>交易所时区：{{ card.status.timezone }} · 交易日：{{ card.status.session_date || '—' }}</p>
          <p>常规开市：{{ time(card.status.session_open) }}；午休：{{ time(card.status.break_start) }} 至 {{ time(card.status.break_end) }}</p>
          <p>常规收市：{{ time(card.status.session_close) }}；下次收市：{{ time(card.status.next_close) }}</p>
          <p v-for="warning in card.status.warnings" :key="warning">提示：{{ warning }}</p>
        </details>
      </article>
    </div>
  </section>
</template>
