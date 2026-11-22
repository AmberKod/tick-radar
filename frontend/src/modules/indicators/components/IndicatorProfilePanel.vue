<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import TokenGate from '../../auth/components/TokenGate.vue'
import { useAuthStore } from '../../auth/stores/auth'
import { ApiError } from '../../../shared/api/client'
import { createProfile, deleteProfile, getProfile, listProfiles, updateProfile } from '../api'
import type { IndicatorParameters, IndicatorProfile, IndicatorProfileCreate } from '../types'

const props = defineProps<{
  parameters: IndicatorParameters
  timeframe: 'day' | 'm15'
  adjustment: 'raw' | 'qfq' | 'hfq' | 'vendor_unverified'
  market: 'CN' | 'HK' | 'US' | null
}>()
const emit = defineEmits<{ load: [parameters: IndicatorParameters]; reset: [] }>()
const auth = useAuthStore()
const items = ref<IndicatorProfile[]>([])
const selectedId = ref(''), name = ref(''), message = ref(''), error = ref('')
const busy = ref(false), confirming = ref(false), stale = ref(false)
const selected = computed(() => items.value.find(item => item.id === selectedId.value))
const compatibleContext = computed(() => props.timeframe === 'm15'
  ? props.market === 'CN' && props.adjustment === 'vendor_unverified'
  : props.adjustment !== 'vendor_unverified' && !(props.market === 'US' && props.adjustment === 'hfq'))
function compatible(item: IndicatorProfile) {
  return compatibleContext.value && item.timeframe === props.timeframe && item.price_adjustment === props.adjustment
    && (item.market_scope === 'ALL' || item.market_scope === props.market)
}
const options = computed(() => items.value.filter(compatible))
const validName = computed(() => name.value.trim().length >= 1 && name.value.trim().length <= 80)
let revision = 0, controller: AbortController | undefined
function invalidate() {
  ++revision
  controller?.abort()
  controller = undefined
  busy.value = false
}
function clearSelection() {
  selectedId.value = ''; name.value = ''; message.value = ''; error.value = ''
  confirming.value = false; stale.value = false
}
function reset() { invalidate(); items.value = []; clearSelection() }
function choose() {
  invalidate()
  name.value = selected.value?.name || ''
  message.value = ''; error.value = ''; confirming.value = false; stale.value = false
}
async function run(action: (signal: AbortSignal) => Promise<void>) {
  if (!auth.authenticated || busy.value) return
  const current = ++revision
  const request = new AbortController()
  controller = request
  busy.value = true; error.value = ''; message.value = ''
  try {
    await action(request.signal)
  } catch (cause) {
    if (current !== revision || request.signal.aborted) return
    error.value = cause instanceof ApiError ? `${cause.message}（${cause.code}）` : cause instanceof Error ? cause.message : '配置操作失败，请重试。'
    if (cause instanceof ApiError && ['PROFILE_VERSION_CONFLICT', 'PROFILE_NOT_FOUND'].includes(cause.code)) {
      stale.value = true
      error.value += ' 请刷新配置并重新选择；当前参数与名称草稿已保留。'
    }
  } finally { if (current === revision) { busy.value = false; controller = undefined } }
}
function refresh() {
  // 刷新保留名称草稿，要求重新选择以取得明确的新版本。
  void run(async signal => {
    const data = await listProfiles({ signal })
    if (signal.aborted) return
    items.value = data.items
    selectedId.value = ''; confirming.value = false; stale.value = false
    message.value = '配置已刷新，请重新选择。'
  })
}
function payload(): IndicatorProfileCreate {
  return { name: name.value.trim(), timeframe: props.timeframe, price_adjustment: props.adjustment,
    market_scope: props.timeframe === 'm15' ? 'CN' : 'ALL', parameters: { ...props.parameters } }
}
function save(overwrite: boolean) {
  if (!validName.value || !compatibleContext.value || (overwrite && (!selected.value || stale.value))) return
  const previous = selected.value
  const data = payload()
  void run(async signal => {
    const saved = overwrite && previous ? await updateProfile(previous.id, { ...data, version: previous.version }, { signal }) : await createProfile(data, { signal })
    if (signal.aborted) return
    items.value = [...items.value.filter(item => item.id !== saved.id), saved]
    selectedId.value = saved.id; name.value = saved.name; confirming.value = false
    message.value = `已保存“${saved.name}”，当前图表不变。`
  })
}
function load() {
  const previous = selected.value
  if (!previous || stale.value || !compatible(previous)) return
  void run(async signal => {
    const item = await getProfile(previous.id, { signal })
    if (signal.aborted) return
    if (!compatible(item)) throw new Error('配置周期、复权或市场不匹配，请刷新配置并重新选择。')
    items.value = items.value.map(value => value.id === item.id ? item : value)
    emit('load', { ...item.parameters })
    message.value = `已载入“${item.name}”，点击查询后应用。`
  })
}
function remove() {
  const item = selected.value
  if (!item || !confirming.value || stale.value) return
  void run(async signal => {
    await deleteProfile(item.id, item.version, { signal })
    if (signal.aborted) return
    items.value = items.value.filter(value => value.id !== item.id)
    clearSelection()
    message.value = `已删除“${item.name}”，当前参数与图表不变。`
  })
}
watch(() => [auth.epoch, auth.authenticated], () => {
  reset()
  emit('reset')
  if (auth.authenticated) refresh()
}, { immediate: true, flush: 'sync' })
watch(() => [props.timeframe, props.adjustment, props.market], () => {
  invalidate(); clearSelection()
  if (auth.authenticated) refresh()
}, { flush: 'sync' })
onBeforeUnmount(reset)
</script>

