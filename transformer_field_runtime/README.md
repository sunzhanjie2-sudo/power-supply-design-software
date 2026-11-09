# 内置变压器场解运行内核

由本项目已接入的“变压器耦合参数提取工具” v0.1.2 提取求解、几何契约与报告模块，以独立包维护。它不依赖原研究文件夹、独立提取器 EXE、用户工程、预先生成的波形或另一套 Python 环境。上游逐文件哈希与本地变更见 `SOURCE_MANIFEST.json`；上游自身的几何适配来源另见 `vendor-provenance.json`。

桌面程序通过 `--field-worker doctor|check|cad|mesh|run` 在独立子进程中调用此内核，不启动提取器 GUI。正式输入仍是设计软件冻结的几何 ZIP 与自动绑定的 `transformer-coupling-tool.project.v1` 设置；其结构、输入哈希、结果矩阵、能量与产物检查没有放宽。Elmer 和 ElmerGrid 由本机设置指定，不随软件安装或修改。

每个任务由父进程指定 `POWER_DESIGN_FIELD_WORKDIR`，Elmer 栈启动副本、Matplotlib 缓存均放在该目录；运行不写安装目录。Python/打包目录仅作为只读模块和资源输入。Windows Job Object 继续负责退出/取消时终止本任务整个进程树。

内核保留原模型边界：零偏置、线性静磁场、圆形绕线路径和闭合等效匝；不表示已覆盖螺旋引线、涡流、高频阻抗、非线性材料或实物收敛验证。

Gmsh 4.15.2 与 meshio 5.3.5 作为 Python 运行依赖由构建收集。第三方许可见 `THIRD_PARTY/`；集成不另行授予或变更项目开源许可证。Gmsh 官方项目与源码：<https://gmsh.info/>、<https://gitlab.onelab.info/gmsh/gmsh>；meshio：<https://github.com/nschloe/meshio>。
