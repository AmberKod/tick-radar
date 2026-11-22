<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { NAlert, NButton, NInput, NPagination } from 'naive-ui'
import { searchSecurities } from '../api'
import type { SecurityDTO } from '../types'
import { errorMessage } from '../../../shared/api/client'
defineProps<{ disabled?: boolean }>()
const emit = defineEmits<{ select: [security: SecurityDTO] }>()
const q = ref(''), items = ref<SecurityDTO[]>([]), error = ref(''), loading = ref(false), searched = ref(false), page = ref(1), total = ref(0)
let revision = 0
let controller: AbortController | undefined
async function search(reset = false) {
  if (reset) page.value = 1
  const version = ++revision
  controller?.abort(); controller = new AbortController(); loading.value = true; error.value = ''; searched.value = true
  try { const result = await searchSecurities(q.value, '', page.value, { signal: controller.signal }); if (version === revision) { items.value = result.items; total.value = result.total } }
  catch (cause) { if (version === revision) { items.value = []; total.value = 0; error.value = errorMessage(cause) } }
  finally { if (version === revision) loading.value = false }
}
onBeforeUnmount(() => { revision++; controller?.abort() })
</script>
<template>
  <div class="security-search">
    <form class="toolbar" @submit.prevent="search(true)"><NInput v-model:value="q" placeholder="搜索已录入的证券代码或名称" aria-label="搜索主数据" /><NButton attr-type="submit" :loading="loading" :disabled="loading || disabled">搜索</NButton></form>
    <NAlert v-if="error" type="error">{{ error }}</NAlert>
    <p v-else-if="searched && !loading && !items.length" class="muted">没有匹配的证券，请先在证券主数据中手工录入。</p>
    <div v-for="security in items" :key="security.id" class="search-result"><div><strong>{{ security.symbol }}</strong> {{ security.name }}<small>{{ security.exchange }} · {{ security.currency }}</small></div><NButton size="small" :disabled="disabled || security.status !== 'ACTIVE'" @click="emit('select', security)">添加</NButton></div>
    <NPagination v-if="total > 20" v-model:page="page" :item-count="total" :page-size="20" :disabled="loading || disabled" @update:page="search()" />
  </div>
</template>
