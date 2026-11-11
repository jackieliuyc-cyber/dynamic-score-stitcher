export function validCrop(crop) {
  return crop.length === 4 && crop.every(n => Number.isFinite(n) && n >= 0 && n <= 1)
    && crop[2] - crop[0] >= .2 - 1e-8 && crop[3] - crop[1] >= .12 - 1e-8;
}
export function videoProblem(duration, width, height) {
  if (!Number.isFinite(duration) || duration < .2)
    return '无法确定视频长度。请使用手机系统录制并保存的 MP4 / MOV 文件，暂不支持缺少时长信息的流式录制文件。';
  if (duration > 900) return 'H5 版支持 15 分钟以内的视频。请先裁短后选择。';
  if (!Number.isFinite(width) || !Number.isFinite(height) || width < 120 || height < 60)
    return '没有读到有效视频画面，请更换手机可播放的 MP4 / H.264 文件。';
  return '';
}
