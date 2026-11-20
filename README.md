<a id="zh"></a>

<sub><b>简体中文</b> · <a href="#english">English</a></sub>

<div align="center">

![ZZBox](docs/images/icon.png)

# 舟舟工具箱 · ZZBox

**视频转码 · 图片处理 · PDF 整理，三个工作台，一套本地引擎**

把文件拖进来，点一下。视频交给显卡压小、抽音轨、超分补帧；图片批量改格式、压体积、放大两到四倍；  
PDF 一格一页地重排、合并、拆页，压缩只换图片不动文字。

![Release](https://img.shields.io/badge/release-v0.7.0-2f6fed)

![Platform](https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-0078d4)

![Python](https://img.shields.io/badge/python-3.13-3776ab)

![License](https://img.shields.io/badge/license-MIT-3da639)

</div>
<img width="1120" height="760" alt="image" src="https://github.com/user-attachments/assets/ce431757-d54d-48d0-8542-361494a5d123" />


|          视频处理         |        图片处理       |    PDF 处理    |
| :-------------------: | :---------------: | :----------: |
|          视频处理         |        图片处理       |    PDF 处理    |
| 队列在上、参数在下，改一个参数整列当场重算 | 同一套布局，图片按张统计体积与耗时 | 一格一页，拖动排序后导出 |

---

## 这是什么

一个纯本地运行的 Windows 桌面工具。顶部三个工作台 —— **视频处理**、**图片处理**、**PDF 处理** ——各自一份队列、一套参数，互不干扰。

- **不联网**。
- **不需要装 Python / FFmpeg**。下载解压，双击 `ZZBox.exe`
- **关掉窗口不等于退出**。程序缩到托盘继续跑，做完弹一条通知

适合这些活：素材瘦身、4K 素材转 1080p 交付、批量压访谈和课程视频、把视频里的音轨单独抽出来；  
相册几十张照片压缩、老照片和截图放大两倍再打印；  
一堆扫描件和截图拼成一份 PDF、从大手册里挑几章单独导出、把扫歪的页面转正。

---

## 下载

到 [Releases](../../releases) 页面下载。自己出包就跑 `python tools/make_zips.py`。

解压后双击 `ZZBox.exe`。整个文件夹可以拷到 U 盘或别的电脑直接用，不写注册表。

---

## 快速开始

1. 解压后双击 `ZZBox.exe`
2. 顶部选 **视频处理** / **图片处理** / **PDF 处理**
3. 把文件拖进窗口，或点队列右上角的 `+`
4. 在下方参数区调好设置，点右下角的「开始压制」「开始压缩」「导出」之类，进度条显示百分比、加速倍率和剩余时间；做完状态圆点变绿，托盘弹通知。

逐项操作的手册见随包附带的 [README.txt](README.txt)。

---

## 导出保存

点「开始压制 / 开始压缩 / 导出」时会弹出统一的保存对话框：

- **保存位置** —— 在上方输入或点「浏览…」选输出文件夹，确认后写回「输出到」
- **文件名** —— 单文件导出（单个视频、合并出的 PDF、单张图）用它命名；批量导出时忽略，命名规则照旧
- **保存类型** —— 按工作台变：视频是 MP4 / MKV / MOV；图片是 PNG / JPG / WebP /PDF（全部合成一个）；PDF 是 合并为 1 个 / 按来源分别导出 / 每页一张 PNG / 每页一张 JPG
- **保存至子文件夹** —— 勾上后在所选目录下新建 `ZZbox output.年.月.日.时.分` 文件夹再输出，不勾就直接输出到所选目录；已经站在输出子文件夹里时不再嵌套

PDF 的导出按钮不再弹「合并为 1 个 / 按来源 / PNG / JPG」选项菜单，格式一律在保存类型里选。

队列通用操作：三个队列都支持选中后按 **Delete** 键删除；鼠标悬停时**整行**底色变化（含操作格整格）；拖动排序时落点处亮一条蓝色提示线，贯穿整行（最右边的操作格下面也不断开）。

---

## 视频处理

### 硬件编码

解码走 CPU，编码交给显卡（NVENC）。三档编码器的体积差异大致如下：

| 编码器   | 同画质下的体积  | 显卡要求        |
| ----- | -------- | ----------- |
| H.264 | 100%（基准） | GTX 10 系及以上 |
| HEVC  | 约 88%    | GTX 10 系及以上 |
| AV1   | 约 75%    | RTX 40 系及以上 |

全 GPU 管线（硬解 + 显存内缩放）还没做，解码这一半仍占 CPU。

### 队列：先告诉你多大，再开始压

队列表格六列，改任何参数都会当场重算：

| 文件名         | 原始格式                      | 导出格式                     | 原始大小   | 预计导出大小 | 操作    |
| ----------- | ------------------------- | ------------------------ | ------ | ------ | ----- |
| 项目汇报_终版.mp4 | 1920×1080 · 25fps · 03:29 | 1280×720 · 25fps · 03:29 | 265 MB | 143 MB | ● 已压制 |

「预计导出大小」不是拍脑袋：按 CRF 与分辨率反推码率，系数用实拍素材标定过，六组设置回测误差都在 1% 内。同类素材实拍会有 ±25% 浮动，码率模式下最准。

### 音轨工具（批量）

- **抽取音频** — 导出 `.m4a`
- **删除音轨** — `-map 0:v:0 -c:v copy -an`，视频流原样拷贝，**一帧都不重编**，几秒钟出结果

两个都是批量的：选中几行就处理几行，没选就整队。

### AI 增强：超分 · 补帧

页签切到「AI 增强」。它和「视频压缩」是两套独立参数，但共用同一个文件队列 ——一个片子可以先超分，再拿去压。

- **超分** — 关闭 / 2× / 3× / 4×。**输出尺寸只有一个来源：源尺寸 × 倍率。**  
  没有并排的「输出分辨率」下拉，那种双旋钮看着像两个功能，实际会互相吃掉（选 2× 配 1080p 上限得到 1.5×，配 4K 上限又完全没用），用户没法预测结果。  
  720p 选 2× 就是 1440p，选 4× 就是 2880p
  - **真人实拍**（`realesrgan-x4plus`，默认）— RRDB 深度网络，约 1670 万参数，能重建皮肤纹理、发丝分层、镜架金属感。固定 4× 推理，再 lanczos 降到你要的尺寸。
  - **慢：720p 素材约 6 秒/帧（RTX 4060）**
  - **动画番剧**（`realesr-animevideov3`）— SRVGGNet 轻量架构，只有 1.4 MB / 约 60 万参数，快 5 倍。它的训练集全是动画帧，**拿去处理真人会把皮肤抹成色块、眼睛描成卡通线条**
- **补帧** — 2× / 4×，RIFE 光流插帧，只改帧率不改时长，音轨原样保留
- **降噪** — 关闭 / 轻度 / 较强。低码率视频的退化是「压缩块 + 振铃」，直接超分等于把这些伪影一起放大 4 倍；先轻度去噪再超分，细节更干净而不是更少
- **锐化** — 关闭 / 轻度 / 较强，默认轻度。4× 重建后降到目标尺寸，边缘会软一档，补一点 unsharp 拉回来；放到「较强」会开始出白边
- **推荐档位** — 鼠标停在倍率按钮上，按当前素材和显卡算出「这一档得到多大、推理面积多少 MP、显存够不够」，推荐的那一档标 ★。判据是「把高度补到 1440p 附近」，1080p 源在 8G 卡上会直接建议不放大（那是 33 MP 推理）
- **显存自适应** — 按显存决定分块大小。倍率降不下来时（x4plus 只有 4×）靠缩小 tile 兜住显存，而不是硬跑一个 OOM
- **临时空间警示** — 面板底部一行黄色提醒写清「这次会在哪个盘产生多少 GB、该盘还剩多少、为什么别把输出放系统盘」。超分要落盘一堆中间帧，1 分钟 720p 的 2× 就要约 39 GB

面板排布是两行三列、标签竖向对齐：**超分 · 补帧 · 模型**一行，**编码 · 降噪 · 锐化**一行。  
底部提示固定两行（灰色 = 规格与推荐，黄色 = 警示），多条提示并进同一行；文字再多也不换行，放不下就横向滚动 —— 提示文字永远不改变面板高度，队列不会被挤扁。

#### 推理倍率和输出倍率是两件事

这是最容易误解的地方。`realesrgan-x4plus` 只有 4× 一档，但选 2× 时**不会**得到一个 4× 的片子：

```
你选 2×  →  引擎按 4× 推理到 2880p  →  lanczos 降到 1440p  →  输出 1440p
```

多出来的一步不是浪费，是**超采样**：先在 4 倍尺度上重建细节，再缩回去，锐度明显好于任何原生2× 模型。这也是它值得慢 5 倍的原因。

另一处顺序上的讲究：补帧放在降采样**之后**。先在 2880p 上插帧再缩，RIFE 要多算 4 倍像素，插出来的中间帧还得跟着缩一次 —— 白花时间，边缘反而更糊。

| 显存     | 720p 素材能做什么        | 体验            |
| ------ | ------------------ | ------------- |
| 6 GB   | 2× (1440p)、3× (4K) | 能用，4× 会切小分块变慢 |
| 8 GB   | 2× / 3× / 4× 都可以   | 甜点区           |
| 12 GB+ | 1080p → 4K         | 舒服            |

引擎是 **Vulkan 后端**的 ncnn 版本：不需要装 CUDA、不需要 Python、不需要配环境变量，解压即用。  
代价是没用 TensorRT，速度不是极限。

> **速度要有心理准备**：实拍模型在 RTX 4060 上约 6 秒/帧，1 分钟 720p（24fps）要 2.5~3 小时。  
> 界面上的「预计耗时」按这张卡的实测基准估算，别的卡会差不少。只补帧不超分很快  
> （1 分钟素材约 1 分钟），嫌慢可以先只补帧。

> **效果预期（说实话版）**：720p → 1440p 用实拍模型，皮肤纹理和发丝是能真的回来的；  
> 720p → 4K 的细节仍有相当一部分是模型「猜」的，人脸、文字、细纹理最容易翻车。  
> 动画和 AI 生成素材可以直接冲 4K，真人实拍建议停在 1440p。

#### 色彩这条路是怎么走的

中间产物是 PNG 序列，而 PNG 不带色彩标签，所以两端的转换必须在命令行里写死，不能交给 ffmpeg 自动协商：

```
源(yuv420p) --拆帧-- RGB PNG --超分/补帧-- RGB PNG --合成-- 输出(yuv420p)
             bt709/tv 转换                           bt709/tv 转回
```

拆帧时用 `scale=in_color_matrix=…:in_range=…` 固定 YUV→RGB 的系数，合成时用`scale=out_color_matrix=…:out_range=…` 按同一套转回来，并把 `-colorspace` / `-color_primaries` /`-color_trc` 写进码流。**两次矩阵不一致，肤色就会整体跑偏**；源文件没写色彩标签时按分辨率推断（≥720p 用 bt709，SD 用 bt601）。

另一半是像素格式：合成时必须显式 `-pix_fmt yuv420p`。PNG 是 RGB，而 NVENC 支持 HEVC Rext 的`gbrp`，ffmpeg 会自动协商成「RGB 直编」—— 产出的文件尺寸、帧率、时长全对，但绝大多数播放器把 G/B/R 三个平面当成 Y/U/V 解释，画面就成了**整体绿配品红**（白色变粉紫、暗部变绿）。  
这是个光看元数据发现不了的坑，所以 `tools/check_color.py` 把像素格式和逐帧 RGB 均值都纳入了检查。

---

## 图片处理

### 批量压缩

队列和视频那边长得一样（文件名 / 原始格式 / 导出格式 / 原始大小 / 预计导出大小 / 操作），  
参数面板也是同一套布局。四个参数：

| 参数  | 选项                      | 说明                          |
| --- | ----------------------- | --------------------------- |
| 格式  | 保持原样 / JPG / PNG / WebP | 保持原样 = 每张图按自己的格式走，只改质量和尺寸   |
| 质量  | 40–100 滑块，默认 82         | JPG 与 WebP 有效；PNG 无损，这个值不参与 |
| 长边  | 不改变 / 1920 / 1280 / 自定义 | 只缩不放，等比缩放，输出边长对齐到偶数         |
| 元数据 | 保留 / 清除                 | 清除会去掉 EXIF、拍摄时间、GPS 和相机型号   |

- **透明通道自动处理**：源图带 alpha 时，PNG 和 WebP 保留透明；转 JPG 时先把透明区摊到白底上，不会拿到一张黑底图
- **手机竖拍照片按你看到的方向转**：EXIF 里记着「转 90°」的照片，输出是正的，不是躺倒的
- 一张图 0.1 秒左右，几百张也就几分钟

### AI 超分

同一个 `realesrgan-ncnn-vulkan` 引擎，同一套模型体系（真人实拍 / 动画番剧）。区别是图片本来就单帧，引擎直接吃文件 —— 不用拆帧、不占临时空间、没有中间帧序列。

- 倍率 2× / 3× / 4×，格式跟随源或指定 JPG / PNG / WebP
- 和视频页共用降噪、锐化两档开关，语义完全一样；布局也和视频页一致：倍率 · 模型 · 格式一行，降噪 · 锐化一行，底部提示同样固定两行
- **推理倍率和输出倍率同样是两件事**：实拍模型只有 4× 一档，选 2× 时它按 4× 推理再降到 2× 尺寸
- RTX 4060 上 1280×720 的图约 8 秒一张，1080p 约 18 秒

> 图片走的是「引擎出 PNG → ffmpeg 缩放/锐化/编码」两步。中间刻意用 PNG：引擎也支持直接出 JPG，  
> 但那一步会把刚重建出来的细节再压掉一次，后面降采样时就看不出超分带回了什么。

---

## PDF 处理

### 一格一页

PDF 工作台的队列换了形态：**一格是一页，不是一个文件**。一份 80 页的扫描件拖进来就是 80 格，一张图片也是一格。所以「合并」「拆页」「挑几页单独导出」在这里是同一个动作 —— 对着页面把顺序排好，导出。

| 想干的事         | 怎么做                                         |
| ------------ | ------------------------------------------- |
| 几十张图合成一个 PDF | 全拖进来，拖好顺序，点「导出」，保存类型选「合并为 1 个」              |
| 多个 PDF 拼成一份  | 同上，PDF 和图片可以混在一个队列里                         |
| 拆成单页         | 右键「导出选中 → 导出为多个 PDF（每页一个）」，或保存类型选 PNG / JPG |
| 从大文件里挑几章     | 只选那几格，「导出选中 → 1 个 PDF」                      |
| 按来源分开导出      | 点「导出」，保存类型选「按来源分别导出」，同一份源文件的页面归到一起          |
| 扫歪的页面转正      | 选中后点「旋转选中」，再点继续叠加 90°                       |

### 导出：文件名跟着原文件走

单页导出（每页一个文件）的命名规则：

| 来源                 | 导出的单页文件                              |
| ------------------ | ------------------------------------ |
| `年度报告.pdf` 的第 3 页  | `年度报告·3.pdf` / `年度报告·3.png`          |
| `票据扫描.jpg`（本来就是一页） | `票据扫描.png` —— 图片不带页号                 |
| 同一页又导一次            | `年度报告·3(2).png` —— 重名自动挂序号，不覆盖上一次的成果 |

页号取的是这页在**原始文件**里的位置，不是队列里的位置。拆出去再拼回来时，看名字就知道它原来在第几页。

底部「导出」走保存对话框：文件直接落在你选的文件夹（勾「保存至子文件夹」则进`ZZbox output.年.月.日.时.分`），保存类型选 PNG/JPG 时每页一张散在该文件夹里。  
右键「导出选中」导出图片时仍进 `源名_png_时间` 子目录，免得和原文件混在一起。

> **导出选中和合并不会重新渲染。** 走的是 PDF 页面对象级搬运，文字层、矢量、链接、表单、书签全都留着  
> —— 导出的 PDF 照样能搜索、能复制。JPEG 图片也是原样嵌进去（`DCTDecode`），一个像素都不重算。

### 操作全在格子墙的右键菜单里

面板上不再放「旋转选中 / 导出选中 / 删除选中 / 压缩」按钮，全部收进**队列右键菜单**：

| 菜单项            | 作用                          |
| -------------- | --------------------------- |
| 旋转选中 90°       | 只动选中页，可以叠加                  |
| 导出选中…          | 合并 / 逐页导出 PDF，或导出 PNG / JPG |
| 压缩选中…          | 先进入调参状态，不立刻动手               |
| 删除选中           | 只动队列，**源文件一个字节都不碰**         |
| 全选 / 撤销 Ctrl+Z | 每一步操作都能回退                   |

格子墙操作：多选（单击、Shift 连选、Ctrl 加选）、拖动排序、Ctrl + 滚轮缩放（92–268 px）。每格文件名下面会显示大小：PDF 页显示「pdf文件」，图片显示「371 KB」；压缩预览时会变成「371kb→101kb」这样的实时对照。

### 压缩：只换图片，不动页面

这项压缩和「把整页拍平成图片」是两件完全不同的事：

|              | 重渲染（旧做法） | 本版做法                      |
| ------------ | -------- | ------------------------- |
| 页面尺寸         | 会变       | **不变**                    |
| 文字层          | 变成图片，不能搜 | **原样保留，照样能搜能复制**          |
| 图片           | 整页重画     | 只把页面里的图片重新编码一遍            |
| 图片像素宽高       | 会缩       | 跟随「图片处理 → 图片压缩」的长边设置，默认不变 |
| 链接 / 书签 / 表单 | 全丢       | 保留                        |

点右键菜单的「压缩选中…」之后，下方才出现质量条（30–100，默认 78）和「确认压缩 / 取消」。拖动质量条时，队列里选中格子的数字实时变化；点「确认压缩」才真正开压，完成后静默把压缩件换进队列，压缩条自动收起。图片直接走**图片工作台那一整套方案**（格式、质量、长边、元数据），PDF 页只重编码内嵌图片、文字层不动。

压缩结果以临时文件形式放在 ZZBox 软件目录里，不覆盖原始文件；导出时直接用这些临时件，退出软件（托盘右键「退出」）时整目录自动删除。按 Ctrl+Z 可以把队列换回压缩前的样子（原文件一直都在）。

**压缩过的页面右上角会挂一个绿色「已压缩」小标**，压不动的页面挂**黄色「不可压缩」小标**，一眼能看出哪几页压过、哪几页白点。已压缩的页面还能**再压一次**：右键「压缩选中…」调更低的质量，第二轮从上一轮的压缩件继续压（不是在原始文件上重来），所以能一层层往下减。每轮缓存按「时间_轮次」分开存（`181231_r01`、`181231_r02`…），同一秒连压两次也不会互相覆盖；Ctrl+Z 逐轮回退——撤一轮回到上一轮压缩件，再撤一轮回到原始文件，绿标跟着增减。

图片预估和确认压缩走**同一条 ffmpeg 命令**，预估多少、压出来就是多少，不会出现「预估 66kb、压完 102kb」这种对不上的数。PDF 页先真解码算一次、之后拖质量条按曲线推算；文件多的时候估算在后台跑，界面不卡，数字一格一格跳出来。拖质量条时只查缓存做比例缩放，松手后后台再算精确值 —— 几十张图的队列也不会卡。大尺寸扫描页的真解码可能要几秒，但不会卡住界面。压不动的页会直接写明原因，不会一直挂在「估算中…」；点确认时这些页会被跳过，保持原样。估算出错也会明确显示「估算失败」。

**重编码反而更大的项保持原样。** PNG 无损重编码、JPG 转 PNG 这类情况，压完比原图还大 ——预估阶段就会用警示色标出来、提示「N 项预计比原图大」；确认后这些项**不会**被更大的「压缩件」替换，保持原文件，挂黄色「不可压缩」标，格子上写「已保持原样 · 重编码反而更大」。想要更小的体积，把图片方案的输出格式改成 JPG 或 WebP 即可。

**PNG 输出时质量不生效。** PNG 是无损格式，质量参数对它没有意义。全部选中项都是 PNG 输出时，质量条会自动禁用，提示里写明「PNG 无损输出，质量不生效」—— 数字纹丝不动不是卡死，是无损格式本来就不受质量影响。

**为什么有的页"明明有图却压不动"？** 排版软件画的柱状图、曲线、渐变条是**矢量图形**（几万条路径操作画出来的），不是位图 —— 看着五颜六色，但没有"图片质量"可降，重编码引擎对它们无能为力，这类页会写「本页无位图（矢量/文字）」。还有一种是图片本来就只有几百字节（小 logo、色块），再压只会更大，会写「N 张图片已极小」。两种都会挂黄标。

### 哪些图会被跳过

宁可少压，也不压坏：

- 蒙版图（`/ImageMask`）、带**非恒等** `/Decode` 映射的 —— 重编码会变色（`/Decode [0 255]` 是默认值，InDesign 爱显式写出来，这种照常压）
- JPEG2000、Separation 等解不开的色彩空间 —— 交给系统查看器原样显示
- `/Indexed` 调色板图会展开调色板再重编码，压不动再退回
- 已经很小的图 —— 再压只会更糊还更大，会标注「已极小」

**印刷设计稿放心压。** 以前带透明蒙版（`/SMask`）的图、CMYK 图会被整张跳过，结果海报、画册这类 PDF 明明满页位图却提示「不可压缩」——那是保守过头了。现在：

- **带 `/SMask` 的图照常压**：只重编码颜色通道，蒙版对象原样保留，透明度一点不变
- **CMYK 图照常压**：用 CMYK JPEG 重编码，按数据来源正确设置反相参数。实测和原图渲染的同向色差 < 0.02/255，肉眼不可见；单页实测 378 KB → 168 KB

这也是「PDF 里的图片跟随图片处理方案」在印刷稿上的体现。

---

## 三个工作台怎么切

顶部的「视频处理 / 图片处理 / PDF 处理」就是分界。三边的队列、参数、状态**完全独立**：

- 拖视频进来 → 进视频队列；拖图片进来 → 进图片队列；拖 PDF 进来 → 自动切到 PDF 工作台
- 站在 PDF 工作台时，拖进去的东西一律进 PDF 队列（连图片也是）—— 你已经在这个页面上了，再把图片塞进图片工作台等于让你自己再找一遍
- 「输出到」三个工作台共用，切过去不用重填
- 进度条、取消、开始按钮共用一套 —— 前三者都吃 GPU，同一时刻只跑一件，串行更稳
- 视频页签里的操作（抽取音频 / 删除音轨）只在视频工作台出现

## 中英切换

模式条（「视频处理 / 图片处理 / PDF 处理」那一行）的**最右侧**有一个语言按钮：

- 中文界面下它写着 `Switch to English`，点一下整套界面切成英文
- 英文界面下它写着 `切换至中文`，点一下切回中文

切换是整套的，不用重启：按钮、页签、表头、参数名、提示语、右键菜单、导出对话框、弹窗、托盘菜单与托盘悬停文字都会跟着变。选择会记在 `ui.json`（优先程序目录，不可写时退到 `%LOCALAPPDATA%\ZZBox\ui.json`），下次打开沿用上次的语言。


不翻译的是文件路径、文件名、文件里的文字内容，以及 `MB` / `KB` / `px` 这类单位。

## 操作手感

- 表头拖列宽，和文件资源管理器一致（拖谁就动谁，右边的列整体平移）
- 单击选中、Shift 连选、Ctrl 加选，还能在下方空白处拉框框选
- 按住行上下拖可以调整压制顺序
- 处理完的绿点会写明是「已完成压制」「已抽取音频」还是「已删除音轨」

---

## 系统要求

- Windows 10 / 11 64 位
- **PDF 处理和图片压缩不需要显卡**，纯 CPU，什么机器都能跑
- 视频硬编码要 NVIDIA 显卡（GTX 10 系及以上；AV1 编码需要 RTX 40 系）+ 较新驱动
- AI 增强额外要求：显卡支持 Vulkan（RTX 20 系及以上都行），显存 6 GB 起；临时帧序列要占几 GB 到几十 GB 磁盘

---

## 常见问题

**双击 `启动.bat` 提示找不到 ZZBox.exe？**  
先确认 `ZZBox.exe` 和 `启动.bat` 在同一个文件夹里。这个脚本先在当前目录找，找不到才去翻`ZZBox vX.Y.Z` 这样的子文件夹（老版本包的布局）。实在不行直接双击 `ZZBox.exe`。

**PDF 压缩后体积几乎没变？**  
说明这一份没什么可压的：纯文字页没有图片，页面上图片本来就只有几十 KB，或者图片全被跳过规则挡住了。压缩只对**页面里的图片**生效，不会重画页面。

**PDF 能转成 Word 吗？**  
不能，也不打算做。真正「可编辑且版式还原」需要版式重建 + 字体映射，是另一个量级的产品；能走通的降级路线（整页图片、文字重排）导出来都不能用。本项目的 PDF 能力集中在页面级的整理与搬运。

**为什么单页文件名带 `·3`？**  
3 是这页在**原始文件**里的页号。队列里怎么排序都不影响它，方便拆完再按名字拼回去。

**超分为什么这么慢？**  
实拍模型约 6 秒/帧（RTX 4060），1 分钟 720p 要 2.5~3 小时。这是模型量和 Vulkan 后端共同决定的，不是配置问题。只补帧不超分快得多。

**处理到一半能暂停吗？**  
不能，只能取消整个队列。队列本身是串行的 —— GPU 并发跑多个任务反而更慢。

**关掉窗口还在跑？**  
对，程序缩到托盘继续工作，做完弹通知。要真退出，右键托盘图标选退出。

---

## 从源码运行

```bash
git clone https://github.com/<你的用户名>/ZZBox.git
cd ZZBox
pip install -r requirements.txt

# 把 ffmpeg.exe / ffprobe.exe 放进 bin\ 目录（或确保它们在 PATH 里）
# AI 增强还需要 bin\ai\ 下的两个引擎，见下方「AI 引擎怎么装」
python main.py
```

FFmpeg 建议用 [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) 的 essentials 版，或  
[BtbN](https://github.com/BtbN/FFmpeg-Builds/releases) 的 win64-gpl 版。

### AI 引擎怎么装

两个引擎都是免安装的压缩包，解开后按下面的结构摆放即可（`bin\` 已被 `.gitignore` 排除，所以仓库里没有，需要自己下）：

```
bin/ai/
├── esrgan/
│   ├── realesrgan-ncnn-vulkan.exe
│   ├── vcomp140.dll
│   └── models/                     ← realesr-animevideov3-x2/x3/x4、realesrgan-x4plus
└── rife/
    ├── rife-ncnn-vulkan.exe
    ├── vcomp140.dll
    └── rife-v4.6/                  ← 模型目录，直接放 exe 旁边
```

下载地址：

- 超分：[Real-ESRGAN releases](https://github.com/xinntao/Real-ESRGAN/releases) →  
  `realesrgan-ncnn-vulkan-*-windows.zip`
- 补帧：[rife-ncnn-vulkan releases](https://github.com/nihui/rife-ncnn-vulkan/releases) →  
  `rife-ncnn-vulkan-*-windows.zip`

放好之后打开程序，切到「AI 增强」页，「引擎与开销」卡片会显示「超分 就绪 · N 个模型」「补帧 就绪」。  
缺了不影响普通压制，点开始时会弹窗告诉你缺哪个。

想确认装对了，跑一条命令就够：

```bash
python tools/test_ai_pipeline.py
```

它会自己造一段 3 秒测试片，走完整个管线，最后打印成片的尺寸 / 帧率 / **颜色偏差**。颜色是单独一项硬检查：输出像素格式必须是 YUV 系，逐帧 RGB 均值差不得超过 16 级 —— 尺寸帧率都对但画面绿成一片的那种毛病，只有这项能拦住。

想单独验某个片子的颜色：

```bash
python tools/check_color.py 源.mp4 输出.mp4
```

---

## 自己打包

```bash
python build.py
```

产物落在仓库上一级的 `zz box 0.7.0\`，里面是完整可运行目录（PyInstaller onedir 模式，比 onefile启动快得多），`bin\` 下的 FFmpeg 与 AI 引擎会一并带上。想换位置就传一个路径：  
`python build.py "D:\some\where\ZZBox"`。

打完必须验一遍：

```bash
"zz box 0.7.0\ZZBox.exe" --selftest --quiet
```

结果写在同目录的 `logs\selftest.txt`，最后一行是 `RESULT = PASS`。它会真跑一段转码、一次图片压缩、一次图片超分，还有 PDF 合成与 PDF 图片压缩 —— 后者专门用来验证 `pypdf` 和 `pdfium.dll` 有没有被PyInstaller 漏收。

---

## 目录结构

交付时是两个并列文件夹：

```
gpu-video-encoder/
├── zz box 0.7.0/        成品：ZZBox.exe + _internal/ + bin/（FFmpeg 与 AI 引擎）+ licenses/
└── zz box code/         纯源码，不含 bin/ 与构建产物
```

源码内部：

```
ZZBox/
├── main.py                 程序入口，含 --selftest 自检（视频 + 图片 + PDF 各跑一遍）
├── build.py                PyInstaller 打包脚本
├── app/
│   ├── core/
│   │   ├── probe.py        找 FFmpeg、读显卡、真跑一次编码验证可用性
│   │   ├── media.py        ffprobe 解析、格式化（分辨率·帧率·时长、体积）
│   │   ├── encoder.py      命令行构造、体积估算、缩放计算
│   │   ├── runner.py       单进程执行、ffmpeg 进度解析、取消
│   │   ├── ai.py           AI 增强：引擎探测、显存档位、四段管线编排
│   │   ├── ai_runner.py    多阶段执行器（数帧数 + ffmpeg 进度，加权汇总）
│   │   ├── image.py        图片：探测、格式/质量/缩放、超分命令、体积估算
│   │   ├── image_runner.py 图片执行器（1~2 步命令链，解析引擎百分比）
│   │   ├── pdf.py          PDF：页面探测、渲染、无损组装（pdfium）、单页命名
│   │   ├── pdf_images.py   PDF 图片压缩：重编码页面内嵌图、保留文字层（pypdf）
│   │   └── pdf_runner.py   PDF 执行器（线程 + 协作式取消，无子进程可管）
│   └── ui/
│       ├── main_window.py  主窗口、三个工作台、参数页、任务调度
│       ├── widgets.py      队列表格、集成化参数面板、属性页页签
│       ├── page_grid.py    PDF 页面格墙（多选 / 拖动排序 / Ctrl+滚轮缩放 / 尺寸行）
│       ├── tray.py         托盘与后台驻留
│       ├── style.py        深色主题 QSS
│       └── icons.py        多尺寸图标加载
├── assets/                 图标（SVG / 多尺寸 PNG / ICO）、版本资源
├── bin/                    ffmpeg.exe / ffprobe.exe（不入库）
│   └── ai/                 两个 ncnn 引擎，各自带 models
├── docs/                   设计文档与截图
└── tools/
    ├── make_icon.py        从 SVG 生成全部尺寸图标与 ICO
    ├── make_zips.py        打 full / lite 两个发布包
    ├── shot_ui.py          给各属性页各截一张图
    ├── test_ai_pipeline.py AI 管线端到端回归测试
    ├── test_pdf_core.py    PDF 核心逻辑回归（文字层、旋转、无损组装、单页命名）
    ├── test_pdf_images.py  图片压缩回归（文字层 / 页面尺寸 / 图片像素全不变）
    ├── test_pdf_ui.py      PDF 工作台离屏实跑 + 截图 + 导出命名验证
    ├── test_pdf_zip_ui.py  压缩区四态实跑（启用 → 全/部分 → 暂存 → 导出）
    └── test_page_grid_drag.py  格墙拖动排序（纯鼠标事件）
```

---

## 已知限制

- 解码用 CPU、编码用 GPU，没有做硬解和显存内缩放
- HDR / 10bit 素材会被转成 8bit，颜色可能偏差
- 队列串行，同时只处理一个文件
- 没有暂停，只能取消整个队列
- 只做了 NVIDIA 路径（NVENC），AMD / Intel 的硬编码没有适配
- AI 增强逐帧处理且中间产物必须落盘（引擎只吃图片目录）：1 分钟 720p 超分 2× 峰值约25~40 GB 临时空间（按 4× 推理尺寸算，比输出大 4 倍），1080p 源更高
- 补帧只能整数倍（2×/4×），24fps → 60fps 这种非整数倍不支持
- 输出尺寸严格等于「源 × 倍率」，不额外改小，也不弹「超过 4K」提示
- AI 增强的输出固定为 8bit `yuv420p`，HDR 素材的色彩无法保留；普通压制按源的位深走
- 图片不支持动图：GIF 会被静默压成第一帧，所以干脆不在支持列表里
- 图片超分没有做分块尺寸自适应，8000 万像素以上的输出可能撞显存上限
- 图片队列与视频队列各自独立，不能混排成一条流水线
- PDF 压缩只作用于**图片**：纯文字页压了等于没压
- PDF 里的图片像素尺寸跟随「图片压缩」的长边设置；默认不改尺寸，只重新编码
- PDF 不支持带打开密码的文件，也不做加密导出
- PDF 不做 OCR、不做文字编辑、不转 Word —— 那是另一个量级的产品
- PDF 队列里同一页可以导入两次（拼版时有这个需求），代价是缩略图各渲染一遍
- PDF 导出不保留书签目录：页面被重排后原页码已经对不上，硬搬反而指错地方

---

## 关于 FFmpeg 与开源协议

**本项目自己的代码是 [MIT](LICENSE)。** 内置的 FFmpeg 是独立程序，通过命令行调用，两者不构成衍生作品。

内置的是 [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) 的 `ffmpeg 7.1-essentials_build`，编译时带了`--enable-gpl --enable-version3 --enable-libx264 --enable-libx265 --enable-libaom`，因此是 **GPLv3** 授权。  
分发时已随包附上许可证全文与源码获取方式，见 [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)。

PDF 部分刻意没有用 PyMuPDF（AGPL，会把整个项目的授权传染掉），页面搬运靠 `pypdfium2`（Apache-2.0 /BSD-3），图片重编码靠 `pypdf`（BSD-3）与 Pillow（MIT-CMU）。

如果你要二次分发：请一并保留 `licenses/` 目录，并保证能提供对应版本的 FFmpeg 源码（直接给 gyan.dev 的下载链接也算书面 offer）。想彻底免掉这个义务，就让用户自己准备 FFmpeg。

---

## 致谢

- [FFmpeg](https://ffmpeg.org/) — 所有转码能力的底座
- [Qt for Python (PySide6)](https://doc.qt.io/qtforpython/) — 界面
- [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) — Windows 版 FFmpeg 构建
- [PDFium](https://pdfium.googlesource.com/pdfium/) / [pypdfium2](https://github.com/pypdfium2-team/pypdfium2) — PDF 渲染与页面搬运
- [pypdf](https://github.com/py-pdf/pypdf) — PDF 对象流改写
- [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN) — 超分模型与 ncnn 实现
- [RIFE](https://github.com/hzwer/ECCV2022-RIFE) / [rife-ncnn-vulkan](https://github.com/nihui/rife-ncnn-vulkan) — 补帧
- [ncnn](https://github.com/Tencent/ncnn) — 两者的推理框架，Vulkan 后端让工具免装 CUDA

---

## 💬 联系作者
由 舟午YueMoon 开发。
如果你有任何建议、遇到了 BUG，或者单纯想催更，欢迎在B站/Youtube相关视频的评论区告诉我！
博客：http://yuemoon.vip/
GitHub：@YueMoon99
B站：UID223633562
YouTube：@YueMoon99

---
<a id="english"></a>

<sub><a href="#zh">简体中文</a> · <b>English</b></sub>

<div align="center">

![ZZBox](docs/images/icon.png)

# ZZBox

**Video transcoding · Image processing · PDF organizing — three workbenches, one local engine**

Drop files in, click once. Video goes to the GPU to shrink, extract audio, upscale and interpolate;
images get converted, shrunk and upscaled two to four times in batches;
PDF pages get reordered one cell at a time, merged, split — and compression swaps only the images, never the text.

![Release](https://img.shields.io/badge/release-v0.7.0-2f6fed)
![Platform](https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-0078d4)
![Python](https://img.shields.io/badge/python-3.13-3776ab)
![License](https://img.shields.io/badge/license-MIT-3da639)

</div>
<img width="1121" height="791" alt="image" src="https://github.com/user-attachments/assets/c32d1948-3856-425c-b79c-82580a4c6095" />


|        Video        |       Images        |      PDF      |
| :-----------------: | :-----------------: | :-----------: |
|        Video        |       Images        |      PDF      |
| Queue on top, settings below — change one and the whole column recalculates | Same layout; per-image size and time | One cell per page; drag to reorder, then export |

---

## What this is

A fully local Windows desktop tool. Three workbenches across the top — **Video**, **Images**, **PDF** — each with its own queue and its own settings, independent of each other.

- **No network access.**
- **No Python or FFmpeg to install.** Unzip, double-click `ZZBox.exe`
- **Closing the window is not quitting.** It drops into the tray and keeps running; a notification tells you when the job is done

Built for jobs like: slimming down footage, turning 4K material into 1080p deliverables, batch-compressing interviews and course videos, pulling the audio track out of a video;
compressing dozens of photos, upscaling old photos and screenshots 2× before printing;
assembling a pile of scans and screenshots into one PDF, pulling a few chapters out of a big manual, straightening crooked pages.

---

## Download

Get it from the [Releases](../../releases) page. To build the archives yourself, run `python tools/make_zips.py`.

Unzip and double-click `ZZBox.exe`. The whole folder can be copied to a USB stick or another machine — nothing is written to the registry.

---

## Quick start

1. Unzip and double-click `ZZBox.exe`
2. Pick **Video** / **Images** / **PDF** at the top
3. Drag files into the window, or click the `+` at the top right of the queue
4. Adjust the settings in the panel below, then click "Start encoding" / "Start compressing" / "Export" at the bottom right. The progress bar shows percentage, speed multiple and time left; finished rows turn their dot green and the tray pops a notification.

For the item-by-item manual, see the bundled [README.txt](README.txt).

---

## Export & saving

Clicking "Start encoding" / "Start compressing" / "Export" opens one shared save dialog:

- **Save to** — type a path or click "Browse…"; the choice is written back to "Output to"
- **Name** — used when a single file comes out (one video, one merged PDF, one image); ignored for batch export, which keeps its own naming rules
- **Save as** — depends on the workbench: video → MP4 / MKV / MOV; images → PNG / JPG / WebP / PDF (all merged into one); PDF → merge into one / export per source / one PNG per page / one JPG per page
- **Save into subfolder** — when checked, a `ZZbox output.YYYY.MM.DD.HH.MM` folder is created under the chosen directory; unchecked, output goes straight there. If you're already inside the output subfolder it won't nest another one

The PDF export button no longer pops a "merge / per source / PNG / JPG" menu — the format lives in Save as.

Queue-wide: all three queues delete the selection with **Delete**; hovering highlights the **whole row** (the action cell included); while dragging to reorder, a blue insertion line lights up across the entire row (it doesn't break under the action cell on the right).

---

## Video

### Hardware encoding

Decode runs on the CPU, encode goes to the GPU (NVENC). Rough size differences between the three encoders:

| Encoder | Size at equal quality | GPU required    |
| ------- | --------------------- | --------------- |
| H.264   | 100% (baseline)       | GTX 10 series + |
| HEVC    | ~88%                  | GTX 10 series + |
| AV1     | ~75%                  | RTX 40 series + |

A fully GPU pipeline (hardware decode plus scaling in VRAM) isn't done yet; the decode half still burns CPU.

### Queue: the size comes first, the encoding second

The queue table has six columns, and changing any setting recalculates it on the spot:

| File                   | Source                    | Output                    | Size   | Est. output | Actions |
| ---------------------- | ------------------------- | ------------------------- | ------ | ----------- | ------- |
| team_update_final.mp4  | 1920×1080 · 25fps · 03:29 | 1280×720 · 25fps · 03:29  | 265 MB | 143 MB      | ● Encoded |

"Est. output" isn't a wild guess: the bitrate is derived from CRF and resolution with coefficients calibrated on real footage — six settings back-tested within 1% error. Real material of the same kind varies ±25%; bitrate mode is the most accurate.

### Audio tools (batch)

- **Extract audio** — writes `.m4a`
- **Strip audio** — `-map 0:v:0 -c:v copy -an`; the video stream is copied as-is, **not a single frame is re-encoded**, done in seconds

Both are batch operations: select a few rows and those run, select nothing and the whole queue runs.

### AI enhance: upscale · interpolate

Switch the tab to "AI enhance". Its settings are independent of "Compression", but the two share one file queue — a clip can be upscaled first and compressed afterwards.

- **Upscale** — off / 2× / 3× / 4×. **Output size has exactly one source: source size × factor.**
  There is no side-by-side "output resolution" dropdown. Those two knobs look like two features but end up eating each other (2× with a 1080p cap gives you 1.5×; with a 4K cap it does nothing at all), and you can't predict the result.
  720p at 2× is 1440p; at 4× it's 2880p
  - **Live action** (`realesrgan-x4plus`, default) — RRDB deep network, ~16.7M parameters; rebuilds skin texture, layered hair, the metallic look of glasses frames. Always infers at 4×, then Lanczos down to the size you asked for
  - **Slow: about 6 s/frame on 720p material (RTX 4060)**
  - **Animation** (`realesr-animevideov3`) — SRVGGNet, a light architecture at 1.4 MB / ~600K parameters, 5× faster. Its training set is animation frames only — **run it on live action and skin turns into color blobs with cartoon outlines around the eyes**
- **Interpolate** — 2× / 4×, RIFE optical-flow interpolation; frame rate changes, duration doesn't, audio is kept as-is
- **Denoise** — off / light / strong. Low-bitrate video degrades into "compression blocks + ringing", and upscaling straight away magnifies exactly those artifacts 4×. A light denoise first gives cleaner detail rather than less detail
- **Sharpen** — off / light / strong, light by default. After 4× reconstruction and downscaling the edges go a touch soft; a little unsharp pulls them back. "Strong" starts producing white halos
- **Recommended setting** — hover a factor button and it works out, for the current clip and GPU, "how big this factor becomes, how many MP the inference area is, whether VRAM is enough"; the recommended one carries a ★. The rule is "bring the height up to around 1440p", so a 1080p source on an 8 GB card is advised not to upscale at all (that would be 33 MP of inference)
- **VRAM adaptation** — tile size follows VRAM. When the factor can't go lower (x4plus only has 4×), smaller tiles cover the VRAM instead of running headfirst into an OOM
- **Temp space warning** — a yellow line at the bottom of the panel spells out "which drive, how many GB this run will produce, how much is left on it, and why the output shouldn't sit on the system drive". Upscaling writes a lot of intermediate frames: one minute of 720p at 2× takes about 39 GB

The panel is two rows of three with the labels aligned in a column: **Upscale · Interpolate · Model** on one row, **Codec · Denoise · Sharpen** on the next.
The bottom always holds two hint lines (grey = spec and recommendation, yellow = warning), several hints merged into one line; the text never wraps — it scrolls sideways instead. Hints never change the panel height, so the queue never gets squeezed.

#### Inference factor and output factor are two different things

This is the most misunderstood part. `realesrgan-x4plus` only has 4×, but picking 2× does **not** give you a 4× clip:

```
you pick 2×  →  engine infers at 4× up to 2880p  →  lanczos down to 1440p  →  output 1440p
```

That extra step isn't waste, it's **supersampling**: rebuild the detail at 4× scale, then shrink back — visibly sharper than any native 2× model. That's what earns it being 5× slower.

One more ordering detail: interpolation runs **after** the downscale. Interpolating at 2880p first would make RIFE compute 4× the pixels, and the interpolated frames would be shrunk again anyway — time wasted, edges softer.

| VRAM   | What 720p material can do | Experience                          |
| ------ | ------------------------- | ----------------------------------- |
| 6 GB   | 2× (1440p), 3× (4K)       | Usable; 4× shrinks tiles and slows down |
| 8 GB   | 2× / 3× / 4× all fine     | The sweet spot                      |
| 12 GB+ | 1080p → 4K                | Comfortable                         |

The engine is the **Vulkan-backed** ncnn build: no CUDA, no Python, no environment variables — unzip and run.
The trade-off is no TensorRT, so speed isn't what it could be.

> **Set your expectations on speed**: the live-action model runs about 6 s/frame on an RTX 4060 — one minute of 720p at 24 fps takes 2.5–3 hours.
> The "estimated time" in the UI is calibrated on this card; other cards differ a lot. Interpolation without upscaling is fast
> (about a minute per minute of footage), so if it's too slow, interpolate only.

> **What to expect (honest version)**: 720p → 1440p with the live-action model really does bring skin texture and individual strands of hair back;
> at 720p → 4K a good part of the detail is the model *guessing*, and faces, text and fine textures are where it fails.
> Animation and AI-generated material can go straight to 4K; live action is best stopped at 1440p.

#### How color is carried through

The intermediate is a PNG sequence, and PNG carries no color tags, so both conversions have to be pinned on the command line instead of left to ffmpeg's negotiation:

```
source (yuv420p) --split-- RGB PNG --upscale/interpolate-- RGB PNG --merge-- output (yuv420p)
                  bt709/tv convert                              bt709/tv convert back
```

Splitting uses `scale=in_color_matrix=…:in_range=…` to pin the YUV→RGB coefficients; merging uses `scale=out_color_matrix=…:out_range=…` with the same set to convert back, and writes `-colorspace` / `-color_primaries` / `-color_trc` into the bitstream. **If the two matrices disagree, skin tones drift as a whole**; when the source carries no color tags we infer from resolution (≥720p → bt709, SD → bt601).

The other half is pixel format: merging must state `-pix_fmt yuv420p` explicitly. PNG is RGB, and NVENC supports HEVC Rext `gbrp`, so ffmpeg happily negotiates "encode RGB directly" — the file has the right size, frame rate and duration, but most players read the G/B/R planes as Y/U/V and the picture comes out **green with magenta** (whites turn pink-purple, shadows turn green).
Metadata inspection won't catch it, so `tools/check_color.py` checks both the pixel format and per-frame RGB means.

---

## Images

### Batch compression

The queue looks the same as the video one (File / Source / Output / Size / Est. output / Actions), and the parameter panel uses the same layout. Four settings:

| Setting  | Options                     | Notes                                                            |
| -------- | --------------------------- | ---------------------------------------------------------------- |
| Format   | Original / JPG / PNG / WebP | Original = each image keeps its own format; only quality and size change |
| Quality  | 40–100 slider, default 82   | Applies to JPG and WebP; PNG is lossless, the value is not used   |
| Long edge| Keep / 1920 / 1280 / Custom | Shrinks only, never enlarges; proportional; output edges rounded to even |
| Metadata | Keep / Strip                | Strip removes EXIF, capture time, GPS and camera model            |

- **Alpha is handled automatically**: sources with alpha keep transparency in PNG and WebP; when converting to JPG the transparent area is flattened onto white, so you never get a black background
- **Phone photos shot in portrait come out the way you saw them**: photos whose EXIF says "rotate 90°" are output upright, not lying on their side
- About 0.1 s per image — a few hundred images take a couple of minutes

### AI upscale

Same `realesrgan-ncnn-vulkan` engine, same model family (live action / animation). The difference is that an image is already a single frame, so the engine reads the file directly — no frame splitting, no temp space, no intermediate sequence.

- Factor 2× / 3× / 4×; format follows the source or is pinned to JPG / PNG / WebP
- Shares the denoise and sharpen switches with the video tab, same semantics; the layout matches too: factor · model · format on one row, denoise · sharpen on the next, and the same two fixed hint lines at the bottom
- **Inference factor and output factor are two things here as well**: the live-action model only has 4×, so picking 2× means inferring at 4× and downscaling to 2× size
- About 8 s for a 1280×720 image on an RTX 4060, about 18 s for 1080p

> Images go through "engine writes PNG → ffmpeg scales / sharpens / encodes". The PNG in the middle is deliberate: the engine can write JPG directly,
> but that step would compress away the detail just reconstructed, and the downscale afterwards would show nothing of what the upscale brought back.

---

## PDF

### One cell per page

The PDF workbench changes shape: **one cell is one page, not one file**. An 80-page scan dropped in becomes 80 cells, and a single image becomes one cell. That makes "merge", "split" and "export a few pages" the same action here — put the pages in order and export.

| What you want                     | How                                                                 |
| --------------------------------- | ------------------------------------------------------------------- |
| Merge dozens of images into a PDF | Drag them all in, order them, click "Export", pick "Merge into one" in Save as |
| Combine several PDFs into one     | Same; PDFs and images can share one queue                            |
| Split into single pages           | Right-click "Export selected → export as multiple PDFs (one per page)", or pick PNG / JPG in Save as |
| Pull a few chapters out of a file | Select just those cells, "Export selected → 1 PDF"                   |
| Export split by source            | Click "Export", pick "export per source" — pages from the same file end up together |
| Straighten a crooked page         | Select it, click "Rotate selected 90°", click again to add another 90° |

### Export: names follow the source file

Naming rules for single-page export (one file per page):

| Source                                   | Exported single page                                        |
| ---------------------------------------- | ----------------------------------------------------------- |
| Page 3 of `annual-report.pdf`            | `annual-report·3.pdf` / `annual-report·3.png`               |
| `receipt-scan.jpg` (already one page)    | `receipt-scan.png` — images carry no page number            |
| Exporting the same page again            | `annual-report·3(2).png` — duplicates get a suffix, nothing is overwritten |

The page number is the page's position in the **original file**, not in the queue. After splitting and reassembling, the name still tells you which page it was.

"Export" at the bottom goes through the save dialog: files land directly in the folder you picked (or in `ZZbox output.YYYY.MM.DD.HH.MM` when "Save into subfolder" is checked); with PNG/JPG, one file per page is scattered there.
Right-click "Export selected" for images still writes into a `source_png_time` subfolder, so they don't get mixed up with the originals.

> **Export selected and merge never re-render.** Pages are moved as PDF page objects, so the text layer, vectors, links, forms and bookmarks all survive
> — the exported PDF is still searchable and copyable. JPEG images are embedded as-is (`DCTDecode`); not a pixel is recomputed.

### Everything lives in the grid's context menu

The panel no longer carries "rotate / export selected / delete selected / compress" buttons — they all moved into the **queue context menu**:

| Menu item          | What it does                                            |
| ------------------ | ------------------------------------------------------- |
| Rotate selected 90°| Only the selected pages; stacks                         |
| Export selected…   | Merge / per-page PDF, or PNG / JPG                      |
| Compress selected… | Enters the tuning state first; nothing runs yet         |
| Delete selected    | Queue only — **not a byte of the source file is touched** |
| Select all / Undo Ctrl+Z | Every step can be undone                         |

Grid operations: multi-select (click, Shift for a range, Ctrl to add), drag to reorder, Ctrl + wheel to zoom (92–268 px). Under each file name the grid shows a size: PDF pages read "pdf file", images read e.g. "371 KB"; while previewing compression it becomes a live comparison like "371 kb → 101 kb".

### Compression: swap the images, leave the pages alone

This compression is a completely different thing from "flatten the page into an image":

|                        | Re-render (old approach)   | This build                                        |
| ---------------------- | -------------------------- | ------------------------------------------------- |
| Page size              | Changes                    | **Unchanged**                                     |
| Text layer             | Becomes an image, not searchable | **Kept as-is; still searchable and copyable** |
| Images                 | Whole page redrawn         | Only the images inside the page are re-encoded     |
| Image pixel dimensions | Shrinks                    | Follows the long-edge setting under "Images → Compression"; unchanged by default |
| Links / bookmarks / forms | All lost                | Preserved                                         |

After choosing "Compress selected…" in the context menu, the quality slider (30–100, default 78) and "Compress / Cancel" appear below. Dragging the slider updates the numbers on the selected cells live; only "Compress" starts the real work, and when it finishes the compressed version silently replaces the cell and the strip folds away. Images go through **the entire image workbench pipeline** (format, quality, long edge, metadata); PDF pages only get their embedded images re-encoded, the text layer untouched.

Results are written as temp files inside the ZZBox program folder, never over the originals; export uses those temp files, and quitting (tray → Quit) removes the whole folder. Ctrl+Z swaps the queue back to the pre-compression state (the originals were never gone).

**Compressed pages get a green "Compressed" badge** in the top-right corner, and pages that can't shrink get a **yellow "Can't shrink" badge**, so you can tell at a glance which pages were touched and which were a waste of time. Compressed pages can be **compressed again**: right-click "Compress selected…" with a lower quality and the second round continues from the previous result (not from the original), so it can go down layer by layer. Each round is cached separately as "time_round" (`181231_r01`, `181231_r02`…), so two rounds within the same second don't overwrite each other; Ctrl+Z undoes round by round — one press back to the previous round, another back to the original, the badges following along.

Image estimation and the actual compression run **the same ffmpeg command**, so the estimate is what you get — never "estimated 66 kb, turned out 102 kb". PDF pages are truly decoded once, then the slider extrapolates along a curve; with many files the estimation runs in the background so the UI stays responsive and numbers pop in cell by cell. Dragging the slider only reads cache and scales proportionally; on release the exact value is computed in the background — a queue of dozens of images won't stutter. Truly decoding a large scanned page can take a few seconds, but it never blocks the UI. Pages that can't shrink say why instead of sitting at "estimating…" forever; they're skipped on confirmation and left as they are. Estimation errors show up as "estimate failed" as well.

**Items that grow when re-encoded are left alone.** PNG lossless re-encoding, JPG → PNG and the like can end up bigger than the original — the estimate already flags them in warning color with "N items will be larger than the original"; on confirmation those items are **not** replaced by a bigger "compressed" file. They keep the original, get a yellow "Can't shrink" badge, and the cell reads "kept as-is · re-encoded larger". To actually get smaller, change the image pipeline's output format to JPG or WebP.

**Quality does nothing for PNG output.** PNG is lossless; the quality parameter means nothing to it. When every selected item outputs PNG the slider is disabled and the hint says "PNG is lossless; quality doesn't apply" — numbers that don't move aren't a freeze, it's a lossless format ignoring quality.

**Why do some pages "have images but won't shrink"?** Bar charts, curves and gradient strips drawn by layout software are **vector graphics** (tens of thousands of path operations), not bitmaps — they look colorful, but there is no "image quality" to lower and a re-encoding engine can't help. Those pages read "no bitmaps on this page (vector/text)". Another case is images that are already a few hundred bytes (small logos, color blocks): compressing them only makes them bigger, and the page reads "N images already tiny". Both get a yellow badge.

### Which images get skipped

Better to compress less than to break something:

- Mask images (`/ImageMask`) and anything with a **non-identity** `/Decode` mapping — re-encoding shifts colors (`/Decode [0 255]` is the default; InDesign likes to write it out explicitly, and those are compressed as usual)
- Color spaces we can't decode, such as JPEG2000 or Separation — left to the system viewer as-is
- `/Indexed` palette images get their palette expanded and are re-encoded, falling back if that doesn't pay off
- Images that are already tiny — re-encoding only makes them blurrier and bigger; marked "already tiny"

**Print artwork is safe to compress.** Previously images with a transparency mask (`/SMask`) or CMYK images were skipped wholesale, so posters and brochures full of bitmaps still reported "Can't shrink" — too conservative. Now:

- **`/SMask` images are compressed as usual**: only the color channel is re-encoded, the mask object stays as-is, transparency unchanged
- **CMYK images are compressed as usual**: re-encoded as CMYK JPEG with the inversion parameters set correctly for the data source. Measured same-direction color error against the original render is < 0.02/255 — invisible; one page measured 378 KB → 168 KB

That's "images inside PDFs follow the image pipeline" applied to print artwork.

---

## Switching between workbenches

The "Video / Images / PDF" row at the top is the dividing line. Queues, settings and state on the three sides are **completely independent**:

- Drop a video → video queue; drop an image → image queue; drop a PDF → jumps to the PDF workbench
- While on the PDF workbench, anything dropped goes into the PDF queue (images included) — you're already on this page, and putting images into the image workbench would just make you hunt for them again
- "Output to" is shared by all three; switching doesn't require retyping it
- Progress bar, cancel and start are shared — the first three all use the GPU, so only one thing runs at a time; serial is steadier
- Video-tab actions (extract audio / strip audio) only appear on the video workbench

## UI language

The mode bar (the "Video / Images / PDF" row) has a language button at its **far right**:

- In the Chinese UI it reads `Switch to English`; one click switches the whole UI to English
- In the English UI it reads `切换至中文`; one click goes back to Chinese

The switch is global and needs no restart: buttons, tabs, headers, parameter names, hints, context menus, the export dialog, message boxes, the tray menu and the tray tooltip all follow. The choice is remembered in `ui.json` (program folder first, falling back to `%LOCALAPPDATA%\ZZBox\ui.json`), and the next launch starts in that language.

What is not translated: file paths, file names, text inside your files, and units such as `MB` / `KB` / `px`.

## Feel of the UI

- Drag header edges to resize columns, same as File Explorer (the column you drag moves, the ones to its right shift as a whole)
- Click to select, Shift for a range, Ctrl to add, plus rubber-band selection in the empty area below
- Hold a row and drag up or down to change the encoding order
- The green dot after processing says which job it was: "Encoded", "Audio extracted" or "Audio stripped"

---

## Requirements

- Windows 10 / 11, 64-bit
- **PDF work and image compression need no GPU** — pure CPU, runs on anything
- Video hardware encoding needs an NVIDIA card (GTX 10 series or newer; AV1 needs RTX 40 series) and a reasonably new driver
- AI enhance additionally needs Vulkan (anything RTX 20 series or newer), 6 GB of VRAM and up; the intermediate frame sequence takes a few GB to tens of GB of disk

---

## FAQ

**Double-clicking `启动.bat` says ZZBox.exe can't be found?**
First check that `ZZBox.exe` and `启动.bat` sit in the same folder. The script looks in the current folder first, then in `ZZBox vX.Y.Z`-style subfolders (the layout old packages used). If all else fails, just double-click `ZZBox.exe`.

**PDF size barely changed after compression?**
That file had nothing to compress: text-only pages have no images, the images on the page were already tens of KB, or everything hit the skip rules. Compression only touches **images inside pages**; it never redraws a page.

**Can PDFs be converted to Word?**
No, and there's no plan to. Real "editable with the layout intact" needs layout reconstruction plus font mapping — a product of another magnitude; the degraded routes that do work (whole-page images, reflowed text) produce output nobody can use. This project's PDF work is page-level organizing and moving.

**Why does a single-page file name carry `·3`?**
3 is the page's number in the **original file**. Ordering the queue however you like doesn't change it, so you can reassemble by name later.

**Why is upscaling so slow?**
The live-action model runs about 6 s/frame (RTX 4060); one minute of 720p takes 2.5–3 hours. That's the model size and the Vulkan backend talking, not a misconfiguration. Interpolating without upscaling is far faster.

**Can I pause halfway?**
No — you can only cancel the whole queue. The queue is serial: running several jobs on the GPU at once is slower, not faster.

**It keeps running after I close the window?**
Right — it drops into the tray and keeps working, then notifies you. To really quit, right-click the tray icon and pick Quit.

---

## Running from source

```bash
git clone https://github.com/<your-name>/ZZBox.git
cd ZZBox
pip install -r requirements.txt

# put ffmpeg.exe / ffprobe.exe into bin\ (or make sure they are on PATH)
# AI enhance also needs the two engines under bin\ai\, see "Installing the AI engines" below
python main.py
```

For FFmpeg, the essentials build from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) is recommended, or
the win64-gpl build from [BtbN](https://github.com/BtbN/FFmpeg-Builds/releases).

### Installing the AI engines

Both engines are portable archives; unzip them into this structure (`bin\` is excluded by `.gitignore`, so the repo doesn't ship them — download your own):

```
bin/ai/
├── esrgan/
│   ├── realesrgan-ncnn-vulkan.exe
│   ├── vcomp140.dll
│   └── models/                     ← realesr-animevideov3-x2/x3/x4, realesrgan-x4plus
└── rife/
    ├── rife-ncnn-vulkan.exe
    ├── vcomp140.dll
    └── rife-v4.6/                  ← model folder, sits next to the exe
```

Downloads:

- Upscale: [Real-ESRGAN releases](https://github.com/xinntao/Real-ESRGAN/releases) →
  `realesrgan-ncnn-vulkan-*-windows.zip`
- Interpolate: [rife-ncnn-vulkan releases](https://github.com/nihui/rife-ncnn-vulkan/releases) →
  `rife-ncnn-vulkan-*-windows.zip`

Once they're in place, open the app and switch to "AI enhance": the "Engines & cost" card shows "Upscale ready · N models" and "Interpolate ready".
Missing engines don't affect normal encoding; clicking start tells you which one is missing.

To confirm the install, one command is enough:

```bash
python tools/test_ai_pipeline.py
```

It builds a 3-second test clip, runs the whole pipeline and prints size / frame rate / **color deviation**. Color is a separate hard check: the output pixel format must be a YUV family and the per-frame RGB mean difference must stay under 16 levels — the "right size and frame rate but the picture is all green" bug is only caught by this one.

To check color on a specific clip:

```bash
python tools/check_color.py source.mp4 output.mp4
```

---

## Building it yourself

```bash
python build.py
```

The output lands in `zz box 0.7.0\` one level above the repo — a complete runnable folder (PyInstaller onedir, much faster to start than onefile), with the FFmpeg and AI engines from `bin\` carried along. To change the location, pass a path:
`python build.py "D:\some\where\ZZBox"`.

Always verify a build:

```bash
"zz box 0.7.0\ZZBox.exe" --selftest --quiet
```

The result goes to `logs\selftest.txt` in the same folder and the last line is `RESULT = PASS`. It really runs a transcode, an image compression, an image upscale, plus PDF assembly and PDF image compression — the last two exist to prove that `pypdf` and `pdfium.dll` weren't dropped by PyInstaller.

---

## Project layout

Two side-by-side folders when delivered:

```
gpu-video-encoder/
├── zz box 0.7.0/        build: ZZBox.exe + _internal/ + bin/ (FFmpeg & AI engines) + licenses/
└── zz box code/         source only, no bin/ and no build artifacts
```

Inside the source:

```
ZZBox/
├── main.py                 entry point, includes the --selftest check (video + image + PDF)
├── build.py                PyInstaller build script
├── app/
│   ├── core/
│   │   ├── probe.py        find FFmpeg, read the GPU, run one real encode to prove it works
│   │   ├── media.py        ffprobe parsing and formatting (resolution·fps·duration, size)
│   │   ├── encoder.py      command construction, size estimation, scaling math
│   │   ├── runner.py       single-process execution, ffmpeg progress parsing, cancel
│   │   ├── ai.py           AI enhance: engine detection, VRAM tiers, four-stage pipeline
│   │   ├── ai_runner.py    multi-stage executor (frame counts + ffmpeg progress, weighted)
│   │   ├── image.py        images: probe, format/quality/scale, upscale command, size estimate
│   │   ├── image_runner.py image executor (1–2 step command chain, parses engine percentage)
│   │   ├── pdf.py          PDF: page probe, render, lossless assembly (pdfium), single-page naming
│   │   ├── pdf_images.py   PDF image compression: re-encode embedded images, keep the text layer (pypdf)
│   │   └── pdf_runner.py   PDF executor (thread + cooperative cancel, no subprocess to manage)
│   └── ui/
│       ├── main_window.py  main window, three workbenches, parameter pages, scheduling
│       ├── widgets.py      queue table, integrated parameter panel, property tabs
│       ├── page_grid.py    PDF page grid (multi-select / drag reorder / Ctrl+wheel zoom / size line)
│       ├── tray.py         tray icon and background residency
│       ├── style.py        dark theme QSS
│       └── icons.py        multi-size icon loading
├── assets/                 icons (SVG / multi-size PNG / ICO), version resource
├── bin/                    ffmpeg.exe / ffprobe.exe (not in the repo)
│   └── ai/                 the two ncnn engines, each with models
├── docs/                   design docs and screenshots
└── tools/
    ├── make_icon.py        generate every icon size and the ICO from SVG
    ├── make_zips.py        build the full / lite release archives
    ├── shot_ui.py          one screenshot per property page
    ├── test_ai_pipeline.py end-to-end AI pipeline regression
    ├── test_pdf_core.py    PDF core regression (text layer, rotation, lossless assembly, naming)
    ├── test_pdf_images.py  image compression regression (text layer / page size / image pixels all unchanged)
    ├── test_pdf_ui.py      PDF workbench offscreen run + screenshots + export naming
    ├── test_pdf_zip_ui.py  compression area, four states (enabled → all/partial → staged → export)
    └── test_page_grid_drag.py  grid drag reordering (pure mouse events)
```

---

## Known limitations

- Decode on the CPU, encode on the GPU; no hardware decode or in-VRAM scaling
- HDR / 10-bit material is converted to 8-bit; colors may shift
- The queue is serial — one file at a time
- No pause; only cancelling the whole queue
- NVIDIA only (NVENC); AMD / Intel hardware encoding isn't supported
- AI enhance works frame by frame and intermediates must go to disk (the engine only reads image folders): one minute of 720p at 2× peaks at about 25–40 GB of temp space (computed at the 4× inference size, 4× the output), and 1080p sources need more
- Interpolation supports integer factors only (2×/4×); 24 fps → 60 fps isn't possible
- Output size is exactly "source × factor" — it isn't reduced further, and there's no "exceeds 4K" warning
- AI enhance output is always 8-bit `yuv420p`; HDR color can't be preserved. Normal encoding follows the source bit depth
- Animated images aren't supported: a GIF would be silently reduced to its first frame, so it isn't on the supported list at all
- Image upscaling has no adaptive tiling; outputs above roughly 80 megapixels can hit the VRAM ceiling
- The image queue and the video queue are independent and can't be merged into one pipeline
- PDF compression only touches **images**: a text-only page compresses to nothing
- Image pixel dimensions inside PDFs follow the long-edge setting under "Image compression"; by default the size is unchanged and only the encoding is redone
- PDF doesn't support password-protected files and doesn't encrypt exports
- PDF does no OCR, no text editing, no Word conversion — that's a product of another magnitude
- The same page can be imported twice into the PDF queue (a real need when imposing), at the cost of rendering the thumbnail twice
- PDF export doesn't keep the bookmark outline: once pages are reordered the original page numbers no longer line up, and carrying them over would point at the wrong places

---

## FFmpeg and licensing

**This project's own code is [MIT](LICENSE).** The bundled FFmpeg is a separate program invoked on the command line; the two do not form a derived work.

The bundle ships `ffmpeg 7.1-essentials_build` from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/), built with `--enable-gpl --enable-version3 --enable-libx264 --enable-libx265 --enable-libaom`, and is therefore **GPLv3**.
The full license text and instructions for obtaining the source ship with the package; see [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).

The PDF side deliberately avoids PyMuPDF (AGPL, which would infect the whole project's licensing): page moving uses `pypdfium2` (Apache-2.0 / BSD-3), image re-encoding uses `pypdf` (BSD-3) and Pillow (MIT-CMU).

If you redistribute: keep the `licenses/` folder and stay able to supply the matching FFmpeg source (a link to the gyan.dev download counts as a written offer). To drop that obligation entirely, let users supply FFmpeg themselves.

---

## Credits

- [FFmpeg](https://ffmpeg.org/) — the foundation under every transcode
- [Qt for Python (PySide6)](https://doc.qt.io/qtforpython/) — the UI
- [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) — Windows FFmpeg builds
- [PDFium](https://pdfium.googlesource.com/pdfium/) / [pypdfium2](https://github.com/pypdfium2-team/pypdfium2) — PDF rendering and page moving
- [pypdf](https://github.com/py-pdf/pypdf) — rewriting PDF object streams
- [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN) — upscaling models and the ncnn implementation
- [RIFE](https://github.com/hzwer/ECCV2022-RIFE) / [rife-ncnn-vulkan](https://github.com/nihui/rife-ncnn-vulkan) — frame interpolation
- [ncnn](https://github.com/Tencent/ncnn) — the inference framework behind both; the Vulkan backend is what keeps this tool free of a CUDA install

---

## 💬 Contact
Blog：http://yuemoon.vip/
GitHub：@YueMoon99
Blibili：UID223633562
YouTube：@YueMoon99

<sub><a href="#zh">↑ 返回中文 / Back to Chinese</a></sub>

