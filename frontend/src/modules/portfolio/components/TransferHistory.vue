<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import type { PortfolioAccount, PortfolioReversalCreate } from '../types'
import type { PortfolioTransfer, PortfolioTransferPage } from '../types/transfers'
import { beijingTime, decimalLabel } from '../composables/format'
import { rateLabel } from '../composables/transferDraft'
const props = defineProps<{ ledger: PortfolioTransferPage | null; accounts: PortfolioAccount[]; filter: string; busy: boolean; reverse: (id: string, body: PortfolioReversalCreate) => Promise<boolean> }>()
const emit = defineEmits<{ filter: [value: string]; page: [value: number] }>()
const target = ref<PortfolioTransfer | null>(null), reason = ref(''), confirmed = ref(false), pending = ref(false), error = ref('')
let requestId = crypto.randomUUID(), alive = true
onBeforeUnmount(() => { alive = false })
watch(() => reason.value.trim(), () => { requestId = crypto.randomUUID(); confirmed.value = false }, { flush: 'sync' })
watch(() => props.filter, () => { target.value = null })
function start(item: PortfolioTransfer) { target.value = item; reason.value = ''; confirmed.value = false; error.value = ''; requestId = crypto.randomUUID() }
async function save() {
  if (pending.value || props.busy || !target.value) return
  if (!reason.value.trim() || reason.value.trim().length > 500 || !confirmed.value) { error.value = '请填写500字以内的作废原因并勾选整体作废确认。'; return }
  pending.value = true; error.value = ''
  try { if (await props.reverse(target.value.id, { request_id: requestId, reason: reason.value.trim() }) && alive) target.value = null }
  catch (cause) { if (alive) error.value = cause instanceof Error ? cause.message : '整体作废失败。' }
  finally { if (alive) pending.value = false }
}
</script>
<template>
  <section class="panel portfolio-panel">
    <h2>划转与换汇历史</h2><label>关联账户筛选<select :value="filter" aria-label="划转历史账户筛选" :disabled="busy || pending" @change="emit('filter', ($event.target as HTMLSelectElement).value)"><option value="">全部账户</option><option v-for="account in accounts" :key="account.id" :value="account.id">{{ account.name }} · {{ account.currency }}</option></select></label>
    <div class="portfolio-scroll"><table><thead><tr><th>时间 / 状态</th><th>划出 / 手续费</th><th>实际到账</th><th>实际成交汇率 / 操作</th></tr></thead><tbody><tr v-for="item in ledger?.items" :key="item.id"><td>{{ beijingTime(item.occurred_at) }}<small>{{ item.status === 'ACTIVE' ? '有效' : '已作废' }}</small></td><td>{{ item.source_account_name }}<small>{{ decimalLabel(item.source_amount) }} {{ item.source_currency }}</small><small>源币手续费 {{ decimalLabel(item.source_fee) }} {{ item.source_currency }}</small></td><td>{{ item.target_account_name }}<small>{{ decimalLabel(item.target_amount) }} {{ item.target_currency }}</small></td><td>1 {{ item.source_currency }} = {{ rateLabel(item.implied_rate) }} {{ item.target_currency }}<small>按实际金额计算，不含手续费</small><details><summary>关联流水与审计详情</summary><small>划转 {{ item.id }}</small><small>源流水 {{ item.source_entry_id }}</small><small>目标流水 {{ item.target_entry_id }}</small><small v-if="item.source_reversal_entry_id">源冲正流水 {{ item.source_reversal_entry_id }}</small><small v-if="item.target_reversal_entry_id">目标冲正流水 {{ item.target_reversal_entry_id }}</small><small>创建时间 {{ beijingTime(item.created_at) }}</small><small v-if="item.reversed_at">作废时间 {{ beijingTime(item.reversed_at) }}</small><small v-if="item.reversal_reason">作废原因 {{ item.reversal_reason }}</small><small>{{ item.note }}</small></details><button v-if="item.status === 'ACTIVE'" :disabled="busy || pending" @click="start(item)">整体作废</button></td></tr></tbody></table></div>
    <p v-if="!ledger?.items.length" class="small-empty">暂无内部划转与换汇记录。</p><div v-if="ledger && ledger.total > ledger.page_size" class="toolbar"><button :disabled="busy || pending || ledger.page <= 1" @click="emit('page', ledger.page - 1)">上一页</button><span>第 {{ ledger.page }} 页，共 {{ ledger.total }} 条</span><button :disabled="busy || pending || ledger.page * ledger.page_size >= ledger.total" @click="emit('page', ledger.page + 1)">下一页</button></div>
    <form v-if="target" class="portfolio-confirm" @submit.prevent="save"><h3>整体作废内部划转 / 换汇</h3><p>{{ target.source_account_name }}（{{ target.source_currency }}）→ {{ target.target_account_name }}（{{ target.target_currency }}）</p><p>将同时冲正两端流水和源币手续费并重算账本。若后续已占用目标账户资金或现金不足，服务端会拒绝，不能保证一定成功。</p><fieldset :disabled="busy || pending"><label>整体作废原因（必填）<textarea v-model="reason" aria-label="整体作废原因" maxlength="500" /></label><label class="portfolio-checkbox"><input v-model="confirmed" type="checkbox" aria-label="确认整体作废" />我已核对两端流水与原因，确认整体作废</label><p v-if="error" role="alert" class="portfolio-error">{{ error }}</p><div class="toolbar"><button :disabled="!reason.trim() || !confirmed">确认整体作废</button><button type="button" @click="target = null">取消</button></div></fieldset><p class="muted">失败保留原因；同一原因重试保留请求编号，修改原因后使用新编号。</p></form>
  </section>
</template>
