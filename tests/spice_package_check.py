"""The packaged modules/resources must be exactly the verified implementation."""
from pathlib import Path
import marshal
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from device_curve_package_check import normalized
from PyInstaller.archive.readers import CArchiveReader


def check(folder):
    folder=Path(folder)
    desktop=(folder/'SwitchingPowerSupplyDesign_V0.exe').is_file()
    archive=CArchiveReader(str(folder/('SwitchingPowerSupplyDesign_V0.exe' if desktop else 'PowerDesignWeb.exe')))
    pyz=archive.open_embedded_archive('PYZ.pyz')
    for name in ('loss_model','nonisolated','nonisolated_spice','parasitics','parasitic_ringing','parasitic_spice','parasitic_report','example_catalog','comp_design','compensation_report','voltage_nodes','coupled_flyback','multi_output_loop','output_capacitors','loop_report','word_math','transformer_turns','spice_export','spice_circuit','spice_runtime','spice_studies','spice_analysis','spice_comparison_report','power_stage','design_engine.specification','controller_logic','qr_spice_export','qr_spice_settings','qr_spice_analysis','qr_loop','acf_spice','acf_cross','acf_periodic','acf_loop')+ (('parasitic_ui','spice_ui','spice_logic_ui') if desktop else ('web_app.worker','web_app.metadata','web_app.server','web_app.actions')):
        source=ROOT/(name.replace('.','/')+'.py')
        assert normalized(pyz.extract(name))==normalized(compile(source.read_text(encoding='utf-8-sig'),str(source),'exec')),name+' stale'
    for name in ('capacitor_banks','capripple','waveforms','isolated_outputs','component_management','topology_diagram','multi_output_charts','design_checks','report_docx','loop_tuning','plants','design_engine.reporting','design_engine.service','design_engine.catalog')+ (('design_api','capacitor_ui','parameter_panel','output_parameter_panel') if desktop else ()):
        source=ROOT/(name.replace('.','/')+'.py')
        assert normalized(pyz.extract(name))==normalized(compile(source.read_text(encoding='utf-8-sig'),str(source),'exec')),name+' stale'
    if desktop:
        source=ROOT/'main.py'
        assert normalized(marshal.loads(archive.extract('main')))==normalized(compile(source.read_text(encoding='utf-8-sig'),str(source),'exec')),'desktop menu stale'
    for relative in ('resources/spice/GenericFlybackPWM.lib','resources/spice/GPWM_CORE.asy',
        'resources/spice/GFLY_CTRL2.asy','docs/FLYBACK_SPICE.md','resources/spice/GenericQR_L6565.lib',
        'resources/spice/GQR_CTRL.asy','resources/spice/QR_ZCD.asy','resources/spice/QR_Flyback_1.asc',
        'resources/spice/QR_Flyback_1.plt','docs/QR_L6565_SPICE.md','docs/QR_TYPE2_COMPENSATION.md','examples/90W_QR_L6565_300V.json',
        'examples/90W_QR_L6565_300V_TUNED.json','resources/spice/GenericACF_MP6005.lib',
        'resources/spice/GACF_CTRL.asy','resources/spice/PowerPmos.asy','resources/spice/PowerChoke.asy',
        'docs/ACF_MP6005_SPICE.md','docs/ACF_PERIODIC_MODEL.md','docs/PARASITIC_MODELS.md','docs/BUILTIN_EXAMPLES.md',
        'examples/33W_3OUT_ACF_MP6005.json','examples/33W_3OUT_ACF_MP6005_COMPACT.json',
        'examples/40W_CCM_3OUT_FLYBACK.json')+tuple(f'resources/spice/Flyback_{i}.asc' for i in range(1,7))+tuple(f'resources/spice/ACF_Forward_{i}.asc' for i in range(1,7)):
        assert (ROOT/relative).read_bytes()==(folder/'_internal'/relative).read_bytes(),relative+' stale'
    for relative in ('resources/spice/GenericBuckBoostPWM.lib','resources/spice/Buck.asc','resources/spice/Boost.asc','resources/spice/NisoPmos.asy','resources/spice/NisoNmos.asy','resources/spice/NisoController.asy','docs/BUCK_BOOST_SPICE.md','examples/24W_BUCK_VM_TPS40200.json','examples/24W_BUCK_PCM_LTC3864.json','examples/24W_BOOST_PCM_LM5022.json'):
        assert (ROOT/relative).read_bytes()==(folder/'_internal'/relative).read_bytes(),relative+' stale'
    if not desktop:
        for name in ('design_theme','pcs_workspace','pcs_reports','docx_layout','xlsx_report_writer'):
            source=ROOT/(name+'.py')
            assert normalized(pyz.extract(name))==normalized(compile(source.read_text(encoding='utf-8-sig'),str(source),'exec')),name+' stale'
        for name in ('aux-calculator.js','aux-calculator.css'):
            assert (ROOT/'web_app/pcs_static'/name).read_bytes()==(folder/'_internal/web_app/pcs_static'/name).read_bytes(),name+' stale'
        import re
        base=folder/'_internal/web_app/static'
        html=(base/'index.html').read_text(encoding='utf-8')
        for ref in re.findall(r'(?:src|href)="(/assets/[^"]+)"',html):
            assert (base/ref.lstrip('/')).is_file(),ref+' missing'
        assert (ROOT/'web_app/static/index.html').read_bytes()==(base/'index.html').read_bytes()
    print('Verified frozen SPICE modules and resources:',folder)


if __name__=='__main__':
    for folder in sys.argv[1:]:check(folder)
