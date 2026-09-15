/**
 * 리플레이 내보내기(scene.json + trajectories.json) → 그리기용 모델.
 *
 * 3_FMS/sim_engine/results/fleet_replay.html 의 buildModel 을 그대로 옮겼다. 좌표 규약과 헤딩 해석이
 * 시뮬 쪽 export_isaac 과 한 글자라도 어긋나면 로봇이 벽을 통과해 보이므로, 새로 쓰지 않고 옮겼다.
 *
 * 좌표 규약(export_isaac): x = (c+0.5)·1 m − 0.4, y = (r+0.5)·1 m → c = round(x − 0.1), r = round(y − 0.5).
 * 행이 증가하는 쪽이 북쪽이다.
 */

/** 0=N 1=E 2=S 3=W (행 증가 = 북) */
export const DIRS = [[1, 0], [0, 1], [-1, 0], [0, -1]]

const toRC = (x, y) => [Math.round(y - 0.5), Math.round(x - 0.1)]

/** atan2(dr,dc) 규약: E=0 → 1, N=π/2 → 0, W=π → 3, S=−π/2 → 2 */
function yawToH(yaw) {
  const k = [1, 0, 3, 2]
  const q = Math.round(yaw / (Math.PI / 2))
  return k[((q % 4) + 4) % 4]
}

/** scene.grid 가 없는 옛 내보내기를 nodes(통행 가능 칸) + zones 로 복원한다. */
function gridFromNodes(scene) {
  const cells = scene.nodes.map(([x, y]) => toRC(x, y))
  const H = Math.max(...cells.map((p) => p[0])) + 2
  const W = Math.max(...cells.map((p) => p[1])) + 2
  const g = Array.from({ length: H }, () => Array(W).fill('#'))
  for (const [r, c] of cells) g[r][c] = '.'
  for (const z of scene.zones || []) {
    const [x0, y0, w, h] = z.rect
    for (let r = Math.floor(y0); r < Math.floor(y0 + h); r += 1) {
      for (let c = Math.floor(x0 + 0.4); c < Math.floor(x0 + w + 0.4); c += 1) {
        if (g[r] && g[r][c] === '.') g[r][c] = 'z'
      }
    }
  }
  return { grid: g.map((row) => row.join('')), H, W }
}

/**
 * 스테이션 종류 → 화면에서의 역할. 맵에는 12종이 있는데 전부 한 색으로 칠하면 AMR 이 어디로
 * 가는 중인지 안 보인다. 주행 흐름(3_FMS/ai_theta/data/README.md)이 기준이다:
 *   입고  inbound_buf → aisle_buf
 *   출고  aisle_buf   → packing
 * 즉 packing 이 출고 목적지이고 aisle_buf 가 중간 집하다. 나머지는 배경으로 둔다.
 */
const STATION_ROLE = {
  packing: 'pack',        // AMR 이 토트를 내려놓는 출고 지점
  aisle_buf: 'pick',      // 통로 집하 — AMR 이 토트를 집는 곳
  inbound_buf: 'in',      // 입고 버퍼
  charger: 'charge',
  charge_q: 'charge',
}

/** 스테이션 종류를 키에서 뽑는다 — `packing[2]` → `packing`. */
export function stationRole(key) {
  const kind = String(key).replace(/\[\d+\]$/, '')
  return STATION_ROLE[kind] ?? 'etc'
}

/** 스테이션 좌표를 통행 가능한 이웃 칸으로 스냅한다 (시뮬 load_map 과 같은 규칙). */
function snapStations(scene, free) {
  if (scene.station_cells) return scene.station_cells
  const stations = {}
  for (const [kind, pts] of Object.entries(scene.stations || {})) {
    if (kind === 'charge_zone') continue
    pts.forEach(([x, y], i) => {
      const r = Math.floor(y)
      const c = Math.floor(x + 0.4)
      for (const [rr, cc] of [[r, c], [r - 1, c], [r + 1, c], [r, c - 1], [r, c + 1]]) {
        if (free(rr, cc)) {
          stations[`${kind}[${i}]`] = [rr, cc]
          break
        }
      }
    })
  }
  return stations
}

