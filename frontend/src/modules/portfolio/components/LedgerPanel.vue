<script setup lang="ts">
import { ref, watch } from 'vue'
import type { PortfolioEntry, PortfolioEntryPage, PortfolioReversalCreate } from '../types'
import { kinds } from '../composables/entryDraft'
import { decimalLabel as number } from '../composables/format'
const props = defineProps<{ ledger: PortfolioEntryPage | null; busy: boolean; reverse: (id: string, body: PortfolioReversalCreate) => Promise<boolean> }>()
const emit = defineEmits<{ page: [value: number] }>()
const target = ref<PortfolioEntry | null>(null), reason = ref(''), confirmed = ref(false)
let requestId = crypto.randomUUID()
watch(reason, () => { requestId = crypto.randomUUID(); confirmed.value = false }, { flush: 'sync' })
function start(entry: PortfolioEntry) { target.value = entry; reason.value = ''; confirmed.value = false; requestId = crypto.randomUUID() }
async function save() { if (!target.value || !reason.value.trim() || !confirmed.value) return; if (await props.reverse(target.value.id, { request_id: requestId, reason: reason.value.trim() })) target.value = null }
const labels: Record<string, string> = { ...kinds, REVERSAL: '冲正', TRANSFER_OUT: '内部划出', TRANSFER_IN: '内部划入' }
const label = (kind: PortfolioEntry['kind']) => labels[kind] || kind
const time = (value: string) => new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })
</script>
<template>
  <section class="panel portfolio-panel">
    <h2>流水账本</h2><p class="muted">发生时间统一显示为北京时间。冲正保留原流水和审计记录。</p><div class="portfolio-scroll"><table><thead><tr><th>序号 / 时间</th><th>类型 / 证券</th><th>数量 / 成交价</th><th>金额 / 费用 / 税</th><th>现金变动</th><th>状态 / 操作</th></tr></thead><tbody><tr v-for="entry in ledger?.items" :key="entry.id"><td>#{{ entry.sequence }}<small>{{ time(entry.occurred_at) }}</small></td><td>{{ label(entry.kind) }}<small>{{ entry.symbol }} {{ entry.security_name }}</small><small>{{ entry.note }}</small></td><td>{{ number(entry.quantity) }}<small>{{ number(entry.price) }}</small></td><td>{{ number(entry.gross_amount) }}<small>费 {{ number(entry.fee) }} / 税 {{ number(entry.tax) }}</small></td><td>{{ number(entry.cash_delta) }} {{ entry.currency }}</td><td>{{ entry.status === 'REVERSED' ? '已作废' : '有效' }}<small v-if="entry.reversal_of_id">原流水 {{ entry.reversal_of_id }}</small><small v-if="entry.transfer_id">关联内部划转，请到内部划转与换汇整体作废<small>划转 {{ entry.transfer_id }}</small></small><button v-if="entry.status === 'ACTIVE' && entry.kind !== 'REVERSAL' && !entry.transfer_id" :disabled="busy" @click="start(entry)">作废并重算/冲正</button></td></tr></tbody></table></div>
    <p v-if="!ledger?.items.length" class="small-empty">暂无流水。请先录入入金，再记录实际交易。</p>
    <div v-if="ledger && ledger.total > 20" class="toolbar"><button :disabled="busy || ledger.page <= 1" @click="emit('page', ledger.page - 1)">上一页</button><span>第 {{ ledger.page }} 页，共 {{ ledger.total }} 条</span><button :disabled="busy || ledger.page * ledger.page_size >= ledger.total" @click="emit('page', ledger.page + 1)">下一页</button></div>
    <form v-if="target" class="portfolio-confirm" @submit.prevent="save"><h3>确认作废原流水 #{{ target.sequence }}</h3><p>{{ label(target.kind) }} · {{ target.symbol || target.currency }} · 现金变动 {{ number(target.cash_delta) }} · {{ time(target.occurred_at) }}</p><p>这会作废原交易并重新计算账本，不是一笔反向市场成交。若后续出现超卖或现金不足，服务端会拒绝冲正。</p><label>作废原因（必填）<textarea v-model="reason" aria-label="作废原因" required maxlength="500" :disabled="busy" /></label><label class="portfolio-checkbox"><input v-model="confirmed" type="checkbox" :disabled="busy" />我已核对原流水及原因，确认作废并重算</label><div class="toolbar"><button :disabled="busy || !confirmed || !reason.trim()">确认冲正</button><button type="button" :disabled="busy" @click="target = null">取消</button></div><p class="muted">失败后保留原因；网络超时请先核对流水，以同一原因重试会保留请求编号。</p></form>
  </section>
</template>
