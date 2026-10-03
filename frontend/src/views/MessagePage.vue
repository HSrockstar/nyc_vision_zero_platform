<script setup lang="ts">defineProps<{ forbidden?: boolean }>()</script>
<template><section class="message-page"><span class="message-code">{{ forbidden ? '403' : '404' }}</span><h2>{{ forbidden ? '当前账户无法访问此页面' : '没有找到这个页面' }}</h2><p class="detail">{{ forbidden ? '请使用左侧导航访问当前角色允许的功能。' : '页面地址可能已变更，请返回工作总览继续。' }}</p><RouterLink class="button-link" to="/">返回工作总览</RouterLink></section></template>
