"""Native-vector power schematics and the matching component/parameter map.

The drawings are engineering reference schematics, not routable CAD designs.
All optional symbols and table rows are driven by the same component registry.
"""
import math

import numpy as np
from matplotlib.patches import Polygon
from matplotlib.patches import Circle

from power_stage import fmt_eng, TOPOLOGIES


def topology_components(p, solved=None):
    """Ordered rows: designator, purpose, current values and source keys."""
    if p.get('outputs') or p.get('feedback_mode')=='PSR-MP6005':
        return isolated_components(p,solved)
    topo = p['topology']
    if topo not in TOPOLOGIES:
        raise ValueError('Unsupported schematic topology: '+str(topo))
    rows = []

    def add(ref, role, fields=(), text=''):
        values = '; '.join(f'{key}={fmt_eng(p[key], unit)}' for key, unit in fields)
        rows.append(dict(ref=ref, role=role, values=text or values,
                         keys=tuple(key for key, _ in fields)))

    add('J1', '输入端口', [('V_in', 'V')])
    add('J2', '输出端口', [('V_out', 'V'), ('P_out', 'W')])
    from component_management import primary_mos_role, controller_reference
    add('Q1', primary_mos_role(p)+'；功率级 Vgs/Vds 图对象',
        [('Rds_on', 'Ω'), ('Qg', 'C'), ('Coss', 'F')])
    add('R_S1', '主开关电流采样（简化串联）', [('Rs', 'Ω')])
    controller = controller_reference(p)
    if controller is not None:
        rows.append(controller)
    if topo in ('FLYBACK', 'QR-FLYBACK', 'ACF-FORWARD'):
        add('T1', '隔离变压器；N=Np/Ns',
            [('Lm_forward' if topo == 'ACF-FORWARD' else 'L', 'H'), ('N', '')])
    if topo not in ('FLYBACK', 'QR-FLYBACK'):
        from inductor_selection import purchased
        add('L1', '外购成品电感' if purchased(p) else '输出滤波电感' if topo == 'ACF-FORWARD' else '储能 / 滤波电感',
            [('L', 'H'), ('inductor_dcr', 'Ω')] if purchased(p) else [('L', 'H')])
    if topo == 'ACF-FORWARD':
        add('Q2', '低侧钳位 P-MOS（负栅压驱动）', [('Rds_aux', 'Ω'), ('Qg_aux', 'C'), ('Coss_aux', 'F')])
        add('C_CL1', '低侧钳位电容', [('C_clamp', 'F'), ('ESR_clamp', 'Ω')])
        add('D2', '次级续流二极管', [('Vf_diode', 'V')])
    role = '续流二极管' if topo == 'BUCK' else '输出整流二极管'
    add('D1', role, [('Vf_diode', 'V')])
    from capacitor_banks import bank
    for side,prefix in (('input','C_IN'),('output','C_O')):
        for i,c in enumerate(bank(p,side),1):
            add(prefix+str(i),('输入' if side=='input' else '输出')+'电容 '+str(i),
                text='; '.join(k+'='+fmt_eng(c[k],u) for k,u in (('C','F'),('ESR','Ω'),('ESL','H'))))
    if p.get('d_in_enable'):
        add('D_IN', '输入防反二极管；耦合模型包含固定压降', [('Vf_din', 'V')])
    if p.get('d_out_enable'):
        add('D_OUT', '输出防反二极管；输出在其后，反馈在其前', [('Vf_dout', 'V')])
    if topo in ('FLYBACK', 'QR-FLYBACK') and p.get('Kc', 0.) > 1.:
        from power_stage import compute_operating_point
        from flyback_clamp import rcd_components
        op = compute_operating_point(p) if solved is None else solved
        rcd = rcd_components(op,p)
        add('D_SN1', '原边 RCD 钳位二极管', text='参考连接；未单独输入器件参数')
        add('R_SN1', 'RCD 电阻；⑧页计算', text='R_snub='+fmt_eng(rcd['R_snub'], 'Ω')+'（同一钳位功耗）')
        add('C_SN1', 'RCD 电容；⑧页计算', text='C_snub='+fmt_eng(rcd['C_snub'], 'F')+'（小纹波电荷预算）')
    add('R_LOAD', '等效电阻负载（非实际负载器件）',
        text=fmt_eng(p['V_out']**2 / p['P_out'], 'Ω'))
    return _diode_curve_labels(rows,p)


