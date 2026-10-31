# 第一阶段：统一计算内核与接口

日期：2026-10-22。此阶段不建立网站、不部署公网、不改电气公式，也不替换现有桌面操作方式。

## 1. 当前边界

新增 `design_engine/` 是应用服务层。现有 Python 电气计算模块仍是唯一公式实现，不把计算复制到 JavaScript、报告模板或 AI 提示词中。

| 模块 | 职责 |
| --- | --- |
| `specification.py` | 从旧 API 原样提取的配置解析，兼容 SI 数值、`v/u`、历史别名及内嵌器件曲线 |
| `catalog.py` | 从 `power_stage.DEFAULT_PARAMS` 和既有参数元数据生成目录、单位说明和 JSON Schema |
| `calculation.py` | 单次工作点、波形、损耗、环路和检查的统一运行时快照构造器 |
| `service.py` | 参数校验、选定工况/双端点计算、报告准备、快照归档和报告导出 |
| `reporting.py` | 已算结果到兼容 JSON 设计报告的投影，不重新设计硬件 |
| `contracts.py` | 严格 JSON 转换、非有限数说明及内容哈希 |

`design_api.py` 保留旧函数名称与既有结果字段。`analysis_workflows.evaluate()`、输入端点计算共用一个快照构造器。桌面报告的后台准备也调用服务层；GUI 不需要运行 HTTP 服务。

参数默认值没有另抄一套。数值/模型规则仍由已有校验函数执行；JSON Schema 主要约束传输类型和字段结构，不等同于全部电路可行性规则。每路输出字段复用 `isolated_outputs.RAIL_KEYS`。当前参数目录中的可见性元数据尚不是完整的网页表单生成器。

## 2. 文件夹边界

```text
本项目/
  main.py、*_ui.py、*_panel.py     现有桌面界面
  design_engine/                  新的统一服务和数据约定
  power_stage.py、loss_model.py…   既有计算公式模块，暂不搬家避免破坏导入
  report_docx.py、report_xlsx.py…  既有报告排版器
  cli.py、mcp_server.py            命令行与 AI 调用入口
  examples/                       正式配置与格式示例
  tests/fixtures/                 受版本管理的回归基准、曲线样例
  tools/                          清理及串行回归工具
  artifacts/                      自动生成的检查日志，Git 忽略
  docs/、resources/               当前文档、正式参考图与图标
  packaging/、releases/           构建定义与完整可复制发布包
  archive/                        历史文档生成工具和旧发布等
  related_projects/、user_data/   独立项目与不打包的用户库
```

2026-10-23 已将独立提取项目与视频制作工程归入 `related_projects/`，未合并进计算内核；原用户库另在 `user_data/`，旧产物可恢复归档。外部截图描点项目 `<本机路径，不随源码分发>` 不在改动范围。当前完整位置与重建入口见 [项目结构](PROJECT_STRUCTURE.md)。

## 3. Python 使用

```python
import json
from pathlib import Path
from design_engine.service import calculate, validate_spec, export_report, read_snapshot

spec = json.loads(Path('examples/40W_CCM_FLYBACK.json').read_text(encoding='utf-8'))
spec.update(V_in_min=24., V_in_max=40., input_voltage_case='max')

validation = validate_spec(spec)
if not validation['ok']:
    raise ValueError(validation['issues'])

run = calculate(spec, analysis='endpoints', include_efficiency=True)
payload = run.to_dict()  # 完整的、可 json.dumps(..., allow_nan=False) 的数据
run.save('artifacts/design_snapshot.json')
saved = read_snapshot('artifacts/design_snapshot.json')  # 校验版本及内容哈希
export_report(run, 'artifacts/design.xlsx')
export_report(run, 'artifacts/design.docx')
```

`analysis='selected'` 按当前显示端点计算；旧标量输入保留原来的单工作点语义。`analysis='endpoints'` 计算 Vinmin/Vinmax，同一套磁件在 Vinmin 解析并固定，补偿参数不随端点自动整定。相同电压仍保留两个具名工况，已有四事件手动平台差异继续生效。

`include_efficiency=True` 在计算准备阶段完成报告效率扫描。只有准备好的双端点快照能经服务导出报告；缺少扫描时会明确拒绝，不在导出过程中偷偷补算。报告从快照复用环路结果和检查项。直接调用老报告排版器的历史补算兼容路径暂时保留，后续新功能统一走服务层。

`include_cross_regulation=True` 沿用现有模型适用性判断；不表示所有拓扑都支持交叉调整率。精简查看可用 `run.to_dict(include_waveforms=False, include_details=False)`，保留摘要、检查和来源，不返回庞大的详细结果。专用 `wf` 是对外时域波形，内部 `coupled_solution` 不在 JSON 中重复导出。

