<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useAuthStore } from '../../auth'
import { useSchedules } from '../composables/useSchedules'
import { beijingTime, scheduleStatus } from '../composables/scheduleDraft'
import ScheduleEditor from './ScheduleEditor.vue'
import ScheduleRuns from './ScheduleRuns.vue'
import ScheduleCalendar from './ScheduleCalendar.vue'
const auth = useAuthStore(), state = useSchedules()
const { schedules, selected, preview, runs, error, busy, runFilter } = state
const confirmDelete = ref(false)
watch(selected, () => { confirmDelete.value = false })
onMounted(() => { void state.load() })
</script>
<template>
  <div class="schedule-panel" data-testid="schedule-panel">
    <section class="panel alert-business-panel schedule-guidance">
      <h2>交易日尾盘提醒</h2>
      <p>固定北京时间，仅当前常规交易时段发送；未知日历或非交易日不发送。当前日历仅覆盖 2026 年，必须在 2027 年之前更新，否则超出覆盖范围会暂停提醒。</p>
      <p>发送窗口为 [计划时间, min(计划时间 + 宽限秒数, 收盘时间))。启动恢复仅在宽限内补发；新启用或编辑不追补过去时间点。同一天同一提醒同一时间点最多一次，编辑版本不会重复发送。超期记为“已错过”，不补发过去日期。</p>
      <p>预览只读，仅展示服务端今天的判断，不生成真实通知；实际通知请在“站内通知与投递”确认。</p>
    </section>
    <p v-if="error" role="alert">{{ error }}</p>
    <div class="schedule-layout">
      <section class="panel alert-business-panel"><h2>尾盘提醒列表</h2><div class="toolbar"><button data-testid="schedule-new" :disabled="busy" @click="state.select(null)">新建提醒</button><button :disabled="busy" @click="state.load">刷新提醒列表</button></div><p v-if="!schedules.length">尚无尾盘提醒，填写后显式保存。</p><button v-for="schedule in schedules" :key="schedule.id" class="alert-rule" :aria-pressed="selected?.id === schedule.id" :disabled="busy" data-testid="schedule-list-item" @click="state.select(schedule)"><strong>{{ schedule.name }}</strong><small>{{ schedule.exchange }} · {{ schedule.enabled ? '已启用' : '已停用' }} · v{{ schedule.version }}</small><small>{{ schedule.times.join('、') }}（北京时间）</small></button></section>
      <div class="schedule-main">
        <ScheduleEditor :key="`${auth.epoch}:${selected?.id || 'new'}`" :schedule="selected" :busy="busy" :submit="state.save" />
        <section v-if="selected" class="panel alert-business-panel" data-testid="schedule-preview">
          <h2>今天的只读预览</h2><p>根据已保存配置 v{{ selected.version }} 预览；未保存草稿不参与。</p>
          <div class="toolbar"><button :disabled="busy" data-testid="schedule-preview-button" @click="state.simulate">读取今天预览（不发送）</button><button :disabled="busy" data-testid="schedule-delete" @click="confirmDelete = true">删除提醒</button></div>
          <div v-if="confirmDelete" class="alert-confirm" role="group" aria-label="确认删除尾盘提醒"><p>确认删除“{{ selected.name }}”（v{{ selected.version }}）？历史执行记录将保留。</p><button :disabled="busy" data-testid="schedule-delete-confirm" @click="state.remove">确认删除“{{ selected.name }}”</button><button :disabled="busy" @click="confirmDelete = false">取消</button></div>
          <template v-if="preview"><p>检查时间：{{ beijingTime(preview.checked_at) }} · 时区 {{ preview.timezone }}</p><ScheduleCalendar :calendar="preview.calendar" /><div class="alert-scroll" tabindex="0" aria-label="今天的尾盘提醒时间表"><table><thead><tr><th>时间</th><th>计划 / 失效（北京时间）</th><th>状态 / 原因</th><th>关联记录</th></tr></thead><tbody><tr v-for="slot in preview.slots" :key="slot.local_time"><td>{{ slot.local_time }}</td><td>{{ beijingTime(slot.scheduled_at) }}<small>{{ beijingTime(slot.expires_at) }}</small></td><td>{{ scheduleStatus(slot.status) }}<small>{{ slot.reason }}</small></td><td>执行：{{ slot.run_id || '无' }}<small>投递：{{ slot.outbox_id || '无' }}</small></td></tr></tbody></table></div></template>
        </section>
      </div>
    </div>
    <section class="panel alert-business-panel"><h2>执行记录</h2><div class="toolbar"><label>执行记录筛选<select v-model="runFilter" aria-label="尾盘执行记录筛选" @change="state.loadRuns(1)"><option value="all">全部提醒（含已删除）</option><option value="selected" :disabled="!selected">当前选中提醒{{ selected ? `：${selected.name}` : '' }}</option></select></label><button data-testid="schedule-runs-refresh" :disabled="runFilter === 'selected' && !selected" @click="state.loadRuns(1)">读取执行记录</button></div><ScheduleRuns :runs="runs" :busy="busy" @page="state.loadRuns" /></section>
  </div>
</template>
<style scoped>
.schedule-panel{display:grid;gap:20px;min-width:0;color:#27364c}.schedule-layout{display:grid;grid-template-columns:minmax(210px,280px) minmax(0,1fr);gap:20px;align-items:start}.schedule-main{display:grid;gap:20px;min-width:0}.schedule-guidance{background:#f7faff;border:1px solid #dce5f5}.schedule-panel :deep(.panel){background-color:#fff}.schedule-panel :deep(summary){cursor:pointer}.schedule-panel :deep(table){font-size:13px}.schedule-panel :deep(.alert-scroll){overscroll-behavior-x:contain}@media(max-width:800px){.schedule-layout{grid-template-columns:minmax(0,1fr)}}
</style>
