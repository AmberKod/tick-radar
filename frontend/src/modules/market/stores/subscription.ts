import { computed, ref } from 'vue'
import type { QuoteDTO } from '../types'
import { streamQuotes, type StreamState } from '../api/stream'
import { errorMessage } from '../../../shared/api/client'

export const streamLabels: Record<StreamState, string> = { idle: '未订阅', connecting: '正在连接行情', connected: '行情已连接', reconnecting: '行情重连中', error: '行情连接失败' }
export function createQuoteSubscription() {
  const quotes = ref<QuoteDTO[]>([]), checkedAt = ref(''), error = ref(''), state = ref<StreamState>('idle')
  const stateLabel = computed(() => streamLabels[state.value])
  let controller: AbortController | undefined, key = '', revision = 0
  function stop() {
    revision++; controller?.abort(); controller = undefined; key = ''
    quotes.value = []; checkedAt.value = ''; error.value = ''; state.value = 'idle'
  }
  function subscribe(symbols: string[]) {
    const codes = [...new Set(symbols.map(symbol => symbol.trim().toUpperCase()))].slice(0, 50)
    const nextKey = codes.join(',')
    if (nextKey === key && state.value !== 'error') return
    stop()
    if (!codes.length) return
    key = nextKey; controller = new AbortController()
    const version = revision
    void streamQuotes(codes, {
      signal: controller.signal,
      onState: value => { if (version === revision) state.value = value },
      onError: cause => { if (version === revision) error.value = errorMessage(cause) },
      onEvent: event => {
        if (version !== revision || event.event === 'heartbeat') return
        quotes.value = event.quotes; checkedAt.value = event.checked_at; error.value = ''
      },
    })
  }
  return { quotes, checkedAt, error, state, stateLabel, subscribe, stop }
}
