import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import CalendarStatusPanel from '../src/modules/market/components/CalendarStatusPanel.vue'
import * as api from '../src/modules/market/api'
import { setAccessToken } from '../src/shared/api/client'
import type { MarketCalendarStatus } from '../src/modules/market/types'

const status: MarketCalendarStatus = {
  exchange: 'SSE', market: 'CN', state: 'REGULAR_SESSION', timezone: 'Asia/Shanghai',
  local_time: '2026-06-01T10:00:00+08:00', checked_at: '2026-06-01T02:00:00Z',
  session_date: '2026-06-01', is_trading_day: true, is_early_close: false,
  session_open: '2026-06-01T09:30:00+08:00', break_start: '2026-06-01T11:30:00+08:00',
  break_end: '2026-06-01T13:00:00+08:00', session_close: '2026-06-01T15:00:00+08:00',
  next_open: '2026-06-01T13:00:00+08:00', next_close: '2026-06-01T15:00:00+08:00',
  calendar_name: 'reviewed calendar', calendar_version: '2026.1', coverage_start: '2026-01-01', coverage_end: '2026-12-31',
  basis: 'CN_2026_REVIEWED_SHARED', reason: '已核验常规交易', warnings: ['不覆盖个股停牌'], scope: 'REGULAR_EQUITIES_ONLY',
}
const response = () => new Response(JSON.stringify({ statuses: [status], checked_at: status.checked_at }), { status: 200 })
beforeEach(() => { vi.useFakeTimers(); setAccessToken('') })
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

describe('市场交易日历', () => {
  it('匿名读取真实接口，展示七所、复市时间和可展开来源', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response()); vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(CalendarStatusPanel); await flushPromises()
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/v1/market-calendar/statuses')
    expect(fetchMock.mock.calls[0]?.[1].headers.Authorization).toBeUndefined()
    expect(wrapper.findAll('.calendar-card')).toHaveLength(7)
    expect(wrapper.text()).toContain('北交所'); expect(wrapper.text()).toContain('中国香港')
    expect(wrapper.text()).toContain('常规交易'); expect(wrapper.text()).toContain('13:00:00 GMT+8')
    expect(wrapper.find('details').text()).toContain('reviewed calendar · 2026.1')
    expect(wrapper.text()).toContain('集合竞价、盘前盘后交易与个股停牌')
    wrapper.unmount()
  })
  it('HTTP错误可见并清除旧常规交易状态，后续轮询可恢复', async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(response()).mockResolvedValueOnce(new Response(JSON.stringify({ message: '服务暂不可用' }), { status: 503 })).mockResolvedValueOnce(response())
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(CalendarStatusPanel); await flushPromises()
    expect(wrapper.find('[data-state="REGULAR_SESSION"]').exists()).toBe(true)
    await vi.advanceTimersByTimeAsync(30_000); await flushPromises()
    expect(wrapper.find('[role="alert"]').text()).toContain('服务暂不可用')
    expect(wrapper.find('[data-state="REGULAR_SESSION"]').exists()).toBe(false)
    expect(wrapper.findAll('[data-state="UNKNOWN"]')).toHaveLength(7)
    await vi.advanceTimersByTimeAsync(30_000); await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.find('[data-state="REGULAR_SESSION"]').exists()).toBe(true)
    wrapper.unmount()
  })
  it('慢请求跨越多个周期不重叠，卸载取消且迟到结果不回填', async () => {
    let finish!: (value: Awaited<ReturnType<typeof api.getCalendarStatuses>>) => void
    const request = vi.spyOn(api, 'getCalendarStatuses').mockImplementation(() => new Promise(resolve => { finish = resolve }))
    const wrapper = mount(CalendarStatusPanel)
    await vi.advanceTimersByTimeAsync(90_000)
    expect(request).toHaveBeenCalledTimes(1)
    const signal = request.mock.calls[0]?.[0]?.signal as AbortSignal
    expect(signal.aborted).toBe(false)
    wrapper.unmount(); expect(signal.aborted).toBe(true)
    const readStatuses = vi.fn(() => [status])
    finish({ get statuses() { return readStatuses() }, checked_at: status.checked_at }); await flushPromises()
    expect(readStatuses).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(60_000)
    expect(request).toHaveBeenCalledTimes(1)
  })
})
