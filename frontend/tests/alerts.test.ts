import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { useAuthStore } from '../src/modules/auth'
import { useAlerts } from '../src/modules/alerts/composables/useAlerts'
import { fixed8, newRuleDraft, rulePayload } from '../src/modules/alerts/composables/ruleDraft'
import RuleEditor from '../src/modules/alerts/components/RuleEditor.vue'
import * as api from '../src/modules/alerts/api'
import { ApiError } from '../src/shared/api/client'
import type { AlertRule } from '../src/modules/alerts/types'
vi.mock('../src/modules/alerts/api', () => ({ listRules: vi.fn(), getRule: vi.fn(), createRule: vi.fn(), updateRule: vi.fn(), deleteRule: vi.fn(), resetRule: vi.fn(), previewRule: vi.fn(), getEvents: vi.fn() }))
const rule = { id: 'r1', name: '测试规则', security_id: 's1', symbol: 'sh600000', security_name: '测试证券', rule_type: 'PRICE_CROSS_UP', mode: 'OBSERVATION', threshold: '10', reset_threshold: '9', cooldown_seconds: 300, enabled: false, version: 2, created_at: '', updated_at: '', state: { phase: 'ARMED', last_value: null, last_sample_key: null, last_received_at: null, last_triggered_at: null, last_reset_at: null, evaluation_status: '', evaluation_reason: '', checked_at: null, trigger_count: 0 } } as AlertRule
beforeEach(() => { setActivePinia(createPinia()); vi.resetAllMocks(); useAuthStore().authenticated = true; vi.mocked(api.listRules).mockResolvedValue({ items: [rule] }) })
function setup() { let alerts!: ReturnType<typeof useAlerts>; const wrapper = mount(defineComponent({ setup() { alerts = useAlerts(); return () => null } })); return { alerts, wrapper } }
describe('预警规则', () => {
  it('请求适配器传版本、十进制字符串，preview 不附带写入字段', async () => {
    const adapter = await vi.importActual<typeof api>('../src/modules/alerts/api')
    const fetcher = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => new Response('{}', { status: 200 }))
    await adapter.updateRule('r1', { ...rulePayload({ ...newRuleDraft(), name: '规则', security_id: 's1', threshold: '10.12345678', reset_threshold: '9' }), version: 2 })
    expect(JSON.parse(fetcher.mock.calls[0]![1]!.body as string)).toMatchObject({ threshold: '10.12345678', version: 2 })
    await adapter.previewRule('r1'); expect(fetcher.mock.calls[1]![0]).toContain('/alerts/rules/r1/preview'); expect(fetcher.mock.calls[1]![1]!.body).toBeUndefined()
    await adapter.deleteRule('r1', 2); expect(fetcher.mock.calls[2]![0]).toContain('/alerts/rules/r1?version=2'); expect(fetcher.mock.calls[2]![1]!.method).toBe('DELETE')
    fetcher.mockRestore()
  })
  it('十进制严格校验并保持超过浮点精度的阈值字符串', () => {
    expect(fixed8('9007199254740993.12345678')).toBe(900719925474099312345678n)
    const body = rulePayload({ ...newRuleDraft(), name: ' 合成规则 ', security_id: 's1', threshold: '9007199254740993.12345678', reset_threshold: '9007199254740993.12345677' })
    expect(body.threshold).toBe('9007199254740993.12345678'); expect(body.name).toBe('合成规则'); expect(body.enabled).toBe(false)
    for (const value of ['', '1e2', 'NaN', '1.123456789', '0x10']) expect(() => fixed8(value)).toThrow()
    expect(() => rulePayload({ ...body, threshold: '0' })).toThrow('大于 0')
    expect(() => rulePayload({ ...body, reset_threshold: body.threshold })).toThrow('小于')
    expect(rulePayload({ ...body, rule_type: 'DAY_CHANGE_BELOW', threshold: '-3', reset_threshold: '-2' }).threshold).toBe('-3')
    expect(() => rulePayload({ ...body, cooldown_seconds: 0.5 })).toThrow('整数')
    expect(() => rulePayload({ ...body, mode: 'REALTIME', enabled: true })).toThrow('尚未验收')
  })
  it('实时模式强制停用，证券搜索与编辑表单不嵌套', async () => {
    const wrapper = mount(RuleEditor, { props: { rule: null, busy: false, submit: vi.fn() }, global: { stubs: { SecuritySearch: { template: '<form data-testid="search-form" />' } } } })
    expect(wrapper.findAll('form')).toHaveLength(2); expect(wrapper.find('form form').exists()).toBe(false)
    await wrapper.get('[aria-label="预警模式"]').setValue('REALTIME')
    expect((wrapper.get('[aria-label="启用规则"]').element as HTMLInputElement).disabled).toBe(true)
    expect(wrapper.text()).toContain('源延迟未知，实时风控尚未验收'); wrapper.unmount()
  })
  it('版本冲突保留草稿，不自动读取覆盖', async () => {
    const { alerts, wrapper } = setup(); alerts.select(rule)
    vi.mocked(api.updateRule).mockRejectedValue(new ApiError('冲突', 409, 'VERSION_CONFLICT', 'req'))
    const editor = mount(RuleEditor, { props: { rule, busy: false, submit: alerts.save }, global: { stubs: { SecuritySearch: true } } })
    await editor.get('[aria-label="规则名称"]').setValue('保留的草稿'); await editor.get('form').trigger('submit'); await flushPromises()
    expect(api.updateRule).toHaveBeenCalledWith('r1', expect.objectContaining({ version: 2, name: '保留的草稿' }), expect.anything())
    expect((editor.get('[aria-label="规则名称"]').element as HTMLInputElement).value).toBe('保留的草稿')
    expect(alerts.error.value).toContain('草稿已保留'); expect(api.listRules).not.toHaveBeenCalled(); editor.unmount(); wrapper.unmount()
  })
  it('试算仅调用 preview，不写规则；切换和退出阻止迟到响应', async () => {
    const { alerts, wrapper } = setup(); alerts.select(rule)
    let resolve!: (value: never) => void
    vi.mocked(api.previewRule).mockImplementationOnce(() => new Promise(done => { resolve = done }))
    const pending = alerts.simulate(); alerts.select({ ...rule, id: 'r2' }); resolve({ rule_id: 'r1' } as never); await pending
    expect(alerts.preview.value).toBeNull(); expect(api.updateRule).not.toHaveBeenCalled(); expect(api.createRule).not.toHaveBeenCalled()
    let finish!: (value: { items: AlertRule[] }) => void
    vi.mocked(api.listRules).mockImplementationOnce(() => new Promise(done => { finish = done }))
    const load = alerts.load(); useAuthStore().logout(); finish({ items: [rule] }); await load
    expect(alerts.rules.value).toEqual([]); expect(alerts.selected.value).toBeNull(); wrapper.unmount()
  })
})
