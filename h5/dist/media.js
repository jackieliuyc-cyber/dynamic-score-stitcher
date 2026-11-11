// Browser-native media probing. Container/MIME hints are never treated as proof of codec support.
const videoTypes = {mp4:'video/mp4',m4v:'video/mp4',mov:'video/quicktime',webm:'video/webm',mkv:'video/x-matroska',avi:'video/x-msvideo','3gp':'video/3gpp','3g2':'video/3gpp2',mpeg:'video/mpeg',mpg:'video/mpeg',ts:'video/mp2t',mts:'video/mp2t',m2ts:'video/mp2t',ogv:'video/ogg'};
export const conversionAdvice = '请用视频编辑器导出为 MP4（视频编码 H.264、音频 AAC）后重新选择；仅修改文件后缀无效。本工具不会自动转码。';
export function extension(name='') { return name.toLowerCase().match(/\.([a-z0-9]+)$/)?.[1] || ''; }
export function fileProblem(file) {
  if (!file || !Number.isFinite(file.size) || file.size <= 0) return '文件为空或没有下载完成。请先在相册中打开并下载原视频，再重新选择。';
  if (file.size > 700 * 1024 ** 2) return '视频超过 700 MB，请先裁短或压缩后导入。';
  const knownVideo = Boolean(videoTypes[extension(file.name)]);
  if (!knownVideo && (/^(image|audio|text)\//i.test(file.type || '') || /\.(jpe?g|png|gif|heic|heif|pdf|zip|txt|mp3|m4a|wav)$/i.test(file.name || '')))
    return '选中的文件不是视频。请选择相册中的视频或录屏文件，不要选择照片、音频或压缩包。';
  return ''; // Empty/generic MIME, extensionless provider files and unknown containers must be tried.
}
export function mediaBlob(file) {
  const hint = videoTypes[extension(file.name)];
  // Android document providers sometimes omit the type or return application/octet-stream.
  return hint && (!file.type || /^(application\/octet-stream|binary\/octet-stream)$/i.test(file.type))
    ? file.slice(0, file.size, hint) : file;
}
export function mediaMessage(code, {kind='local', timeout=false}={}) {
  const local = kind === 'local';
  if (timeout) return local
    ? '读取视频超时，暂时无法判断是否为格式问题。请先在相册中打开视频并等待云端原片下载完成，再用「从文件选择」重试；也可关闭省流模式，保持页面在前台。'
    : '读取视频超时。请检查网络和视频文件地址，或将视频下载到手机后导入。';
  if (code === 1) return '视频读取已中止，请重新选择；原文件不会被修改。';
  if (code === 2) return local
    ? '无法完整读取本地视频。请先下载相册中的原视频，或保存到「文件」后重新选择。'
    : '视频地址无法完整读取。请检查网络，以及该地址是否允许跨域读取；也可下载后导入。';
  if (code === 3) return '视频解码失败，可能是当前浏览器不支持该编码，或文件内容已损坏。' + conversionAdvice;
  if (code === 4) return '当前浏览器无法读取这个视频格式或编码，也可能文件内容无效。MP4 / MOV 后缀不保证可解码；部分设备不支持 HEVC / H.265。' + conversionAdvice;
  return '视频读取失败，请先确认原文件能在相册正常播放，再从「文件」重新选择。' + conversionAdvice;
}
export function waitForMedia(video, {start=()=>{}, condition=()=>video.readyState>=2&&!video.seeking,
    timeoutMs=45000, pollMs=150, signal, kind='local', onWaiting=()=>{}}={}) {
  return new Promise((resolve,reject)=>{
    let done=false, timeout, interval;
    const events=['loadedmetadata','loadeddata','canplay','canplaythrough','progress','seeked','resize'];
    function finish(error) {
      if(done)return;done=true;clearTimeout(timeout);clearInterval(interval);
      for(const name of events)video.removeEventListener(name,check);
      video.removeEventListener('error',failed);signal?.removeEventListener('abort',aborted);
      error?reject(error):resolve();
    }
    function failed(){finish(new Error(mediaMessage(video.error?.code,{kind})));}
    function aborted(){const error=new Error('已取消读取，可以重新选择视频。');error.name='AbortError';finish(error);}
    function check(){if(done)return;if(video.error)return failed();if(condition())return finish();onWaiting(video.readyState);}
    for(const name of events)video.addEventListener(name,check);
    video.addEventListener('error',failed);signal?.addEventListener('abort',aborted,{once:true});
    timeout=setTimeout(()=>finish(new Error(mediaMessage(null,{kind,timeout:true}))),timeoutMs);
    interval=setInterval(check,pollMs);
    if(signal?.aborted)return aborted();
    try{start();check();}catch(error){finish(error);}
  });
}
