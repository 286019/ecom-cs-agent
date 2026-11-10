# Render 免费部署手册

本项目自带 `Dockerfile` 和 `render.yaml`，可以部署到 Render 免费实例，得到一个公网可访问的地址。以下步骤中**涉及 GitHub 和 Render 网页操作的部分，需要在有网络的环境由你本人完成**，原因见文末「本机现状」。

---

## 0. 前置条件

- 一个 GitHub 账号
- 一个 Render 账号（可用 GitHub 账号直接登录，免费，不需要绑卡）
- 本机安装 Git
- 一个可用的模型 API Key（如智谱 `glm-4-flash` 的 Key）。**没有 Key 也能部署**，只是运行在 `demo` 演示模式。

---

## 1. 在 GitHub 建仓库并推送

### 1.1 检查并安装 Git

```powershell
git --version
```

如果提示「找不到命令」，到 https://git-scm.com/download/win 下载安装包，默认选项一路下一步即可；或用 winget：

```powershell
winget install --id Git.Git -e --source winget
```

安装完成后**重开一个终端**，再次执行 `git --version` 应输出版本号。

### 1.2 确认 `.env` 不会被提交

项目根目录的 `.gitignore` 已排除 `.env`、`.venv/`、`logs/`、`__pycache__/`。初始化后务必确认：

```powershell
git status --short
```

输出里**不应该出现** `.env`、`.venv`、`logs`。如果出现了，说明 `.gitignore` 被改动，先修正再继续。

### 1.3 初始化并首次提交

```powershell
cd D:\code\ecom-cs-agent
git init
git add .
git commit -m "feat: ecommerce customer-service agent with eval reports"
```

### 1.4 在 GitHub 新建仓库并推送

1. 打开 https://github.com/new
2. Repository name 填 `ecom-cs-agent`
3. 选 **Private** 或 Public 均可，**不要**勾选 Add README / .gitignore / license（本地已有）
4. 创建后按页面提示推送：

```powershell
git remote add origin https://github.com/<你的用户名>/ecom-cs-agent.git
git branch -M main
git push -u origin main
```

> 推送只需用户名 + Personal Access Token（GitHub 已不支持密码推送）。Token 在 GitHub → Settings → Developer settings → Personal access tokens 中生成，勾选 `repo` 权限。

---

## 2. 在 Render 接入

两种方式任选其一，推荐 **Blueprint**，因为 `render.yaml` 已经写好了配置。

### 方式 A：Blueprint（推荐）

1. 登录 https://dashboard.render.com
2. 点 **New +** → **Blueprint**
3. 选择刚才的 GitHub 仓库，Render 会自动识别根目录的 `render.yaml`
4. 服务名默认 `ecom-cs-agent`，实例类型 `Free`
5. Render 会提示需要填写 `API_KEY`（`render.yaml` 里标了 `sync: false`，即不在仓库里存值）
6. 点 **Apply / Deploy**

### 方式 B：手动 Web Service

1. **New +** → **Web Service**
2. 连接同一个仓库
3. 配置：
   - Runtime：**Docker**
   - Dockerfile Path：`./Dockerfile`
   - Instance Type：**Free**
   - Health Check Path：`/health`
4. 在 **Environment** 里加环境变量（见下一节）
5. 点 **Create Web Service**

---

## 3. 环境变量

在 Render 服务的 **Environment** 页面填写：

| Key | Value | 说明 |
| --- | --- | --- |
| `PROVIDER` | `zhipu` | 模型供应商；用其他兼容 OpenAI 协议的供应商时改为 `custom` 并加 `OPENAI_BASE_URL`、`MODEL_NAME` |
| `API_KEY` | 你的 Key | **只在 Render 控制台填**，不要写进仓库 |
| `HOST` | `0.0.0.0` | 已在 `render.yaml` 中给出 |
| `TOOL_BACKEND` | `mock` | 工具层用内置 mock 数据，不需要外部业务系统 |
| `PORT` | 不用填 | Render 自动注入，应用会读取该变量；本地才需要手动指定 |

> 不想暴露真实 Key 做演示时：把 `API_KEY` 留空，服务会以 `demo` 模式运行，界面和链路完整，只是回复来自内置话术与本地检索。

---

## 4. 免费实例的行为

- **15 分钟无请求自动休眠**：免费 Web Service 在没有流量时会进入休眠，进程被回收。
- **冷启动**：休眠后第一个请求会触发重新启动，通常需要 **30～60 秒**，期间浏览器可能一直转圈或返回 502，刷新即可。
- **建议**：面试演示前 1～2 分钟先访问一次 `/health` 把实例唤醒，避免当场等冷启动。
- 免费实例每月有额度上限，足够个人演示使用；不要用于真实业务流量。

---

## 5. 部署后验证

1. 打开 Render 服务页面，等待状态变为 **Live**（首次构建约 3～8 分钟）
2. 访问 `https://<服务名>.onrender.com/health`，确认关键字段：

```json
{
  "mode": "live",
  "provider_label": "智谱 GLM",
  "model": "glm-4-flash",
  "knowledge_chunks": 33,
  "tools": 6
}
```

- `mode=live` 表示已读取到 `API_KEY`，走真实模型。
- 若 `mode=demo`，说明环境变量没生效：检查 `API_KEY` 是否填错、是否点了 **Save changes** 并触发重新部署。
- `knowledge_chunks` 应大于 0；为 0 说明知识库目录没进镜像，检查 `.dockerignore` 是否误排除了 `knowledge/*.md`。
3. 打开根路径 `https://<服务名>.onrender.com/`，问一句「退换货政策是什么」，能返回带来源的答案即部署成功。
4. Render 的 **Logs** 页面可看启动日志；应用也会把启动地址写入容器内 `logs/server_url.txt`。

---

## 6. 为什么不用 `.env` 文件

- `.env` 是本地开发用的载体，里面是明文 Key。一旦提交进 Git 仓库，等于把 Key 公开在历史记录里，无法通过删除文件挽回。
- Render 的容器每次部署都是全新的，`render.yaml` 里明确不引用 `.env`；运行时配置统一来自**平台环境变量**（Render 控制台或 Blueprint 的 `envVars`）。
- 因此：**仓库里只有 `.env.example`（不含任何真实值），真实 Key 只存在于 Render 的环境变量中**。本地开发照常用 `.env`，两者互不影响。

---

## 本机现状（需要你操作的部分）

本次准备时在本机检查过：

- **未安装 Git**，且当前网络无法访问 GitHub（`curl https://github.com` 超时），winget 下载 Git 安装包也失败（`InternetOpenUrl() failed 0x80072efd`）。
- 因此**本机无法完成 `git init` / 首次提交 / push**，也没有远端仓库。

所以第 1 节的 Git 安装、建仓、推送，以及第 2～3 节的 Render 网页操作，**都需要你在有网络的环境中手动完成**。代码侧能提前做的已经做完：

- `Dockerfile`、`render.yaml`、`.dockerignore`、`requirements.txt`、`.env.example` 均已就绪
- `.gitignore` 已排除 `.env` / `.venv` / `logs` / `__pycache__`，不会误提交密钥
- 服务已读取 `PORT` / `HOST` 环境变量，适配 Render 的端口注入
