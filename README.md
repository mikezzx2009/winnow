# Winnow —— 126 邮箱 AI 智能转发服务

*An AI-powered mail triage & forwarding service for NetEase 126 mailboxes, with a web console.*

🌐 作者的线上实例：<https://winnow.zares.me>（私人部署，需登录，仅供参观登录页 🙂）

持续监控 126 邮箱的新邮件，用 AI（MiniMax）判断每封是否「重要」（非广告/垃圾/营销），
把重要邮件以**原 126 身份**转发到指定目标邮箱。本质是一个「带 Web 控制台的后台邮件处理服务」。

**功能一览**
- 两级过滤：规则预筛（退订头/群发头/营销词，不调模型）+ MiniMax 结构化判断，省额度、避限流
- 以原 126 身份 SMTP 转发：保留原始正文/附件，`Reply-To` 回到真人，SPF/DKIM 天然对齐
- 幂等去重（`Message-ID`）、发信限速、每日上限、断线指数退避重连、126 无 IDLE 时自动轮询
- Web 控制台：登录、邮箱绑定（授权码 Fernet 加密入库）、白/黑名单、阈值等规则配置、
  处理日志（AI 理由 + 人工复核纠错）、统计面板、系统状态/告警
- 多用户多租户：自助注册（可关闭/可设邀请码），每个用户只见自己名下的账号与数据，
  第一个用户自动成为管理员（可见全部 + 用户管理）
- 多账号（每账号独立 worker）；AI 适配器可替换（换 Key/模型/厂商只改配置）

---

## 1. 环境要求

