<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { NAlert, NButton, NInput, NModal, NSelect, NTabs, NTab } from 'naive-ui'
import { useAuthStore } from '../../auth'
import TokenPrompt from '../components/TokenPrompt.vue'
import { useMarketStore } from '../stores/market'
import QuoteTable from '../components/QuoteTable.vue'
import CalendarStatusPanel from '../components/CalendarStatusPanel.vue'
import * as api from '../api'
import { errorMessage } from '../../../shared/api/client'
import type { Market, SecurityFromQuoteInput } from '../types'
const store = useMarketStore(), auth = useAuthStore()
const market = ref<Market | 'ALL'>('ALL'), symbol = ref(''), groupName = ref(''), groupChoice = ref(''), exchange = ref<NonNullable<SecurityFromQuoteInput['exchange']> | ''>(''), securityType = ref<SecurityFromQuoteInput['security_type']>('STOCK')
const gateOpen = ref(false), adding = ref(false), creating = ref(false), actionError = ref('')
let mounted = true
const quoteUsable = computed(() => !!store.quote?.name && store.quote.price != null && !store.quote.error && !['INVALID', 'UNAVAILABLE'].includes(store.quote.quality_status))
const exchanges: Record<Market, string[]> = { CN: ['SSE', 'SZSE', 'BSE'], HK: ['HKEX'], US: ['NASDAQ', 'NYSE', 'AMEX'] }
const currentMarket = computed<Market | null>(() => store.quote?.market || null)
const exchangeOptions = computed(() => currentMarket.value ? exchanges[currentMarket.value].map(value => ({ label: value, value })) : [])
const groupOptions = computed(() => store.groups.map(group => ({ label: group.name, value: group.id })))
const filteredQuotes = computed(() => store.visibleQuotes(market.value))
const checkedAtLabel = computed(() => {
  if (!store.checkedAt) return '—'
  const date = new Date(store.checkedAt)
  return Number.isNaN(date.getTime()) ? '时间未知' : `${date.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })} GMT+8`
})
const canAdd = computed(() => auth.authenticated && quoteUsable.value && !!groupChoice.value && !adding.value && !creating.value)
async function lookup(value = symbol.value) { if (!value.trim()) return; symbol.value = value; await store.lookup(value) }
function initializeAdd() {
  groupChoice.value = store.groupId || store.groups[0]?.id || ''
  const code = store.quote?.symbol.split(':')[1] || ''
  exchange.value = currentMarket.value === 'HK' ? 'HKEX' : currentMarket.value === 'CN' ? (/^(4|8|92)/.test(code) ? 'BSE' : /^[65]/.test(code) ? 'SSE' : /^(0|3|15)/.test(code) ? 'SZSE' : '') : ''
  securityType.value = currentMarket.value === 'CN' && /^(5|15)/.test(code) ? 'ETF' : 'STOCK'
  actionError.value = ''
}
async function openAdd() {
  if (!quoteUsable.value) return
  initializeAdd(); gateOpen.value = true
  if (auth.authenticated && !store.groups.length) {
    const epoch = auth.epoch
    await store.loadGroups()
    if (mounted && auth.authenticated && epoch === auth.epoch) initializeAdd()
  }
}
async function createGroup() {
  if (!auth.authenticated || !quoteUsable.value || !groupName.value.trim() || creating.value || adding.value) return
  const epoch = auth.epoch
  const current = () => mounted && auth.authenticated && epoch === auth.epoch
  creating.value = true; actionError.value = ''
  try {
    const group = await api.createGroup(groupName.value.trim())
    if (!current()) return
    groupName.value = ''; await store.loadGroups()
    if (current()) { groupChoice.value = group.id; store.groupId = group.id }
  } catch (cause) { if (current()) actionError.value = `创建分组失败：${errorMessage(cause)}` }
  finally { if (current()) creating.value = false }
}
async function addToWatchlist() {
  if (!store.quote || !canAdd.value) return
  if (!exchange.value) { actionError.value = '请选择证券交易所，美股交易所需要手动确认。'; return }
  const epoch = auth.epoch, selected = groupChoice.value, selectedQuote = store.quote
  const current = () => mounted && auth.authenticated && epoch === auth.epoch
  adding.value = true; actionError.value = ''; store.actionMessage = ''
  let registered = false
  try {
    const body: SecurityFromQuoteInput = { symbol: selectedQuote.symbol, exchange: exchange.value, security_type: securityType.value }
    const security = await api.createSecurityFromQuote(body)
    registered = true
    if (!current()) return
    await api.addItem(selected, security.id)
    if (!current()) return
    gateOpen.value = false
    store.actionMessage = `${security.symbol} 已加入自选分组。`
    if (store.groupId === selected) await store.loadBoard()
    else store.groupId = selected
  } catch (cause) { if (current()) actionError.value = `${registered ? '证券已登记，但加入分组失败' : '证券登记失败'}：${errorMessage(cause)}` }
  finally { if (current()) adding.value = false }
}
watch(() => store.groupId, () => { if (auth.authenticated) void store.loadBoard() })
watch(() => auth.epoch, () => { adding.value = false; creating.value = false; actionError.value = '' }, { flush: 'sync' })
watch(() => auth.authenticated, async value => {
  if (!value) { store.clearPrivate(); return }
  const epoch = auth.epoch
  await store.loadGroups()
  if (!mounted || !auth.authenticated || epoch !== auth.epoch) return
  if (gateOpen.value && store.quote) initializeAdd()
  else if (gateOpen.value) gateOpen.value = false
}, { immediate: true })
onBeforeUnmount(() => { mounted = false; store.clear() })
</script>
<template>
  <div class="business-page market-page">
    <section class="page-heading"><div><div class="eyebrow">MARKET OBSERVATION</div><h1>市场观察</h1><p>公共报价只读查看；状态或时间未知时会明确标注，不作实时保证。</p></div><div class="toolbar market-actions"><NButton v-if="auth.authenticated && store.groupId" :loading="store.loading" @click="store.loadBoard()">刷新看板</NButton><NButton v-if="auth.authenticated && store.quotes.length" type="primary" @click="store.refresh()">主动刷新报价</NButton></div></section>
    <NAlert v-if="store.error" type="error">{{ store.error }}</NAlert><NAlert v-if="store.quoteError" type="error">自选报价读取失败，成员管理仍可继续：{{ store.quoteError }}</NAlert><NAlert v-if="store.actionMessage" type="success">{{ store.actionMessage }}</NAlert>
    <CalendarStatusPanel />
    <section class="panel business-panel market-lookup"><h2>查询报价</h2><NTabs v-model:value="market" type="segment" class="market-tabs" aria-label="自选市场筛选"><NTab name="ALL">全部市场</NTab><NTab name="CN">沪深京</NTab><NTab name="HK">港股</NTab><NTab name="US">美股</NTab></NTabs><form class="toolbar" @submit.prevent="lookup()"><NInput v-model:value="symbol" placeholder="标准代码，如 CN:600519、HK:00700、US:AAPL" aria-label="统一证券代码" /><NButton type="primary" attr-type="submit" :loading="store.loading" :disabled="store.loading || !symbol.trim()">查询报价</NButton></form><div class="sample-actions"><span>示例代码</span><NButton text @click="lookup('CN:600519')">CN:600519</NButton><NButton text @click="lookup('HK:00700')">HK:00700</NButton><NButton text @click="lookup('US:AAPL')">US:AAPL</NButton></div><NAlert v-if="store.error" type="error">{{ store.error }}</NAlert><section v-if="store.quote" class="quote-result"><div class="quote-summary"><div><strong>{{ store.quote.symbol }}</strong><span>{{ store.quote.name || '证券名称未知' }}</span></div><NButton type="primary" :disabled="!quoteUsable" @click="openAdd()">加入自选</NButton></div><QuoteTable :quotes="[store.quote]" /></section></section>
    <section v-if="auth.authenticated" class="panel business-panel"><div class="market-board-heading"><h2>自选行情看板</h2><NSelect v-model:value="store.groupId" :options="groupOptions" placeholder="选择自选分组" aria-label="自选分组" class="market-group-select" /></div><p class="muted">{{ store.connectionLabel }} · 最多展示所选分组前 50 个成员 · 本次检查 {{ checkedAtLabel }}</p><NAlert v-if="store.quoteError" type="error">报价读取失败：{{ store.quoteError }}</NAlert><QuoteTable :quotes="filteredQuotes" :empty-text="store.groupId ? '所选分组暂无证券或暂无报价。可在上方输入代码查询并加入自选。' : '暂无自选分组。验证 Token 后可创建分组并加入证券。'" /></section>
    <section v-else class="panel business-panel market-board-prompt"><h2>自选行情看板</h2><p>验证访问 Token 后，查看个人分组内的共享报价并添加自选。</p><NButton @click="gateOpen = true">验证 Token</NButton></section>
    <NModal v-model:show="gateOpen" preset="card" :title="auth.authenticated ? '加入自选' : '验证访问 Token'" class="editor-modal"><TokenPrompt><div v-if="store.quote" class="entry-form"><p>{{ store.quote.symbol }} · {{ store.quote.name || '名称未知' }}</p><NSelect v-model:value="groupChoice" :options="groupOptions" placeholder="选择分组" aria-label="选择自选分组" /><form class="toolbar" @submit.prevent="createGroup"><NInput v-model:value="groupName" placeholder="创建新分组" aria-label="新分组名称" /><NButton attr-type="submit" :loading="creating" :disabled="!auth.authenticated || !quoteUsable || !groupName.trim() || creating || adding">创建分组</NButton></form><NSelect v-if="currentMarket" v-model:value="exchange" :options="exchangeOptions" :placeholder="currentMarket === 'US' ? '请选择美股交易所' : '交易所'" aria-label="证券交易所" /><NSelect v-model:value="securityType" :options="['STOCK','ETF','ADR'].map(value => ({label:value,value}))" aria-label="证券类型" /><NAlert v-if="actionError" type="error">{{ actionError }}</NAlert><NButton type="primary" :loading="adding" :disabled="!canAdd" @click="addToWatchlist()">确认加入自选</NButton></div></TokenPrompt></NModal>
  </div>
</template>
