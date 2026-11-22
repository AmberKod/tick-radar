import { ref } from 'vue'
import { defineStore } from 'pinia'
import { ApiError, errorMessage, setAccessToken } from '../../../shared/api/client'
import { verifySession } from '../api'
export const useAuthStore = defineStore('auth', () => {
  const authenticated = ref(false)
  const loading = ref(false)
  const error = ref('')
  const epoch = ref(0)
  let controller: AbortController | undefined
  function logout() {
    controller?.abort()
    controller = undefined
    setAccessToken('')
    authenticated.value = false
    loading.value = false
    epoch.value++
    window.dispatchEvent(new CustomEvent('auth:cleared'))
  }
  window.addEventListener('api:unauthorized', () => { logout(); error.value = '访问 Token 已失效，请重新验证。' })
  async function login(token: string) {
    logout()
    error.value = ''
    if (!token.trim()) { error.value = '请输入访问 Token'; return }
    const current = new AbortController()
    controller = current
    loading.value = true
    setAccessToken(token.trim())
    try {
      const session = await verifySession(current.signal)
      if (current.signal.aborted) return
      if (!session.authenticated) throw new Error('Token 验证未通过')
      authenticated.value = true
    } catch (cause) {
      if (current.signal.aborted) return
      setAccessToken('')
      error.value = cause instanceof ApiError && cause.code === 'AUTH_NOT_CONFIGURED' ? 'AUTH_NOT_CONFIGURED：后端尚未配置访问 Token，请先完成服务端配置。' : errorMessage(cause)
    } finally {
      if (controller === current) { loading.value = false; controller = undefined }
    }
  }
  return { authenticated, loading, error, epoch, login, logout }
})
