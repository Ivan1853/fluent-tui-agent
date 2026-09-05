# 类似项目调研 / Related projects

Author: Manuel Sun

检索日期：2026-09-05。依据各项目公开 GitHub README、目录和文档进行比较；未安装或实际验证第三方工具。搜索包含 Fluent、ANSYS、TUI、Codex、SKILL.md、MCP 等组合，排除了与 ANSYS 无关的同名 Fluent 项目。公开索引并不完整，不能据此声称本项目是首个或唯一方案。

| 项目 | 类型与公开能力 | 与本项目的主要差别 |
|---|---|---|
| [cavoiie/fluent-cfd-skill](https://github.com/cavoiie/fluent-cfd-skill) | Codex Skill；CFD 建模、收敛、验证、错误恢复和 PyFluent MCP 使用指导。README 明确说明实时控制需要独立本地 PyFluent MCP server。 | 最接近通用 Fluent 工作流 Skill；执行层单独提供，公开 README 未确立 v221 直接 stdin/stdout 兼容性。 |
| [Bettertoo2/ansys-mcp-server](https://github.com/Bettertoo2/ansys-mcp-server) 与其 [ansys-fluent-tui-guide](https://github.com/Bettertoo2/ansys-mcp-server/tree/master/skills/ansys-fluent-tui-guide) | 本地 MCP + 内置 TUI Skill；Fluent/Mechanical/Geometry，MCP-to-TUI journal 映射、结构化错误与恢复建议。README 标明测试阶段，面向 ANSYS 2024 R2。 | 确实存在类似 TUI Skill，但版本目标和 PyAnsys/MCP 执行架构不同。它也明确区分完整与 partial journal，不能把未映射操作宣称已复现。 |
| [Cai-aa/CAE-Agent-Hub — Fluent MCP](https://github.com/Cai-aa/CAE-Agent-Hub/tree/main/MCP/Ansys/Fluent%20MCP) | CAE 工具集合中的 Fluent 执行模块：检测安装、批处理 journal、任务与日志跟踪；可选实时 PyFluent 会话运行 Scheme/TUI/Python 探测。 | 与本项目 Journal 执行层有明显交集；公开介绍没有证明与本项目相同的 v221 逐提示符 PIPE 闭环。其主仓库 Skill 列表侧重 Abaqus，不应把 Fluent MCP 直接称作同名 Codex Skill。 |
| [jiweiqi/fluent-mcp-server](https://github.com/jiweiqi/fluent-mcp-server) | Fluent 官方文档导航 MCP，返回手册链接与主题建议。 | 当前 README 将 PyFluent 会话控制列为后续计划；不能将文档导航误当成已实现的 Solver 控制。 |

## 如何选择

需要 CFD 建模与收敛判断，可参考 `fluent-cfd-skill`；需要 ANSYS 2024 R2 多产品 MCP 与 TUI 映射，可评估 `ansys-mcp-server`；需要更广泛 CAE 工具接入，可评估 `CAE-Agent-Hub`。选择前仍应在自己的软件版本和许可证环境验证。

本项目专注 Windows **Fluent 2022 R1 / v221** 的直接 TUI 执行、当前 prompt 观察和有界修正。其区别是明确的实现和本地测试范围，不能推导为第三方方案做不到同样功能，也不能推广成所有 Fluent 版本均已支持。

## English summary

Related Fluent skills and MCP servers already exist. The closest workflow skill is `cavoiie/fluent-cfd-skill`; `Bettertoo2/ansys-mcp-server` includes an actual TUI guide skill targeting 2024 R2; `CAE-Agent-Hub` offers a Fluent batch/live execution module. `jiweiqi/fluent-mcp-server` currently documents a manual-navigation service, with execution on its roadmap. The comparison concerns documented scope, not a benchmark or an exhaustive novelty claim.
