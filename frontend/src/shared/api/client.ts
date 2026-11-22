export interface ApiErrorBody {
  code?: string
  message?: string
  details?: unknown
  trace_id?: string
}
export class ApiError extends Error {
  constructor(message: string, public readonly status: number, public readonly code: string, public readonly requestId: string, public readonly detail?: unknown) {
    super(message)
    this.name = 'ApiError'
  }
}
export interface RequestOptions { signal?: AbortSignal; timeoutMs?: number }
let accessToken = '', sessionGeneration = 0
export const getAccessToken = () => accessToken
export const getSessionGeneration = () => sessionGeneration
export const setAccessToken = (token: string) => { accessToken = token; sessionGeneration++ }
export const baseUrl = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '')
export async function responseError(response: Response, requestId: string, requestToken: string, requestGeneration: number, signal?: AbortSignal): Promise<ApiError> {
  signal?.throwIfAborted()
  const body = await response.json().catch(cause => {
    signal?.throwIfAborted()
    if (cause instanceof Error && cause.name === 'AbortError') throw cause
    return {}
  }) as ApiErrorBody
  signal?.throwIfAborted()
  const id = response.headers.get('X-Request-ID') || body.trace_id || requestId
  // Token值可重复使用，会话代数仍必须一致才允许旧请求注销当前会话。
  if (response.status === 401 && sessionGeneration === requestGeneration && accessToken === requestToken) {
    setAccessToken('')
    window.dispatchEvent(new CustomEvent('api:unauthorized'))
  }
  return new ApiError(body.message || `请求失败（HTTP ${response.status}）`, response.status, body.code || 'HTTP_ERROR', id, body.details)
}
export async function apiRequest<T>(method: 'GET' | 'POST' | 'PUT' | 'DELETE', path: string, data?: unknown, options: RequestOptions = {}): Promise<T> {
  const controller = new AbortController()
  const requestId = crypto.randomUUID()
  const requestToken = accessToken, requestGeneration = sessionGeneration
  let timedOut = false
  const abort = () => controller.abort(options.signal?.reason)
  if (options.signal?.aborted) abort()
  else options.signal?.addEventListener('abort', abort, { once: true })
  const timeout = setTimeout(() => { timedOut = true; controller.abort() }, options.timeoutMs ?? 10_000)
  try {
    controller.signal.throwIfAborted()
    const response = await fetch(`${baseUrl}${path}`, {
      method, signal: controller.signal,
      headers: { Accept: 'application/json', 'X-Request-ID': requestId, ...(requestToken ? { Authorization: `Bearer ${requestToken}` } : {}), ...(data !== undefined ? { 'Content-Type': 'application/json' } : {}) },
      ...(data !== undefined ? { body: JSON.stringify(data) } : {}),
    })
    if (!response.ok) {
      throw await responseError(response, requestId, requestToken, requestGeneration, controller.signal)
    }
    if (response.status === 204) return undefined as T
    return await response.json() as T
  } catch (error) {
    if (timedOut) throw new ApiError('请求超时，请检查服务连接后重试', 0, 'TIMEOUT', requestId)
    if (controller.signal.aborted) throw error
    if (error instanceof ApiError) throw error
    throw new ApiError('无法连接服务，请检查后端是否已启动', 0, 'NETWORK_ERROR', requestId)
  } finally {
    clearTimeout(timeout)
    options.signal?.removeEventListener('abort', abort)
  }
}
export const apiGet = <T>(path: string, options?: RequestOptions) => apiRequest<T>('GET', path, undefined, options)
export const apiPost = <T>(path: string, data?: unknown, options?: RequestOptions) => apiRequest<T>('POST', path, data, options)
export const apiPut = <T>(path: string, data?: unknown, options?: RequestOptions) => apiRequest<T>('PUT', path, data, options)
export const apiDelete = <T = void>(path: string, options?: RequestOptions) => apiRequest<T>('DELETE', path, undefined, options)
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    const friendly = error.status === 409 ? '操作冲突：名称或证券可能重复，非空分组不能删除，请刷新后重试。' : error.status === 422 ? '录入信息不符合要求，请检查字段。' : error.message
    return `${friendly}（${error.code}；请求 ID：${error.requestId}）`
  }
  return error instanceof Error ? error.message : '操作失败，请重试'
}
