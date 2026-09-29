<template>
  <router-view />
</template>

<script setup lang="ts">
import 'pretendard/dist/web/variable/pretendardvariable-dynamic-subset.css';
import { useTheme } from './composables/useTheme';

defineOptions({ name: 'App' });
useTheme().init();
</script>
