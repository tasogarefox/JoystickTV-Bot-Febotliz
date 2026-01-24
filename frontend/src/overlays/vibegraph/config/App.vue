<template>
  <div v-show="initialized" class="config-page">
    <h2>Vibegraph Configuration</h2>

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

    <div class="field">
      <label>
        Strength: <strong>{{ config.strength }}</strong>
      </label>
      <br />
      <input
        type="range"
        min="0"
        max="100"
        v-model.number="config.strength"
      />
    </div>

    <button class="clear-btn" @click="clearQueue">Clear Queue</button>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted } from "vue"
import axios from "axios"
import { useDebounceFn } from "@vueuse/core"

import { ws_url } from "@/settings"


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

.field {
  margin-bottom: 1rem;
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
