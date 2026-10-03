<script setup lang="ts">
import type { IconName } from '../navigation'
defineProps<{ name: IconName }>()
const paths: Record<IconName, string> = {
  overview: 'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',
  collisions: 'M7 3h7l4 4v14H4V3h3 M14 3v5h4 M8 12h6 M8 16h4',
  map: 'm3 5 6-2 6 2 6-2v16l-6 2-6-2-6 2V5z M9 3v16 M15 5v16',
  risks: 'm12 3 9 17H3L12 3z M12 9v5 M12 17v.2',
  governance: 'M9 5H5v16h14V5h-4 M9 3h6v4H9z M8 12l2 2 5-5 M8 18h7',
  statistics: 'M4 3v18h17 M8 16v-5 M13 16V6 M18 16v-8',
  imports: 'M12 15V3 m-4 4 4-4 4 4 M4 13v7h16v-7',
  users: 'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2 M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8 M17 4a4 4 0 0 1 0 7 M22 21v-2a4 4 0 0 0-3-3.8',
  menu: 'M4 6h16 M4 12h16 M4 18h16', chevron: 'm14 6-6 6 6 6',
  logout: 'M9 3H3v18h6 M9 12h12 m-5-5 5 5-5 5', arrow: 'M4 12h16 m-6-6 6 6-6 6',
  shield: 'm12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3z m-4 9 3 3 5-6',
}
</script>
<template><svg class="app-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path :d="paths[name]" /></svg></template>
