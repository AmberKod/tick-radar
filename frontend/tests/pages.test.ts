import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'
import { markRaw } from 'vue'
import SystemOverview from '../src/modules/system/views/SystemOverview.vue'
import ModulePlaceholderPage from '../src/shared/components/ModulePlaceholderPage.vue'
import { workspaceModules } from '../src/app/router/modules'
import { useSystemStore } from '../src/modules/system/stores/system'
import { statusFixture, modulesFixture } from './fixtures'
import { ApiError } from '../src/shared/api/client'
beforeEach(() => { setActivePinia(createPinia()) })
describe('工作台页面', () => {
  it('空状态不展示虚构报价，行情与预警入口不可操作', () => {
    const wrapper = mount(SystemOverview)
    expect(wrapper.text()).toContain('尚未接入行情数据')
    expect(wrapper.text()).toContain('等待模块目录')
    expect(wrapper.findAll('button').every(button => button.attributes('disabled') !== undefined)).toBe(true)
    expect(wrapper.text()).not.toMatch(/\d+\.\d+%/)
    wrapper.unmount()
  })
  it('显示后端真实降级信息与模块状态', () => {
    const store = useSystemStore()
    store.status = statusFixture
    store.modules = modulesFixture.modules
    const wrapper = mount(SystemOverview)
    expect(wrapper.text()).toContain('依赖服务降级')
    expect(wrapper.text()).toContain('数据库连接失败')
    expect(wrapper.text()).toContain('基础已接入')
    expect(wrapper.text()).toContain('阶段0禁用采集')
    wrapper.unmount()
  })
  it('显示503错误与可追踪请求标识', () => {
    useSystemStore().error = new ApiError('依赖不可用', 503, 'UNAVAILABLE', 'test-request')
    const wrapper = mount(SystemOverview)
    expect(wrapper.text()).toContain('无法获取系统状态')
    expect(wrapper.text()).toContain('test-request')
    expect(wrapper.find('button').attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })
  it('占位页面使用统一目录显示模块范围', () => {
    const module = workspaceModules.find(item => item.key === 'watchlist')!
    const wrapper = mount(ModulePlaceholderPage, { props: { module: { ...module, icon: markRaw(module.icon) } }, global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } } })
    expect(wrapper.text()).toContain('自选股正在规划中')
    expect(wrapper.text()).toContain('自选分组')
    expect(wrapper.text()).toContain('尚未启用')
    wrapper.unmount()
  })
})
