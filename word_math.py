"""Engineering notation -> structured native Word math (no raster equations).

Small explicit grammar: groups, products, fractions, scripts, roots, sums and
integrals. This is not a LaTeX parser. Unsupported input raises, never flattens
the whole equation to an m:t run. Variable aliases preserve the source symbols.
"""
import re
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

ALIASES = {
    'Kpin':'K_P,COMP',
    'PL':'P_L','ILrms':'I_L,rms','Pextra':'P_extra',
    'Iin':'I_in','Iout':'I_out','Idiv':'I_div','Iq':'I_q',
    'Pchip':'P_chip','Tj':'T_j','Ta':'T_a','θja':'θ_ja',
    'Vout':'V_out','Vblock':'V_block','Vinbus':'V_in,bus','Vclamp':'V_clamp','Rload':'R_load',
    'Z_k':'Z_k','Z_1':'Z_1','Z_2':'Z_2','Z_p':'Z_p','Z_o':'Z_o',
    'R_k':'R_k','R_L':'R_L','C_k':'C_k','i_k':'i_k','u_k':'u_k',
    'du_k':'du_k','vnode':'v_node',
    'If,k':'I_f,k','If':'I_f',
    'Fpre':'F_pre','Fpost':'F_post','Vdrv':'V_drv',
    'Qplateau,end':'Q_M,end','Qplateau,start':'Q_M,start',
    'gfs':'g_fs','Vgp,ref':'V_gp,ref','Cgs,inc':'C_gs,inc',
    'Qgs,on':'Q_gs,on','Qgs,off':'Q_gs,off',
    'R_j':'R_j','V_ref,j':'V_ref,j','P_load,j':'P_load,j',
    'V_max,j':'V_max,j','V_min,j':'V_min,j','ΔV_env,%':'ΔV_env,%',
    'Gj':'G_j','Gb':'G_b','Gjk':'G_jk','Gbk':'G_bk','Hj':'H_j','Zjk':'Z_jk',
    'xnext':'x_n+1','xstate':'x_n','Ad':'A_d','Bd':'B_d','Q_j':'Q_j',
    'vcontrol':'v_c','vcompare':'v_cmp','ip_off':'i_p,off','slope_a':'m_a',
    'Reff':'R_eff',
    'Ns_j':'N_s,j','Ns_b':'N_s,b','V_j,est':'V_j,est',
    'Acu_j':'A_Cu,j','nstrand_j':'n_strand,j','d_j':'d_j',
    'nparallel_j':'b_j','nparallel':'b',
    'J_j':'J_j','Irms_j':'I_rms,j','Rdc_j':'R_dc,j',
    'P_j':'P_j','V_j':'V_j','I_j':'I_j','w_j':'w_j','N_j':'N_j','N_1':'N_1','V_1':'V_1',
    'N_a':'N_a','N_s':'N_s','N_p':'N_p','R_s':'R_s','V_f':'V_f','V_FB':'V_FB',
    'R_FB,L':'R_FB,L','R_FB,H':'R_FB,H','R_z':'R_z','C_z':'C_z','C_p':'C_p','g_m':'g_m',
    'L_min':'L_min','L_eq':'L_eq','C_eq':'C_eq','L_j':'L_j','C_j':'C_j','V_b':'V_b',
    'I_s,j':'I_s,j','I_p,off':'I_p,off','P_ctrl':'P_ctrl','I_reg':'I_reg','g_reg':'g_reg',
    'V_aux':'V_aux','R_REG':'R_REG','t_33':'t_33','t_con':'t_con','H_FB':'H_FB',
    'Pin,est':'P_in,est','Pin,final':'P_in,final','Iin,est':'I_in,est',
    'Ploss,budget':'P_loss,budget','Ploss':'P_loss','ηfinal':'η_final','Req':'R_eq',
    'Pcap,in':'P_cap,in','Iincap,j,rms':'I_incap,j,rms','ESRin,j':'ESR_in,j',
    'Gvc,out':'G_vc,out','Gvc,core':'G_vc,core',
    'Vin':'V_in','Vo':'V_o','Po':'P_o','Pout':'P_out','Io':'I_o','Pin':'P_in','Vf':'V_f',
    'Vr':'V_r','Vs':'V_s','Vm':'V_m','Vgs':'V_gs','Vth':'V_th','Vds':'V_ds',
    'Vgp,on':'V_gp,on','Vgp,off':'V_gp,off','Rds,on':'R_ds,on',
    'Ids,on':'I_ds,on','Ids,off':'I_ds,off','fs':'f_s','Ts':'T_s',
    'Ton':'T_on','Tdemag':'T_demag','Tring':'T_ring','Tms':'T_ms',
    'Irms':'I_rms','Ipk':'I_pk','Imin':'I_min','IL,avg':'I_L,avg',
    'Ip,on,avg':'I_p,on,avg','Is,pk':'I_s,pk','Isw,rms':'I_sw,rms',
    'Isw':'I_sw','Iavg':'I_avg','Ic,rms':'I_c,rms','Ibank,rms':'I_bank,rms',
    'Ibank':'I_bank','Ij,band':'I_j,band','Ij,total':'I_j,total',
    'Ij,peak':'I_j,peak','Ioutcap,j,rms':'I_outcap,j,rms',
    'Ic,rms,j':'I_c,rms,j','Rc,j':'R_c,j','Iclamp,rms':'I_clamp,rms',
    'Im,pk':'I_m,pk','Vhump':'V_hump','Vreset':'V_reset','Vcl':'V_cl',
    'Lmin':'L_min','Cmin':'C_min','DCCM':'D_CCM','DDCM':'D_DCM','Dp':'D_p',
    'ΔIL':'ΔI_L','ΔIp':'ΔI_p','ΔIm':'ΔI_m','ΔB':'ΔB','ΔT':'ΔT',
    'Lleak':'L_leak','Eleak':'E_leak','Rsnub':'R_snub','Csnub':'C_snub',
    'Rpullup':'R_pullup','R_LED':'R_LED','R_pz':'R_pz','C_pz':'C_pz',
    'Rlower':'R_lower','Vref':'V_ref',
    'R1':'R_1','R2':'R_2','R3':'R_3','C1':'C_1','C2':'C_2','C3':'C_3',
    'Copto':'C_opto','Cp':'C_p','Ccl,min':'C_cl,min','Ccl':'C_cl','Lm':'L_m',
    'Rdc':'R_dc','Ron':'R_on','Roff':'R_off','Rg_drive':'R_g,drive',
    'Qg_th':'Q_g,th','Qgs':'Q_gs','Qgd':'Q_gd','Coss':'C_oss','Qg':'Q_g',
    'Qrr':'Q_rr','k_sw':'k_sw','dwire':'d_wire','nstrand':'n_strand',
    'Bmax':'B_max','Bpk':'B_pk','Bsat':'B_sat','Np,auto':'N_p,auto',
    'Ns,auto':'N_s,auto','NL':'N_L','Np':'N_p','Ns':'N_s','Ae':'A_e',
    'Ve':'V_e','Wa':'W_a','Awire':'A_wire','Asurf':'A_surf','lg':'l_g',
    'le':'l_e','μr':'μ_r','μe':'μ_e','AL':'A_L','L0':'L_0',
    'Rcore':'R_core','Rgap':'R_gap',
    'Rth':'R_i-a',
    'fRHP':'f_RHP','feff':'f_eff','fc,max':'f_c,max','fc':'f_c',
    'fr':'f_r','fz':'f_z','fp':'f_p','ωz₁':'ω_z1','ωz₂':'ω_z2',
    'ωp₁':'ω_p1','ωp₂':'ω_p2','ωc':'ω_c','ωp':'ω_p','ω₁₈₀':'ω_180',
    'Gc0':'G_c0','Gd0':'G_d0','Gvc':'G_vc','Gvd':'G_vd','Gid':'G_id',
    'Gc':'G_c','Fm':'F_m','Fi':'F_i','Fv':'F_v','Qc':'Q_c','NRHP':'N_RHP',
    'Ptotal':'P_total','Psemi':'P_semi','Pmag':'P_mag','Pcap':'P_cap',
    'Psense':'P_sense','Prcd':'P_rcd','Pdin':'P_din','Pdout':'P_dout',
    'Pclamp':'P_clamp','Pcond':'P_cond','Pon':'P_on','Poff':'P_off',
    'Pcoss':'P_coss','Pgate':'P_gate','Pdiode':'P_diode','Pcu':'P_cu',
    'Pcore':'P_core','Psin':'P_sin','Ptri':'P_tri','PNSE':'P_NSE',
    'PiGSE':'P_iGSE','PESR,j':'P_ESR,j','Pres':'P_res','ESRout,j':'ESR_out,j',
    'ESRclamp':'ESR_clamp','ESRj':'ESR_j','ESLj':'ESL_j','Zeq':'Z_eq',
    'Zeq':'Z_eq','Yj':'Y_j','Yk':'Y_k','Zj':'Z_j','Ij':'I_j','Cj':'C_j',
    'Rcin':'R_cin','icin':'i_c,in','iin':'i_in','ic':'i_c','Ic':'I_c',
    'iL':'i_L','im':'i_m','Rs_on':'R_s,on','Rs_off':'R_s,off','Rs':'R_s','Rg':'R_g',
    'Ap,L':'A_p,L','Ap,T':'A_p,T','Fr':'F_r','Rd':'R_d','dtms':'dt_ms',
    'i主,ON':'i_main,ON','i辅助,OFF':'i_aux,OFF','I辅助,rms':'I_aux,rms',
    'V器件,pk':'V_device,pk','ring_margin':'ring_margin',
    'mean':'mean','min':'min','max':'max','round':'round','ceil':'ceil',
    'cos':'cos','tan':'tan','ln':'ln','arg':'arg','PM':'PM','GM':'GM','CTR':'CTR',
    'boost':'boost','scale':'scale','fill':'fill',
    'ηguess':'η_guess','kN':'k_N','ki':'k_i','Cfit':'C_fit','Cα':'C_α',
    'Nsamples':'N_samples','Xselected':'X_selected','GMdB':'GM_dB',
    'ΔVESR':'ΔV_ESR','ΔVC':'ΔV_C','Ctotal':'C_total','ESReq':'ESR_eq',
    'Vf,din':'V_f,din','Rd,din':'R_d,din','Vf,dout':'V_f,dout','Rd,dout':'R_d,dout',
    'PM目标':'PM_target','ripple_target':'ripple_target','A_sense':'A_sense',
    'log₁₀':'log_10','μ₀':'μ_0','δF':'δ_F','gm':'g_m','Ku':'K_u','KP':'K_P',
    'M_ij':'M_ij','k_ij':'k_ij','L_ii':'L_ii','L_jj':'L_jj','L_ij':'L_ij',
    'v_i':'v_i','R_i':'R_i','i_i':'i_i','di_j':'di_j','i_j':'i_j',
    'Rload_j':'R_load,j','Vtarget_j':'V_target,j','Prated_j':'P_rated,j',
    'Pactual_j':'P_actual,j','Iavg_j':'I_avg,j','Vo_j':'V_o,j',
    'Vds,plateau':'V_ds,plateau','Vds,clamp':'V_ds,clamp',
    'iclamp':'i_clamp','Ioff':'I_off','treset':'t_reset','ΔVc':'ΔV_c',
    'ΔVcl':'ΔV_cl','Vc':'V_c','Lp':'L_p','Lsc':'L_sc','Lσ':'L_σ','dt':'dt',
    'I_FB,负向':'I_FB,negative','Ipk,最小':'I_pk,min',
    'fs,估算':'f_s,estimate','Pout,最低':'P_out,min',
    'G_c':'G_c','d_c,j':'d_c,j','d_o':'d_o','d_c':'d_c','Δd':'Δd',
    'W_u':'W_u','H_u':'H_u','m_x':'m_x','m_y':'m_y',
    'b_w':'b_w','b_h':'b_h','h_j':'h_j','t_l':'t_l','t_w':'t_w',
    'H_req':'H_req','ΔH':'ΔH','k_Cu':'k_Cu','n_w':'n_w','n_j':'n_j',
    'n_b':'n_b','D_b':'D_b','k_pack':'k_pack','a_f':'a_f','w_t':'w_t',
    'q_max':'q_max','q_set':'q_set','w_occ':'w_occ','p_x':'p_x','x_0':'x_0',
    'N_layer':'N_ℓ','h_layer':'h_ℓ','t_layer':'t_ℓ','y_layer':'y_ℓ',
    'y_first':'y_1','y_prev':'y_ℓ−1','h_prev':'h_ℓ−1',
    'floor':'floor',
}
NAMES = sorted(ALIASES, key=len, reverse=True)
SUBS = str.maketrans('₀₁₂₃₄₅₆₇₈₉', '0123456789')
SUPS = str.maketrans('⁰¹²³⁴⁵⁶⁷⁸⁹⁻', '0123456789-')


