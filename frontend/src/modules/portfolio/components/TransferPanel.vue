<script setup lang="ts">
import { onBeforeUnmount, onMounted, watch } from 'vue'
import type { PortfolioAccount } from '../types'
import { useTransfers } from '../composables/useTransfers'
import TransferForm from './TransferForm.vue'
import TransferHistory from './TransferHistory.vue'
const props = defineProps<{ accounts: PortfolioAccount[]; selected: string }>()
const emit = defineEmits<{ changed: []; busy: [value: boolean] }>()
const transfers = useTransfers(() => emit('changed'))
const { ledger, filter, loading, saving, error } = transfers
watch(saving, value => emit('busy', value), { flush: 'sync' })
onMounted(() => { void transfers.select(props.selected) })
onBeforeUnmount(() => emit('busy', false))
</script>
<template><div class="portfolio-main"><TransferForm :accounts="accounts" :selected="selected" :busy="saving" :submit="transfers.create" /><p v-if="error" role="alert" class="portfolio-error">{{ error }}</p><section class="panel portfolio-panel"><button :disabled="loading || saving" @click="transfers.load">{{ loading ? '正在读取…' : '刷新划转历史' }}</button></section><TransferHistory :ledger="ledger" :accounts="accounts" :filter="filter" :busy="loading || saving" :reverse="transfers.reverse" @filter="transfers.select" @page="transfers.changePage" /></div></template>
