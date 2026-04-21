# FlyAgent Ubuntu 部署说明

本文说明在 **Ubuntu 22.04 LTS**（或相近版本）上部署 FlyAgent 的推荐流程：Python 虚拟环境、环境变量、进程守护（systemd）、可选 Nginx 反向代理。

---

## 1. 服务器要求

| 项目 | 说明 |
|------|------|
| 系统 | Ubuntu 20.04 / 22.04 / 24.04 等 |
| Python | **3.10+**（推荐 3.12；需与依赖兼容） |
| 网络 | 需能访问各模型 API；阿里云 NLS 需能访问阿里云网关 |
| 磁盘 | 预留 SQLite 与日志空间；`data/` 目录会写入数据库 |

---

## 2. 安装系统依赖

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git
```

> `requirements.txt` 中的 `nls` 通过 **Git** 从 GitHub 安装，请务必安装 `git`。

---

## 3. 部署代码

将项目放到固定目录（示例：`/opt/flyagent`）：

```bash
sudo mkdir -p /opt/flyagent
sudo chown "$USER":"$USER" /opt/flyagent
# 方式一：git clone 你的仓库到 /opt/flyagent
# 方式二：scp/rsync 上传整个项目目录
cd /opt/flyagent
```

---

## 4. Python 虚拟环境与依赖

```bash
cd /opt/flyagent
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

若 `pip install` 因网络拉取 GitHub 失败，可配置代理或使用国内镜像源后再试。

---

## 5. 配置环境变量

```bash
cp .env.example .env
nano .env   # 或使用 vim
```

**必填（按功能）：**

- **大模型**：在 `models.yaml` 中配置各模型；在 `.env` 中填写 `models.yaml` 里 `api_key_env` 指向的变量（如 `QWEN_API_KEY`）。
- **阿里云语音（ASR/TTS）**：`NLS_ACCESS_KEY_ID`、`NLS_ACCESS_KEY_SECRET`、`NLS_APP_KEY`。
- **生产环境强烈建议**：
  - `FLYAGENT_API_KEY`：保护 `/api/chat`、`/api/asr/*`、`/api/tts`、`/api/voice/chat` 等接口。
  - `FLYAGENT_ADMIN_USER`、`FLYAGENT_ADMIN_PASSWORD`、`FLYAGENT_SESSION_SECRET`：管理页登录。

可选：

- `FLYAGENT_HOST` / `FLYAGENT_PORT`：应用监听地址与端口（见下文 systemd）。
- `FLYAGENT_DB_PATH`：SQLite 路径，默认 `./data/flyagent.db`。
- `FLYAGENT_MODELS_PATH`：`models.yaml` 路径（默认项目根目录 `models.yaml`）。
- NLS TTS：`NLS_TTS_VOICE`、`NLS_TTS_FORMAT` 等（见 `.env.example`）。

**不要将 `.env` 提交到 Git**（仓库已 `.gitignore`）。

---

## 6. 启动验证（手动）

```bash
cd /opt/flyagent
source .venv/bin/activate
export FLYAGENT_HOST=0.0.0.0
export FLYAGENT_PORT=8765
uvicorn app.main:app --host 0.0.0.0 --port 8765
```

浏览器访问：`http://服务器IP:8765/`（管理页）。

健康与接口示例：

```bash
curl -s http://127.0.0.1:8765/api/asr/ready
curl -s http://127.0.0.1:8765/api/presets
```

若配置了 `FLYAGENT_API_KEY`，请求需加：

```bash
curl -s -H "X-API-Key: 你的密钥" http://127.0.0.1:8765/api/presets
```

完整 HTTP 说明见项目根目录 **`HTTP_API文档.md`**。

---

## 7. systemd 常驻（推荐，**开机自启**）

用 **systemd** 管理进程：崩溃可自动拉起，**开机自动运行**（`enable` 后无需再手敲 `uvicorn`）。

