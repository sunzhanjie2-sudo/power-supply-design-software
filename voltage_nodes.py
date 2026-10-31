"""Shared DC node convention: output after blocking diode, sense before it."""
CONVENTION = 'output-after-blocking-feedback-before-blocking-v1'
NOTE = ('输出电压及负载功率按输出防反管之后的端口统计；反馈取样在防反管之前的电容端。'
        '固定压降模型下 Vcap=Vout+Vf,block；未启用防反管时两节点重合。')


def output_drop(rail):
    return float(rail.get('Vf_dout', 0.)) if rail.get('d_out_enable', False) else 0.


def input_drop(p):
    return float(p.get('Vf_din', 0.)) if p.get('d_in_enable', False) else 0.


def capacitor_voltage(rail, voltage=None):
    return float(rail['V_out'] if voltage is None else voltage)+output_drop(rail)


def ratio_voltage(reference, rail, turns_ratio):
    """CCM nominal winding estimate, not a cross-regulation solution."""
    reflected=capacitor_voltage(reference)+float(reference.get('Vf_diode', 0.))
    return reflected*turns_ratio-float(rail.get('Vf_diode', 0.))-output_drop(rail)


def attach_nodes(op, p):
    """Annotate legacy efficiency estimates without relabelling their solver."""
    op.update(voltage_convention=CONVENTION,V_out_cap=capacitor_voltage(p,op['V_out']),
        V_feedback=capacitor_voltage(p,op['V_out']),V_feedback_target=capacitor_voltage(p),
        V_in_bus=float(p['V_in'])-input_drop(p),V_block=output_drop(p),V_input_block=input_drop(p))
    return op
