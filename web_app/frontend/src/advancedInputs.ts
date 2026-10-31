export type CompensationInterpretation = 'desktop' | 'si';
const prefixes: Record<string, number> = { '': 1, k: 1e3, M: 1e6, G: 1e9, m: 1e-3, u: 1e-6, 'µ': 1e-6, 'μ': 1e-6, n: 1e-9, p: 1e-12 };

/** Match the desktop's display-value × prefix contract unless the user
 * explicitly selects SI interpretation. Never infer encoding by magnitude. */
export function compensationInputs(saved: Record<string, any>, defaults: Record<string, number>, interpretation: CompensationInterpretation) {
  const values = { ...defaults }, warnings: string[] = [];
  for (const [key, raw] of Object.entries(saved.vars || {}) as [string, any][]) {
    if (!(key in values)) continue;
    const prefix = String(raw?.u || '');
    if (interpretation === 'desktop' && !(prefix in prefixes)) { warnings.push(`${key} 的单位前缀 ${prefix} 无效，保留当前表单值。`); continue; }
    const value = Number(raw?.v) * (interpretation === 'si' ? 1 : prefixes[prefix]);
    if (raw?.v === null || raw?.v === '' || !Number.isFinite(value)) { warnings.push(`${key} 的保存数值无效，保留当前表单值。`); continue; }
    values[key] = value;
  }
  return { values, warnings };
}
