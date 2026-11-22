import type { components } from '../../../generated/api-schema'
import { ApiError, baseUrl, getAccessToken, getSessionGeneration, responseError } from '../../../shared/api/client'

export type QuoteStreamEvent = components['schemas']['QuoteStreamEvent']
export type StreamState = 'idle' | 'connecting' | 'connected' | 'reconnecting' | 'error'
const MAX_BUFFER = 512 * 1024

// 每行及未完成事件共享上限，避免无换行或无空行的流无限增长。
export function createSSEParser(emit: (event: string, data: string) => void) {
  let line = '', event = '', data: string[] = [], size = 0, skipLF = false
  function endLine() {
    if (!line) {
      if (data.length) emit(event || 'message', data.join('\n'))
      event = ''; data = []; size = 0
    } else if (!line.startsWith(':')) {
      const colon = line.indexOf(':'), field = colon < 0 ? line : line.slice(0, colon)
      const value = colon < 0 ? '' : line.slice(colon + 1).replace(/^ /, '')
      if (field === 'event') event = value
      if (field === 'data') data.push(value)
    }
    line = ''
  }
  return (chunk: string) => {
    for (const char of chunk) {
      if (skipLF && char === '\n') { skipLF = false; continue }
      skipLF = false
      const code = char.codePointAt(0)!
      size += code <= 0x7f ? 1 : code <= 0x7ff ? 2 : code <= 0xffff ? 3 : 4
      if (size > MAX_BUFFER) throw new Error('行情流事件超过大小限制')
      if (char === '\r' || char === '\n') { endLine(); skipLF = char === '\r' }
      else line += char
    }
  }
}
function delay(ms: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    const abort = () => { clearTimeout(timer); reject(signal.reason); signal.removeEventListener('abort', abort) }
    const timer = setTimeout(() => { signal.removeEventListener('abort', abort); resolve() }, ms)
    signal.addEventListener('abort', abort, { once: true })
    if (signal.aborted) abort()
  })
}
export async function streamQuotes(symbols: string[], options: {
  signal: AbortSignal
  onEvent: (event: QuoteStreamEvent) => void
  onState: (state: StreamState) => void
  onError: (error: unknown) => void
}) {
  const { signal } = options
  const codes = [...new Set(symbols.map(symbol => symbol.trim().toUpperCase()))].slice(0, 50)
  if (!codes.length || signal.aborted) return
  let attempt = 0
  while (!signal.aborted) {
    options.onState(attempt ? 'reconnecting' : 'connecting')
    const controller = new AbortController(), requestId = crypto.randomUUID(), token = getAccessToken(), generation = getSessionGeneration()
    let reader: ReadableStreamDefaultReader<Uint8Array> | undefined, timer: ReturnType<typeof setTimeout> | undefined
    let receivedSnapshot = false
    const abort = () => { controller.abort(); void reader?.cancel().catch(() => {}) }
    const arm = () => { clearTimeout(timer); timer = setTimeout(abort, 45_000) }
    signal.addEventListener('abort', abort, { once: true })
    window.addEventListener('offline', abort)
    try {
      signal.throwIfAborted(); arm()
      const response = await fetch(`${baseUrl}/events/stream?${new URLSearchParams({ symbols: codes.join(',') })}`, {
        signal: controller.signal,
        headers: { Authorization: `Bearer ${token}`, 'X-Request-ID': requestId, Accept: 'text/event-stream' },
      })
      if (!response.ok) throw await responseError(response, requestId, token, generation, controller.signal)
      if (!response.headers.get('Content-Type')?.includes('text/event-stream') || !response.body) throw new Error('行情流响应格式无效')
      reader = response.body.getReader()
      const decoder = new TextDecoder()
      const parse = createSSEParser((event, data) => {
        if (signal.aborted || controller.signal.aborted) return
        if (!['snapshot', 'quote.updated', 'heartbeat', 'error'].includes(event)) return
        const envelope = JSON.parse(data) as QuoteStreamEvent
        if (envelope.event !== event || envelope.schema_version !== 1 || !Array.isArray(envelope.quotes)) throw new Error('行情流事件格式无效')
        if (event === 'error') throw new ApiError(envelope.error?.message || '行情流暂不可用', 0, envelope.error?.code || 'STREAM_ERROR', requestId)
        if (!receivedSnapshot && event !== 'snapshot') throw new Error('行情流缺少初始快照')
        if (event === 'snapshot') { receivedSnapshot = true; options.onState('connected') }
        options.onEvent(envelope)
      })
      while (!signal.aborted) {
        arm()
        const { done, value } = await reader.read()
        if (done) { parse(decoder.decode()); break }
        parse(decoder.decode(value, { stream: true }))
      }
      if (!signal.aborted) throw new Error('行情连接已断开')
    } catch (cause) {
      if (signal.aborted) break
      if (cause instanceof ApiError && (cause.status === 401 || cause.code === 'AUTH_NOT_CONFIGURED')) {
        options.onState('error'); options.onError(cause); return
      }
      // 短暂断线仅显示连接状态，不重复弹出错误。
      options.onState('reconnecting')
    } finally {
      clearTimeout(timer); signal.removeEventListener('abort', abort); window.removeEventListener('offline', abort)
      controller.abort(); await reader?.cancel().catch(() => {}); reader?.releaseLock()
    }
    if (signal.aborted) break
    const backoff = [1000, 2000, 4000, 8000, 15000][Math.min(attempt++, 4)]!
    try { await delay(backoff + Math.floor(Math.random() * 200), signal) } catch { break }
  }
}
