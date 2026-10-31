import { windingRows, assess, windingChart } from "./winding";
import { type Spec } from "./spec";
import { mean, ptp, interpolate } from "./math";
import { design } from "./engine";
import { scaleLoad, pinHardware } from "./actions";
import { compensationDiagram } from "./compensation";
import { loopResponse } from "./loop";
export const escape = (v: any) =>
  String(v ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&apos;",
      })[c]!,
  );
const palette = [
  "#2376e5",
  "#20aebf",
  "#ee8a37",
  "#7b62df",
  "#119777",
  "#c47a0b",
];
const text = (
  x: number,
  y: number,
  s: any,
  size = 16,
  color = "#152238",
  anchor = "start",
) =>
  `<text x="${x}" y="${y}" font-family="Microsoft YaHei,Arial,sans-serif" font-size="${size}" fill="${color}" text-anchor="${anchor}">${escape(s)}</text>`;
export function frame(body: string, title: string, height = 540, width = 1200) {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><rect width="${width}" height="${height}" rx="14" fill="#fff"/>${text(30, 34, "PCS / AUXILIARY POWER DESIGN", 12, "#2376e5")}${text(30, 67, title, 24)}${body}</svg>`;
}
function eng(v: number) {
  return Number.isFinite(v)
    ? v === 0
      ? "0"
      : Math.abs(v) >= 1e5 || Math.abs(v) < 0.001
        ? v.toExponential(2)
        : Number(v.toPrecision(4)).toString()
    : "—";
}
export function lineChart(
  series: { x: number[]; y: number[]; label: string }[],
  title: string,
  unit: string,
  log = false,
  height = 540,
  xLabel?: string,
) {
  const left = 90,
    right = 1160,
    top = 115 + Math.max(0, Math.ceil(series.length / 4) - 1) * 23,
    bottom = height - 75,
    valid = series.flatMap((s) =>
      s.x
        .map((x, i) => [log ? Math.log10(x) : x, s.y[i]])
        .filter((p) => p.every(Number.isFinite)),
    );
  if (!valid.length) throw Error("图表没有有效数据");
  const xs = valid.map((p) => p[0]),
    ys = valid.map((p) => p[1]),
    xmin = Math.min(...xs),
    xmax = Math.max(...xs),
    y0 = Math.min(...ys),
    y1 = Math.max(...ys),
    pad = Math.max((y1 - y0) * 0.1, Math.abs(y1) * 0.02, 0.01),
    ymin = y0 - pad,
    ymax = y1 + pad,
    mapx = (v: number) =>
      left + ((v - xmin) / (xmax - xmin || 1)) * (right - left),
    mapy = (v: number) =>
      bottom - ((v - ymin) / (ymax - ymin)) * (bottom - top);
  let body = "";
  for (let j = 0; j <= 5; j++) {
    const y = top + ((bottom - top) * j) / 5,
      x = left + ((right - left) * j) / 5;
    body +=
      `<path d="M${left} ${y}H${right} M${x} ${top}V${bottom}" stroke="#e4eaf2"/>` +
      text(
        left - 12,
        y + 5,
        eng(ymax - ((ymax - ymin) * j) / 5),
        14,
        "#68788f",
        "end",
      ) +
      text(
        x,
        bottom + 28,
        eng(
          log
            ? 10 ** (xmin + ((xmax - xmin) * j) / 5)
            : xmin + ((xmax - xmin) * j) / 5,
        ),
        14,
        "#68788f",
        "middle",
      );
  }
  series.forEach((s, j) => {
    const stride = Math.max(1, Math.floor(s.x.length / 1800)),
      points = s.x
        .flatMap((v, i) =>
          i % stride === 0 || i === s.x.length - 1
            ? [[mapx(log ? Math.log10(v) : v), mapy(s.y[i])]]
            : [],
        )
        .filter((p) => p.every(Number.isFinite));
    body +=
      `<polyline points="${points.map((p) => p.join(",")).join(" ")}" fill="none" stroke="${palette[j % palette.length]}" stroke-width="2.4"/>` +
      text(
        100 + (j % 4) * 275,
        95 + Math.floor(j / 4) * 23,
        s.label,
        15,
        palette[j % palette.length],
      );
  });
  body +=
    text(left, top - 9, unit, 14, "#68788f") +
    text(
      (left + right) / 2,
      height - 15,
      xLabel || (log ? "频率 / Hz" : "时间 / µs"),
      15,
      "#68788f",
      "middle",
    );
  return frame(body, title, height);
}
export function bars(
  rows: { name: string; values: number[] }[],
  labels: string[],
  title: string,
  height = 540,
) {
  const max = Math.max(
      ...rows.map((r) => r.values.reduce((s, v) => s + v, 0)),
      1e-9,
    ),
    left = 90,
    bottom = height - 95,
    top = 125,
    width = 1050 / Math.max(rows.length, 1);
  let body = "";
  for (let j = 0; j <= 4; j++) {
    const y = bottom - ((bottom - top) * j) / 4;
    body +=
      `<path d="M${left} ${y}H1160" stroke="#e4eaf2"/>` +
      text(left - 12, y + 4, eng((max * j) / 4), 14, "#68788f", "end");
  }
  rows.forEach((r, i) => {
    let current = bottom;
    r.values.forEach((v, j) => {
      const h = (v / max) * (bottom - top),
        x = left + i * width + width * 0.2;
      body += `<rect x="${x}" y="${current - h}" width="${width * 0.6}" height="${Math.max(h, 0)}" rx="2" fill="${palette[j % palette.length]}"/>`;
      current -= h;
    });
    body +=
      text(
        left + (i + 0.5) * width,
        bottom + 26,
        r.name,
        14,
        "#68788f",
        "middle",
      ) +
      text(
        left + (i + 0.5) * width,
        current - 9,
        eng(r.values.reduce((s, v) => s + v, 0)),
        14,
        "#152238",
        "middle",
      );
  });
  labels.forEach(
    (s, i) =>
      (body += text(95 + i * 205, 96, s, 14, palette[i % palette.length])),
  );
  return frame(body, title, height);
}
export function topology(p: Spec, res: Spec) {
  const rr = res.outputs,
    isFlyback = ["FLYBACK", "QR-FLYBACK"].includes(p.topology);
  const height = Math.max(580, rr.length * 190 + 195);
  const line = (x: number, y: number, u: number, v: number) =>
    `<path d="M${x} ${y}L${u} ${v}" fill="none" stroke="#183551" stroke-width="2.4"/>`;
  const cap = (x: number, y: number, bottom: number, name: string) =>
    line(x, y, x, y + 28) +
    line(x - 17, y + 28, x + 17, y + 28) +
    line(x - 17, y + 38, x + 17, y + 38) +
    line(x, y + 38, x, bottom) +
    text(x - 27, bottom + 22, name, 13);
  const diode = (x: number, y: number, name: string) =>
    `<path d="M${x} ${y - 12}V${y + 12}L${x + 22} ${y}Z M${x + 26} ${y - 14}V${y + 14}" fill="white" stroke="#183551" stroke-width="2.4"/>` +
    text(x, y - 23, name, 13);
  const coil = (x: number, y: number) =>
    `<path d="M${x} ${y} ${Array.from({ length: 4 }, (_, i) => "c25 0 25 20 0 20").join(" ")}" fill="none" stroke="#2376e5" stroke-width="2.5"/>`;
  const dots = (x: number, y: number) =>
    `<circle cx="${x}" cy="${y}" r="4" fill="#183551"/>`;
  let body = text(
    40,
    110,
    `Vin ${p.V_in_min}–${p.V_in_max} V · ${p.topology}`,
    18,
  );
  const inputCount = res.capacitors.input.caps.length;
  body +=
    (p.d_in_enable
      ? line(70, 170, 95, 170) +
        diode(95, 170, "D_IN") +
        line(121, 170, 475, 170)
      : line(70, 170, 475, 170)) +
    line(70, height - 95, 475, height - 95) +
    text(75, 150, "J1 / VIN", 16);
  [0, 1]
    .slice(0, Math.min(inputCount, 2))
    .forEach(
      (i) => (body += cap(145 + i * 105, 170, height - 95, "C_IN" + (i + 1))),
    );
  if (inputCount > 2)
    body += text(290, 240, "… 共 " + inputCount + " 颗并联", 14, "#68788f");
  if (isFlyback || p.topology === "ACF-FORWARD") {
    body +=
      line(475, 170, 475, 185) +
      coil(475, 185) +
      dots(462, 190) +
      line(475, 265, 475, 315);
    body +=
      `<rect x="433" y="315" width="84" height="65" rx="8" fill="#e9f2ff" stroke="#2376e5"/>` +
      text(475, 342, "Q1", 18, "#2376e5", "middle") +
      text(475, 366, "MOS", 13, "#68788f", "middle");
    body +=
      line(475, 380, 475, 408) +
      `<rect x="462" y="408" width="26" height="44" fill="white" stroke="#183551" stroke-width="2"/>` +
      text(405, 433, "R_S1", 14) +
      line(475, 452, 475, height - 95);
    body += line(360, 347, 433, 347) + text(340, 330, "PWM", 14, "#68788f");
    if (p.topology === "ACF-FORWARD")
      body +=
        line(475, 285, 340, 285) +
        cap(340, 285, 380, "C_CLAMP") +
        '<rect x="303" y="380" width="74" height="50" rx="6" fill="#e9f2ff" stroke="#2376e5"/>' +
        text(340, 410, "Q2", 17, "#2376e5", "middle") +
        line(340, 430, 340, height - 95) +
        text(290, 458, "互补 / 死区", 13, "#68788f");
    body +=
      line(535, 155, 535, Math.max(290, height - 130)) +
      line(543, 155, 543, Math.max(290, height - 130)) +
      text(540, 134, "T1", 18, "#2376e5", "middle");
    body +=
      text(337, 285, "Np " + res.mag.transformer.Np, 14, "#68788f") +
      text(80, height - 65, "PGND", 14);
    rr.forEach((r: Spec, i: number) => {
      const y = 170 + i * 190,
        capCount = r.capacitors.output.caps.length,
        names = rr.length > 1 && p.outputs?.length;
      body +=
        coil(615, y) +
        dots(602, y + (isFlyback ? 74 : 6)) +
        line(615, y, 685, y) +
        diode(685, y, names ? "D_O" + r.id : "D1") +
        (isFlyback
          ? line(711, y, 985, y)
          : line(711, y, 735, y) +
            `<path d="M735 ${y} q7 -20 14 0 q7 -20 14 0 q7 -20 14 0 q7 -20 14 0" fill="none" stroke="#2376e5" stroke-width="2.4"/>` +
            text(740, y - 26, "L_O" + r.id, 13) +
            line(791, y, 985, y) +
            line(725, y, 725, y + 22) +
            line(725, y + 45, 725, y + 80) +
            `<path d="M713 ${y + 45}L737 ${y + 45}L725 ${y + 25}ZM710 ${y + 22}H740" fill="white" stroke="#183551" stroke-width="2.2"/>` +
            text(673, y + 62, "D_F" + r.id, 12)) +
        line(615, y + 80, 1140, y + 80);
      const prefix = names ? "C_O" + r.id : "C_O";
      [0, 1]
        .slice(0, Math.min(capCount, 2))
        .forEach(
          (j) =>
            (body += cap(
              800 + j * 115,
              y,
              y + 80,
              prefix + (names ? String.fromCharCode(65 + j) : j + 1),
            )),
        );
      if (capCount > 2)
        body += text(
          800,
          y + 120,
          "… 共 " + capCount + " 颗并联",
          13,
          "#68788f",
        );
      if (
        r.op.d_out_enable ||
        p.outputs?.[i]?.d_out_enable ||
        (!p.outputs?.length && p.d_out_enable)
      )
        body +=
          diode(985, y, names ? "D_B" + r.id : "D_OUT") +
          line(1011, y, 1140, y);
      else body += line(985, y, 1140, y);
      body +=
        text(
          630,
          y - 47,
          `OUT${r.id} · ${r.name} · Ns ${res.mag.transformer.windings[i].Ns}`,
          17,
        ) +
        text(1030, y + 35, eng(r.op.V_out) + " V", 17, "#2376e5") +
        text(1030, y + 61, eng(r.op.P_out) + " W", 14, "#68788f");
      if (r.id === (p.feedback_output || 1))
        body +=
          dots(965, y) +
          text(930, y + 112, "↑ 主反馈：防反管前", 13, "#2376e5");
    });
  } else {
    const bottom = height - 95,
      buck = p.topology === "BUCK",
      boost = p.topology === "BOOST";
    const switchBox = (x: number, y: number) =>
      `<rect x="${x}" y="${y}" width="80" height="48" rx="7" fill="#e9f2ff" stroke="#2376e5"/>` +
      text(x + 40, y + 30, "Q1", 18, "#2376e5", "middle");
    const horizontalCoil = (x: number, y: number) =>
      `<path d="M${x} ${y} q7 -22 14 0 q7 -22 14 0 q7 -22 14 0 q7 -22 14 0" fill="none" stroke="#2376e5" stroke-width="2.4"/>` +
      text(x + 18, y - 30, "L1", 15);
    body += line(475, bottom, 1120, bottom);
    if (buck) {
      body +=
        switchBox(475, 146) +
        line(555, 170, 650, 170) +
        horizontalCoil(650, 170) +
        line(706, 170, 930, 170) +
        line(605, 170, 605, 240) +
        `<g transform="translate(605 270) rotate(-90)">${diode(0, 0, "D1")}</g>` +
        line(605, 270, 605, bottom) +
        text(600, 147, "SW", 14);
    } else if (boost) {
      body +=
        horizontalCoil(475, 170) +
        line(531, 170, 685, 170) +
        diode(685, 170, "D1") +
        line(711, 170, 930, 170) +
        line(625, 170, 625, 270) +
        switchBox(585, 270) +
        line(625, 318, 625, bottom) +
        text(615, 147, "SW", 14);
    } else {
      body +=
        switchBox(475, 146) +
        line(555, 170, 625, 170) +
        line(625, 170, 625, 235) +
        coil(625, 235) +
        line(625, 315, 625, bottom) +
        text(648, 275, "L1", 15) +
        line(625, 170, 685, 170) +
        `<g transform="translate(735 170) rotate(180)">${diode(0, 0, "D1")}</g>` +
        line(735, 170, 930, 170) +
        text(730, 235, "负输出，参考共地", 15, "#68788f");
    }
    body +=
      cap(790, 170, bottom, "C_OUT ×" + rr[0].capacitors.output.caps.length) +
      dots(910, 170) +
      text(850, 310, "主反馈：防反管前", 14, "#2376e5");
    body +=
      (p.d_out_enable
        ? diode(930, 170, "D_OUT") + line(956, 170, 1120, 170)
        : line(930, 170, 1120, 170)) +
      text(1000, 145, "J2 / OUT", 16) +
      text(970, 220, eng(rr[0].op.V_out) + " V", 20, "#2376e5") +
      text(80, bottom + 28, "GND", 15);
  }
  body += text(
    30,
    height - 22,
    "工程示意 · 电容数量随配置更新；完整器件参数见 BOM；未展开钳位、驱动与辅助供电。",
    14,
    "#68788f",
  );
  return frame(body, "辅源拓扑与器件位号", height);
}

export function chart(p: Spec, res: Spec, kind: string, output = 1) {
  const w = res.wf,
    branch = res.outputs[output - 1] || res.outputs[0],
    bw = w.outputs?.[output - 1] || w,
    time = (a: number[]) => a.map((x) => x * 1e6),
    series = (key: string, label: string, scale = 1) => ({
      x: time(w.t),
      y: w[key].map((v: number) => v * scale),
      label,
    });
  if (kind === "topology") return topology(p, res);
  if (kind === "multi_reference" || kind === "multi_load") {
    const d = loopResponse(p, res.op, output),
      load = kind === "multi_load";
    if (load && !d.dc_load) throw Error("理想匝比模型没有独立负载动态");
    const panels = [
      lineChart(
        d.outputs.map((r: Spec) => ({
          x: d.frequency,
          y: load ? r.load_db : r.reference_db,
          label: "OUT" + r.id,
        })),
        load ? `OUT${output} 负载 → 各路电压` : "主参考 → 各路相对变化率",
        load ? "dBΩ（ΔV / ΔI）" : "dB（% / %）",
        true,
      ),
      lineChart(
        d.outputs.map((r: Spec) => ({
          x: d.frequency,
          y: load ? r.load_phase : r.reference_phase,
          label: "OUT" + r.id,
        })),
        load ? "负载扰动相位" : "主参考跟踪相位",
        "deg",
        true,
      ),
    ];
    return `<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="1080" viewBox="0 0 1200 1080">${panels.map((svg, i) => svg.replace("<svg ", `<svg x="0" y="${i * 540}" `)).join("")}</svg>`;
  }
  if (kind === "compensation")
    return compensationDiagram(
      res.compensation?.key || p.__comp?.key || "opamp3",
    );
  if (kind === "parasitics") {
    const data = res.parasitics || res.op.parasitics;
    if (!data?.edges?.length)
      throw Error(data?.scope || "未启用局部寄生换流计算");
    return lineChart(
      data.edges.map((e: Spec) => ({
        x: e.t.map((v: number) => v * 1e6),
        y: e.voltage,
        label: e.ref + " · " + eng(e.peak) + "V",
      })),
      "局部寄生换流 · 独立端口 RLC",
      "V",
    );
  }
  if (kind === "efficiency") {
    const fixed = pinHardware(res),
      rows = Array.from({ length: 10 }, (_, i) => {
        const frac = (i + 1) / 10;
        try {
          return { frac, eta: design(scaleLoad(fixed, frac), false).eta };
        } catch (e) {
          return { frac, eta: null, error: String(e) };
        }
      });
    return lineChart(
      [
        {
          x: rows.filter((r) => r.eta !== null).map((r) => r.frac * 100),
          y: rows.filter((r) => r.eta !== null).map((r) => r.eta! * 100),
          label: "Vin " + p.V_in + "V · 固定磁件",
        },
      ],
      "效率与负载 · 失败负载点留空",
      "η / %",
      false,
      540,
      "负载 / %",
    );
  }
  if (kind === "winding")
    return windingChart(assess(windingRows(res), p.winding_config || {}));
  if (kind === "power")
    return lineChart(
      [
        series("i_p", "励磁/电感电流"),
        series("i_sw", "MOS 电流"),
        series("i_d", "主路整流电流"),
      ],
      "功率级关键电流",
      "A",
    );
  if (kind === "outputs")
    return `<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="1080" viewBox="0 0 1200 1080">${lineChart(
      [
        { x: time(bw.t), y: bw.i_d, label: "副边 / 整流电流" },
        { x: time(bw.t), y: bw.i_c, label: "输出电容电流" },
      ],
      `OUT${output} · ${branch.name} 电流 · RMS ${eng(Math.sqrt(mean(bw.i_d.map((v: number) => v * v))))}A`,
      "A",
    ).replace("<svg ", '<svg x="0" y="0" ')}${lineChart(
      [
        { x: time(bw.t), y: bw.v_d, label: "整流管反压" },
        { x: time(bw.t), y: bw.vout, label: "端口输出电压" },
      ],
      `OUT${output} 电压 · 反压不含未建模尖峰，选型留裕量`,
      "V",
    ).replace("<svg ", '<svg x="0" y="540" ')}</svg>`;
  if (
    kind === "output_caps" ||
    kind === "capacitors" ||
    kind === "input_caps"
  ) {
    const input = kind === "input_caps",
      caps = input
        ? res.capacitors.input.caps
        : kind === "output_caps"
          ? branch.capacitors.output.caps
          : res.capacitors.output.caps;
    const labels = ["<0.5fs", "1–3fs", "4–10fs", "11–20fs", "HF"],
      name = input ? "C_IN" : "C_OUT";
    return bars(
      caps.map((c: Spec, i: number) => ({
        name: name + (i + 1),
        values: [
          [0, 1],
          [1, 4],
          [4, 11],
          [11, 21],
          [21, 22],
        ].map(([a, b]) =>
          c.bands.slice(a, b).reduce((s: number, v: number) => s + v * v, 0),
        ),
      })),
      labels,
      (input ? "输入" : "OUT" + output + " 输出") +
        "电容频带分流 / A²（各频带相加为 RMS²）",
    );
  }
  if (kind === "output_losses")
    return bars(
      res.outputs.map((r: Spec) => ({
        name: "OUT" + r.id,
        values: [r.P_rectifier, r.P_cap, r.P_dout],
      })),
      ["整流损耗", "电容 ESR", "防反损耗"],
      "各路输出器件损耗 / W",
    );
  if (kind === "device_losses")
    return bars(
      Object.entries(res.semi.switch)
        .filter(
          ([k, v]) =>
            k.startsWith("P_") && k !== "P_total" && typeof v === "number",
        )
        .map(([k, v]) => ({
          name: k.replace("P_", ""),
          values: [v as number],
        })),
      ["损耗 / W"],
      "主 MOSFET 损耗分解",
    );
  if (kind === "losses")
    return bars(
      [
        "P_semi",
        "P_mag",
        "P_cap",
        "P_cap_in",
        "P_sense",
        "P_rcd",
        "P_din",
        "P_dout",
      ].map((k) => ({ name: k, values: [res[k]] })),
      ["损耗 / W"],
      "设计损耗分解",
    );
  if (kind === "magnetics")
    return bars(
      [res.mag.transformer, res.mag.inductor, ...(res.mag.inductors || [])]
        .filter(Boolean)
        .map((x: Spec, i: number) => ({
          name: x.core + " " + (i + 1),
          values: [x.P_cu, x.P_core],
        })),
      ["铜损", "磁芯损耗"],
      "磁件损耗 / W",
    );
  if (kind === "magnetic_flux") {
    const tr = res.mag.transformer,
      dev = tr || res.mag.inductor,
      l = tr ? (p.topology === "ACF-FORWARD" ? p.Lm_forward : p.L) : p.L,
      n = tr ? dev.Np : dev.N;
    const z = res.op.acf_solution,
      fluxPoints = z
        ? z.t.map((v: number, j: number) => [
            v,
            (z.lambda_p[j] / n / dev.Ae) * 1000,
          ])
        : null;
    return lineChart(
      [
        {
          x: time(w.t),
          y:
            p.topology === "ACF-FORWARD"
              ? w.t.map((v: number) => {
                  return z
                    ? interpolate(fluxPoints!, v % res.op.Ts)
                    : (v % res.op.Ts < res.op.D * res.op.Ts
                        ? -dev.dB / 2 +
                          (dev.dB * (v % res.op.Ts)) / (res.op.D * res.op.Ts)
                        : dev.dB / 2 -
                          (dev.dB * ((v % res.op.Ts) - res.op.D * res.op.Ts)) /
                            ((1 - res.op.D) * res.op.Ts)) * 1000;
                })
              : w.i_p.map((v: number) => ((l * v) / n / dev.Ae) * 1000),
          label: "磁链参考 B",
        },
      ],
      "磁通密度参考波形",
      "mT",
    );
  }
  if (kind === "clamp")
    return lineChart([series("v_sw", "Q1 Vds")], "MOS 电压与钳位包络", "V");
  if (kind === "loop") {
    if (!res.loop) throw Error(res.loop_error || "环路未完成");
    const loop = res.loop;
    const magnitude = lineChart(
      [0, 1, 2].map((j) => ({
        x: loop.f,
        y: loop.gains.map(
          (v: any) => 20 * Math.log10(Math.max(Math.hypot(...v[j]), 1e-300)),
        ),
        label: ["对象 Gvc", "补偿器 Gc", "开环 T"][j],
      })),
      "环路幅频响应",
      "dB",
      true,
    );
    const phase = lineChart(
      [0, 1, 2].map((j) => ({
        x: loop.f,
        y: loop.phases[j],
        label: ["对象 Gvc", "补偿器 Gc", "开环 T"][j],
      })),
      "环路相频响应",
      "deg",
      true,
    );
    return `<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="1080" viewBox="0 0 1200 1080">${magnitude.replace("<svg ", '<svg x="0" y="0" ')}${phase.replace("<svg ", '<svg x="0" y="540" ')}</svg>`;
  }
  if (kind === "loop_phase") {
    if (!res.loop) throw Error(res.loop_error || "环路未完成");
    return lineChart(
      [0, 1, 2].map((j) => ({
        x: res.loop.f,
        y: res.loop.phases[j],
        label: ["对象 Gvc", "补偿器 Gc", "开环 T"][j],
      })),
      "环路相频响应",
      "deg",
      true,
    );
  }
  if (kind === "switching" || kind === "switching_real") {
    const s = res.semi.switch,
      g = s.gate,
      ds = [s.t1, s.t2, s.t3, s.t4, s.t5, s.t6, s.t7, s.t8];
    const hold =
      kind === "switching_real"
        ? Math.max(
            res.op.D * res.op.Ts - ds.slice(0, 4).reduce((a, b) => a + b, 0),
            1e-12,
          )
        : Math.max(ds.reduce((a, b) => a + b, 0) * 0.15, 1e-9);
    const boundaries = [0];
    for (const [i, d] of ds.entries())
      boundaries.push(boundaries.at(-1)! + d + (i === 4 ? hold : 0));
    const vs = res.op.clamp?.V_plateau ?? res.op.V_sw_max,
      lowOn = p.Rds_on * g.I_on,
      lowOff = p.Rds_on * g.I_off;
    const x = [
      0,
      ...boundaries.slice(1, 5),
      boundaries[4] + hold,
      ...boundaries.slice(5),
    ];
    const vg = [
      0,
      p.Vth,
      g.Vgp_on,
      g.Vgp_on,
      p.Vgs,
      p.Vgs,
      g.Vgp_off,
      g.Vgp_off,
      p.Vth,
      0,
    ];
    const vd = [vs, vs, vs, lowOn, lowOn, lowOff, lowOff, vs, vs, vs];
    const read = (values: number[], v: number) => {
      let j = x.findIndex((z) => z >= v);
      if (j < 0) return values.at(-1)!;
      j = Math.max(j, 1);
      return (
        values[j - 1] +
        ((values[j] - values[j - 1]) * (v - x[j - 1])) / (x[j] - x[j - 1] || 1)
      );
    };
    const t = Array.from({ length: 600 }, (_, i) => (i * x.at(-1)!) / 599);
    return lineChart(
      [
        {
          x: t.map((v) => v * 1e6),
          y: t.map((v) => read(vg, v)),
          label: "Vgs / V",
        },
        {
          x: t.map((v) => v * 1e6),
          y: t.map((v) => read(vd, v)),
          label: "Vds / V",
        },
      ],
      kind === "switching_real"
        ? "MOS t1–t8 · 实际导通间隔（边沿可能较窄）"
        : "MOS t1–t8 · 边沿展开（中间导通段缩短）",
      "V",
    );
  }
  throw Error("该图表模块尚未完成 TypeScript 迁移：" + kind);
}
