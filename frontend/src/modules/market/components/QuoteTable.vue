<script setup lang="ts">
import { RouterLink } from 'vue-router'
import { marketStateLabels, type QuoteDTO } from '../types'
defineProps<{ quotes: QuoteDTO[]; emptyText?: string }>()
function statusLabel(quote: QuoteDTO) {
  if (quote.quality_status === 'MARKET_CLOSED') return '休市报价'
  if (quote.quality_status === 'STALE') return quote.error ? `数据滞后 · 上次请求失败：${quote.error.message}（${quote.error.code}）` : '数据滞后'
  if (quote.quality_status === 'UNAVAILABLE' || quote.quality_status === 'INVALID') return quote.error?.message || '报价不可用'
  return '时效未知'
}
function time(value?: string | null) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : `${date.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })} GMT+8`
}
function sourceTime(quote: QuoteDTO) {
  const raw = quote.source_time_raw
  if (quote.market_timestamp) return time(quote.market_timestamp)
  if (!raw) return '源端时间未知'
  const compact = raw.match(/^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})$/)
  return `${compact ? `${compact[1]}/${compact[2]}/${compact[3]} ${compact[4]}:${compact[5]}:${compact[6]}` : raw}（源端原始时间，时区未经确认）`
}
</script>
<template>
  <div class="table-scroll market-table-scroll"><table class="data-table market-table"><thead><tr><th>证券</th><th>最新价</th><th>涨跌</th><th>涨跌幅</th><th>状态</th><th>报价来源 / 时间</th><th>采集时间</th></tr></thead><tbody><tr v-for="item in quotes" :key="item.symbol"><td><strong>{{ item.symbol }}</strong><small>{{ item.name || '—' }} · {{ item.currency }}</small><RouterLink :to="{ path: '/market/history', query: { symbol: item.symbol } }">历史K线</RouterLink></td><td class="price-cell">{{ item.price ?? '—' }}</td><td :class="item.change == null ? '' : Number(item.change) > 0 ? 'price-up' : Number(item.change) < 0 ? 'price-down' : ''">{{ item.change ?? '—' }}</td><td :class="item.change_percent == null ? '' : Number(item.change_percent) > 0 ? 'price-up' : Number(item.change_percent) < 0 ? 'price-down' : ''">{{ item.change_percent == null ? '—' : `${item.change_percent}%` }}</td><td><span :title="[item.market_state_reason, item.market_state_basis].filter(Boolean).join(' · ')">{{ marketStateLabels[item.market_state || 'UNKNOWN'] }}</span><small>{{ statusLabel(item) }}</small><small v-if="item.delay_status === 'UNKNOWN'">延迟状态未知</small></td><td>{{ item.source }}<small>{{ sourceTime(item) }}</small></td><td>{{ time(item.received_at) }}</td></tr></tbody></table></div>
  <p v-if="!quotes.length" class="small-empty">{{ emptyText || '暂无可显示的报价。' }}</p>
</template>
<style scoped>
.price-up { color: #d03050; }
.price-down { color: #16804a; }
</style>