def _diode_curve_labels(rows,p):
    from device_curve_sources import source_for
    bank=p.get('diode_curves',{})
    for row in rows:
        if row['ref'] in bank and source_for(p,row['ref'])=='curve' and '导通损耗曲线=' not in row['values']:
            row['values']+='; 导通损耗曲线='+bank[row['ref']]['name']+' (X=Vf, Y=If)'
    return rows


class _Schematic:
    def __init__(self, ax):
        self.ax, self.refs = ax, set()
        self.ink = '#33465b'
        from design_theme import is_pcs
        if is_pcs(): self.ink = '#152238'
        self.fontsize = 9

    def wire(self, *points, **kw):
        x, y = zip(*points)
        self.ax.plot(x, y, color=self.ink, lw=1.35, solid_capstyle='round', **kw)

    def text(self, x, y, text, **kw):
        kw.setdefault('fontsize',self.fontsize); kw.setdefault('ha','center'); kw.setdefault('va','center')
        self.ax.text(x, y, text, color=self.ink, **kw)

    def node(self, x, y):
        self.ax.plot(x, y, 'o', ms=3.2, color=self.ink)

    def terminal(self, x, y):
        self.ax.plot(x, y, 'o', ms=4, mfc='white', mec=self.ink)

    def _part(self, center, direction, ref, kind, label_side=1):
        c = np.array(center, float)
        d = np.array(direction, float)
        d /= np.linalg.norm(d)
        n = np.array([-d[1], d[0]])

        def point(a, b=0.):
            return tuple(c+a*d+b*n)

        a, b = point(-.75), point(.75)
        if kind == 'capacitor':
            self.wire(a, point(-.15)); self.wire(point(.15), b)
            self.wire(point(-.15, -.38), point(-.15, .38))
            self.wire(point(.15, -.38), point(.15, .38))
        elif kind == 'resistor':
            self.wire(a, point(-.48)); self.wire(point(.48), b)
            vertices = [point(-.48, -.17), point(.48, -.17),
                        point(.48, .17), point(-.48, .17), point(-.48, -.17)]
            self.wire(*vertices)
        elif kind == 'inductor':
            self.wire(a, point(-.60)); self.wire(point(.60), b)
            u = np.linspace(-.60, .60, 100)
            pts = [point(t, .25*abs(math.sin((t+.60)*math.pi/.30))) for t in u]
            self.wire(*pts)
        elif kind == 'diode':
            self.wire(a, point(-.28)); self.wire(point(.28), b)
            self.ax.add_patch(Polygon([point(-.28, -.32), point(-.28, .32), point(.28)],
                                      fill=False, ec=self.ink, lw=1.35))
            self.wire(point(.28, -.36), point(.28, .36))
        if ref:
            self.refs.add(ref)
            label = c + n*.66*label_side
            self.text(*label,ref,**({'ha':'right' if label_side>0 else 'left'}
                                   if abs(d[1])>.9 else {}))
        return a, b

    def capacitor(self, x, y, ref, **kw):
        return self._part((x, y), (0, 1), ref, 'capacitor', **kw)

    def capacitor_bank(self, values, refs, x_range, top, bottom, summary_y=None):
        """Draw small banks in full; an ellipsis represents omitted branches.

        The first/last designators and the count refer to the complete bank,
        including the branches represented by the ellipsis. The component
        table always lists every branch separately.
        """
        count = len(values)
        assert count == len(refs) and count > 0
        visible = list(range(count)) if count <= 3 else [0, count-1]
        left, right = x_range
        middle = (left+right)/2
        positions = np.linspace(left, right, len(visible)) if count > 1 else [middle]
        cy = (top+bottom)/2
        label_offset = 1.5 if top-bottom > 5 else .82
        for rank, (index, x) in enumerate(zip(visible, positions)):
            a, b = self.capacitor(x, cy, None)
            self.wire((x, top), b); self.wire(a, (x, bottom))
            self.node(x, top); self.node(x, bottom)
            # Alternate label heights so three adjacent designators remain
            # readable in both the desktop figure and the narrower report.
            self.text(x, cy+(label_offset if rank % 2 == 0 else -label_offset), refs[index],
                      fontsize=min(self.fontsize, 7.5),
                      bbox=dict(facecolor='white', edgecolor='none', pad=.25))
        if count > 3:
            self.text(middle, cy+.3, '…', fontsize=11)
        if summary_y is not None:
            self.text(middle, summary_y,
                      f'{count} 颗 · ΣC={fmt_eng(sum(c["C"] for c in values), "F")}',
                      fontsize=7, bbox=dict(facecolor='white', edgecolor='none', pad=.2))
        self.refs.update(refs)

    def resistor(self, x, y, ref, **kw):
        return self._part((x, y), (0, 1), ref, 'resistor', **kw)

    def diode(self, x, y, ref, direction=(1, 0), **kw):
        return self._part((x, y), direction, ref, 'diode', **kw)

    def inductor(self, x, y, ref, direction=(1, 0), **kw):
        return self._part((x, y), direction, ref, 'inductor', **kw)

    def mos(self, x, y, ref, p_channel=False, label_offset=(1.02, 0.)):
        self.refs.add(ref)
        self.wire((x, y+1), (x, y+.47), (x+.25, y+.47))
        self.wire((x, y-1), (x, y-.47), (x+.25, y-.47))
        for a, b in ((-.55, -.25), (-.15, .15), (.25, .55)):
            self.wire((x+.25, y+a), (x+.25, y+b))
        self.wire((x-.12, y-.50), (x-.12, y+.50))
        self.wire((x-1.15, y), (x-.32 if p_channel else x-.12, y))
        if p_channel:
            self.ax.add_patch(Circle((x-.22, y), .10, fc='white', ec=self.ink, lw=1.2))
        # Q1 N-MOS: S -> D. Low-side Q2 P-MOS: D -> S (ground).
        self.wire((x, y+.80), (x+.65, y+.80), (x+.65, y+.75))
        self.diode(x+.65, y, None, direction=(0, -1 if p_channel else 1))
        self.wire((x+.65, y-.75), (x+.65, y-.80), (x, y-.80))
        self.text(x+label_offset[0],y+label_offset[1],ref,ha='left')
        self.ax.text(x-.3, y+.77, 'D', fontsize=7, ha='right', color=self.ink)
        self.ax.text(x-.3, y-.77, 'S', fontsize=7, ha='right', color=self.ink)
        self.ax.text(x-1.17, y+.18, 'G', fontsize=7, ha='center', color=self.ink)
        return (x, y+1), (x, y-1)


