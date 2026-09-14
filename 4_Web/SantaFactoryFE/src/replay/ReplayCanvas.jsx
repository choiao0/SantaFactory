import { useEffect, useMemo, useRef } from 'react'
import { DIRS, buildModel, poseAt, stationRole } from './model.js'

/**
 * 리플레이 캔버스 (S15P21A106-205).
 *
 * 그리는 방식은 3_FMS 의 fleet_replay.html 을 옮겼다 — 배경(격자·랙·존·스테이션)은 안 변하므로
 * 오프스크린 캔버스에 한 번만 그려두고, 매 프레임에는 그걸 통째로 복사한 뒤 로봇만 올린다.
 * 배경이 수천 칸이라 매 프레임 다시 그리면 대수가 늘수록 눈에 띄게 버벅인다.
 *
 * 색은 CSS 변수에서 읽는다. 사이트 테마를 바꾸면 캔버스도 같이 따라오게 하려는 것이고,
 * 원본도 같은 방식이라 옮기면서 달라진 것이 없다.
 */

const TRAIL_TICKS = 30

/**
 * 색은 캔버스 자신의 계산된 스타일에서 읽는다 — :root 가 아니라.
 * 변수를 보드(.sim-board)에 두면 리플레이 색이 사이트 전역 팔레트를 오염시키지 않는데,
 * :root 에서 읽으면 그 변수들이 안 보여서 빈 문자열이 오고 캔버스가 통째로 비어 버린다.
 */
const cssVar = (el, name) => getComputedStyle(el).getPropertyValue(name).trim()

/** 배경 레이어를 통째로 복사한다. 매 프레임 격자 수천 칸을 다시 그리면 대수가 늘수록 버벅인다. */
function restoreBackground(ctx, { layer, dpr }) {
  ctx.setTransform(1, 0, 0, 1, 0, 0)
  ctx.drawImage(layer, 0, 0)
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
}

/** 최근 지나온 자리. 정지 화면에서도 어디서 왔는지 읽히게 한다. */
function drawTrails(ctx, canvas, { cell, px, py }, model, ti) {
  ctx.lineWidth = 2
  ctx.lineCap = 'round'
  ctx.strokeStyle = cssVar(canvas, '--rp-amr')
  ctx.globalAlpha = 0.28
  for (const rid of Object.keys(model.robots)) {
    const back = Math.max(0, ti - TRAIL_TICKS)
    ctx.beginPath()
    for (let k = back; k <= ti; k += 1) {
      const p = poseAt(model, rid, k)
      const x = px(p.c) + cell / 2
      const y = py(p.r) + cell / 2
      if (k === back) ctx.moveTo(x, y); else ctx.lineTo(x, y)
    }
    ctx.stroke()
  }
  ctx.globalAlpha = 1
}

/** 로봇 한 대. heading 모델이면 두 칸을 차지하는 차체를 방향대로 돌려 그린다. */
function drawRobot(ctx, canvas, { cell, px, py }, model, rid, tick) {
  const p = poseAt(model, rid, tick)
  const [dr, dc] = DIRS[p.h]
  ctx.fillStyle = cssVar(canvas, '--rp-amr')
  if (model.twoCell) {
    // 위치가 앞축 기준이라 차체 중심은 뒤로 0.39 m 물러나 있다 (export_isaac 규약)
    const [len, wid] = model.meta.robot_dim_m || [1.5, 0.92]
    const axleToCenter = len / 2 - 0.39
    ctx.save()
    ctx.translate(px(p.c) + cell / 2 - dc * axleToCenter * cell,
                  py(p.r) + cell / 2 + dr * axleToCenter * cell)
    ctx.rotate(Math.atan2(-dr, dc))
    ctx.fillRect((-len * cell) / 2, (-wid * cell) / 2, len * cell, wid * cell)
    ctx.restore()
  } else {
    ctx.fillRect(px(p.c) + 0.5, py(p.r) + 0.5, cell - 1, cell - 1)
  }
  // 진행 방향 표식 — 회전만으로는 앞뒤가 구분되지 않는다
  ctx.fillStyle = 'rgba(255,255,255,0.92)'
  ctx.beginPath()
  ctx.arc(px(p.c) + cell / 2 + dc * cell * 0.28, py(p.r) + cell / 2 - dr * cell * 0.28, 1.3, 0, Math.PI * 2)
  ctx.fill()
}

