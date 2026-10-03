<script setup lang="ts">
import GovernancePanel from '../components/GovernancePanel.vue'
import { governanceProfile } from '../workspace'
</script>
<template><GovernancePanel :profile="governanceProfile" /></template>
