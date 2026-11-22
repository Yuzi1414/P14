# 线上 AI 配置（Render + 通义千问）

## 为什么本地能用、线上不行

AI 模块原来把地址写死在 `reconcile/ai.py`：

```python
ENDPOINT = "http://127.0.0.1:11434"   # Ollama
```

`127.0.0.1` 永远指**跑这段代码的那台机器**：

| 环境 | `127.0.0.1:11434` 指向 | 结果 |
|---|---|---|
| 你本机 | 本机 Ollama（qwen3:4b 已下载） | 正常出建议 |
| Render 容器 | 容器自己，那里没装 Ollama | 连接失败 → 侧栏显示"规则引擎模式" |

就算把 Ollama 装进容器也没用：免费实例只有 512 MB 内存，qwen3:4b 权重 2.4 GB、加载需 3 GB+；磁盘还是临时的（每次重启清空），且 15 分钟无访问就休眠。

所以线上改走**云端 API**，本地开发仍然默认走本机 Ollama，两边行为不变。

---

## 一、阿里云百炼取 Key（约 3 分钟）

1. 打开 <https://bailian.console.aliyun.com>，用阿里云账号登录（需实名）
2. 左侧 **API-KEY 管理** → **创建我的 API-KEY**，复制 `sk-...` 开头的字符串
   ⚠️ 只填进 Render 环境变量，**不要**写进代码或提交 Git
3. 同一页面的**模型广场**确认要用的模型可用。默认用 `qwen-plus`：中文对账场景够用，价格比 `qwen-max` 低一个量级

新账号通常有免费额度，具体额度与有效期以控制台显示为准。

---

## 二、Render 配环境变量（约 2 分钟）

Render 控制台 → 你的服务 → **Environment** → **Add Environment Variable**，加这四项：

| Key | Value | 说明 |
|---|---|---|
| `AI_PROVIDER` | `qwen` | 走 OpenAI 兼容协议；也可写 `dashscope` / `openai` / `deepseek` |
| `AI_API_KEY` | `sk-你的key` | 也接受 `DASHSCOPE_API_KEY` |
| `AI_ENDPOINT` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | 不填默认就是它 |
| `AI_MODEL` | `qwen-plus` | 也可选 `qwen-turbo`（更便宜）、`qwen-max`（更强） |

保存后 Render 会自动重新部署（1–2 分钟）。刷新页面，侧栏应显示：

```
云端千问：● qwen-plus 可用
```

`AI 辅助与记录` 页会写明当前后端、模型和接口地址。

### 关于模型名

- `qwen-plus`：性价比默认选择，支持 JSON 模式
- `qwen-turbo`：最便宜，字段映射这种简单任务足够
- `qwen-max`：候选解释更稳，成本约 qwen-plus 的数倍
- `qwen3-*`：会默认"思考"，代码已自动关掉 `enable_thinking`；确需思考链时设 `AI_ENABLE_THINKING=1`

---

## 三、本地开发保持不变

不设任何环境变量时，行为和以前完全一致：连本机 `127.0.0.1:11434` 的 `qwen3:4b`。

想在本机临时试云端：

```powershell
$env:AI_PROVIDER="qwen"; $env:AI_API_KEY="sk-..."
.\.venv\Scripts\python.exe -m streamlit run app.py
```

判断规则很简单：**设了 `AI_API_KEY` 就走云端，没设就走本机 Ollama**；写了 `AI_PROVIDER` 则以它为准。

---

## 四、排错

| 现象 | 原因 | 处理 |
|---|---|---|
| 侧栏显示"未配置云端密钥" | 没设 `AI_API_KEY`，或设了没重启 | 补变量后重新部署 |
| 提示 `HTTP 401/403` | Key 错了、被删、或余额不足 | 重新生成 Key |
| 提示 `HTTP 404` | 模型名不对，或该账号没开通 | 换 `qwen-plus` 试试 |
| 提示 `HTTP 429` | 限流 / 免费额度用完 | 等一会儿或充值 |
| 提示超时 | 网络出口慢 | 设 `AI_TIMEOUT=90` |
| 想彻底关掉 AI | — | 设 `AI_ENABLED=0`，按钮置灰，规则结果不受影响 |

请求失败**不会**影响规则结果：`app.py` 里 AI 建议只写日志，分类和金额始终由规则引擎计算，采纳与否仍需人工点确认。

---

## 五、数据边界（重要）

启用云端 AI 后，**只有发起建议时的那几行数据**（列名 + 前 3 行样例，或候选记录的关键字段）会经 HTTPS 发往阿里云，其余数据仍在 Supabase 与浏览器会话里。

如果项目要求"数据不出境 / 不出内网"，两个替代方案：

1. 线上设 `AI_ENABLED=0`，AI 功能只在本地部署版演示
2. 用隧道把本机 Ollama 映射到公网（电脑需常开，且必须自己加鉴权），不推荐用于真实财务数据

具体数据清理要求见 [数据清理说明](DATA_POLICY.md)。
