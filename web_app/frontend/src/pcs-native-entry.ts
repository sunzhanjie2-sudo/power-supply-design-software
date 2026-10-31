import { createApp } from "vue";
import App from "./App.vue";
import { useLocalTransport } from "./api";
import {
  localRequest,
  localBlob,
  nativeStatus,
} from "./native_engine/transport";
import "./style.css";
import "./pcs.css";
// Capture while the classic IIFE is executing. Relative assets work on file://.
const script =
  (document.currentScript as HTMLScriptElement | null)?.src || location.href;
const cssUrl = new URL("aux-calculator.css", script).href;
useLocalTransport({ request: localRequest, blob: localBlob });
export const native = true;
export const request = localRequest;
export const getBlob = localBlob;
export const status = nativeStatus;
import {normalizeNetwork,analyzeNetwork,networkNodes,networkIncoming,networkPort,NETWORK_SCHEMA} from './native_engine/network';
export const network={normalize:normalizeNetwork,analyze:analyzeNetwork,nodes:networkNodes,incoming:networkIncoming,port:networkPort,schema:NETWORK_SCHEMA};
export function mount(host: HTMLElement, options: Record<string, any> = {}) {
  const shadow = host.shadowRoot || host.attachShadow({ mode: "open" });
  shadow.replaceChildren();
  const sheet = document.createElement("link");
  sheet.rel = "stylesheet";
  sheet.href = cssUrl;
  const container = document.createElement("div"),
    portal = document.createElement("div");
  portal.className = "pcs-modal-portal";
  shadow.append(sheet, container, portal);
  const documentUrls = {
    manual: new URL("../../docs/aux-power/计算方法与公式说明.docx", script)
      .href,
    tutorial: new URL(
      "../../docs/aux-power/多路反激电源设计入门教程.docx",
      script,
    ).href,
  };
  const app = createApp(App, {
      ...options,
      documentUrls,
      portal,
      embedded: true,
    }),
    api = app.mount(container) as any;
  return {
    destroy: () => {
      app.unmount();
      shadow.replaceChildren();
    },
    calculate: () => api.calculate(),
    getSpec: () => api.getSpec(),
    save: () => api.saveConfig(),
  };
}
