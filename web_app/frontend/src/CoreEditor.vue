<script setup lang="ts">
import { computed, ref } from "vue";
import type { Spec, Bootstrap } from "./types";
const props = withDefaults(
  defineProps<{
    spec: Spec;
    meta: Bootstrap;
    inductor?: boolean;
    material?: boolean;
  }>(),
  { inductor: false, material: true },
);
const emit = defineEmits<{ change: [spec: Spec] }>();
const dimensions = [
  { key: "Ae", label: "有效截面积", power: 2 },
  { key: "Ve", label: "有效体积", power: 3 },
  { key: "Wa", label: "窗口面积", power: 2 },
  { key: "MLT", label: "平均匝长", power: 1 },
];
const units = ref<Record<string, string>>({
  Ae: "mm",
  Ve: "mm",
  Wa: "mm",
  MLT: "mm",
});
const choice = computed(() =>
    props.inductor ? "core_choice_L" : "core_choice",
  ),
  geometry = computed(() => (props.inductor ? "custom_core_L" : "custom_core"));
const cores = computed(() =>
  !props.inductor && props.spec.core_shape && props.spec.core_shape !== "auto"
    ? props.meta.core_shapes?.[props.spec.core_shape] ||
      Object.keys(props.meta.cores)
    : Object.keys(props.meta.cores),
);
function clone() {
  return JSON.parse(JSON.stringify(props.spec));
}
function set(key: string, value: any) {
  const next = clone();
  next[key] = value;
  emit("change", next);
}
function selectCore(value: string) {
  const next = clone();
  next[choice.value] = value;
  if (value === "自定义（非标准）" && !next[geometry.value]?.Ae)
    next[geometry.value] = {
      name: "自定义磁芯",
      Ae: { v: 0, u: "mm²" },
      Ve: { v: 0, u: "mm³" },
      Wa: { v: 0, u: "mm²" },
      MLT: { v: 0, u: "mm" },
    };
  emit("change", next);
}
function shape(value: string) {
  const next = clone();
  next.core_shape = value;
  if (
    next.core_choice !== "自定义（非标准）" &&
    value !== "auto" &&
    !props.meta.core_shapes?.[value]?.includes(next.core_choice)
  )
    next.core_choice = "auto";
  emit("change", next);
}
function chooseMaterial(value: string) {
  const next = clone();
  next.core_material = value;
  const p = props.meta.materials[value];
  if (p && value !== "Custom")
    Object.assign(next, { k_core: p.k, a_core: p.a, b_core: p.b });
  emit("change", next);
}
function si(key: string, power: number) {
  const raw = props.spec[geometry.value]?.[key];
  if (typeof raw === "object" && raw) {
    const u = String(raw.u || "").toLowerCase();
    const factor = u.startsWith("mm") ? 1e-3 : u.startsWith("cm") ? 1e-2 : 1;
    return Number(raw.v || 0) * factor ** power;
  }
  return Number(raw || 0);
}
function suffix(base: string, power: number) {
  return base + (power === 2 ? "²" : power === 3 ? "³" : "");
}
function shown(key: string, power: number) {
  return Number(
    (
      si(key, power) /
      (units.value[key] === "cm" ? 1e-2 : 1e-3) ** power
    ).toPrecision(10),
  );
}
function input(key: string, power: number, value: string) {
  const next = clone();
  next[geometry.value] ||= {};
  next[geometry.value][key] = {
    v: value === "" ? null : Number(value),
    u: suffix(units.value[key] || "mm", power),
  };
  emit("change", next);
}
</script>
<template>
  <div class="core-editor">
    <h4>{{ inductor ? "独立输出电感磁芯" : "磁芯与有效几何" }}</h4>
    <label v-if="material" class="stacked-label"
      >磁芯材料（主动选择后加载损耗系数）<select
        :value="spec.core_material"
        @change="chooseMaterial(($event.target as HTMLSelectElement).value)"
      >
        <option v-for="(_, name) in meta.materials" :value="name">
          {{ name }}
        </option>
      </select></label
    ><label v-if="!inductor" class="stacked-label"
      >磁芯形状<select
        :value="spec.core_shape || 'auto'"
        @change="shape(($event.target as HTMLSelectElement).value)"
      >
        <option value="auto">不限形状 / 自动</option>
        <option v-for="(_, name) in meta.core_shapes" :value="name">
          {{ name }}
        </option>
      </select></label
    ><label class="stacked-label"
      >{{ inductor ? "电感磁芯型号" : "磁芯型号"
      }}<select
        :value="spec[choice]"
        @change="selectCore(($event.target as HTMLSelectElement).value)"
      >
        <option value="auto">自动选择磁芯</option>
        <option value="自定义（非标准）">自定义（非标准）</option>
        <option v-for="name in cores" :value="name">{{ name }}</option>
      </select></label
    ><template v-if="spec[choice] === '自定义（非标准）'"
      ><label class="field-row"
        >磁芯名称<input
          class="name-input"
          :value="spec[geometry]?.name"
          @input="
            set(geometry, {
              ...spec[geometry],
              name: ($event.target as HTMLInputElement).value,
            })
          " /></label
      ><label v-for="d in dimensions" class="field-row"
        ><span>{{ d.label }} {{ d.key }}</span
        ><span class="quantity"
          ><input
            type="number"
            step="any"
            :value="shown(d.key, d.power)"
            :aria-label="(inductor ? '电感' : '') + d.key"
            @input="
              input(d.key, d.power, ($event.target as HTMLInputElement).value)
            "
          /><select v-model="units[d.key]" :aria-label="d.key + '几何单位'">
            <option value="mm">{{ suffix("mm", d.power) }}</option>
            <option value="cm">{{ suffix("cm", d.power) }}</option>
          </select></span
        ></label
      >
      <p class="hint">
        填写有效磁芯几何，不是外形包络。切换 mm / cm 只改变显示，不改变物理量。
      </p></template
    >
    <p v-if="material" class="hint">
      k、α、β 仍在本组直接编辑；材料预设不代表所有温度和磁通工况。
    </p>
    <p v-if="material && ['FLYBACK','QR-FLYBACK','ACF-FORWARD'].includes(spec.topology) && meta.permeability_materials" class="hint">
      材料初始磁导率 μi={{ meta.permeability_materials[spec.core_material]?.mu_r ?? '待提供' }}。
      μr 填 0 时采用该预设，可在“磁导率与气隙估算”中修改。有效磁路长度 le 自动取 Ve/Ae，平均匝长 MLT 用于铜阻计算。
    </p>
  </div>
</template>
<style scoped>
.core-editor {
  padding: 12px 0;
}
.core-editor h4 {
  font-size: 15px;
  margin: 0 0 14px;
  color: #294b73;
}
.core-editor .stacked-label {
  margin: 12px 0;
}
.core-editor select {
  min-height: 36px;
}
.core-editor input {
  min-height: 34px;
}
</style>
