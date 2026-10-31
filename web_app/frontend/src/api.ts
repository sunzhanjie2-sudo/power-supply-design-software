let token = "";
let local: {request:(url:string,options?:RequestInit)=>Promise<any>;blob:(url:string,signal?:AbortSignal)=>Promise<Blob>} | null = null;
export function useLocalTransport(adapter:NonNullable<typeof local>) { local=adapter; }
export function setToken(value: string) {
  token = value;
}
export async function request<T = any>(
  url: string,
  options: RequestInit = {},
): Promise<T> {
  if(local)return local.request(url,options) as Promise<T>;
  const response = await fetch("/api" + url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-Power-Token": token,
      ...options.headers,
    },
  });
  if (!response.ok) {
    let data: any;
    try {
      data = await response.json();
    } catch {
      data = { error: response.statusText };
    }
    throw new Error(
      typeof data.error === "string"
        ? data.error
        : typeof data.detail === "string"
          ? data.detail
          : JSON.stringify(data.detail ?? data),
    );
  }
  return response.json() as Promise<T>;
}
export async function getBlob(
  url: string,
  signal?: AbortSignal,
): Promise<Blob> {
  if(local)return local.blob(url,signal);
  const response = await fetch("/api" + url, {
    signal,
    headers: { "X-Power-Token": token },
  });
  if (!response.ok) {
    const data = await response
      .json()
      .catch(() => ({ error: response.statusText }));
    throw new Error(data.error || data.detail || "文件无法加载");
  }
  return response.blob();
}
export function download(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 3000);
}
export function post<T = any>(url: string, data: unknown) {
  return request<T>(url, { method: "POST", body: JSON.stringify(data) });
}
export async function postBlob(url:string,data:unknown):Promise<Blob>{
  const response=await fetch('/api'+url,{method:'POST',headers:{'Content-Type':'application/json','X-Power-Token':token},body:JSON.stringify(data)});
  if(!response.ok){const error=await response.json().catch(()=>({error:'导出失败'}));throw Error(error.error||'导出失败');}
  return response.blob();
}
