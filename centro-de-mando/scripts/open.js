#!/usr/bin/env node
// Abre index.html en el navegador por defecto (macOS, Windows o Linux).
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const file = fileURLToPath(new URL('../index.html', import.meta.url));
const [cmd, args] = {
  darwin: ['open', [file]],
  win32: ['cmd', ['/c', 'start', '""', file]],
}[process.platform] || ['xdg-open', [file]];

spawn(cmd, args, { stdio: 'ignore', detached: true }).on('error', () => {
  console.log(`Abre manualmente: ${file}`);
}).unref();