- Python **3.11+**
- [uv](https://docs.astral.sh/uv/) 包管理器
- 前端构建产物（`web/dist`）已随仓库提交，运行**无需 Node**；改前端才需要 Node 18+
- 生产部署（Ubuntu + systemd + Nginx/HTTPS）见 [docs/DEPLOY.md](docs/DEPLOY.md)

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

## 6. Phase 1 运行（收信 → 判断 → 转发）

命令（`winnow` 由 `uv sync` 安装到虚拟环境）：

```bash
# 演练：回捞最近 5 封真实邮件，走完整判断链路但【不实际转发】——安全的端到端自检
uv run winnow once --backfill 5 --dry-run

# 跑一轮：处理「上次以来的新邮件」并按判断结果转发
#   首次运行会把当前最大 UID 设为基线，只处理之后新到的邮件（不回捞旧邮件）
uv run winnow once

# 常驻服务：实时收信 + 自动重连（优先 IMAP IDLE；网易不支持 IDLE 时自动回退轮询）
uv run winnow run

# 查看处理记录（AI 判断理由 / 是否转发 / 分类）
uv run winnow logs --limit 20
```

单元测试：

```bash
uv run pytest -q
```

## 7. 工作原理

- **两级过滤（省额度、避限流）**：先用规则预筛，明显的群发营销（`List-Unsubscribe`
  退订头、`Precedence: bulk`、营销主题词）直接判为不重要、**不调模型**；拿不准的才交给 MiniMax。
- **结构化判断**：模型返回 `{is_important, confidence, reason, category}`，对夹带代码围栏/
  多余文字的输出做健壮 JSON 解析；被限流自动重试 + 指数退避；AI 故障时兜底为「保守转发」。
- **决策（漏判代价不对称）**：判为重要 → 转发；判为不重要**但置信度低于阈值**（默认 0.75）
  → 仍然转发。宁可误转发广告，不漏掉重要邮件。阈值可在 `.env` 配。
- **转发（保留原始身份与内容）**：改写信封头后原样重发原始 MIME —— `From` 为你的 126 地址
  （SPF/DKIM 天然对齐），`Reply-To` 为原始发件人（回复回到真人），主题加 `[Winnow]` 前缀，
  原始正文/内联图片/附件完整保留。
- **收信方式**：优先 IMAP IDLE 实时收信；**网易 126/163 不支持 IDLE**，服务自动回退为轮询
  （默认每 30s，`POLL_INTERVAL_SECONDS` 可调）+ 断线指数退避重连。
- **幂等（绝不重复转发）**：以 `Message-ID` 去重并记录已处理 UID，服务重启不会重发旧邮件。
- **反垃圾限速**：相邻转发最小间隔（默认 5s）+ 每日上限（默认 200，超限排队至次日）。
- **隐私/数据最小化**：邮件正文会发给 MiniMax（第三方）判断；数据库只存元数据 + 判断结果 +
  ≤120 字短摘要，不长期存完整正文；日志不打印正文与任何凭据。

## 8. 部署到阿里云（Ubuntu 22.04 + systemd）

```bash
# 1) 安装 uv（若无）
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2) 拉代码（首次 clone / 后续 git pull）
sudo git clone <你的仓库地址> /opt/winnow && cd /opt/winnow

# 3) 装依赖（生成 .venv 及 winnow 命令）
uv sync

# 4) 配 .env 并收紧权限
cp .env.example .env && chmod 600 .env && vim .env   # 填 126 授权码 / MiniMax Key

# 5) 【重要】先在服务器上把三个命脉脚本各跑一次，确认真实部署环境也通
uv run python scripts/check_imap.py
uv run python scripts/check_smtp.py
uv run python scripts/check_minimax.py

# 6) 安装并启动 systemd 服务（单元文件见 deploy/winnow.service，按需改 User/路径）
sudo cp deploy/winnow.service /etc/systemd/system/winnow.service
sudo systemctl daemon-reload
sudo systemctl enable --now winnow

# 7) 看日志
journalctl -u winnow -f
```

> Phase 1 只有后台服务 + CLI，**无需开放入站端口**；Phase 2 的 Web 端口届时再在阿里云安全组开放。

## 9. Web 控制台（Phase 2）

FastAPI 后端 + React(Vite+Tailwind) 前端，前端构建产物由 FastAPI 单进程托管（单端口）。
需在 `.env` 配置 `FERNET_KEY`（绑定授权码加密）和 `SESSION_SECRET`（登录 Cookie 签名）。

```bash
# 1) 启动控制台，浏览器打开 http://<host>:8000
uv run winnow web --host 0.0.0.0 --port 8000
#    首次使用：直接在登录页点「注册」——第一个注册的用户自动成为管理员。
#    （也可用 CLI 创建管理员：uv run winnow set-password --username admin）

# 2) 改动前端后需重新构建（产物 web/dist 已入库，只跑后端可跳过）
cd web && npm install && npm run build && cd ..
```

**注册与多租户**：`ALLOW_REGISTRATION` 控制是否开放注册（默认开）；公开部署建议设置
`REGISTRATION_INVITE_CODE`，注册时必须填对邀请码，防止陌生人注册消耗你的 AI 额度。
每个用户只能看到/管理自己名下的邮箱账号、日志、规则与统计；管理员可见全部账号，
并在「管理」页管理用户（删除用户时其名下账号归给操作的管理员）。

功能：登录 → **统计面板**（今日/累计 收到·重要·转发 + 服务健康横幅）→ **邮箱绑定**（126 地址+授权码，
Fernet 加密入库；转发目标/前缀/阈值/间隔/每日上限/启用开关）→ **转发规则**（发件人白/黑名单，
白名单必转发、黑名单必拦截）→ **处理日志**（列表 + AI 理由 + 转发状态 + 搜索/筛选 + **人工复核纠错**：
标记「其实重要/其实垃圾」、一键把发件人加白/黑名单）→ **系统状态**（收信服务心跳、
事件/告警列表：连接断开·转发失败·授权码失效·AI 限流，可标记已处理）。

配置改动即时生效：常驻收信服务每轮从 DB 重读账号配置与名单（连接凭据/前缀改动需重启收信服务）。
授权码优先用控制台绑定的（解密使用），未绑定则回退 `.env`。

## 10. 部署两个服务（阿里云 · systemd）

Winnow 由两个进程组成，各一个 systemd 单元：
- **收信服务** `winnow.service` → `winnow run`（IMAP IDLE 常驻，无需开端口）
- **Web 控制台** `winnow-web.service` → `winnow web`（端口 8000，需在安全组放行）

```bash
sudo cp deploy/winnow.service      /etc/systemd/system/
sudo cp deploy/winnow-web.service  /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now winnow winnow-web
journalctl -u winnow -f          # 收信日志
journalctl -u winnow-web -f      # 控制台日志
```

> `web/dist` 已随仓库提交，服务器 `git pull` 后无需 Node 即可运行控制台。
> 生产建议：控制台前面加 Nginx 反代 + HTTPS，或安全组只放行可信 IP。

## 11. Phase 3（已完成）

- ✅ **人工复核纠错**：日志页可标记「其实重要/其实垃圾」，并一键把发件人加白/黑名单。
- ✅ **健壮错误处理与告警**：收信服务心跳 + 事件表（连接断开/转发失败/授权码失效/AI 限流），
  控制台「系统状态」页展示并可标记已处理；服务已内建重连退避、AI 限流重试、转发失败记录。
- ✅ **多账号 / 多用户**：
  - 收信服务为「每个已启用且已绑定授权码的账号」各起一个 worker 线程（独立 IDLE 连接 + 重连），
    Supervisor 每 60s 对账启停；SQLite 开启 WAL 降低并发写锁。
  - 控制台「管理」页可增删 126 账号、增删控制台登录用户、改密码；顶部账号切换器，
    绑定/规则/日志/统计/状态均按所选账号隔离。
  - 未绑定授权码的账号仅回退 .env 到与 EMAIL_126 同名的那个账号，其余必须在控制台绑定各自授权码。

> 新增账号后需在「邮箱绑定」页填该账号授权码并启用；收信服务会在下一次对账（≤60s）或重启后接管。

## 12. License

[MIT](LICENSE)。注意：邮件正文会发送给你配置的 AI 服务商（默认 MiniMax）用于重要性判断，
请自行评估隐私影响；本项目不长期存储完整正文（详见「工作原理」）。
