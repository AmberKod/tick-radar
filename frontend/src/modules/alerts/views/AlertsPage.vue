<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useAuthStore } from '../../auth'
import { NotificationsPanel } from '../../notifications'
import { useAlerts } from '../composables/useAlerts'
import { decimalLabel, ruleLabels } from '../composables/ruleDraft'
import RuleEditor from '../components/RuleEditor.vue'
import RuleActions from '../components/RuleActions.vue'
import EventHistory from '../components/EventHistory.vue'
const auth = useAuthStore(), alerts = useAlerts(), tab = ref('rules'), eventRule = ref('')
const { rules, selected, events, preview, error, busy } = alerts
onMounted(() => { void alerts.load() })
function changeTab(value: string) { tab.value = value; if (value === 'events') void alerts.loadEvents(1, eventRule.value) }
</script>
<template>
  <div class="business-page alerts-page">
    <section class="page-heading"><div><div class="eyebrow">ALERTS & NOTIFICATIONS</div><h1>预警与通知</h1><p>观察行情条件、追溯触发快照，管理站内通知。</p></div><button :disabled="busy" @click="alerts.load">刷新规则列表</button></section>
    <p class="panel alert-business-panel">观察模式仅接收 UNKNOWN / MARKET_CLOSED 且最新接收不超过 180 秒的数据，源延迟未知，不作为实时止损。最多保存 200 条未归档规则，每轮采集最多 50 个标的；满额时最多预留 10 个规则轮转名额。规则证券无需加入自选，轮转可能造成断档，不能保证实时或完整穿越捕获。</p>
    <nav class="toolbar" aria-label="预警中心标签"><button v-for="item in [{ key: 'rules', label: '预警规则' }, { key: 'events', label: '触发记录' }, { key: 'notifications', label: '站内通知与投递' }]" :key="item.key" :aria-pressed="tab === item.key" :disabled="busy" @click="changeTab(item.key)">{{ item.label }}</button></nav>
    <p v-if="error" role="alert">{{ error }}</p>
    <div v-if="tab === 'rules'" class="alert-layout"><section class="panel alert-business-panel"><h2>规则列表</h2><button :disabled="busy" @click="alerts.select(null)">新建规则</button><p v-if="!rules.length">尚无规则，请明确填写阈值后保存。</p><button v-for="rule in rules" :key="rule.id" class="alert-rule" :aria-pressed="selected?.id === rule.id" :disabled="busy" @click="alerts.select(rule)"><strong>{{ rule.name }}</strong><small>{{ rule.symbol }} · {{ rule.security_name }} · v{{ rule.version }}</small><small>{{ ruleLabels[rule.rule_type] }} {{ decimalLabel(rule.threshold) }} · {{ rule.enabled ? '启用' : '停用' }} · {{ rule.state.phase }}</small></button></section><div class="alert-main"><RuleEditor :key="`${auth.epoch}:${selected?.id || 'new'}`" :rule="selected" :busy="busy" :submit="alerts.save" /><RuleActions v-if="selected" :rule="selected" :preview="preview" :busy="busy" :remove="alerts.remove" :reset="alerts.reset" @preview="alerts.simulate" /></div></div>
    <template v-if="tab === 'events'"><label>事件规则筛选<select v-model="eventRule" :disabled="busy" aria-label="事件规则筛选" @change="alerts.loadEvents(1, eventRule)"><option value="">全部规则（含已删除）</option><option v-for="rule in rules" :key="rule.id" :value="rule.id">{{ rule.name }} · {{ rule.symbol }} · v{{ rule.version }}</option></select></label><EventHistory :events="events" :busy="busy" @page="alerts.loadEvents($event, eventRule)" /></template>
    <NotificationsPanel v-if="tab === 'notifications'" :key="auth.epoch" />
  </div>
</template>
<style scoped>
.alerts-page{min-width:0}.alert-layout{display:grid;grid-template-columns:minmax(210px,280px) minmax(0,1fr);gap:20px;align-items:start}.alert-main{display:grid;gap:20px;min-width:0}.alerts-page :deep(.alert-business-panel){padding:20px;min-width:0;overflow-wrap:anywhere}.alerts-page :deep(.alert-form),.alerts-page :deep(fieldset){display:grid;gap:12px}.alerts-page :deep(fieldset){border:0;padding:0;margin:0;min-width:0}.alerts-page :deep(label){display:grid;gap:6px;min-width:0}.alerts-page :deep(input),.alerts-page :deep(select){max-width:100%;width:100%;box-sizing:border-box;border:1px solid #dce2eb;border-radius:6px;padding:9px;background:#fff;color:#27364c;font:inherit}.alerts-page :deep(button){border:1px solid #cbd5e1;background:#f8fafc;color:#23354d;border-radius:6px;padding:8px 12px;cursor:pointer;white-space:normal;max-width:100%;overflow-wrap:anywhere}.alerts-page :deep(button:disabled){opacity:.5;cursor:default}.alerts-page :deep(button[aria-pressed=true]){border-color:#446ee7;background:#edf2ff}.alerts-page :deep(.alert-fields){display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.alerts-page :deep(.alert-check){display:flex;align-items:center;gap:8px}.alerts-page :deep(input[type=checkbox]){width:auto}.alerts-page :deep(.alert-scroll){overflow-x:auto;max-width:100%}.alerts-page :deep(table){width:100%;border-collapse:collapse;min-width:680px}.alerts-page :deep(th),.alerts-page :deep(td){text-align:left;padding:12px 8px;border-bottom:1px solid #e6ebf1;vertical-align:top}.alerts-page :deep(small){display:block;margin-top:5px;overflow-wrap:anywhere}.alerts-page :deep([role=alert]){color:#a32432;overflow-wrap:anywhere}.alerts-page :deep(.alert-confirm){padding:12px;background:#fff5eb;margin-top:12px}.alerts-page :deep(.alert-rule){display:block;width:100%;text-align:left;margin-top:12px}.alerts-page :deep(.alert-message){padding:14px 0;border-bottom:1px solid #e6ebf1}.alerts-page :deep(.toolbar){display:flex;flex-wrap:wrap;gap:10px;margin:12px 0}.alerts-page :deep(.alert-id){overflow-wrap:anywhere}@media(max-width:760px){.alert-layout{grid-template-columns:minmax(0,1fr)}.alerts-page :deep(.alert-fields){grid-template-columns:minmax(0,1fr)}}
</style>
