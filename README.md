#### webhook转发 
适合其他的webhook信息转发到企业微信 
在目录下创建 `.env` 文件，写入你的企业微信 webhook 地址：
```env
WECHAT_WEBHOOK_URL=你的企业微信webhook地址
SHOW_CSLOG_SUMMARY=true
SHOW_CSLOG_PAGED=true
SHOW_CSLOG_DETAIL=true
```

### CSQAQ 库存监控动态转发
接口文档：`https://docs.csqaq.com/api-358158458`

配置 `CSQAQ_API_TOKEN` 和库存监控任务后，服务会按间隔请求：
`POST https://api.csqaq.com/api/v1/task/get_task_business`

请求 Body 字段对应接口文档：
- `page_index`：页码，服务会从第 1 页开始抓取
- `page_size`：每页数量
- `task_id`：库存监控任务 id
- `search`：搜索关键词，可留空
- `type`：动态类型过滤，默认 `ALL`；当前输出映射为 `0=默认库存`、`4=取出组件`、`5=cd恢复`、`7=卖出/存入组件`

推荐用 JSON 配置多个任务，每个任务会独立执行、独立去重，并按批次推送企业微信 markdown：
```env
CSQAQ_API_TOKEN=你的CSQAQ_API_TOKEN
CSQAQ_INVENTORY_INTERVAL_SECONDS=300
CSQAQ_INVENTORY_BATCH_SIZE=10
CSQAQ_INVENTORY_SEND_INITIAL=false
CSQAQ_INVENTORY_TASKS=[{"task_id":34,"name":"用户A-武器箱","search":"武器箱","type":"ALL","page_size":50,"max_pages":1},{"task_id":1431,"name":"用户B-全部动态","search":"","type":"ALL","page_size":50,"max_pages":1}]
```

如果只需要按任务 id 监控，也可以用逗号分隔：
```env
CSQAQ_API_TOKEN=你的CSQAQ_API_TOKEN
CSQAQ_INVENTORY_TASK_IDS=34,1431
CSQAQ_INVENTORY_SEARCH=
CSQAQ_INVENTORY_TYPE=ALL
```

常用配置：
- `CSQAQ_INVENTORY_INTERVAL_SECONDS`：轮询间隔秒数，默认 `300`，最小 `30`
- `CSQAQ_INVENTORY_PAGE_SIZE`：默认每页数量，默认 `50`
- `CSQAQ_INVENTORY_MAX_PAGES`：每轮每个任务最多抓取页数，默认 `1`
- `CSQAQ_INVENTORY_BATCH_SIZE`：每条企业微信 markdown 最多包含多少条动态，默认 `10`
- `CSQAQ_INVENTORY_SEND_INITIAL`：首次启动是否推送已存在的历史动态，默认 `false`；默认只记录基线，避免刷屏
- `CSQAQ_INVENTORY_STATE_FILE`：去重状态文件，默认 `logs/csqaq_inventory_state.json`
- `CSQAQ_INVENTORY_TYPE_LABELS`：自定义动态类型文案，例如 `{"0":"默认库存","4":"取出组件","5":"cd恢复","7":"卖出/存入组件"}`

服务接口：
- `GET /csqaq/inventory/status`：查看库存监控配置和运行状态
- `POST /csqaq/inventory/run`：立即执行一次所有库存监控任务，适合测试

注意：库存动态 `type` 默认输出为 `0=默认库存`、`4=取出组件`、`5=cd恢复`、`7=卖出/存入组件`。如果后续需要改文案，可以用 `CSQAQ_INVENTORY_TYPE_LABELS` 覆盖。

首次启动建议执行：
```bash
docker compose up -d --build
```

服务启动后可访问健康检查：
`http://localhost:8000/health`

接收 webhook 的地址：
`http://localhost:8000/webhook/incoming`

### 其他说明
- 端口映射可以根据需要修改，默认是 `8000:8000`

- 需要确保你的企业微信webhook地址正确，并且服务器能够访问到企业微信的服务器
- 这个服务会持续运行，除非你手动停止它，适合长期使用来转发webhook信息
- 如果需要查看日志，可以使用 `docker compose logs -f` 来实时查看日志输出
- 如果需要更新代码，可以先停止服务，拉取最新代码，然后重新启动服务：
```bash
docker compose down
git pull
docker compose up -d --build
```
- 这个服务是基于 Python 的 FastAPI 构建的，使用 `requests` 库将 webhook 转发到企业微信
- `SHOW_CSLOG_SUMMARY`、`SHOW_CSLOG_PAGED`、`SHOW_CSLOG_DETAIL` 可用于控制企业微信里显示哪些 cslog 模块
- 你可以根据需要修改代码来添加更多的功能，比如支持不同类型的webhook信息，或者添加一些安全措施来验证来源等
- 这个服务是开源的，你可以根据需要进行修改和扩展，欢迎提交PR或者提出建议！
