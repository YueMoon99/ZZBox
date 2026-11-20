"""中文 → English 词表。

键是源码里原样的中文（标点、空格、换行都要一致），值是英文译文。
含 ``{}`` 的条目按模板匹配，用来翻「锁定 3」这类带数字或文件名的动态句子；
不含占位符的条目走精确匹配。同一张表反向查就是英译中，所以不需要第二份。
"""

STRINGS: dict[str, str] = {
    # ------------------------------------------------------------ 外壳
    "舟舟工具箱（ZZBox）": "ZZBox",
    "舟舟工具箱（ZZBox） {}": "ZZBox {}",
    "启动失败": "Startup failed",
    "程序启动时出错，无法继续运行。": "The app hit an error at startup and can't continue.",
    "错误详情已记录到：\n{}\n\n请把这个文件发给开发者。":
        "Details were written to:\n{}\n\nPlease send this file to the developer.",
    "环境检测中…": "Checking environment…",
    "输出到": "Output to",
    "留空 = 输出到源文件同目录": "Empty = save next to each source file",
    "浏览": "Browse",
    "就绪": "Ready",
    "取消": "Cancel",
    "开始压制": "Start encoding",
    "抽取音频": "Extract audio",
    "删除音轨": "Strip audio",
    "把所选（未选则全部）文件的音轨导出成 .m4a\n输出到上方的输出目录，未设置则与源文件同目录":
        "Export the audio track of the selected files (all if none selected) as .m4a\n"
        "Saved to the output folder above, or next to the source file if unset",
    "只剥掉音轨，视频流原样拷贝、不重新压制\n输出为「原名_无音轨」的副本，源文件不动":
        "Drop the audio track only; video is copied as-is without re-encoding\n"
        "Writes a copy named \"original_no-audio\"; the source stays untouched",
    # ------------------------------------------------------------ 模式条
    "视频处理": "Video",
    "图片处理": "Images",
    "PDF 处理": "PDF",
    "压缩 · 转码 · AI 超分补帧 · 音轨处理": "Compress · transcode · AI upscale & interpolate · audio",
    "批量压缩 · 格式转换 · AI 超分放大": "Batch compress · convert · AI upscale",
    "多图合成 · 页面重排 · 拆分导出 · 压缩": "Merge · reorder pages · split export · compress",
    "拖入 PDF 或图片，按页排序后导出": "Drop a PDF or images, sort the pages, then export",
    # 语言切换按钮的文案由 i18n.switch_label()/switch_tip() 直接给出，
    # 两边都已经是目标语言，所以这里**不能**再放对应词条：中文态那句英文
    # 会被反向词表翻回中文（曾经踩过）。
    # ------------------------------------------------------------ 队列通用
    "重提所选": "Retry",
    "把选中的行状态重置为就绪，可再次参与处理":
        "Reset the selected rows to Ready so they run again",
    "删除所选": "Delete",
    "从队列中移除选中的行": "Remove the selected rows from the queue",
    "清空": "Clear",
    "全选": "Select all",
    "文件队列": "File queue",
    "添加视频文件（也可以直接把视频拖进列表）":
        "Add video files (you can also drag them into the list)",
    "文件队列 · 空": "File queue · empty",
    "图片队列": "Image queue",
    "图片队列 · 空": "Image queue · empty",
    "添加图片（也可以直接把图片拖进列表）":
        "Add images (you can also drag them into the list)",
    "把图片拖到这里，或点右上角“+”添加图片":
        "Drop images here, or click + at the top right",
    "PDF 队列 · 空": "PDF queue · empty",
    "添加 PDF 或图片（也可以直接拖进列表）":
        "Add a PDF or images (you can also drag them in)",
    "把 PDF 或图片拖到这里\n多页 PDF 会自动展开成多个页面":
        "Drop a PDF or images here\nMulti-page PDFs expand into one card per page",
    "把视频文件拖到这里，或点右上角“+”添加文件":
        "Drop video files here, or click + at the top right",
    "单击 / Shift 连选 / Ctrl 加选 · 拖动格子排序 · 右键更多操作 · Ctrl+滚轮缩放 · Ctrl+Z 撤销":
        "Click / Shift range / Ctrl add · drag to reorder · right-click for more · "
        "Ctrl+wheel zoom · Ctrl+Z undo",
    "文件名": "Name",
    "原始格式": "Source",
    "导出格式": "Output",
    "原始大小": "Size",
    "预计导出大小": "Est. output",
    "操作": "Actions",
    "按编码器 / CRF / 码率与分辨率估算，\n"
    "仅供参考；实际体积取决于画面内容与编码器":
        "Estimated from encoder / CRF / bitrate and resolution.\n"
        "For reference only; real size depends on the footage and encoder",
    "锁定": "Lock",
    "已锁": "On",
    "已锁定": "Locked",
    "重提": "Retry",
    "删除": "Del",
    "锁定后本轮压制会跳过该项": "Skip this item in the next run",
    "状态重置为就绪，可再次参与压制": "Reset to Ready so it runs again",
    "从队列中移除": "Remove from the queue",
    "压制中": "Encoding",
    "已完成压制": "Encoded",
    "失败": "Failed",
    "无法读取": "Unreadable",
    "读取失败": "Read failed",
    "读取中…": "Reading…",
    "参数有误": "Bad settings",
    "已完成": "Done",
    "已停止": "Stopped",
    "已增强": "Enhanced",
    "无法规划": "Can't plan",
    "已取消": "Cancelled",
    "手动停止": "Stopped manually",
    "待估算": "pending",
    "—": "—",
    # ------------------------------------------------------------ 视频压缩页
    "视频压缩": "Compression",
    "缩放、编码与音轨处理": "Scale, encode, audio",
    "AI 增强": "AI enhance",
    "超分辨率重建与 AI 补帧": "Super-resolution and frame interpolation",
    "编码器": "Encoder",
    "音轨": "Audio",
    "质量": "Quality",
    "缩放": "Scale",
    "码率": "Bitrate",
    "兼容性最好，同画质体积最大": "Most compatible, biggest files at equal quality",
    "同画质约为 H.264 的 88%，现代设备都能播":
        "About 88% of H.264 at the same quality; plays on modern devices",
    "同画质约为 H.264 的 75%，压缩最省，但老设备播不了":
        "About 75% of H.264 at the same quality; oldest devices can't play it",
    "压缩 AAC": "AAC",
    "移除": "Remove",
    "保留原样": "Copy",
    "音轨原样拷贝，不重新编码，速度最快": "Copy the audio as-is, no re-encode, fastest",
    "输出文件不带音轨": "Output without an audio track",
    "选择文件后显示输出规格": "Select files to see the output spec",
    "数值越小画质越好、体积越大\n已按 CPU CRF 等效校准":
        "Lower = better quality, bigger file\nCalibrated against CPU CRF",
    "固定码率，出片体积可预期": "Constant bitrate; predictable output size",
    # 输入框很窄，英文再短一档，不然占位文字会被省略成 "Percent or 1280…"
    "百分比或 1280x720": "Percent or size",
    "填 37 表示 37%；填 1280x720 表示指定尺寸":
        "37 means 37%; 1280x720 means a fixed size",
    "不改变": "Keep",
    "接近无损 · 体积约为 CRF25 的 2～3 倍":
        "Near-lossless · about 2–3× the size of CRF 25",
    "高画质 · 体积约为 CRF25 的 1.5 倍": "High quality · about 1.5× CRF 25",
    "均衡 · 与小丸工具箱 CRF25 体积相当": "Balanced · same size as Maruko CRF 25",
    "小体积 · 约省 20%～35%（画面略有损失）":
        "Small · saves about 20–35% (slight quality loss)",
    "极小体积 · 约省 40% 以上（细节会糊）":
        "Tiny · saves 40%+ (fine detail gets mushy)",
    "输出 原尺寸": "Output: original size",
    # ------------------------------------------------------------ AI 面板
    "超分": "Upscale",
    "补帧": "Interpolate",
    "模型": "Model",
    "编码": "Codec",
    "降噪": "Denoise",
    "锐化": "Sharpen",
    "倍率": "Scale",
    "格式": "Format",
    "长边": "Long edge",
    "元数据": "Metadata",
    "关闭": "Off",
    "关": "Off",
    "轻度": "Light",
    "较强": "Strong",
    "真人实拍": "Live action",
    "动画番剧": "Animation",
    "跟随源": "Same as source",
    "保留": "Keep",
    "清除": "Strip",
    "长边 1920": "Long edge 1920",
    "长边 1280": "Long edge 1280",
    "像素": "px",
    "帧率翻倍，时长不变，音轨原样保留":
        "Doubles the frame rate, same duration, audio kept as-is",
    "引擎检测中…": "Detecting engines…",
    "图片压缩": "Compression",
    "AI 超分": "AI upscale",
    "格式、质量与长边缩放": "Format, quality, long-edge scaling",
    "Real-ESRGAN 放大与锐化": "Real-ESRGAN upscaling and sharpening",
    "保持原样": "Original",
    "跟随每张图自己的格式，只改质量和尺寸":
        "Keep each image's own format; only quality and size change",
    "通用性最好，不支持透明": "Most compatible, no transparency",
    "无损，体积最大，支持透明": "Lossless, biggest files, keeps transparency",
    "同画质体积约为 JPG 的 70%，支持透明":
        "About 70% of JPG at the same quality, keeps transparency",
    "超分细节最完整的落盘格式，体积也最大":
        "Keeps the most upscaled detail, but the largest files",
    "去掉 EXIF、拍摄时间、GPS 和相机型号 —— 发图前建议清掉":
        "Removes EXIF, capture time, GPS and camera model — worth clearing before sharing",
    "自定义长边像素，只缩不放": "Custom long-edge pixels; only shrinks, never enlarges",
    "超分引擎就绪后可批量放大": "Batch upscale once the engine is ready",
    "选择图片后显示输出规格": "Select images to see the output spec",
    "缺失": "Missing",
    "不可用": "Unavailable",
    "未检测到": "Not detected",
    "未知": "Unknown",
    "可用": "Available",
    "选择视频文件": "Select video files",
    "选择图片": "Select images",
    "选择 PDF 或图片": "Select a PDF or images",
    "选择输出目录": "Choose the output folder",
    "视频文件 (*.mp4 *.mkv *.mov *.avi *.flv *.webm *.ts *.m4v *.wmv *.rmvb);;所有文件 (*.*)":
        "Video files (*.mp4 *.mkv *.mov *.avi *.flv *.webm *.ts *.m4v *.wmv *.rmvb);;"
        "All files (*.*)",
    "图片文件 (*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff *.avif);;所有文件 (*.*)":
        "Image files (*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff *.avif);;All files (*.*)",
    "PDF 与图片 (*.pdf *.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff *.avif)":
        "PDF and images (*.pdf *.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff *.avif)",
    "所有文件 (*.*)": "All files (*.*)",
    # ------------------------------------------------------------ PDF 工作台
    "压缩质量": "Compression quality",
    "图片按这个值重新编码（和图片工作台同一套方案）；PDF 页按它压内嵌图片":
        "Re-encodes images at this quality (same scheme as the image workspace); "
        "PDF pages compress their embedded images with it",
    "确认压缩": "Compress",
    "旋转选中 90°": "Rotate selected 90°",
    "导出选中…": "Export selected…",
    "压缩选中…": "Compress selected…",
    "删除选中": "Delete selected",
    "撤销  Ctrl+Z": "Undo  Ctrl+Z",
    "图片按图片工作台的方案压缩；PDF 只重编码内嵌图片，文字层不动":
        "Images use the image workspace settings; PDFs only re-encode embedded "
        "images and keep the text layer",
    "导出为多个 PDF（每页一个）": "Export as separate PDFs (one per page)",
    "导出为 PNG 图片": "Export as PNG images",
    "导出为 JPG 图片": "Export as JPG images",
    "不重新渲染，文字层、链接、表单原样保留":
        "No re-render; text, links and forms are kept intact",
    "导出为 1 个 PDF（{} 页）": "Export as 1 PDF ({} pages)",
    "已压缩 ": "Compressed ",
    "已压缩 · 导出时生效": "Compressed · applied on export",
    "已保持原样 · 重编码反而更大": "Kept original · re-encoding got bigger",
    "pdf文件": "pdf",
    "不可压缩": "Can't shrink",
    "无图片可压": "no images to compress",
    "估算失败": "estimate failed",
    "估算中…": "Estimating…",
    "本页无位图（矢量/文字）": "No bitmaps on this page (vector/text)",
    "队列是空的": "Queue is empty",
    "先把 PDF 或图片拖进来，或点右上角“+”添加。":
        "Drag a PDF or images in first, or click + at the top right.",
    "有文件没能读取": "Some files could not be read",
    "以下文件被跳过：\n\n": "These files were skipped:\n\n",
    "没有可压缩的图片": "No compressible images",
    "选中的 PDF 页没有可压缩的图片：纯文字页，或图片都被跳过规则挡住了。":
        "The selected PDF pages have nothing to compress: text-only pages, or "
        "every image was excluded by the skip rules.",
    "导出视频": "Export video",
    "导出图片": "Export images",
    "导出 PDF": "Export PDF",
    "导出": "Export",
    "开始压缩": "Start compressing",
    "开始超分": "Start upscaling",
    "开始增强": "Start enhancing",
    "没有文件": "No files",
    "先把视频拖进来，或点右上角“+”添加文件。":
        "Drag videos in first, or click + at the top right.",
    "没有图片": "No images",
    "先把图片拖进来，或点右上角“+”添加图片。":
        "Drag images in first, or click + at the top right.",
    "没有可压制的文件": "Nothing to encode",
    "正在检测显卡": "Checking the GPU",
    "还在确认显卡和 ffmpeg，稍等一两秒再开始。":
        "Still probing the GPU and ffmpeg — give it a second, then start again.",
    "所有项目都已完成或被锁定。\n": "Every item is done or locked.\n",
    "全部完成": "All done",
    "存在失败任务": "Some tasks failed",
    "正在停止…": "Stopping…",
    "已手动停止": "Stopped manually",
    "没有可处理的图片": "No images to process",
    "所有图片都已完成或被锁定。\n": "Every image is done or locked.\n",
    "没有启用超分": "Upscaling is off",
    "「倍率」是关闭状态，没有要处理的内容。\n至少选一个倍率再点开始。":
        "Scale is set to Off, so there is nothing to do.\nPick a scale first.",
    "缺少超分引擎": "Upscale engine missing",
    "没有找到 realesrgan-ncnn-vulkan.exe。\n\n":
        "realesrgan-ncnn-vulkan.exe was not found.\n\n",
    "缺少组件": "Missing component",
    "缺少 AI 引擎": "AI engine missing",
    "缺少 FFmpeg": "FFmpeg missing",
    "找不到 bin/ffmpeg.exe，无法编码图片。":
        "bin/ffmpeg.exe was not found, so images can't be encoded.",
    "还没找到 ffmpeg，无法处理音轨。": "ffmpeg is missing, so audio can't be processed.",
    "没有可处理的项目": "Nothing to process",
    "所选文件里没有音频轨道。\n": "The selected files have no audio track.\n",
    "没有启用增强": "Enhancement is off",
    "「超分」和「补帧」都关着，没东西可做。\n至少打开一个再点开始。":
        "Upscale and Interpolate are both off.\nTurn one on first.",
    "以下组件没有找到：\n  ": "These components were not found:\n  ",
    "把它们解压到这个目录下即可：\n": "Unzip them into this folder:\n",
    "没有可处理的文件": "Nothing to process",
    "所有项目都已完成或被锁定。": "Every item is done or locked.",
    "磁盘空间不足": "Not enough disk space",
    "无法创建临时目录": "Can't create the temp folder",
    "PDF 装订失败": "PDF binding failed",
    "没有可装订的图片": "No images to bind",
    "PDF 未生成": "PDF not created",
    "PDF 已合成": "PDF created",
    "压缩完成": "Compression done",
    "压制完成": "Encoding done",
    "AI 增强完成": "AI enhancement done",
    "任务结束": "Task finished",
    "处理完成": "Processing done",
    "正在压制": "Encoding in progress",
    "队列还在压制，退出会中断当前任务。\n确定要退出吗？":
        "A job is still running; quitting will interrupt it.\nQuit anyway?",
    "仍在后台运行": "Still running in the background",
    "准备中…": "Preparing…",
    "使用中": "In use",
    "取消当前任务": "Cancel current task",
    "显示主窗口": "Show window",
    "退出": "Quit",
    "环境自检": "Environment check",
    "复制诊断信息": "Copy diagnostics",
    "关闭窗口": "Close",
    "当前任务跑完再操作": "Wait for the current task to finish",
    "正在处理的图片不能删除": "Can't delete an image that is being processed",
    "正在压制的文件不能重提": "Can't retry a file that is being encoded",
    "正在压制的文件不能删除": "Can't delete a file that is being encoded",
    "压制过程中不能调整顺序": "Can't reorder while encoding",
    "正在压制的文件已跳过": "Skipped files that are being encoded",
    "已重提 {} 个": "Retried {} item(s)",
    "成功 {} · 失败 {}": "{} succeeded · {} failed",
    "增强 {} · 失败 {}": "{} enhanced · {} failed",
    "成功 {} 个 · 失败 {} 个": "{} succeeded · {} failed",
    # ------------------------------------------------------------ 其他动态句
    "约 {} 秒": "about {} s",
    "约 {} 分钟": "about {} min",
    "约 {} 小时": "about {} h",
    "已清理 {} 个上次遗留的临时目录": "Cleaned up {} leftover temp folders",
    "已清理 {} 个残留临时目录": "Cleaned up {} leftover temp folders",
    "正在压缩 {} 项…": "Compressing {} items…",
    "已压缩 {} 项": "Compressed {} items",
    "，{} 项保持原样（重编码反而更大）": ", {} kept as-is (re-encoding got bigger)",
    "，{} 页无图片已跳过": ", {} pages with no images skipped",
    "选中 {} 项 · 调整质量后点「确认压缩」（大图估算可能要几秒）":
        "{} selected · adjust quality, then hit Compress (large images take a moment)",
    "选中 {} 项 · 调整质量后点「确认压缩」":
        "{} selected · adjust quality, then hit Compress",
    "选中 {} 项 · 正在估算…（大图可能要几秒）":
        "{} selected · estimating… (large images take a moment)",
    "选中 {} 项 · {} → {}（省 {}%）{}": "{} selected · {} → {} (saves {}%){}",
    "选中 {} 项 · {} 页没有可压缩的图片，将保持原样":
        "{} selected · {} pages have nothing to compress and stay as-is",
    " · {} 页无图片": " · {} pages without images",
    " · 其余估算中…": " · estimating the rest…",
    " · PNG 无损输出，质量不生效": " · PNG is lossless, quality has no effect",
    " · {} 项为 PNG 无损输出，不受质量影响":
        " · {} items are lossless PNG and ignore quality",
    " · {} 项预计比原图大，确认后保持原样（可改 JPG/WebP）":
        " · {} items would grow; they stay as-is (switch to JPG/WebP to shrink)",
    "无法读取图片尺寸": "Can't read the image size",
    "没有可装订的图片\n": "No images to bind\n",
    "第 {} 页 · {}": "Page {} · {}",
    "图片 · {}": "Image · {}",
    "{} 页": "{} pages",
    "选中 {}": "{} selected",
    "生成预览 {}/{}": "Generating previews {}/{}",
    "{} 个": "{} items",
    "{} 张": "{} images",
    "锁定 {}": "{} locked",
    "完成 {}": "{} done",
    "共 {} 张　": "{} images　",
    "正在压缩图片… {}%": "Compressing images… {}%",
    "正在导出图片… {}%": "Exporting images… {}%",
    "正在导出… {}%": "Exporting… {}%",
    "PDF 处理中 {}%": "Processing PDF… {}%",
    "正在导出 {} 张图片…": "Exporting {} images…",
    "正在导出 {} 个 PDF…": "Exporting {} PDFs…",
    "已导出 {} 个 PDF": "Exported {} PDFs",
    "已导出 {} 张图片到 {}": "Exported {} images to {}",
    "导出 {} 页": "Export {} pages",
    "导出 {} 个 PDF": "Export {} PDFs",
    "正在处理　{}": "Processing　{}",
    "处理中 {}%": "Processing {}%",
    "压制中 {}%": "Encoding {}%",
    "压制中 0%": "Encoding 0%",
    "处理中 0%": "Processing 0%",
    "AI 增强 0%": "AI enhance 0%",
    "就绪 · {} 页": "Ready · {} pages",
    "就绪 · 队列为空": "Ready · queue is empty",
    "{} · PDF（{} 页）": "{} · PDF ({} pages)",
    "就绪 · {} 个文件": "Ready · {} files",
    "{} · 就绪（{} 个文件）": "{} · Ready ({} files)",
    "全部完成 · {} 个": "All done · {} items",
    "{} · 全部完成（{} 个文件）": "{} · All done ({} files)",
    "完成 {} 张{}": "{} images done{}",
    " · 失败 {}": " · {} failed",
    "已合成 PDF：{}（{} 页）{}": "PDF created: {} ({} pages){}",
    "{}（{} 页）": "{} ({} pages)",
    "{} · 用时 {}": "{} · took {}",
    "用时 {} 秒": "took {} s",
    "用时 <1 秒": "took <1 s",
    "已导出 {} 个 PDF\n": "Exported {} PDFs\n",
    "已重提 {} 个\n": "Retried {} items\n",
    "跳过 {} 个无音轨文件": "Skipped {} files without audio",
    "\n将跳过 {} 个无音轨文件。": "\n{} files without audio will be skipped.",
    "将对 {} 个文件{}。\n输出到：{}\n\n继续吗？":
        "{} file(s) will be {}. \nOutput to: {}\n\nContinue?",
    "输出：{}": "Output: {}",
    "各源文件所在目录": "each source file's folder",
    "已清理 {} 个残留临时目录\n": "Cleaned up {} leftover temp folders\n",
    "　临时文件未删净：{}": "　Temp files not fully removed: {}",
    "已停止{}": "Stopped{}",
    "输出 {}×{}（源 {}×{}{}）": "Output {}×{} (source {}×{}{})",
    "推荐 {}×（{}）": "Recommended {}× ({})",
    "推荐关闭（{}）": "Recommended: off ({})",
    "{} · 高于推荐档，更慢更占空间": "{} · above the recommended tier, slower and larger",
    "{}×推理后降采样": "{}× inference then downsample",
    "（{}×推理后降采样）": " ({}× inference, then downsample)",
    "{}×{} 原尺寸": "{}×{} original size",
    "超分 {}": "Upscale {}",
    "补帧 {}": "Interpolate {}",
    "显存 {}G·{}": "VRAM {}G·{}",
    " · 超分与补帧均已关闭": " · upscale and interpolation are both off",
    " · 选择文件后显示输出规格": " · select files to see the output spec",
    " · 超分引擎 {}{}": " · upscale engine {}{}",
    "{} · {} · 当前 {}": "{} · {} · current {}",
    "{} · {} 就绪": "{} · {} ready",
    "{} · 无可用编码器": "{} · no usable encoder",
    "全部完成（{} 个文件）": "All done ({} files)",
    "超分 {}/": "Upscale {}/",
    "临时约 {} GB，{} 仅剩 {} GB，空间不足，请换输出目录":
        "About {} GB of temp space needed, only {} GB left on {}; pick another output folder",
    "（余 {} GB）": " ({} GB free)",
    "临时约 {} GB → {}{}，做完自动删": "Temp {} GB → {}{}, deleted when done",
    "推理 {} MP，明显超出 {}档显存": "{} MP inference, well beyond the {} tier",
    "推理 {} MP，{}档显存可以应付": "{} MP inference, the {} tier can handle it",
    "驱动：{}": "Driver: {}",
    "显卡：{}": "GPU: {}",
    "路径：{}": "Path: {}",
    "FFmpeg：{}": "FFmpeg: {}",
    "　显存 {} MB": "　VRAM {} MB",
    "不可用（{}）": "Unavailable ({})",
    "{} · 缺少第 {} 页": "{}: page {} is missing",

    # ------------------------------------------------------------ AI 引擎与计划
    "超分引擎": "Upscale engine",
    "补帧引擎": "Interpolation engine",
    "超分引擎 {}": "Upscale engine {}",
    "补帧引擎 {}": "Interpolation engine {}",
    "拆帧": "Split frames",
    "合成": "Mux",
    "引擎": "engine",
    "程序": "program",
    "未找到 realesrgan-ncnn-vulkan.exe": "realesrgan-ncnn-vulkan.exe not found",
    "未找到 rife-ncnn-vulkan.exe": "rife-ncnn-vulkan.exe not found",
    "超分引擎缺失：需要 bin/ai/realesrgan-ncnn-vulkan.exe":
        "Upscale engine missing: bin/ai/realesrgan-ncnn-vulkan.exe is required",
    "超分引擎没有可用模型，请检查 bin/ai/models 目录":
        "The upscale engine has no usable model; check bin/ai/models",
    "补帧引擎缺失：需要 bin/ai/rife-ncnn-vulkan.exe":
        "Interpolation engine missing: bin/ai/rife-ncnn-vulkan.exe is required",
    "源文件不可读": "The source file can't be read",
    "超分和补帧都关掉了，没有可做的事":
        "Upscale and interpolation are both off, so there is nothing to do",
    "无法计算输出尺寸": "Can't work out the output size",
    "无法启动 {}，请确认文件未被杀毒软件删除":
        "Can't start {}; make sure the file was not removed by antivirus",
    "超分 {}× → {}×": "Upscale {}× → {}×",
    "降采样 {}× → {}×": "Downsample {}× → {}×",
    "超分 {}×": "Upscale {}×",
    "补帧 {}×": "Interpolate {}×",
    "{}p 在这张卡上推理面积过大，建议不放大":
        "{}p is too much area for this GPU; not upscaling is recommended",
    "源已是 {}p，再超分收益很小": "Source is already {}p; upscaling gains little",
    "推理面积 {} MP，约为 {}档显存建议值的 {} 倍，可能因显存不足失败或明显变慢":
        "{} MP of inference, about {}× the {} tier's budget; may run out of VRAM or slow down",
    "输出尺寸没有超过源文件，这次超分不会带来更大画面":
        "The output is no bigger than the source, so upscaling adds no detail",
    "{}×{} 超出 {}档显存建议范围，已改用 {}px 分块处理，耗时会明显增加":
        "{}×{} exceeds the {} tier's budget; switching to {}px tiles will take noticeably longer",
    "音轨为 {}，容器不支持，已转 AAC": "Audio is {}; the container doesn't support it, so it was converted to AAC",
    "音轨为 {}，目标容器不支持，已自动转 AAC":
        "Audio is {}; the target container doesn't support it, converted to AAC",
    "源音频码率 {} Mbps 偏大，已转 AAC {}k 以缩小体积":
        "Source audio is {} Mbps, which is high; converted to AAC {}k to save space",
    "低码率视频先降噪再超分，避免把压缩块和振铃一起放大 4 倍\n"
    "逐帧对比过：轻度档对细节几乎无损，压制痕迹明显的源值得开":
        "Denoise low-bitrate video before upscaling, so blockiness and ringing don't get 4× bigger\n"
        "Frame-by-frame comparison: Light is nearly lossless on detail; worth it for visibly compressed sources",
    "4× 重建后降到目标尺寸，边缘会软一档，补一点 unsharp 拉回来\n"
    "默认轻度；开到「较强」会开始出白边，慎用":
        "After 4× reconstruction the edges get soft once downsampled; a little unsharp brings them back\n"
        "Light by default; Strong starts to produce halos, use with care",
    "RRDB 深度网络（约 1670 万参数），能重建皮肤纹理、发丝、布料\n"
    "固定 4× 推理再降采样到目标尺寸，单帧约 6 秒（8G 卡）":
        "RRDB network (~16.7M parameters) that rebuilds skin texture, hair and fabric\n"
        "Always infers at 4× then downsamples; about 6 s per frame on an 8 GB card",
    "SRVGGNet 轻量架构（约 60 万参数，仅 1.4 MB），速度快 5 倍\n"
    "训练集全是动画帧，拿它处理真人会把皮肤抹成色块 —— 只给番剧/动画用":
        "Lightweight SRVGGNet (~0.6M parameters, only 1.4 MB), about 5× faster\n"
        "Trained purely on animation frames; live-action skin turns into flat patches — use it for anime only",
    "高": "High",
    "中": "Medium",
    "低": "Low",
    "极低": "Very low",
    "12G 以上，4K 输出全开": "12 GB+, 4K output is fine",
    "8G 档，4K 需要较长等待": "8 GB tier, 4K takes a while",
    "6G 档，建议最高 1440p": "6 GB tier, 1440p recommended",
    "4G 及以下，仅建议 1080p": "4 GB or less, 1080p only",
    "就绪·{}模型": "Ready · {} models",
    "{}·{}模型": "{} · {} models",
    # ------------------------------------------------------------ 图片核心
    "文件不存在": "The file doesn't exist",
    "文件无法解析，可能已损坏或格式不支持":
        "The file can't be parsed; it may be damaged or unsupported",
    "ffprobe 输出解析失败": "Failed to parse ffprobe output",
    "该文件不包含图像": "The file contains no image",
    "该文件不包含视频流": "The file contains no video stream",
    "读取失败：{}": "Read failed: {}",
    "未找到 ffprobe.exe": "ffprobe.exe not found",
    "未找到 ffmpeg.exe，请确认 bin 目录完整":
        "ffmpeg.exe not found; check that bin/ is complete",
    "未知错误": "Unknown error",
    "无音轨": "No audio",
    "{} 条音轨 · {}": "{} audio track(s) · {}",
    "{}× 推理 → {}×": "{}× inference → {}×",
    "{}× 超分": "{}× upscale",
    "约 {}{}": "about {}{}",
    " · 原图 {}": " · original {}",
    " · 每张约 {} 秒": " · about {} s each",
    "输出 {}×{} 超过 8000 万像素，单张可能占用数 GB 显存":
        "Output {}×{} is over 80 MP; a single image may need several GB of VRAM",
    "输出 {}×{} 约 {} MP，一张要跑几十秒":
        "Output {}×{} is about {} MP; each image takes tens of seconds",
    "源图 {} MP，超分后像素接近 {} MP，耗时很长":
        "Source is {} MP and upscaling approaches {} MP; this will take a long time",
    "目标尺寸不超过原图长边，超分出来的细节会被直接缩掉，白花时间":
        "The target is no larger than the source's long edge, so the extra detail is thrown away",
    "源图带透明通道，转 JPG 后透明区域会变成白色":
        "The source has transparency; JPG turns transparent areas white",
    # ------------------------------------------------------------ PDF 核心
    "解析页面失败：{}": "Failed to parse pages: {}",
    "这个 PDF 有打开密码，暂不支持带密码的文件":
        "This PDF requires a password, which isn't supported yet",
    "文件不是有效的 PDF，或已经损坏": "Not a valid PDF, or the file is damaged",
    "无法打开：{}": "Can't open: {}",
    "图片无法读取：{}": "Image can't be read: {}",
    "页码超出了文件范围": "The page number is out of range",
    "没有可导出的页面": "No pages to export",
    "没有可压缩的页面": "No pages to compress",
    "写入失败：{}": "Write failed: {}",
    "压缩失败：{}": "Compression failed: {}",
    "约原体积的 {}%": "about {}% of the original",
    "这个文件已经是文字版，压缩后会变成图片，体积反而涨到约 {} 倍 —— 不建议压缩":
        "This file is already text-based; compressing rasterizes it and grows the file to about {}× — not recommended",
    "检测到 {} 页含文字层，压缩后文字会变成图片、不能再搜索或复制":
        "{} pages have a text layer; after compression the text becomes an image and can't be searched or copied",
    "图片 {} · 待估算": "Image {} · pending",
    "图片 {} → {}": "Image {} → {}",
    "{} 张图片已极小（共 {}），无可压缩空间":
        "{} images are already tiny (of {}); nothing to save",
    "{} 张图片不可压缩（共 {}）": "{} images can't be compressed (of {})",
    "蒙版图": "Mask",
    "自定义颜色映射": "Custom color map",
    "{} 色彩空间": "{} color space",
    "打不开 {}：{}": "Can't open {}: {}",
    "{} 已加密，需要密码才能处理": "{} is encrypted and needs a password",
    "读不了 {}：{}": "Can't read {}: {}",
    "写不出 {}：{}": "Can't write {}: {}",
    "读不出图片 {}：{}": "Can't extract image {}: {}",
    "{} 不是有效图片": "{} is not a valid image",
    "{} 没有第 {} 页": "{} has no page {}",
    # ------------------------------------------------------------ 运行时错误
    "剩余 {}:{}": "{}:{} left",
    "完成": "Done",
    "无法启动 ffmpeg，请确认 bin 目录中的 ffmpeg.exe 存在":
        "Can't start ffmpeg; check that bin/ffmpeg.exe exists",
    "文件已损坏或格式不支持": "The file is damaged or the format is unsupported",
    "当前的 ffmpeg 无法解码这种素材（缺少解码器）":
        "This ffmpeg build can't decode that source (decoder missing)",
    "素材解码出错，文件可能已损坏": "Decoding failed; the file may be damaged",
    "没有写入权限，请换一个输出目录":
        "No write permission; choose another output folder",
    "当前 ffmpeg 不支持该编码器": "This ffmpeg build doesn't support that encoder",
    "显卡不支持这组编码参数（10bit 或 B 帧），请换 HEVC 或升级显卡":
        "The GPU rejects these encoder settings (10-bit or B-frames); "
        "use HEVC or a newer card",
    "显卡不支持这组编码参数（10bit、B 帧或分辨率超限），请换 HEVC 或降低分辨率":
        "The GPU rejects these encoder settings (10-bit, B-frames or resolution); "
        "switch to HEVC or lower the resolution",
    "该显卡不支持 B 帧参考（Pascal 及更早的 NVENC）":
        "This GPU has no B-frames-as-references (Pascal and older NVENC)",
    "编码器没有产出画面，显卡可能不支持该格式":
        "The encoder produced no frames; the GPU may not support this format",
    "编码器没有产出画面，显卡可能不支持该格式或分辨率":
        "The encoder produced no frames; the GPU may not support this format or resolution",
    "色彩格式无法转换（源素材的色度抽样或色彩标签异常）":
        "Colour conversion failed (odd chroma subsampling or colour tags in the source)",
    "分辨率低于显卡编码器的最小要求":
        "Resolution is below the GPU encoder's minimum",
    "编码器初始化失败，显卡可能不支持这组参数":
        "Encoder init failed; the GPU may not accept these settings",
    "{}×{} 超出 {} 的上限 {}px，已按 {}×{} 输出":
        "{}×{} exceeds the {} limit of {}px; outputting {}×{}",
    "目标 {}×{} 小于显卡最小尺寸 {}×{}，已按原尺寸输出":
        "Target {}×{} is below the GPU minimum {}×{}; keeping the original size",
    "分辨率 {}×{} 低于显卡最小尺寸，已放大到 {}×{} 后编码":
        "{}×{} is below the GPU minimum; upscaled to {}×{} before encoding",
    "{} 不支持 10bit，HDR 素材已转为 SDR":
        "{} can't encode 10-bit; HDR tone-mapped to SDR",
    "{} 不支持 10bit，已降为 8bit（HDR 信息丢失）":
        "{} can't encode 10-bit; dropped to 8-bit (HDR lost)",
    "{} 不支持 10bit，已降为 8bit":
        "{} can't encode 10-bit; dropped to 8-bit",
    "压缩 · 转码 · AI 超分补帧 · 音轨处理 · HDR 素材将转为 SDR":
        "Compress · transcode · AI upscale & interpolate · audio · HDR → SDR",
    "显存或内存不足": "Out of VRAM or memory",
    "输出文件已存在": "The output file already exists",
    "ffmpeg 退出码 {}": "ffmpeg exit code {}",
    "显存不足，请降低超分倍率": "Out of VRAM; lower the upscale factor",
    "图片无法读取，可能已损坏或格式不支持":
        "The image can't be read; it may be damaged or unsupported",
    "格式不支持，换一种输出格式再试":
        "Unsupported format; try a different output format",
    "退出码 {}": "exit code {}",
    "没有可执行的步骤": "No steps to run",
    "还有任务在跑，等它结束": "Another task is still running; wait for it to finish",
    "{}阶段失败：显存不足，请降低倍率或输出分辨率":
        "Stage {} failed: out of VRAM; lower the scale or output resolution",
    "{}阶段失败：文件读写被拒绝，检查输出目录权限":
        "Stage {} failed: file access denied; check the output folder permissions",
    "{}阶段失败：模型文件不匹配，请重新下载 AI 引擎":
        "Stage {} failed: model mismatch; download the AI engine again",
    "{}阶段失败：{}": "Stage {} failed: {}",
    "磁盘空间不足，临时帧序列写不下了":
        "Not enough disk space for the temporary frame sequence",
    # ------------------------------------------------------------ 导出对话框
    "保存位置": "Save to",
    "选择一个文件夹作为输出位置": "Pick a folder for the output",
    "浏览…": "Browse…",
    "输入文件名": "Enter a file name",
    "保存类型": "Save as",
    "保存至子文件夹（ZZbox output.年.月.日.时.分）":
        "Save into a subfolder (ZZbox output.YYYY.MM.DD.HH.mm)",
    "当前目录已经是输出子文件夹，不再嵌套":
        "This folder is already an output subfolder; no extra nesting",
    "保存": "Save",
    "还没选位置": "No location yet",
    "先选一个输出文件夹。": "Choose an output folder first.",
    "位置无效": "Invalid location",
    "这个文件夹无法创建：\n{}": "This folder can't be created:\n{}",
    "输出到：{}\\{}": "Output to: {}\\{}",
    "{} 等 {} 个文件": "{} and {} more files",
    "文件": "file",
    "MP4 视频 (*.mp4)": "MP4 video (*.mp4)",
    "MKV 视频 (*.mkv)": "MKV video (*.mkv)",
    "MOV 视频 (*.mov)": "MOV video (*.mov)",
    "PNG 图片 (*.png)": "PNG image (*.png)",
    "JPG 图片 (*.jpg)": "JPG image (*.jpg)",
    "WebP 图片 (*.webp)": "WebP image (*.webp)",
    "PDF（全部合成一个）": "PDF (all in one)",
    "PDF（合并为 1 个）": "PDF (merge into one)",
    "PDF（按来源分别导出）": "PDF (one per source)",
    "PNG 图片（每页一张）": "PNG images (one per page)",
    "JPG 图片（每页一张）": "JPG images (one per page)",
    # ------------------------------------------------------------ 文件名与阶段词
    "合并": "merged",
    "整理": "organized",
    "拆分": "split",
    "页面": "page",
    "图片": "images",
    "选中_{}页": "selected_{}pages",
    "抽取中": "Extracting audio",
    "去音轨中": "Stripping audio",
    "已抽取音频": "Audio extracted",
    "已删除音轨": "Audio stripped",
    "_无音轨": "_noaudio",

    # ------------------------------------------------------------ 补充：弹窗与提示
    "界面渲染出错：{}": "UI render error: {}",
    "PDF (*.pdf)": "PDF (*.pdf)",
    "图片 (*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff *.avif)":
        "Images (*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff *.avif)",
    " · 高于推荐档，更慢更占空间": " · above the recommended tier, slower and larger",
    "选中的 PDF 页没有可压缩的图片：纯文字页，或图片都被跳过规则挡住了。"
    "这些页保持原样，不需要压缩。":
        "The selected PDF pages have nothing to compress: either text-only pages or "
        "every image was excluded by the skip rules. They stay as they are.",
    "\n另外 {} 页已加入队列。": "\n{} more pages were added to the queue.",
    "{}完成": "{} done",
    "{}失败": "{} failed",
    "窗口已隐藏，压制任务不会中断。\n双击托盘图标可恢复窗口，右键托盘图标可退出。":
        "The window is hidden; encoding keeps running.\n"
        "Double-click the tray icon to bring it back, right-click to quit.",
    "·{}模型": " · {} models",
    "未找到 FFmpeg": "FFmpeg not found",
    "未检测到 NVIDIA 显卡": "No NVIDIA GPU detected",
    "找不到 ffmpeg.exe": "ffmpeg.exe not found",
    "目标码率 · 1080p 建议 4000~8000 kbps，数值越大越清晰":
        "Target bitrate · 4000–8000 kbps is typical for 1080p; higher looks cleaner",
    "超分与补帧均已关闭": "upscale and interpolation are both off",
    "不放大，只做补帧（如果补帧也关着，就没有可做的事）":
        "No upscaling, interpolation only (if that is off too, nothing happens)",
    "所有项目都已完成或被锁定。\n点行尾的「重提」可以把它们重新放回队列。":
        "Every item is done or locked.\nUse Retry at the end of a row to put it back in the queue.",
    "所有图片都已完成或被锁定。\n点行尾的「重提」可以把它们重新放回队列。":
        "Every image is done or locked.\nUse Retry at the end of a row to put it back in the queue.",
    "所选文件里没有音频轨道。\n（删除音轨需要有音轨才谈得上删除；抽取音频同理）":
        "The selected files have no audio track.\n"
        "(Stripping or extracting audio needs a track to begin with.)",
    "{} {} · 失败 {}": "{} {} · {} failed",
    "已压缩": "Compressed",
    "已压缩 {}": "Compressed {}",
    "PDF 队列": "PDF queue",
    "压缩": "Compress",
    "压缩结果已换入队列，导出时直接使用":
        "Compressed copies replaced the queued items; export uses them directly",
    "处理中": "Processing",
    "AI 增强中": "Enhancing",
    "无法构造命令": "Can't build the command",
    "{} 项已换入队列": "{} items replaced in the queue",
    "\n\n★ 当前素材推荐关闭：放大不划算":
        "\n\n★ Off is recommended for this footage; upscaling isn't worth it",
    "\n\n★ 当前素材推荐这一档": "\n\n★ Recommended tier for this footage",
    "推理 {} MP，明显超出 {}档显存建议范围，容易失败或很慢":
        "{} MP of inference is well past the {} tier's budget; likely to fail or crawl",
    "{}（不支持这种格式）": "{} (format not supported)",
    "<1 秒": "<1 s",
    "{} 秒": "{} s",
    "\n\n把它们解压到这个目录下即可：\n": "\n\nUnzip them into this folder:\n",
    "没有找到 realesrgan-ncnn-vulkan.exe。\n\n把它解压到这个目录下即可：\n{}\n\n"
    "目录结构：\n  bin/ai/realesrgan-ncnn-vulkan.exe\n  bin/ai/models/\n\n"
    "引擎是 Vulkan 版，不需要装 CUDA 或 Python。":
        "realesrgan-ncnn-vulkan.exe was not found.\n\nUnzip it into this folder:\n{}\n\n"
        "Layout:\n  bin/ai/realesrgan-ncnn-vulkan.exe\n  bin/ai/models/\n\n"
        "The engine is the Vulkan build; no CUDA or Python needed.",
    "以下组件没有找到：\n  {}\n\n把它们解压到这个目录下即可：\n{}\n\n"
    "目录结构：\n  bin/ai/realesrgan-ncnn-vulkan.exe\n  bin/ai/models/\n"
    "  bin/ai/rife-ncnn-vulkan.exe\n  bin/ai/rife/models/\n\n"
    "引擎是 Vulkan 版，不需要装 CUDA 或 Python。":
        "These components were not found:\n  {}\n\nUnzip them into this folder:\n{}\n\n"
        "Layout:\n  bin/ai/realesrgan-ncnn-vulkan.exe\n  bin/ai/models/\n"
        "  bin/ai/rife-ncnn-vulkan.exe\n  bin/ai/rife/models/\n\n"
        "The engines are Vulkan builds; no CUDA or Python needed.",
    "这次增强需要约 {} 临时空间，\n输出目录与系统临时盘最多只剩 {}。\n\n"
    "换一个空间充裕的输出目录，或先处理短一点的片段。\n"
    "临时文件会落在输出目录所在的磁盘，尽量不要放在系统盘。":
        "This enhancement needs about {} of temp space, but the output folder and the "
        "system temp drive have only {} left.\n\n"
        "Pick an output folder with more room, or process a shorter clip first.\n"
        "Temp files live on the output folder's drive; avoid the system drive.",
    "将处理 {} 个文件。\n临时帧序列峰值约 {}（放在 {}）\n\n"
    "AI 增强是用算力换画质：1 分钟 720p 片段可能需要几分钟到几十分钟。\n"
    "处理期间请勿关闭程序或拔掉硬盘。\n\n继续吗？":
        "{} file(s) will be processed.\nPeak temp frames about {} (in {})\n\n"
        "AI enhancement trades compute for quality: a 1-minute 720p clip can take "
        "minutes to tens of minutes.\nDon't close the app or unplug the drive while it runs."
        "\n\nContinue?",
    "按编码器 / CRF / 码率与分辨率估算，\n实际成片通常有 ±25% 浮动，码率模式最准。":
        "Estimated from encoder / CRF / bitrate and resolution.\n"
        "Real output usually varies by ±25%; bitrate mode is the closest.",
    "当前显卡不支持该编码器": "This GPU doesn't support that encoder",
    "把 PDF 或图片拖到这里，或点右上角“+”添加":
        "Drop a PDF or images here, or click + at the top right",
    "_超分{}x": "_upscaled{}x",
    "_压缩": "_compressed",
}
