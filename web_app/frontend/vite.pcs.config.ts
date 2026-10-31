import {defineConfig} from 'vite';
import vue from '@vitejs/plugin-vue';
export default defineConfig({plugins:[vue()],define:{'process.env.NODE_ENV':JSON.stringify('production')},build:{outDir:'../pcs_static',emptyOutDir:true,
  lib:{entry:'src/pcs-entry.ts',name:'PCSAuxCalculator',formats:['iife'],fileName:()=> 'aux-calculator.js',cssFileName:'aux-calculator'},
  cssCodeSplit:false}});
