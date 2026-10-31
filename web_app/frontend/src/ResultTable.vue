<script setup lang="ts">
import { computed } from "vue";
import type { Spec } from "./types";
import { fmt } from "./types";
const props = defineProps<{
  data?: Spec | null;
  keys?: string[];
  title?: string;
}>();
const labels: Record<string, [string, string?, number?]> = {
  V_max: ["耐压应力", "V"],
  V_block: ["稳态阻断电压", "V"],
  V_peak_physical: ["模拟包络峰值", "V"],
  V_recommended: ["独立选型参考", "V"],
  I_rms: ["电流有效值", "A"],
  I_pk: ["峰值电流", "A"],
  I_avg: ["平均电流", "A"],
  note: ["模型说明"],
  includes_parasitic_spikes: ["是否包含寄生尖峰"],
  P_cond: ["导通损耗", "W"],
  P_sw_on: ["开通损耗", "W"],
  P_sw_off: ["关断损耗", "W"],
  P_coss: ["Coss 损耗", "W"],
  P_gate: ["栅极驱动损耗", "W"],
  P_rr: ["反向恢复损耗", "W"],
  P_total: ["总损耗", "W"],
  P_semi: ["功率半导体损耗", "W"],
  P_mag: ["磁件总损耗", "W"],
  P_cap: ["电容总损耗", "W"],
  P_cap_in: ["输入电容损耗", "W"],
  P_cap_out: ["输出电容损耗", "W"],
  P_sense: ["电流采样损耗", "W"],
  P_rcd: ["RCD 吸收损耗", "W"],
  P_clamp: ["钳位损耗", "W"],
  P_din: ["输入防反二极管损耗", "W"],
  P_dout: ["输出防反二极管损耗", "W"],
  P_in: ["输入功率", "W"],
  P_in_est: ["预设效率下输入功率", "W"],
  P_loss_budget: ["预设效率对应损耗预算", "W"],
  P_in_delta: ["输入功率估算差", "W"],
  eta: ["计算效率", "%", 100],
  eta_delta: ["计算与预设效率差", "百分点", 100],
  P_sr_cond: ["同步整流导通损耗", "W"],
  P_body: ["体二极管 / 死区损耗", "W"],
  K: ["旧版等效耦合 K"],
  Kc: ["钳位电压比 Kc"],
  L_leak: ["漏感", "µH", 1e6],
  Lm: ["励磁电感", "µH", 1e6],
  V_reflect: ["反射电压", "V"],
  V_clamp: ["钳位电压", "V"],
  V_plateau: ["Vds 反射平台", "V"],
  V_peak: ["模型波形峰值", "V"],
  V_ceiling: ["Kc 应力上限", "V"],
  R_snub: ["吸收电阻", "kΩ", 1e-3],
  C_snub: ["吸收电容", "nF", 1e9],
  P_res: ["吸收电阻功耗", "W"],
  dV_clamp: ["钳位电容纹波", "V"],
  model: ["所用模型"],
  notes: ["注意事项"],
  D: ["主开关占空比"],
  Dp: ["副边导通占空比"],
  f_sw: ["实际开关频率", "kHz", 1e-3],
  f_sw_max: ["频率上限", "kHz", 1e-3],
  Ts: ["开关周期", "µs", 1e6],
  mode: ["工作模式"],
  V_in: ["输入电压", "V"],
  V_out: ["输出电压", "V"],
  P_out: ["输出功率", "W"],
  I_out: ["输出电流", "A"],
  I_in_est: ["输入电流估算", "A"],
  V_r: ["反射电压", "V"],
  V_sw_max: ["MOS 电压应力", "V"],
  V_d_max: ["整流反压（不含尖峰）", "V"],
  eta_guess: ["预设效率", "%", 100],
  V_reset: ["复位电压", "V"],
  V_clamp_hump: ["钳位电压隆起", "V"],
  C_clamp_min: ["钳位最小电容（5%预算）", "nF", 1e9],
  I_mag_pk: ["励磁峰值电流", "A"],
  I_clamp_rms: ["钳位 RMS 电流", "A"],
  f_clamp: ["励磁-钳位谐振频率", "kHz", 1e-3],
  f_clamp_effective: ["折算谐振频率", "kHz", 1e-3],
  fc_recommended_max: ["原模型建议 fc 上限", "Hz"],
  core_label: ["磁芯型号"],
  Ae: ["有效截面积 Ae", "mm²", 1e6],
  Ve: ["有效体积 Ve", "mm³", 1e9],
  Wa: ["窗口面积 Wa", "mm²", 1e6],
  MLT: ["每匝平均长度", "mm", 1e3],
  MLT_source: ["MLT 来源"],
  Np: ["原边匝数", "匝"],
  Ns: ["副边匝数", "匝"],
  N: ["匝数 / 匝比"],
  gap: ["气隙", "µm", 1e6],
  B_pk: ["峰值磁密", "mT", 1e3],
  dB: ["磁通摆幅", "mT", 1e3],
  fill: ["窗口填充比例", "%", 100],
  P_core: ["磁芯损耗", "W"],
  P_cu: ["铜损", "W"],
  dT: ["估算温升", "K"],
  Rth_transformer: ["变压器至环境热阻", "K/W"],
  R_dc: ["几何 DCR", "mΩ", 1e3],
  R_dc_p: ["原边几何 DCR", "mΩ", 1e3],
  R_dc_s: ["副边几何 DCR", "mΩ", 1e3],
  J_actual: ["电流密度", "A/mm²", 1e-6],
  J_actual_p: ["原边电流密度", "A/mm²", 1e-6],
  J_actual_s: ["副边电流密度", "A/mm²", 1e-6],
  Fr: ["Rac / Rdc"],
  Fr_p: ["原边 Rac / Rdc"],
  Fr_s: ["副边 Rac / Rdc"],
  d_wire: ["单股线径", "mm", 1e3],
  d_wire_p: ["原边单股线径", "mm", 1e3],
  d_wire_s: ["副边单股线径", "mm", 1e3],
  n_strand_p: ["原边并绕总股数", "股"],
  n_strand_s: ["副边并绕总股数", "股"],
  id: ["输出编号"],
  output_id: ["所属输出编号"],
  name: ["名称"],
  ok: ["磁件计算有效"],
  kind: ["磁件类别"],
  I_rms_p: ["原边 RMS 电流", "A"],
  I_rms_s: ["副边 RMS 电流", "A"],
  controller: ["控制器"],
  region: ["调制区间"],
  Na: ["辅助绕组匝数", "匝"],
  Vaux: ["辅助绕组电压", "V"],
  RfbH: ["辅助上分压", "kΩ", 1e-3],
  RfbL: ["辅助下分压", "kΩ", 1e-3],
  Vfb: ["反馈电压", "V"],
  Vout_set: ["反馈设定输出电压", "V"],
  Vout_error: ["输出设定偏差", "V"],
  Ifb_negative: ["FB 负向电流", "mA", 1e3],
  RfbH_min: ["FB 最小上分压", "kΩ", 1e-3],
  Rreg: ["线路补偿电阻", "kΩ", 1e-3],
  Ireg: ["补偿电流", "µA", 1e6],
  Rs_recommended: ["推荐采样电阻", "mΩ", 1e3],
  Ipk_limit_typ: ["典型峰值限流", "A"],
  Ipk_limit_min: ["最小峰值限流", "A"],
  Vcs_peak: ["CS 峰值电压", "mV", 1e3],
  tcon: ["退磁导通时间", "ns", 1e9],
  sample_blank: ["采样消隐时间", "ns", 1e9],
  sample_window: ["有效采样窗口", "ns", 1e9],
  Lpri_min: ["最小原边电感参考", "µH", 1e6],
  minimum_load: ["最小负载参考", "W"],
  Rcomp: ["COMP 电阻", "kΩ", 1e-3],
  Ccomp: ["COMP 电容", "nF", 1e9],
  Cpole: ["COMP 高频电容", "pF", 1e12],
  fz: ["COMP 零点", "Hz"],
  fp: ["COMP 极点", "Hz"],
  KP: ["补偿器 KP"],
  P_controller: ["控制器及分压损耗", "W"],
  P_feedback: ["反馈分压损耗", "W"],
  Vcc: ["控制器 Vcc", "V"],
  Vgp_on: ["开通米勒平台", "V"],
  Vgp_off: ["关断米勒平台", "V"],
  I_on: ["开通换流电流", "A"],
  I_off: ["关断换流电流", "A"],
  Qgs_on: ["开通 0V 至平台电荷", "nC", 1e9],
  Qgs_off: ["关断 0V 至平台电荷", "nC", 1e9],
  Qgd_on: ["开通平台电荷", "nC", 1e9],
  Qgd_off: ["关断平台电荷", "nC", 1e9],
  Qg_th: ["门限栅极电荷", "nC", 1e9],
  Qg_on: ["开通总栅电荷", "nC", 1e9],
  Qg_off: ["关断总栅电荷", "nC", 1e9],
  charge_mode: ["电荷计算来源"],
  label: ["计算来源"],
  C: ["电容容量", "µF", 1e6],
  ESR: ["ESR", "mΩ", 1e3],
  ESL: ["ESL", "nH", 1e9],
  total: ["交流纹波 RMS", "A"],
  total_bank: ["电容组 RMS", "A"],
  spectrum_method: ["频谱方法"],
  reason: ["原因"],
  source: ["来源"],
  revision: ["资料版本"],
};
const rows = computed(() =>
  (props.keys || Object.keys(props.data || {}))
    .filter((key) => props.data && key in props.data)
    .flatMap((key) => {
      const value = props.data![key];
      if (
        value !== null &&
        typeof value === "object" &&
        !(Array.isArray(value) && value.every((x) => typeof x !== "object"))
      )
        return [];
      const info = labels[key] || [key];
      return [
        {
          key,
          label: info[0],
          value,
          unit: info[1] || "",
          scale: info[2] || 1,
        },
      ];
    }),
);
function format(value: any, unit: string, scale: number) {
  if (value === null || value === undefined) return "—";
  if (Array.isArray(value)) return value.join("；");
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "string") return value;
  return fmt(Number(value) * scale, unit, 5);
}
</script>
<template>
  <section class="card result-table">
    <div v-if="title" class="card-heading">
      <h3>{{ title }}</h3>
    </div>
    <div class="table-wrap">
      <table class="data-table">
        <thead>
          <tr>
            <th>参数 / 检查项目</th>
            <th>当前工况</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.key">
            <td>
              {{ row.label
              }}<small v-if="row.label !== row.key">{{ row.key }}</small>
            </td>
            <td>{{ format(row.value, row.unit, row.scale) }}</td>
          </tr>
          <tr v-if="!rows.length">
            <td colspan="2">当前工况不适用或尚未计算。</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
<style scoped>
.result-table small {
  display: block;
  color: #75869b;
  font-size: 12px;
  font-family: Consolas, monospace;
  margin-top: 3px;
}
.result-table td:nth-child(2) {
  font-variant-numeric: tabular-nums;
  word-break: break-word;
}
.result-table {
  margin-bottom: 20px;
}
</style>
