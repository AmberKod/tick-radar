import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { reactive } from 'vue'
import IndicatorProfilePanel from '../src/modules/indicators/components/IndicatorProfilePanel.vue'
import HistoryPage from '../src/modules/market/views/HistoryPage.vue'
import { useAuthStore } from '../src/modules/auth/stores/auth'
import { setAccessToken } from '../src/shared/api/client'
import type { IndicatorParameters, IndicatorProfile } from '../src/modules/indicators/types'

const route = reactive<{ query: Record<string, string> }>({ query: {} })
vi.mock('vue-router', () => ({ useRoute: () => route, useRouter: () => ({ push: async (value: { query: Record<string, string> }) => { route.query = value.query } }) }))
vi.mock('../src/modules/market/components/HistoryChart.vue', () => ({ default: { props: ['parameters'], template: '<div class="chart-snapshot">{{ parameters?.ma_period }}</div>' } }))
vi.mock('naive-ui', () => ({
  NButton: { props: ['disabled', 'attrType'], template: '<button :disabled="disabled" :type="attrType || \'button\'"><slot /></button>' },
  NInput: { props: ['value', 'type'], emits: ['update:value'], template: '<input :type="type || \'text\'" :value="value" @input="$emit(\'update:value\', $event.target.value)" />' },
  NSelect: { props: ['value', 'options'], emits: ['update:value'], template: '<select :value="value" @change="$emit(\'update:value\', typeof value === \'number\' ? Number($event.target.value) : $event.target.value)"><option v-for="option in options" :key="option.value" :value="option.value">{{ option.label }}</option></select>' },
  NAlert: { template: '<div><slot /></div>' },
}))
const parameters: IndicatorParameters = { ma_period: 10, macd_fast: 6, macd_slow: 13, macd_signal: 5, kdj_lookback: 13, kdj_k: 5, kdj_d: 5, atr_period: 14 }
const profile: IndicatorProfile = { id: 'profile-1', name: '我的观察', timeframe: 'day', price_adjustment: 'raw', market_scope: 'ALL', parameters: { ...parameters, ma_period: 20 }, algorithm_version: 'daily-v1', version: 3, parameter_hash: 'profile-hash', created_at: '2026-11-22T00:00:00Z', updated_at: '2026-11-22T00:00:00Z' }
const response = (data: unknown, status = 200) => new Response(status === 204 ? null : JSON.stringify(data), { status })
const wrappers: VueWrapper[] = []
function mountPanel(loggedIn = true) {
  if (loggedIn) { useAuthStore().authenticated = true; setAccessToken('secret') }
  const wrapper = mount(IndicatorProfilePanel, { props: { parameters: { ...parameters }, timeframe: 'day', adjustment: 'raw', market: 'US' } })
  wrappers.push(wrapper)
  return wrapper
}
async function click(wrapper: VueWrapper, label: string) {
  await wrapper.findAll('button').find(button => button.text() === label)!.trigger('click')
  await flushPromises()
}
async function select(wrapper: VueWrapper) {
  await flushPromises()
  await wrapper.find('[aria-label="已保存配置"]').setValue(profile.id)
}
beforeEach(() => {
  setActivePinia(createPinia()); setAccessToken(''); route.query = {}
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ items: [profile] })))
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.unstubAllGlobals() })

