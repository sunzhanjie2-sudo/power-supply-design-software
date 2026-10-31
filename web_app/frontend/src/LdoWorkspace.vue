<script setup lang="ts">
import { ref, onMounted, watch, nextTick } from "vue";
import { request, post, postBlob, download } from "./api";
import { fmt, type Spec } from "./types";
const props = defineProps<{
  initialSpec: Spec;
  unitName: string;
  onState?: (s: Spec) => void;
}>();
const form = ref<Spec>(JSON.parse(JSON.stringify(props.initialSpec))),
  fields = ref<any[]>([]),
  result = ref<Spec | null>(null),
  dirty = ref(true),
  busy = ref(false),
  error = ref(""),
  notice = ref("");
const stateNames: Spec = {
  pass: "模型内满足",
  review: "需核对",
  undefined: "资料待补充",
  na: "不适用",
};
const copy = (v: any) => JSON.parse(JSON.stringify(v));
function publish() {
  props.onState?.({
    spec: copy(form.value),
    preview: {
      outputs: [
        {
          V_out: form.value.V_out,
          P_out: form.value.V_out * form.value.I_out_max,
        },
      ],
    },
  });
}
watch(
  form,
  () => {
    dirty.value = true;
    publish();
  },
  { deep: true },
);
function number(k: string, scale: number, event: Event) {
  const value = (event.target as HTMLInputElement).value;
  form.value[k] = value === "" ? null : Number(value) * scale;
}
async function calculate() {
  busy.value = true;
  error.value = "";
  try {
    const r = await post<Spec>("/ldo/calculate", { spec: form.value });
    for (const b of r.bom)
      if (b.ref !== "U1")
        r.spec.component_management.items[b.ref] ||= {
          manufacturer: "",
          model: "",
          package: "",
          capacitor_type: "unknown",
          voltage_V: null,
          power_W: null,
        };
    form.value = r.spec;
    await nextTick();
    result.value = r;
    dirty.value = false;
    publish();
    notice.value = "已计算四角点；额定值或热条件缺失的项目仍待核对。";
  } catch (e: any) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}
async function report(format: string) {
  if (dirty.value) return;
  busy.value = true;
  error.value = "";
  try {
    download(
      await postBlob("/ldo/export/" + format, { spec: form.value }),
      props.unitName + "-LDO." + format,
    );
  } catch (e: any) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}
function item(ref: string) {
  const items = form.value.component_management.items;
  return (
    items[ref] ||
    (items[ref] = {
      manufacturer: "",
      model: "",
      package: "",
      capacitor_type: "unknown",
      voltage_V: null,
      power_W: null,
    })
  );
}
onMounted(async () => {
  try {
    const d = await request<Spec>("/ldo/defaults");
    fields.value = d.fields;
    form.value = {
      ...d.spec,
      ...form.value,
      component_management: {
        ...d.spec.component_management,
        ...form.value.component_management,
      },
    };
    form.value.component_management.items ||= {};
    await calculate();
  } catch (e: any) {
    error.value = e.message;
  }
});
defineExpose({ getSpec: () => copy(form.value) });
</script>

