// 只格式化十进制字符串，不经Number转换，保留原始精度。
export function decimalLabel(value: string | null | undefined): string {
  if (value == null) return '未覆盖'
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(value)
  if (!match) return '—'
  const whole = match[2]!.replace(/^0+(?=\d)/, '')
  const fraction = (match[3] || '').replace(/0+$/, '')
  const sign = whole === '0' && !fraction ? '' : match[1]!
  return `${sign}${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}${fraction ? `.${fraction}` : ''}`
}

export function beijingTime(value: string | null | undefined): string {
  if (!value) return '未知'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '未知' : `${date.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })} GMT+8`
}
