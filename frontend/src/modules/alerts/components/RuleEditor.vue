<script setup lang="ts">
import { ref, watch } from 'vue'
import { SecuritySearch, type SecurityDTO } from '../../securities'
import type { AlertRule, AlertRuleCreate } from '../types'
import { newRuleDraft, ruleDraft, ruleLabels, rulePayload } from '../composables/ruleDraft'
const props = defineProps<{ rule: AlertRule | null; busy: boolean; submit: (body: AlertRuleCreate) => Promise<boolean> }>()
const draft = ref(newRuleDraft()), securityLabel = ref(''), error = ref('')
watch(() => props.rule, rule => { draft.value = rule ? ruleDraft(rule) : newRuleDraft(); securityLabel.value = rule ? `${rule.symbol} · ${rule.security_name}` : ''; error.value = '' }, { immediate: true })
watch(() => draft.value.mode, mode => { if (mode === 'REALTIME') draft.value.enabled = false })
function choose(security: SecurityDTO) { draft.value.security_id = security.id; securityLabel.value = `${security.symbol} · ${security.name}` }
async function save() { error.value = ''; try { await props.submit(rulePayload(draft.value)) } catch (cause) { error.value = cause instanceof Error ? cause.message : '请检查输入' } }
</script>
<template>
  <section class="panel alert-business-panel" data-testid="rule-editor">
    <h2>{{ rule ? '编辑规则' : '新建规则' }}</h2>
    <p v-if="rule">{{ rule.symbol }} · 版本 {{ rule.version }} · {{ rule.state.phase }} · 已触发 {{ rule.state.trigger_count }} 次<br>{{ rule.state.evaluation_status }} · {{ rule.state.evaluation_reason }}</p>
    <p>证券：{{ securityLabel || '尚未选择' }}</p>
    <SecuritySearch :disabled="busy" @select="choose" />
    <form class="alert-form" @submit.prevent="save">
      <fieldset :disabled="busy">
        <label>规则名称<input v-model="draft.name" aria-label="规则名称" maxlength="80" required></label>
        <label>规则类型<select v-model="draft.rule_type" aria-label="规则类型"><option v-for="(label, type) in ruleLabels" :key="type" :value="type">{{ label }}</option></select></label>
        <label>模式<select v-model="draft.mode" aria-label="预警模式"><option value="OBSERVATION">观察模式</option><option value="REALTIME">实时模式（尚未验收）</option></select></label>
        <p v-if="draft.mode === 'REALTIME'" role="status">源延迟未知，实时风控尚未验收。可以保存停用规则。</p>
        <div class="alert-fields"><label>触发阈值{{ draft.rule_type.startsWith('DAY_') ? '（%）' : '' }}<input v-model="draft.threshold" aria-label="触发阈值" inputmode="decimal" required></label><label>重置阈值<input v-model="draft.reset_threshold" aria-label="重置阈值" inputmode="decimal" required></label></div>
        <label>冷却秒数<input v-model.number="draft.cooldown_seconds" aria-label="冷却秒数" type="number" min="0" max="86400" step="1" required></label>
        <label class="alert-check"><input v-model="draft.enabled" type="checkbox" aria-label="启用规则" :disabled="draft.mode === 'REALTIME'">启用规则（须明确勾选）</label>
        <p>上穿/下穿首次采样只建立基线；涨跌幅条件首次满足即可触发。冷却与重置独立，重置不会清除冷却。</p>
        <p v-if="error" role="alert">{{ error }}</p><button type="submit">{{ busy ? '正在提交…' : '保存规则' }}</button>
      </fieldset>
    </form>
  </section>
</template>
