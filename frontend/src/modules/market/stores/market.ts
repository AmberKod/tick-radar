import { ref, watch } from 'vue'
import { defineStore } from 'pinia'
import * as api from '../api'
import type { Market, QuoteDTO } from '../types'
import { errorMessage } from '../../../shared/api/client'
import { createQuoteSubscription } from './subscription'
export const useMarketStore = defineStore('market', () => {
  const subscription = createQuoteSubscription()
  const { quotes, checkedAt, error: quoteError, state: connectionState, stateLabel: connectionLabel } = subscription
  const quote = ref<QuoteDTO | null>(null)
  const groups = ref<Awaited<ReturnType<typeof api.getGroups>>['groups']>([]), groupId = ref('')
  const loading = ref(false), error = ref(''), actionMessage = ref('')
  let lookupController: AbortController | undefined, boardController: AbortController | undefined, groupsController: AbortController | undefined
  let lookupRevision = 0, boardRevision = 0, sessionEpoch = 0
  function clearPrivate() {
    sessionEpoch++; boardRevision++; boardController?.abort(); groupsController?.abort()
    subscription.stop(); groups.value = []; groupId.value = ''; actionMessage.value = ''
  }
  function clear() {
    clearPrivate(); lookupRevision++; lookupController?.abort(); quote.value = null; loading.value = false; error.value = ''
  }
  watch(groupId, () => { boardRevision++; boardController?.abort(); subscription.stop() }, { flush: 'sync' })
  async function lookup(symbol: string) {
    const version = ++lookupRevision, controller = new AbortController()
    lookupController?.abort(); lookupController = controller
    loading.value = true; error.value = ''; actionMessage.value = ''; quote.value = null
    try { const result = await api.getQuote(symbol.trim().toUpperCase(), { signal: controller.signal }); if (version === lookupRevision) quote.value = result }
    catch (cause) { if (version === lookupRevision && !controller.signal.aborted) { quote.value = null; error.value = errorMessage(cause) } }
    finally { if (version === lookupRevision) loading.value = false }
  }
  async function loadGroups() {
    const epoch = sessionEpoch, controller = new AbortController()
    groupsController?.abort(); groupsController = controller
    try {
      const result = await api.getGroups({ signal: controller.signal })
      if (epoch !== sessionEpoch || controller.signal.aborted) return
      groups.value = result.groups.slice().sort((a, b) => a.position - b.position)
      if (!groups.value.some(group => group.id === groupId.value)) groupId.value = groups.value[0]?.id || ''
    } catch (cause) { if (epoch === sessionEpoch && !controller.signal.aborted) quoteError.value = errorMessage(cause) }
  }
  async function loadBoard() {
    const selected = groupId.value, epoch = sessionEpoch, version = ++boardRevision, controller = new AbortController()
    boardController?.abort(); boardController = controller
    if (!selected) { quotes.value = []; checkedAt.value = ''; return }
    const current = () => epoch === sessionEpoch && version === boardRevision && selected === groupId.value && !controller.signal.aborted
    quoteError.value = ''
    try {
      const { items } = await api.getItems(selected, { signal: controller.signal })
      if (!current()) return
      const symbols = items.slice(0, 50).map(item => item.security.symbol)
      subscription.subscribe(symbols)
    } catch (cause) { if (current()) quoteError.value = errorMessage(cause) }
  }
  async function refresh() {
    if (!quotes.value.length) return
    const epoch = sessionEpoch, selected = groupId.value
    quoteError.value = ''
    try { await api.refreshQuotes(quotes.value.map(item => item.symbol)) }
    catch (cause) { if (epoch === sessionEpoch && selected === groupId.value) quoteError.value = errorMessage(cause) }
  }
  function visibleQuotes(market: Market | 'ALL') { return market === 'ALL' ? quotes.value : quotes.value.filter(item => item.market === market) }
  window.addEventListener('auth:cleared', clearPrivate)
  return { quote, quotes, checkedAt, groups, groupId, loading, error, quoteError, actionMessage, lookup, loadGroups, loadBoard, refresh, visibleQuotes, connectionState, connectionLabel, clearPrivate, clear }
})
