<script setup lang="ts">
import type { MarketCalendarStatus } from '../types/schedules'
import { beijingTime } from '../composables/scheduleDraft'
defineProps<{ calendar: MarketCalendarStatus }>()
</script>
<template>
  <dl class="schedule-calendar" data-testid="schedule-calendar">
    <div><dt>交易日 / 状态</dt><dd>{{ calendar.session_date }} · {{ calendar.exchange }} · {{ calendar.state }}</dd></div>
    <div><dt>依据 basis</dt><dd>{{ calendar.basis }}</dd></div>
    <div><dt>日历名称 / 版本</dt><dd>{{ calendar.calendar_name }} · {{ calendar.calendar_version }}</dd></div>
    <div><dt>覆盖范围</dt><dd>{{ calendar.coverage_start }} 至 {{ calendar.coverage_end }}</dd></div>
    <div><dt>日历原因 reason</dt><dd>{{ calendar.reason }}</dd></div>
    <div><dt>检查时间（北京时间）</dt><dd>{{ beijingTime(calendar.checked_at) }}</dd></div>
    <div v-if="calendar.warnings?.length"><dt>日历提示</dt><dd>{{ calendar.warnings.join('；') }}</dd></div>
  </dl>
</template>
<style scoped>
.schedule-calendar{display:grid;gap:8px;margin:12px 0;font-size:13px}.schedule-calendar div{display:grid;grid-template-columns:130px minmax(0,1fr);gap:8px}.schedule-calendar dt{color:#5c6b80}.schedule-calendar dd{margin:0;overflow-wrap:anywhere}@media(max-width:600px){.schedule-calendar div{grid-template-columns:1fr;gap:2px}}
</style>
