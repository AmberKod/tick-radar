<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import type { PortfolioAccount } from '../types'
import type { PortfolioTransferCreate } from '../types/transfers'
import { actualRate, newTransferDraft, rateLabel, sourceTotal, transferPayload } from '../composables/transferDraft'
const props = defineProps<{ accounts: PortfolioAccount[]; selected: string; busy: boolean; submit: (body: PortfolioTransferCreate) => Promise<boolean> }>()
const initialSource = () => props.accounts.find(item => item.id === props.selected && item.is_active)?.id || props.accounts.find(item => item.is_active)?.id || ''
const draft = reactive(newTransferDraft(initialSource())), confirmed = ref(false), error = ref(''), pending = ref(false)
watch(() => props.accounts, () => { if (!draft.source_account_id) draft.source_account_id = initialSource() })
let requestId = crypto.randomUUID(), canonical = '', alive = true
onBeforeUnmount(() => { alive = false })
const source = computed(() => props.accounts.find(item => item.id === draft.source_account_id)), target = computed(() => props.accounts.find(item => item.id === draft.target_account_id))
const sameCurrency = computed(() => !!source.value && source.value.currency === target.value?.currency)
const body = computed(() => { try { return transferPayload(draft, props.accounts, '') } catch { return null } })
watch(() => JSON.stringify(body.value || draft), value => { if (value !== canonical) { canonical = value; requestId = crypto.randomUUID(); confirmed.value = false } }, { flush: 'sync', immediate: true })
const preview = computed(() => { if (!body.value) return null; return { total: sourceTotal(body.value.source_amount, body.value.source_fee ?? '0'), rate: actualRate(body.value.source_amount, body.value.target_amount) } })
async function save() {
  if (pending.value || props.busy) return
  error.value = ''
  try {
    const payload = transferPayload(draft, props.accounts, requestId)
    if (!confirmed.value) throw new Error('请先核对两端账户及金额并勾选确认。')
    pending.value = true
    if (await props.submit(payload) && alive) { Object.assign(draft, newTransferDraft(initialSource())); confirmed.value = false; requestId = crypto.randomUUID() }
  } catch (cause) { if (alive) error.value = cause instanceof Error ? cause.message : '提交失败，请核对表单。' }
  finally { if (alive) pending.value = false }
}
</script>
<template>
  <section class="panel portfolio-panel">
    <h2>内部划转与换汇</h2><p class="muted">按两端实际金额记账。手续费以划出账户币种单独扣除；汇率由实际金额计算，不使用市场报价。</p>
    <form class="portfolio-form" @submit.prevent="save">
      <fieldset :disabled="busy || pending">
        <div class="portfolio-fields">
          <label>划出账户<select v-model="draft.source_account_id" aria-label="划出账户"><option value="">请选择</option><option v-for="account in accounts" :key="account.id" :value="account.id" :disabled="!account.is_active">{{ account.name }} · {{ account.currency }}{{ account.is_active ? '' : '（已停用）' }}</option></select></label>
          <label>划入账户<select v-model="draft.target_account_id" aria-label="划入账户"><option value="">请明确选择划入账户</option><option v-for="account in accounts" :key="account.id" :value="account.id" :disabled="!account.is_active || account.id === draft.source_account_id">{{ account.name }} · {{ account.currency }}</option></select></label>
          <label>划出金额（{{ source?.currency || '源币' }}）<input v-model="draft.source_amount" aria-label="划出金额" inputmode="decimal" /></label>
          <label>实际到账金额（{{ target?.currency || '目标币' }}）<input :value="sameCurrency ? draft.source_amount : draft.target_amount" :readonly="sameCurrency" aria-label="实际到账金额" inputmode="decimal" @input="draft.target_amount = ($event.target as HTMLInputElement).value" /></label>
          <label>源币手续费（{{ source?.currency || '源币' }}）<input v-model="draft.source_fee" aria-label="源币手续费" inputmode="decimal" /></label>
          <label>发生时间（北京时间）<input v-model="draft.occurred_at" aria-label="划转发生时间" type="datetime-local" /></label>
        </div><label>备注（最多500字）<textarea v-model="draft.note" aria-label="划转备注" maxlength="500" /></label>
        <div v-if="preview" class="portfolio-confirm"><h3>提交前核对</h3><p>{{ source?.name }}（{{ source?.currency }}） → {{ target?.name }}（{{ target?.currency }}）</p><p>源账户合计扣款 {{ preview.total }} {{ source?.currency }}，其中手续费 {{ draft.source_fee }} {{ source?.currency }}</p><p>目标账户实际到账 {{ body?.target_amount }} {{ target?.currency }}</p><p>实际成交汇率：1 {{ source?.currency }} = {{ rateLabel(preview.rate) }} {{ target?.currency }}（不含手续费）</p><label class="portfolio-checkbox"><input v-model="confirmed" type="checkbox" aria-label="确认划转" />我已核对两端账户、币种及实际金额</label></div>
        <p v-if="error" role="alert" class="portfolio-error">{{ error }}</p><button :disabled="!confirmed || !body">{{ pending ? '正在提交…' : '确认内部划转 / 换汇' }}</button><p class="muted">失败保留草稿。网络失败请先核对历史；相同内容重试沿用原请求编号，不会自动重试。</p>
      </fieldset>
    </form>
  </section>
</template>
