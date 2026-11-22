<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { NAlert, NButton } from 'naive-ui'
import { SecuritySearch } from '../../securities'
import { marketApi, QuoteTable, type QuoteDTO } from '../../market'
import { errorMessage } from '../../../shared/api/client'
import { useWatchlistStore } from '../stores/watchlist'
import * as api from '../api'
import GroupList from '../components/GroupList.vue'
import MemberTable from '../components/MemberTable.vue'
const store = useWatchlistStore()
const busy = computed(() => store.loading || store.saving)
const quotes = ref<QuoteDTO[]>([]), quoteError = ref('')
let quoteRevision = 0, controller: AbortController | undefined
async function loadQuotes() {
  const version = ++quoteRevision
  controller?.abort(); controller = new AbortController()
  quoteError.value = ''
  const symbols = store.items.slice(0, 50).map(item => item.security.symbol)
  if (!symbols.length) { quotes.value = []; return }
  try {
    const result = await marketApi.getQuotes(symbols, { signal: controller.signal })
    if (version === quoteRevision) quotes.value = result.quotes
  } catch (cause) {
    if (version === quoteRevision && !controller.signal.aborted) quoteError.value = errorMessage(cause)
  }
}
watch(() => store.items, () => { quotes.value = []; void loadQuotes() })
const timer = setInterval(() => { if (!store.loading) void loadQuotes() }, 10_000)
onMounted(() => { void store.load() })
onBeforeUnmount(() => { quoteRevision++; controller?.abort(); clearInterval(timer); store.clear() })
</script>
<template>
  <div class="business-page">
    <section class="page-heading"><div><div class="eyebrow">WATCHLIST</div><h1>自选股</h1><p>管理关注证券与观察备注，共享报价自动读取；开市时效未知，价格预警未启用。</p></div><NButton :loading="store.loading" :disabled="busy" @click="store.load()">刷新列表</NButton></section>
    <NAlert v-if="store.error" type="error">{{ store.error }}</NAlert>
    <div class="watchlist-grid">
      <GroupList :groups="store.groups" :selected="store.selected" :busy="busy" @select="store.select" @create="name => store.mutate(() => api.createGroup(name))" @rename="(id,name) => store.mutate(() => api.renameGroup(id,name))" @remove="id => store.mutate(() => api.deleteGroup(id))" @order="(index,direction) => store.reorder('groups',index,direction)" />
      <section class="panel business-panel">
        <h2>{{ store.groups.find(group => group.id === store.selected)?.name || '分组成员' }} <small>{{ store.items.length }} / 500</small></h2>
        <template v-if="store.selected !== null"><h3>观察报价</h3><NAlert v-if="quoteError" type="warning">报价暂不可读，成员管理不受影响：{{ quoteError }}</NAlert><QuoteTable :quotes="quotes" empty-text="添加证券后显示观察报价；失败或时效未知将明确标注。" /><p v-if="store.items.length > 50" class="muted">当前只观察前50个成员；完整列表仍可管理。</p><h3 class="watchlist-manage-heading">添加与管理成员</h3><SecuritySearch :key="store.selected" :disabled="busy || store.items.length >= 500" @select="security => store.mutate(() => api.addItem(store.selected!,security.id))" /><MemberTable :items="store.items" :groups="store.groups" :busy="busy" :loading="store.loading" @note="(id,note) => store.mutate(() => api.updateNote(id,note))" @move="(id,group) => store.mutate(() => api.moveItem(id,group))" @remove="id => store.mutate(() => api.deleteItem(id))" @order="(index,direction) => store.reorder('items',index,direction)" /></template>
        <div v-if="store.selected === null" class="small-empty">{{ store.loading ? '正在加载分组…' : store.error ? '分组加载失败，请刷新列表。' : '先创建一个自选分组，再搜索证券主数据添加成员。' }}</div>
      </section>
    </div>
  </div>
</template>
