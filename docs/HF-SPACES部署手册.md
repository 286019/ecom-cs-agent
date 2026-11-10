# Hugging Face Spaces 部署手册（Docker SDK，备选方案）

本手册是 Render 的备选路径：同一套代码、同一个 Dockerfile，不改 `render.yaml`，可直接部署到 Hugging Face Spaces 的 Docker SDK。**本机没有发布 Space，也没有写入任何真实 Key**，上线动作需要你本人操作。

---

## 0. 结论：这条路可行，但有前提

| 检查项 | 结论 |
| --- | --- |
| 端口 | HF Docker Space 固定要求监听 `0.0.0.0:7860`。已在 `Dockerfile` 里加 `ENV PORT=7860`、`EXPOSE 7860`，并在 README YAML 头写 `app_port: 7860` |
| 与 Render 共存 | Render 运行时会注入自己的 `PORT`，覆盖镜像默认值，因此 `render.yaml` 无需改动 |
| 容器权限 | HF 以 uid 1000 运行容器，镜像里已把 `logs/` 设为可写（`chmod 777`），避免启动时写日志失败 |
| 体积 | 镜像只装 4 个 Python 依赖，代码 + 知识库 + 评测报告 < 2 MB，构建很快 |
| 硬性障碍 | 无技术硬障碍；真正的障碍是**网络**：`huggingface.co` 在国内的连通性和 GitHub 类似，可能同样打不开 |

**如果 huggingface.co 也打不开**：这条路同样走不通，建议换国内平台，见文末「替代平台」。

---

## 1. 前置条件

- 一个 Hugging Face 账号（https://huggingface.co/join，邮箱注册即可，免费）
- 能访问 huggingface.co 的网络
- 可选：一个模型 API Key（不填则运行在 `demo` 演示模式，流程完整）

---

## 2. 创建 Space

1. 登录后打开 https://huggingface.co/new-space
2. 填写：
   - **Space name**：`ecom-cs-agent`
   - **License**：MIT（与仓库 `LICENSE` 一致）
   - **Select the Space SDK**：选 **Docker** → **Blank**
   - **Space hardware**：**CPU basic · 2 vCPU · 16 GB · FREE**
   - **Visibility**：**Public**（免费账号一般只能建公开 Space；私有 Space 通常需要 Pro 订阅。公开不影响安全，Key 不放代码里）
3. 点 **Create Space**

创建完成后，Space 仓库地址形如：

```
https://huggingface.co/spaces/<你的用户名>/ecom-cs-agent
```

---

## 3. 上传代码

两种方式，二选一。

### 方式 A：网页上传（不需要本机 git）

1. 进入 Space 页面 → **Files** 标签
2. **Add file** → **Upload files**
3. 把项目里的这些内容拖进去（保持目录结构）：
   - `Dockerfile`、`README.md`、`requirements.txt`、`.env.example`
   - `app/`、`config/`、`knowledge/`、`static/`、`eval/`、`docs/`
4. **不要上传**：`.env`、`.venv/`、`logs/`、`screenshots/`
5. 填 commit message → **Commit changes to main**

> 网页上传对目录结构支持一般，文件多时容易漏。更稳的是方式 B。

### 方式 B：git 推送（推荐）

```powershell
& 'D:\a\code_soft\Git\cmd\git.exe' clone https://huggingface.co/spaces/<用户名>/ecom-cs-agent hf-space
```

把项目文件复制进 `hf-space`（同样排除 `.env` / `.venv` / `logs` / `screenshots`），然后：

```powershell
cd hf-space
& 'D:\a\code_soft\Git\cmd\git.exe' add .
& 'D:\a\code_soft\Git\cmd\git.exe' commit -m "deploy: ecom-cs-agent"
& 'D:\a\code_soft\Git\cmd\git.exe' push
```

推送时用户名填 HF 用户名，**密码填 Access Token**（https://huggingface.co/settings/tokens 新建，勾 `write` 权限），不是账号密码。

> HF 的仓库对 README 顶部 YAML 很敏感：`sdk: docker` 与 `app_port: 7860` 必须保留，否则 Space 会按错误的方式启动。

---

## 4. 配置环境变量（Settings）

进入 Space → **Settings** → **Variables and secrets**：

