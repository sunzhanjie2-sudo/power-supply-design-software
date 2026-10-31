<script setup lang="ts">
import { computed } from 'vue';
const props = withDefaults(defineProps<{ modelValue: number; label: string; unit?: string; scale?: number; min?: number; max?: number; disabled?: boolean }>(), { unit: '', scale: 1 });
const emit = defineEmits<{ 'update:modelValue': [value: number] }>();
const shown = computed(() => Number.isFinite(props.modelValue) ? Number((props.modelValue / props.scale).toPrecision(10)) : '');
function change(event: Event) {
  const value = (event.target as HTMLInputElement).value;
  emit('update:modelValue', value === '' ? NaN : Number(value) * props.scale);
}
</script>
<template>
  <label class="advanced-number"><span>{{ label }}</span><span class="advanced-number-control"><input :value="shown" type="number" step="any" :min="min === undefined ? undefined : min / scale" :max="max === undefined ? undefined : max / scale" :disabled="disabled" @input="change" /><span v-if="unit">{{ unit }}</span></span></label>
</template>
<style scoped>
.advanced-number{display:grid;gap:7px;min-width:0;font-size:15px;line-height:1.5;color:#334155}.advanced-number-control{display:flex;align-items:center;gap:7px}.advanced-number input{min-width:0;width:100%;min-height:40px;border:1px solid #cbd5e1;border-radius:8px;padding:7px 10px;font:inherit;color:#0f172a;background:white}.advanced-number-control>span{white-space:nowrap;min-width:25px;font-size:14px;color:#64748b}.advanced-number input:focus{outline:2px solid #93c5fd;outline-offset:1px}.advanced-number input:disabled{background:#f1f5f9}
</style>
