<script setup lang="ts">
import type { Spec } from "./types";
import { fmt } from "./types";
import { ref, computed } from "vue";
const props = defineProps<{
  bank?: Spec | null;
  title: string;
  prefix: string;
}>();
const showBands = ref(false),
  selected = ref(0);
const chosen = computed(
  () =>
    props.bank?.caps?.[Math.min(selected.value, props.bank.caps.length - 1)],
);
</script>
<template>
  <section v-if="bank" class="card">
    <div class="card-heading">
      <h3>{{ title }}</h3>
    </div>
    <div class="table-wrap">
      <table class="data-table">
        <thead>
          <tr>
            <th>电容</th>
            <th>容量</th>
            <th>ESR</th>
            <th>ESL</th>
            <th>交流 RMS</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(cap, index) in bank.caps" :key="index">
            <td>{{ prefix }}{{ Number(index) + 1 }}</td>
            <td>{{ fmt(cap.C * 1e6, "µF", 5) }}</td>
            <td>{{ fmt(cap.ESR * 1e3, "mΩ", 5) }}</td>
            <td>{{ fmt(cap.ESL * 1e9, "nH", 5) }}</td>
            <td>{{ fmt(cap.total, "A", 5) }}</td>
          </tr>
          <tr>
            <th colspan="4">电容组总交流 RMS（不等于各颗 RMS 直接相加）</th>
            <td>{{ fmt(bank.total_bank, "A", 5) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <p class="card-note">
      频谱方法：{{
        bank.spectrum_method
      }}。频带分量见对应图表；这里读取同一份已算结果，不重复求解。
    </p>
    <details @toggle="showBands = ($event.target as HTMLDetailsElement).open">
      <summary>查看逐颗电容完整频带 RMS（含 1–20 次开关谐波）</summary>
      <template v-if="showBands">
        <label
          >选择电容
          <select v-model.number="selected" aria-label="频带查看电容">
            <option v-for="(_, index) in bank.caps" :key="index" :value="index">
              {{ prefix }}{{ Number(index) + 1 }}
            </option>
          </select></label
        >
        <div class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>频带</th>
                <th>本颗频带 RMS / A</th>
                <th>占本颗 RMS²</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(value, index) in chosen?.bands || []" :key="index">
                <td>{{ bank.labels?.[index] }}</td>
                <td>{{ fmt(value, "A", 6) }}</td>
                <td>
                  {{
                    chosen.total > 0
                      ? fmt(
                          (100 * value * value) / (chosen.total * chosen.total),
                          "%",
                          5,
                        )
                      : "—"
                  }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="card-note">
          频带 RMS 按平方相加后开方得到本颗总
          RMS。此表直接读取已算频谱，不重新计算。
        </p>
      </template>
    </details>
  </section>
</template>