<template>
  <section class="ldo-workspace">
    <header class="ldo-heading">
      <div>
        <small>LINEAR REGULATOR / STATIC DESIGN</small>
        <h1>{{ unitName }} · LDO 线性稳压器</h1>
        <p>压差、功耗、温升、外围要求与器件初查；使用独立线性模型。</p>
      </div>
      <button class="button primary" :disabled="busy" @click="calculate">
        计算 LDO
      </button>
    </header>
    <p v-if="error" role="alert" class="system-error">{{ error }}</p>
    <p role="status" class="system-note">
      {{ dirty ? "输入已修改，请重新计算；旧结果不用于导出。" : notice }}
    </p>
    <div class="ldo-grid">
      <aside class="card ldo-form">
        <h2>需求与芯片</h2>
        <label v-for="key in ['manufacturer', 'model', 'package']" :key="key"
          >{{
            ({ manufacturer: "厂家", model: "型号", package: "封装" } as Spec)[
              key
            ]
          }}<input v-model="form[key]"
        /></label>
        <label
          >输出类型<select v-model="form.output_mode" aria-label="输出类型">
            <option value="fixed">固定输出</option>
            <option value="adjustable">可调输出（计算分压电阻）</option>
          </select></label
        >
        <label class="ldo-check"
          ><input
            v-model="form.follow_input"
            type="checkbox"
          />进入单元及生成系统报告时跟随上游输入范围</label
        >
        <template v-for="[title, rows] in fields" :key="title"
          ><section
            v-if="title !== '可调输出分压' || form.output_mode === 'adjustable'"
          >
            <h3>{{ title }}</h3>
            <label v-for="[key, label, unit, scale] in rows" :key="key"
              >{{ label }} / {{ unit
              }}<input
                type="number"
                :aria-label="label"
                :value="form[key] === null ? '' : form[key] / scale"
                @input="number(key, scale, $event)"
            /></label></section
        ></template>
        <label class="ldo-check"
          ><input
            v-model="form.thermal_verified"
            type="checkbox"
          />有效热阻已按实际 PCB / 散热条件核对</label
        >
        <label
          >反向电流保护<select v-model="form.reverse_blocking">
            <option value="unknown">未知，需核对</option>
            <option value="yes">具备（按芯片条件）</option>
            <option value="no">不具备</option>
          </select></label
        >
        <label class="ldo-check"
          ><input v-model="form.enable_pin" type="checkbox" />芯片具有 EN
          引脚</label
        ><label class="ldo-check"
          ><input v-model="form.power_good" type="checkbox" />芯片具有 PG
          引脚</label
        >
        <label>资料来源与条件<textarea v-model="form.notes" rows="3" /></label>
        <p class="card-note">
          未知额定值和规格书限制留空。压差、Iq、有效容量须覆盖实际负载、温度及偏压条件。
        </p>
      </aside>
      <main v-if="result" class="ldo-results">
        <section class="card">
          <h2>参考连接与位号</h2>
          <svg viewBox="0 0 800 230" role="img" aria-label="LDO 参考电路">
            <g fill="none" stroke="#173b64" stroke-width="2">
              <path
                d="M45 75H310M490 75H750M45 185H750M400 125V185M160 75V120M142 120H178M142 132H178M160 132V185M630 75V120M612 120H648M612 132H648M630 132V185"
              />
              <rect
                x="310"
                y="30"
                width="180"
                height="95"
                rx="10"
                fill="#e9f4ff"
              />
            </g>
            <g
              font-family="Microsoft YaHei,Arial"
              font-size="18"
              fill="#173b64"
            >
              <text x="350" y="70">U1 · LDO</text>
              <text x="345" y="100">{{ form.model || "型号待填" }}</text>
              <text x="40" y="50">VIN</text>
              <text x="680" y="50">OUT</text>
              <text x="110" y="215">C_IN1</text>
              <text x="590" y="215">C_OUT1</text>
              <text x="375" y="215">GND</text>
            </g>
          </svg>
          <p class="card-note">
            参考连接不指定实际封装引脚。{{
              form.output_mode === "adjustable"
                ? "R1/R2 分压数值见下表；FB 接法按规格书。"
                : ""
            }}
          </p>
        </section>
        <section class="card">
          <h2>输入端点 × 轻载 / 满载</h2>
          <div class="table-wrap">
            <table class="data-table">
              <thead>
                <tr>
                  <th>工况</th>
                  <th>输入 / V</th>
                  <th>负载 / mA</th>
                  <th>压差裕量 / V</th>
                  <th>芯片损耗 / W</th>
                  <th>效率</th>
                  <th>结温 / °C</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="c in result.corners" :key="c.id">
                  <td>{{ c.id }}</td>
                  <td>{{ fmt(c.V_in) }}</td>
                  <td>{{ fmt(c.I_out * 1000) }}</td>
                  <td>{{ fmt(c.dropout_margin) }}</td>
                  <td>{{ fmt(c.P_chip) }}</td>
                  <td>
                    {{ c.eta === null ? "不承诺稳压" : fmt(c.eta * 100, "%") }}
                  </td>
                  <td>{{ fmt(c.T_j) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p class="card-note">
            压差不足时保留失败工况，输出、电损耗与温升不套用稳压公式。损耗包含分压电流和最大接地
            Iq。
          </p>
        </section>
        <section v-if="form.output_mode === 'adjustable'" class="card">
          <h2>输出分压</h2>
          <p>
            R1 = {{ fmt(result.divider.R_top, "Ω") }}；R2 =
            {{ fmt(result.divider.R_bottom, "Ω") }}；分压电流
            {{ fmt(result.divider.I_divider * 1e6, "µA") }}。
          </p>
          <p class="card-note">
            此处忽略 FB 偏置电流；分压电阻耗散按额定功率的 20% 初查。
          </p>
        </section>
        <section class="card">
          <h2>关键器件资料与降额</h2>
          <label
            >规范分区<select v-model="form.component_management.zone">
              <option value="I">I 区</option>
              <option value="II">II 区</option>
            </select></label
          >
          <div class="table-wrap">
            <table class="data-table ldo-bom">
              <thead>
                <tr>
                  <th>位号 / 用途</th>
                  <th>厂家 / 型号 / 封装</th>
                  <th>额定值与类型</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="r in result.bom" :key="r.ref">
                  <td>{{ r.ref }}<br />{{ r.role }}</td>
                  <td v-if="r.ref === 'U1'">芯片资料在左侧统一填写</td>
                  <td v-else>
                    <input
                      v-for="key in ['manufacturer', 'model', 'package']"
                      :key="key"
                      v-model="item(r.ref)[key]"
                      :aria-label="r.ref + ' ' + key"
                      :placeholder="key"
                    />
                  </td>
                  <td v-if="r.kind === 'capacitor'">
                    <label
                      >耐压 / V<input
                        v-model.number="item(r.ref).voltage_V"
                        type="number" /></label
                    ><select v-model="item(r.ref).capacitor_type">
                      <option value="unknown">类型待选</option>
                      <option value="mlcc">MLCC</option>
                      <option value="electrolytic">铝电解</option>
                      <option value="film">薄膜</option>
                      <option value="other">其他</option>
                    </select>
                  </td>
                  <td v-else-if="r.kind === 'resistor'">
                    <label
                      >额定功率 / W<input
                        v-model.number="item(r.ref).power_W"
                        type="number"
                    /></label>
                  </td>
                  <td v-else>
                    按推荐输入范围、电流及结温检查；不套用 MOS 降额因数。
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
        <section class="card">
          <h2>检查结果</h2>
          <div class="table-wrap">
            <table class="data-table">
              <thead>
                <tr>
                  <th>检查项</th>
                  <th>值 / 限值</th>
                  <th>状态与说明</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="c in result.checks" :key="c.id">
                  <td>{{ c.name }}</td>
                  <td>
                    {{ fmt(c.value) }} {{ c.comparison }} {{ fmt(c.limit) }}
                    {{ c.unit }}
                  </td>
                  <td
                    :class="c.state === 'pass' ? 'system-pass' : 'system-warn'"
                  >
                    {{ stateNames[c.state] }}<br />{{ c.note }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
        <section class="card">
          <h2>报告与计算边界</h2>
          <p v-for="n in result.notes" :key="n" class="card-note">{{ n }}</p>
          <div class="system-actions">
            <button
              v-for="f in ['docx', 'xlsx', 'json']"
              :key="f"
              class="button"
              :disabled="busy || dirty"
              @click="report(f)"
            >
              导出 {{ f.toUpperCase() }}
            </button>
          </div>
        </section>
      </main>
    </div>
  </section>
</template>

<style scoped>
.ldo-workspace {
  max-width: 1640px;
  margin: 24px auto;
  padding: 0 24px 40px;
  color: #17334d;
}
.ldo-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
}
.ldo-heading small {
  letter-spacing: 2px;
  color: #168b9c;
}
.ldo-heading h1 {
  font-size: 27px;
  margin: 8px 0;
}
.ldo-heading p {
  color: #71849a;
}
.ldo-grid {
  display: grid;
  grid-template-columns: 350px minmax(0, 1fr);
  gap: 22px;
  align-items: start;
}
.ldo-form {
  max-height: 80vh;
  overflow: auto;
  position: sticky;
  top: 18px;
}
.ldo-workspace label {
  display: grid;
  gap: 6px;
  margin-bottom: 15px;
  font-size: 14px;
}
.ldo-workspace input,
.ldo-workspace select,
.ldo-workspace textarea {
  padding: 9px;
  border: 1px solid #cbd9e7;
  border-radius: 7px;
  max-width: 100%;
  min-width: 0;
  background: white;
  font: inherit;
}
.ldo-workspace .ldo-check {
  display: flex;
  align-items: center;
  gap: 8px;
  line-height: 1.6;
}
.ldo-form h3 {
  padding-top: 14px;
  border-top: 1px solid #e3eaf1;
}
.ldo-results {
  display: grid;
  gap: 20px;
  min-width: 0;
}
.ldo-workspace h2 {
  font-size: 20px;
}
.ldo-results svg {
  max-height: 230px;
  width: 100%;
}
.ldo-bom input {
  display: block;
  width: 100%;
  margin: 4px 0;
}
.ldo-workspace .card {
  padding: 22px;
}
.ldo-workspace .table-wrap {
  overflow-x: auto;
}
@media (max-width: 1000px) {
  .ldo-grid {
    grid-template-columns: 1fr;
  }
  .ldo-form {
    position: static;
    max-height: none;
  }
  .ldo-workspace {
    padding: 0 12px;
  }
}
</style>
