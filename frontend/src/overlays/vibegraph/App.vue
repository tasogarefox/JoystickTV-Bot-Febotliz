<template>
  <div>
    <h2 v-if="!connected">Connecting...</h2>
  </div>
  <div v-show="connected && !config.hidden">
    <div v-if="tTotal && username" class="title">
        <p class="title-prefix">Responding to</p>
        <p class="title-username">{{ username }}</p>
    </div>
    <canvas ref="canvas" v-show="tTotal" height="80" class="graph"></canvas>
    <div class="controls row">
      <div class="devices row">
        <div
          v-for="(device, i) in devices"
          :key="device.name"
          :class="{ 'device': true, 'column': devices.length > 1, 'row': devices.length <= 1 }"
          :style="{ '--icon-color': toCssRgba(getLineColor(i)) }"
        >
          <div class="device-icon">
            <div
              class="device-icon-mask"
              role="img"
              :aria-label="device.name"
              :style="{
                maskImage: `url('/icon/toy/${device.name}')`,
                WebkitMaskImage: `url('/icon/toy/${device.name}')`,
              }"
            ></div>
          </div>
          <p class="device-name">{{ device.name }}</p>
        </div>
      </div>
      <div v-if="tTotal" class="spacer"></div>
      <p v-if="tTotal" class="time">
        <span class="time-remaining">{{ formatTime(tTotal-tNow) }}</span>
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from "vue"

import { Chart } from "chart.js/auto"
import type { Point } from "chart.js"
// import type { ScriptableLineSegmentContext } from "chart.js"

import { ws_url } from "@/settings"


// ==========================================================================
// CONFIG

const VISIBLE_PAST = 5_000  // ms
const VISIBLE_FUTURE = 5_000  // ms

const STEP_SMOOTHING = 100  // ms
const STEP_TENSION = 0.1

const LINE_COLORS: RGB[] = [
  {r: 242, g: 12, b: 127},  // red
  {r: 12, g: 242, b: 242},  // blue
  {r: 242, g: 242, b: 242},  // white
  {r: 242, g: 242, b: 127},  // yellow
  {r: 12, g: 242, b: 12},  // green
  // {r: 242, g: 127, b: 12},  // orange
  // {r: 242, g: 127, b: 242},  // purple
  // {r: 127, g: 127, b: 242},  // light blue
  // {r: 127, g: 242, b: 127},  // light green
  // {r: 127, g: 127, b: 127},  // gray
  // {r: 12, g: 12, b: 12},  // black
]


// ==========================================================================
// TYPES

type VibeConfig = {
  hidden: boolean
  paused: boolean
  strength: number
}

type RGB = {
  r: number
  g: number
  b: number
}

type VibeTargetMode = "OVERRIDE" | "EXCLUSIVE"

type VibeTarget = {
  device: string
  value: number
}

type VibeFrame = {
  id: number
  duration: number
  value: number
  targets: VibeTarget[]
  mode: VibeTargetMode
}

type VibeGroup = {
  username: string
  frames: VibeFrame[]
}

type VibeDevice = {
  name: string
}


// ==========================================================================
// STATE

const canvas = ref<HTMLCanvasElement | null>(null)
let chart: Chart | null = null

const connected = ref<boolean>(false)
let ws: WebSocket | null = null

const config = ref<VibeConfig>({
  hidden: false,
  paused: false,
  strength: 100,
})

const devices = ref<VibeDevice[]>([])

const username = ref<string>("")
let tFrameBegin = 0
let tFrameEnd = 0
const tNow = ref<number>(0)
const tTotal = ref<number>(0)

let tUpdatedAt: number = 0
let rafId = 0


// ==========================================================================
// INIT

onMounted(() => {
  if (!initChart()) {
    console.error("Failed to initialize chart")
    return
  }
  wsConnect()
})

onUnmounted(() => {
  ws?.close()
  cancelAnimationFrame(rafId)
})

