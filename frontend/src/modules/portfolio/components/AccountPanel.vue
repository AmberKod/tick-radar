<script setup lang="ts">
import { ref, watch } from 'vue'
import type { PortfolioAccount, PortfolioAccountCreate, PortfolioAccountUpdate } from '../types'
const props = defineProps<{ accounts: PortfolioAccount[]; selected: string; busy: boolean }>()
const emit = defineEmits<{ select: [id: string]; create: [body: PortfolioAccountCreate]; update: [body: PortfolioAccountUpdate] }>()
const name = ref(''), currency = ref<PortfolioAccountCreate['currency']>('CNY'), rename = ref(''), active = ref(true)
watch(() => props.accounts.find(item => item.id === props.selected), account => { rename.value = account?.name || ''; active.value = account?.is_active ?? true }, { immediate: true })
</script>
<template>
  <section class="panel portfolio-panel">
    <h2>账户</h2><p class="muted">各币种独立记账，不跨币种合计。先创建账户，再录入入金。</p>
    <label>选择账户<select :value="selected" aria-label="选择账户" @change="emit('select', ($event.target as HTMLSelectElement).value)"><option value="" disabled>请选择账户</option><option v-for="account in accounts" :key="account.id" :value="account.id">{{ account.name }} · {{ account.currency }}{{ account.is_active ? '' : '（已停用）' }}</option></select></label>
    <form class="portfolio-form" @submit.prevent="emit('create', { name: name.trim(), currency })">
      <h3>新建账户</h3><label>账户名称<input v-model="name" aria-label="新账户名称" required maxlength="80" :disabled="busy" /></label><label>记账币种<select v-model="currency" aria-label="记账币种" :disabled="busy"><option>CNY</option><option>HKD</option><option>USD</option></select></label><button :disabled="busy || !name.trim()">创建账户</button>
    </form>
    <form v-if="selected" class="portfolio-form" @submit.prevent="emit('update', { name: rename.trim(), is_active: active })">
      <h3>编辑当前账户</h3><label>名称<input v-model="rename" aria-label="编辑账户名称" required maxlength="80" :disabled="busy" /></label><label class="portfolio-checkbox"><input v-model="active" type="checkbox" :disabled="busy" />账户启用</label><button :disabled="busy || !rename.trim()">保存账户</button>
    </form>
  </section>
</template>
