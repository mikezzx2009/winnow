# Winnow 部署指南（阿里云轻量 · Ubuntu 22.04 · systemd）

目标：在服务器上常驻两个进程 —— **收信服务** `winnow run` 与 **Web 控制台** `winnow web`。
前端已随仓库提交（`web/dist`），**服务器无需安装 Node**。

---

## 0. 前置准备

手头备好：
- 阿里云轻量应用服务器（Ubuntu 22.04），能 SSH 登录（root 或有 sudo 的用户）。
- 126 邮箱**客户端授权码**、MiniMax **API Key**（订阅 `sk-sp-` 或按量 `sk-cp-`）。
- （可选，推荐）一个解析到服务器公网 IP 的域名，用于 HTTPS。

安全组/防火墙先记住：
- 收信服务 `winnow run` 只**出站**连 126/MiniMax，**不需要开任何入站端口**。
- Web 控制台默认监听 8000。推荐用 Nginx 反代 + HTTPS，只放行 80/443；不放行 8000 到公网。

---

## 1. 系统依赖 + 专用用户

```bash
sudo apt update
sudo apt install -y git curl rsync

# 建一个专用非 root 用户运行服务
sudo useradd -m -s /bin/bash winnow

# 部署目录
sudo mkdir -p /opt/winnow
sudo chown winnow:winnow /opt/winnow
```

装 uv（以 winnow 用户身份，装到它的 ~/.local/bin）：

```bash
sudo -u winnow -i bash -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
```

> 运行时不依赖 uv（systemd 直接调用 venv 里的 `winnow`），uv 只用于装依赖。

---

## 2. 把代码放到 /opt/winnow

**方式 A：Git（推荐，若已推到私有仓库）**

```bash
sudo -u winnow git clone <你的仓库地址> /opt/winnow
```

**方式 B：从本地 Mac rsync（没有 Git 远端时）**

在你的 **Mac** 上执行（把 SERVER 换成服务器 IP/别名）：

```bash
rsync -av --delete \
  --exclude '.venv' --exclude 'node_modules' --exclude 'web/node_modules' \
  --exclude '.env' --exclude '*.db' --exclude '*.db-wal' --exclude '*.db-shm' \
  --exclude '.git' \
  ~/Documents/Winnow/  winnow@SERVER:/opt/winnow/
```

> `web/dist`（已构建前端）会一并同步，服务器无需 Node。`.env` 和数据库不同步，服务器上单独配。

---

## 3. 配置 .env（只在服务器上，权限 600）

```bash
sudo -u winnow -i
cd /opt/winnow
cp .env.example .env
chmod 600 .env

# 生成两把密钥
echo "FERNET_KEY=$(python3 -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())' 2>/dev/null || uv run python -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())')"
echo "SESSION_SECRET=$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')"
```

编辑 `.env`，至少填这几项（其余用默认即可）：

```dotenv
EMAIL_126=你的@126.com
IMAP_AUTH_CODE=你的126客户端授权码
MINIMAX_API_KEY=sk-...              # 订阅或按量 Key
FERNET_KEY=上一步生成的值
SESSION_SECRET=上一步生成的值
# FORWARD_TO / IMPORTANCE_THRESHOLD / FORWARD_INTERVAL_SECONDS / DAILY_FORWARD_LIMIT 可按需覆盖
```

> `FERNET_KEY` 一旦用于加密授权码入库就**不能再变**（变了解不开旧密文）。

---

## 4. 安装依赖（创建 .venv 与 winnow 命令）

```bash
# 仍以 winnow 用户，在 /opt/winnow 下
uv sync            # 生成 /opt/winnow/.venv 及 winnow 可执行文件
# 生产可用 uv sync --no-dev 省掉 pytest 等
```

---

## 5. 在服务器上复跑三条命脉（务必做一次）

```bash
uv run python scripts/check_imap.py     # 期望 ✅ IMAP 命脉 PASS
uv run python scripts/check_smtp.py     # 期望 ✅ SMTP，且目标邮箱收到测试信
uv run python scripts/check_minimax.py  # 期望 ✅ MiniMax，base_resp.status_code=0
```

三条都 PASS 再继续（阿里云国内机房访问 126/MiniMax 通常更稳）。

---

## 6. 建控制台登录用户

```bash
uv run winnow set-password --username admin   # 交互式输入密码
exit   # 退出 winnow 用户 shell，回到有 sudo 的账号
```

---

## 7. 安装并启动两个 systemd 服务

仓库里已带单元文件：`deploy/winnow.service`、`deploy/winnow-web.service`
（默认 `User=winnow`、`WorkingDirectory=/opt/winnow`、`ExecStart=/opt/winnow/.venv/bin/winnow ...`）。
如用了别的用户名/路径，先编辑这两个文件再拷贝。

