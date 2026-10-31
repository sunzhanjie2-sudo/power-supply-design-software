# PI 控制器（2026-10-08）

> 历史记录：此更新已于 2026-10-09 撤回。当前程序恢复 auto / type2 / type3 与原版⑧页元件简化支路；旧 PI 配置迁移为 auto，需重新核对环路。下文只描述旧版行为，不是当前使用说明。

左侧 Controller、④自动整定与⑧元件换算共用 `auto / PI / type2 / type3`。
显式选择决定实际补偿器，不会被电压模式/峰值电流模式覆盖；控制模式仍决定功率级对象。
旧配置没有 `controller_type` 时按 `auto`：PCM 用二型，VM 用三型。

## 模型与参数

PI 的精确模型为：

`Gc(s) = Kp + Ki/s = KP·(1+s/ωz1)/s`，`ωz1=2πfz1`。

为兼容已有配置，`KP` 字段表示 `Ki`，并非标准 PI 的比例系数；`Kp=KP/(2πfz1)`。
PI 只使用 Ki/KP 与 fz1。二型额外使用 fp1；三型再使用 fz2/fp2。
未参与的参数隐藏，保留旧值便于切换，但不会添加任何额外零极点。
PI 的高频幅频趋于 Kp、相位趋于 0°；二型则在 fp1 后继续衰减。
右下图是总开环 `Gc·Gvc`，仍会包含对象自身的极点和右半平面零点。

## 自动整定

对目标 fc、PM，在 fc 处取得对象增益 M 和连续相位 φ：

`boost=PM−90°−φ`，`K=tan(boost)`，`fz1=fc/K`。

`Ki=KP=2πfc/(M·sqrt(1+K²))`，`Kp=Ki/(2πfz1)`。

正增益 PI 要求 `0°<boost<90°`（计算留 0.001° 数值边界）。
无法达到目标时 GUI 提示原因并保留原增益/频率；API 返回 `feasible=false`、空 `spec_updates`。
PI 无额外高频滚降；实际运放有限带宽、采样延迟、光耦带宽、噪声与硬件环路稳定性需单独检查。

## ⑧ 元件换算

参考图仍使用原三型电路的元件命名，图上方标明所需省略支路：

| 网络 | PI | 二型 |
|---|---|---|
| 普通运放 | C2/C3 不焊 | C3 不焊，保留 C2 高频极点 |
| 跨导运放 | C1/C3 不焊，指定上分压 R1 | C1 不焊，保留 C3，指定 R1 |
| TL431+光耦，无快车道 | 不支持理想 PI（光耦自身极点） | C3 不焊，光耦支路形成 fp1 |
| TL431+光耦，快车道 | 不支持 | 请改用无快车道网络 |

反向计算根据实际电容自动识别 PI/二型/三型并同步④选择，仅写回有效频率。
旧 Python 元件 API 的 `type2=True` 历史上去掉了两个有限极点，实际上表示 PI；为保持旧调用兼容未改变。
新代码应使用明确的 `controller_type='pi'/'type2'/'type3'`。

## 验证与调用

`python tests/controller_check.py --gui` 检查精确零极点、整定幅值/相位、GUI 类型一致性、
配置回读、元件网络复数传函正反算，并渲染 `_tmp_pi_qa/pi_loop.png`。

API/CLI 示例（与 GUI 配置格式不同，为 API SI 参数）：

`python cli.py autotune --spec examples/PI_BUCK.json --fc 3000 --pm 65`

成功返回的 `spec_updates` 只有 `controller_type/KP/fz1`，不包含 PI 不使用的高频极点。

参考：二型结构与运放/OTA 网络依据 [TI SLVA662](https://www.ti.com/lit/an/slva662a/slva662a.pdf)；
PI 结构参考 [TI Teaching Your PI Controller to Behave](https://www.ti.com/document-viewer/lit/html/ssztcg4)。
