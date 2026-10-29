# hakuX 简体中文自动汉化构建补丁

将本压缩包内的文件按目录结构复制到你的 `Kanadeforever/hakuX` 仓库根目录。

然后提交并推送到默认分支，在 GitHub 仓库设置中允许 Actions 对仓库内容进行读写，最后从 Actions 页面手动运行一次工作流。

此补丁：
- 每日检查上游 Latest Release；
- 只在发现新正式版本时编译；
- 应用首版简体中文词条；
- 使用固定签名密钥，需要配置四项 GitHub Actions Secrets；
- 成功后在你的仓库 Releases 中发布 APK 和源码附件。

首版词条是部分汉化，工作流会附带未匹配词条报告。未通过汉化或构建检查时不会发布。


## 固定签名密钥配置

请使用单独提供的 `hakuX_zhcn_release_signing.jks` 与 `hakuX_GitHub_Secrets_配置.txt`。按配置文本中的四个 Secret 名称填写到 GitHub 仓库的 `Settings → Secrets and variables → Actions`。密钥库与配置文本包含私钥材料，不得提交到公开仓库。