```bash
sudo cp /opt/winnow/deploy/winnow.service     /etc/systemd/system/
sudo cp /opt/winnow/deploy/winnow-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now winnow winnow-web

# 看日志确认
journalctl -u winnow -f          # 收信：应看到「已连接 / 已设基线」
journalctl -u winnow-web -f      # 控制台：uvicorn 启动
```

> 若打算用 Nginx 反代（下一步），先把 `winnow-web.service` 的 `--host 0.0.0.0` 改成 `--host 127.0.0.1`，
> 让 8000 只对本机开放，然后 `daemon-reload && restart winnow-web`。

---

## 8. 暴露 Web 控制台（二选一）

### 方案 A：快速（直接开 8000，明文，仅临时/信任 IP）
阿里云安全组放行 TCP 8000（建议限来源 IP）。浏览器访问 `http://服务器IP:8000`。

### 方案 B：Nginx 反代 + HTTPS（推荐）

```bash
sudo apt install -y nginx
sudo tee /etc/nginx/sites-available/winnow >/dev/null <<'NGINX'
server {
    listen 80;
    server_name winnow.example.com;   # 换成你的域名
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
NGINX
sudo ln -sf /etc/nginx/sites-available/winnow /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# HTTPS（Let's Encrypt）
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d winnow.example.com
```

阿里云安全组只放行 **80/443**（不放 8000）。建议再开 ufw：

```bash
sudo ufw allow OpenSSH && sudo ufw allow 'Nginx Full' && sudo ufw enable
```

---

## 9. 首次使用

浏览器打开控制台 → 用 admin 登录 →
- **邮箱绑定**：确认 126 地址、目标邮箱、阈值等（授权码可在此加密入库；若已在 `.env` 配好可不填）。
- **系统状态**：确认「收信服务运行正常」（有心跳）。
- 给该 126 邮箱发一封测试邮件，几秒后在 **处理日志** 看判定、在目标邮箱看 `[Winnow]` 转发。

多账号：**管理**页添加新 126 账号 → 顶部切到该账号 → 邮箱绑定页填它的授权码并启用；
收信服务会在下一次对账（≤60s）自动为它起一个 worker。

---

## 10. 运维

**更新代码**
```bash
# 方式A(git)： sudo -u winnow git -C /opt/winnow pull
# 方式B(rsync)：在 Mac 上重跑第 2 步的 rsync
sudo -u winnow bash -c 'cd /opt/winnow && uv sync'
sudo systemctl restart winnow winnow-web
```

**改了前端**（在 Mac 上）：`cd web && npm run build`，提交/同步 `web/dist`，然后 `restart winnow-web`。

**备份数据库**（含判定记录/绑定/规则/用户）：
```bash
sudo -u winnow sqlite3 /opt/winnow/winnow.db ".backup '/opt/winnow/backup-$(date +%F).db'"
```
（WAL 模式下别只拷 `winnow.db`，用上面的 `.backup` 才一致。）

**改密码 / 加用户**：控制台「管理」页，或 `uv run winnow set-password --username <名>`。

---

## 11. 常见问题

- **`Unsafe Login`**：已由 IMAP ID 命令处理；若仍报，多半授权码错或未开 IMAP 服务。
- **授权码失效**：控制台「系统状态」会出 `auth` 告警；到「邮箱绑定」重填授权码即可（无需改 .env）。
- **MiniMax 频繁限流**：把 `.env` 的 `MINIMAX_API_KEY` 换成按量付费 Key（代码无需改），或调大预筛/阈值减少调用。
- **发信被 126 限频/冻结**：调大 `FORWARD_INTERVAL_SECONDS`、调小 `DAILY_FORWARD_LIMIT`。
- **实时性/延迟**：网易 126/163 **不支持 IMAP IDLE**，收信服务会自动回退为**轮询**（默认每 30s，
  `POLL_INTERVAL_SECONDS` 可调），因此从收到到转发有最多约 30s 延迟，属正常现象（日志会有一条
  “服务器不支持 IMAP IDLE，改用轮询”的 info）。
- **服务反复重启**：`journalctl -u winnow -e` 看报错；多半是 `.env` 缺 `EMAIL_126/IMAP_AUTH_CODE/MINIMAX_API_KEY`。
- **重启后要重新登录**：`SESSION_SECRET` 没固定（每次随机）。在 `.env` 固定它。
- （macOS 本机开发才会遇到的 `getcwd/Operation not permitted`：给终端授予「Documents/完全磁盘访问」或把项目移出 `~/Documents`；Linux 服务器不受影响。）
