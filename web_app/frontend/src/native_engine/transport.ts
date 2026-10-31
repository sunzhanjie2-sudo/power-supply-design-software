import NativeWorker from "./worker?worker&inline";
import { type Spec, reference, normalize, clone } from "./spec";
import { preview } from "./preview";
const VERSION = "0.2.0-native-ts";
import { inspect, applyCurve } from "./curves";
import { bundle, jsonFile } from "./archive";
import type { Picture } from "./reports";
import { normalizeNetwork } from "./network";
type Pending = {
  resolve: (v: any) => void;
  reject: (e: Error) => void;
  progress?: (s: string) => void;
};
let worker: Worker | null = null,
  counter = 0;
let pictureCache: { job: string; items: Picture[] } | null = null;
const pending = new Map<number, Pending>(),
  jobs = new Map<string, Spec>(),
  files = new Map<string, Blob>();
function rpc(method: string, args: Spec = {}, progress?: (s: string) => void) {
  if (!worker) {
    worker = new NativeWorker();
    worker.onmessage = (e) => {
      const value = e.data,
        call = pending.get(value.id);
      if (!call) return;
      if (value.progress) {
        call.progress?.(value.progress);
        return;
      }
      pending.delete(value.id);
      value.error
        ? call.reject(new Error(value.error))
        : call.resolve(value.result);
    };
    worker.onerror = (e) => {
      for (const p of pending.values())
        p.reject(new Error("浏览器计算线程异常：" + e.message));
      pending.clear();
      worker?.terminate();
      worker = null;
    };
  }
  const id = ++counter;
  return new Promise<any>((resolve, reject) => {
    pending.set(id, { resolve, reject, progress });
    worker!.postMessage({ id, method, args });
  });
}
function cancelAll() {
  pictureCache = null;
  worker?.terminate();
  worker = null;
  for (const p of pending.values()) p.reject(new Error("计算已取消"));
  pending.clear();
  for (const j of jobs.values())
    if (["running", "queued"].includes(j.state)) j.state = "cancelled";
}
function job(message: string) {
  if (jobs.size > 8) {
    const first = jobs.keys().next().value;
    if (first) {
      jobs.delete(first);
      files.delete(first);
    }
  }
  const row = {
    id: "native-" + Date.now().toString(36) + "-" + ++counter,
    state: "running",
    progress: 0,
    message,
  };
  jobs.set(row.id, row);
  return row as Spec;
}
function start(message: string, fn: (row: Spec) => Promise<any>) {
  const row = job(message);
  void fn(row)
    .then((result) => {
      if (row.state !== "cancelled") {
        row.state = "succeeded";
        row.progress = 100;
        row.message = "已完成 · 浏览器本机计算";
        row.result = result;
      }
    })
    .catch((e) => {
      if (row.state !== "cancelled") {
        row.state = "failed";
        row.error = { message: e.message };
      }
    });
  return clone(row);
}
function find(id: string) {
  const row = jobs.get(id);
  if (!row) throw Error("计算任务已释放，请重新计算");
  return row;
}
async function png(svg: string) {
  const url = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
  let deadline: ReturnType<typeof setTimeout> | undefined;
  try {
    const image = new Image();
    image.src = url;
    await Promise.race([
      image.decode(),
      new Promise<never>((_, reject) => {
        deadline = setTimeout(
          () => reject(new Error("报告图像渲染超时，请重试或重新计算该单元")),
          15000,
        );
      }),
    ]);
    const canvas = document.createElement("canvas");
    canvas.width = image.naturalWidth;
    canvas.height = image.naturalHeight;
    const ctx = canvas.getContext("2d")!;
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(image, 0, 0);
    const blob = await new Promise<Blob>((resolve, reject) =>
      canvas.toBlob(
        (b) => (b ? resolve(b) : reject(new Error("图表转换失败"))),
        "image/png",
      ),
    );
    return {
      data: new Uint8Array(await blob.arrayBuffer()),
      width: canvas.width,
      height: canvas.height,
    };
  } finally {
    if (deadline) clearTimeout(deadline);
    URL.revokeObjectURL(url);
  }
}
async function exportFile(jobId: string, format: string, row: Spec) {
  const active = () => {
    if (row.state === "cancelled") throw Error("计算已取消");
  };
  active();
  if (format === "comparison")
    throw Error(
      "纯 HTML 无法直接运行本机 LTspice。该仿真导出模块仍由原计算器提供。",
    );
  let pictures: Picture[] = [];
  if (format !== "json" && format !== "zip" && pictureCache?.job === jobId)
    pictures = pictureCache.items;
  else if (format !== "json" && format !== "zip") {
    const svgs = await rpc(
      "pictures",
      { job: jobId },
      (message) => (row.message = message),
    );
    for (const [i, p] of svgs.entries()) {
      active();
      if (!p.svg) continue;
      row.message = "准备报告图表 " + (i + 1) + "/" + svgs.length;
      pictures.push({ ...p, ...(await png(p.svg)) });
    }
    pictureCache = { job: jobId, items: pictures };
  }
  row.message = "浏览器后台生成 " + format.toUpperCase();
  active();
  const data = await rpc("export", { job: jobId, format, pictures });
  return new Blob([data], {
    type:
      format === "zip"
        ? "application/zip"
        : format === "json"
          ? "application/json"
          : format === "xlsx"
            ? "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            : "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  });
}
export async function localRequest(
  url: string,
  options: RequestInit = {},
): Promise<any> {
  const path = url.split("?")[0],
    body = typeof options.body === "string" ? JSON.parse(options.body) : {};
  if (path === "/bootstrap")
    return {
      ...clone(reference.bootstrap),
      token: "browser-native",
      version: VERSION,
      native: true,
    };
  if (path === "/config") return normalize(body.spec);
  if (path === "/preview") return preview(body.spec);
  if (path.startsWith("/examples/")) {
    const name = decodeURIComponent(path.slice(10)),
      example = reference.examples[name];
    if (!example) throw Error("示例不存在");
    return clone(example);
  }
  if (path === "/curves/inspect") return inspect(body);
  if (path === "/curves/apply") return applyCurve(body);
  if (path === "/jobs" && options.method === "POST") {
    pictureCache = null;
    files.clear();
    return start("等待浏览器后台线程", async (row) =>
      rpc(
        "calculate",
        { spec: body.spec, job: row.id, cross: body.cross_regulation },
        (message) => (row.message = message),
      ),
    );
  }
  let match = path.match(
    /^\/(jobs|operations)\/([^/]+)(?:\/(result|cancel|export|action))?$/,
  );
  if (match) {
    const [, type, id, action] = match,
      row = find(id);
    if (action === "cancel") {
      cancelAll();
      return { ...row, state: "cancelled" };
    }
    if (action === "result") {
      if (row.state !== "succeeded") throw Error("计算尚未完成");
      return row.result;
    }
    if (action === "export")
      return start("准备离线报告", async (operation) => {
        files.set(operation.id, await exportFile(id, body.format, operation));
        return { format: body.format };
      });
    if (action === "action")
      return start("浏览器执行 " + body.action, async (operation) => {
        const result = await rpc(
          "action",
          {
            job: id,
            action: body.action,
            options: body.options,
            caseId: body.options?.case || "Vinmin",
          },
          (message) => (operation.message = message),
        );
        if (result.chart_svg) {
          files.set(
            operation.id,
            new Blob([result.chart_svg], { type: "image/svg+xml" }),
          );
          delete result.chart_svg;
        }
        return result;
      });
    return clone(row);
  }
  if (path === "/pcs/reports") {
    const project = normalizeNetwork(body.project);
    return start("逐单元生成辅源报告包", async (row) => {
      const packed: Record<string, Uint8Array> = {
          "辅源工程.json": jsonFile(project),
        },
        manifest: Spec = {
          engine: VERSION,
          units: [],
          source: "browser-native",
        };
      let success = 0;
      for (const unit of project.units) {
        pictureCache = null;
        if (row.state === "cancelled") throw Error("计算已取消");
        row.message = "计算 " + unit.id + " · " + unit.name;
        const identity = "report-" + unit.id;
        try {
          await rpc(
            "calculate",
            {
              job: identity,
              spec: {
                ...unit.spec,
                __web_project_title: unit.id + " · " + unit.name,
              },
              cross: !!project.includeCrossRegulation,
            },
            (message) => (row.message = message),
          );
          packed[unit.id + "/设计输入.json"] = jsonFile(unit.spec);
          if (row.state === "cancelled") throw Error("计算已取消");
          for (const format of ["xlsx", "docx"])
            packed[unit.id + "/设计报告." + format] = new Uint8Array(
              await (await exportFile(identity, format, row)).arrayBuffer(),
            );
          manifest.units.push({
            id: unit.id,
            name: unit.name,
            state: "completed",
          });
          success++;
        } catch (e) {
          if (row.state === "cancelled") throw e;
          manifest.units.push({
            id: unit.id,
            name: unit.name,
            state: "failed",
            error: String(e),
          });
        }
      }
      if (row.state === "cancelled") throw Error("计算已取消");
      row.message = "生成 OR 汇流与竞争供电预算";
      const network = await rpc("network-budget", { project, manifest });
      packed["供电网络预算.xlsx"] = network.data;
      packed["供电网络计算.json"] = jsonFile(network.review);
      manifest.schema_version = "power.system-delivery/2";
      manifest.budget = network.review.capacity;
      manifest.interfaces = network.review.interfaces;
      manifest.coverage_complete = network.review.coverage_complete;
      manifest.method = network.review.method;
      if (row.state === "cancelled") throw Error("计算已取消");
      if (body.architecture_svg)
        packed["辅源供电架构.svg"] = new TextEncoder().encode(
          body.architecture_svg,
        );
      const picture = body.architecture_svg
        ? await png(body.architecture_svg)
        : undefined;
      packed["辅源架构与交付总览.docx"] = await rpc("overview", {
        project,
        manifest,
        picture,
      });
      packed["交付清单.json"] = jsonFile(manifest);
      packed["阅读说明.txt"] = new TextEncoder().encode(
        "PCS 辅源离线报告包\n" +
          project.title +
          "\n完整完成 " +
          success +
          "/" +
          project.units.length +
          " 个单元。\n输入输出关系保存在辅源工程.json；请先核对交付清单，失败单元没有伪造报告。",
      );
      files.set(
        row.id,
        new Blob([bundle(packed)], { type: "application/zip" }),
      );
      return { successful: success, total: project.units.length, manifest };
    });
  }
  throw Error("纯前端尚未提供该接口：" + path);
}
export async function localBlob(
  url: string,
  signal?: AbortSignal,
): Promise<Blob> {
  if (signal?.aborted) throw new DOMException("取消", "AbortError");
  const parsed = new URL(url, "https://local.invalid"),
    path = parsed.pathname;
  let match = path.match(/^\/jobs\/([^/]+)\/chart\/([^/]+)$/);
  if (match) {
    const svg = await rpc("chart", {
      job: match[1],
      kind: match[2],
      caseId: parsed.searchParams.get("case") || "Vinmin",
      output: Number(parsed.searchParams.get("output") || 1),
    });
    return new Blob([svg], { type: "image/svg+xml" });
  }
  const id = path.match(/^\/(?:files|pcs\/reports)\/([^/]+)$/)?.[1];
  if (id) {
    const file = files.get(id);
    if (!file) throw Error("文件已释放，请重新导出");
    return file;
  }
  if (path === "/manual" || path === "/tutorial")
    throw Error(
      "请从软件 docs 文件夹打开原计算说明与教程；纯 HTML 未将文档塞入计算资源。",
    );
  throw Error("纯前端未提供该文件：" + path);
}
export const nativeStatus = () => ({
  engine: VERSION,
  worker: !!worker,
  networkRequired: false,
  python: false,
});
