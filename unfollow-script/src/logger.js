import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const LOG_DIR = path.resolve(__dirname, '..', 'logs');

if (!fs.existsSync(LOG_DIR)) fs.mkdirSync(LOG_DIR, { recursive: true });

const stamp = () => new Date().toISOString().replace(/[:.]/g, '-');
const runFile = path.join(LOG_DIR, `run-${stamp()}.jsonl`);

export const logger = {
  runFile,
  info: (msg, meta = {}) => {
    const line = { ts: new Date().toISOString(), level: 'info', msg, ...meta };
    console.log(`[${line.ts}] ${msg}`, Object.keys(meta).length ? meta : '');
    fs.appendFileSync(runFile, JSON.stringify(line) + '\n');
  },
  warn: (msg, meta = {}) => {
    const line = { ts: new Date().toISOString(), level: 'warn', msg, ...meta };
    console.warn(`[${line.ts}] WARN ${msg}`, Object.keys(meta).length ? meta : '');
    fs.appendFileSync(runFile, JSON.stringify(line) + '\n');
  },
  error: (msg, meta = {}) => {
    const line = { ts: new Date().toISOString(), level: 'error', msg, ...meta };
    console.error(`[${line.ts}] ERROR ${msg}`, Object.keys(meta).length ? meta : '');
    fs.appendFileSync(runFile, JSON.stringify(line) + '\n');
  },
};
