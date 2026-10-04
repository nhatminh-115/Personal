import { copyFile, mkdir, rm } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const assetRoot = resolve(webRoot, 'public/ocr');
const coreRoot = resolve(webRoot, 'node_modules/tesseract.js-core');
const copy = async (source, destination) => {
  await mkdir(dirname(destination), { recursive: true });
  await copyFile(source, destination);
};

await rm(assetRoot, { recursive: true, force: true });
await copy(resolve(webRoot, 'node_modules/tesseract.js/dist/worker.min.js'), resolve(assetRoot, 'worker.min.js'));

for (const extension of ['wasm.js', 'wasm']) {
  await copy(
    resolve(coreRoot, `tesseract-core-lstm.${extension}`),
    resolve(assetRoot, 'core', `tesseract-core-lstm.${extension}`),
  );
}

for (const language of ['eng', 'vie']) {
  await copy(
    resolve(webRoot, `node_modules/@tesseract.js-data/${language}/4.0.0_best_int/${language}.traineddata.gz`),
    resolve(assetRoot, 'lang', `${language}.traineddata.gz`),
  );
}
