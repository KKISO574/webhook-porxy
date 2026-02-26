#### webhook转发 
适合其他的webhook信息转发到企业微信 
在目录下自己创建.env文件 写入WECHAT_WEBHOOK_URL=你的企业微信webhook地址
```bash
docker-compose up -d
```
访问 http://localhost:1090/ 即可看到转发的webhook信息
### 其他说明
- 端口映射可以根据需要修改，默认是1090映射到容器的8000端口

- 需要确保你的企业微信webhook地址正确，并且服务器能够访问到企业微信的服务器
- 这个服务会持续运行，除非你手动停止它，适合长期使用来转发webhook信息
- 如果需要查看日志，可以使用 `docker-compose logs -f` 来实时查看日志输出
- 如果需要更新代码，可以先停止服务，拉取最新代码，然后重新启动服务：
```bash
docker-compose down
git pull
docker-compose up -d
```
- 这个服务是基于Python的Flask框架构建的，使用了requests库来发送HTTP请求到企业微信的webhook地址
- 你可以根据需要修改代码来添加更多的功能，比如支持不同类型的webhook信息，或者添加一些安全措施来验证来源等
- 这个服务是开源的，你可以根据需要进行修改和扩展，欢迎提交PR或者提出建议！