import { type Spec, clone } from "./spec";
import { frame, escape } from "./charts";
export const windingRows = (res: Spec) =>
  res.mag.transformer
    ? [
        {
          id: "P",
          name: "原边 P",
          turns: res.mag.transformer.Np,
          strands: res.mag.transformer.n_strand_p,
          bare_diameter: res.mag.transformer.d_wire_p,
        },
        ...res.mag.transformer.windings.map((w: Spec) => ({
          id: "OUT" + w.id,
          name: w.name,
          turns: w.Ns,
          strands: w.n_strand_s,
          bare_diameter: w.d_wire_s,
        })),
        ...(res.mag.transformer.auxiliary
          ? [
              {
                id: "AUX",
                name: "辅助采样绕组",
                turns: res.mag.transformer.auxiliary.Na,
                strands: 1,
                bare_diameter: res.mag.transformer.auxiliary.d_wire,
              },
            ]
          : []),
      ]
    : [];
export function assess(rows: Spec[], raw: Spec = {}) {
  const config: Spec = {
      window_width: 0,
      window_height: 0,
      margin_x: 0.00025,
      margin_y: 0.0001,
      diameter_allowance: 0.00003,
      layer_insulation: 0.00005,
      interwinding_insulation: 0.00015,
      wire_gap: 0,
      order: [],
      overrides: {},
      layer_plan: [],
      ...clone(raw),
    },
    base: Spec = {
      config,
      configured: config.window_width > 0 && config.window_height > 0,
      windings: [],
      fits: null,
      status: "not_configured",
      warnings: [],
      interleaved: !!config.layer_plan.length,
      physical_layers: [],
      total_layer_count: 0,
    };
  if (!base.configured) return base;
  for (const key of [
    "window_width",
    "window_height",
    "margin_x",
    "margin_y",
    "diameter_allowance",
    "layer_insulation",
    "interwinding_insulation",
    "wire_gap",
  ])
    if (!Number.isFinite(config[key]) || config[key] < 0)
      throw Error(key + " 必须为有限非负数");
  if (config.layer_plan.length > 1000) throw Error("手动层计划最多 1000 层");
  const width = config.window_width - 2 * config.margin_x,
    height = config.window_height - 2 * config.margin_y;
  if (!(width > 0 && height > 0))
    throw Error("窗口扣除留边后的净宽净高必须大于 0");
  const by = new Map(rows.map((r) => [r.id, r])),
    ordered = [
      ...config.order.filter((id: string) => by.has(id)),
      ...rows.map((r) => r.id).filter((id) => !config.order.includes(id)),
    ];
  for (const id of ordered) {
    const row = by.get(id)!,
      override = (config.overrides as Spec)[id] || {},
      wire = {
        wire_type: "auto",
        parallel_bundles: 1,
        packing_factor: 0.75,
        bundle_diameter: 0,
        flatten_ratio: 1.5,
        winding_style: "sparse",
        turns_per_layer: 0,
        outer_diameter: 0,
        ...override,
      },
      bundles = wire.strand_columns ? 1 : wire.parallel_bundles,
      per = row.strands / bundles;
    if (
      !Number.isInteger(row.turns) ||
      row.turns < 1 ||
      !Number.isFinite(row.bare_diameter) ||
      row.bare_diameter <= 0
    )
      throw Error(id + " 匝数与线径无效");
    if (
      !(wire.packing_factor > 0 && wire.packing_factor <= 1) ||
      !(wire.flatten_ratio > 0 && wire.flatten_ratio <= 3)
    )
      throw Error(id + " 线束填充与压扁比例无效");
    if (!Number.isInteger(bundles) || bundles < 1 || !Number.isInteger(per))
      throw Error(id + " 每匝并绕束数必须整除总股数");
    if (
      wire.strand_columns &&
      (!Number.isInteger(wire.strand_columns) ||
        wire.strand_columns < 1 ||
        wire.strand_columns > row.strands)
    )
      throw Error("旧矩形束列数须为不大于股数的正整数");
    if (
      wire.strand_columns &&
      [
        "wire_type",
        "parallel_bundles",
        "packing_factor",
        "bundle_diameter",
        "flatten_ratio",
        "winding_style",
        "turns_per_layer",
      ].some((k) => k in override)
    )
      throw Error("旧矩形束不能与等效线束参数混用，请将 strand_columns 设为0");
    const outer =
        wire.outer_diameter || row.bare_diameter + config.diameter_allowance,
      kind =
        per === 1
          ? "solid"
          : wire.wire_type === "auto"
            ? "litz"
            : wire.wire_type,
      ratio = !wire.strand_columns && kind === "litz" ? wire.flatten_ratio : 1,
      diameter =
        wire.bundle_diameter ||
        (per === 1 ? outer : outer * Math.sqrt(per / wire.packing_factor));
    if (
      !wire.strand_columns &&
      (diameter < outer * Math.sqrt(per) - 1e-15 ||
        diameter / ratio < outer - 1e-15)
    )
      throw Error(id + " 整束尺寸或压扁比例不合理");
    const bw = wire.strand_columns
        ? wire.strand_columns * outer +
          (wire.strand_columns - 1) * config.wire_gap
        : diameter * ratio,
      bh = wire.strand_columns
        ? Math.ceil(row.strands / wire.strand_columns) * outer +
          (Math.ceil(row.strands / wire.strand_columns) - 1) * config.wire_gap
        : diameter / ratio,
      turnWidth = bundles * bw + (bundles - 1) * config.wire_gap,
      capacity = Math.max(
        0,
        Math.floor(
          (width + config.wire_gap) / (turnWidth + config.wire_gap) + 1e-10,
        ),
      ),
      perLayer = wire.turns_per_layer || capacity;
    if (wire.turns_per_layer > capacity)
      throw Error(id + " 指定每层匝数超过窗口容量");
    base.windings.push({
      ...row,
      layout_model: wire.strand_columns ? "legacy_rectangular" : "equivalent",
      bundle_width: bw,
      bundle_height: bh,
      turn_width: turnWidth,
      parallel_bundles: bundles,
      wire_type: kind,
      winding_style: wire.winding_style,
      turns_per_layer: perLayer,
      capacity,
      layers: Math.ceil(row.turns / Math.max(perLayer, 1)),
    });
  }
  const map = new Map(base.windings.map((w: Spec) => [w.id, w])) as Map<
    string,
    Spec
  >;
  let plan: Spec[] = config.layer_plan;
  if (!plan.length) {
    plan = [];
    for (const row of base.windings) {
      let remaining = row.turns;
      while (remaining > 0) {
        if (plan.length >= 12000) throw Error("实体层数量超过计算上限");
        const turns = Math.min(Math.max(row.turns_per_layer, 1), remaining);
        plan.push({
          winding_id: row.id,
          turns,
          winding_style: row.winding_style,
        });
        remaining -= turns;
      }
    }
  } else {
    for (const row of base.windings) {
      const count = plan
        .filter((v) => v.winding_id === row.id)
        .reduce((s, v) => s + v.turns, 0);
      if (count !== row.turns)
        throw Error(row.id + " 手动层计划总匝数与电气匝数不符");
    }
  }
  let y = 0,
    last = "",
    overflow = false;
  for (const [index, entry] of plan.entries()) {
    if (!Number.isInteger(entry.turns) || entry.turns < 1)
      throw Error("每层匝数必须为正整数");
    const row = map.get(entry.winding_id);
    if (!row) throw Error("层计划包含不存在的绕组");
    if (entry.turns < 1 || entry.turns > row.capacity) overflow = true;
    if (index)
      y +=
        last === row.id
          ? config.layer_insulation
          : config.interwinding_insulation;
    base.physical_layers.push({
      ...row,
      index: index + 1,
      turns: entry.turns,
      y,
      winding_style: entry.winding_style || row.winding_style,
    });
    y += row.bundle_height;
    last = row.id;
  }
  base.windings.forEach(
    (row: Spec) =>
      (row.layers = plan.filter((v) => v.winding_id === row.id).length),
  );
  return {
    ...base,
    status: "assessed",
    fits: !overflow && y <= height,
    required_height: y,
    height_margin: height - y,
    usable_width: width,
    usable_height: height,
    total_layer_count: plan.length,
    automatic_plan: plan,
    warnings: [
      "等效线束及绝缘几何预评估，不代表制造与安规验证通过；机械设置不改变电气 DCR、股数或耦合系数。",
    ],
  };
}
export function windingChart(a: Spec) {
  if (!a.configured)
    return frame(
      '<text x="90" y="170" font-size="24" fill="#68788f">请填写骨架窗口净宽与净高</text>',
      "变压器绕制横截面",
    );
  const cfg = a.config,
    w = cfg.window_width,
    h = Math.max(cfg.window_height, a.required_height + 2 * cfg.margin_y),
    scale = Math.min(940 / w, 400 / h),
    left = 130,
    bottom = 530,
    top = bottom - h * scale,
    palette = ["#2376e5", "#20aebf", "#ee8a37", "#7b62df", "#119777"];
  let body = `<rect x="${left}" y="${top}" width="${w * scale}" height="${cfg.window_height * scale}" fill="#f8fafc" stroke="#68788f" stroke-width="2"/><rect x="${left - 20}" y="${top - 20}" width="20" height="${cfg.window_height * scale + 40}" fill="#e4eaf2"/><rect x="${left + w * scale}" y="${top - 20}" width="20" height="${cfg.window_height * scale + 40}" fill="#e4eaf2"/>`;
  for (const layer of a.physical_layers.slice(0, 256)) {
    const width =
        layer.turn_width * layer.turns + cfg.wire_gap * (layer.turns - 1),
      start =
        layer.winding_style === "dense_right"
          ? w - cfg.margin_x - width
          : cfg.margin_x,
      gap =
        layer.winding_style === "sparse" && layer.turns > 1
          ? (a.usable_width - layer.turns * layer.turn_width) /
            (layer.turns - 1)
          : cfg.wire_gap,
      color =
        palette[
          a.windings.findIndex((r: Spec) => r.id === layer.id) % palette.length
        ],
      y = top + (cfg.margin_y + layer.y + layer.bundle_height / 2) * scale;
    for (let turn = 0; turn < Math.min(layer.turns, 300); turn++)
      for (let b = 0; b < layer.parallel_bundles; b++) {
        const x =
          left +
          (start +
            turn * (layer.turn_width + gap) +
            b * (layer.bundle_width + cfg.wire_gap) +
            layer.bundle_width / 2) *
            scale;
        body +=
          layer.layout_model === "legacy_rectangular"
            ? `<rect x="${x - (layer.bundle_width * scale) / 2}" y="${y - (layer.bundle_height * scale) / 2}" width="${layer.bundle_width * scale}" height="${layer.bundle_height * scale}" fill="white" stroke="${color}"/>`
            : `<ellipse cx="${x}" cy="${y}" rx="${(layer.bundle_width * scale) / 2}" ry="${(layer.bundle_height * scale) / 2}" fill="white" stroke="${color}" stroke-width="1.5"/>`;
      }
    body += `<text x="${left + w * scale + 28}" y="${y + 5}" font-family="Microsoft YaHei,Arial" font-size="15" fill="${color}">${escape(layer.id)} · ${layer.turns} 匝</text>`;
  }
  body += `<text x="130" y="580" font-family="Microsoft YaHei,Arial" font-size="17" fill="#152238">窗口 ${(w * 1000).toFixed(2)} × ${(cfg.window_height * 1000).toFixed(2)} mm · 径向占用 ${(a.required_height * 1000).toFixed(2)} mm · ${a.fits ? "可容纳" : "存在溢出"}</text>`;
  return frame(body, "变压器等比例绕制横截面", 630);
}
