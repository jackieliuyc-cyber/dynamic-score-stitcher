# 动态乐谱拼接工具 · H5

独立的手机浏览器版本。H5 源码位于 `h5/` 目录，Mac 版源码与启动脚本保留在项目根目录。

## 在线使用

[打开公开 H5 网页](https://dynamic-score-stitcher-h5.jackie-liuyc.chatgpt.site/) · 无需登录，手机使用移动网络或任意 Wi-Fi 即可，Mac 不需要开机。

## 使用

1. 用手机的系统录屏录下完整视频，保存到相册；页面内提供 iPhone / Android 操作指引。
2. 在 Safari / Chrome 打开 H5 地址，点击「从相册选择视频」，找不到文件时改用「从文件选择（兼容入口）」。也可用新生成的 24 秒旋律五线谱样例体验。
3. 用手指框选谱面，或者填写边界百分比。设置开始、结束时间，去掉录屏开头的系统界面。
4. 点击「生成完整乐谱」。保持页面在前台；切后台会暂停，回来后可继续。
5. 检查谱行、取消误识别的行或调整顺序，下载 PNG。长谱自动分图；手机不支持下载时，可打开原图长按保存。

手机 H5 不依赖网页共享屏幕：使用系统录屏后导入文件。视频仅在当前设备的浏览器内解码、识别和拼接，不上传处理服务器，不读取账号或 Cookie。不需要安装 Python、FFmpeg 或调用 AI 模型。

## 本机与手机预览

双击此目录中的 `启动H5预览.command`。终端会打印本机及局域网地址。

- Mac 浏览器：`http://127.0.0.1:8780/`。
- 手机：与 Mac 连接同一个 Wi-Fi，使用终端显示的局域网地址。不要在手机上输入 `127.0.0.1`。
- Mac 需保持开机且预览服务运行。若无法连接，检查两台设备是否在同一网络，以及防火墙是否允许 Python 的入站连接。
- 按 Ctrl+C 停止预览。服务提供 `dist/` 内的静态文件，传入 `--feedback-db` 时也接收反馈。

此预览启动器需要 Mac 已有的 Python 3。乐谱拼接可以部署在支持 HTTPS 的静态托管上，意见反馈需要同源的 `POST /api/feedback` 接口。直接双击 HTML 的 `file://` 模式不支持模块和 Worker。

## 意见反馈

页面底部的「意见反馈」接收最多 2000 字的文字。ECS 上的 Nginx 将 `/api/feedback` 转发给只监听 `127.0.0.1:8781` 的 `dynamic-score-feedback` 服务。反馈保存在站点目录之外，站长通过 SSH 登录 ECS 后可以查看：

```sh
sudo python3 feedback.py --database /var/lib/dynamic-score-feedback/feedback.sqlite3 --list
```

在本机开发时可以运行 `python3 serve.py --host 127.0.0.1 --feedback-db /tmp/dynamic-score-feedback-test.sqlite3`，用独立数据库测试反馈。

在反馈服务中传入 `--geoip-db /服务器数据目录/city.mmdb` 可启用来源地区推测。服务使用 `maxminddb`
读取 [DB-IP City Lite](https://db-ip.com/db/download/ip-to-city-lite) 的 MMDB 文件。杭州 ECS 的 Python 3.6 使用
`maxminddb==2.2.0`。数据库应放在网站静态目录外，可替换为新版文件后重启反馈服务。

在 Nginx 的反馈接口配置中设置 `proxy_set_header X-Real-IP $remote_addr;`，由 Nginx 用连接地址覆盖客户端请求头。
若使用 CDN，需要先配置 Nginx 只信任 CDN 的代理地址。反馈库只保存省市（`source_region`），邮件中以
「来源地区（IP 推测）」显示。本机转发、内网请求和查不到归属地的请求显示「未知」。历史反馈保留原内容。

中国省市按 `china_regions.json` 显示为中文，例如「浙江省杭州市」或「北京市」。只能确认省级地区时显示省名。
反馈服务启动时会把可识别的既有中国地区转换成相同格式。对照表的内地行政区划来自
[Administrative-divisions-of-China](https://github.com/modood/Administrative-divisions-of-China/tree/c49d495b40ac73eb1a66f6eeae5f8fd10696f035)，
拼音别名用 [pypinyin](https://pypi.org/project/pypinyin/0.55.0/) 生成，并补充了常见异名。

### 反馈邮件通知

后端启动参数 `--mail-config /安全路径/mail.json` 可启用 SMTP 通知。配置文件包含
`host`、`port`、`security`（`ssl` 或 `starttls`）、`username`、`password`、`sender`、`recipient`。
配置文件应仅允许服务账号读取，放在站点目录和 Git 仓库之外。Gmail 使用应用专用密码。

例如，在服务器上用下列命令启动带邮件通知的服务（需先创建数据库所在目录并授予服务账号写权限）：

```sh
python3 feedback.py \
  --database /var/lib/dynamic-score-feedback/feedback.sqlite3 \
  --mail-config /var/lib/dynamic-score-feedback/mail.json
```

`feedback.py`、`feedback_mail.py`、`feedback_region.py` 和 `china_regions.json` 应部署在同一目录。将同源 `/api/feedback` 请求代理到
`http://127.0.0.1:8781`。用本机 `serve.py --feedback-db` 验收时，反馈会写入本机指定的数据库；
验收 ECS 邮件通知时，应通过私有端口转发访问 ECS 站点并提交反馈。

启用后，新反馈与邮件待发送记录在同一数据库事务中保存，后台发送邮件。发送失败后自动重试，
间隔从 30 秒逐步增加到最多 1 小时，服务重启后继续处理待发送记录。历史反馈不会自动补发。
SMTP 接受邮件后记录发送时间，最终是否进入收件箱仍取决于收件服务。若发信成功后进程在记录
发送状态前退出，重试可能产生重复邮件，可按反馈编号识别。

本地回归测试运行 `python3 -m unittest discover -s h5/tests -p test_feedback_mail.py -v`
（从仓库根目录执行）。测试中的 SMTP 使用模拟对象，真实投递需要配置凭据后单独验收。

## 能力与限制

- 支持鼓谱与旋律五线谱的纵向滚动、逐页切换；直接截取原谱，不重绘音符。
- 简谱、六线谱、横向滚动暂不支持；钢琴双谱表、复杂换页需人工核对。
- 手机优先使用可本机播放的 MP4 / H.264；MOV 等格式能否读取取决于浏览器解码器。不转码，不能处理没有有限时长信息的流式 WebM。
- 最大 700 MB、15 分钟、1200 个采样画面、200 行 / 24 MB 谱行像素数据；建议先用 5 分钟以内的视频。长图按手机画布预算自动分图。
- 支持允许跨域读取的视频文件直链，不解析视频播放页面链接。
- 视频、谱行与结果暂存在当前页面内存；关闭、刷新页面或系统回收页面会丢失未保存结果。
- 文件分享与保持屏幕常亮按浏览器能力启用，局域网 HTTP 下可能不可用。图片下载和长按保存可作为替代。

## 验证与开发

无需 npm 安装、无需构建：

```sh
node --test tests/*.test.mjs
python3 serve.py
```

测试覆盖谱行检测、重复节奏滚动保留、画布分图、触屏裁切参数、无效录屏输入，并用新编码的 24 秒旋律谱 MP4 解码后检验 12 行完整保留和顺序。视频解码测试需要开发机安装 FFmpeg；H5 实际运行不需要。

本次自动浏览器连接超时，未完成浏览器端实测及 iPhone / Android 真机验收；自动测试不代表所有手机视频格式均可处理。


## 手机导入兼容性更新（1.2.0）

- 相册入口保留 `video/*` 提示且不强制摄像头；增加无类型过滤的文件选择备用入口。文件选择菜单由系统提供，网页不能强制所有手机显示相同菜单。
- 容许空 MIME、通用 MIME、无扩展名的视频进入浏览器实际解码；已知扩展名仅用于补充缺失的容器类型，不作为编码支持保证。
- 检查空文件、700 MB 上限和明显的照片/音频/文档；区分中止、读取错误、解码失败、格式/编码不可用、超时，提供本地化建议。
- 不只等待 loadeddata：结合 canplay、seeked、readyState 等信号；等待画面时显示预览及「继续读取画面」，允许用户触发静音读取。45 秒仍未就绪提示超时，不直接断言格式不支持。
- 支持取消导入、再次选择同一文件；失败会释放 Blob URL 和事件监听，恢复两种选择入口。打开选择器后直接取消不会清空当前视频。
- 未增加浏览器转码；HEVC 等格式仍由设备实际解码能力决定。建议用视频编辑器导出 H.264 / AAC MP4，仅改扩展名无效。
- 21 项自动测试通过，包括 iPhone MOV、Android 空 MIME、解码失败后重试、取消、缺少 loadeddata 事件、既有谱行提取回归。浏览器控制连接仍超时，iPhone / Android 真机验收尚未完成。

参考：[MDN 文件选择](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/input/file)、[loadeddata 的手机省流限制](https://developer.mozilla.org/en-US/docs/Web/API/HTMLMediaElement/loadeddata_event)、[媒体错误分类](https://developer.mozilla.org/en-US/docs/Web/API/MediaError/code)。


## 短谱行漏识别修复（1.2.1）

修复长谱行和短谱行混排时，短行因横线长度阈值过高被漏掉的问题。保持五条等距谱线的校验，并增加短结束行、短换拍行以及非五线图形的回归测试。23 项自动测试通过。用户提供的视频在本机按 H5 像素处理流程重跑，由 13 行恢复为 15 行；原始视频与提取图片不随源码发布。此验证使用本机 FFmpeg 解码与 H5 JavaScript 引擎，不等同于手机浏览器真机测试。