def element(name, *children, **attrs):
    node = OxmlElement('m:'+name)
    for k, v in attrs.items(): node.set(qn('m:'+k), str(v))
    node.extend(children)
    return node


def run(text, upright=False):
    # Labels such as "in" are literal identifiers, not a membership
    # operator. Without m:lit some OMML readers misparse in a subscript,
    # swallowing the rest of the equation into an error expression.
    pr = element('rPr')
    if upright and any(ch.isalpha() or ch==',' for ch in text):
        pr.append(element('lit'))
    pr.append(element('sty', val='p' if upright else 'i'))
    wp = OxmlElement('w:rPr')
    fonts = OxmlElement('w:rFonts')
    for k in ('ascii', 'hAnsi'): fonts.set(qn('w:'+k), 'Cambria Math')
    wp.append(fonts)
    t = element('t'); t.text = text
    return element('r', pr, wp, t)


def script(base, sub=None, sup=None):
    e = element('e', *base)
    if sub is not None and sup is not None:
        return [element('sSubSup', e, element('sub', *sub), element('sup', *sup))]
    if sub is not None: return [element('sSub', e, element('sub', *sub))]
    return [element('sSup', e, element('sup', *sup))]


def name(symbol):
    symbol = ALIASES.get(symbol, symbol)
    if '_' not in symbol: return [run(symbol, symbol in ('PM','GM','CTR','ESR','MLT','mean','min','max','round','ceil','floor','cos','tan','ln','arg','boost','scale','fill'))]
    base, sub = symbol.split('_', 1)
    return script([run(base)], [run(sub, True)])


