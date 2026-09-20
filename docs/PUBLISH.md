# GitHub发布

本目录是独立Git仓库，不需要推送原研究工作区或队友源码/行情。

1. 在自己的GitHub账号创建空仓库 `bitgetstrategy`，建议公开以便评委访问。
2. 按实际地址设置远端并推送：

```bash
git remote add origin https://github.com/cunicle/bitgetstrategy.git
git push -u origin main
```

3. Settings → Pages → Source选择GitHub Actions；Actions中手动运行Publish evidence demo。
4. 打开部署URL，检查首页、留出报告和CSV下载。Pages工作流本身不能证明公网已经发布。
5. 将真实URL补入README、表单说明和X帖，执行提交检查表。

工作流仅手动发布，不会在本地自动创建远端、发X帖或填写比赛表单。
