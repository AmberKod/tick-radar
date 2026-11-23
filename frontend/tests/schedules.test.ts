import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { useAuthStore } from '../src/modules/auth'
import { useSchedules } from '../src/modules/alerts/composables/useSchedules'
import { newScheduleDraft, schedulePayload, scheduleTimes } from '../src/modules/alerts/composables/scheduleDraft'
import ScheduleEditor from '../src/modules/alerts/components/ScheduleEditor.vue'
import ScheduleRuns from '../src/modules/alerts/components/ScheduleRuns.vue'
import * as api from '../src/modules/alerts/api/schedules'
import { ApiError } from '../src/shared/api/client'
import type { Schedule, SchedulePreview, ScheduleRunPage } from '../src/modules/alerts/types/schedules'
vi.mock('../src/modules/alerts/api/schedules', () => ({ listSchedules: vi.fn(), getSchedule: vi.fn(), createSchedule: vi.fn(), updateSchedule: vi.fn(), deleteSchedule: vi.fn(), previewSchedule: vi.fn(), getScheduleRuns: vi.fn() }))
const schedule = { id: 's1', version: 3, ...schedulePayload({ ...newScheduleDraft(), name: '收盘检查' }), timezone: 'Asia/Shanghai', created_at: '', updated_at: '' } as Schedule
function setup() { let state!: ReturnType<typeof useSchedules>; const wrapper = mount(defineComponent({ setup() { state = useSchedules(); return () => null } })); return { state, wrapper } }
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done }); return { promise, resolve } }
beforeEach(() => { setActivePinia(createPinia()); vi.resetAllMocks(); useAuthStore().authenticated = true; vi.mocked(api.listSchedules).mockResolvedValue({ items: [schedule] }) })
describe('交易日尾盘提醒', () => {
  it('分钟精度、14 点边界、重复和数量均严格校验，升序规范化', () => {
    expect(scheduleTimes('14:59，14:00 14:30')).toEqual(['14:00', '14:30', '14:59'])
    expect(scheduleTimes('14:00,14:01,14:02,14:03,14:04,14:05,14:06,14:07')).toHaveLength(8)
    for (const value of ['', '13:59', '15:00', '14:60', '14:1', '14:30:00', '14：30', '14:00,bad']) expect(() => scheduleTimes(value)).toThrow()
    expect(() => scheduleTimes('14:30, 14:30')).toThrow('重复')
    expect(() => scheduleTimes('14:00,14:01,14:02,14:03,14:04,14:05,14:06,14:07,14:08')).toThrow('8')
  })
  it('默认停用且只构造白名单创建字段，校验控制字符和宽限整数', () => {
    const draft = { ...newScheduleDraft(), name: '提醒', timezone: 'UTC', version: 12 }
    expect(schedulePayload(draft)).toEqual({ name: '提醒', exchange: 'SSE', times: ['14:30', '14:40', '14:50'], message: draft.message, grace_seconds: 120, enabled: false })
    expect(schedulePayload({ ...draft, message: '第一行\n第二行', enabled: true }).enabled).toBe(true)
    for (const grace_seconds of [29, 601, 30.5, NaN]) expect(() => schedulePayload({ ...draft, grace_seconds })).toThrow('整数')
    for (const name of ['', 'a\nb', 'a\tb', 'a'.repeat(81)]) expect(() => schedulePayload({ ...draft, name })).toThrow('名称')
    for (const message of ['', 'a\tb', 'a\rb', 'a'.repeat(1001)]) expect(() => schedulePayload({ ...draft, message })).toThrow('内容')
  })
  it('适配器发送 CAS 版本、DELETE 查询版本和无 body 的今日预览', async () => {
    const adapter = await vi.importActual<typeof api>('../src/modules/alerts/api/schedules')
    const fetcher = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => new Response('{}', { status: 200 }))
    try {
      await adapter.createSchedule(schedulePayload({ ...newScheduleDraft(), name: '新提醒' }))
      expect(fetcher.mock.calls[0]![1]!.method).toBe('POST'); expect(JSON.parse(fetcher.mock.calls[0]![1]!.body as string)).toMatchObject({ enabled: false }); expect(fetcher.mock.calls[0]![1]!.body).not.toContain('timezone')
      await adapter.updateSchedule('s/1', { ...schedulePayload({ ...newScheduleDraft(), name: '更新' }), version: 3 })
      expect(fetcher.mock.calls[1]![0]).toContain('/alerts/schedules/s%2F1'); expect(JSON.parse(fetcher.mock.calls[1]![1]!.body as string).version).toBe(3)
      await adapter.previewSchedule('s1'); expect(fetcher.mock.calls[2]![0]).toContain('/s1/preview'); expect(fetcher.mock.calls[2]![1]!.body).toBeUndefined(); expect(fetcher.mock.calls[2]![0]).not.toContain('?')
      await adapter.deleteSchedule('s1', 3); expect(fetcher.mock.calls[3]![0]).toContain('/s1?version=3'); expect(fetcher.mock.calls[3]![1]!.method).toBe('DELETE')
      await adapter.getScheduleRuns(2, 's/1'); expect(fetcher.mock.calls[4]![0]).toContain('/schedule-runs?page=2&page_size=20&schedule_id=s%2F1')
    } finally { fetcher.mockRestore() }
  })
  it('只有显式勾选并提交才启用，表单展示规范时间', async () => {
    const submit = vi.fn().mockResolvedValue(false)
    const wrapper = mount(ScheduleEditor, { props: { schedule: null, busy: false, submit } })
    expect(submit).not.toHaveBeenCalled(); expect((wrapper.get('[aria-label="启用尾盘提醒"]').element as HTMLInputElement).checked).toBe(false)
    await wrapper.get('[aria-label="尾盘提醒名称"]').setValue('检查')
    await wrapper.get('[aria-label="尾盘提醒时间"]').setValue('14:50，14:30')
    expect(wrapper.get('[data-testid="schedule-canonical-times"]').text()).toContain('14:30、14:50')
    await wrapper.get('[aria-label="启用尾盘提醒"]').setValue(true); expect(submit).not.toHaveBeenCalled()
    await wrapper.get('form').trigger('submit'); expect(submit).toHaveBeenCalledWith(expect.objectContaining({ enabled: true, times: ['14:30', '14:50'] })); wrapper.unmount()
  })
  it('409 和网络失败保留草稿且不自动重发，成功后保留服务端版本', async () => {
    const { state, wrapper } = setup(); state.select(schedule)
    vi.mocked(api.updateSchedule).mockRejectedValueOnce(new ApiError('冲突', 409, 'VERSION_CONFLICT', 'req')).mockRejectedValueOnce(new Error('网络中断'))
    const editor = mount(ScheduleEditor, { props: { schedule, busy: false, submit: state.save } })
    await editor.get('[aria-label="尾盘提醒名称"]').setValue('保留草稿')
    await editor.get('form').trigger('submit'); await flushPromises()
    expect(state.error.value).toContain('草稿已保留'); expect((editor.get('[aria-label="尾盘提醒名称"]').element as HTMLInputElement).value).toBe('保留草稿'); expect(api.updateSchedule).toHaveBeenCalledTimes(1)
    await editor.get('form').trigger('submit'); await flushPromises(); expect((editor.get('[aria-label="尾盘提醒名称"]').element as HTMLInputElement).value).toBe('保留草稿'); expect(api.listSchedules).not.toHaveBeenCalled()
    vi.mocked(api.updateSchedule).mockResolvedValueOnce({ ...schedule, version: 4, name: '保留草稿' })
    await editor.get('form').trigger('submit'); await flushPromises(); expect(state.selected.value?.version).toBe(4)
    expect(api.updateSchedule).toHaveBeenLastCalledWith('s1', expect.objectContaining({ version: 3 }), expect.anything()); expect(state.busy.value).toBe(false)
    editor.unmount(); wrapper.unmount()
  })
  it('预览只读，选择切换使迟到响应无效且释放 busy', async () => {
    const { state, wrapper } = setup(); state.select(schedule)
    const pending = deferred<SchedulePreview>(); vi.mocked(api.previewSchedule).mockReturnValueOnce(pending.promise)
    const request = state.simulate(); expect(state.busy.value).toBe(true)
    state.select({ ...schedule, id: 's2' }); expect(state.busy.value).toBe(false)
    pending.resolve({ schedule_id: 's1' } as SchedulePreview); await request
    expect(state.preview.value).toBeNull(); expect(state.selected.value?.id).toBe('s2'); expect(api.createSchedule).not.toHaveBeenCalled(); expect(api.updateSchedule).not.toHaveBeenCalled(); wrapper.unmount()
  })
  it('退出和 epoch 变更丢弃旧列表及写入响应，不锁住新会话', async () => {
    const { state, wrapper } = setup(); const oldList = deferred<{ items: Schedule[] }>(); vi.mocked(api.listSchedules).mockReturnValueOnce(oldList.promise)
    const list = state.load(); state.select(schedule)
    const oldWrite = deferred<Schedule>(); vi.mocked(api.updateSchedule).mockReturnValueOnce(oldWrite.promise)
    const save = state.save(schedulePayload({ ...newScheduleDraft(), name: '旧写入' })); useAuthStore().logout()
    useAuthStore().authenticated = true; oldList.resolve({ items: [schedule] }); oldWrite.resolve(schedule); await Promise.all([list, save])
    expect(state.schedules.value).toEqual([]); expect(state.selected.value).toBeNull(); expect(state.busy.value).toBe(false)
    const next = deferred<{ items: Schedule[] }>(); vi.mocked(api.listSchedules).mockReturnValueOnce(next.promise)
    const changed = state.load(); useAuthStore().epoch++; next.resolve({ items: [schedule] }); await changed; expect(state.schedules.value).toEqual([]); wrapper.unmount()
  })
  it('记录分页和选中筛选隔离迟到响应，删除不改历史接口', async () => {
    const { state, wrapper } = setup(); state.select(schedule); state.runFilter.value = 'selected'
    const first = deferred<ScheduleRunPage>(), second = deferred<ScheduleRunPage>()
    vi.mocked(api.getScheduleRuns).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
    const a = state.loadRuns(1); state.select({ ...schedule, id: 's2' }); const b = state.loadRuns(2)
    second.resolve({ items: [], page: 2, page_size: 20, total: 21 }); await b; first.resolve({ items: [], page: 1, page_size: 20, total: 1 }); await a
    expect(state.runs.value?.page).toBe(2); expect(api.getScheduleRuns).toHaveBeenLastCalledWith(2, 's2', expect.anything())
    vi.mocked(api.deleteSchedule).mockResolvedValueOnce(); await state.remove(); expect(api.deleteSchedule).toHaveBeenCalledWith('s2', 3, expect.anything()); expect(state.selected.value).toBeNull(); wrapper.unmount()
  })
  it('卸载后不接纳响应，执行状态不误称已投递', async () => {
    const { state, wrapper } = setup(); const pending = deferred<{ items: Schedule[] }>(); vi.mocked(api.listSchedules).mockReturnValueOnce(pending.promise)
    const load = state.load(); wrapper.unmount(); pending.resolve({ items: [schedule] }); await load; expect(state.schedules.value).toEqual([])
    const history = mount(ScheduleRuns, { props: { busy: false, runs: { items: [], total: 0, page: 1, page_size: 20 } } })
    expect(history.text()).toContain('已入投递队列不代表已投递'); expect(history.text()).toContain('已删除提醒'); history.unmount()
  })
})
