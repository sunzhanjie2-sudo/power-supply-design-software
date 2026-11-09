"""Public scope, source links and inputs for specification-driven first drafts."""

REVISION = '2026-11-04.3'
DOCUMENT = '自动计算参数依据.docx'
SOURCES = {
    'BUCK': ('TI · SLVA477C', 'Basic Calculation of a Buck Converter’s Power Stage，§§1–4、6–7',
             'https://www.ti.com/lit/an/slva477b/slva477b.pdf'),
    'TPS40200': ('TI · TPS40200', 'SLUS659G，电气特性、§7.3.5、§8.2.1.2',
                 'https://www.ti.com/lit/ds/symlink/tps40200.pdf'),
    'LTC3864': ('ADI · LTC3864', 'Rev. C，Electrical Characteristics、Applications Information',
                'https://www.analog.com/media/en/technical-documentation/data-sheets/ltc3864.pdf'),
    'BOOST': ('TI · SLVA372D', 'Basic Calculation of a Boost Converter’s Power Stage，§§2–7',
              'https://www.ti.com/lit/an/slva372d/slva372d.pdf'),
    'LM5022': ('TI · LM5022', 'SNVS480J，电气特性、§7.3、§8.2.2.9 及补偿式 (47)–(55)',
               'https://www.ti.com/lit/ds/symlink/lm5022.pdf'),
    'BUCK-BOOST': ('TI · SLVAFJ7', '反相 Buck-Boost 功率级、器件应力与控制带宽',
                   'https://www.ti.com/document-viewer/lit/html/SLVAFJ7'),
    'FLYBACK': ('TI · SNVA866A', 'LM5155 隔离反激设计，变压器、限流、输出与环路',
                'https://www.ti.com/lit/an/snva866a/snva866a.pdf'),
    'FLYBACK-DCM': ('TI · SSZTCW6', 'Designing a DCM flyback converter，储能、退磁与空闲时间',
                    'https://www.ti.com/lit/ta/ssztcw6/ssztcw6.pdf'),
    'MP6005': ('MPS · MP6005', 'Rev. 1.1，电气特性、SSR 接法与 SENSE 电阻选取',
               'https://www.monolithicpower.com/en/documentview/productdocument/index/version/2/document_type/Datasheet/lang/en/sku/MP6005GK/document_id/6877/'),
    'RCD': ('TI · SSZTCV6', 'Snubbing the flyback converter，漏感能量与钳位损耗',
            'https://www.ti.com/document-viewer/lit/html/SSZTCV6'),
    'CROSS': ('TI · SSZTCW3', '多输出反激的交叉调整与整流导通区间',
              'https://www.ti.com/document-viewer/lit/html/SSZTCW3/GUID-9BE5B4A2-3166-4329-A3F0-4F836580FCC7'),
    'QR-FLYBACK': ('ST · L6565', '准谐振反激控制器，退磁检测、变频与控制特性',
                   'https://www.st.com/resource/en/datasheet/l6565.pdf'),
    'ACF-FORWARD': ('TI · SLUA535A', 'UCC2897A 有源钳位正激设计，功率级与钳位网络',
                    'https://www.ti.com/lit/an/slua535a/slua535a.pdf'),
}
SCOPE = {
    'BUCK': '已接入。异步 Buck，电压模式或峰值电流模式，成品电感。',
    'BOOST': '已接入。LM5022 异步峰值电流模式，校核低线满载、区间内电感纹波和 RHP 零点。',
    'BUCK-BOOST': '待接入。保留反相端口极性，按输入与输出电压之和校核器件应力。',
    'FLYBACK': '已接入。MP6005 定频峰值电流 SSR，满载 CCM 或 DCM，支持继承多路绕组并核对交叉负载。',
    'QR-FLYBACK': '待接入。联算励磁电感、退磁与谷底时间、工作频率范围和钳位应力。',
    'ACF-FORWARD': '待接入。分别设计励磁电感和各路滤波电感，检查复位、钳位及死区。',
}
# key, display label, display-unit multiplier to SI, default in display units
FIELDS = (
    ('vin_min', '最低输入电压 / V', 1., 18.), ('vin_max', '最高输入电压 / V', 1., 30.),
    ('vout', '输出端口电压 / V', 1., 12.), ('iout', '额定输出电流 / A', 1., 2.),
    ('imin', '最小负载电流 / A（可留空）', 1., 1.),
    ('fs', '开关频率 / kHz', 1000., 50.), ('ripple', '允许输出纹波 / %', .01, 1.),
    ('il_ratio', '满载电感纹波目标 / %', .01, 30.), ('pm', '最低相位裕度 / °', 1., 60.),
)
MODES = {'Voltage Mode': 'TPS40200 · 电压模式', 'Peak Current Mode': 'LTC3864 · 峰值电流模式'}
TOPOLOGY_MODES = {'BUCK': MODES, 'BOOST': {'Peak Current Mode': 'LM5022 · 峰值电流模式'},
                  'FLYBACK': {'Peak Current Mode': 'MP6005 · 定频峰值电流 / SSR'}}


def fields_for(topology):
    if topology == 'BUCK':
        return FIELDS
    if topology == 'FLYBACK':
        defaults = dict(vin_min=20.,vin_max=30.,vout=30.,iout=4./3.,imin=2./3.,fs=250.,il_ratio=65.)
        labels = dict(vout='反馈路端口电压 / V',iout='反馈路额定电流 / A',imin='反馈路最小电流 / A（可留空）',fs='MP6005 标称固定频率 / kHz',
                      il_ratio='CCM 满载 ΔI / 导通平均电流上限 / %')
        return (*( (k,labels.get(k,label),scale,defaults.get(k,v)) for k,label,scale,v in FIELDS),
                ('eta_guess','预设效率 / %',.01,90.),('duty_target','低线额定占空比目标 / %',.01,40.),
                ('kc','RCD 钳位比 Kc',1.,1.6),('rth','变压器至环境热阻 / K/W',1.,60.))
    defaults = dict(vin_min=9.,vin_max=18.,vout=24.,iout=1.,imin=.5,fs=200.)
    fields = [(key,'电感纹波 / 低线满载输入电流（%）' if key=='il_ratio' else label,
               scale,defaults.get(key,value)) for key,label,scale,value in FIELDS]
    return (*fields, ('eta_guess','预设效率 / %',.01,90.))
