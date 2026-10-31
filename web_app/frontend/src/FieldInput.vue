<script setup lang="ts">
import { ref, watch, computed } from "vue";
import type { Parameter } from "./types";
const props = defineProps<{
  field: Parameter;
  value: any;
  disabled?: boolean;
  hint?: string;
}>();
const emit = defineEmits<{ change: [value: any] }>();
const levels = [
  { v: 1e-12, s: "p" },
  { v: 1e-9, s: "n" },
  { v: 1e-6, s: "µ" },
  { v: 1e-3, s: "m" },
  { v: 1, s: "" },
  { v: 1e3, s: "k" },
  { v: 1e6, s: "M" },
];
const scalable = computed(
  () =>
    props.field.unit !== "" &&
    props.field.display_factor === 1 &&
    !["k_core", "a_core", "b_core", "Rth_transformer", "h_conv"].includes(
      props.field.name,
    ),
);
function best(value: number) {
  if (!value || !scalable.value) return 1;
  return levels.reduce((a, b) =>
    Math.abs(Math.log10(Math.abs(value / b.v)) - 1) <
    Math.abs(Math.log10(Math.abs(value / a.v)) - 1)
      ? b
      : a,
  ).v;
}
const prefix = ref(best(Number(props.value)));
const lastManual = ref<number | null>(
  Number(props.value) > 0 ? Number(props.value) : null,
);
const automatic = computed(() => props.field.auto_zero && props.value === 0);
const longUnit = computed(
  () => !scalable.value && props.field.display_unit.length > 8,
);
function toggleAuto(enabled: boolean) {
  if (enabled) {
    if (Number(props.value) > 0) lastManual.value = Number(props.value);
    emit("change", 0);
  } else emit("change", lastManual.value);
}
const shown = computed(() =>
  typeof props.value === "number"
    ? Number(
        ((props.value * props.field.display_factor) / prefix.value).toPrecision(
          10,
        ),
      )
    : (props.value ?? ""),
);
watch(
  () => props.field.name,
  () => (prefix.value = best(Number(props.value))),
);
function changed(event: Event) {
  const input = event.target as HTMLInputElement;
  emit(
    "change",
    input.value === ""
      ? null
      : (Number(input.value) * prefix.value) / props.field.display_factor,
  );
}
</script>
<template>
  <div
    class="field-row"
    :title="field.name + (field.auto_zero ? ' · 0 表示自动计算' : '')"
  >
    <span class="field-label"
      >{{ field.label }}<small>{{ field.symbol }}</small></span
    >
    <span v-if="field.type === 'boolean'" class="toggle-wrap"
      ><input
        type="checkbox"
        :checked="value"
        :aria-label="field.label"
        :disabled="disabled"
        @change="emit('change', ($event.target as HTMLInputElement).checked)"
      /><span>{{ value ? "启用" : "关闭" }}</span></span
    >
    <span v-else class="field-control"
      ><span class="quantity"
        ><input
          type="number"
          step="any"
          :value="shown"
          :aria-label="field.label"
          :disabled="disabled || automatic"
          @input="changed"
        /><select
          v-if="scalable"
          v-model="prefix"
          :aria-label="field.label + '单位'"
        >
          <option v-for="level in levels" :value="level.v">
            {{ level.s }}{{ field.unit }}
          </option></select
        ><span v-else-if="!longUnit" class="unit">{{
          field.display_unit || "—"
        }}</span></span
      >
      <span v-if="field.auto_zero" class="auto-control"
        ><input
          type="checkbox"
          :checked="automatic"
          :disabled="disabled"
          :aria-label="field.label + '自动'"
          @change="toggleAuto(($event.target as HTMLInputElement).checked)"
        />自动</span
      >
      <small v-if="longUnit" class="long-unit">{{ field.display_unit }}</small>
      <small v-if="hint" class="field-density">{{ hint }}</small>
    </span>
  </div>
</template>
<style scoped>
.field-control {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  align-items: center;
  gap: 6px;
  max-width: 190px;
}
.auto-control {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: #637a94;
}
.long-unit,
.field-density {
  flex-basis: 100%;
  text-align: right;
  font-size: 12px;
  color: #527592;
  line-height: 1.5;
}
.quantity input:disabled {
  background: #edf2f7;
  color: #7d8a9a;
}
</style>
