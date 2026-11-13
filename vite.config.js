import {defineConfig} from 'vite';
export default defineConfig({server:{proxy:{'/api':'http://127.0.0.1:8768','/media':'http://127.0.0.1:8768'}},build:{outDir:'dist'}});
