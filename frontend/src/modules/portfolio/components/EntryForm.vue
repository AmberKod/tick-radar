<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { SecuritySearch, type SecurityDTO } from '../../securities'
import type { PortfolioAccount, PortfolioEntryCreate } from '../types'
import { entryPayload, kinds, newDraft } from '../composables/entryDraft'
const props = defineProps<{ account: PortfolioAccount; busy: boolean; submit: (body: PortfolioEntryCreate) => Promise<boolean> }>()
const draft = ref(newDraft()), security = ref<SecurityDTO | null>(null), error = ref('')
let requestId = crypto.randomUUID()
const trade = computed(() => draft.value.kind === 'BUY' || draft.value.kind === 'SELL')
const needsSecurity = computed(() => trade.value || draft.value.kind === 'DIVIDEND')
watch([draft, security], () => { requestId = crypto.randomUUID(); error.value = '' }, { deep: true, flush: 'sync' })
function choose(value: SecurityDTO) { if (value.currency !== props.account.currency) { error.value = '证券币种与账户币种不一致，请切换账户或证券。'; return }; security.value = value }
async function save() {
  error.value = ''
  try { const body = entryPayload(draft.value, security.value, props.account, requestId); if (await props.submit(body)) { draft.value = newDraft(); security.value = null } }
  catch (cause) { error.value = cause instanceof Error ? cause.message : '请检查录入信息。' }
}
</script>
<template>
  <section class="panel portfolio-panel">
    <h2>录入流水</h2><p v-if="!account.is_active" role="status">账户已停用，可查询历史；启用后才能录入。</p>
    <div v-if="needsSecurity" class="portfolio-security-picker"><p>选择证券：{{ security ? `${security.symbol} ${security.name} · ${security.currency}` : '尚未选择' }}</p><SecuritySearch :disabled="busy || !account.is_active" @select="choose" /></div>
    <form class="portfolio-form" @submit.prevent="save">
      <fieldset :disabled="busy || !account.is_active">
        <label>流水类型<select v-model="draft.kind" aria-label="流水类型"><option v-for="(label, key) in kinds" :key="key" :value="key">{{ label }}</option></select></label>
        <label>发生时间（北京时间 UTC+08:00）<input v-model="draft.occurred_at" aria-label="发生时间" type="datetime-local" required /></label>
        <div class="portfolio-fields">
          <template v-if="trade"><label>数量（股/份，非手）<input v-model="draft.quantity" aria-label="数量" inputmode="decimal" required /></label><label>成交价（{{ account.currency }}）<input v-model="draft.price" aria-label="成交价" inputmode="decimal" required /></label></template><label v-else>金额（{{ account.currency }}）<input v-model="draft.amount" aria-label="金额" inputmode="decimal" required /></label>
          <template v-if="needsSecurity"><label>手续费（{{ account.currency }}）<input v-model="draft.fee" aria-label="手续费" inputmode="decimal" required /></label><label>税费（{{ account.currency }}）<input v-model="draft.tax" aria-label="税费" inputmode="decimal" required /></label></template>
        </div>
        <label>备注<textarea v-model="draft.note" aria-label="备注" maxlength="500" /></label><p v-if="error" role="alert" class="portfolio-error">{{ error }}</p><button :disabled="busy || !account.is_active">{{ busy ? '正在提交…' : '提交流水' }}</button>
      </fieldset>
    </form><p class="muted">数量与金额最多8位小数；沪深京、港股仅整数股/份，美股支持碎股。网络失败后请先核对流水，再以原表单重试。</p>
  </section>
</template>
