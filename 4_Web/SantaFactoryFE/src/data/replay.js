export const GRID = { width: 24, length: 14 }

export const RUN_STATUS_LABEL = {
  QUEUED: '대기',
  RUNNING: '계산 중',
  DONE: '완료',
  FAILED: '실패',
  TIMEOUT: '시간 초과',
}

export const ESTIMATE_STATUS_LABEL = {
  RUNNING: '진행 중',
  DONE: '완료',
  PARTIAL: '일부 실패',
  CANCELLED: '취소됨',
}

const EMPTY = 0
export const RACK = 1
export const STATION = 2
export const DOCK = 3

export function buildLayout() {
  const { width: W, length: H } = GRID
  const cells = new Array(W * H).fill(EMPTY)
  for (let y = 2; y < H - 2; y++) {
    if (y % 3 === 1) continue
    for (let x = 4; x < W - 4; x++) {
      if ((x - 4) % 5 === 4) continue
      cells[y * W + x] = RACK
    }
  }
  ;[2, 5, 8, 11].forEach((y) => (cells[y * W + 0] = STATION))
  ;[3, 7, 11].forEach((y) => (cells[y * W + W - 1] = DOCK))
  return cells
}

export const BOTS = [
  { x: 2, y: 4, state: 'carry', path: 'a' },
  { x: 8, y: 1, state: 'move', path: 'b' },
  { x: 13, y: 7, state: 'work', path: 'c' },
  { x: 18, y: 10, state: 'carry', path: 'd' },
  { x: 21, y: 4, state: 'move', path: 'e' },
  { x: 5, y: 12, state: 'free', path: 'f' },
  { x: 11, y: 1, state: 'carry', path: 'g' },
  { x: 16, y: 12, state: 'move', path: 'h' },
  { x: 1, y: 8, state: 'work', path: 'i' },
]
