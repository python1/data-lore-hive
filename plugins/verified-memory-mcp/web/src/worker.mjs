// Parses the chosen export off the main thread so a large file does not freeze the page.
import { ExportError, loadExport } from './load-export.mjs';
import { blobSource } from './zip.mjs';

self.onmessage = async ({ data: file }) => {
  try {
    self.postMessage({ ok: true, result: await loadExport({ name: file.name, source: blobSource(file) }) });
  } catch (error) {
    self.postMessage({ ok: false, expected: error instanceof ExportError, message: error instanceof Error ? error.message : String(error) });
  }
};