仓库提供示例单元文件：**`scripts/flyagent.service.example`**，可复制到 `/etc/systemd/system/flyagent.service` 后按你的安装路径修改 `User` / `WorkingDirectory` / `ExecStart`。

创建服务用户（可选，更安全）：

```bash
sudo useradd -r -s /usr/sbin/nologin flyagent 2>/dev/null || true
sudo chown -R flyagent:flyagent /opt/flyagent
```

创建服务文件：

```bash
# 若已把项目放在 /opt/flyagent，可直接：
sudo cp /opt/flyagent/scripts/flyagent.service.example /etc/systemd/system/flyagent.service
sudo nano /etc/systemd/system/flyagent.service   # 核对路径、端口、User

# 或手动创建：
sudo nano /etc/systemd/system/flyagent.service
```

内容示例（按实际路径修改 `User` / `WorkingDirectory`；与下面示例等价时可不手写）：

```ini
[Unit]
Description=FlyAgent FastAPI (uvicorn)
After=network.target

[Service]
Type=simple
User=flyagent
Group=flyagent
WorkingDirectory=/opt/flyagent
Environment=PATH=/opt/flyagent/.venv/bin
ExecStart=/opt/flyagent/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8765
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

启用并启动（**`enable` = 写入开机自启**）：

```bash
sudo systemctl daemon-reload
sudo systemctl enable flyagent    # 随 multi-user.target 开机启动
sudo systemctl start flyagent     # 立即启动
sudo systemctl status flyagent
```

取消开机自启：`sudo systemctl disable flyagent`（不删单元文件）。

日志：

```bash
sudo journalctl -u flyagent -f
```

---

## 8. 防火墙

若仅内网访问可跳过；若公网暴露：

```bash
sudo ufw allow 8765/tcp comment 'FlyAgent'
sudo ufw enable
sudo ufw status
```

生产环境更推荐 **只开放 80/443**，由 Nginx 反代到本机 `127.0.0.1:8765`。

---

## 9. Nginx 反向代理（可选）

安装：

```bash
sudo apt install -y nginx
```

站点示例 `/etc/nginx/sites-available/flyagent`：

```nginx
server {
    listen 80;
    server_name your.domain.com;

    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        # WebSocket（若使用 /api/asr/stream）
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        client_max_body_size 100M;
    }
}
```

启用站点并重载：

```bash
sudo ln -sf /etc/nginx/sites-available/flyagent /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

HTTPS 建议使用 **Let’s Encrypt**（`certbot`）为 `server_name` 申请证书后，在 Nginx 中配置 `listen 443 ssl`。

---

## 10. 升级与维护

```bash
cd /opt/flyagent
git pull   # 若使用 Git
source .venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart flyagent
```

数据库文件默认在 `data/flyagent.db`，请纳入备份策略。

---

## 11. 常见问题

| 现象 | 处理 |
|------|------|
| `No module named 'aliyunsdkcore'` | 确认已执行 `pip install -r requirements.txt`，且含 `aliyun-python-sdk-core`。 |
| `nls` 安装失败 | 安装 `git`，检查服务器能否访问 GitHub。 |
| 外网无法访问 | 检查 `uvicorn` 是否 `--host 0.0.0.0`、安全组/防火墙、Nginx `proxy_pass`。 |
| 管理页无法登录 | 检查 `.env` 中 `FLYAGENT_SESSION_SECRET` 是否在启用管理登录时已配置。 |
| 大模型 502 | 检查 `models.yaml` 与对应 `*_API_KEY`；查看日志与阿里云/厂商控制台额度。 |

---

## 12. 相关文档

- 客户端 HTTP 接口：`HTTP_API文档.md`
- 模型与聊天预设：`models.yaml`
- 环境变量示例：`.env.example`
- systemd 单元模板：`scripts/flyagent.service.example`
- Windows 计划任务 / NSSM：`docs/WINDOWS_STARTUP.md`（仅 Windows）