def _controller_box(s, p, y):
    """Keep the reference away from power wires; no implied real IC pinout."""
    from component_management import controller_reference, primary_mos_role
    row = controller_reference(p)
    if row is None:
        return
    item = p['component_management']['items']['U_CTRL']
    name = ' '.join(str(item.get(k) or '').strip() for k in ('manufacturer', 'model')).strip()
    s.refs.add('U_CTRL')
    s.wire((.1, y-.7), (8.1, y-.7), (8.1, y+.7), (.1, y+.7), (.1, y-.7))
    s.text(4.1, y+.3, 'U_CTRL · '+(name or '控制器型号待补充')[:58], fontsize=7.5,
           bbox=dict(facecolor='white', edgecolor='none', pad=.2))
    s.text(4.1, y-.24, '参考框：未展开引脚、驱动与偏置', fontsize=6.8)
    if 'P-MOS' in primary_mos_role(p):
        s.text(14.4, y, 'Q1 为 P-MOS；本图按幅值等效示意\n实物须按器件源漏极性及驱动设计',
               fontsize=7, bbox=dict(facecolor='white', edgecolor='none', pad=.25))


def draw_topology(ax, p, solved=None):
    """Draw all six supported circuits; return the displayed designators."""
    if p.get('outputs') or p.get('feedback_mode')=='PSR-MP6005':
        return draw_isolated(ax,p,solved)
    components = topology_components(p,solved)
    refs = {r['ref'] for r in components}
    topo = p['topology']
    isolated = topo in ('FLYBACK', 'QR-FLYBACK', 'ACF-FORWARD')
    ax.clear(); ax.set_aspect('equal'); ax.set_xlim(-.4, 20.2); ax.set_ylim(-2.5 if 'U_CTRL' in refs else -.25, 10.7)
    ax.set_axis_off()
    s = _Schematic(ax)
    s.refs.update(('J1', 'J2', 'R_LOAD'))
    s.terminal(.25, 9); s.terminal(.25, 1)
    s.text(.35, 9.9, 'J1 · Vin +'); s.text(.35, .35, 'J1 −')
    s.wire((.25, 1), (7 if isolated else 19.6, 1))
    input_end = 5.5 if topo == 'BOOST' else 7
    if 'D_IN' in refs:
        a, b = s.diode(1.2, 9, 'D_IN')
        s.wire((.25, 9), a); s.wire(b, (input_end, 9))
    else:
        s.wire((.25, 9), (input_end, 9))
    from capacitor_banks import bank
    input_caps = bank(p, 'input')
    s.capacitor_bank(input_caps, [f'C_IN{i}' for i in range(1, len(input_caps)+1)],
                     (2.05, 3.9), 9, 1, 2.15)

    # Primary / switching-node connections.
    if isolated:
        s.inductor(7, 7.5, None, direction=(0, 1))
        s.wire((7, 9), (7, 8.25)); s.wire((7, 6.75), (7, 6))
        s.inductor(9, 7.5, None, direction=(0, 1), label_side=-1)
        s.wire((9, 9), (9, 8.25)); s.wire((9, 6.75), (9, 1))
        s.wire((7.9, 6.7), (7.9, 8.3)); s.wire((8.1, 6.7), (8.1, 8.3))
        s.refs.add('T1'); s.text(8, 9.9, 'T1 · Np/Ns')
        # Flyback secondary dot is opposite to the forward transformer dot.
        s.node(7.32, 8.3); s.node(8.68, 8.3 if topo == 'ACF-FORWARD' else 6.7)
        ax.plot([8.5, 8.5], [.5, 6.2], color='#b7c6d7', lw=.9, ls='--')
        ax.text(8.5, .05, '隔离', fontsize=8, ha='center', color='#7890a6')
        d, source = s.mos(7, 3.9, 'Q1')
        s.wire((7, 6), d); s.node(7, 6)
        a, b = s.resistor(7, 1.9, 'R_S1')
        s.wire(source, b); s.wire(a, (7, 1))
        s.wire((9, 1), (19.6, 1))
        if topo == 'ACF-FORWARD':
            bottom, top = s.capacitor(5.25, 4.9, None)
            s.refs.add('C_CL1'); s.text(5.25, 6.8, 'C_CL1')
            s.wire((7, 6), (5.25, 6), top)
            d2, source2 = s.mos(5.25, 2.95, 'Q2', p_channel=True)
            s.wire(bottom, d2); s.wire(source2, (5.25, 1)); s.node(5.25, 1)
        elif 'D_SN1' in refs:
            a, b = s.diode(6.1, 6, None, direction=(-1, 0))
            s.refs.add('D_SN1'); s.text(6.1, 5.3, 'D_SN1')
            s.wire((7, 6), a); s.wire(b, (4.8, 6), (4.8, 6.75))
            bottom, top = s.resistor(4.8, 7.5, None)
            s.refs.add('R_SN1'); s.text(4.8, 10.35, 'R_SN1')
            s.wire(bottom, (4.8, 6)); s.wire(top, (4.8, 9)); s.node(4.8, 9)
            bottom, top = s.capacitor(6.0, 7.5, None)
            s.refs.add('C_SN1'); s.text(6, 9.65, 'C_SN1')
            s.wire((4.8, 6), (4.8, 6.5), (6, 6.5), bottom)
            s.wire(top, (6, 9)); s.node(6, 9)
        a, b = s.diode(10.7, 9, 'D1')
        s.wire((9, 9), a)
        if topo == 'ACF-FORWARD':
            s.wire(b, (12.1, 9), (12.1, 7.55))
            a2, b2 = s.diode(12.1, 6.8, 'D2', direction=(0, 1), label_side=-1)
            s.wire((12.1, 1), a2); s.wire(b2, (12.1, 9)); s.node(12.1, 9); s.node(12.1, 1)
            la, lb = s.inductor(13.4, 9, 'L1')
            s.wire(b, la); s.wire(lb, (16.5, 9))
        else:
            s.wire(b, (16.5, 9))
        out_y = 9
    elif topo == 'BOOST':
        la, lb = s.inductor(6.25, 9, 'L1')
        d, source = s.mos(8.5, 5, 'Q1')
        s.wire((7, 9), (8.5, 9), d); s.node(8.5, 9)
        a, b = s.resistor(8.5, 2.5, 'R_S1'); s.wire(source, b); s.wire(a, (8.5, 1))
        da, db = s.diode(11, 9, 'D1'); s.wire((8.5, 9), da); s.wire(db, (16.5, 9))
        s.wire(lb, (8.5, 9))
        out_y = 9
    else:
        # High-side Q1 / series sense, common to buck and inverting buck-boost.
        d, source = s.mos(7, 7.8, 'Q1'); s.wire((7, 9), d)
        a, b = s.resistor(7, 5.65, 'R_S1'); s.wire(source, b)
        s.wire(a, (7, 4.5)); s.node(7, 4.5)
        if topo == 'BUCK':
            la, lb = s.inductor(11.0, 4.5, 'L1')
            s.wire((7, 4.5), la); s.wire(lb, (16.5, 4.5))
            a, b = s.diode(8.8, 2.65, 'D1', direction=(0, 1), label_side=-1)
            s.wire((8.8, 1), a); s.wire(b, (8.8, 4.5)); s.node(8.8, 4.5)
        else:
            a, b = s.inductor(8.8, 2.65, 'L1', direction=(0, 1), label_side=-1)
            s.wire((8.8, 1), a); s.wire(b, (8.8, 4.5))
            s.wire((7, 4.5), (9.7, 4.5)); s.node(8.8, 4.5)
            da, db = s.diode(11, 4.5, 'D1', direction=(-1, 0), label_side=-1)
            s.wire((9.7, 4.5), da); s.wire(db, (16.5, 4.5))
        out_y = 4.5

    output_caps = bank(p)
    s.capacitor_bank(output_caps, [f'C_O{i}' for i in range(1, len(output_caps)+1)],
                     (14.5, 16.15), out_y, 1, .35)
    if 'D_OUT' in refs:
        da, db = s.diode(17.5, out_y, 'D_OUT',
                         direction=(-1, 0) if topo == 'BUCK-BOOST' else (1, 0))
        # Direction changes terminal order, not the connection to each rail.
        ends = sorted((da, db))
        s.wire((16.5, out_y), ends[0]); s.wire(ends[1], (19.6, out_y))
    else:
        s.wire((16.5, out_y), (19.6, out_y))
    a, b = s.resistor(18.9, (out_y+1)/2, 'R_LOAD', label_side=-1)
    s.wire((18.9, out_y), b); s.wire(a, (18.9, 1)); s.node(18.9, out_y)
    s.terminal(19.6, out_y); s.terminal(19.6, 1)
    s.text(18.9, out_y+.9, 'J2 · Vout '+('−' if topo == 'BUCK-BOOST' else '+'))
    s.text(19.2, .35, 'SGND' if isolated else 'GND')
    if isolated:
        s.text(6.2, .35, 'PGND')
    _controller_box(s, p, -1.2)
    assert s.refs == refs, (s.refs-refs, refs-s.refs)
    return components


