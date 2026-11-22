<script setup lang="ts">
import { ref } from 'vue'
import { NButton, NInput, NModal, NPopconfirm, NSelect } from 'naive-ui'
import type { Group, Item } from '../types'
const props = defineProps<{ items: Item[]; groups: Group[]; busy: boolean; loading: boolean }>()
const emit = defineEmits<{ note: [id: string, note: string]; move: [id: string, groupId: string]; remove: [id: string]; order: [index: number, direction: number] }>()
const editing = ref<Item>(), note = ref(''), destination = ref<string | null>(null), mode = ref<'note' | 'move'>('note')
function edit(item: Item, kind: 'note' | 'move') { editing.value = item; mode.value = kind; note.value = item.note ?? ''; destination.value = null }
function save() {
  if (!editing.value) return
  if (mode.value === 'note') emit('note', editing.value.id, note.value)
  else if (destination.value !== null) emit('move', editing.value.id, destination.value)
  editing.value = undefined
}
</script>
<template>
  <div class="table-scroll"><table class="data-table"><thead><tr><th>证券</th><th>市场 / 类型</th><th>备注</th><th>操作</th></tr></thead><tbody><tr v-for="(item,index) in items" :key="item.id"><td><strong>{{ item.security.symbol }}</strong><small>{{ item.security.name }}</small></td><td>{{ item.security.exchange }}<small>{{ item.security.security_type }} · {{ item.security.currency }}</small></td><td class="note-cell">{{ item.note || '—' }}</td><td><div class="row-actions"><NButton size="tiny" :disabled="busy || index === 0" aria-label="成员上移" @click="emit('order',index,-1)">↑</NButton><NButton size="tiny" :disabled="busy || index === items.length-1" aria-label="成员下移" @click="emit('order',index,1)">↓</NButton><NButton size="tiny" :disabled="busy" @click="edit(item,'note')">备注</NButton><NButton size="tiny" :disabled="busy || groups.length < 2" @click="edit(item,'move')">移动</NButton><NPopconfirm :disabled="busy" @positive-click="emit('remove',item.id)"><template #trigger><NButton size="tiny" :disabled="busy">移除</NButton></template>确认从当前分组移除 {{ item.security.symbol }}？</NPopconfirm></div></td></tr></tbody></table></div>
  <p v-if="!items.length" class="small-empty">{{ loading ? '正在加载成员…' : '分组暂无证券，请搜索已录入的主数据并添加。' }}</p>
  <NModal :show="!!editing" preset="card" :title="mode === 'note' ? '编辑备注' : '移动到其他分组'" class="editor-modal" @update:show="value => { if (!value) editing = undefined }"><form class="entry-form" @submit.prevent="save"><NInput v-if="mode === 'note'" v-model:value="note" type="textarea" :maxlength="500" aria-label="成员备注" /><NSelect v-else v-model:value="destination" placeholder="选择目标分组" :options="props.groups.filter(group => group.id !== editing?.group_id).map(group => ({label:group.name,value:group.id}))" /><NButton type="primary" attr-type="submit" :disabled="busy || (mode === 'move' && destination === null)">保存</NButton></form></NModal>
</template>