/**
 * 바깥 벽 두께를 네 면 같게 잘라낸다. 시뮬 지도는 1 m 격자로 줄일 때 세 면에만 채움 칸이 붙어 와서
 * 그대로 그리면 한 면만 테두리가 얇다. 벽이 없는 면이 있으면 자르지 않는다.
 */
function trimBorder(grid, H, W) {
  const wallRow = (r) => {
    for (let c = 0; c < W; c += 1) if (grid[r][c] !== '#') return false
    return true
  }
  const wallCol = (c) => {
    for (let r = 0; r < H; r += 1) if (grid[r][c] !== '#') return false
    return true
  }
  let low = 0
  while (low < H && wallRow(low)) low += 1
  let high = 0
  while (high < H - low && wallRow(H - 1 - high)) high += 1
  let left = 0
  while (left < W && wallCol(left)) left += 1
  let right = 0
  while (right < W - left && wallCol(W - 1 - right)) right += 1
  const keep = Math.min(low, high, left, right)
  if (keep === 0) return { grid, H, W, r0: 0, c0: 0 }
  const r0 = low - keep
  const r1 = H - (high - keep)
  const c0 = left - keep
  const c1 = W - (right - keep)
  return { grid: grid.slice(r0, r1).map((row) => row.slice(c0, c1)), H: r1 - r0, W: c1 - c0, r0, c0 }
}

/**
 * @returns {{H, W, grid, T, stations, robots, meta, twoCell}} robots 는 rid → [[r, c, heading, action], …]
 */
export function buildModel(replay) {
  const { scene } = replay
  let grid
  let H
  let W
  if (scene.grid) {
    grid = scene.grid
    H = grid.length
    W = grid[0].length
  } else {
    ({ grid, H, W } = gridFromNodes(scene))
  }
  const free = (r, c) => r >= 0 && r < H && c >= 0 && c < W && (grid[r][c] === '.' || grid[r][c] === 'z')
  const stations = snapStations(scene, free)
  const trimmed = trimBorder(grid, H, W)
  const shift = ([r, c]) => [r - trimmed.r0, c - trimmed.c0]
  for (const key of Object.keys(stations)) stations[key] = shift(stations[key])

  const robots = {}
  let T = 0
  for (const [rid, pts] of Object.entries(replay.robots || {})) {
    // 헤딩은 변할 때만 기록돼 온다. 기록이 없는 시점은 마지막 기록을 유지한다 — 시점마다 동쪽으로
    // 되돌리면 서 있는 로봇이 빙글빙글 돈다. 첫 기록 전에는 동쪽
    const events = [...(replay.headings?.[rid] || [])].sort((a, b) => a[0] - b[0])
    let k = 0
    let h = 1
    const arr = pts.map(([t, x, y]) => {
      const [r, c] = shift(toRC(x, y))
      while (k < events.length && events[k][0] <= t + 1e-6) {
        h = yawToH(events[k][1])
        k += 1
      }
      return [r, c, h]
    })
    robots[rid] = arr
    T = Math.max(T, arr.length)
  }

  const model = replay.model || scene.meta?.model || 'heading'
  return {
    H: trimmed.H,
    W: trimmed.W,
    grid: trimmed.grid,
    T,
    stations,
    robots,
    // heading 모델은 로봇이 두 칸을 차지한다 — 위치가 앞축 기준이라 그리는 위치를 뒤로 민다
    twoCell: model === 'heading',
    meta: { ...(scene.meta || {}), model, dt: replay.dt_s || scene.meta?.dt_s || 1 },
  }
}

/** 틱 사이를 선형 보간한 자세. 정수 틱만 쓰면 로봇이 칸 단위로 튄다. */
export function poseAt(model, rid, tt) {
  const series = model.robots[rid]
  const at = (i) => series[Math.max(0, Math.min(i, series.length - 1))]
  const i = Math.floor(tt)
  const f = tt - i
  const [r0, c0, h0] = at(i)
  const [r1, c1] = at(i + 1)
  return { r: r0 + (r1 - r0) * f, c: c0 + (c1 - c0) * f, h: h0 }
}