def isolated_components(p, solved=None):
    from isolated_outputs import output_specs
    from isolated_fields import FIELDS
    from mp6005 import DEFAULTS
    rails = output_specs(p) or [dict(p,name='OUT1',id=1)]
    from power_stage import compute_operating_point
    solved=compute_operating_point(p) if solved is None else solved
    q = dict(solved.get('aggregate_params',p),outputs=[],feedback_mode='SSR',feedback_output=1,
             coupling_config=dict(enabled=False))
    q['component_management'] = p.get('component_management', {})
    if p.get('feedback_mode') == 'PSR-MP6005':
        q['component_management'] = dict(q['component_management'], items={
            key:value for key,value in q['component_management'].get('items', {}).items() if key != 'U_CTRL'})
    old = topology_components(q,solved)
    keep = {'J1','Q1','R_S1','T1','C_IN1','C_IN2','D_IN','Q2','C_CL1','D_SN1','R_SN1','C_SN1','U_CTRL'}
    rows = [r for r in old if r['ref'] in keep or r['ref'].startswith('C_IN')]
    for r in rows:
        if r['ref']=='T1':
            r['role']='共享磁芯；主反馈电压为输入，其余输出按实际副边匝数比估算'
            r['values']='N(OUT1)='+fmt_eng(p['N'],'')+'; '+('Lm_forward='+fmt_eng(p['Lm_forward'],'H') if p['topology']=='ACF-FORWARD' else 'Lm='+fmt_eng(p['L'],'H'))
            if solved.get('coupled_model'):
                r['role']='线性耦合绕组；Lp 为原边开路自感；kij 见左栏⑦'
                r['values']='Lp='+fmt_eng(p['L'],'H')+'; kij=完整对称矩阵'
    for rail in rails:
        i = rail['id']
        fields = [('J_O'+str(i),'输出端口',('V_out','P_out')),('D_O'+str(i),'整流二极管',('Vf_diode','Qrr')),
                  ('C_O'+str(i)+'A','输出电容 A',('C_out','Rc','ESL')),('R_LOAD'+str(i),'等效负载',('P_out',))]
        if rail['d_out_enable']: fields.append(('D_B'+str(i),'输出防反二极管',('Vf_dout',)))
        if p['topology']=='ACF-FORWARD':
            fields += [('D_F'+str(i),'续流二极管',('Vf_diode',)),('L_O'+str(i),'独立输出电感',('L',))]
        for ref,role,keys in fields:
            if ref.startswith('C_O'):continue
            rows.append(dict(ref=ref,role=f"OUT{i} {rail['name']} · {role}",
                             # FIELDS already chooses the display prefix;
                             # applying fmt_eng again creates e.g. "100mmΩ".
                             values='; '.join(f'{k}={rail[k]/FIELDS[k][2]:.5g}{FIELDS[k][1]}' for k in keys),keys=keys))
        from capacitor_banks import bank,output_ref
        for j,c in enumerate(bank(rail),1):
            rows.append(dict(ref=output_ref(i,j,True),role=f'OUT{i} 输出电容 {j}',
                values='; '.join(k+'='+fmt_eng(c[k],u) for k,u in (('C','F'),('ESR','Ω'),('ESL','H'))),keys=('output_capacitors',)))
    if p.get('feedback_mode')=='PSR-MP6005':
        for ref,role,key in [('N_A','独立辅助采样绕组','psr_Na'),('R_FBH','FB 分压上电阻','psr_RfbH'),
                             ('R_FBL','FB 分压下电阻（0=自动）','psr_RfbL'),('R_REG','SENSE 补偿/抖频设置','psr_Rreg'),
                             ('R_COMP','COMP 串联电阻','psr_Rcomp'),('C_COMP','COMP 串联电容','psr_Ccomp'),
                             ('C_POLE','COMP 高频并联电容','psr_Cpole')]:
            rows.append(dict(ref=ref,role=role,values=f'{key}={p.get(key,DEFAULTS[key]):.5g}',keys=(key,)))
        rows.append(dict(ref='U_PSR',role='MP6005，MODE 悬空',values='250kHz PWM / 轻载降频；非精确 IC 仿真',keys=()))
    else:
        rows.append(dict(ref='U_FB',role='SSR 主反馈通路（控制框图）',values=f"OUT{int(p.get('feedback_output',1))}；未反馈路不独立稳压",keys=('feedback_output',)))
    return _diode_curve_labels(rows,p)


