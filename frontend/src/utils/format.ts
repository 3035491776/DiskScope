const UNITS = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']

export function formatBytes(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value) || value < 0) return '—'
  if (value < 1024) return `${Math.round(value)} B`
  let amount = value
  let unit = 0
  while (amount >= 1024 && unit < UNITS.length - 1) {
    amount /= 1024
    unit += 1
  }
  return `${amount.toFixed(1)} ${UNITS[unit]}`
}

export function formatNumber(value: number | null | undefined): string {
  return value == null || !Number.isFinite(value) ? '—' : value.toLocaleString()
}

export function formatSeconds(milliseconds: number | null | undefined): string {
  return milliseconds == null || !Number.isFinite(milliseconds)
    ? '—'
    : `${(milliseconds / 1000).toFixed(1)} s`
}

export function formatLocalTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.valueOf()) ? '—' : date.toLocaleString()
}
