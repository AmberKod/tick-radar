<script setup lang="ts">
import { ref } from 'vue'
import { NAlert, NButton, NInput } from 'naive-ui'
import { useAuthStore } from '../../auth'
const auth = useAuthStore(), token = ref('')
async function submit() { const value = token.value; token.value = ''; await auth.login(value) }
</script>
<template>
  <form v-if="!auth.authenticated" class="entry-form" @submit.prevent="submit"><p>加入自选需要验证单用户访问 Token。Token 仅保存在当前页面内存。</p><div class="toolbar"><NInput v-model:value="token" type="password" autocomplete="off" aria-label="访问 Token" placeholder="输入访问 Token" /><NButton type="primary" attr-type="submit" :loading="auth.loading" :disabled="auth.loading || !token.trim()">验证</NButton></div><NAlert v-if="auth.error" type="error">{{ auth.error }}</NAlert></form>
  <slot v-else />
</template>