def draw_isolated(ax,p,solved=None):
    """Expanded winding drawing. Each secondary has its own local return."""
    from isolated_outputs import output_specs
    rails = output_specs(p) or [dict(p,name='OUT1',id=1)]
    rows = isolated_components(p,solved); refs={r['ref'] for r in rows}
    ax.clear(); ax.set_axis_off()
    height=max(12,5*len(rails)+2)
    ax.set_xlim(-.8,25); ax.set_ylim(-7 if p.get('feedback_mode')=='PSR-MP6005' else -3,height); ax.set_aspect('auto')
    s=_Schematic(ax)
    s.fontsize=7.5
    y=height-2; ground=y-8
    s.refs.update(('J1','T1')); s.terminal(0,y); s.terminal(0,ground)
    s.text(0,y+.9,'J1 · Vin'); s.wire((0,ground),(7,ground))
    if 'D_IN' in refs:
        a,b=s.diode(1,y,'D_IN'); s.wire((0,y),a); s.wire(b,(7,y))
    else: s.wire((0,y),(7,y))
    from capacitor_banks import bank, output_ref
    input_caps = bank(p, 'input')
    s.capacitor_bank(input_caps, [f'C_IN{i}' for i in range(1, len(input_caps)+1)],
                     (2.05, 3.9), y, ground, y-7.2)
    a,b=s.inductor(7,y-1.5,None,direction=(0,1)); s.wire((7,y),b); s.wire(a,(7,y-3))
    s.node(7.35,y-.65); s.text(7.3,y+.9,'T1 · Np')
    d,src=s.mos(7,y-4.5,'Q1',label_offset=(-1.6,-.65)); s.wire((7,y-3),d)
    a,b=s.resistor(7,y-6.65,'R_S1'); s.wire(src,b); s.wire(a,(7,ground))
    s.text(6,ground-.5,'PGND')
    if 'Q2' in refs:
        a,b=s.capacitor(5.25,y-3.8,'C_CL1'); s.wire((7,y-3),(5.25,y-3),b)
        d,src=s.mos(5.25,y-5.6,'Q2',True); s.wire(a,d); s.wire(src,(5.25,ground))
    elif 'D_SN1' in refs:
        a,b=s.diode(5.8,y-3,'D_SN1',direction=(-1,0)); s.wire((7,y-3),a); s.wire(b,(4.8,y-3))
        for x,ref,method in ((4.8,'R_SN1',s.resistor),(6.,'C_SN1',s.capacitor)):
            a,b=method(x,y-1.5,None); s.wire((4.8,y-3),(x,y-3),a); s.wire(b,(x,y))
            s.refs.add(ref); s.text(x,y+.5 if ref=='R_SN1' else y+1.8,ref,ha='center')
    # Core and isolation boundary span every configured secondary.
    s.wire((8.3,height-3),(8.3,1)); s.wire((8.5,height-3),(8.5,1))
    ax.plot([9,9],[-2,height],ls='--',lw=.8,color='#9aaec1')
    for rail in rails:
        i=rail['id']; yy=height-2-5*(i-1); low=yy-2.8
        a,b=s.inductor(10,yy-1.4,None,direction=(0,1)); s.wire((10,yy),b); s.wire(a,(10,low),(22.7,low))
        s.node(9.65,yy-.55 if p['topology']=='ACF-FORWARD' else low+.55)
        a,b=s.diode(11.8,yy,f'D_O{i}'); s.wire((10,yy),a)
        if p['topology']=='ACF-FORWARD':
            c,d=s.diode(13.2,yy-1.4,f'D_F{i}',direction=(0,1),label_side=-1)
            s.wire((13.2,low),c); s.wire(d,(13.2,yy)); s.wire(b,(13.2,yy))
            c,d=s.inductor(14.5,yy,f'L_O{i}'); s.wire(b,c); s.wire(d,(20,yy))
        else: s.wire(b,(20,yy))
        output_caps = bank(rail)
        s.capacitor_bank(output_caps, [output_ref(i, j, True) for j in range(1, len(output_caps)+1)],
                         (16., 18.5), yy, low)
        if f'D_B{i}' in refs:
            a,b=s.diode(20.5,yy,f'D_B{i}'); s.wire((20,yy),a); s.wire(b,(22.7,yy))
        else: s.wire((20,yy),(22.7,yy))
        a,b=s.resistor(22.,yy-1.4,None); s.wire((22,yy),b); s.wire(a,(22,low))
        s.refs.add(f'R_LOAD{i}'); s.text(21.5,yy-1.4,f'R_LOAD{i}',ha='right',fontsize=7.5)
        s.refs.add(f'J_O{i}'); s.terminal(22.7,yy); s.terminal(22.7,low)
        main=i==p.get('feedback_output',1)
        name = rail['name']+' ' if len(rails) <= 3 else ''
        title = f"J_O{i} · {name}{rail['V_out']:.4g}V / {rail['P_out']:.4g}W"+(' ★' if main else '')
        title += f' · 电容 {len(output_caps)} 颗 · ΣC={fmt_eng(sum(c["C"] for c in output_caps), "F")}'
        s.text(17., yy+1.5, title, fontsize=7 if len(rails) > 3 else 7.5,
               bbox=dict(facecolor='white', edgecolor='none', pad=.3))
        s.text(23., low, f'SGND{i}', fontsize=7, ha='left')
    if p.get('feedback_mode')=='PSR-MP6005':
        s.refs.update(draw_psr_network(ax,origin=(0,-6)))
    else:
        s.refs.add('U_FB'); yy=height-2-5*(p.get('feedback_output',1)-1)
        ax.text(18,-1.8,'U_FB · SSR：★ 路防反前取样；端口输出在防反后',ha='center',fontsize=8,color='#2068a0')
        ax.plot([19.3,19.3],[-1.3,yy],ls='--',color='#2068a0',lw=.8)
        ax.annotate('',xy=(19.3,yy),xytext=(19.3,yy-.75),arrowprops=dict(arrowstyle='->',color='#2068a0',lw=.8))
    _controller_box(s, p, ground-2.)
    assert s.refs==refs,(s.refs-refs,refs-s.refs)
    return rows


