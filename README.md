# Winnow —— 126 邮箱 AI 智能转发服务

持续监控一个 126 邮箱的新邮件，用 AI（MiniMax）判断每封是否「重要」（非广告/垃圾/营销），
把重要邮件以**原 126 身份**转发到指定目标邮箱。本质是一个「带 Web 控制台的后台邮件处理服务」。

> 当前进度：**Phase 1 · 步骤 A（命脉验证）**。先把三条命脉（IMAP 收信 / SMTP 发信 / MiniMax 调用）
> 各自跑通，再拼装完整管线。

---

## 1. 环境要求

- Python **3.11+**（开发机现为 3.13）
- [uv](https://docs.astral.sh/uv/) 包管理器
- 部署目标：阿里云轻量应用服务器 · Ubuntu 22.04 LTS · systemd 常驻（部署细节在 Phase 1 收尾时补全）

安装 uv（若未安装）：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

同步依赖（在项目根目录）：

```bash
uv sync
```

---

## 2. 获取 126 邮箱「授权码」

网易第三方客户端登录**不能用网页登录密码**，必须用「客户端授权码」：

1. 浏览器登录 <https://mail.126.com>。
2. 顶部 **设置 → POP3/SMTP/IMAP**。
3. 开启 **IMAP/SMTP 服务**（首次开启需短信/扫码验证）。
4. 按提示**生成/查看授权码**，复制这串字符。
5. 在 `.env` 里把它填到 `IMAP_AUTH_CODE`（IMAP 和 SMTP 共用同一个授权码）。

> 授权码 = 凭据，切勿泄露；本项目只放 `.env`、不落数据库、不打日志。

---

## 3. 获取 MiniMax 订阅 Key

1. 登录 MiniMax 开放平台 <https://platform.minimaxi.com>。
2. 进入**账户管理 / 接口密钥**，找到 **Token Plan 订阅专属 Key**（形如 `sk-sp-xxxx`）。
3. 填入 `.env` 的 `MINIMAX_API_KEY`。

> ⚠️ 订阅 Key 与「按量付费」Key 是两套、额度不互通。Token Plan 面向个人交互式场景，
> 有 RPM/TPM 限流并受 5 小时/周窗口额度限制，对常驻自动化调用可能触发限流。
> 本服务已设计两级过滤（规则预筛尽量少调模型）+ 限流重试退避；若经常被限流，
> 只需把 `.env` 里的 Key 换成按量付费 Key 即可（代码无需改动）。
>
> 隐私提示：邮件正文会发送给 MiniMax（第三方）用于判断。数据库不长期存完整正文，
> 仅存元数据 + AI 判断结果 + 必要短摘要。

---

## 4. 配置 `.env`

```bash
cp .env.example .env
# 用编辑器填入 EMAIL_126 / IMAP_AUTH_CODE / MINIMAX_API_KEY 等真实值
```

字段说明见 `.env.example` 内注释。

---

## 5. Phase 1 · 步骤 A：跑三个命脉脚本

依次运行，每个都应打印 `✅ ... PASS`：

```bash
# (a) IMAP 收信：登录 + 发 ID 命令 + 拉最新 5 封邮件头（只读，不改状态、不打正文）
uv run python scripts/check_imap.py

# (b) SMTP 发信：以 126 身份发一封测试邮件到 FORWARD_TO
uv run python scripts/check_smtp.py

# (c) MiniMax：用订阅 Key 调一次分类，确认 Key 可程序化调用、暴露限流/权限问题
uv run python scripts/check_minimax.py
```

三条都 PASS 后（**本地 Mac** 一遍，**服务器** 再各一遍），才继续拼装完整管线。

---

## 6. 后续阶段（预告）

- **Phase 1 步骤 1+**：数据层 → 规则预筛 → MiniMax 适配器 → SMTP 转发器 → 管线编排 →
  IMAP IDLE 常驻服务 + CLI（`winnow run` / `once` / `logs`）。
- **Phase 2**：登录、邮箱绑定页、转发规则配置、处理日志页、统计面板（React + FastAPI）。
- **Phase 3**：人工复核纠错、多账号/多用户、更健壮的告警。