export default function ReplayCanvas({ replay, tick, showTrails = true }) {
  const canvasRef = useRef(null)
  const staticRef = useRef(null)
  const model = useMemo(() => buildModel(replay), [replay])

  // 배경. 모델이 바뀔 때만 다시 그린다
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    const cell = Math.max(3, Math.floor((canvas.clientWidth || 900) / model.W))
    const width = model.W * cell
    const height = model.H * cell

    canvas.width = width * dpr
    canvas.height = height * dpr
    canvas.style.height = 'auto'

    const px = (c) => c * cell
    const py = (r) => (model.H - 1 - r) * cell

    const layer = document.createElement('canvas')
    layer.width = canvas.width
    layer.height = canvas.height
    const s = layer.getContext('2d')
    s.setTransform(dpr, 0, 0, dpr, 0, 0)

    const colors = {
      '#': cssVar(canvas, '--rp-wall'),
      '.': cssVar(canvas, '--rp-floor'),
      a: cssVar(canvas, '--rp-picker'),
      z: cssVar(canvas, '--rp-zone'),
    }
    for (let r = 0; r < model.H; r += 1) {
      for (let c = 0; c < model.W; c += 1) {
        s.fillStyle = colors[model.grid[r][c]] || colors['#']
        s.fillRect(px(c), py(r), cell, cell)
      }
    }
    // 5칸마다 눈금 — 거리를 가늠할 기준이 없으면 넓은 창고가 그냥 얼룩으로 보인다
    s.strokeStyle = cssVar(canvas, '--rp-gridline')
    s.lineWidth = 1
    for (let c = 0; c <= model.W; c += 5) {
      s.beginPath(); s.moveTo(px(c) + 0.5, 0); s.lineTo(px(c) + 0.5, height); s.stroke()
    }
    for (let r = 0; r <= model.H; r += 5) {
      s.beginPath(); s.moveTo(0, py(r) + cell + 0.5); s.lineTo(width, py(r) + cell + 0.5); s.stroke()
    }
    // 역할별로 색을 나눈다. 출고 지점(packing)은 크게 칠해 한눈에 찾게 한다 —
    // 5칸뿐인데 57칸짜리 스테이션 무리에 묻히면 AMR 이 어디로 가는지 읽히지 않는다
    const roleVar = { pack: '--rp-pack', pick: '--rp-pick', in: '--rp-in', charge: '--rp-charge', etc: '--rp-etc' }
    for (const [key, [r, c]] of Object.entries(model.stations)) {
      const role = stationRole(key)
      s.fillStyle = cssVar(canvas, roleVar[role])
      const pad = role === 'pack' ? 0 : 1.5
      s.fillRect(px(c) + pad, py(r) + pad, cell - pad * 2, cell - pad * 2)
    }
    staticRef.current = { layer, cell, dpr, px, py }
  }, [model])

  // 로봇. tick 이 바뀔 때마다
  useEffect(() => {
    const canvas = canvasRef.current
    const base = staticRef.current
    if (!canvas || !base) return
    const ctx = canvas.getContext('2d')

    restoreBackground(ctx, base)
    if (showTrails) drawTrails(ctx, canvas, base, model, Math.floor(tick))
    for (const rid of Object.keys(model.robots)) {
      drawRobot(ctx, canvas, base, model, rid, tick)
    }
  }, [model, tick, showTrails])

  return <canvas ref={canvasRef} className="rp-canvas" aria-label="창고 격자 위 AMR 주행 리플레이" />
}
