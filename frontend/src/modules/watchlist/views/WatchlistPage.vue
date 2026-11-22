<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { NAlert, NButton } from 'naive-ui'
import { SecuritySearch } from '../../securities'
import { useWatchlistStore } from '../stores/watchlist'
import * as api from '../api'
import GroupList from '../components/GroupList.vue'
import MemberTable from '../components/MemberTable.vue'
const store = useWatchlistStore()
const busy = computed(() => store.loading || store.saving)
onMounted(() => { void store.load() })
onBeforeUnmount(store.clear)
</script>
<template>
  <div class="business-page">
    <section class="page-heading"><div><div class="eyebrow">WATCHLIST</div><h1>自选股</h1><p>用分组整理关注证券，保留观察备注。行情尚未接入，不显示价格。</p></div><NButton :loading="store.loading" :disabled="busy" @click="store.load()">刷新列表</NButton></section>
    <NAlert v-if="store.error" type="error">{{ store.error }}</NAlert>
    <div class="watchlist-grid">
      <GroupList :groups="store.groups" :selected="store.selected" :busy="busy" @select="store.select" @create="name => store.mutate(() => api.createGroup(name))" @rename="(id,name) => store.mutate(() => api.renameGroup(id,name))" @remove="id => store.mutate(() => api.deleteGroup(id))" @order="(index,direction) => store.reorder('groups',index,direction)" />
      <section class="panel business-panel">
        <h2>{{ store.groups.find(group => group.id === store.selected)?.name || '分组成员' }} <small>{{ store.items.length }} / 500</small></h2>
        <template v-if="store.selected !== null"><SecuritySearch :key="store.selected" :disabled="busy || store.items.length >= 500" @select="security => store.mutate(() => api.addItem(store.selected!,security.id))" /><MemberTable :items="store.items" :groups="store.groups" :busy="busy" :loading="store.loading" @note="(id,note) => store.mutate(() => api.updateNote(id,note))" @move="(id,group) => store.mutate(() => api.moveItem(id,group))" @remove="id => store.mutate(() => api.deleteItem(id))" @order="(index,direction) => store.reorder('items',index,direction)" /></template>
        <div v-else class="small-empty">{{ store.loading ? '正在加载分组…' : store.error ? '分组加载失败，请刷新列表。' : '先创建一个自选分组，再搜索证券主数据添加成员。' }}</div>
      </section>
    </div>
  </div>
</template>
