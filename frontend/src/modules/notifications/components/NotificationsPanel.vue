<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useNotifications, canRetry } from '../composables/useNotifications'
const notifications = useNotifications()
const { inbox, outbox, deliveries, selected, unreadOnly, status, inboxPage, outboxPage, busy, error, notice } = notifications
const tab = ref('inbox')
const time = (value: string | null | undefined) => value ? new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) : '—'
const statusLabels = { PENDING: '待投递', RETRY: '待重试', SENT: '已投递', DEAD: '投递终止' }
onMounted(() => { void notifications.refresh() })
</script>
<template>
  <section class="panel alert-business-panel" data-testid="notifications-panel">
    <h2>站内通知与投递</h2><p>仅站内 IN_APP 通道，不发送外部消息。测试通知明确标记为“站内通知测试”，不是行情触发。</p>
    <div class="toolbar"><button :disabled="busy" @click="notifications.refresh">刷新通知</button><button :disabled="busy" data-testid="notification-test" @click="notifications.test">站内通知测试</button><button :aria-pressed="tab === 'inbox'" @click="tab = 'inbox'">收件箱（未读 {{ inbox?.unread_count ?? '—' }}）</button><button :aria-pressed="tab === 'outbox'" @click="tab = 'outbox'">投递状态</button></div>
    <p>测试写入待投递，后台完成后刷新收件箱。网络失败后再次点击测试将沿用同一请求编号。</p>
    <p v-if="error" role="alert">{{ error }}</p><p v-if="notice" role="status">{{ notice }}</p>
    <template v-if="tab === 'inbox'">
      <div class="toolbar"><label class="alert-check"><input v-model="unreadOnly" type="checkbox" :disabled="busy" @change="inboxPage = 1; notifications.filter()">仅未读</label><button :disabled="busy || !inbox?.unread_count" @click="notifications.readAll">全部标为已读</button></div>
      <p v-if="!inbox?.items.length">暂无站内通知。</p><article v-for="message in inbox?.items" :key="message.id" class="alert-message"><h3>{{ message.title }} <small>{{ message.read_at ? '已读' : '未读' }}</small></h3><p>{{ message.body }}</p><small>{{ time(message.created_at) }} · 北京时间</small><button :disabled="busy || !!message.read_at" @click="notifications.read(message.id)">标为已读</button></article>
      <div v-if="inbox" class="toolbar"><button :disabled="busy || inboxPage <= 1" @click="inboxPage--; notifications.filter()">上一页</button><span>第 {{ inboxPage }} 页，共 {{ inbox.total }} 条</span><button :disabled="busy || inboxPage * inbox.page_size >= inbox.total" @click="inboxPage++; notifications.filter()">下一页</button></div>
    </template>
    <template v-else>
      <label>状态筛选<select v-model="status" :disabled="busy" aria-label="投递状态筛选" @change="outboxPage = 1; notifications.filter()"><option value="">全部</option><option v-for="(label, key) in statusLabels" :key="key" :value="key">{{ label }}</option></select></label>
      <p v-if="!outbox?.items.length">暂无投递记录。</p><div v-else class="alert-scroll"><table><thead><tr><th>通知</th><th>投递状态</th><th>时间 / 错误</th><th>操作</th></tr></thead><tbody><tr v-for="item in outbox.items" :key="item.id"><td>{{ item.title }}<small>{{ item.body }}</small><small>{{ item.channel }}</small></td><td>{{ statusLabels[item.status] }}<small>尝试 {{ item.attempts }} / {{ item.max_attempts }}</small></td><td>创建 {{ time(item.created_at) }}<small>下次 {{ time(item.next_attempt_at) }}</small><small>成功 {{ time(item.sent_at) }}</small><small>{{ item.last_error || '无错误记录' }}</small></td><td><button :disabled="busy" @click="notifications.inspect(item.id)">查看投递尝试</button><button :disabled="busy || !canRetry(item)" @click="notifications.retry(item)">手动重试</button></td></tr></tbody></table></div>
      <p>待重试或投递终止后可手动重试，增加 5 次尝试额度并保留历史；已投递不能重试。</p>
      <div v-if="outbox" class="toolbar"><button :disabled="busy || outboxPage <= 1" @click="outboxPage--; notifications.filter()">上一页</button><span>第 {{ outboxPage }} 页，共 {{ outbox.total }} 条</span><button :disabled="busy || outboxPage * outbox.page_size >= outbox.total" @click="outboxPage++; notifications.filter()">下一页</button></div>
      <section v-if="selected"><h3>投递尝试</h3><p class="alert-id">{{ selected }}</p><p v-if="!deliveries?.items.length">暂无尝试记录。</p><p v-for="delivery in deliveries?.items" :key="delivery.id">第 {{ delivery.attempt }} 次 · {{ delivery.status === 'SENT' ? '成功' : '失败' }} · {{ delivery.error_code || '无错误' }} · {{ time(delivery.created_at) }}</p></section>
    </template>
  </section>
</template>
