# 第三方组件与许可证

ZZBox 自身的源码以 [MIT](LICENSE) 授权。下面这些组件是**独立作品**，各自遵循自己的许可证，不因被打包在同一个文件夹里而改变。

---

## 1. FFmpeg（GPLv3）

| 项目 | 内容 |
|---|---|
| 程序 | `ffmpeg.exe`、`ffprobe.exe` |
| 版本 | `9.0.2-essentials_build` |
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
<https://www.gyan.dev/ffmpeg/builds/>（`ffmpeg-9.0.2-essentials_build` 对应的 source 包）

**上游源码**：<https://ffmpeg.org/download.html> · 镜像 <https://git.ffmpeg.org/ffmpeg.git>

### 想彻底避开这些义务

用 **lite 包**：不内附 FFmpeg，由使用者自行准备（放进 `bin\` 或加到 PATH）。此时你分发的只有 MIT 授权的 ZZBox，GPL 义务不适用于你。

---

## 2. Qt for Python（PySide6）— LGPLv3

| 项目 | 内容 |
|---|---|
| 版本 | 6.12.0 |
| 许可证 | LGPLv3 / GPLv3 双授权，本项目按 **LGPLv3** 使用 |
| 说明 | 以**动态链接**方式使用（PyInstaller 打包的 Qt DLL 保持独立文件，未静态链接、未修改 Qt 源码），符合 LGPLv3 对动态链接的要求 |

LGPLv3 全文：<https://www.gnu.org/licenses/lgpl-3.0.txt>

使用者有权替换 Qt 库：`_internal/` 目录下的 Qt DLL 是独立文件，替换为自行编译的同版本库即可。

---

## 3. Python 运行时

| 项目 | 内容 |
|---|---|
| 版本 | CPython 3.13 |
| 许可证 | PSF License Agreement |
| 全文 | <https://docs.python.org/3/license.html> |

---

## 4. 编解码器专利（重要提醒）

FFmpeg 的**软件**许可证（GPL）和**编解码器专利**是两件不同的事：

- H.264 / AVC：MPEG LA / Via LA 专利池
- HEVC / H.265：Access Advance、MPEG LA、Via LA 等多个专利池
- AV1：AOMedia 宣称 Royalty-Free，但仍有第三方专利主张的先例

**个人学习、研究、开源分发**通常不会有人找你，但**商业分发**（尤其是预装到硬件、企业内分发、对外售卖）可能需要向专利池取得许可。这一块 GPL 管不到，也不是本项目的授权能覆盖的，需要自行评估。

`--enable-gpl` 带来的 x264 / x265 本身是 GPL，也意味着**不能**把它们的二进制用于闭源商业产品。

---

## 5. 图标

`assets/` 下的图标由本项目作者绘制，随源码以 MIT 授权。
