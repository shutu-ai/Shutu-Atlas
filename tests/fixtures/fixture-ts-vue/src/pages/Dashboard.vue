<template><main class="dark-dashboard"><KpiCard label="Active jobs" value="42" /><div id="trend-chart"></div><select aria-label="Filter"><option>All</option></select><table><tr><td>Running</td></tr></table></main></template>
<script setup lang="ts">import * as echarts from 'echarts'; import KpiCard from '../components/KpiCard.vue'; const trend = echarts.init(document.querySelector('#trend-chart')!); trend.setOption({});</script>

