# 工程验证与验收

本页属于个人桌面版及共享 Python 数据模型。它汇总已完成的计算、匹配配置的电路仿真证据、用户手工录入和整改记录，不新增一套电源公式，也不自动启动电磁或电路仿真。

## 使用

1. 打开“工程评审 → 工程验证与验收”。已有当前工况快照可以先显示，另一端未计算时保持空白。
2. 点击“刷新 Vinmin / Vinmax 计算”显式在后台准备同套硬件的双端结果。翻页、绘图及编辑验收阈值不会触发此求解。
3. 选择一行修改目标。`range` 表示允许的闭区间，其他关系支持 `<=`、`>=`、`<`、`>`。空阈值表示未定义，不是零。
4. 选择判定必需的来源。默认同时要求计算、仿真和实测录入；只要求计算时，满足结论仅适用于计算，不代表完成仿真或实测。
5. “导入仿真证据…”由主程序加载带当前输入指纹的证据，并保存外部文件引用。当前联合任务的已采用硬件一致时，也能读取其电路证据。普通旧报告缺少输入匹配信息时不自动认定为当前数据。
6. 手录实测需填写来源、测试条件，并显式确认对应当前硬件与工况。软件不证明仪器校准或数据真实性。修改目标或输入不会自动重新绑定旧测量。
7. 使用“应用目标”“保存两端实测录入”或“应用整改记录”将编辑写入当前工程。最后保存设计 JSON 或系统工程，才能长期保留这些记录。

主表六列同时展示两个输入工况，每个数值格依次为“计、仿、录”。选择指标后，详情给出百分偏差、每个来源的阈值余量和出处。普通字号下两端同屏；大字号保留完整列宽并可横向滚动，整页可纵向滚动。

输入变化、证据引用不可读、文件哈希改变、仿真不完整或逐周期检查失败，都不能据此得到通过结论。关闭整改项需要对应当前输入的验证说明，输入改变后旧关闭证据会失效。所有指标均停用也不判通过。

## 保存格式

顶层 `engineering_acceptance` 为版本 1 的对象，内部数值沿用该指标的 SI 单位；效率为比例，例如 0.93。它不改变功率级、补偿或器件参数。

```json
{
  "version": 1,
  "criteria": [{
    "id": "out1_voltage",
    "metric": "out1_voltage",
    "comparison": "range",
    "lower": 11.4,
    "upper": 12.6,
    "limit": null,
    "enabled": true,
    "required_sources": ["calculation", "simulation", "measurement"],
    "note": "产品端口电压范围"
  }],
  "measurements": [{
    "id": "out1_voltage:Vinmin",
    "criterion_id": "out1_voltage",
    "case_id": "Vinmin",
    "value": 12.05,
    "source": "示例格式：台账编号和仪器编号",
    "conditions": "示例格式：输入电压、负载、温度、测量点及带宽",
    "evidence_ref": "示例格式：测试数据文件或报告编号",
    "input_fingerprint": "由程序绑定当前输入",
    "origin": "manual-entry",
    "recorded_at": "由程序填写时间"
  }],
  "issues": [{
    "id": "ISSUE-001",
    "title": "示例格式：启动尖峰待复核",
    "description": "现象及原因",
    "action": "整改措施",
    "owner": "负责人",
    "status": "open",
    "evidence": "验证或关闭依据",
    "input_fingerprint": "由程序绑定当前输入",
    "updated_at": "由程序填写时间"
  }]
}
```

`criteria[].name/unit` 可选；内置指标未覆盖这些字段时保留原名称和单位。整改状态编码为 `open`、`in_progress`、`closed`，界面显示“待整改、整改中、已关闭”。配置只记录已编辑覆盖项；默认阈值从当前计算检查及输入目标投影，不与某个示例硬编码绑定。

## 维护接口和匹配原则

- `engineering_acceptance.normalize(config)`：严格校验并返回独立副本；未知数值为 `null`，拒绝 NaN、无穷、布尔数值、未知版本和重复 ID。
- `input_fingerprint(p)`：解码显示数量级，展开默认输入，覆盖物理参数、曲线点、绕制位置和模型设置。排除验收数据、显示所选 Vin 和内部/历史记录。旧单点 Vin 规范为相同上下限，真实 Vin 变化仍会改变指纹。
- `report_snapshot(p, range_result=None, joint_record=None, spice_evidence=None)`：只投影已完成数据。支持 runtime 端点 bundle、保存快照，及明确具名的单端快照；不会补造另一端结果或读取任意文件。
- `manual_measurement(...)`：显式生成当前输入绑定的手录测量，来源固定标记 `manual-entry`。
- `AcceptancePanel`：宿主通过 `get_spec/on_apply/on_refresh/on_import_evidence` 与三个证据 getter 提供读写和后台任务；Tk 控件只在主线程访问。

报告快照 `rows[].cases.Vinmin/Vinmax` 提供三来源数值、`states`、`margins`、`sources`、`delta_simulation/delta_measurement`（%）、`status/reason`。总览包含各状态计数与未闭环问题数；不能把“有数值”当成“达到阈值”，也不能把“达到阈值”当成硬件认证。

原生 SPICE 证据必须有匹配指纹及 `powerdesign-spice-comparison-2` schema；适配封装也可提供 `{input_fingerprint, evidence, source}`。联合记录比较当前参数与 `adopted_config`，不能用 `original_config` 的匹配为不同回填硬件背书。相同 Vin 但手动 MOS 事件不同的两个具名工况不会互相补齐。

状态为 `pass/review/undefined/stale/na`。`undefined` 可能表示目标缺失、数据缺失、仿真未完成或范围未覆盖。只有当前配置、所需来源、目标阈值均满足且无未闭环整改项，才能形成对应范围的满足结论。当前未扩展温度迭代、全容差统计、PCB 场解或自动仪器控制。

针对性验证入口为 `tests/engineering_acceptance_check.py`、`tests/engineering_acceptance_ui_check.py`；主程序保存重开、后台刷新及证据文件校验由各集成测试覆盖。

## 报告阅读顺序

设计报告首先说明评审结论和证据覆盖，再给共同需求、硬件和拓扑。随后依次展开功率级、器件与损耗、电容、磁件、环路和补偿，各模块固定左 Vinmin、右 Vinmax，末尾集中模型边界、未闭环问题和追溯信息。共同输入和计算关系只保留一份；表格及主要图像按同一指标对齐。较宽的拓扑及原生数学公式保留全宽，避免缩小后无法阅读。

联合报告先解释磁件结构、场解矩阵、检查及漏感裕量如何回填，再呈现回填硬件的设计计算和实际电路对比，最后回到验收及整改。流程完成与工程验收满足分别给出；启动尖峰不使用稳态窗口数值替代。仿真仅完成一个端点时另一列明确缺失，不补造数据。

Excel 按模块分 Sheet，并设独立验收页。左右两侧保持同一工况顺序、相同指标和单位，方便评审横向查阅。

`__acceptance_evidence` 只存本机外部 JSON/ZIP 路径和其中证据内容的 SHA-256，不把 RAW 或整份仿真工程嵌入配置。移动电脑或文件后需重新导入新位置；读取失败或内容改变会显示原因，不沿用旧的绿色结论。联合记录以已采用硬件 `adopted_config` 为匹配依据。