describe('指标配置管理', () => {
  it('未登录不发配置请求；Token验证后才读取，退出清理名称、列表与反馈', async () => {
    const wrapper = mountPanel(false)
    await flushPromises(); expect(fetch).not.toHaveBeenCalled()
    vi.mocked(fetch).mockResolvedValueOnce(response({ authenticated: true })).mockResolvedValueOnce(response({ items: [profile] }))
    await wrapper.find('[aria-label="访问 Token"]').setValue('secret')
    await wrapper.find('form').trigger('submit'); await flushPromises()
    expect(vi.mocked(fetch).mock.calls[1]![1]!.headers).toMatchObject({ Authorization: 'Bearer secret' })
    await select(wrapper)
    expect((wrapper.find('[aria-label="配置名称"]').element as HTMLInputElement).value).toBe(profile.name)
    useAuthStore().logout(); await flushPromises()
    expect(wrapper.text()).not.toContain(profile.name)
    expect(wrapper.find('[aria-label="配置名称"]').exists()).toBe(false)
  })

  it.each([
    { timeframe: 'day' as const, adjustment: 'qfq' as const, market: 'HK' as const, scope: 'ALL' },
    { timeframe: 'm15' as const, adjustment: 'vendor_unverified' as const, market: 'CN' as const, scope: 'CN' },
  ])('另存为准确保存 $timeframe 上下文和参数快照，不触发载入', async context => {
    const wrapper = mountPanel(); await flushPromises()
    await wrapper.setProps({ timeframe: context.timeframe, adjustment: context.adjustment, market: context.market }); await flushPromises()
    await wrapper.find('[aria-label="配置名称"]').setValue('  新配置  ')
    vi.mocked(fetch).mockResolvedValueOnce(response({ ...profile, name: '新配置' }))
    await click(wrapper, '另存为')
    const request = vi.mocked(fetch).mock.calls.at(-1)!
    expect(request[0]).toBe('/api/v1/indicators/profiles')
    expect(request[1]!.method).toBe('POST')
    expect(JSON.parse(request[1]!.body as string)).toEqual({ name: '新配置', timeframe: context.timeframe, price_adjustment: context.adjustment, market_scope: context.scope, parameters })
    expect(wrapper.emitted('load')).toBeUndefined()
  })

  it('选择不载入，显式载入通过单条GET读取，更新可重命名且携带版本不载入', async () => {
    const wrapper = mountPanel(); await select(wrapper)
    expect(wrapper.emitted('load')).toBeUndefined()
    vi.mocked(fetch).mockResolvedValueOnce(response(profile))
    await click(wrapper, '载入配置')
    expect(wrapper.emitted('load')).toEqual([[profile.parameters]])
    expect(wrapper.text()).toContain('点击查询后应用')
    await wrapper.find('[aria-label="配置名称"]').setValue('重命名')
    vi.mocked(fetch).mockResolvedValueOnce(response({ ...profile, name: '重命名', version: 4 }))
    await click(wrapper, '覆盖更新')
    expect(JSON.parse(vi.mocked(fetch).mock.calls.at(-1)![1]!.body as string)).toMatchObject({ name: '重命名', version: 3, parameters })
    expect(wrapper.emitted('load')).toHaveLength(1)
  })

  it.each(['PROFILE_NAME_CONFLICT', 'PROFILE_VERSION_CONFLICT', 'PROFILE_NOT_FOUND'])('%s 保留名称和参数草稿，显示服务端错误且不重试', async code => {
    const wrapper = mountPanel(); await select(wrapper)
    await wrapper.find('[aria-label="配置名称"]').setValue('保留的草稿')
    vi.mocked(fetch).mockResolvedValueOnce(response({ code, message: '服务器中文冲突说明' }, 409))
    await click(wrapper, '覆盖更新')
    expect(fetch).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('服务器中文冲突说明')
    expect((wrapper.find('[aria-label="配置名称"]').element as HTMLInputElement).value).toBe('保留的草稿')
    expect(wrapper.props('parameters')).toEqual(parameters)
    expect(wrapper.emitted('load')).toBeUndefined()
    if (code !== 'PROFILE_NAME_CONFLICT') {
      expect(wrapper.text()).toContain('刷新配置并重新选择')
      expect(wrapper.findAll('button').find(button => button.text() === '覆盖更新')!.attributes('disabled')).toBeDefined()
      vi.mocked(fetch).mockResolvedValueOnce(response({ items: [{ ...profile, version: 4 }] }))
      await click(wrapper, '刷新配置')
      expect((wrapper.find('[aria-label="配置名称"]').element as HTMLInputElement).value).toBe('保留的草稿')
      expect((wrapper.find('[aria-label="已保存配置"]').element as HTMLSelectElement).value).toBe('')
    }
  })

  it('删除须明确名称二次确认，DELETE携带版本且不修改参数', async () => {
    const wrapper = mountPanel(); await select(wrapper)
    await click(wrapper, '删除配置')
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(wrapper.find('[aria-label="确认删除配置"]').text()).toContain(profile.name)
    await click(wrapper, '取消'); expect(fetch).toHaveBeenCalledTimes(1)
    await click(wrapper, '删除配置')
    vi.mocked(fetch).mockResolvedValueOnce(response(null, 204))
    await click(wrapper, '确认删除')
    expect(fetch).toHaveBeenLastCalledWith('/api/v1/indicators/profiles/profile-1?version=3', expect.objectContaining({ method: 'DELETE' }))
    expect(wrapper.emitted('load')).toBeUndefined()
    expect(wrapper.props('parameters')).toEqual(parameters)
  })

  it('仅列当前周期、复权及兼容市场；上下文切换清空选择和迟到响应', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(response({ items: [profile, { ...profile, id: 'hk', market_scope: 'HK' }, { ...profile, id: 'qfq', price_adjustment: 'qfq' }, { ...profile, id: 'minute', timeframe: 'm15' }] }))
    const wrapper = mountPanel(); await select(wrapper)
    expect(wrapper.findAll('[aria-label="已保存配置"] option')).toHaveLength(2)
    let finish!: (response: Response) => void
    vi.mocked(fetch).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    await click(wrapper, '载入配置')
    const signal = vi.mocked(fetch).mock.calls.at(-1)![1]!.signal!
    vi.mocked(fetch).mockResolvedValueOnce(response({ items: [] }))
    await wrapper.setProps({ adjustment: 'qfq' }); await flushPromises()
    expect(signal.aborted).toBe(true)
    finish(response(profile)); await flushPromises()
    expect(wrapper.emitted('load')).toBeUndefined()
    expect((wrapper.find('[aria-label="已保存配置"]').element as HTMLSelectElement).value).toBe('')
    expect(wrapper.text()).not.toContain(profile.name)
  })

  it.each(['logout', 'unmount', 'session'])('%s 终止请求，晚到列表不能回填或载入', async action => {
    let finish!: (response: Response) => void
    vi.mocked(fetch).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const wrapper = mountPanel(); await flushPromises()
    const signal = vi.mocked(fetch).mock.calls[0]![1]!.signal!
    if (action === 'unmount') wrapper.unmount()
    else if (action === 'session') { useAuthStore().logout(); vi.mocked(fetch).mockResolvedValueOnce(response({ items: [] })); useAuthStore().authenticated = true }
    else useAuthStore().logout()
    await flushPromises()
    expect(signal.aborted).toBe(true)
    finish(response({ items: [profile] })); await flushPromises()
    expect(wrapper.emitted('load')).toBeUndefined()
    if (action !== 'unmount') expect(wrapper.text()).not.toContain(profile.name)
  })
})

