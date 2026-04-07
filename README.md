#### webhook转发 
适合其他的webhook信息转发到企业微信 
在目录下创建 `.env` 文件，写入你的企业微信 webhook 地址：
```env
WECHAT_WEBHOOK_URL=你的企业微信webhook地址
SHOW_CSLOG_SUMMARY=true
SHOW_CSLOG_PAGED=true
SHOW_CSLOG_DETAIL=true
```

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
