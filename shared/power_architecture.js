/* Editable PCS power tree. Geometry and gestures are independent of the calculator. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  // Bundlers can provide a CommonJS shim inside a browser. Still publish the
  // browser API so the standalone shell and the classic PCS script share it.
  if (typeof window !== "undefined") root.PCSAuxGraph = api;
})(typeof globalThis === "undefined" ? this : globalThis, function () {
  "use strict";
  const WIDTH = 288,
    LIMIT = 10000;
  const esc = (value) =>
    String(value ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
  const copy = (value) => JSON.parse(JSON.stringify(value));
  const keyOf = (kind, id) => kind + ":" + id;
  const disconnected = () => ({ kind: "none", id: "", output: 1 });
  const collections = {bus:"sources",unit:"units",junction:"junctions",load:"loads"};
  const network = p => Array.isArray(p.connections);
  const allNodes = p => Object.entries(collections).flatMap(([kind,key])=>(p[key]||[]).map(data=>({kind,data})));
  const defaultRails = (unit) =>
    unit.rails?.length
      ? unit.rails
      : unit.spec.outputs?.length
        ? unit.spec.outputs
        : [{ V_out: unit.spec.V_out, P_out: unit.spec.P_out }];
  const format = (value) =>
    Number.isFinite(Number(value))
      ? Number(Number(value).toPrecision(4)).toString()
      : "待配置";
  const cut = (value, length = 18) =>
    String(value).length > length
      ? String(value).slice(0, length - 1) + "…"
      : String(value);

  function connectionError(project, targetId, source, rails = defaultRails) {
    if(network(project)) {
      const target=allNodes(project).find(n=>n.data.id===targetId);
      const parent=allNodes(project).find(n=>n.data.id===source.id&&n.kind===source.kind);
      if(!target||target.kind==='bus')return '下游应为电源模块、OR汇流节点或负载';
      if(!parent||parent.kind==='load')return '上游供电端口不存在';
      const count=parent.kind==='unit'?rails(parent.data).length:1;
      if(!Number.isInteger(source.output)||source.output<1||source.output>count)return '上游 OUT 端口不存在';
      if(project.connections.some(e=>e.target===targetId&&e.source.kind===source.kind&&e.source.id===source.id&&e.source.output===source.output))return '此供电连接已存在';
      const stack=[targetId],seen=new Set();
      while(stack.length){const id=stack.pop();if(id===source.id)return '此连接会形成循环供电，不能连接';if(seen.has(id))continue;seen.add(id);stack.push(...project.connections.filter(e=>e.source.id===id).map(e=>e.target));}
      return '';
    }
    const target = project.units.find((u) => u.id === targetId);
    if (!target) return "目标辅源不存在";
    if (source.kind === "none") return "";
    if (source.kind === "bus")
      return project.sources.some((b) => b.id === source.id)
        ? (source.output ?? 1) === 1
          ? ""
          : "外部输入源只有 DC 端口"
        : "输入源不存在";
    if (source.kind !== "unit") return "请选择外部输入源或辅源输出端口";
    const parent = project.units.find((u) => u.id === source.id);
    if (!parent) return "上游辅源不存在";
    if (
      !Number.isInteger(source.output) ||
      source.output < 1 ||
      source.output > rails(parent).length
    )
      return "上游 OUT 端口不存在";
    const visited = new Set([targetId]);
    let node = parent;
    while (node) {
      if (visited.has(node.id)) return "此连接会形成循环供电，不能连接";
      visited.add(node.id);
      node =
        node.source.kind === "unit"
          ? project.units.find((u) => u.id === node.source.id)
          : null;
    }
    return "";
  }

  function nodesFor(project, rails = defaultRails) {
    if(network(project))return allNodes(project).map(({kind,data})=>({kind,data,key:keyOf(kind,data.id),height:kind==='unit'?158+Math.max(0,rails(data).length-1)*26:156,ports:kind==='load'?0:kind==='unit'?rails(data).length:1}));
    return [
      ...project.sources.map((data) => ({
        kind: "bus",
        data,
        key: keyOf("bus", data.id),
        height: 156,
        ports: 1,
      })),
      ...project.units.map((data) => ({
        kind: "unit",
        data,
        key: keyOf("unit", data.id),
        height: 158 + Math.max(0, rails(data).length - 1) * 26,
        ports: rails(data).length,
      })),
    ];
  }
  function arranged(project, rails = defaultRails) {
    const nodes = nodesFor(project, rails),
      byId = new Map(allNodes(project).map(n => [n.data.id, n.data]));
    const depth = (unit, visited = new Set()) => {
      if (visited.has(unit.id)) return 1;
      visited.add(unit.id);
      if(network(project))return Math.min(24,Math.max(0,...project.connections.filter(e=>e.target===unit.id).map(e=>depth(byId.get(e.source.id),new Set(visited))+1)));
      const parent =
        unit.source.kind === "unit" ? byId.get(unit.source.id) : null;
      return parent ? Math.min(24, depth(parent, visited) + 1) : 1;
    };
    const bottoms = new Map(),
      positions = {};
    for (const node of nodes) {
      const column = node.kind === "bus" ? 0 : depth(node.data),
        y = bottoms.get(column) || 36;
      positions[node.key] = { x: 36 + column * 382, y };
      bottoms.set(column, y + node.height + 48);
    }
    return positions;
  }
  function layout(project, rails = defaultRails) {
    const nodes = nodesFor(project, rails),
      defaults = arranged(project, rails),
      saved = project.layout?.nodes || {};
    const occupied = nodes
      .filter((n) => saved[n.key])
      .map((n) => ({ ...n, ...saved[n.key] }));
    for (const node of nodes) {
      let point = saved[node.key];
      if (!point || !Number.isFinite(point.x) || !Number.isFinite(point.y)) {
        point = { ...defaults[node.key] };
        while (
          occupied.some(
            (n) =>
              point.x < n.x + WIDTH + 28 &&
              point.x + WIDTH + 28 > n.x &&
              point.y < n.y + n.height + 28 &&
              point.y + node.height + 28 > n.y,
          )
        )
          point.y += node.height + 48;
        occupied.push({ ...node, ...point });
      }
      node.x = Math.max(24, Math.min(LIMIT, point.x));
      node.y = Math.max(24, Math.min(LIMIT, point.y));
    }
    return nodes;
  }
  function saveLayout(project, rails = defaultRails) {
    project.layout = {
      ...(network(project)?{diodes:copy(project.layout?.diodes||{})}:{}),
      nodes: Object.fromEntries(
        layout(project, rails).map((n) => [n.key, { x: n.x, y: n.y }]),
      ),
    };
  }
  function autoArrange(project, rails = defaultRails) {
    project.layout = { nodes: arranged(project, rails) };
  }
  function removeNode(project, key) {
    if(network(project)) {
      const [kind,id]=key.split(':'),list=project[collections[kind]],index=list?.findIndex(n=>n.id===id);
      if(index==null||index<0)return null;
      const record={kind,id,index,node:copy(list[index]),position:copy(project.layout?.nodes?.[key]||null),connections:copy(project.connections.filter(e=>e.target===id||e.source.id===id))};
      const removed=new Set(record.connections.map(e=>e.id));record.remainingInputs=Object.fromEntries(record.connections.map(e=>[e.target,project.connections.filter(v=>v.target===e.target&&!removed.has(v.id)).map(v=>v.id).sort().join('|')]));
      record.diodes=Object.fromEntries(Object.entries(project.layout?.diodes||{}).filter(([key])=>removed.has(key)));
      for(const key of removed)if(project.layout?.diodes)delete project.layout.diodes[key];
      list.splice(index,1);project.connections=project.connections.filter(e=>e.target!==id&&e.source.id!==id);
      if(project.layout?.nodes)delete project.layout.nodes[key];
      if(project.activeUnit===id)project.activeUnit=project.units[0]?.id||'';
      return record;
    }
    const [kind, id] = key.split(":"),
      list = kind === "bus" ? project.sources : project.units;
    const index = list.findIndex((n) => n.id === id);
    if (index < 0) return null;
    const record = {
      kind,
      id,
      index,
      node: list[index],
      position: copy(project.layout?.nodes?.[key] || null),
      activeUnit: project.activeUnit,
      children: [],
    };
    for (const unit of project.units)
      if (unit.source.kind === kind && unit.source.id === id) {
        record.children.push({ id: unit.id, source: copy(unit.source) });
        unit.source = disconnected();
        unit.stale = true;
      }
    list.splice(index, 1);
    if (project.layout?.nodes) delete project.layout.nodes[key];
    if (project.activeUnit === id)
      project.activeUnit = project.units[0]?.id || "";
    return record;
  }
  function restoreNode(project, record) {
    if(network(project)) {
      if(allNodes(project).some(n=>n.data.id===record.id))return false;
      const list=project[collections[record.kind]];
      list.splice(Math.min(record.index,list.length),0,copy(record.node));
      if(record.position){project.layout||={nodes:{}};project.layout.nodes[keyOf(record.kind,record.id)]=copy(record.position);}
      const unchanged=new Set(Object.entries(record.remainingInputs||{}).filter(([id,ids])=>project.connections.filter(e=>e.target===id).map(e=>e.id).sort().join('|')===ids).map(([id])=>id));
      for(const e of record.connections){
        if(e.target!==record.id&&!unchanged.has(e.target))continue;
        if(!project.connections.some(v=>v.id===e.id)&&!connectionError(project,e.target,e.source)){
          project.connections.push(copy(e));
          if(record.diodes?.[e.id]){project.layout.diodes||={};project.layout.diodes[e.id]=copy(record.diodes[e.id]);}
        }
      }
      return true;
    }
    const list = record.kind === "bus" ? project.sources : project.units;
    if (
      list.length >= 24 ||
      [...project.sources, ...project.units].some((n) => n.id === record.id)
    )
      return false;
    list.splice(Math.min(record.index, list.length), 0, record.node);
    if (
      record.kind === "unit" &&
      connectionError(project, record.node.id, record.node.source)
    )
      record.node.source = disconnected();
    if (record.position) {
      project.layout ||= { nodes: {} };
      project.layout.nodes[keyOf(record.kind, record.id)] = record.position;
    }
    for (const child of record.children) {
      const unit = project.units.find((u) => u.id === child.id);
      if (
        unit?.source.kind === "none" &&
        !connectionError(project, unit.id, child.source)
      )
        unit.source = child.source;
    }
    if (record.activeUnit === record.id) project.activeUnit = record.id;
    return true;
  }
  const inputPoint = (node) => ({ x: node.x, y: node.y + 94 });
  const outputPoint = (node, index = 1) => ({
    x: node.x + WIDTH,
    y: node.y + (node.kind === "bus" ? 102 : 119 + (index - 1) * 26),
  });
  function pathBetween(a, b) {
    const curve = Math.max(b.x >= a.x ? 12 : 60, Math.abs(b.x - a.x) * 0.45);
    return `M${a.x} ${a.y}C${a.x + curve} ${a.y},${b.x - curve} ${b.y},${b.x} ${b.y}`;
  }
  function diodePoint(edge,project,positions=project.layout?.diodes||{}) {
    const a=outputPoint(edge.source,edge.port),b=inputPoint(edge.target),saved=positions[edge.id];
    return saved&&Number.isFinite(saved.x)&&Number.isFinite(saved.y)?{x:saved.x,y:saved.y}:{x:(a.x+b.x)/2,y:(a.y+b.y)/2};
  }
  function connectionPath(edge,project,positions) {
    const a=outputPoint(edge.source,edge.port),b=inputPoint(edge.target);
    if(edge.mode!=='diode')return pathBetween(a,{x:b.x-9,y:b.y});
    const p=diodePoint(edge,project,positions);
    return pathBetween(a,{x:p.x-44,y:p.y})+' '+pathBetween({x:p.x+44,y:p.y},{x:b.x-9,y:b.y});
  }
  function edgesFor(nodes, project) {
    if(network(project))return project.connections.flatMap(e=>{const source=nodes.find(n=>n.kind===e.source.kind&&n.data.id===e.source.id),target=nodes.find(n=>n.data.id===e.target);return source&&target?[{source,target,port:e.source.output,id:e.id,mode:e.mode,vf:e.vf,enabled:e.enabled}]:[];});
    return nodes
      .filter((n) => n.kind === "unit")
      .flatMap((target) => {
        const source = nodes.find(
          (n) =>
            n.kind === target.data.source.kind &&
            n.data.id === target.data.source.id,
        );
        const port = target.data.source.output || 1;
        return source && port <= source.ports ? [{ source, target, port, id:target.data.id }] : [];
      });
  }
  function bounds(nodes,diodes={}) {
    return {
      width: Math.max(1050, ...nodes.map((n) => n.x + WIDTH + 65),...Object.values(diodes).map(p=>p.x+85)),
      height: Math.max(440, ...nodes.map((n) => n.y + n.height + 45),...Object.values(diodes).map(p=>p.y+65)),
    };
  }
  function svg(project, options = {}) {
    const rails = options.rails || defaultRails,
      nodes = options.nodes || layout(project, rails),
      interactive = !!options.interactive;
    const diodes=options.diodes||project.layout?.diodes||{},size = bounds(nodes,diodes),
      selected = options.selected,
      font = "Segoe UI,Microsoft YaHei,Arial,sans-serif";
    const text = (x, y, value, fill = "#152238", size = 13, extra = "") =>
      `<text x="${x}" y="${y}" fill="${fill}" font-size="${size}" ${extra}>${esc(value)}</text>`;
    const links = edgesFor(nodes, project)
      .map((edge) => {
        const {source,target,port,id,mode,vf,enabled}=edge;
        const a = outputPoint(source, port),
          b = inputPoint(target),
          active = selected?.kind === "edge" && selected.id === id;
        const d = connectionPath(edge,project,diodes),p=mode==='diode'?diodePoint(edge,project,diodes):null;
        return `<g ${interactive ? `data-edge="${esc(id)}" role="button" tabindex="0" aria-label="连接 ${esc(source.data.id)} ${source.kind === "unit" ? "OUT" + port : "DC"} 到 ${esc(target.data.id)}"` : ""}>
        ${interactive ? `<path d="${d}" fill="none" stroke="transparent" stroke-width="16" pointer-events="stroke"/>` : ""}
        <path data-link-path="${esc(id)}" d="${d}" fill="none" stroke="${active ? "#d57d16" : enabled===false?'#a4adbb':"#2376e5"}" stroke-width="${active ? 3 : 2}" ${enabled===false?'stroke-dasharray="6 4"':''} marker-end="url(#aux-arrow)" pointer-events="none"/>
        ${mode==='diode'?`<g data-diode-symbol="" ${interactive?`data-diode-drag="${esc(id)}" role="button" tabindex="0" aria-label="拖动竞争二极管 ${esc(id)}"`:''} transform="translate(${p.x} ${p.y})"><title>${esc(id)} · 拖动调整位置，选中修改压降</title><rect x="-44" y="-25" width="88" height="50" rx="10" fill="#ffffff" stroke="${active?'#d58b26':'#afc1dc'}" stroke-width="${active?2.5:1.2}"/><text x="0" y="-12" text-anchor="middle" fill="#677d98" font-size="8.5" pointer-events="none">${esc(id)}</text><path d="M-21 -5L-8 2L-21 9Z M-6 -7V11" fill="#e8efff" stroke="#3563b3" stroke-width="1.8" pointer-events="none"/><text x="17" y="6" text-anchor="middle" fill="#233f63" font-size="11" font-weight="600" pointer-events="none">${format(vf)}V</text><text x="0" y="20" text-anchor="middle" fill="#8d9cb0" font-size="7.5" pointer-events="none">${enabled===false?'支路停用':'OR-ING DIODE'}</text></g>`:text((a.x+b.x)/2,(a.y+b.y)/2-14,source.kind==='unit'?'OUT'+port:'DC','#8293a9',11,`data-link-label="${esc(id)}" text-anchor="middle" pointer-events="none"`)}</g>`;
      })
      .join("");
    const cards = nodes
      .map((node) => {
        const d = node.data,
          dark = node.kind === "bus",
          active = selected?.kind === node.kind && selected.id === d.id;
        const accent={bus:'#1da6bc',unit:'#3979e6',junction:'#8664ce',load:'#149b83'}[node.kind];
        const fg = dark ? "#ffffff" : "#152238",
          muted = dark ? "#bdd0e1" : "#68788f",
          label = dark ? "INPUT SOURCE" : node.kind==='load'?'LOAD':node.kind==='junction'?'DIODE OR BUS':"CONVERTER";
        let controls = "",
          ports = "";
        if (interactive)
          controls = `<g data-node-delete="${esc(node.key)}" role="button" tabindex="0" aria-label="删除 ${esc(d.id)}"><rect x="252" y="10" width="26" height="26" rx="6" fill="${dark ? "#29394d" : "#fff0f2"}"/><path d="M261 19l8 8m0-8l-8 8" stroke="${dark ? "#d9e5f5" : "#b44b60"}" stroke-width="1.7" pointer-events="none"/><title>删除节点；可撤销删除</title></g>`;
        if (node.kind !== "bus") {
          const count=network(project)?project.connections.filter(e=>e.target===d.id&&e.enabled).length:(d.source?.kind==='none'?0:1);
          ports += `<circle cx="0" cy="94" r="7" fill="${!count ? "#fff4df" : "#fff"}" stroke="${!count ? "#d29129" : "#2376e5"}" stroke-width="2"/>${text(14, 98, count>1?'IN · 二极管 OR ×'+count:'IN', muted, 11)}`;
          if (interactive)
            ports += `<circle data-port-input="${esc(d.id)}" cx="0" cy="94" r="15" fill="transparent" role="button" tabindex="0" aria-label="${esc(d.id)} 输入 IN"/>`;
          ports += text(
            18,
            node.height - 14,
            node.kind==='unit'?(interactive ? "进入计算 →" : "独立电源计算"):node.kind==='load'?'终端负载 · 可自定义名称':'二极管竞争供电 · 可分配多个后级',
            "#2376e5",
            12,
            interactive && node.kind==='unit'
              ? `data-node-open="${esc(d.id)}" role="button" tabindex="0" aria-label="计算 ${esc(d.id)}"`
              : "",
          );
        }
        for (let port = 1; port <= node.ports; port++) {
          const y = node.kind === "bus" ? 102 : 119 + (port - 1) * 26,
            rail = node.kind === "unit" ? rails(d)[port - 1] : null;
          ports += `<circle cx="${WIDTH}" cy="${y}" r="7" fill="${dark ? "#79dbea" : "#fff"}" stroke="${dark ? "#79dbea" : "#2376e5"}" stroke-width="2"/>`;
          if (interactive)
            ports += `<circle data-port-output="${esc(node.key)}" data-output="${port}" cx="${WIDTH}" cy="${y}" r="15" fill="transparent" role="button" tabindex="0" aria-label="${esc(d.id)} ${dark ? "DC" : "OUT" + port} 输出"/>`;
          ports += text(
            WIDTH - 18,
            y + 4,
            node.kind==='junction'?'OR BUS 输出':dark
              ? "DC 输出"
              : `OUT${port}  ${format(rail.V_out)}V / ${format(rail.P_out)}W`,
            dark ? "#79dbea" : "#446a94",
            12,
            'text-anchor="end" pointer-events="none"',
          );
        }
        const watts =
          node.kind === "unit"
            ? rails(d).reduce((s, r) => s + (Number(r.P_out) || 0), 0)
            : node.kind==='load'?d.power:d.capacity;
        return `<g transform="translate(${node.x} ${node.y})" ${interactive ? `data-graph-node="${esc(node.key)}" role="group" tabindex="0" aria-label="${esc(d.id + " " + d.name)}"` : ""}>
        <rect width="${WIDTH}" height="${node.height}" rx="15" fill="${dark ? "#10243b" : "#ffffff"}" stroke="${active ? accent : dark ? "#10243b" : "#dce5f0"}" stroke-width="${active ? 2.5 : 1.2}"/>
        <rect x="0" y="18" width="4" height="32" rx="2" fill="${accent}"/>
        ${text(18, 29, d.id + " " + label, dark ? "#79dbea" : "#2376e5", 11, 'font-weight="700" pointer-events="none"')}
        ${text(18, 57, cut(d.name), fg, 18, 'font-weight="700" pointer-events="none"')}
        ${text(18, 80, options.describe?.(d) ?? (dark ? `${format(d.min)}–${format(d.max)}V · ${format(watts)}W` : node.kind==='load'?`${format(watts)}W · ${d.max?format(d.min)+'–'+format(d.max)+'V':'电压范围未限定'}`:node.kind==='junction'?`二极管 OR · 容量 ${format(watts)}W`:(options.names?.[d.spec.topology] || d.spec.topology) + " · " + format(watts) + "W"), muted, 12, 'pointer-events="none"')}
        ${d.enabled===false?text(180,57,'停用','#b67726',12):''}
        ${options.badge?.(d)?text(140,node.height-14,options.badge(d),muted,11):""}${dark ? text(18, 137, "外部输入范围与分配容量", muted, 12, 'pointer-events="none"') : ""}${ports}${controls}</g>`;
      })
      .join("");
    const empty = !nodes.length
      ? text(
          55,
          90,
          "画布为空，点击“增加输入源”或“新增辅源单元”开始设计。",
          "#68788f",
          17,
        )
      : "";
    const pixelScale = interactive
      ? 1
      : Math.min(1, 1800 / size.width, 1400 / size.height);
    return `<svg class="aux-power-tree" xmlns="http://www.w3.org/2000/svg" width="${Math.round(size.width * pixelScale)}" height="${Math.round(size.height * pixelScale)}" viewBox="0 0 ${size.width} ${size.height}" font-family="${font}" role="img" aria-label="辅源供电架构"><defs><pattern id="aux-grid" width="24" height="24" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r=".8" fill="#ced9e8"/></pattern><marker id="aux-arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0L7,3L0,6" fill="#3979e6"/></marker></defs><rect width="100%" height="100%" fill="${interactive?'url(#aux-grid)':'#ffffff'}"/>${links}${cards}${empty}${interactive ? '<path data-pending-link fill="none" stroke="#20aebf" stroke-width="2.5" stroke-dasharray="6 4" pointer-events="none"/>' : ""}</svg>`;
  }

  function mount(container, options) {
    const project = options.project,
      rails = options.rails || defaultRails;
    let nodes = layout(project, rails),
      selected = options.selected || null,
      connecting = null,
      gesture = null,
      frame = 0,
      nextPoint = null,
      disposed = false;
    const diodePositions=copy(project.layout?.diodes||{});
    let edgeData=[],edgeElements=new Map(),nodeElements=new Map(),incident=new Map();
    container.tabIndex = 0;
    const element = () => container.querySelector("svg");
    const point = (event) => {
      const svg=element(),rect=svg.getBoundingClientRect(),box=svg.viewBox.baseVal;
      return {x:(event.clientX-rect.left)*box.width/rect.width,y:(event.clientY-rect.top)*box.height/rect.height};
    };
    function paint() {
      if (!disposed) {
        const zoom=element()?.style.zoom;
        container.innerHTML = svg(project, {
          ...options,
          nodes,
          diodes:diodePositions,
          interactive: true,
          selected,
        });
        if(zoom)element().style.zoom=zoom;
        edgeData=edgesFor(nodes,project);incident=new Map();
        edgeElements=new Map([...container.querySelectorAll('[data-edge]')].map(g=>[g.dataset.edge,{paths:[...g.querySelectorAll(':scope > path')],label:g.querySelector('[data-link-label]'),diode:g.querySelector('[data-diode-symbol]')} ]));
        nodeElements=new Map([...container.querySelectorAll('[data-graph-node]')].map(g=>[g.dataset.graphNode,g]));
        for(const e of edgeData)for(const key of [e.source.key,e.target.key]){if(!incident.has(key))incident.set(key,[]);incident.get(key).push(e);}
      }
    }
    function select(value) {
      selected = value;
      paint();
      options.onSelect?.(value);
    }
    function setConnection(source) {
      connecting = source;
      options.onConnection?.(source);
      paint();
    }
    function cancelConnection() {
      connecting = null;
      options.onConnection?.(null);
      element()?.querySelector("[data-pending-link]")?.setAttribute("d", "");
    }
    function connect(target) {
      if (!connecting) return;
      const error = connectionError(project, target, connecting, rails);
      if (error) {
        options.onError?.(error);
        return;
      }
      const source = { ...connecting };
      cancelConnection();
      options.onConnect(target, source);
    }
    function updateLinks(edges=edgeData) {
      for (const edge of edges) {
        const a = outputPoint(edge.source, edge.port),
          b = inputPoint(edge.target);
        const group=edgeElements.get(edge.id);
        group?.paths.forEach((p) =>
            p.setAttribute("d", connectionPath(edge,project,diodePositions)),
          );
        const label = group?.label;
        if (label) {
          label.setAttribute("x", (a.x + b.x) / 2);
          label.setAttribute("y", (a.y + b.y) / 2 - 14);
        }
        const dp=diodePoint(edge,project,diodePositions);
        group?.diode?.setAttribute('transform',`translate(${dp.x} ${dp.y})`);
      }
    }
    function updateBounds(){
      const size = bounds(nodes,diodePositions),
        svg = element();
      svg.setAttribute("width", size.width);
      svg.setAttribute("height", size.height);
      svg.setAttribute("viewBox", `0 0 ${size.width} ${size.height}`);
    }
    function flush() {
      frame = 0;
      if (!nextPoint || !gesture) return;
      if (gesture.kind === "move") {
        const n = gesture.node;
        n.x = Math.round(
          Math.max(24, Math.min(LIMIT, nextPoint.x - gesture.offset.x)),
        );
        n.y = Math.round(
          Math.max(24, Math.min(LIMIT, nextPoint.y - gesture.offset.y)),
        );
        nodeElements.get(n.key)?.setAttribute("transform", `translate(${n.x} ${n.y})`);
        updateLinks(incident.get(n.key)||[]);
      } else if(gesture.kind==='diode') {
        diodePositions[gesture.id]={x:Math.round(Math.max(48,Math.min(LIMIT,nextPoint.x-gesture.offset.x))),y:Math.round(Math.max(32,Math.min(LIMIT,nextPoint.y-gesture.offset.y)))};
        updateLinks(edgeData.filter(e=>e.id===gesture.id));
      }
      nextPoint = null;
    }
    function preview(event) {
      if (!connecting) return;
      const source = nodes.find(
        (n) => n.key === keyOf(connecting.kind, connecting.id),
      );
      if (!source) return;
      element()
        .querySelector("[data-pending-link]")
        .setAttribute(
          "d",
          pathBetween(outputPoint(source, connecting.output), point(event)),
        );
    }
    function down(event) {
      if(event.button===1){gesture={kind:'pan',x:event.clientX,y:event.clientY,left:container.scrollLeft,top:container.scrollTop};container.classList.add('is-panning');container.setPointerCapture(event.pointerId);event.preventDefault();return;}
      if (event.button !== 0) return;
      const target = event.target,
        remove = target.closest("[data-node-delete]"),
        open = target.closest("[data-node-open]"),
        out = target.closest("[data-port-output]"),
        input = target.closest("[data-port-input]"),
        diode = target.closest('[data-diode-drag]'),
        edge = target.closest("[data-edge]"),
        nodeElement = target.closest("[data-graph-node]");
      if (remove) {
        event.preventDefault();
        options.onDelete(remove.dataset.nodeDelete);
        return;
      }
      if (open) {
        event.preventDefault();
        options.onOpen(open.dataset.nodeOpen);
        return;
      }
      if (input && connecting) {
        event.preventDefault();
        connect(input.dataset.portInput);
        return;
      }
      if (out) {
        const [kind, id] = out.dataset.portOutput.split(":");
        setConnection({ kind, id, output: Number(out.dataset.output) });
        container.focus({ preventScroll: true });
        gesture = {
          kind: "connect",
          x: event.clientX,
          y: event.clientY,
          moved: false,
        };
        event.preventDefault();
        container.setPointerCapture(event.pointerId);
        preview(event);
        return;
      }
      if(diode){
        const id=diode.dataset.diodeDrag,edgeData=edgesFor(nodes,project).find(e=>e.id===id),p=point(event),original=diodePoint(edgeData,project,diodePositions);
        cancelConnection();select({kind:'edge',id});
        gesture={kind:'diode',id,original,wasPlaced:!!diodePositions[id],offset:{x:p.x-original.x,y:p.y-original.y}};
        container.focus({preventScroll:true});container.setPointerCapture(event.pointerId);event.preventDefault();return;
      }
      if (edge) {
        cancelConnection();
        select({ kind: "edge", id: edge.dataset.edge });
        event.preventDefault();
        container.focus({ preventScroll: true });
        return;
      }
      if (nodeElement) {
        const key = nodeElement.dataset.graphNode,
          n = nodes.find((n) => n.key === key),
          p = point(event);
        cancelConnection();
        select({ kind: n.kind, id: n.data.id });
        gesture = {
          kind: "move",
          node: n,
          offset: { x: p.x - n.x, y: p.y - n.y },
          original: { x: n.x, y: n.y },
        };
        container.focus({ preventScroll: true });
        container.setPointerCapture(event.pointerId);
        event.preventDefault();
        return;
      }
      cancelConnection();
      select(null);
      gesture={kind:'pan',x:event.clientX,y:event.clientY,left:container.scrollLeft,top:container.scrollTop};
      container.classList.add('is-panning');container.setPointerCapture(event.pointerId);event.preventDefault();
      container.focus({ preventScroll: true });
    }
    function move(event) {
      if(gesture?.kind==='pan'){container.scrollLeft=gesture.left-(event.clientX-gesture.x);container.scrollTop=gesture.top-(event.clientY-gesture.y);return;}
      if (gesture?.kind === "move"||gesture?.kind==='diode') {
        nextPoint = point(event);
        if (!frame) frame = requestAnimationFrame(flush);
      }
      if (
        gesture?.kind === "connect" &&
        Math.hypot(event.clientX - gesture.x, event.clientY - gesture.y) > 5
      )
        gesture.moved = true;
      preview(event);
    }
    function up(event) {
      if (!gesture) return;
      if (frame) {
        cancelAnimationFrame(frame);
        flush();
      }
      const completed = gesture;
      gesture = null;
      if (container.hasPointerCapture(event.pointerId))
        container.releasePointerCapture(event.pointerId);
      container.classList.remove('is-panning');
      if(completed.kind==='pan')return;
      updateBounds();
      if (completed.kind === "move") {
        if (
          completed.node.x !== completed.original.x ||
          completed.node.y !== completed.original.y
        )
          options.onMove(completed.node.key, {
            x: completed.node.x,
            y: completed.node.y,
          });
      } else if(completed.kind==='diode') {
        const p=diodePositions[completed.id];
        if(p&&(p.x!==completed.original.x||p.y!==completed.original.y)){
          if(options.onDiodeMove)options.onDiodeMove(completed.id,copy(p));
          else {project.layout||={nodes:{}};project.layout.diodes||={};project.layout.diodes[completed.id]=copy(p);}
        }
      } else {
        const input = document
          .elementFromPoint(event.clientX, event.clientY)
          ?.closest("[data-port-input]");
        if (input && container.contains(input))
          connect(input.dataset.portInput);
        else if (completed.moved) cancelConnection();
      }
    }
    function cancel() {
      if (frame) cancelAnimationFrame(frame);
      frame = 0;
      container.classList.remove('is-panning');
      nextPoint = null;
      if (gesture?.kind === "move")
        Object.assign(gesture.node, gesture.original);
      if(gesture?.kind==='diode'){
        if(gesture.wasPlaced)diodePositions[gesture.id]=gesture.original;
        else delete diodePositions[gesture.id];
      }
      gesture = null;
      cancelConnection();
      paint();
    }
    function key(event) {
      const target = event.target;
      if (event.key === "Escape") {
        cancel();
        event.preventDefault();
        return;
      }
      if (event.key === "Delete" || event.key === "Backspace") {
        const edge = target.closest("[data-edge]"),
          node = target.closest("[data-graph-node]");
        if (edge) options.onDisconnect(edge.dataset.edge);
        else if (node) options.onDelete(node.dataset.graphNode);
        else if (selected?.kind === "edge") options.onDisconnect(selected.id);
        else if (selected) options.onDelete(keyOf(selected.kind, selected.id));
        event.preventDefault();
        return;
      }
      if (event.key !== "Enter" && event.key !== " ") return;
      const remove = target.closest("[data-node-delete]"),
        open = target.closest("[data-node-open]"),
        out = target.closest("[data-port-output]"),
        input = target.closest("[data-port-input]");
      if (remove) options.onDelete(remove.dataset.nodeDelete);
      else if (open) options.onOpen(open.dataset.nodeOpen);
      else if (out) {
        const [kind, id] = out.dataset.portOutput.split(":");
        setConnection({ kind, id, output: Number(out.dataset.output) });
        container.focus({ preventScroll: true });
      } else if (input && connecting) connect(input.dataset.portInput);
      else if (target.closest("[data-edge]")) {
        select({
          kind: "edge",
          id: target.closest("[data-edge]").dataset.edge,
        });
        container.focus({ preventScroll: true });
      } else if (
        target
          .closest("[data-graph-node]")
          ?.dataset.graphNode.startsWith("unit:")
      )
        options.onOpen(
          target.closest("[data-graph-node]").dataset.graphNode.slice(5),
        );
      else if (selected?.kind === "unit") options.onOpen(selected.id);
      event.preventDefault();
    }
    function double(event) {
      if (
        event.target.closest(
          "[data-port-output],[data-port-input],[data-node-delete]",
        )
      )
        return;
      const node = event.target.closest("[data-graph-node]");
      if (node?.dataset.graphNode.startsWith("unit:"))
        options.onOpen(node.dataset.graphNode.slice(5));
    }
    const events = {
      pointerdown: down,
      pointermove: move,
      pointerup: up,
      pointercancel: cancel,
      keydown: key,
      dblclick: double,
    };
    for (const [name, fn] of Object.entries(events))
      container.addEventListener(name, fn);
    paint();
    return {
      refresh: paint,
      destroy() {
        disposed = true;
        container.classList.remove('is-panning');
        if (frame) cancelAnimationFrame(frame);
        for (const [name, fn] of Object.entries(events))
          container.removeEventListener(name, fn);
      },
    };
  }
  return {
    layout,
    saveLayout,
    autoArrange,
    svg,
    mount,
    connectionError,
    removeNode,
    restoreNode,
    disconnected,
    keyOf,
  };
});
