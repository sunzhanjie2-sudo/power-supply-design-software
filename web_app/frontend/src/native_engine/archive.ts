import { zipSync, strToU8 } from "fflate";
export const bundle = (files: Record<string, Uint8Array>) =>
  zipSync(files, { level: 5 });
export const jsonFile = (data: any) => strToU8(JSON.stringify(data, null, 2));
