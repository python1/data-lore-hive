// Parses the chosen export file(s) off the main thread so a large file does not freeze the page.
import { ExportError, loadExports } from './load-export.mjs';
import { blobSource } from './zip.mjs';

self.onmessage = async ({ data: files }) => {
  try {
    self.postMessage({ ok: true, result: await loadExports(files.map((file) => ({ name: file.name, source: blobSource(file) }))) });
  } catch (error) {
    self.postMessage({ ok: false, expected: error instanceof ExportError, message: error instanceof Error ? error.message : String(error) });
  }
};
