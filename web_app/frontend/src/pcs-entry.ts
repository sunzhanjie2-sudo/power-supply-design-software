import { createApp } from 'vue';
import App from './App.vue';
import './style.css';
import './pcs.css';

export function mount(host: HTMLElement, options: Record<string, any> = {}) {
  const shadow = host.shadowRoot || host.attachShadow({mode: 'open'});
  shadow.replaceChildren();
  const sheet = document.createElement('link');
  sheet.rel = 'stylesheet'; sheet.href = options.cssUrl || '/pcs-engine/aux-calculator.css';
  const container = document.createElement('div');
  const portal = document.createElement('div'); portal.className = 'pcs-modal-portal';
  shadow.append(sheet, container, portal);
  const app = createApp(App, {...options, portal, embedded: true});
  const api = app.mount(container) as any;
  return {destroy: () => {app.unmount(); shadow.replaceChildren();},
    calculate: () => api.calculate(), getSpec: () => api.getSpec(), save: () => api.saveConfig()};
}