| 类型 | Name | Value | 说明 |
| --- | --- | --- | --- |
| Secret | `API_KEY` | 你的模型 Key | 加密保存，不会出现在仓库和日志里 |
| Variable | `PROVIDER` | `zhipu` | 非敏感，用 Variable 即可 |

- 不配 `API_KEY`：服务以 `demo` 模式运行，可正常演示，`/health` 显示 `mode=demo`。
- 配了 `API_KEY`：`/health` 显示 `mode=live`，走真实模型。
- 保存后 Space 会自动重建（Restart this Space 也可以）。

---

## 5. 首次构建与等待

- 提交代码后 Space 进入 **Building**，可在 **Logs → Build** 查看
- 本项目依赖少，通常 2～5 分钟完成；完成后状态变为 **Running**
- 构建失败常见原因：
  - `Dockerfile` 不在仓库根目录
  - README YAML 头被改坏（缺 `sdk: docker`）
  - `requirements.txt` 路径不对

---

## 6. 部署后验证

1. 打开 Space 页面，应直接加载聊天界面（端口 7860）
2. 访问 `https://<用户名>-ecom-cs-agent.hf.space/health`，预期：

```json
{
  "mode": "live",
  "model": "glm-4-flash",
  "knowledge_chunks": 33,
  "tools": 6
}
```

- `mode=live`：说明 Settings 里的 `API_KEY` 已注入
- `knowledge_chunks=33`：说明 `knowledge/*.md` 已进镜像（.dockerignore 没有误排除）
- 若 `mode=demo`：检查 Secret 名称是否为 `API_KEY`、`PROVIDER` 是否为 `zhipu`，改完点 Restart
3. 回到首页问「退换货政策是什么」，能返回带来源的答案即成功

---

## 7. 免费实例的休眠行为

- 免费 CPU basic Space 在**约 48 小时无访问**后自动休眠（不是 15 分钟，比 Render 宽松）
- 休眠后第一次访问会自动唤醒，冷启动通常 **30～90 秒**，期间页面可能白屏或转圈，刷新即可
- 容器磁盘是**临时的**：`logs/`、`data/embedding_cache.json` 在重建/重启后丢失，不影响功能（会重新生成）
- Space 代码公开可见；Key 在 Secrets 里，不会随代码泄露

---

## 8. 与 Render 方案的取舍

| 维度 | Render（Blueprint） | Hugging Face Spaces（Docker） |
| --- | --- | --- |
| 接入方式 | 连 GitHub 仓库，读 `render.yaml` | 直接推 HF 仓库，无 CI 配置 |
| 依赖 GitHub | **是**（本机打不开，卡住的原因） | **否**，只需要 HF 账号 |
| 国内可达性 | 控制台与 onrender.com 通常可访问 | huggingface.co 可能同样被墙，需代理或镜像 |
| 端口 | 平台注入 `PORT` | 固定 7860（已适配） |
| 免费休眠 | 15 分钟无请求休眠，冷启动 30～60 秒 | 约 48 小时无访问休眠，冷启动 30～90 秒 |
| 配置注入 | 控制台环境变量 / Blueprint `envVars` | Settings → Variables and secrets |
| 代码可见性 | 取决于 GitHub 仓库（可私有） | 免费账号一般只能公开 Space |
| 适合场景 | 有 GitHub、想接自己仓库 | 没有 GitHub、或想快速拿到公网地址 |

**建议**：优先保留 Render 配置不动；GitHub 恢复后仍用 Render。HF Spaces 作为「GitHub 不可用」时的备份出口，两边共用同一个 `Dockerfile`，不产生分叉。

---

## 9. 替代平台（若 HF 也不可达）

- **ModelScope 创空间**：国内站点，支持 Docker 部署，流程与 HF Space 接近（需魔搭账号）
- **阿里云函数计算 / 轻量应用服务器**：直接 `docker run`，可控性最好，但需要备案域名或按量计费
- 共同点：都需要一个能 `docker build` 的环境；本项目镜像不依赖任何平台私有能力，迁移成本就是一条 `docker run -p 7860:7860`

---

## 10. 本次没有做的事

- 没有实际创建 Space、没有 push、没有填写真实 Key
- 没有修改 `render.yaml`，Render 路径保持原样
- Space 侧唯一需要你手动完成的是：注册 HF 账号 → 建 Space → 上传/推送 → 填 `API_KEY`