def draw_psr_network(ax,origin=(0,0),standalone=False):
    """Unrectified auxiliary FB and genuine series-RC / parallel-C COMP."""
    if standalone:
        ax.clear(); ax.set_axis_off(); ax.set_xlim(-.5,24); ax.set_ylim(-.5,6.4)
    ox,oy=origin
    # Reuse a temporary translated coordinate helper without hidden state.
    inset=ax.inset_axes([0,0,1,1],transform=ax.transAxes) if not standalone else ax
    if not standalone:
        inset.set_axis_off(); inset.set_xlim(ax.get_xlim()); inset.set_ylim(ax.get_ylim()); inset.patch.set_alpha(0)
    s=_Schematic(inset)
    s.fontsize=7.5
    def coord(x,y): return (x+ox,y+oy)
    a,b=s.inductor(*coord(1.2,3.6),None,direction=(0,1)); s.refs.add('N_A')
    s.wire(b,coord(1.2,5),coord(2.5,5)); s.text(*coord(1.8,5.8),'N_A',fontsize=8)
    a,b=s._part(coord(3.3,5),(1,0),None,'resistor'); s.wire(coord(2.5,5),a); s.wire(b,coord(6,5),coord(8,5))
    s.refs.add('R_FBH'); s.text(*coord(3.3,5.75),'R_FBH')
    c,d=s.resistor(*coord(6,3.3),None); s.wire(coord(6,5),d); s.wire(c,coord(6,1))
    s.refs.add('R_FBL'); s.text(*coord(5.55,3.4),'R_FBL',ha='right')
    s.wire(coord(1.2,2.85),coord(1.2,1),coord(6,1)); s.text(*coord(3.3,.45),'PGND · 简化采样参考')
    c,d=s._part(coord(5.4,2),(1,0),'R_REG','resistor'); s.wire(coord(3,2),c); s.wire(d,coord(8,2)); s.text(*coord(2.4,2),'R_S1 采样点')
    s.refs.add('U_PSR'); s.wire(coord(8,1),coord(13,1),coord(13,5.6),coord(8,5.6),coord(8,1))
    s.text(*coord(10.5,4),'U_PSR · MP6005',fontsize=8); s.text(*coord(10.5,3),'MODE 悬空',fontsize=8)
    s.text(*coord(8.5,5),'FB'); s.text(*coord(9,2),'SENSE'); s.text(*coord(12.2,5),'COMP')
    a,b=s.resistor(*coord(16,4),None); s.wire(coord(13,5),coord(16,5),b)
    s.refs.add('R_COMP'); s.text(*coord(15.55,4),'R_COMP',ha='right')
    c,d=s.capacitor(*coord(16,2),None); s.wire(a,d); s.wire(c,coord(16,1))
    s.refs.add('C_COMP'); s.text(*coord(15.55,2),'C_COMP',ha='right')
    c,d=s.capacitor(*coord(19,3),None); s.wire(coord(16,5),coord(19,5),d); s.wire(c,coord(19,1),coord(16,1))
    s.refs.add('C_POLE'); s.text(*coord(18.55,3),'C_POLE',ha='right')
    s.text(*coord(18,.45),'PGND'); s.text(*coord(21.4,3.5),'gEA COMP\n(R + C串联) ∥ Cp',fontsize=8)
    return s.refs
