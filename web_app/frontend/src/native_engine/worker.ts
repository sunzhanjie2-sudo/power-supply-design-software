import { windingRows, assess, windingChart } from "./winding";
/// <reference lib="webworker" />
import { calculate, design, VERSION } from "./engine";
import { chart } from "./charts";
import { advancedAction } from "./actions";
import { excel, word, overview, networkExcel, jsonFile } from "./reports";
import { analyzeNetwork } from "./network";
import { exportSpice } from "./spice_export";
import { type Spec, clone, normalize } from "./spec";
const runs = new Map<string, ReturnType<typeof calculate>>();
const context = (id: string) => {
  const r = runs.get(id);
  if (!r) throw Error("计算快照已释放，请重新计算");
  return r;
};
const clean = (v: any) =>
  JSON.parse(
    JSON.stringify(v, (_, x) =>
      typeof x === "number" && !Number.isFinite(x) ? null : x,
    ),
  );
self.onmessage = async (event: MessageEvent) => {
  const { id, method, args } = event.data;
  const progress = (message: string) =>
    self.postMessage({ id, progress: message });
  try {
    let result: any;
    switch (method) {
      case "network-budget": {
        const review = analyzeNetwork(args.project);
        result = {
          review,
          data: await networkExcel(args.project, args.manifest, review),
        };
        break;
      }
      case "overview":
        result = await overview(args.project, args.manifest, args.picture);
        break;
      case "calculate": {
        runs.clear();
        const r = calculate(args.spec, progress, !!args.cross);
        runs.set(args.job, r);
        result = clean(r.snapshot);
        break;
      }
      case "chart": {
        const r = context(args.job),
          index = args.caseId === "Vinmax" ? 1 : 0;
        result = chart(r.runs[index].p, r.runs[index], args.kind, args.output);
        break;
      }
      case "pictures": {
        const r = context(args.job);
        result = [];
        for (const [i, c] of r.snapshot.cases.entries())
          for (const kind of [
            "topology",
            "power",
            "outputs",
            "input_caps",
            "output_caps",
            "device_losses",
            "switching",
            "losses",
            "magnetics",
            "magnetic_flux",
            "winding",
            "clamp",
            "compensation",
            "parasitics",
            "efficiency",
            "loop",
            "loop_phase",
            "multi_reference",
            "multi_load",
          ]) {
            progress("计算报告图表 " + c.id + " / " + kind);
            const outputs = ["outputs", "output_caps", "multi_load"].includes(
              kind,
            )
              ? r.runs[i].outputs.map((v: Spec) => v.id)
              : [1];
            for (const output of outputs)
              try {
                if (
                  kind === "compensation" &&
                  (!r.runs[i].compensation || r.runs[i].compensation.error)
                )
                  continue;
                if (
                  kind === "parasitics" &&
                  !r.runs[i].parasitics?.edges?.length
                )
                  continue;
                if (
                  kind.startsWith("multi_") &&
                  (!r.runs[i].loop || r.runs[i].outputs.length < 2)
                )
                  continue;
                const svg = chart(r.runs[i].p, r.runs[i], kind, output);
                result.push({
                  caseId: c.id,
                  kind,
                  title:
                    c.id +
                    " · " +
                    (
                      {
                        topology: "拓扑与位号",
                        power: "功率级波形",
                        outputs: "逐路电流与电压",
                        input_caps: "输入电容频带分流",
                        output_caps: "输出电容频带分流",
                        device_losses: "半导体损耗",
                        switching: "MOS t1–t8",
                        losses: "损耗分配",
                        magnetics: "磁件损耗",
                        magnetic_flux: "磁链与磁通参考",
                        winding: "绕制横截面",
                        clamp: "钳位包络",
                        compensation: "补偿参考电路",
                        parasitics: "局部寄生换流",
                        efficiency: "效率与负载",
                        loop: "环路幅相",
                        loop_phase: "环路相位",
                        multi_reference: "多路参考跟踪",
                        multi_load: "多路负载扰动",
                      } as Spec
                    )[kind] +
                    (outputs.length > 1 ? " · OUT" + output : ""),
                  svg,
                });
              } catch (error) {
                result.push({
                  caseId: c.id,
                  kind,
                  title: c.id + " · " + kind,
                  error: String(error),
                });
              }
          }
        break;
      }
      case "export": {
        const r = context(args.job);
        if (args.format === "zip") result = exportSpice(r);
        else if (args.format === "json") result = jsonFile(r.snapshot);
        else if (args.format === "xlsx")
          result = await excel(r.snapshot, args.pictures);
        else if (args.format === "docx")
          result = await word(r.snapshot, args.pictures);
        else
          throw Error(
            "纯 HTML 暂不提供本机 LTspice 运行与对比报告；请使用原计算器完成仿真。",
          );
        break;
      }
      case "action": {
        const r = context(args.job),
          index = args.caseId === "Vinmax" ? 1 : 0,
          run = r.runs[index],
          options = args.options || {};
        if (args.action === "winding_preview") {
          const windings = windingRows(run),
            assessment = assess(windings, options.config);
          result = {
            windings,
            assessment,
            automatic_plan: assessment.automatic_plan || [],
            has_chart: true,
            chart_svg: windingChart(assessment),
          };
        } else
          result = advancedAction(
            run,
            args.action,
            { ...options, case: args.caseId },
            progress,
          );
        break;
      }
      default:
        throw Error("未知浏览器计算操作 " + method);
    }
    self.postMessage({ id, result });
  } catch (error) {
    self.postMessage({
      id,
      error: error instanceof Error ? error.message : String(error),
    });
  }
};
