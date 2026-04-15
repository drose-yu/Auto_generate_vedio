# 豆包工作流复刻台

这个项目用 `FastAPI + Vue 3 + TypeScript` 复刻了你贴出来的 Coze 工作流，并把结果整合成一个可视化页面：

- 输入剧情文本
- 前端选择豆包 / 火山方舟的非敏感运行参数
- 密钥类信息统一从 `backend/.env` 读取
- 点击运行后，后端串行编排以下步骤：
  1. 生成标题与 8 个剧情节点
  2. 提取角色并生成角色视觉描述
  3. 提取每个镜头里出现的角色
  4. 批量生成角色原型图
  5. 为每个剧情节点生成运镜提示词
  6. 清洗旁白文本并合成音频
  7. 输出最终 shots 映射
- 前端可查看运行进度条与分阶段日志
- 运行中可点击“停止运行”取消后台任务
- 可导出 `result.json`
- 可打包下载角色图片与旁白音频 ZIP
- 文本模型支持“主模型 + 按节点覆写”，图片模型和 TTS 独立配置

## 目录结构

```text
backend/
  app/
    api/routes/workflow.py
    core/config.py
    models/schemas.py
    services/
frontend/
  src/
    App.vue
    lib/
```

## 后端启动

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .[dev]
uvicorn app.main:app --reload --port 8010
```

默认地址：`http://127.0.0.1:8010`

后端启动前，请先准备 `backend/.env`：

```powershell
cd backend
Copy-Item .env.example .env
```

然后填写：

```dotenv
APP_DOUBAO_API_KEY=你的豆包APIKey
APP_TTS_APP_ID=你的TTS App ID
APP_TTS_ACCESS_TOKEN=你的TTS Access Token
APP_TTS_CLUSTER=volcano_tts
```

## 前端启动

```powershell
cd frontend
npm install
npm run dev
```

默认地址：`http://127.0.0.1:5173`

前端已经把 `/api` 和 `/health` 代理到本地 `8010` 端口。

## 表单参数建议

- `Base URL`：默认填的是 `https://ark.cn-beijing.volces.com/api/v3`
- `主文本模型 / 接入点 ID`：这是文本节点的默认模型；优先使用方舟控制台中的 `ep-...` 接入点 ID
- `高级配置：按节点覆写文本模型`：可为剧情拆解、角色提取、镜头角色映射、运镜提示词分别指定模型；不填就继承主文本模型
- `图片模型 / 接入点 ID`：填写可访问的图片模型 ID 或图片接入点；不填时会跳过角色图生成
- `API Key / TTS 凭证`：不再从前端输入，统一由后端读取 `backend/.env`
- 如果返回 `InvalidEndpointOrModel.NotFound`，通常表示当前账号未开通该模型，或者该账号必须通过 `ep-...` 接入点调用

## 说明

- 这次实现保留了原工作流的主干能力，但把它整理成了更稳定的后端编排。
- 原工作流中“根据剧情节点生成运镜”节点没有正确接入角色变量，这里已经在后端补齐，运镜生成会显式使用当前镜头角色与角色描述。
- 浏览器本地缓存里的旧模型值会自动迁移，例如旧版 `doubao-seed-character` 不会再被继续提交。
- 如果图片模型或 TTS 未配置，接口不会失败，而是返回结构化结果并附带 warning。
- 新增了任务式接口，前端通过轮询任务状态显示实时进度和日志。

