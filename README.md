# fluent-tui-agent

Author: Manuel Sun

简体中文 | [English](README.en.md)

[架构与设计](docs/ARCHITECTURE.md) · [测试范围](TEST_REPORT.md)

针对 Windows 上的 ANSYS Fluent **2022 R1 / v221** TUI 执行、观察、诊断和有限修正 Skill。使用真实 Fluent 进程与 console/transcript；不使用 PyFluent；其他版本未进行测试。测试结论和范围见 [TEST_REPORT.md](TEST_REPORT.md)。

## 项目定位

把用户目标转成 TUI 输入，并根据 Fluent 实际输出决定下一步。支持持久 Interactive 会话和 Journal + Transcript 后端、逐提示符参数输入、错误分类、最多 3 次自动修正、checkpoint 与完整本地审计记录。

**返回提示符不等于 CFD 结果正确。** 例如 patch 后仍应读取实际字段报告验证目标值。未知错误由 Codex 基于当前上下文提出修正假设；脚本不承诺任意报错都能自动修复。

## 获取skill

```powershell
git clone https://github.com/Ivan1853/fluent-tui-agent.git
Set-Location fluent-tui-agent
```

仓库不包含 Fluent、许可证、生产 case/data 或本地运行日志。需要自行安装合法可用的 ANSYS Fluent 2022 R1。

## 安装与识别

将整个 `fluent-tui-agent` 文件夹复制到当前 Codex 的个人 skills 目录。本机 Skill 目录为 `$env:USERPROFILE\.codex\skills`；通用新版本文档还列出了 `$env:USERPROFILE\.agents\skills` 和项目 `.agents\skills`。只选择当前应用实际使用的一个位置，避免重复安装。

```powershell
# 在解压后的父目录执行；目标目录应不存在，避免覆盖已有配置/日志。
$skillSource = Join-Path (Get-Location) 'fluent-tui-agent'
$skillTarget = Join-Path $env:USERPROFILE '.codex\skills\fluent-tui-agent'
if (Test-Path -LiteralPath $skillTarget) { throw '目标已存在，请先检查已有版本。' }
Copy-Item -LiteralPath $skillSource -Destination $skillTarget -Recurse
Set-Location -LiteralPath $skillTarget
```

