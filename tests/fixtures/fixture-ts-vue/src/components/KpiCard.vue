<template><article class="kpi-card"><span>{{ label }}</span><strong>{{ value }}</strong></article></template>
<script setup lang="ts">defineProps<{ label: string; value: string }>();</script>
<style scoped>.kpi-card { background: var(--dashboard-surface); color: #e8f1ff; }</style>

