<script setup lang="ts">
import { ref, watch } from 'vue'
import { NAlert, NButton, NInput } from 'naive-ui'
import { useAuthStore } from '../stores/auth'
const auth = useAuthStore()
const token = ref('')
watch(() => auth.epoch, () => { token.value = '' }, { flush: 'sync' })
function submit() {
  const value = token.value
  token.value = ''
  void auth.login(value)
}
</script>
<template>
  <slot v-if="auth.authenticated" :key="auth.epoch" />
  <section v-else class="panel token-panel">
    <div class="eyebrow">PRIVATE WORKSPACE</div><h2>验证访问 Token</h2>
    <p>私有业务与配置管理需要单用户访问 Token。仅在当前页面内存中保存，刷新或退出后需重新输入。</p>
    <form class="toolbar" @submit.prevent="submit">
      <NInput v-model:value="token" type="password" autocomplete="off" placeholder="输入服务端配置的 Token" :disabled="auth.loading" aria-label="访问 Token" />
      <NButton type="primary" attr-type="submit" :loading="auth.loading" :disabled="auth.loading || !token.trim()">验证并进入</NButton>
    </form>
    <NAlert v-if="auth.error" type="error" class="feedback-alert">{{ auth.error }}</NAlert>
    <p class="muted">系统概览、公共健康检查与历史行情查询无需验证。</p>
  </section>
</template>
