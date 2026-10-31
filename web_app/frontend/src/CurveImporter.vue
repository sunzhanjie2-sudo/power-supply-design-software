<script setup lang="ts">
import { ref, computed } from "vue";
import { post } from "./api";
import type { CurveTarget, Spec } from "./types";
import Icon from "./Icon.vue";
import CurvePlot from "./CurvePlot.vue";
const props = defineProps<{ target: CurveTarget; spec: Spec }>();
const emit = defineEmits<{ close: []; applied: [spec: Spec] }>();
const filename = ref(""),
  content = ref(""),
  info = ref<any>(null),
  index = ref(0),
  busy = ref(false),
  error = ref("");
const x = ref(1),
  y = ref(1),
  start = ref<number | null>(null),
  end = ref<number | null>(null);
const fileInput = ref<HTMLInputElement>();
const choices = [
  { v: 1, s: "1 · 原值 / SI" },
  { v: 1e-3, s: "m · 10⁻³" },
  { v: 1e-6, s: "µ · 10⁻⁶" },
  { v: 1e-9, s: "n · 10⁻⁹" },
  { v: 1e-12, s: "p · 10⁻¹²" },
  { v: 1e3, s: "k · 10³" },
];
const selected = computed(() => info.value?.curves?.[index.value]);
function selectCurve() {
  const pair = selected.value?.plateau;
  start.value = pair?.[0] ?? null;
  end.value = pair?.[1] ?? null;
}
async function read(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0];
  if (!file) return;
  error.value = "";
  if (file.size > 5 * 1024 * 1024) {
    error.value = "文件不可超过5 MiB";
    return;
  }
  filename.value = file.name;
  content.value = await file.text();
  busy.value = true;
  try {
    info.value = await post("/curves/inspect", {
      filename: filename.value,
      content: content.value,
      target: props.target.target,
    });
    index.value = 0;
    x.value = 1;
    y.value = 1;
    selectCurve();
  } catch (e: any) {
    error.value = e.message;
    info.value = null;
  } finally {
    busy.value = false;
  }
}
async function apply() {
  busy.value = true;
  error.value = "";
  try {
    const result = await post("/curves/apply", {
      filename: filename.value,
      content: content.value,
      target: props.target.target,
      spec: props.spec,
      index: index.value,
      x_multiplier: x.value,
      y_multiplier: y.value,
      plateau_start: start.value,
      plateau_end: end.value,
    });
    emit("applied", result.spec);
  } catch (e: any) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}
</script>
<template>
  <div class="modal-backdrop" @click.self="emit('close')">
    <section
      class="modal import-modal"
      role="dialog"
      aria-modal="true"
      aria-label="导入器件曲线"
    >
      <header>
        <div>
          <span class="eyebrow">DEVICE CURVE</span>
          <h2>导入曲线 · {{ target.ref }}</h2>
        </div>
        <button class="icon-button" aria-label="关闭" @click="emit('close')">
          <Icon name="close" />
        </button>
      </header>
      <div class="modal-body">
        <div class="curve-object">
          <Icon name="chip" :size="25" />
          <div>
            <strong>{{ target.role }}</strong>
            <p>{{ target.axes }}</p>
          </div>
        </div>
        <button class="dropzone" @click="fileInput?.click()">
          <Icon name="upload" :size="28" /><strong>{{
            filename || "选择 CSV / JSON 曲线文件"
          }}</strong
          ><span>支持简单 x,y 坐标 · 不根据文件名猜测物理量</span></button
        ><input
          ref="fileInput"
          type="file"
          accept=".csv,.json"
          class="visually-hidden"
          @change="read"
        /><template v-if="info"
          ><label class="stacked-label"
            >文件内曲线<select v-model="index" @change="selectCurve">
              <option v-for="item in info.curves" :value="item.index">
                {{ item.name }} · {{ item.points }} 点
              </option>
            </select></label
          >
          <div class="two-fields">
            <label class="stacked-label"
              >X 轴数量级<select v-model="x" :disabled="!info.simple">
                <option v-for="option in choices" :value="option.v">
                  {{ option.s }}
                </option>
              </select></label
            ><label class="stacked-label"
              >Y 轴数量级<select v-model="y" :disabled="!info.simple">
                <option v-for="option in choices" :value="option.v">
                  {{ option.s }}
                </option>
              </select></label
            >
          </div>
          <p class="hint">
            若描点文件已乘数量级（例如电荷已是 C），请选择 1，避免再次乘
            n。带结构的旧格式沿用 SI。
          </p>
          <CurvePlot
            :lines="selected?.sample_curves"
            :x-scale="x"
            :y-scale="y"
            x-label="X（换算后）"
            y-label="Y（换算后）" />
          <div
            v-if="target.target === 'Q1:charge' && info.simple"
            class="notice"
          >
            <strong>请确认米勒平台两端的 X 坐标</strong>
            <p>
              建议值来自原有识别方法，必须对照原图核对；单位与原始 X 数值相同。
            </p>
            <div class="two-fields">
              <label class="stacked-label"
                >平台起点（Qgs）<input
                  v-model.number="start"
                  type="number"
                  step="any" /></label
              ><label class="stacked-label"
                >平台终点<input v-model.number="end" type="number" step="any"
              /></label>
            </div></div
        ></template>
        <p v-if="error" class="error-box">{{ error }}</p>
      </div>
      <footer>
        <button class="button" @click="emit('close')">取消</button
        ><button
          class="button primary"
          :disabled="!info || busy"
          @click="apply"
        >
          <span v-if="busy" class="spinner" /><Icon
            v-else
            name="check"
          />确认导入到 {{ target.ref }}
        </button>
      </footer>
    </section>
  </div>
</template>
