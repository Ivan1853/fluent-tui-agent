---
name: fluent-tui-agent
description: 在 Windows 上直接执行、观察、诊断和修正 ANSYS Fluent 2022 R1（v221）的 TUI 与 journal。用于“用 Fluent 执行”“运行 Fluent TUI”“修改 Fluent 设置”“执行 .jou”“修复 TUI 报错”或“读取 case 后设置边界条件”等请求；保留真实会话、逐提示符响应和有界恢复，不依赖 PyFluent。
metadata:
  author: Manuel Sun
  short-description: Fluent v221 TUI execution and feedback agent
---

# Fluent TUI agent

Fluent 的真实 console/transcript 输出是判断命令结果的最终依据。模型知识只产生候选命令。目标固定为 **Fluent 2022 R1 / v221 / 22.1.x**；不使用 PyFluent，不把新版本文档当作 v221 可用性的证明。

这是执行与观察工具，Codex 负责将用户目标转成计划、解释物理含义并提出修正假设。脚本执行可验证的状态转换、记录证据、阻止错误状态的输入并限制重试；未知修正不会由脚本凭空生成。

## 开始任务

1. 明确用户目标、case/data、单位、目标 zone/variable 和保存位置。原始目标已授权的步骤不重复请求批准。先阅读 [交互规则](references/tui_interaction_rules.md)；使用计划时阅读 [API 与计划 schema](references/api_and_plans.md)。
2. 在本 Skill 目录运行 `python scripts/fluent_driver.py discover --save`。检查所有候选、选择理由和 `valid_v221`。找不到则请求正确安装位置；不得自动改用其他版本。检测只搜索配置、环境变量、常见安装树及 PATH；自定义盘位置加入 `search_roots`。
3. `python scripts/fluent_driver.py start`。该 CLI 启动本地长期存活的 broker，后续 `send/status/observe` 操作同一个 Solver。只有真实启动 banner、根提示符、只读查询输出和再次出现的根提示符均验证后，`available=true`。
4. PIPE 失败时自动尝试原生 Windows ConPTY。两者都失败时保留诊断并转 [Journal 后端](references/api_and_plans.md)。后端测试失败不等于 Fluent 未安装。许可证、沙箱、本地通信、编码都可能阻止启动。

## 必须执行的反馈闭环

正常：**PLAN → INSPECT → EXECUTE → OBSERVE → VERIFY → CONTINUE**。

错误：**PLAN → EXECUTE → OBSERVE → DIAGNOSE → CORRECT → RETRY → VERIFY**。

每个关键步骤读完整 `output`、事件、`prompt_after`、`state_after`、warning/error 和必要的物理验证结果。`success=true` 只表示这一次输入获得了新提示符且未识别到错误；它可能停在子提示符，不能证明整个命令结束，更不能证明 CFD 设置正确。计划的 `expect:"prompt"` 要求回到 ROOT/MENU；对初始化、patch、边界条件等，再用实际字段/设置报告验证目标值。只有 `Done.`、退出码 0 或返回 `>` 都不单独证明 CFD 任务成功。

先用 `status` 确认“Fluent 当前在等待什么”。输入分为：

- `kind:tui`：ROOT/MENU 中的完整绝对路径，例如 `/solve/patch`。
- `kind:response`：当前命令参数；必须提供匹配真实提示符的 `expect_prompt`。发送一个 token/line，再观察下一提示符。
- `kind:scheme`：在根菜单或 Scheme 上下文执行的表达式，单独审查副作用。
- `kind:menu_control`：已观察菜单中的空行列表、`q` 返回、`?` 进入帮助；这些不是命令参数。仅在真实 `[help-mode]>` 时用 `q` 退出帮助。

状态包括 ROOT、MENU、COMMAND_ARGUMENT、YES_NO_PROMPT、ZONE_PROMPT、VALUE_PROMPT、SCHEME、SOLVING、ERROR、UNKNOWN。**不能在 zone/value/yes-no prompt 中发送 `/solve/...`。** 当前没有新 prompt 时先 `observe --wait`；超时不重发原命令。历史 prompt 后又出现错误，说明当前输入状态未验证，应保留会话并停止自动输入。

实际 v221 菜单与提示符优先于记忆。进入候选菜单后，以 `send "" --kind menu_control` 读取选项。`?` 会进入帮助模式；它不是普通列出菜单的命令。未知菜单不连续猜测。见 [v221 实测说明](references/fluent_2022r1_tui_notes.md)。

## 诊断与修正