<template>
  <section class="profile-panel" aria-label="指标配置管理">
    <h3>我的指标配置</h3>
    <p class="profile-hint">保存当前参数、周期与复权口径。载入仅填入参数，点击查询后才应用。</p>
    <TokenGate>
      <p class="profile-context">{{ timeframe === 'day' ? '日线 · 全市场保存' : '15分钟 · CN市场保存' }} · {{ adjustment }}</p>
      <p v-if="!compatibleContext" role="alert">当前周期、复权或市场不支持此配置，请先选择兼容的上下文。</p>
      <div class="profile-controls">
        <label>已保存配置
          <select v-model="selectedId" aria-label="已保存配置" :disabled="busy || !compatibleContext" @change="choose">
            <option value="">请选择配置</option>
            <option v-for="item in options" :key="item.id" :value="item.id">{{ item.name }} · v{{ item.version }} · {{ item.market_scope }}</option>
          </select>
        </label>
        <button type="button" :disabled="busy" @click="refresh">刷新配置</button>
        <button type="button" :disabled="busy || !selected || stale || !compatibleContext" @click="load">载入配置</button>
      </div>
      <div class="profile-controls">
        <label>配置名称<input v-model="name" aria-label="配置名称" maxlength="80" autocomplete="off" :disabled="busy" /></label>
        <button type="button" :disabled="busy || !validName || !compatibleContext" @click="save(false)">另存为</button>
        <button type="button" :disabled="busy || !validName || !selected || stale || !compatibleContext" @click="save(true)">覆盖更新</button>
        <button type="button" :disabled="busy || !selected || stale" @click="confirming = true">删除配置</button>
      </div>
      <p class="profile-hint">名称去除首尾空格后为 1–80 字；覆盖更新可同时重命名。</p>
      <div v-if="confirming && selected" class="profile-confirm" role="group" aria-label="确认删除配置">
        <p>确定删除“{{ selected.name }}”（v{{ selected.version }}）？此操作无法撤销。</p>
        <button type="button" :disabled="busy || stale" @click="remove">确认删除</button>
        <button type="button" :disabled="busy" @click="confirming = false">取消</button>
      </div>
      <p v-if="busy" role="status">正在处理配置…</p>
      <p v-if="message" role="status">{{ message }}</p>
      <p v-if="error" role="alert" class="profile-error">{{ error }}</p>
    </TokenGate>
  </section>
</template>

<style scoped>
.profile-panel { margin-top: 20px; padding: 16px; border: 1px solid #dce3ed; border-radius: 10px; background: #f8fafc; min-width: 0; overflow-wrap: anywhere; }
h3 { margin: 0 0 8px; }
.profile-hint, .profile-context { color: #596579; font-size: 12px; line-height: 1.7; }
.profile-controls { display: flex; flex-wrap: wrap; align-items: end; gap: 8px; margin: 12px 0; }
.profile-controls label { display: grid; gap: 6px; flex: 1 1 200px; min-width: 0; }
input, select { box-sizing: border-box; width: 100%; min-width: 0; padding: 8px; border: 1px solid #cbd5e1; border-radius: 6px; background: white; color: #243247; }
button { padding: 8px 12px; border: 1px solid #cbd5e1; border-radius: 6px; background: white; color: #243247; cursor: pointer; }
button:disabled { opacity: .5; cursor: default; }
.profile-error { color: #b4233e; }
.profile-confirm { padding: 12px; border: 1px solid #e8c5cb; border-radius: 8px; background: #fff; }
.profile-confirm button + button { margin-left: 8px; }
.profile-panel :deep(.token-panel) { padding: 12px; min-width: 0; }
.profile-panel :deep(.toolbar) { flex-wrap: wrap; }
.profile-panel :deep(.toolbar > *) { max-width: 100%; }
</style>
