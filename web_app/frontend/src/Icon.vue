<script setup lang="ts">
withDefaults(defineProps<{ name: string; size?: number }>(), { size: 18 });
const paths: Record<string, string> = {
  bolt: "m13 2-9 12h7l-1 8 10-12h-7l1-8Z",
  grid: "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
  upload: "M12 16V3m-5 5 5-5 5 5M4 15v5h16v-5",
  download: "M12 3v13m-5-5 5 5 5-5M4 16v5h16v-5",
  play: "m8 5 12 7-12 7V5Z",
  check: "m5 12 4 4L19 6",
  close: "m6 6 12 12M18 6 6 18",
  search: "M21 21l-5-5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0",
  chevron: "m8 10 4 4 4-4",
  settings: "M12 8v8M8 12h8M4 4h16v16H4z",
  file: "M14 2H5v20h14V7l-5-5Zm0 0v6h5M8 12h8M8 16h6",
  shield: "m12 2 9 4v6c0 6-9 10-9 10S3 18 3 12V6l9-4Zm-4 10 3 3 5-6",
  wave: "M2 12h4l3-8 5 16 3-8h5",
  chip: "M6 6h12v12H6zM9 1v5m6-5v5M9 18v5m6-5v5M1 9h5m-5 6h5m12-6h5m-5 6h5",
  book: "M3 4h7l2 2 2-2h7v16h-7l-2 2-2-2H3V4Zm9 2v16",
  clock: "M12 8v5l3 2M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0",
  chart: "M3 3v18h18M7 15V9m5 6V5m5 10v-4",
  circle: "M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0",
  info: "M12 11v6m0-10v1M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0",
  refresh:
    "M20 7v5h-5M4 17v-5h5M5 8a8 8 0 0 1 13-3l2 2M4 17l2 2a8 8 0 0 0 13-3",
  folder: "M3 5h6l2 2h10v13H3V5Z",
  expand: "M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5",
  layers: "m12 2 10 6-10 6L2 8l10-6ZM2 12l10 6 10-6M2 16l10 6 10-6",
  alert: "m12 3 10 18H2L12 3Zm0 6v5m0 3v1",
  code: "m8 6-6 6 6 6m8-12 6 6-6 6m-3-15-2 18",
  plus: "M12 5v14M5 12h14",
};
</script>
<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.7"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path :d="paths[name] || paths.circle" />
  </svg>
</template>
