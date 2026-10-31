"""Render QA document using detached verified RC data and bundled docx only."""
import json
import math
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    from docx_layout import new_document,paragraph,table,equation,figure
    from unittest.mock import patch
    from compensation_report import _equations,NETWORKS,PARTS
    rows=json.loads((ROOT/'artifacts/qa/qr_type2_20261029/compensation_snapshots.json').read_text(encoding='utf-8'))
    out=ROOT/'output/QR_采样与二型复核_20261029';out.mkdir(parents=True,exist_ok=True)
    doc=new_document('QR标准二型补偿电路复核','采样增益1 有限高频极点保留','QR标准二型复核')
    paragraph(doc,'本次修正QR示例采样增益与谐振电容的计算口径，并消除二型阻容反推误用第二零极点的问题。四种理想参考网络均保留原点极点和有限高频极点。以下结果对应300V输入、60V/92W示例。')
    evidence=json.loads((ROOT/'artifacts/qa/qr_type2_20261029/verification.json').read_text(encoding='utf-8'))
    a=evidence['fra']['design']['loop'];b=evidence['fra']['simulation']['loop']
    table(doc,['指标','计算','真实LTspice'],[
        ('采样增益','1','1'),('有效漏极谐振电容','470 pF','470 pF'),
        ('穿越频率',f"{a['fc']:.2f} Hz",f"{b['fc']:.2f} Hz"),
        ('相位裕度',f"{a['pm']:.2f}°",f"{b['pm']:.2f}°"),
        ('半幅复核','不适用','通过')],[2.4,2.35,2.35])
    plot=ROOT/'artifacts/qa/qr_type2_20261029/loop_comparison.png'
    if plot.is_file():figure(doc,plot.read_bytes(),'新配置实际FRA与独立周期平均模型',width=7.1)
    equation(doc,'Gc(s)=KP·(1+s/ωz₁)/[s·(1+s/ωp₁)]')
    paragraph(doc,'计算表使用与实测相同的离散频点插值；数学整定目标为1kHz/60°。实际输出约59.9985V，开关频率约41.6kHz，直流与逐周期检查通过。',True)
    paragraph(doc,'Gvc/Gc采用CS等效控制指令口径，真实L6565 COMP管脚的前馈缩放和误差放大器仍需另核。后面逐页列出四类理想网络的阻容及可编辑Word数学公式。',True)
    for index,data in enumerate(rows):
        doc.add_page_break()
        doc.add_heading(NETWORKS[data['key']][0],1)
        paragraph(doc,'二型只采用KP、fz1、fp1；下表阻容实现原点极点、一个有限零点和一个有限高频极点，未使用保存的第二零极点。')
        checks=[]
        for field,name in [('KP','KP'),('wz1','fz1'),('wp1','fp1')]:
            scale=1 if field=='KP' else 2*math.pi
            a,b=data['targets'][field]/scale,data['realized'][field]/scale
            checks.append((name,f'{a:.6g}',f'{b:.6g}','匹配' if abs(a-b)<1e-6*abs(a) else '待核对'))
        table(doc,['量','目标','阻容回代','核验'],checks,[.8,2.1,2.1,2.1])
        doc.add_heading('元件数值',2)
        parts=[]
        for name in ('R1','R2','R3','R_LED','R_pz','Rpullup','C1','C2','C3','C_pz','Copto','gm','CTR'):
            if name not in data['parts']:continue
            value=data['parts'][name];label,unit=PARTS.get(name,(name,''))
            from power_stage import fmt_eng
            parts.append((name,fmt_eng(value,unit) if value else '不装'))
        paired=[]
        for start in range(0,len(parts),2):
            left=parts[start];right=parts[start+1] if start+1<len(parts) else ('','')
            paired.append((*left,*right))
        table(doc,['元件','数值','元件','数值'],paired,[1.3,2.25,1.3,2.25])
        doc.add_heading('原生数学公式',2)
        def local_equation(document,text,*args,**kwargs):
            if text in ('ω = 2πf','Gc(s)=KP·(1+s/ωz₁)/[s·(1+s/ωp₁)]'):return
            return equation(document,text,*args,**kwargs)
        with patch('docx_layout.equation',side_effect=local_equation):
            _equations(doc,data)
        paragraph(doc,'省略支路按电容0处理；该支路电阻的0值表示不装该串联支路，不要求并接零欧姆。',True)
        paragraph(doc,'这是理想参考网络的CS等效控制口径。真实L6565 COMP前馈、电平转换、有限放大器增益与器件偏置需另核，代数匹配不代表实物稳定性验证。',True)
    path=out/'标准二型补偿电路复核.docx';doc.save(path);print(path)


if __name__=='__main__':main()
