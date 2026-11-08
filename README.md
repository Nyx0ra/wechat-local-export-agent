# WeChat Local Export Agent · 微信聊天记录导出工具

**将微信聊天记录导出为本地可阅读的 HTML 和 UTF-8 TXT，支持指定联系人和时间范围，并保存可提取的附件。** 当前面向 Windows + iPhone 本地备份。

你可以手动运行，也可以让具备本机操作能力的 **AI agent 帮你完成环境检查、配置、导出和结果验证**。项目已提供操作说明和任务提示模板，告诉 agent 想导出谁、哪段时间的记录即可开始；手机解锁、信任此电脑和密码输入仍由你在对应界面完成。

这是实验性工具。只支持已经完成、未加密且相关 SQLite 可读的 Apple 本地备份；不提供 SQLCipher 密钥获取、数据库解密或加密手机备份解密。压缩字典缺失时保留占位，不保证所有微信版本兼容。

## 让 AI agent 帮你导出

把本项目下载到电脑后，将项目目录交给 agent，并告诉它：

> 请阅读这个项目的 AGENTS.md 和 docs/agent-runbook.md，帮我把本人的 iPhone 微信中，与【联系人备注名或微信号】在【起止时间，或全部记录】的聊天导出为 HTML 和 TXT。请实际执行并验证结果，聊天和附件只保留本机；需要我操作手机时，再给出具体提示。

也可以直接使用[完整任务提示模板](docs/prompt-template.md)。Agent 会按说明检查本机环境、核对备份和联系人，再执行导出；遇到身份歧义或不支持的格式时停止并说明原因。

仓库仅存放工具源码、操作说明与合成测试，真实备份、配置和导出结果均保存在仓库外。Agent 只需处理本地文件，不需要将聊天正文或附件发送给在线模型。

## 手动运行

需要 Python 3.12+；真正的上游媒体转换程序仅适用 Windows x64。以下以 PowerShell 为例，在项目目录运行；`../private-runtime` 必须位于 Git 和云同步目录之外，并有足够磁盘空间。

```powershell
python -m venv ../private-runtime/venv
& ../private-runtime/venv/Scripts/python.exe -m pip install -r requirements.txt
Copy-Item examples/config.example.json ../private-runtime/case.json
# 编辑 ../private-runtime/case.json，明确 backup_dir、全新的 case_dir、联系人和时间范围。
& ../private-runtime/venv/Scripts/python.exe wxlocal.py --config ../private-runtime/case.json run
```

所有配置路径都相对**配置文件所在目录**解析。示例路径需要按实际位置修改，示例不是可直接运行的真实备份。

`time_range` 使用 `[start, end)`：包含起始秒，排除结束秒。时间必须带 `Z` 或明确偏移，精确到秒。例如导出一月：起始为 `2024-01-01T00:00:00+08:00`，结束为 `2024-02-01T00:00:00+08:00`。`time_range: null` 表示选定联系人全部可读记录；单侧边界也可使用。展示时区是独立的固定偏移，不改变筛选的实际时刻。

新项目不复制备份或案例到仓库。相同时间戳按源 `MesLocalID` 排序。配置变更后必须使用新的案例目录，以免混用旧附件和旧导出。

## 附件与可选转换

默认 `conversion: disabled`，仅保存能从源备份选出的原附件；图片可校验并显示，原始语音编码等可能不能直接播放，报告如实标记未验证。此模式不运行第三方可执行程序。

如需原作者 SILK/AMR 等转换，先将固定版本下载到仓库外：

```powershell
python tools/fetch_upstream.py --destination ../private-runtime/upstream
# 配置 conversion 为 upstream，exporter_executable 为该目录下 WechatExporterCmd.exe 的明确路径。
```

下载器仅向原作者发布站点请求公开安装包，校验 ZIP 和 EXE SHA-256，拒绝路径穿越和覆盖既有目录。它不会读取案例或聊天。仓库不包含上游二进制和虚拟环境。

**上游转换不是网络沙箱。** 代理变量只是降低其联网机会，不能当作隔离保证。处理真实聊天前，应由用户提供已确认的离线运行环境；不擅自关闭防护或修改防火墙。不能满足时继续使用默认模式并报告媒体播放限制。

时间受限时，只有能根据本地消息 ID 或选中正文中的资源哈希关联的附件才会进入候选集合。无法证明属于窗口的资源不导出，记录候选排除数量；这不是完整附件数量。完整会话允许保存目标会话尚未关联到单条消息的附件，并在页面单独列出。

## 分阶段运行和产物

```powershell
python wxlocal.py --config ../private-runtime/case.json identify
python wxlocal.py --config ../private-runtime/case.json inventory
python wxlocal.py --config ../private-runtime/case.json prepare
# conversion=upstream 时执行 official；默认模式略过。
python wxlocal.py --config ../private-runtime/case.json media
python wxlocal.py --config ../private-runtime/case.json render
python wxlocal.py --config ../private-runtime/case.json verify
```

`run` 顺序执行全部阶段；失败后查看**本机** `work/stage-*.log`，不要把日志原文贴进在线服务。已完成阶段不能覆盖重跑（`verify` 除外）；部分失败状态不保证可恢复，必要时使用新案例目录，不自动删除旧案例。

在配置的 `case_dir` 下生成：

- `exports/html/index.html`、`media/`、`media-index.json`：静态页面与资源，必须一并保存。
- `exports/txt/chat.txt`：UTF-8 文本；附件路径相对指向 HTML 资源目录。
- `export-report.txt` 和 `work/export-verification.json`：记录数、时间、未解析正文及媒体核验结果。
- `work/target-only-raw.sqlite`：仅选定联系人和窗口的原始消息工作副本，包含可能尚未解压的字段。

验证会重新读取源备份的目标窗口，逐条比对身份方向、时间、类型和正文/缺失标记，检查本地资源路径与媒体哈希。完整性结论仅覆盖选定备份和筛选条件，手机界面对照与所有历史覆盖不自动视为通过。

## 测试与源码打包

```powershell
python -B -m unittest discover -s tests -v
python -B tools/privacy_check.py
python -B tools/build_release.py --output ../wechat-local-export-agent-source.zip
```

测试数据完全由代码生成，包括虚构账号、联系人、SQLite、图片和压缩正文。不会连接手机、读取默认备份目录或使用真实会话。测试临时文件位于系统临时目录；ZIP 不含 `.git`、缓存、二进制或环境。

可用仓库外的 JSON 字符串列表向隐私检查提供 `--deny-file`，检查本人的账号、联系人或机器标识。检查只显示命中文件和规则，不回显敏感词。自动检查不能证明任意内容都无隐私，发布前还应检查确切的 Git 待提交文件和 ZIP。

参见 [兼容性](docs/compatibility.md)、[安全与隐私](SECURITY.md)、[第三方来源](THIRD_PARTY_NOTICES.md)。源码采用 GPL-2.0-only；本项目不代表腾讯或 Apple。
