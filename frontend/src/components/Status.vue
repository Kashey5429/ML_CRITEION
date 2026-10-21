<script setup lang="ts">
import { labels } from '../api'
defineProps<{ value: string }>()
</script>
<template>
  <span class="badge" :class="value"><i></i>{{ labels[value] || value }}</span>
</template>
