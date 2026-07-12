<template>
  <div v-show="initialized" class="config-page">
    <h2>Vibegraph Configuration</h2>

    <div class="row stretch">
      <div class="column stretch">
        <div class="field strength-field">
          <label>
            Strength: <strong>{{ config.strength }}</strong>
          </label>
          <br />
          <input
            class="vertical-slider"
            type="range"
            min="0"
            :max="STRENGTH_MAX"
            v-model.number="config.strength"
            @wheel.prevent="onStrengthWheel"
          />
        </div>
      </div>

      <div class="column stretch">
        <div class="field">
          <label>
            <input type="checkbox" v-model="config.hidden" />
            Hidden
          </label>
        </div>

        <div class="field">
          <label>
            <input type="checkbox" v-model="config.paused" />
            Paused
          </label>
        </div>

        <div class="spacer"></div>

        <div class="field">
          <button class="clear-btn" @click="clearQueue">Clear Queue</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted } from "vue"
import axios from "axios"
import { useDebounceFn } from "@vueuse/core"

import { ws_url } from "@/settings"

const STRENGTH_MAX = 200


// ==========================================================================
// TYPES

type VibeConfig = {
  hidden: boolean
  paused: boolean
  strength: number
}


// ==========================================================================
// STATE

const api = axios.create({
  baseURL: `${ws_url}/vibegraph/`,
})

const initialized = ref(false)

const config = ref<VibeConfig>({
  hidden: false,
  paused: false,
  strength: 100,
})


// ==========================================================================
// INIT

watch(
  config,
  () => { if (initialized.value) submitConfig() },
  { deep: true },
)

onMounted(async () => {
  await loadConfig()
  initialized.value = true
})


// ==========================================================================
// METHODS

function onStrengthWheel(event: WheelEvent) {
  const delta = event.deltaY > 0 ? -1 : 1
  const value = config.value.strength + delta
  config.value.strength = Math.max(0, Math.min(STRENGTH_MAX, value))
}

async function loadConfig() {
  const { data } = await api.get("/config")
  config.value = data
}

const submitConfig = useDebounceFn(async () => {
  await api.post("/config", {
    ...config.value,
  })
}, 300)

const clearQueue = useDebounceFn(async () => {
  await api.post("/clear")
}, 300)
</script>

<style scoped>
.config-page {
  padding: 1rem;
  max-width: 400px;
}

.row {
  display: flex;
  flex-direction: row;
  justify-content: center;
  align-items: center;
}

.column {
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
}

.center {
  justify-content: center;
  align-items: center;
}

.stretch {
  align-items: stretch;
}

.spacer {
  flex-grow: 1;  /* expand to take all available space in a flex container */
}

.vertical-slider {
  writing-mode: vertical-lr;
  direction: rtl;

  height: 300px;
  width: 50px;
  cursor: pointer;
}

.field {
  margin-bottom: 1rem;
}

.strength-field {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;

  .vertical-slider {
    width: 150px;
  }
}

/* button.clear-btn {
  padding: 0.4rem 0.8rem;
  background-color: #f0f0f0;
  border: 1px solid #ccc;
  border-radius: 4px;
  cursor: pointer;
}

button.clear-btn:hover {
  background-color: #e0e0e0;
} */
</style>