function calculated() {
  const history = { symbol: 'US:AAPL', market: 'US', currency: 'USD', source: 'tencent_history_public', adjustment: 'raw', period: 'day', bars: [{ date: '2026-11-20', open: '100', high: '102', low: '99', close: '101', volume: '10' }], requested_limit: 120, actual_count: 1, latest_date: '2026-11-20', earliest_date: '2026-11-20', checked_at: '2026-11-22T08:00:00Z', data_as_of: '2026-11-20', observation_only: true, warnings: [], history_complete: true }
  return { history, parameters: { ...parameters }, algorithm_version: 'daily-v1', parameter_hash: 'short-hash', source_bars: 20, warmup_bars: 19, warmup_requested: 100, visible_bars: 1, points: [{ date: '2026-11-20', ma: null, dif: null, dea: null, macd: null, k: null, d: null, j: null, atr: null }], as_of: '2026-11-20', calculated_at: '2026-11-22T08:00:00Z', warnings: [], observation_only: true, formula_notes: [] }
}
describe('配置与公共历史隔离', () => {
  it('载入和覆盖不重新计算、不改变图表快照；查询才应用；401清私有参数但保留公开图表', async () => {
    useAuthStore().authenticated = true; setAccessToken('secret'); route.query = { symbol: 'US:AAPL' }
    vi.mocked(fetch).mockImplementation(async (url, init) => {
      if (url === '/api/v1/indicators/daily') return response({ ...calculated(), parameters: JSON.parse(init!.body as string).parameters })
      if (url === '/api/v1/indicators/profiles/profile-1') return response(profile)
      return response({ items: [profile] })
    })
    const wrapper = mount(HistoryPage); wrappers.push(wrapper); await flushPromises()
    await select(wrapper)
    const queries = () => vi.mocked(fetch).mock.calls.filter(([url]) => url === '/api/v1/indicators/daily')
    await click(wrapper, '载入配置')
    expect(queries()).toHaveLength(1)
    expect((wrapper.find('[aria-label="MA 周期"]').element as HTMLInputElement).value).toBe('20')
    expect(wrapper.find('.chart-snapshot').text()).toBe('10')
    expect(wrapper.text()).toContain('实际参数：MA 10')
    await click(wrapper, '覆盖更新')
    expect(queries()).toHaveLength(1)
    expect(wrapper.find('.chart-snapshot').text()).toBe('10')
    await wrapper.find('form').trigger('submit'); await flushPromises()
    expect(queries()).toHaveLength(2)
    expect(wrapper.find('.chart-snapshot').text()).toBe('20')
    vi.mocked(fetch).mockResolvedValueOnce(response({ code: 'UNAUTHORIZED', message: 'Token失效' }, 401))
    await click(wrapper, '刷新配置')
    expect(useAuthStore().authenticated).toBe(false)
    expect((wrapper.find('[aria-label="MA 周期"]').element as HTMLInputElement).value).toBe('10')
    expect(wrapper.find('.chart-snapshot').text()).toBe('20')
    expect(wrapper.text()).not.toContain(profile.name)
    await wrapper.find('form').trigger('submit'); await flushPromises()
    expect(queries()).toHaveLength(3)
    expect(queries().at(-1)![1]!.headers).not.toHaveProperty('Authorization')
  })

  it('未登录可直接查询历史，不读取私有配置', async () => {
    route.query = { symbol: 'US:AAPL' }
    vi.mocked(fetch).mockResolvedValue(response(calculated()))
    const wrapper = mount(HistoryPage); wrappers.push(wrapper); await flushPromises()
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(wrapper.find('.chart-snapshot').text()).toBe('10')
    expect(vi.mocked(fetch).mock.calls[0]![0]).toBe('/api/v1/indicators/daily')
  })
})
