import { afterEach, describe, expect, it, vi } from 'vitest'
import { createSSEParser, streamQuotes } from '../src/modules/market/api/stream'
import { getAccessToken, setAccessToken } from '../src/shared/api/client'
import { createQuoteSubscription } from '../src/modules/market/stores/subscription'
const encoder = new TextEncoder()
const envelope = (event = 'snapshot') => ({ id: '1', event, schema_version: 1, symbols: ['US:AAPL'], quotes: [], checked_at: '2026-01-01T00:00:00Z', observation_only: true, error: null })
const frame = (event = 'snapshot') => `event: ${event}\r\ndata: ${JSON.stringify(envelope(event))}\r\n\r\n`
function response(text: string, close = false) {
  return new Response(new ReadableStream({ start(controller) { controller.enqueue(encoder.encode(text)); if (close) controller.close() } }), { headers: { 'Content-Type': 'text/event-stream' } })
}
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); setAccessToken('') })
describe('行情 SSE', () => {
  it('跨 chunk 处理 CRLF、多行 data 和 UTF8', () => {
    const events: unknown[] = [], parse = createSSEParser((event, data) => events.push([event, data]))
    const bytes = encoder.encode(':注释\r\nevent: snapshot\r\ndata: 中文\r\ndata: 第二行\r\n\r\n')
    const decoder = new TextDecoder()
    for (const byte of bytes) parse(decoder.decode(new Uint8Array([byte]), { stream: true }))
    expect(events).toEqual([['snapshot', '中文\n第二行']])
  })
  it('限制无换行及未结束事件的 buffer', () => {
    const parse = createSSEParser(() => {})
    expect(() => parse('x'.repeat(512 * 1024 + 1))).toThrow('大小限制')
    const multiline = createSSEParser(() => {})
    expect(() => multiline('data: x\n'.repeat(70000))).toThrow('大小限制')
  })
  it('仅从内存 Token 设置授权头，退出取消 reader 且不重连', async () => {
    vi.useFakeTimers(); setAccessToken('private-token')
    const cancel = vi.fn(), fetchMock = vi.fn().mockResolvedValue(new Response(new ReadableStream({ start(c) { c.enqueue(encoder.encode(frame())) }, cancel }), { headers: { 'Content-Type': 'text/event-stream' } }))
    vi.stubGlobal('fetch', fetchMock)
    const controller = new AbortController(), onEvent = vi.fn(), onState = vi.fn()
    const pending = streamQuotes(['US:AAPL', 'US:AAPL'], { signal: controller.signal, onEvent, onState, onError: vi.fn() })
    await vi.advanceTimersByTimeAsync(0)
    expect(fetchMock.mock.calls[0]?.[0]).not.toContain('private-token')
    expect(fetchMock.mock.calls[0]?.[1].headers.Authorization).toBe('Bearer private-token')
    expect(onEvent).toHaveBeenCalledTimes(1); expect(onState).toHaveBeenCalledWith('connected')
    controller.abort(); await pending; await vi.advanceTimersByTimeAsync(60_000)
    expect(cancel).toHaveBeenCalled(); expect(fetchMock).toHaveBeenCalledTimes(1)
  })
  it('重连必须先收到 snapshot，并且退避可取消', async () => {
    vi.useFakeTimers(); const fetchMock = vi.fn().mockResolvedValueOnce(response(frame(), true)).mockResolvedValueOnce(response(frame('quote.updated')))
    vi.stubGlobal('fetch', fetchMock)
    const controller = new AbortController(), onEvent = vi.fn()
    const pending = streamQuotes(['US:AAPL'], { signal: controller.signal, onEvent, onState: vi.fn(), onError: vi.fn() })
    await vi.advanceTimersByTimeAsync(1250)
    expect(fetchMock).toHaveBeenCalledTimes(2); expect(onEvent).toHaveBeenCalledTimes(1)
    controller.abort(); await pending; await vi.advanceTimersByTimeAsync(60_000)
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })
  it('旧 Token 的迟到401不能注销新 Token且不重试', async () => {
    vi.useFakeTimers(); setAccessToken('old')
    let finish!: (response: Response) => void
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(resolve => { finish = resolve })))
    const controller = new AbortController(), onError = vi.fn()
    const pending = streamQuotes(['US:AAPL'], { signal: controller.signal, onEvent: vi.fn(), onState: vi.fn(), onError })
    setAccessToken('new'); finish(new Response(JSON.stringify({ code: 'UNAUTHORIZED' }), { status: 401 }))
    await pending; await vi.advanceTimersByTimeAsync(60_000)
    expect(getAccessToken()).toBe('new'); expect(fetch).toHaveBeenCalledTimes(1); expect(onError).toHaveBeenCalledTimes(1)
  })
  it('浏览器离线立即中止旧流并进入重连', async () => {
    vi.useFakeTimers()
    const cancel = vi.fn(), onState = vi.fn()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(new ReadableStream({ start(c) { c.enqueue(encoder.encode(frame())) }, cancel }), { headers: { 'Content-Type': 'text/event-stream' } })))
    const controller = new AbortController()
    const pending = streamQuotes(['US:AAPL'], { signal: controller.signal, onEvent: vi.fn(), onState, onError: vi.fn() })
    await vi.advanceTimersByTimeAsync(0)
    window.dispatchEvent(new Event('offline')); await vi.advanceTimersByTimeAsync(0)
    expect(cancel).toHaveBeenCalled(); expect(onState).toHaveBeenLastCalledWith('reconnecting')
    controller.abort(); await pending
  })
  it('认证未配置停止重连', async () => {
    vi.useFakeTimers(); vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ code: 'AUTH_NOT_CONFIGURED' }), { status: 503 })))
    await streamQuotes(['US:AAPL'], { signal: new AbortController().signal, onEvent: vi.fn(), onState: vi.fn(), onError: vi.fn() })
    await vi.advanceTimersByTimeAsync(60_000); expect(fetch).toHaveBeenCalledTimes(1)
  })
  it('headers 和读取空闲45秒超时重连', async () => {
    vi.useFakeTimers()
    const fetchMock = vi.fn().mockImplementationOnce((_url, options) => new Promise((_resolve, reject) => options.signal.addEventListener('abort', () => reject(new Error('aborted'))))).mockResolvedValue(response(frame()))
    vi.stubGlobal('fetch', fetchMock)
    const controller = new AbortController()
    const pending = streamQuotes(['US:AAPL'], { signal: controller.signal, onEvent: vi.fn(), onState: vi.fn(), onError: vi.fn() })
    await vi.advanceTimersByTimeAsync(46_250); expect(fetch).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(47_250); expect(fetch).toHaveBeenCalledTimes(3)
    controller.abort(); await pending
  })
  it('相同 symbols 不重建连接，heartbeat 不清空快照', async () => {
    vi.useFakeTimers()
    let stream!: ReadableStreamDefaultController<Uint8Array>
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(new ReadableStream({ start(c) { stream = c } }), { headers: { 'Content-Type': 'text/event-stream' } })))
    const subscription = createQuoteSubscription(); subscription.subscribe(['US:AAPL']); await vi.advanceTimersByTimeAsync(0)
    const snapshot = { ...envelope(), quotes: [{ symbol: 'US:AAPL' }] }
    stream.enqueue(encoder.encode(`event: snapshot\ndata: ${JSON.stringify(snapshot)}\n\n${frame('heartbeat')}`))
    await vi.advanceTimersByTimeAsync(0); subscription.subscribe(['US:AAPL'])
    expect(subscription.quotes.value).toEqual(snapshot.quotes); expect(fetch).toHaveBeenCalledTimes(1)
    subscription.stop(); await vi.advanceTimersByTimeAsync(60_000); expect(fetch).toHaveBeenCalledTimes(1)
  })
})
