<script setup lang="ts">
import { useRouter } from 'vue-router'
import RiskPanel from '../components/RiskPanel.vue'
import { governanceProfile } from '../workspace'
import type { RiskProfile } from '../api/m4'
const router = useRouter()
function select(profile: RiskProfile) { governanceProfile.value = profile; void router.push('/governance') }
</script>
<template><RiskPanel @governance="select" /></template>