Chart.register({
  id: "cursorLine",

  afterDatasetsDraw(chart: Chart<"line">) {
    const { ctx, scales } = chart
    const { bottom } = chart.chartArea
    const x = scales.x!.getPixelForValue(tNow.value)

    let lineTop = bottom  // start at the lowest possible point
    for (const ds of chart.data.datasets) {
      const data = ds.data as Point[]
      if (!data.length) continue

      const vNow = getChartValueAtTime(data, tNow.value)
      if (vNow == null) continue

      const y = scales.y!.getPixelForValue(vNow)

      if (y < lineTop) {
        lineTop = y
      }
    }

    ctx.save()

    ctx.beginPath()
    ctx.moveTo(x, lineTop)
    ctx.lineTo(x, bottom)

    ctx.strokeStyle = "rgba(255, 255, 255, 0.7)"
    ctx.lineWidth = 1
    ctx.setLineDash([4, 4]) // optional dashed line
    ctx.stroke()

    ctx.restore()
  }
})

Chart.register({
  id: "cursorPoint",

  afterDatasetsDraw(chart: Chart<"line">) {
    const { ctx, scales } = chart
    const x = scales.x!.getPixelForValue(tNow.value)

    chart.data.datasets.forEach((ds, i) => {
      if (!ds.data.length) return

      const data = ds.data as Point[]
      const vNow = getChartValueAtTime(data, tNow.value) ?? 0
      const y = scales.y!.getPixelForValue(vNow)
      const color = getLineColor(i)

      ctx.save()
      ctx.beginPath()
      ctx.fillStyle = toCssRgba(color, 1.0)
      ctx.arc(x, y, 6, 0, Math.PI * 2)
      ctx.fill()
      ctx.restore()
    })
  }
})

// Chart.register({
//   id: "lineGlow",

//   beforeDatasetsDraw(chart: Chart<"line">) {
//     const ctx = chart.ctx
//     ctx.save()
//     ctx.shadowBlur = 12
//     ctx.shadowColor = "rgba(255,255,255,0.7)"
//     ctx.lineWidth = 2
//   },

//   afterDatasetsDraw(chart: Chart) {
//     chart.ctx.restore()
//   },
// })

function initChart(): boolean {
  if (!canvas.value) return false

  chart = new Chart(canvas.value, {
    type: "line",
    data: {
      datasets: LINE_COLORS.map(color => ({
        data: [],
        parsing: false,
        // stepped: "before",
        tension: STEP_TENSION,

        backgroundColor: toCssRgba(color, 0.2),
        fill: 'origin',

        borderColor: toCssRgba(color, 0.7),
        borderWidth: 3,

        pointBackgroundColor: toCssRgba(color, 0.9),
        pointBorderColor: "#fff",
        pointBorderWidth: 0,
        pointRadius: 0,

        segment: {
          // borderColor: (ctx: ScriptableLineSegmentContext) => {
          //   return toCssRgba(color, ctx.p0.parsed.x! > tNow.value ? 0.3 : 0.9)
          // },
          // borderDash: (ctx: ScriptableLineSegmentContext) => {
          //   return ctx.p1.parsed.x! > tNow.value ? [4, 6] : undefined
          // },
        },
      })),
    },
    options: {
      responsive: false,
      animation: false,
      plugins: {
        legend: { display: false },
        tooltip: { enabled: false },
      },
      scales: {
        x: {
          type: "linear",
          display: false,
          grid: { display: false },
          min: -VISIBLE_PAST,
          max: VISIBLE_FUTURE,
        },
        y: {
          display: false,
          grid: { display: false },
          min: 0,
          max: 1,
        },
      },
    },
  })

  return true
}