## 4. 快照约定

- `schema = power-design.snapshot.v1`：传输结构版本，和电气模型版本分别管理。
- `spec`：解析后的用户输入，顶层电气量转为现有 SI 约定；经验磁损系数 `k/α/β` 的单位约定不改变。界面百分数仍以比例保存。嵌套的自定义磁芯输入/未激活草稿保留既有格式，解析后的实际几何应读取 `hardware/result`，不能盲目把其中每个原输入数值当作 SI。
- `cases`：工况名称、输入电压、参数、结果、摘要、检查、环路错误、效率扫描。传函对象只留在运行时，不序列化为字符串或 pickle。
- `hardware`、`hardware_reference`：固定硬件及参考工况，不让两个输入端点各自重新选型。
- `provenance`：模型版本、可用源码 SHA-256、代码指纹、Python/依赖版本、内嵌器件曲线哈希。源码不可用的冻结包不能假称已记录完整源码版本。
- `numeric_diagnostics`：NaN/±Infinity 转为 JSON `null`，同时给出字段路径和原数值类别；不能把 `null` 当零。复数以 `real/imag` 表达。
- `snapshot_id`：对规范内容计算 SHA-256，时间戳不参与。`read_snapshot` 能发现内容损坏/修改，但哈希不是数字签名或防伪证明。
- `ok`：计算流程完成，不代表所有工程检查通过。检查项与模型限制必须同时查看。

保存的 JSON 是只读审计记录，可以查看或取出 `spec` 重新计算；本阶段不提供从 JSON 无损恢复 Python 传函对象、继续执行报告排版的能力。需要导出时保留内存中的 `DesignRun`。跨机器重新求解可能存在浮点或库版本差异，不能承诺位级相同。

## 5. CLI 与 AI 接口

```powershell
python cli.py validate --spec examples/40W_CCM_FLYBACK.json
python cli.py parameters --schema --out artifacts/input.schema.json
python cli.py snapshot --spec examples/3_OUTPUT_COUPLED_FLYBACK.json --analysis endpoints --out artifacts/design_snapshot.json
python cli.py report --spec examples/40W_CCM_FLYBACK.json --out artifacts/design.xlsx
```

旧 `design/corners/transient/autotune` 命令保留。`snapshot` 成功只表示结果可生成，工程检查仍需查看；输入或求解失败退出码为 2，协作取消为 130。旧 `design` 命令原有“检查未通过返回 1”的行为不变。

现有 MCP 服务新增 `validate_spec`、`parameter_schema`、`design_snapshot`，旧工具继续可用。新快照工具返回精简结果，避免把多兆字节轨迹塞给 AI。实际使用 MCP 需要单独安装可选依赖；并未新增任何云端 AI 调用或自动上传设计资料。

## 6. 回归与开发约束

```powershell
python -m pip install -r requirements-dev.txt
# 如需运行 MCP 工具：python -m pip install -r requirements-mcp.txt
python tools/check_engine.py
python tools/check_engine.py --gui --reports
```

运行器串行启动白名单测试，每个脚本有超时，日志存入 `artifacts/checks/时间戳/`。不会运行 `update_*` 等文档修改脚本。GUI 测试只操作测试自己创建的窗口；真实报告测试在临时目录中创建并清理文件。

`tests/fixtures/engine_baseline_20261022.json` 在服务重构之前采集，覆盖单路反激、Buck、DCM、正激、六路输出、耦合反激、MP6005。基准证明数值兼容，不证明模型符合实物；已知 MOS 应力/损耗电压区分、QR 非理想 ZVS、温度迭代等缺口并未在本次重构中修正。禁止通过自动覆盖基准掩盖回归。

`requirements*.txt` 固定的是本次 Windows/Python 3.13 实测依赖，不保证其他系统版本未经测试即可复现。

## 7. 第二阶段以前不要做的事

不在前端重写公式，不让 AI 绕开检查直接改实物设计，不让报告重新优化器件，不把本地仿真软件变成任意命令执行接口。未来 HTTP 层需另行处理任务隔离、取消、权限、文件路径和并发限制。本阶段没有 HTTP 监听端口、账号系统、局域网共享或公网部署。

本次只更新源码与接口，现有 `dist/Custom_core_geometry_20261021/` 发布包保留且未替换；可用 `python main.py` 运行重构后的桌面源码。

本次实际执行范围与结果见 [验收记录](ENGINE_SERVICE_QA_20261022.md)。
