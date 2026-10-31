import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
export default defineConfig({
  plugins: [vue()],
  define: { "process.env.NODE_ENV": JSON.stringify("production") },
  worker: { format: "iife" },
  build: {
    outDir: "../pcs_native_static",
    emptyOutDir: true,
    lib: {
      entry: "src/pcs-native-entry.ts",
      name: "PCSAuxCalculator",
      formats: ["iife"],
      fileName: () => "aux-calculator.js",
      cssFileName: "aux-calculator",
    },
    cssCodeSplit: false,
  },
});