class Parser:
    def __init__(self, text):
        self.text = text.replace('−', '-').replace('×', '·').replace('½', '(1/2)')
        self.i = 0

    def peek(self):
        while self.i < len(self.text) and self.text[self.i].isspace(): self.i += 1
        return self.text[self.i:self.i+1]

    def expr(self, stops=''):
        result = self.product(stops+'=+-,;；≥≤≈<>：:±')
        while self.peek() and self.peek() not in stops:
            ch = self.peek()
            if ch in ')]}': break
            self.i += 1
            result += [run(ch)] + self.product(stops+'=+-,;；≥≤≈<>：:±')
        return result

    def product(self, stops):
        result = []
        while self.peek() and self.peek() not in stops and self.peek() not in ')]}':
            if self.peek() == '/':
                self.i += 1
                den = self.factor(stops=stops)
                if not result or not den: raise ValueError('Empty fraction: '+self.text)
                result = [element('f', element('num', *result), element('den', *den))]
            elif self.peek() == '·':
                self.i += 1; result.append(run('·'))
            else:
                before = self.i
                result += self.factor(stops=stops)
                if before == self.i: raise ValueError('Unparsed math: '+self.text[self.i:])
        return result

    def factor(self, scripts=True, stops=''):
        ch = self.peek()
        if not ch: return []
        if ch in '([{|':
            self.i += 1; close = {'(':')', '[':']', '{':'}','|':'|'}[ch]
            content = self.expr(close)
            if self.peek() != close: raise ValueError('Unclosed group: '+self.text)
            self.i += 1
            result = [element('d', element('dPr', element('begChr', val=ch),
                                          element('endChr', val=close)), element('e', *content))]
        elif ch == '√':
            self.i += 1
            result = [element('rad', element('radPr', element('degHide', val='1')),
                              element('deg'), element('e', *self.factor(stops=stops)))]
        elif ch in 'Σ∑∫':
            self.i += 1; sub = sup = None
            if self.peek() == '_':
                self.i += 1; sub = self.factor(scripts=False,stops=stops)
            if self.peek() == '^':
                self.i += 1; sup = self.factor(scripts=False,stops=stops)
            # OMML requires the mathematical summation character U+2211.
            # Greek capital Sigma U+03A3 is not a supported n-ary operator
            # in Word/LibreOffice, even though the glyphs look similar.
            operator='∑' if ch in 'Σ∑' else ch
            pr = element('naryPr', element('chr', val=operator), element('limLoc', val='subSup'),
                         element('subHide', val='0' if sub else '1'),
                         element('supHide', val='0' if sup else '1'))
            # Use the caller's scope: an absolute-value bar may START an
            # integral operand, or CLOSE the enclosing expression.  A
            # blanket stop at '|' emitted an empty n-ary operand (a visible
            # Word placeholder) for integral |dB/dt|^alpha dt.
            operand=self.product(stops+'=+-,;；≥≤≈<>：:±')
            if not operand or not any(node.text for part in operand for node in part.iter(qn('m:t'))):
                raise ValueError('Empty n-ary operand: '+self.text)
            result = [element('nary', pr, element('sub', *(sub or [])),
                              element('sup', *(sup or [])), element('e', *operand))]
        else:
            matched = next((s for s in NAMES if self.text.startswith(s, self.i)), None)
            if matched:
                self.i += len(matched); result = name(matched)
            elif ch.isdigit() or ch == '.':
                m = re.match(r'\d+(?:\.\d+)?|\.\d+', self.text[self.i:])
                if not m: self.i += 1; result = [run(ch)]
                else: self.i += len(m[0]); result = [run(m[0], True)]
            elif ch == '-':
                self.i += 1; result = [run('-')] + self.factor(stops=stops)
            else:
                self.i += 1; result = [run(ch, bool(re.match(r'[\u4e00-\u9fff]', ch)))]
        if not scripts:
            return result
        if self.peek() == '′':
            self.i += 1; result.append(run('′'))
        if self.peek() and self.peek() in '₀₁₂₃₄₅₆₇₈₉':
            raw = ''
            while self.peek() and self.peek() in '₀₁₂₃₄₅₆₇₈₉': raw += self.peek(); self.i += 1
            result = script(result, [run(raw.translate(SUBS), True)])
        if self.peek() == '^':
            self.i += 1; result = script(result, sup=self.factor(stops=stops))
        elif self.peek() and self.peek() in '⁰¹²³⁴⁵⁶⁷⁸⁹⁻':
            raw = ''
            while self.peek() and self.peek() in '⁰¹²³⁴⁵⁶⁷⁸⁹⁻': raw += self.peek(); self.i += 1
            result = script(result, sup=[run(raw.translate(SUPS), True)])
        return result


def math_nodes(text):
    parser = Parser(text)
    result = parser.expr()
    if parser.peek(): raise ValueError('Trailing math: '+text[parser.i:])
    return result
