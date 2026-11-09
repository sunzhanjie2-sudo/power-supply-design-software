export type Spec = Record<string, any>;
export interface Parameter {
  name: string;
  label: string;
  symbol: string;
  unit: string;
  display_unit: string;
  display_factor: number;
  category: string;
  group: string;
  type: string;
  enabled_by: string;
  auto_zero: boolean;
  deprecated: boolean;
  topologies: string[];
  default: any;
}
export interface CurveTarget {
  target: string;
  ref: string;
  role: string;
  axes: string;
  source: string;
  loaded: boolean;
  filename: string;
  kind: string;
}
export interface Preview {
  component_rows?: Spec[];
  component_rules?: Spec;
  capacitor_types?: Spec;
  component_note?: string;
  outputs: Spec[];
  isolated: boolean;
  targets: CurveTarget[];
}
export interface Bootstrap {
  native?: boolean;
  parasitics: Spec;
  spice_options: {key:string;default:number;minimum:number;maximum:number;label:string;unit:string;group:string;topologies:string[];choices?:Record<string,string>}[];
  spice_presets: Record<string,Spec>;
  spice_niso_reference_keys: string[];
  spice_logic: Spec;
  spice_qr_logic: Spec;
  spice_acf_logic: Spec;
  spice_niso_logic: Spec;
  token: string;
  version: string;
  spec: Spec;
  parameters: Parameter[];
  sections: Record<string, string>;
  topologies: string[];
  examples: Record<string, string>;
  cores: Record<string, Spec>;
  materials: Record<string, Spec>;
  permeability_materials?: Record<string, Spec>;
  core_shapes: Record<string, string[]>;
  coupling: Record<string, Spec>;
  output_template: Spec;
  preview: Preview;
}
export interface Check {
  id: string;
  name: string;
  value: number | null;
  limit: number | null;
  comparison: string;
  unit: string;
  state: string;
  note: string;
}
export interface Summary {
  ok: boolean;
  error?: string;
  topology: string;
  operating_point: Record<string, any>;
  losses: Record<string, number>;
  magnetics: Spec;
  checks: Check[];
  loop: Spec | null;
  warnings: string[];
  outputs: Spec[];
  feedback: Spec;
}
export interface Case {
  id: string;
  V_in: number;
  parameters: Spec;
  summary: Summary;
  checks: Check[];
  error: string | null;
  loop_error: string | null;
}
export interface Snapshot {
  schema: string;
  snapshot_id: string;
  created_at: string;
  ok: boolean;
  spec: Spec;
  cases: Case[];
  hardware: Spec;
  provenance: Spec;
  cross_regulation: Spec | null;
  display: Spec[];
}
export interface Job {
  id: string;
  state: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  progress: number;
  message: string;
  error?: { message: string; issues?: Spec[] };
  result?: Spec;
}
export const topologyNames: Record<string, string> = {
  FLYBACK: "反激",
  "QR-FLYBACK": "准谐振反激",
  "ACF-FORWARD": "有源钳位正激",
  BUCK: "Buck 降压",
  BOOST: "Boost 升压",
  "BUCK-BOOST": "Buck-Boost 升降压",
};
export function fmt(value: any, unit = "", digits = 3): string {
  if (value === null || value === undefined || !Number.isFinite(Number(value)))
    return "—";
  const n = Number(value);
  return (
    new Intl.NumberFormat("zh-CN", { maximumSignificantDigits: digits }).format(
      n,
    ) + (unit ? " " + unit : "")
  );
}