错误上下文必须保留当前命令、执行前 prompt、完整局部输出、错误行、Error Object、执行后 prompt。解析器识别 SUCCESS、WARNING、ERROR、PROMPT、QUESTION、ITERATION、CONVERGENCE、FATAL、UNKNOWN；详见 [错误模式](references/error_patterns.md)。

1. 定位失败 step/input，保存 `last_successful_step`，不重跑已成功步骤。
2. 根据输出提出一个明确 hypothesis，仅修改相关 token。脚本可从同一实际菜单中选择唯一近似的末级命令；其他修正由 Codex 提供 evidence/prompt 匹配的 `repairs`。
3. 默认初次执行后最多 **3 次修正重试**；禁止相同失败输入无变化重发。日志保存原命令、诊断、假设、新命令、理由、真实结果。失败或不确定时停止、保留 Solver、给出完整诊断及需要用户决定的具体问题。
4. `safe_to_retry` 仅是诊断候选，不是授权或成功保证；还要检查当前 prompt、风险、原始用户目标、修正差异和重试预算。
5. warnings 必须读取并判断；计划默认停在未明确接受的 warning。数值发散/FPE/AMG 求解失败不能通过随机改模型、边界条件或重新初始化来试错。

对 `/solve/patch fluid_nozzle () pressure ,`：分别检查 zone 是否实际存在、是否仍在第二个 zone 或 register 提示、pressure 是否可选、CFF yes/no、数值是否缺失。**绝不能由 `[()]` 推出应发送 `()`；也不能把 Enter、逗号、`""` 与 `()` 当作等价输入。** 用户给出的六步提示序列是测试场景，不是所有 v221 case 的固定序列。

## 风险与状态保护

| 类别 | 执行原则 |
|---|---|
| READ_ONLY | 查询 zone/model、明确的 list/report、显示配置；允许自动查询。未确认副作用的未知命令不要仅凭名称降级。 |
| LOW_RISK | 新解初始化、目标范围内 patch、监控设置；通常可按用户目标执行。 |
| STATE_CHANGING | 边界、材料、湍流模型、solver 等；必须属于原始目标，计划标记 `in_user_goal:true`。 |
| DESTRUCTIVE | 覆盖 case/data/结果、删文件、丢弃未保存状态、重初始化已有解；不能作为自动试错。独立授权的目标操作可执行。 |

代码的风险推断是保守辅助，不是任意 TUI/Scheme 的完整副作用分析器。Codex 必须审查用户 journal 和自定义命令；`risk_evidence` 写具体依据，不得用它绕过已知 destructive 操作。

重要初始化、大量 patch、重大模型修改或长迭代之前，根据恢复成本决定 checkpoint。`checkpoint NAME` 写唯一的新 case/data，验证输出和非空文件。不要每个小命令都写大型 data。优先继续当前 session；只有状态污染、不可恢复或明确恢复决策时才 `rollback NAME --authorized`。回滚覆盖当前会话状态，不作为试错捷径。

## Journal fallback

先审查 .jou，确认其副作用在用户目标范围内，再使用 `run-journal FILE --reviewed`。每次新建 `run_XXXX`，保存原文、执行 journal、stdout/stderr、transcript、result.json。包装器用 v221 实测的 transcript 命令与 Scheme 输出标记；不注入未验证的 `set-tui-version`。

批处理中的成功必须有实际 v221 banner、独立执行的唯一完成标记、无识别错误、未超时、正确退出，以及目标字段/文件等后置条件。原 journal 自带 exit 或提前停录可能导致证据不足；检查原文并有依据地调整，不能忽略失败状态。动态未知多提示符任务优先 Interactive。Journal 计划采用显式 checkpoint 事务，失败时只修正失败事务；不能把新进程当成仍持有旧会话。

## 输出与结束

给用户说明完成的步骤、实际验证的值/文件、剩余问题和日志位置。不要把 mock 测试描述成真实 Fluent 测试。当前环境不具备真实 Fluent 时标记 **NOT VERIFIED WITH REAL FLUENT**。

`logs/.../final_report.md` 保存状态报告，`commands.jsonl/errors.jsonl/corrections.jsonl` 保存完整闭环。查看实时输出用 README 中的 PowerShell `Get-Content -Wait`。任务失败不自动退出；用户要求结束时按授权保存/丢弃并 `stop`。卡死进程只清理该会话记录的 PID 树，不能全局 kill 所有 Fluent。更多安装与使用示例见 [README](README.md)。
