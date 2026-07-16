import { execFileSync } from 'node:child_process';
import { chmodSync, existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const desktopDir = dirname(dirname(fileURLToPath(import.meta.url)));
const target = execFileSync('rustc', ['--print', 'host-tuple'], { encoding: 'utf8' }).trim();
const suffix = process.platform === 'win32' ? '.exe' : '';
const binary = join(desktopDir, 'src-tauri', 'binaries', `engine-sidecar-${target}${suffix}`);

mkdirSync(dirname(binary), { recursive: true });
if (!existsSync(binary)) {
  writeFileSync(binary, 'development placeholder\n');
  if (process.platform !== 'win32') chmodSync(binary, 0o755);
}
