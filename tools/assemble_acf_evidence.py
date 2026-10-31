"""Assemble independently completed, matching real-simulator checkpoints.

Never changes measured numbers. Refuses unavailable FRA or incomplete corners.
"""
import json
from pathlib import Path
import shutil
import sys
from zipfile import ZipFile,ZIP_DEFLATED
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from design_engine.specification import load_spec
from spice_studies import collect_study
from spice_comparison_report import write_report
from spice_export import export_project,project_files


def assemble():
    out=ROOT/'output/MP6005_三路有源钳位正激_20261028'
    archive=out/'仿真与设计计算对比报告.zip';doc=archive.with_suffix('.docx')
    with ZipFile(archive) as z:
        assert z.testzip() is None
        files={k:z.read(k) for k in z.namelist()}
    evidence=json.loads(files['comparison.json'])
    p=load_spec(json.loads((ROOT/'examples/33W_3OUT_ACF_MP6005.json').read_text(encoding='utf-8')))
    evidence['settings']=p['spice_config']
    for record in evidence['cases']:
        assert record['complete'] and record['nominal_comparable'] and record['acf_timing']['passed'],record['id']
        vin=int(record['voltage']);prefix='Vinmin' if vin==20 else 'Vinmax'
        for study,revision,key,label in (('fra','c','loop','FRA'),('cross','b','cross','交叉调整率')):
            folder=ROOT/f'artifacts/qa/acf/{study}_{vin}_{revision}'
            result=json.loads((folder/'result.json').read_text(encoding='utf-8'))
            if not result.get('complete') or study=='fra' and not result.get('available'):
                raise RuntimeError(f'{vin} V {study} 尚未通过：'+str(result.get('error')))
            meta=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
            if meta['hardware']!=record['hardware']:raise RuntimeError('冻结磁件不一致')
            if meta['resolved_controller']!=record['controller']:raise RuntimeError('补偿／控制器不一致')
            # Check both actual libraries, not merely a model-version label.
            original=record['id']+'/'
            for name in ('GenericACF_MP6005.lib','GenericFlybackPWM.lib','coupling.inc'):
                if (folder/name).read_bytes()!=files[original+name]:raise RuntimeError('模型／互感不一致：'+name)
            record[key]=result
            files.update(collect_study(folder,prefix+'_'+label))
            if study=='fra':files.update(collect_study(folder/'half_amplitude',prefix+'_'+label+'/half_amplitude'))
            for retry in folder.glob('retry_*'):
                if retry.is_dir():files.update(collect_study(retry,prefix+'_'+label+'/'+retry.name))
    evidence['qa']=json.loads((ROOT/'artifacts/qa/acf/nominal_qa.json').read_text(encoding='utf-8'))
    evidence['qa']['assembly']='Same frozen hardware/controller/libraries; real nominal, FRA and corner checkpoints assembled without altering measurements.'
    # The original 15-turn sections exceeded physical layer capacity. This
    # display-only migration changes no electrical parameter or simulation.
    for name in list(files):
        if not name.endswith('/design.json'):continue
        source=json.loads(files[name])
        if source.get('winding_config',{}).get('layer_plan')!=p['winding_config']['layer_plan']:
            files[name.replace('/design.json','/design_original_at_run.json')]=files[name]
            source['winding_config']['layer_plan']=p['winding_config']['layer_plan']
            source['__ui_migration']='15+15 sections split into valid 9+6 physical layers for UI; electrical network unchanged; original input retained beside this file.'
            files[name]=json.dumps(source,ensure_ascii=False,indent=2).encode('utf-8')
    write_report(doc,evidence)
    files['comparison.json']=json.dumps(evidence,ensure_ascii=False,allow_nan=False,indent=2).encode('utf-8')
    files[doc.name]=doc.read_bytes()
    files['完整示例.json']=(ROOT/'examples/33W_3OUT_ACF_MP6005.json').read_bytes()
    pending=archive.with_suffix('.pending.zip')
    with ZipFile(pending,'w',ZIP_DEFLATED) as z:
        for name,data in files.items():z.writestr(name,data)
    pending.replace(archive)
    shutil.copy2(ROOT/'examples/33W_3OUT_ACF_MP6005.json',out/'33W 三路有源钳位正激 MP6005.json')
    export_project(out/'LTspice_三路有源钳位正激.zip',p)
    folder=out/'仿真工程';folder.mkdir(exist_ok=True)
    for name,data in project_files(p).items():(folder/name).write_bytes(data)
    readme=['# MP6005 三路有源钳位正激验证示例','',
        '已将用户提供的多路反激配置改为有源钳位正激。原文件名写 40W，但各路功率为 30+1+2=33W；本示例按实际三路总功率 33W 命名。',
        '', '## 文件与使用','',
        '- 在新版软件导入 `33W 三路有源钳位正激 MP6005.json`，或从文件菜单选择 MP6005 三路正激示例。',
        '- 直接仿真：解压 `LTspice_三路有源钳位正激.zip`，用 LTspice 打开 `Flyback.asc`；文件名沿用导出接口，内部是有源钳位正激。完整解压目录也在“仿真工程”。',
        '- `仿真与设计计算对比报告.docx` 包含两端输入的原副边电流、驱动与钳位、输出电感、纹波、实际 FRA 和交叉调整率。',
        '- 同名 ZIP 保留模型、配置、日志、FRA 复数数据和 comparison.json；普通大瞬态 RAW 不打包。',
        '', '## 配置修改','',
        '| 项目 | 新配置 |','|---|---|',
        '| 输入与频率 | 20–30V，250kHz；OUT1 主反馈端口 30V |',
        '| 变压器匝数 | 原边 8；OUT1/2/3 为 30/13/6 |',
        '| 励磁与钳位 | 220μH；钳位电容 100nF；双边沿死区 100ns |',
        '| 各路输出电感 | 1mH / 1.5mH / 220μH；主路大电感用于覆盖 2W 轻载 CCM，体积与损耗需复核 |',
        '| 补偿 | 二型，KP=100，fz1=100Hz，fp1=15kHz；按同一参数计算与仿真 |',
        '| 其余数据 | 保留原输入范围、输出功率及最小功率、电容、导线和器件资料、两两 kij；原文件未覆盖的新续流管明确按固定值估算 |',
        '', '## 已完成的实际验证','',
        '| 输入 | 主路输出 V | OUT2 V | OUT3 V | FRA fc Hz | PM deg | 交叉角点 |',
        '|---|---:|---:|---:|---:|---:|---|']
    for c in evidence['cases']:
        m=c['measurements'];loop=c['loop']['simulation']['loop'];cross=c['cross']
        readme.append(f'| {c["voltage"]:g}V | {m["out1_before"]:.4f} | {m["out2_before"]:.4f} | {m["out3_before"]:.4f} | {loop["fc"]:.2f} | {loop["pm"]:.2f} | {cross["settled_cases"]}/{cross["total_cases"]} |')
    readme += ['',
        'FRA 为实际开关闭环注入，两端均做全频点半幅检查。主辅驱动无检测到交叠，磁复位伏秒检查通过。1–6路原生模板通过 ASC 与 CIR 电气等价核对；实际完整端点仿真使用本三路例子，不声称已仿真所有六路应用。',
        '', '未收敛角点先保留原扫描，再用同一硬件、固定该组负载从零启动进行独立长时间复核。报告标明复核来源，原曲线没有被替换或修平。',
        '', '## 如何看计算与仿真差异','',
        '标称计算器仍使用 CCM、小钳位纹波和预设效率的等效负担；非反馈路按匝比近似。实际 SPICE 使用全部 kij、DCR、整流压降与物理钳位，因此会有换流占空比损失和交叉调整。OUT2/OUT3 不是独立稳压输出，不能把其名义电压当作所有角点都满足的规格。',
        '', '交叉负载表另外提供未拟合仿真数据的一阶直流估算，包含 CCM/DCM、DCR 和换流损失；它不等同于完整互感矩阵开关解。所有偏差保留在报告与 JSON 中。',
        '', '## 工程范围','',
        '这是 MP6005 公开逻辑参考的通用行为模型，不是原厂完整芯片模型。实际 AC 耦合驱动、PSM、OVP、频率抖动、内部供电、非线性 Coss、反向恢复和磁芯饱和等仍需补充；不能据此保证 ZVS 或硬件合格。',
        '', '原 12×3.3mm 绕制窗口保留后，新增匝数的径向叠厚不足，软件会明确显示溢出。主副边交错的两个 15 匝区段已分别拆成 9+6 物理层，避免非法单层造成页面报错；需要按实际骨架重新选择窗口/线束/磁芯。没有人为加大窗口来制造“可绕制通过”。',
        '', '完整仿真较耗时；默认每次 LTspice 最多 2 线程，软件后台运行并可取消。可先关闭 FRA 与交叉负载扫描检查普通波形，再启用完整报告。',
        '', '详细模型说明见仿真工程中的 ACF_MODEL_GUIDE.md。']
    (out/'先读说明.md').write_text('\n'.join(readme)+'\n',encoding='utf-8')
    print('Complete real-evidence comparison:',doc)


if __name__=='__main__':assemble()
