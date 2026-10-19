import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/postcss';
import { defineConfig } from 'vite';

export default defineConfig({
  base: '/Campus-E-Wayfinding/',
  plugins: [react()],
  css: { postcss: { plugins: [tailwindcss()] } },
  build: { outDir: 'pages-dist', emptyOutDir: true },
});
