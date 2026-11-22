<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { NAlert, NButton, NInput, NModal, NPagination, NSelect } from 'naive-ui'
import { useSecuritiesStore } from '../stores/securities'
import SecurityForm from '../components/SecurityForm.vue'
import type { CreateSecurity, SecurityDTO, UpdateSecurity } from '../types'
const store = useSecuritiesStore()
const open = ref(false), editing = ref<SecurityDTO>()
onMounted(() => { void store.load() })
onBeforeUnmount(store.clear)
function search() { store.page = 1; void store.load() }
async function save(body: CreateSecurity | UpdateSecurity) { if (await store.save(body, editing.value?.id)) open.value = false }
</script>
<template>
  <div class="business-page">
    <section class="page-heading"><div><div class="eyebrow">SECURITY MASTER</div><h1>证券主数据</h1><p>维护真实证券身份与资料，供自选分组使用。</p></div><NButton type="primary" :disabled="store.saving" @click="editing = undefined; open = true">手工录入</NButton></section>
    <NAlert type="warning">手工资料未经供应商验证，请核对证券代码、交易所与名称。行情尚未接入，当前不提供报价。</NAlert>
    <section class="panel business-panel">
      <form class="toolbar" @submit.prevent="search"><NInput v-model:value="store.q" placeholder="代码或名称" aria-label="搜索证券" /><NSelect v-model:value="store.market" :options="[{label:'全部市场',value:''},...['CN','HK','US'].map(value=>({label:value,value}))]" aria-label="筛选市场" /><NButton attr-type="submit" :loading="store.loading" :disabled="store.loading">查询</NButton></form>
      <NAlert v-if="store.error" type="error">{{ store.error }}</NAlert>
      <div class="table-scroll" :aria-busy="store.loading"><table class="data-table"><thead><tr><th>代码 / 名称</th><th>市场 / 交易所</th><th>类型 / 币种</th><th>状态</th><th>来源</th><th>操作</th></tr></thead><tbody><tr v-for="item in store.items" :key="item.id"><td><strong>{{ item.symbol }}</strong><small>{{ item.name }}</small></td><td>{{ item.market }} · {{ item.exchange }}</td><td>{{ item.security_type }} · {{ item.currency }}</td><td>{{ item.status === 'ACTIVE' ? '启用' : '停用' }}</td><td>手工录入</td><td><NButton size="small" :disabled="store.saving" @click="editing = item; open = true">编辑</NButton></td></tr></tbody></table></div>
      <div v-if="!store.items.length" class="small-empty">{{ store.loading ? '正在加载证券资料…' : store.error ? '资料加载失败，请重新查询。' : '暂无证券资料，请手工录入或调整筛选条件。' }}</div>
      <NPagination v-if="store.total" v-model:page="store.page" :item-count="store.total" :page-size="20" :disabled="store.loading" @update:page="store.load()" />
    </section>
    <NModal v-model:show="open" preset="card" :title="editing ? '编辑证券资料' : '手工录入证券'" class="editor-modal" :mask-closable="!store.saving" :closable="!store.saving" :close-on-esc="!store.saving"><SecurityForm :key="editing?.id ?? 'new'" :security="editing" :saving="store.saving" @save="save" /><NAlert v-if="store.error" type="error">{{ store.error }}</NAlert></NModal>
  </div>
</template>