function wsConnect(): void {
  ws?.close()
  console.info("(Re)connecting to WebSocket...")
  ws = new WebSocket(`${ws_url}/vibegraph/`)

  ws.onopen = () => {
    connected.value = true
    console.info("Connected to WebSocket")
  }

  ws.onclose = () => {
    connected.value = false
    console.info("Disconnected from WebSocket")
    setTimeout(wsConnect, 1000)
  }

  ws.onmessage = e => {
    const msg = JSON.parse(e.data)
    console.debug("WebSocket message received:", msg)

    let doUpdate = false
    switch (msg.type) {
      case "ping":
        break

      case "update-config":
        config.value = msg.config
        break

      case "update-devices":
        doUpdate = updateDevices(msg.devices)
        break

      case "reset-group":
        resetGroup()
        break

      case "set-group":
        doUpdate = setGroup(msg.group)
        startUpdateLoop()
        break

      case "add-frame":
        doUpdate = addFrame(msg.frame)
        startUpdateLoop()
        break

      case "advance":
        doUpdate = advance(msg.amount)
        break

      default:
        console.error(`Unknown message type: ${msg.type}`)
    }

    if (doUpdate) {
      update(false)
    }
  }
}

function getLength(): number {
  return chart?.data.datasets[0]!.data.length || 0
}

function isEmpty(): boolean {
  return getLength() === 0
}

function startUpdateLoop(): void {
  if (rafId != 0) return
  updateLoop()
}

function updateLoop(): void {
  if (isEmpty()) {
    rafId = 0
    resetGroup()
    return
  }

  update()
  rafId = requestAnimationFrame(updateLoop)
}

function updateDevices(updatedDevices: VibeDevice[]): boolean {
  // Early exit if nothing changed
  if (
    devices.value.length === updatedDevices.length &&
    devices.value.every((d, i) => d.name === updatedDevices[i]?.name)
  ) {
    return false
  }

  const datasets = chart!.data.datasets

  // Map old device name -> dataset data
  const oldDataByName = new Map<string, any[]>()
  devices.value.forEach((device, i) => {
    const ds = datasets[i]
    if (!ds) return
    oldDataByName.set(device.name, [...ds.data])
  })

  // Replace device list (respect dataset limit)
  devices.value.length = 0
  for (const d of updatedDevices.slice(0, datasets.length)) {
    devices.value.push(d)
  }

  // Rebuild datasets in new order
  devices.value.forEach((device, i) => {
    const ds = datasets[i]
    if (!ds) return
    ds.data = oldDataByName.get(device.name) || []
  })

  // Clear leftover datasets (removed devices)
  for (let i = devices.value.length; i < datasets.length; i++) {
    datasets[i]!.data.length = 0
  }

  return true
}

function resetGroup(): boolean {
  tFrameBegin = 0
  tFrameEnd = 0
  tNow.value = 0
  tTotal.value = 0
  username.value = ""

  if (isEmpty()) return false

  for (const ds of chart!.data.datasets) {
    ds.data.length = 0
  }

  return true
}

function setGroup(group: VibeGroup): boolean {
  let hasChanged = resetGroup()

  hasChanged = hasChanged || username.value !== group.username
  username.value = group.username

  for (const frame of group.frames) {
    hasChanged = addFrame(frame) || hasChanged
  }

  return hasChanged
}

function addFrame(frame: VibeFrame): boolean {
  if (frame.duration <= 0) return false

  let hasChanged = false

  const targetByDevice = mapVibeTargets(frame)
  devices.value.forEach((device, i) => {
    const ds = chart!.data.datasets[i]
    if (!ds) return

    const target = targetByDevice.get(device.name)
    if (!target) return

    hasChanged = true
    ds.data.push({
      x: tTotal.value,
      y: target.value,
    }, {
      x: tTotal.value + frame.duration - Math.min(frame.duration * 0.2, STEP_SMOOTHING),
      y: target.value,
    })
  })

  if (!hasChanged) return false

  tTotal.value += frame.duration

  return true
}

function advance(amount: number): boolean {
  if (amount <= 0) return false
  tFrameBegin = tFrameEnd
  tFrameEnd += amount
  tNow.value = tFrameBegin
  return true
}

