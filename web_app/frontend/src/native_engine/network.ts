/** Static auxiliary-power network. Ported from power_network.py; no UI or HTTP. */
import { type Spec, clone } from "./spec";
export const NETWORK_SCHEMA = "power.system-network/2";
export const collections: Record<string, string> = {
  bus: "sources",
  unit: "units",
  junction: "junctions",
  load: "loads",
};
export const networkNodes = (p: Spec): [string, Spec][] =>
  Object.entries(collections).flatMap(([k, list]) =>
    (p[list] || []).map((n: Spec) => [k, n] as [string, Spec]),
  );
export const networkRails = (u: Spec): Spec[] =>
  u.rails?.length
    ? u.rails
    : u.spec.outputs?.length
      ? u.spec.outputs
      : [{ V_out: u.spec.V_out, P_out: u.spec.P_out, name: "OUT1" }];
export const networkIncoming = (p: Spec, id: string, enabled = false): Spec[] =>
  p.connections.filter((e: Spec) => e.target === id && (!enabled || e.enabled));
export const networkPort = (s: Spec) =>
  s.id + (s.kind === "unit" ? "/OUT" + s.output : "");
function num(v: any, label: string, min = 0) {
  if (typeof v !== "number" || !Number.isFinite(v) || v < min)
    throw Error(label + "须为不小于" + min + "的有限数值");
  return v;
}
function id(v: any) {
  if (typeof v !== "string" || !/^[-A-Za-z0-9_]{1,40}$/.test(v))
    throw Error("节点/连线编号格式无效");
  return v;
}
function name(v: any) {
  if (typeof v !== "string" || !v.trim() || v.trim().length > 120)
    throw Error("节点名称须为1～120字");
  return v.trim();
}
function enabled(v: any) {
  if (v === undefined) return true;
  if (typeof v !== "boolean") throw Error("启用状态须为布尔值");
  return v;
}
export function topologicalNetwork(p: Spec) {
  const ids = networkNodes(p).map(([, n]) => n.id),
    parents = new Map(ids.map((i) => [i, [] as string[]]));
  for (const e of p.connections) parents.get(e.target)!.push(e.source.id);
  const seen = new Set<string>(),
    stack = new Set<string>(),
    order: string[] = [];
  function visit(i: string) {
    if (stack.has(i)) throw Error("辅源架构包含循环供电");
    if (seen.has(i)) return;
    stack.add(i);
    for (const v of parents.get(i)!) visit(v);
    stack.delete(i);
    seen.add(i);
    order.push(i);
  }
  ids.forEach(visit);
  return order;
}
export function normalizeNetwork(raw: Spec): Spec {
  const p = clone(raw);
  if (p.schema_version === "pcs.aux-workspace/1") {
    p.schema_version = NETWORK_SCHEMA;
    p.loads = [];
    p.junctions = [];
    p.connections = [];
    for (const u of p.units || [])
      if (u.source?.kind && u.source.kind !== "none")
        p.connections.push({
          id: "LINK-" + String(p.connections.length + 1).padStart(3, "0"),
          source: clone(u.source),
          target: u.id,
          mode: "direct",
          vf: 0.3,
          enabled: true,
        });
  }
  if (p.schema_version !== NETWORK_SCHEMA)
    throw Error("需要辅源网络或旧版 PCS 辅源工程 JSON");
  const used = new Set<string>();
  for (const [kind, key] of Object.entries(collections)) {
    p[key] ??= [];
    if (
      !Array.isArray(p[key]) ||
      p[key].length > (["bus", "unit"].includes(kind) ? 24 : 48)
    )
      throw Error("输入源/单元最多24个，OR汇流/负载每类最多48个");
    for (const n of p[key]) {
      n.id = id(n.id);
      if (used.has(n.id)) throw Error("节点编号重复");
      used.add(n.id);
      n.name = name(n.name);
      n.enabled = enabled(n.enabled);
      if (kind === "bus") {
        num(n.min, "输入下限", 1e-9);
        num(n.max, "输入上限", n.min);
        num(n.capacity, "输入容量", 1e-9);
      } else if (kind === "junction")
        n.capacity = num(n.capacity ?? 100, "OR母线容量", 1e-9);
      else if (kind === "load") {
        n.power = num(n.power ?? 1, "负载功耗");
        n.min = num(n.min ?? 0, "负载电压下限");
        n.max = num(n.max ?? 0, "负载电压上限");
        if (n.max && n.max < n.min)
          throw Error("负载上限不得小于下限；0表示不限定");
      } else {
        if (!n.spec || typeof n.spec !== "object")
          throw Error("辅源单元缺少计算配置");
        const s = n.spec;
        s.V_in_min ??= s.V_in;
        s.V_in_max ??= s.V_in;
        num(s.V_in_min, "设计输入下限", 1e-9);
        num(s.V_in_max, "设计输入上限", s.V_in_min);
        num(s.eta_guess, "预设效率", 1e-9);
        if (s.eta_guess > 1) throw Error("预设效率须不大于1");
        const rails = networkRails(n);
        if (!rails.length || rails.length > 6)
          throw Error("每单元支持1～6路输出");
        for (const r of rails) {
          num(r.V_out, "输出电压", 1e-9);
          num(r.P_out, "输出功率");
        }
        n.rails = clone(rails);
        delete n.source;
      }
    }
  }
  const byId = new Map(
    networkNodes(p).map(([k, n]) => [n.id, { kind: k, node: n }]),
  );
  if (!Array.isArray(p.connections) || p.connections.length > 256)
    throw Error("连接列表无效或超过256条");
  const edgeIds = new Set<string>(),
    pairs = new Set<string>();
  p.connections = p.connections.map((e: Spec) => {
    const eid = id(e.id),
      s = e.source || {},
      source = byId.get(s.id),
      target = byId.get(e.target),
      port = s.output ?? 1;
    if (used.has(eid) || edgeIds.has(eid))
      throw Error("连接编号重复或与节点相同");
    edgeIds.add(eid);
    if (
      !source ||
      source.kind !== s.kind ||
      !["bus", "unit", "junction"].includes(s.kind)
    )
      throw Error("上游端口不存在；负载不能作为电源");
    if (!target || target.kind === "bus")
      throw Error("下游须为单元、OR汇流或负载");
    if (
      !Number.isInteger(port) ||
      port < 1 ||
      port > (s.kind === "unit" ? networkRails(source.node).length : 1)
    )
      throw Error("上游输出端口不存在");
    const pair = s.id + "|" + port + "|" + e.target;
    if (pairs.has(pair)) throw Error("该供电连接已存在");
    pairs.add(pair);
    const mode = e.mode ?? (target.kind === "junction" ? "diode" : "direct");
    if (!["direct", "diode"].includes(mode)) throw Error("连接方式无效");
    return {
      id: eid,
      source: { kind: s.kind, id: s.id, output: port },
      target: e.target,
      mode,
      vf: num(e.vf ?? 0.3, "二极管压降"),
      enabled: enabled(e.enabled),
    };
  });
  for (const [kind, n] of networkNodes(p)) {
    const ins = networkIncoming(p, n.id, true);
    if (
      (ins.length > 1 || kind === "junction") &&
      ins.some((e) => e.mode !== "diode")
    )
      throw Error(n.id + " 多源竞争供电须逐支路二极管隔离，不能直接并联");
  }
  topologicalNetwork(p);
  const positions = p.layout?.nodes || {},
    diodes = p.layout?.diodes || {},
    valid = new Set(networkNodes(p).map(([k, n]) => k + ":" + n.id));
  p.layout = { nodes: {}, diodes: {} };
  for (const [key, point] of Object.entries(positions) as [string, Spec][]) {
    if (valid.has(key)) {
      p.layout.nodes[key] = {
        x: num(point.x, "横坐标"),
        y: num(point.y, "纵坐标"),
      };
      if (Math.max(point.x, point.y) > 10000)
        throw Error("布局坐标不得超过10000");
    }
  }
  for (const [key, point] of Object.entries(diodes) as [string, Spec][]) {
    if (p.connections.some((e: Spec) => e.id === key && e.mode === "diode")) {
      p.layout.diodes[key] = {
        x: num(point.x, "二极管横坐标"),
        y: num(point.y, "二极管纵坐标"),
      };
      if (Math.max(point.x, point.y) > 10000)
        throw Error("布局坐标不得超过10000");
    }
  }
  p.activeUnit = p.units.some((n: Spec) => n.id === p.activeUnit)
    ? p.activeUnit
    : p.units[0]?.id || "";
  p.workspace_kind = "power-system";
  p.title = p.title || "PCS 辅源供电网络";
  return p;
}
export function analyzeNetwork(raw: Spec): Spec {
  const p = normalizeNetwork(raw),
    entries = networkNodes(p),
    byId = new Map(entries.map(([kind, node]) => [node.id, { kind, node }])),
    order = topologicalNetwork(p);
  const roots = p.sources
      .filter((b: Spec) => b.enabled)
      .map((b: Spec) => b.id) as string[],
    availability: [string, string[]][] = [["全部输入源", roots]];
  if (roots.length > 1) {
    for (const r of roots)
      availability.push([r + " 掉电", roots.filter((v) => v !== r)]);
    for (const r of roots) availability.push([r + " 单独供电", [r]]);
  }
  const unique = new Map<string, { names: string[]; available: Set<string> }>();
  for (const [label, values] of availability) {
    const key = [...values].sort().join("|");
    if (unique.has(key)) unique.get(key)!.names.push(label);
    else unique.set(key, { names: [label], available: new Set(values) });
  }
  const capacity: Record<string, Spec> = {},
    iface: Record<string, Spec> = {},
    diode: Record<string, number> = {};
  for (const [kind, n] of entries) {
    if (kind === "unit")
      networkRails(n).forEach(
        (r, i) => (capacity[n.id + "/OUT" + (i + 1)] = { capacity: r.P_out }),
      );
    else if (["bus", "junction"].includes(kind))
      capacity[n.id] = { capacity: n.capacity };
    if (kind !== "bus") {
      const s = n.spec || {};
      iface[n.id] = {
        unit: n.id,
        name: n.name,
        kind,
        design_min: kind === "unit" ? s.V_in_min : n.min || 0,
        design_max: kind === "unit" ? s.V_in_max : n.max || 0,
        source_min: null,
        source_max: null,
        ok: true,
        normal_available: true,
        unavailable: 0,
        enabled: n.enabled,
      };
    }
  }
  for (const [key, r] of Object.entries(capacity))
    Object.assign(r, {
      port: key,
      allocated: 0,
      normal: 0,
      worst_case: "无供电需求",
      remaining: r.capacity,
      ok: true,
    });
  const inputs = new Map(
      entries.map(([, n]) => [n.id, networkIncoming(p, n.id, true)]),
    ),
    variable = p.sources
      .filter((b: Spec) => b.enabled && b.max > b.min)
      .map((b: Spec) => b.id) as string[];
  const voltagesCases: [string, Set<string>][] = [["Vinmin", new Set()]];
  if (variable.length) voltagesCases.push(["Vinmax", new Set(variable)]);
  if (variable.length > 1)
    for (const r of variable) voltagesCases.push([r + " 高压", new Set([r])]);
  const cases: Spec[] = [];
  let complete = true;
  for (const { names, available } of unique.values())
    for (const [voltageName, high] of voltagesCases) {
      const voltages: Record<string, number> = {},
        choices: Record<string, Spec[]> = {};
      for (const identity of order) {
        const { kind, node: n } = byId.get(identity)!;
        if (!n.enabled) continue;
        if (kind === "bus") {
          if (available.has(identity))
            voltages[identity] = high.has(identity) ? n.max : n.min;
          continue;
        }
        const candidates: Spec[] = [];
        for (const e of inputs.get(identity)!) {
          const s = e.source,
            parent = byId.get(s.id)!.node;
          let vin = voltages[s.id];
          if (vin !== undefined && s.kind === "unit")
            vin = networkRails(parent)[s.output - 1].V_out;
          const v =
            vin === undefined ? -1 : vin - (e.mode === "diode" ? e.vf : 0);
          if (v > 0) candidates.push({ e, v, vin });
        }
        if (!candidates.length) continue;
        const winner = Math.max(...candidates.map((c) => c.v));
        choices[identity] = candidates.filter(
          (c) => Math.abs(c.v - winner) <= 1e-8 * Math.max(1, winner),
        );
        voltages[identity] = winner;
      }
      const normal = available.size === roots.length;
      for (const [identity, r] of Object.entries(iface)) {
        if (!r.enabled) continue;
        const v = voltages[identity];
        if (v === undefined) {
          r.unavailable++;
          if (normal) r.normal_available = false;
          continue;
        }
        r.source_min = r.source_min === null ? v : Math.min(r.source_min, v);
        r.source_max = r.source_max === null ? v : Math.max(r.source_max, v);
        r.ok &&=
          (!r.design_min || v >= r.design_min - 1e-8) &&
          (!r.design_max || v <= r.design_max + 1e-8);
      }
      const keys = Object.keys(choices),
        count = keys.reduce((n, k) => n * choices[k].length, 1);
      if (count > 128) complete = false;
      for (let index = 0; index < Math.min(count, 128); index++) {
        if (cases.length >= 2048) {
          complete = false;
          break;
        }
        let code = index;
        const picked: Record<string, Spec> = {};
        for (let i = keys.length - 1; i >= 0; i--) {
          const k = keys[i];
          picked[k] = choices[k][code % choices[k].length];
          code = Math.floor(code / choices[k].length);
        }
        const demand: Record<string, number> = {},
          allocated: Record<string, number> = {},
          losses: Record<string, number> = {},
          routes: Record<string, string> = {};
        for (const identity of [...order].reverse()) {
          const { kind, node: n } = byId.get(identity)!;
          if (
            voltages[identity] === undefined ||
            !n.enabled ||
            !picked[identity] ||
            kind === "bus"
          )
            continue;
          const watts =
            kind === "unit"
              ? networkRails(n).reduce((sum, r) => sum + r.P_out, 0) /
                n.spec.eta_guess
              : kind === "load"
                ? n.power
                : demand[identity] || 0;
          const { e, v, vin } = picked[identity],
            pin = (watts * vin) / v,
            key = networkPort(e.source);
          allocated[key] = (allocated[key] || 0) + pin;
          demand[e.source.id] = (demand[e.source.id] || 0) + pin;
          losses[e.id] = Math.max(0, pin - watts);
          routes[identity] = e.id;
        }
        const name = names.join(" / ") + " · " + voltageName;
        cases.push({
          name,
          normal,
          allocated,
          routes,
          unavailable: Object.keys(iface).filter(
            (i) => iface[i].enabled && voltages[i] === undefined,
          ),
        });
        for (const [key, watts] of Object.entries(allocated)) {
          const r = capacity[key];
          if (watts > r.allocated)
            Object.assign(r, { allocated: watts, worst_case: name });
          if (normal) r.normal = Math.max(r.normal, watts);
        }
        for (const [key, watts] of Object.entries(losses))
          diode[key] = Math.max(diode[key] || 0, watts);
      }
    }
  for (const r of Object.values(capacity))
    Object.assign(r, {
      remaining: r.capacity - r.allocated,
      ok: r.allocated <= r.capacity + 1e-8 && complete,
    });
  for (const r of Object.values(iface)) {
    r.ok &&= r.normal_available && r.source_min !== null;
    r.note = !r.enabled
      ? "未启用"
      : !r.normal_available
        ? "正常供电缺失"
        : r.unavailable
          ? "存在掉电/独供工况失电"
          : "已覆盖已评估工况";
  }
  return {
    capacity: Object.values(capacity),
    interfaces: Object.values(iface),
    cases,
    diode_losses: p.connections.map((e: Spec) => ({
      connection: e.id,
      source: networkPort(e.source),
      target: e.target,
      vf: e.mode === "diode" ? e.vf : 0,
      loss: diode[e.id] || 0,
    })),
    coverage_complete: complete,
    method:
      "固定Vf标称稳态预算；高电压支路优先，同压不假定均流，枚举独占供电。覆盖全源、逐源掉电和单源独供，以及全低/全高/逐源高压；非全部电压组合，非瞬态或切换仿真。",
  };
}
