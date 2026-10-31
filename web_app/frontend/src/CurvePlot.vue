<script setup lang="ts">
import { computed, ref } from "vue";
import { fmt } from "./types";
const props = withDefaults(
  defineProps<{
    lines?: { name?: string; points: number[][] }[];
    xScale?: number;
    yScale?: number;
    xLabel?: string;
    yLabel?: string;
  }>(),
  { xScale: 1, yScale: 1, xLabel: "X", yLabel: "Y" },
);
const logY = ref(false),
  colors = ["#2468b3", "#138a7c", "#b66d21", "#8b55a6", "#b03a52", "#377792"];
const data = computed(() =>
  (props.lines || []).map((line) => ({
    ...line,
    points: (line.points || [])
      .filter(
        (p) =>
          p.length >= 2 &&
          p.slice(0, 2).every(Number.isFinite) &&
          (!logY.value || p[1] > 0),
      )
      .map((p) => [p[0] * props.xScale, p[1] * props.yScale]),
  })),
);
const extents = computed(() => {
  const all = data.value.flatMap((l) => l.points);
  const xs = all.map((p) => p[0]),
    ys = all.map((p) => (logY.value ? Math.log10(p[1]) : p[1]));
  return {
    x0: Math.min(...xs, 0),
    x1: Math.max(...xs, 1e-20),
    y0: logY.value ? Math.min(...ys) : Math.min(...ys, 0),
    y1: Math.max(...ys, logY.value ? -Infinity : 1e-20),
  };
});
function point(p: number[]) {
  const e = extents.value;
  return [
    65 + ((p[0] - e.x0) / Math.max(e.x1 - e.x0, 1e-30)) * 475,
    278 -
      (((logY.value ? Math.log10(p[1]) : p[1]) - e.y0) /
        Math.max(e.y1 - e.y0, 1e-30)) *
        235,
  ];
}
function ticks(axis: "x" | "y") {
  const e = extents.value;
  return Array.from({ length: 5 }, (_, i) => {
    const v =
      (axis === "x" ? e.x0 : e.y0) +
      ((axis === "x" ? e.x1 - e.x0 : e.y1 - e.y0) * i) / 4;
    return {
      p: axis === "x" ? 65 + (475 * i) / 4 : 278 - (235 * i) / 4,
      label: fmt(axis === "y" && logY.value ? 10 ** v : v, "", 3),
    };
  });
}
</script>
<template>
  <div class="curve-preview">
    <label class="checkbox-label"
      ><input v-model="logY" type="checkbox" />预览 Y
      对数轴（不修改导入数据）</label
    ><svg
      v-if="data.some((l) => l.points.length)"
      viewBox="0 0 580 330"
      role="img"
      aria-label="导入曲线坐标预览"
    >
      <rect
        x="65"
        y="43"
        width="475"
        height="235"
        fill="#fafcfe"
        stroke="#bdcad9"
      />
      <g v-for="t in ticks('x')">
        <path :d="`M ${t.p} 43 V 278`" stroke="#e1e7ef" />
        <text :x="t.p" y="298" text-anchor="middle">{{ t.label }}</text>
      </g>
      <g v-for="t in ticks('y')">
        <path :d="`M 65 ${t.p} H 540`" stroke="#e1e7ef" />
        <text x="55" :y="t.p + 4" text-anchor="end">{{ t.label }}</text>
      </g>
      <polyline
        v-for="(line, i) in data"
        :points="line.points.map((p) => point(p).join(',')).join(' ')"
        fill="none"
        :stroke="colors[i % colors.length]"
        stroke-width="2.5"
      />
      <text x="300" y="324" text-anchor="middle">{{ xLabel }}</text>
      <text transform="translate(17 160) rotate(-90)" text-anchor="middle">
        {{ yLabel }}
      </text>
    </svg>
    <p v-else class="hint">暂无可预览的坐标点。</p>
    <div class="curve-legend">
      <span
        v-for="(line, i) in data"
        :style="{ color: colors[i % colors.length] }"
        >● {{ line.name || "曲线 " + (i + 1) }}</span
      >
    </div>
    <p class="hint">
      只作坐标核对；抽样预览不减少真实导入点数，也不代表已验证器件测试条件。
    </p>
  </div>
</template>
<style scoped>
.curve-preview {
  padding: 12px 0;
}
.curve-preview svg {
  display: block;
  width: 100%;
  margin: 12px 0;
}
.curve-preview text {
  font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
  font-size: 13px;
  fill: #445b75;
}
.curve-legend {
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
  font-size: 14px;
}
.curve-preview .hint {
  font-size: 13px;
}
</style>
