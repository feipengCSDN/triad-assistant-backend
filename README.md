# 铁三角 APP AI 填报后端

该服务将录音转写为中文文本，并将其识别为“拜访互动任务”或“商机编辑”页面的字段建议。服务不会登录铁三角 APP、不读取 APP 账户数据，也不会自动提交表单；APP 客户端仍负责页面导航、任务类型选择、人工确认与最终提交。

## 业务约束

- 拜访互动：`task_type` 必须由客户端保留原页面选择结果并传入，服务不从语音中修改它。
- 任务类型非“其他”时，互动地点、互动对象姓名/职务/电话/层级、沟通内容为必填；“其他”时，互动地点与说明为必填。
- 互动对象层级仅接受 `高管理`、`中管层`、`一般管理`。模型返回其他值时服务会清空该字段并要求确认。
- 商机编辑：丢单风险、跟踪情况说明、下一步行动策略均为必填。
- 音频、转写与表单数据仅在请求内存中处理，不写磁盘、不持久化。

## 配置与启动

复制 `.env.example` 为 `.env`，填入企业提供的 OpenAI 兼容 ASR 和 LLM 网关配置。当前示例已按智谱配置：ASR 使用 `glm-asr-2512`，LLM 使用 `glm-4-flash`。`ASR_BASE_URL` 需提供 `POST /audio/transcriptions`，`LLM_BASE_URL` 需提供 `POST /chat/completions`。

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\uvicorn visit_report_ai.main:app --reload
```

服务默认监听 `http://127.0.0.1:8000`，健康检查为 `GET /healthz`。

## HTML 测试前端

`web/index.html` 是不依赖前端框架的测试页面。先启动后端，再在项目根目录执行：

```bash
python -m http.server 5500 --directory web
```

浏览器打开 `http://127.0.0.1:5500`。测试页面默认请求 `http://47.94.81.141:8000`，页面右上角可以修改后端地址；跨域测试时，将该页面来源加入服务器的 `CORS_ORIGINS`。

容器部署：

```bash
docker compose up --build -d
```

生产环境应使用 HTTPS 反向代理，仅允许可信客户端访问，并通过部署平台的 Secret 或环境变量注入 `ASR_API_KEY` 和 `LLM_API_KEY`。

## 接口

### 文本识别

`POST /api/v1/form-extractions`

```json
{
  "transcript": "今天在客户总部会议室与采购经理张三沟通了设备交付计划，电话是一三八零零一三八零零零。",
  "form": {
    "fields": [
      {"key": "interaction_location", "label": "互动地点", "required": true},
      {"key": "contact_name", "label": "互动对象姓名", "required": true},
      {"key": "contact_level", "label": "互动对象层级", "options": ["高管理", "中管层", "一般管理"]},
      {"key": "communication_content", "label": "沟通内容", "required": true}
    ]
  },
  "include_metadata": false
}
```

请求包含转写文本、表单定义和可选的 `include_metadata`。前端通过 `form.fields` 决定需要抽取的字段：`key` 是稳定字段标识，`label` 是字段名称，`required` 表示必填项，`options` 可限制候选值。默认 `include_metadata` 为 `false`，响应中的 `fields` 直接返回 `{字段 key: string|null}`，适合 App 自动回填；传 `true` 时才返回 `{value, confidence, evidence}`，并生成低置信度 `warnings`。两种模式都会返回 `missing_required_fields`。

默认轻量模式限制模型输出为 `LLM_MAX_TOKENS`（默认 512）；元数据模式使用 `LLM_METADATA_MAX_TOKENS`（默认 1024）。

### 语音转写

`POST /api/v1/transcriptions`，以 `multipart/form-data` 上传 `audio` 文件。

### APP 语音转写路径

`POST /api/v1/voice-form-extractions` 供 APP 调用，以 `multipart/form-data` 上传 `audio`，后端将请求转发到配置的语音服务 `http://10.90.15.23:8770/v1/asr/transcribe`，并将上游返回的 `text` 转换为 `transcript`。前端无需直接访问上游地址。

上游接口要求 WAV 文件，前端请求字段为 `audio`，后端转发字段为 `file`，并自动传递 `language=zh`。

```bash
curl -X POST http://127.0.0.1:8000/api/v1/voice-form-extractions \
  -F "audio=@visit.wav;type=audio/wav"
```
