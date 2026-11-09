<script setup lang="ts">
import { computed } from "vue";
import type { Spec, Parameter, Preview, Bootstrap } from "./types";
import FieldInput from "./FieldInput.vue";
import Icon from "./Icon.vue";
import CoreEditor from "./CoreEditor.vue";
import CapacitorBank from "./CapacitorBank.vue";
import { fmt } from "./types";
const props = defineProps<{
  spec: Spec;
  meta: Bootstrap;
  preview: Preview | null;
}>();
const emit = defineEmits<{ change: [spec: Spec] }>();
const rails = computed<Spec[]>(() => props.spec.outputs || []);
const fields = computed(() =>
  Object.fromEntries(props.meta.parameters.map((row) => [row.name, row])),
);
function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value));
}
function update(index: number, key: string, value: any) {
  const next = clone(props.spec);
  next.outputs[index][key] = value;
  emit("change", next);
}
function replaceRail(index: number, value: Spec) {
  const next = clone(props.spec);
  next.outputs[index] = value;
  emit("change", next);
}
function count(value: number) {
  const next = clone(props.spec);
  const old = next.outputs || [];
  next.outputs = Array.from(
    { length: value },
    (_, i) =>
      old[i] || {
        ...clone(props.meta.output_template),
        output_capacitors: clone(props.spec.output_capacitors ?? null),
        name: `OUT${i + 1}`,
        P_out: i === 0 ? props.spec.P_out : 5,
        P_out_min: i === 0 ? props.spec.P_out : 5,
        Ns: props.spec.Ns || 12,
      },
  );
  if (next.feedback_output > value) next.feedback_output = 1;
  if (
    next.coupling_config?.enabled &&
    next.coupling_config.k?.length !== value + 1
  ) {
    next.coupling_config = clone(props.meta.coupling[String(value)]);
    next.coupling_config.enabled = true;
  }
  emit("change", next);
}
function field(key: string): Parameter {
  return (
    fields.value[key] || {
      name: key,
      label: key,
      symbol: key,
      unit: "",
      display_unit: "",
      display_factor: 1,
      type: "number",
      category: "",
      group: "",
      enabled_by: "",
      auto_zero: false,
      deprecated: false,
      topologies: [],
      default: 0,
    }
  );
}
</script>
<template>
  <div class="output-editor">
    <label class="inline-label"
      >启用输出路数<select
        :value="rails.length || 1"
        @change="count(Number(($event.target as HTMLSelectElement).value))"
      >
        <option v-for="n in 6" :value="n">{{ n }} 路</option>
      </select></label
    >
    <p class="hint">
      只设定反馈路电压。其它路按整数匝比估算，耦合模型启用后再联立求解。
    </p>
    <details
      v-for="(rail, index) in rails"
      :key="index"
      class="output-section"
      :open="index === 0"
    >
      <summary>
        <span class="output-dot" />OUT{{ index + 1
        }}<span v-if="spec.feedback_output === index + 1" class="tag feedback"
          >主反馈</span
        ><small
          >{{ fmt(preview?.outputs?.[index]?.V_out, "V") }} ·
          {{ fmt(rail.P_out, "W") }}</small
        ><Icon name="chevron" :size="14" />
      </summary>
      <div class="output-fields">
        <label class="field-row"
          ><span>输出名称</span
          ><input
            class="name-input"
            :value="rail.name"
            @input="
              update(index, 'name', ($event.target as HTMLInputElement).value)
            " /></label
        ><FieldInput
          v-if="spec.feedback_output === index + 1"
          :field="field('V_out')"
          :value="rail.V_out"
          @change="update(index, 'V_out', $event)"
        />
        <div v-else class="read-only-row">
          <span>匝比估算电压</span
          ><strong>{{ fmt(preview?.outputs?.[index]?.V_out, "V") }}</strong>
        </div>
        <FieldInput
          v-for="key in ['P_out', 'P_out_min', 'Ns', 'd_wire_s', 'n_strand_s','parallel_wires_s']"
          :key="key"
          :field="field(key)"
          :value="rail[key]"
          @change="update(index, key, $event)"
        />
        <h5>整流二极管 D_O{{ index + 1 }}</h5>
        <FieldInput
          v-for="key in ['Vf_diode', 'Qrr']"
          :key="key"
          :field="field(key)"
          :value="rail[key]"
          @change="update(index, key, $event)"
        />
        <h5>输出电容组 C_O{{ index + 1 }}</h5>
        <CapacitorBank :spec="rail" :value="rail.output_capacitors" @change="update(index,'output_capacitors',$event)" />
        <FieldInput
          :field="field('d_out_enable')"
          :value="rail.d_out_enable"
          @change="update(index, 'd_out_enable', $event)"
        /><FieldInput
          v-if="rail.d_out_enable"
          :field="field('Vf_dout')"
          :value="rail.Vf_dout"
          @change="update(index, 'Vf_dout', $event)"
        /><FieldInput
          :field="field('ripple_target')"
          :value="rail.ripple_target"
          @change="update(index, 'ripple_target', $event)"
        /><template v-if="spec.topology === 'ACF-FORWARD'"
          ><h5>该路正激输出电感</h5>
          <FieldInput
            :field="field('L')"
            :value="rail.L"
            @change="update(index, 'L', $event)" /><CoreEditor
            :spec="rail"
            :meta="meta"
            inductor
            :material="false"
            @change="replaceRail(index, $event)"
        /></template>
      </div>
    </details>
  </div>
</template>
