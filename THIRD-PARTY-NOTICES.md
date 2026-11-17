# 第三方组件与许可证

ZZBox 自身的源码以 [MIT](LICENSE) 授权。下面这些组件是**独立作品**，各自遵循自己的许可证，不因被打包在同一个文件夹里而改变。

---

## 1. FFmpeg（GPLv3）

| 项目 | 内容 |
|---|---|
| 程序 | `ffmpeg.exe`、`ffprobe.exe` |
| 版本 | `7.1-essentials_build`（以随包 `ffmpeg.exe -version` 的实际输出为准） |
| 来源 | [gyan.dev/ffmpeg/builds](https://www.gyan.dev/ffmpeg/builds/) |
| 上游 | [ffmpeg.org](https://ffmpeg.org/) |
| 许可证 | **GNU General Public License v3**（全文见 [licenses/GPL-3.0.txt](licenses/GPL-3.0.txt)） |

### 为什么是 GPLv3

该构建的编译参数包含：

```
--enable-gpl --enable-version3
--enable-libx264 --enable-libx265 --enable-libaom
```

`--enable-gpl` 启用 GPL 组件（x264、x265 等），`--enable-version3` 把整体提升到 GPLv3。构建中**没有** `--enable-nonfree`，因此可以合法再分发。

### 与主程序的关系

ZZBox 通过 **子进程调用命令行** 使用 FFmpeg（`subprocess` 执行 `ffmpeg.exe`），没有链接 FFmpeg 的库、没有包含其头文件、没有静态或动态链接其目标代码。按 FSF 对 GPL 的解释以及 FFmpeg 官方 FAQ 的说明，这属于**两个独立程序的聚合（aggregate）**，不构成衍生作品。

因此：
- ZZBox 的源码可以继续使用 MIT
- FFmpeg 二进制仍然完整地受 GPLv3 约束，必须按 GPLv3 分发

### 分发时你需要做什么

只要你在分发里带上 `ffmpeg.exe` / `ffprobe.exe`，就必须：

1. **附上许可证全文** —— 本仓库的 `licenses/GPL-3.0.txt` 随包分发即可
2. **提供对应源码** —— 三种做法任选：
   - 附上该版本 FFmpeg 的完整源码（约 15 MB 压缩包）
   - 给出**书面要约**：明确承诺在收到请求后提供源码（有效期至少三年）
   - 给出**等效访问方式**：指向 [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) 的对应版本及其源码包下载页
3. **保留版权声明** —— 不要删除二进制里的版权信息，不要改名冒充自己的作品
4. **如果你改过 FFmpeg 源码** —— 需要公开你的修改（本项目没有修改）

**对应的源码获取地址**（第三方构建，源码同页提供）：
<https://www.gyan.dev/ffmpeg/builds/>（`ffmpeg-7.1-essentials_build` 对应的 source 包）

> 升级 FFmpeg 时请同步修改本节与 README 里的版本号 —— 这份文件是履行 GPLv3 告知义务的载体，写成旧版本等于没告知。

**上游源码**：<https://ffmpeg.org/download.html> · 镜像 <https://git.ffmpeg.org/ffmpeg.git>

### 想彻底避开这些义务

用 **lite 包**：不内附 FFmpeg，由使用者自行准备（放进 `bin\` 或加到 PATH）。此时你分发的只有 MIT 授权的 ZZBox，GPL 义务不适用于你。

---

## 2. AI 增强引擎（Real-ESRGAN / RIFE / ncnn）

`bin/ai/` 下的两个可执行程序同样是**独立作品**，和 FFmpeg 一样通过子进程命令行调用，不与主程序链接。

### 2.1 Real-ESRGAN（BSD-3-Clause）

| 项目 | 内容 |
|---|---|
| 程序 | `bin/ai/esrgan/realesrgan-ncnn-vulkan.exe` 及其 `models/` 权重 |
| 上游 | [xinntao/Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN) |
| 许可证 | **BSD 3-Clause**（全文见 [licenses/Real-ESRGAN-BSD-3-Clause.txt](licenses/Real-ESRGAN-BSD-3-Clause.txt)） |
| 商用 | 允许，保留版权声明与免责声明即可 |

用到的权重：`realesr-animevideov3`（x2/x3/x4）与 `realesrgan-x4plus`，由上游以同一许可证发布。

### 2.2 RIFE / rife-ncnn-vulkan（MIT）

| 项目 | 内容 |
|---|---|
| 程序 | `bin/ai/rife/rife-ncnn-vulkan.exe` 及 `rife-v4.6/` 权重 |
| 算法 | [hzwer/ECCV2022-RIFE](https://github.com/hzwer/ECCV2022-RIFE)（MIT） |
| ncnn 实现 | [nihui/rife-ncnn-vulkan](https://github.com/nihui/rife-ncnn-vulkan)（MIT，全文见 [licenses/rife-ncnn-vulkan-LICENSE.txt](licenses/rife-ncnn-vulkan-LICENSE.txt)） |
| 商用 | 允许，保留版权声明即可 |

### 2.3 ncnn（BSD-3-Clause）

两个引擎的推理框架，[Tencent/ncnn](https://github.com/Tencent/ncnn)，BSD-3-Clause。它已被静态编译进上述两个 exe，因此这两个二进制里同时含有 ncnn 的代码。

### 2.4 Vulkan 与 vcomp140.dll

- **Vulkan**：没有随包分发任何 Vulkan 运行时，运行时用的是**显卡驱动自带**的 `vulkan-1.dll`。所以 AI 增强要求安装了较新的显卡驱动。
- **vcomp140.dll**：Microsoft Visual C++ 运行库（OpenMP），随引擎二进制附带。分发它适用 Visual Studio 的可再发行组件许可，允许随应用程序一起分发。

---

## 3. PDF 处理库（pypdfium2 / PDFium / pypdf / Pillow）

PDF 工作台用的是**链接进主程序**的库（不像 FFmpeg 那样子进程调用），所以许可证选择和本项目是否兼容就是硬要求。

| 组件 | 版本 | 许可证 | 用途 |
|---|---|---|---|
| [pypdfium2](https://github.com/pypdfium2-team/pypdfium2) | 5.15.2 | Apache-2.0 / BSD-3-Clause | PDF 页面搬运、渲染、封装 |
| [PDFium](https://pdfium.googlesource.com/pdfium/) | 随 pypdfium2 分发 | BSD-3-Clause | pypdfium2 底层的 PDF 引擎（Google/Chromium 项目） |
| [pypdf](https://github.com/py-pdf/pypdf) | 7.1.0 | BSD-3-Clause | 改写页面内嵌图片（压缩）、按队列合并 |
| [Pillow](https://python-pillow.org/) | 13.0.0 | MIT-CMU | 图片解码、缩略图合成、JPEG 编码 |

四者都与 MIT 兼容，不需要改变 ZZBox 的授权，也没有源码开放义务。

### 为什么不用 PyMuPDF

PyMuPDF 功能更全，但它是 **AGPL-3.0**。AGPL 的传染性覆盖"通过网络提供服务"的场景，把它静态打进分发包会让整个 ZZBox 被迫以 AGPL 发布 —— 与本项目的 MIT 定位直接冲突。

PDFium 是渲染引擎，只读 —— 它没有任何修改 PDF 对象的 API，所以「只换页面里的图片、不动文字层」这件事它做不了。这一项交给 pypdf：纯 Python 实现，能直接拿到 `/XObject` 流对象并改写，许可证是 BSD-3-Clause。

两条管线各管一段：

  · pypdfium2 —— 渲染缩略图、按队列整页搬运（旋转、合并、拆页），快且稳
  · pypdf —— 压缩时重编码页面内嵌图片，保住文字层和页面尺寸

缺的仍然是 PDF 编辑（改文字、重排段落）和 OCR，这两项本来就不在工具箱的范围内。

### 分发时你需要做什么

Apache-2.0、BSD-3-Clause 都要求保留版权声明与许可证全文。`_internal/` 目录下的库文件自带 `*.dist-info/LICENSE*`，PyInstaller 会一并收集；如果你自行裁剪分发包，注意不要把 `pypdfium2-*.dist-info/` 和 `PIL/` 下的许可证文件删掉。

---

## 4. Qt for Python（PySide6）— LGPLv3

| 项目 | 内容 |
|---|---|
| 版本 | 6.12.0 |
| 许可证 | LGPLv3 / GPLv3 双授权，本项目按 **LGPLv3** 使用 |
| 说明 | 以**动态链接**方式使用（PyInstaller 打包的 Qt DLL 保持独立文件，未静态链接、未修改 Qt 源码），符合 LGPLv3 对动态链接的要求 |

LGPLv3 全文：<https://www.gnu.org/licenses/lgpl-3.0.txt>

使用者有权替换 Qt 库：`_internal/` 目录下的 Qt DLL 是独立文件，替换为自行编译的同版本库即可。

---

## 5. Python 运行时

| 项目 | 内容 |
|---|---|
| 版本 | CPython 3.13 |
| 许可证 | PSF License Agreement |
| 全文 | <https://docs.python.org/3/license.html> |

---

## 6. 编解码器专利（重要提醒）

FFmpeg 的**软件**许可证（GPL）和**编解码器专利**是两件不同的事：

- H.264 / AVC：MPEG LA / Via LA 专利池
- HEVC / H.265：Access Advance、MPEG LA、Via LA 等多个专利池
- AV1：AOMedia 宣称 Royalty-Free，但仍有第三方专利主张的先例

**个人学习、研究、开源分发**通常不会有人找你，但**商业分发**（尤其是预装到硬件、企业内分发、对外售卖）可能需要向专利池取得许可。这一块 GPL 管不到，也不是本项目的授权能覆盖的，需要自行评估。

`--enable-gpl` 带来的 x264 / x265 本身是 GPL，也意味着**不能**把它们的二进制用于闭源商业产品。

---

## 7. 图标

`assets/` 下的图标由本项目作者绘制，随源码以 MIT 授权。
