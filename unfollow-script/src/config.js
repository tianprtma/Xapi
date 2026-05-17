import 'dotenv/config';

const required = ['XAPI_BASE_URL', 'AUTH_TOKEN'];
for (const k of required) {
  if (!process.env[k]) {
    console.error(`[config] env ${k} wajib di-set (lihat .env.example)`);
    process.exit(1);
  }
}

const parseIds = (s) =>
  (s || '')
    .split(',')
    .map((x) => x.trim())
    .filter(Boolean);

export const config = {
  baseUrl: process.env.XAPI_BASE_URL.replace(/\/+$/, ''),
  authToken: process.env.AUTH_TOKEN,
  unfollowDelayMs: Number(process.env.UNFOLLOW_DELAY_MS || 8000),
  pauseEvery: Number(process.env.PAUSE_EVERY || 25),
  pauseDurationMs: Number(process.env.PAUSE_DURATION_MS || 60000),
  maxUnfollow: Number(process.env.MAX_UNFOLLOW || 0),
  whitelistIds: new Set(parseIds(process.env.WHITELIST_IDS)),
  whitelistUsernames: new Set(
    parseIds(process.env.WHITELIST_USERNAMES).map((u) => u.toLowerCase())
  ),
};
