# Windows 下随系统后台启动 FlyAgent

当前手动命令：

```text
uvicorn app.main:app --host 0.0.0.0 --port 8765
```

后台启动前请确认：**工作目录为项目根目录**（含 `app/`、`.env`），否则配置与数据库路径会错。仓库提供 **`scripts/start_flyagent.bat`**：自动 `cd` 到项目根，并优先使用 **`.venv\Scripts\python.exe`**。

监听地址/端口：bat 使用环境变量 **`FLYAGENT_HOST`**（默认 `0.0.0.0`）、**`FLYAGENT_PORT`**（默认 `8765`）。可在「任务计划程序 → 任务 → 操作 → 编辑 → 起始于」同页配置环境变量，或与 `.env` 里 `FLYAGENT_HOST` / `FLYAGENT_PORT` 保持一致（需自己在任务里设一遍，cmd 不会自动读 `.env`）。

---

## 方式一：任务计划程序（内置，无需第三方）

1. `Win + R` → 输入 `taskschd.msc` → 回车。  
2. **创建任务**（不要用「创建基本任务」，便于精细设置）。  
3. **常规**：名称如 `FlyAgent`；勾选 **不管用户是否登录都要运行**（需输入管理员密码）；配置选 **Windows 10** 或当前系统。  
4. **触发器**：**新建** → **启动时**（或 **登录时** 仅当前用户）。若机器启动后网络较慢，可在触发器里设 **延迟任务** 30～60 秒。  
5. **操作**：**新建** → **启动程序**  
   - **程序或脚本**：浏览到仓库里的 `scripts\start_flyagent.bat`（建议用绝对路径，如 `C:\workspace\python\FlyAgent\scripts\start_flyagent.bat`）。  
   - **起始于（可选）**：项目根目录，例如 `C:\workspace\python\FlyAgent`。  
6. **条件**：可按需取消「只有交流电源才启动」等笔记本限制。  
7. **设置**：可勾选 **如果任务失败，按以下频率重新启动**。  
8. 确定后右键任务 → **运行** 测一次；浏览器访问 `http://127.0.0.1:8765` 验证。

**说明**：以「不管用户是否登录都运行」时，界面里看不到控制台窗口，适合长期后台；日志依赖 uvicorn 默认输出，需要落盘时可改用下方 NSSM 或给 bat 加重定向。

---

## 方式二：NSSM 安装为 Windows 服务（推荐要日志/崩溃重启时）

1. 下载 [NSSM](https://nssm.cc/download)，解压后按系统位数用 `nssm.exe`。  
2. **管理员**打开命令提示符或 PowerShell，执行（路径请改成你的实际目录）：

```bat
nssm install FlyAgent
```

在弹出窗口中设置：

- **Path**：`C:\workspace\python\FlyAgent\.venv\Scripts\python.exe`（无 venv 则填系统 `python.exe`）。  
- **Startup directory**：`C:\workspace\python\FlyAgent`  
- **Arguments**：`-m uvicorn app.main:app --host 0.0.0.0 --port 8765`  

3. 在 NSSM 的 **I/O** 页可设 **stdout/stderr** 到某个 `.log` 文件。  
4. **服务** 应用 → 启动服务：`nssm start FlyAgent` 或在 `services.msc` 里启动 **FlyAgent**。

卸载：`nssm remove FlyAgent confirm`

---

## 防火墙

若局域网其它设备访问，需在 **Windows 防火墙** 中为 **TCP 8765**（或你改的端口）入站放行。
