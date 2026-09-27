export function formatDateTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function formatWon(won) {
  if (won == null || Number.isNaN(won)) return '—'
  const man = Math.round(won / 10000)
  const eok = Math.floor(man / 10000)
  const rest = man % 10000
  if (eok === 0) return `${rest.toLocaleString()}만 원`
  if (rest === 0) return `${eok}억 원`
  return `${eok}억 ${rest.toLocaleString()}만 원`
}

export function formatPercent(value) {
  if (value == null || Number.isNaN(value)) return '—'
  return Number.isInteger(value) ? `${value}` : value.toFixed(1)
}

export function formatEok(won) {
  if (won == null) return ''
  const eok = won / 100000000
  return `${Number.isInteger(eok) ? eok : eok.toFixed(1)}억`
}