function prune(): boolean {
  let hasChanged = false
  const cutoff = tNow.value - VISIBLE_PAST

  chart!.data.datasets.forEach(ds => {
    const data = ds.data as Point[]
    if (!data.length) return

    // Find first point whose x is past the cutoff
    let i = 0
    while (i < data.length && data[i]!.x! < cutoff) {
      i++
    }

    // Remove points before the cutoff
    // Case 1: everything is before cutoff → clear all
    if (i === data.length) {
      data.length = 0
      hasChanged = true
    }
    // Case 2: keep exactly one padding point
    else if (i > 1) {
      data.splice(0, i - 1)
      hasChanged = true
    }
  })

  return hasChanged
}

function update(advance: boolean = true): boolean {
  const t = performance.now()
  const dt = t - tUpdatedAt
  tUpdatedAt = t

  if (dt <= 0) return false

  let hasChanged = false

  if (advance && tNow.value < tFrameEnd) {
    hasChanged = true
    tNow.value = Math.min(tNow.value + dt, tFrameEnd)

    // scroll window
    chart!.options.scales!.x!.min = tNow.value - VISIBLE_PAST
    chart!.options.scales!.x!.max = tNow.value + VISIBLE_FUTURE
  }

  hasChanged = prune() || hasChanged

  if (hasChanged) {
    chart!.update()
  }

  return hasChanged
}

function mapVibeTargets(frame: VibeFrame): Map<string, VibeTarget> {
  const targets = new Map<string, VibeTarget>()

  // Always add explicit targets first
  for (const target of frame.targets) {
    targets.set(target.device, target)
  }

  // OVERRIDE mode fills missing devices with default value
  if (frame.mode === "OVERRIDE") {
    for (const device of devices.value) {
      if (!targets.has(device.name)) {
        targets.set(device.name, {
          device: device.name,
          value: frame.value,
        })
      }
    }
  }

  return targets
}

function getChartValueAtTime(data: Point[], time: number): number | null {
    let last: Point | null = null;

    for (const p of data) {
        if (p.x! > time) break;
        last = p;
    }

    return last?.y ?? null;
}

function getLineColor(i: number): RGB {
  return LINE_COLORS[i % LINE_COLORS.length]!
}

function toCssRgba(rbg: RGB, a: number = 1): string {
  return `rgba(${rbg.r}, ${rbg.g}, ${rbg.b}, ${a})`
}

function formatTime(ms: number): string {
  const s = Math.floor(ms / 1000)
  const minutes = Math.floor(s / 60).toString().padStart(2, "0");
  const seconds = (s % 60).toString().padStart(2, "0");
  return `${minutes}:${seconds}`
}
</script>

<style scoped>
.title {
  margin-top: 0.6rem;
}

.title-prefix {
  color: #999;
  font-size: 1.0rem;
}

.title-username {
  font-size: 1.5rem;
  font-weight: bold;
}

.graph {
  width: 100vw;

  margin: 0.5rem 0;

  image-rendering: pixelated;
}

.controls {
  margin: 0 0.6rem;

  align-items: normal;
}

.devices {
  flex-wrap: wrap;
  justify-content: start;
  align-items: start;
}

.device {
  margin-right: 0.5rem;
  margin-bottom: 0.5rem;

  --icon-color: rgba(242, 12, 127, 1.0);
}

.device.row {
  align-items: normal;
  text-align: left;
}

.device-icon {
  width: 2rem;
  height: 2rem;

  margin-right: 0.3rem;
  margin-bottom: 0.3rem;
  padding: 0.1rem;

  background-color: rgba(255, 255, 255, 0.3);

  border-radius: 1000rem;
  border: 0.15rem solid var(--icon-color);

  transition: border-color 0.2s ease;
}

.device-icon-mask {
  width: 100%;
  height: 100%;

  background-color: var(--icon-color);

  transition: background-color 0.2s ease;

  mask-repeat: no-repeat;
  mask-position: center;
  mask-size: contain;

  -webkit-mask-repeat: no-repeat;
  -webkit-mask-position: center;
  -webkit-mask-size: contain;
}

.device-name {
  width: 4.2rem;

  font-size: 1rem;
  color: #999;

  word-wrap: break-word;
}

.time {
  font-size: 1.5rem;
  font-weight: bold;
}
</style>
