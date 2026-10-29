# hakuX 汉化版

本仓库为上游仓库的汉化版，利用Github Action自动检测与拉取上游最新发行版，并自动构建中文翻译apk。

如果发现当前版本缺字，那可能是上游仓库有变化，请耐心等待追加翻译。

下方的原始readme仅作简体中文翻译，内容只字未改。

本仓库许可与分发均与上游完全相同：

hakuX 汉化版同样是免费的，而且将永远免费。唯一的汉化下载渠道是 [hakuX 汉化版的 GitHub releases](https://github.com/Kanadeforever/hakuX/releases)。

---

# hakuX

hakuX 在 Android（arm64）上运行原版 Xbox 游戏，并针对 Adreno GPU 进行了调优。

其核心在一个 JIT（FEX 的一个分支）上运行游戏的 x86 代码，该 JIT 运行在 Xbox 内核的重实现之下；并通过解码游戏自身的 Direct3D 发送给 NV2A 的推送缓冲区（push buffer）来绘制到 Vulkan。音频是 MCPX APU，从 xemu 移植而来。

## hakuX 是免费的

hakuX 是免费的，而且将永远免费。唯一的官方下载渠道是 [hakuX 的 GitHub releases](https://github.com/rfandango/hakuX/releases)。

如果你以任何方式、任何形式为 hakuX 付过费，那你就是被骗了。这包括商店购买、订阅、应用内解锁、“高级”版本，或任何将其重新打包的应用。请向你付费的地方申请退款，并在此处免费获取 hakuX。

## 要求

- 一台支持 Vulkan 的 arm64 Android 设备。Adreno GPU 可以加载自定义 Turnip 驱动。
- 你自己的游戏镜像（ISO 或 XISO），从你拥有的光盘中提取。

不需要 BIOS、MCPX ROM 或硬盘镜像。hakuX 不包含任何受版权保护的 Xbox 软件。

## 构建

参见 [android/README.md](android/README.md)。

## 许可证

hakuX 是 GNU 通用公共许可证第 3 版或更高版本（[COPYING](COPYING)）下的自由软件：任何分发它或基于它的作品的人，都必须以相同的许可证提供完整源代码。从 xemu 移植的代码（MCPX APU）以及第三方组件保留各自的许可证，列于 [LICENSE](LICENSE) 和 [licenses/](licenses/) 中。

## 说明

- hakuX 与 Microsoft 无关联。
