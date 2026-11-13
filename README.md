# P14 账务核对平台

本地财务对账演示原型。导入银行流水、学生收费、财务往来账 Excel，分别核对银行—收费与银行—往来关系，汇总三方结果，支持本地 AI 建议、人工复核及 Excel 导出。

**全部演示规则未经财务确认，所有输出仅供辅助参考，不用于正式财务结算。** `samples/` 为独立合成数据，不包含财务处真实样例。

## 启动

Windows 已安装 Python 3.12 时，双击 `start.cmd`，在浏览器打开 <http://127.0.0.1:8501>。首次运行会安装 Python 依赖；随后核心流程可离线运行。

```powershell
# 手动安装及启动
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe scripts\generate_samples.py
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\start.ps1

# 首次下载本地 AI 运行时与模型（只下载公开软件，不上传业务文件）
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\setup-ai.ps1
```

本地 AI 使用 Ollama `qwen3:4b`，首次下载需要网络和数 GB 磁盘空间。后续由 `scripts/start-ai.ps1` 启动，仅绑定 `127.0.0.1:11434`，关闭云功能，按 CPU 推理配置运行。`start.ps1` 会在运行时已安装时尝试启动它。模型不可用不会破坏规则结果。

线上（Render 免费实例）装不了 Ollama：512 MB 内存装不下 2.4 GB 的权重，磁盘重启即清空。因此线上改走**云端通义千问**——设 `AI_PROVIDER`／`AI_API_KEY` 即可，本地不设变量时行为不变。配置步骤见 [线上 AI 配置](docs/线上AI配置.md)。

若本机代理使 Ollama 下载器返回 EOF，安装脚本会尝试 `scripts/download_model.py`，通过系统 curl 从同一官方 registry 下载并验证各文件 SHA256，不修改证书或系统代理。已安装模型再次执行 setup 不重新下载。

进入工作台后先登录（或注册一个账号），加载合成演示，切换“结果与人工复核”查看依据。银行缺编号的演示记录可体验候选解释与人工关联。更多步骤见 [用户操作说明](docs/USER_GUIDE.md)。

`dist/` 成果包包含源码、文档、合成样例和验证证据，不包含模型、虚拟环境或本机任务数据库。另一台设备需要按以上脚本重建环境。更新源码后请重启工作台，避免保留旧的内存缓存。

## 验证与结构

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\benchmark.py
.\.venv\Scripts\python.exe scripts\verify_local_ai.py
```

- `reconcile/`：导入标准化、规则引擎、AI 适配（本地 Ollama／云端千问双后端）、复核服务、SQLite／Supabase 存储及 Excel 导出。
- `app.py`：Streamlit 工作台，计算逻辑独立于界面。
- `samples/`：三类合成 Excel、独立预期结果。
- `docs/`：PRD、业务规则、验收记录、操作与汇报材料。
- `runtime/`、`.runtime/`：本机任务、日志、模型及工具，已排除出版本库。

## 数据边界

不连接生产系统，不自动制单或记账，不提供公网 API。不要把受限数据放到源代码或 `samples/`。任务数据库、AI 使用记录、导出及截图可能含派生数据，需与原始样例一起受控；项目结束按 [数据清理说明](docs/DATA_POLICY.md) 处理。

不将合成测试通过写成财务业务验收通过。正式业务仍需确认关联键、汇总关系、退款、手续费、日期及用户测试结果，见 [待财务确认清单](docs/BUSINESS_CONFIRMATION.md)。

