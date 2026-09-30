<script setup lang="ts">
import { sessionUser } from '../api/auth'
import CollisionPanel from './CollisionPanel.vue'
import ImportPanel from './ImportPanel.vue'
import MapPanel from './MapPanel.vue'
</script>

<template>
  <div class="workspace-panels">
    <CollisionPanel />
    <MapPanel />
    <ImportPanel v-if="sessionUser && sessionUser.role !== 'VIEWER'" />
  </div>
</template>