`SKILL.md` 含 `name/description` frontmatter，`agents/openai.yaml` 启用自动选择。更新未显示时重新打开 Codex；也可在对话中显式写 `$fluent-tui-agent`。识别格式和发现方式依据 [OpenAI 官方 Skill 文档](https://learn.chatgpt.com/docs/build-skills)。

## 配置和连接验证

需要 Windows 10 1809+/Windows 11、Python 3.10+、Fluent v221 和可用许可证。核心模块只用 Python 标准库。

```powershell
Copy-Item config\fluent_config.example.json config\fluent_config.json
python scripts\fluent_driver.py discover --save
python scripts\fluent_driver.py start
python scripts\fluent_driver.py status
```

不要覆盖已有 `fluent_config.json`。可编辑其中的 `executable`，例如 `D:/Program Files/ANSYS Inc/v221/fluent/ntbin/win64/fluent.exe`。检测顺序为配置 → 环境变量（优先 AWP_ROOT221/ANSYS221_DIR）→ 常见安装树 → 这些安装树与自定义 `search_roots`/PATH 中的 executable；检查文件版本或 v221 目录及 22.1 payload。检测输出列出候选、证据、选中项，`--save` 保存最终路径。不会默认使用新版 Fluent。

配置支持 `dimension:2d|3d`、`precision:single|double`、`parallel`、`processors`、`gui`、`working_directory`、`transport:auto|pipe|conpty`、超时和编码。默认启动参数为 `3ddp -g -t1`；parallel=true 时使用所设 CPU 数。默认单 rank 配置不表示硬件或许可证只支持一个 CPU。`extra_args` 仅填写已在 v221 验证的选项。

`start` 必须读到实际 2022 R1 banner、ROOT、查询输出及再次 ROOT 才标记 available。启动失败时查看 logs，尤其是许可证和本地进程通信；在 Codex 沙箱无法启动时，按现有授权在允许的 Windows 执行环境运行，不能将环境限制报告成“Fluent 未安装”。

## 单条 TUI、多步骤、prompt response

```powershell
python scripts\fluent_driver.py send '/report/system/sys-stats'
python scripts\fluent_driver.py execute-plan examples\basic_tui.json
python scripts\fluent_driver.py execute-plan examples\recovery_plan.json

# 仅在用户目标要求初始化、且当前状态允许时：
python scripts\fluent_driver.py send '/solve/initialize/initialize-flow'

# 在已观察到对应 prompt 后逐个执行；不是固定无条件脚本：
python scripts\fluent_driver.py send '/solve/patch'
python scripts\fluent_driver.py send 'fluid_nozzle' --kind response --expect-prompt 'cell zone id/name\(1\)'
```

每次都读取返回 JSON 再决定下一步。状态改变的未知命令使用 `--in-goal` 标记已属于用户目标。需要重初始化已有解等明确破坏性操作时，在已有授权下使用 `--allow-destructive`；不能用于错误恢复试错。

`examples/patch_plan.json` 对应用户给出的模拟序列；真实 v221 可能多出 register 等提示，应按真实输出修改。`patch_example.jou` 记录了本次压力出口测试夹具的实际序列，要求在同一事务中先加载并初始化相应 case，不能作为所有 case 通用的 patch 脚本。`patch_and_verify_v221.json` 包含实际压力报告验证。计划 schema、修正候选和 backend 限制见 [API 说明](references/api_and_plans.md)。

PowerShell 5.1 会丢失某些传给原生程序的空参数，**发送 Enter 优先用 JSON inputs 中的 `"command":""`**。不要用逗号、`()` 或 `""` 的字面值来绕过这个问题。

## 执行已有 journal

```powershell
# 先检查原 .jou 的读取路径、覆盖/退出及其他副作用，确认在用户目标内。
python scripts\fluent_driver.py run-journal 'C:\CFD\job.jou' --reviewed --timeout 600
```

设置 `working_directory` 为原 journal 所需目录。Runner 新建进程并用 `-i` 执行包装 journal，保存原文、输出、transcript 和 result；不修改原 `.jou`。原文自带 exit 时可能导致 wrapper 完成证据缺失，必须如实检查和调整，不能将退出码 0 当成功。

## 查看控制台、诊断和日志

```powershell
$fluentStatus = python scripts\fluent_driver.py status | ConvertFrom-Json
Get-Content -LiteralPath (Join-Path $fluentStatus.log_dir 'stdout.log') -Tail 40 -Wait
# 在另一 PowerShell 窗口读取结构化状态/等待新 prompt：
python scripts\fluent_driver.py observe --wait --timeout 30
Get-Content -LiteralPath (Join-Path $fluentStatus.log_dir 'errors.jsonl') -Tail 5
Get-Content -LiteralPath (Join-Path $fluentStatus.log_dir 'corrections.jsonl') -Tail 5
python scripts\fluent_driver.py diagnose 'C:\CFD\error-output.txt' --command '/solve/patch' --before 'Variable>'
```

每次任务生成 `logs/YYYYMMDD_HHMMSS_taskname_unique/`，包含 session.log、commands.jsonl、stdout.log、stderr.log、errors.jsonl、corrections.jsonl、progress.json、final_report.md。Journal 另有 `run_XXXX/command.jou/source.jou/stdout.log/stderr.log/transcript.trn/result.json`。运行中的 transcript 可能缓冲，stdout 是主要的实时来源。原生 ConPTY 将 console 的 stdout/stderr 合并，stderr.log 因而可能为空。

## checkpoint、恢复和关闭

```powershell
python scripts\fluent_driver.py checkpoint before_model_change
# 只在明确决定以该 checkpoint 替换当前状态时：
python scripts\fluent_driver.py rollback before_model_change --authorized
python scripts\fluent_driver.py stop
# 用户已要求丢弃测试/未保存状态时：
python scripts\fluent_driver.py stop --discard
```

`checkpoint` 使用唯一新路径，先核验输出与非空 case/data。自动恢复最多 3 次，超限保留会话。`stop` 不会为了测试而默认丢弃未保存更改。

卡死时先读 `status` 和日志，必要时 `interrupt` 后重新 `observe --wait`。Windows PIPE 不保证 Ctrl-C，工具会明确报告。确认需要终止该会话后运行：

```powershell
python scripts\fluent_driver.py stop --force
# broker 已死而 Fluent 仍活着时，先核对 session 文件和日志中的具体 PID：
# taskkill /PID <已核对的该会话FluentPID> /T /F
# 确认 broker 和对应 Fluent 进程均已停止后才清除失效元数据：
python scripts\fluent_driver.py clear-session --confirmed-stopped
```

不要按进程名称结束全部 Fluent。重启 broker 不会神奇恢复旧 Solver 内存；从 checkpoint 恢复时明确重建剩余步骤。

## 测试

```powershell
python -m unittest discover -s tests -p test_agent.py -v
python tests\integration_fluent.py --config config\fluent_config.json
```

单元测试中的模拟 Solver 始终标记 MOCK；实际集成脚本新建独立配置/日志和空白会话，执行只读查询、故意无效路径、自动修正及 Journal 证据检查，结束自身测试进程。CFD patch/checkpoint 的本次实际记录单独列在 TEST_REPORT。未发现 v221 时脚本明确输出 **NOT VERIFIED WITH REAL FLUENT**，不会冒充成功。

## 给 Codex 的三个使用示例

1. `$fluent-tui-agent 启动 Fluent 2022 R1，读取系统统计，报告真实版本、当前 prompt 和日志路径。`
2. `$fluent-tui-agent 执行 examples/recovery_plan.json，展示无效路径的实际报错、菜单证据、修正假设与重试结果。`
3. `$fluent-tui-agent 检查 C:\CFD\job.jou 的前置条件和副作用，在用户目标范围内执行，读取 transcript 并报告失败步骤；没有输出证据时不要报告成功。`

## 文档与相关项目

- [架构和修正边界](docs/ARCHITECTURE.md)：状态机、backend、证据与恢复策略。
- [API 与计划 schema](references/api_and_plans.md)：交互计划、响应类型、Journal 事务。
- [文件树](FILE_TREE.txt)：发布文件清单。

本项目是独立的社区工具，与 Ansys 或 OpenAI 无隶属关系。项目名称中的 ANSYS、Fluent 和 Codex 用于标识兼容目标。
