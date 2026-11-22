<script setup lang="ts">
import { ref } from 'vue'
import { NButton, NInput, NPopconfirm } from 'naive-ui'
import type { Group } from '../types'
defineProps<{ groups: Group[]; selected: string | null; busy: boolean }>()
const emit = defineEmits<{ select: [id: string]; create: [name: string]; rename: [id: string, name: string]; remove: [id: string]; order: [index: number, direction: number] }>()
const name = ref(''), editing = ref<string>(), draft = ref('')
function create() { if (name.value.trim()) { emit('create', name.value.trim()); name.value = '' } }
</script>
<template>
  <aside class="panel business-panel groups-panel">
    <h2>自选分组 <small>{{ groups.length }} / 50</small></h2>
    <form class="toolbar" @submit.prevent="create"><NInput v-model:value="name" :maxlength="80" placeholder="新分组名称" aria-label="新分组名称" :disabled="busy || groups.length >= 50" /><NButton attr-type="submit" :disabled="busy || !name.trim() || groups.length >= 50">创建</NButton></form>
    <p v-if="!groups.length" class="muted">暂无分组。先创建分组，再搜索主数据添加证券。</p>
    <div v-for="(group,index) in groups" :key="group.id" class="group-row" :class="{selected: selected === group.id}">
      <NButton text :disabled="busy" @click="emit('select',group.id)">{{ group.name }}</NButton>
      <form v-if="editing === group.id" class="toolbar" @submit.prevent="emit('rename',group.id,draft.trim()); editing = undefined"><NInput v-model:value="draft" :maxlength="80" aria-label="分组新名称" :disabled="busy" /><NButton attr-type="submit" :disabled="busy || !draft.trim()">保存</NButton><NButton :disabled="busy" @click="editing = undefined">取消</NButton></form>
      <div class="row-actions"><NButton size="tiny" :disabled="busy || index === 0" aria-label="分组上移" @click="emit('order',index,-1)">↑</NButton><NButton size="tiny" :disabled="busy || index === groups.length-1" aria-label="分组下移" @click="emit('order',index,1)">↓</NButton><NButton size="tiny" :disabled="busy" @click="editing = group.id; draft = group.name">改名</NButton><NPopconfirm :disabled="busy" @positive-click="emit('remove',group.id)"><template #trigger><NButton size="tiny" :disabled="busy">删除</NButton></template>确认删除“{{ group.name }}”？非空分组不能删除。</NPopconfirm></div>
    </div>
  </aside>
</template>
