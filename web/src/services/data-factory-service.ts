import { registerNextServer } from '@/utils/register-server';
const Prefix = '/api/v1/data-factory';
const endpoints = registerNextServer({
  get: { url: (config: any) => Prefix + config.path, method: 'get' },
  post: { url: (config: any) => Prefix + config.path, method: 'post' },
  remove: { url: (config: any) => Prefix + config.path, method: 'delete' },
});
async function read(path: string, params?: Record<string, unknown>) {
  const result = await endpoints.get({ path, params }, true);
  if (result.data.code !== 0) throw new Error(result.data.message);
  return result.data.data;
}
async function post(path: string, data: unknown) {
  const result = await endpoints.post({ path, data }, true);
  if (result.data.code !== 0) throw new Error(result.data.message);
  return result.data.data;
}
async function remove(path: string) {
  const result = await endpoints.remove({ path }, true);
  if (result.data.code !== 0) throw new Error(result.data.message);
  return result.data.data;
}
async function download(path: string, filename: string) {
  const response = await endpoints.get({ path, responseType: 'blob' }, true);
  if (
    response.status >= 400 ||
    !String(response.headers['content-type']).includes('application/zip')
  )
    throw new Error('导出失败，请检查格式支持的模态和当前权限');
  const url = URL.createObjectURL(response.data);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
async function media(path: string) {
  const response = await endpoints.get({ path, responseType: 'blob' }, true);
  if (
    response.status >= 400 ||
    String(response.headers['content-type']).includes('application/json')
  )
    throw new Error('媒体读取失败');
  return URL.createObjectURL(response.data);
}
export default { read, post, remove, download, media };
