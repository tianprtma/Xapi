import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { config } from './config.js';
import { api } from './api.js';
import {
  fetchMe,
  fetchFollowing,
  fetchFollowers,
  diffNotFollowback,
} from './relations.js';
import { logger } from './logger.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUT_DIR = path.resolve(__dirname, '..', 'out');
if (!fs.existsSync(OUT_DIR)) fs.mkdirSync(OUT_DIR, { recursive: true });

const args = new Set(process.argv.slice(2));
const DRY_RUN = args.has('--dry-run');
const LIST_ONLY = args.has('--list-only');

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  logger.info('Mulai', {
    base: config.baseUrl,
    dryRun: DRY_RUN,
    listOnly: LIST_ONLY,
  });

  const me = await fetchMe();
  logger.info('Auth user', me);

  logger.info('Ambil daftar following...');
  const following = await fetchFollowing(me.id);
  logger.info(`Total following: ${following.length}`);

  logger.info('Ambil daftar followers...');
  const followers = await fetchFollowers(me.id);
  logger.info(`Total followers: ${followers.length}`);

  const targets = diffNotFollowback(following, followers, {
    ids: config.whitelistIds,
    usernames: config.whitelistUsernames,
  });
  logger.info(`Not followback: ${targets.length}`);

  // Simpan snapshot
  const snapPath = path.join(OUT_DIR, `not-followback-${Date.now()}.json`);
  fs.writeFileSync(
    snapPath,
    JSON.stringify(
      {
        me,
        counts: {
          following: following.length,
          followers: followers.length,
          notFollowback: targets.length,
        },
        targets,
      },
      null,
      2
    )
  );
  logger.info(`Snapshot: ${snapPath}`);

  if (LIST_ONLY) {
    console.log('\nMode --list-only, skip unfollow.');
    return;
  }

  if (targets.length === 0) {
    logger.info('Gak ada target buat di-unfollow. Done.');
    return;
  }

  if (DRY_RUN) {
    logger.info('DRY RUN — gak akan beneran unfollow. Preview 20 pertama:');
    for (const u of targets.slice(0, 20)) {
      console.log(`  - @${u.username || '?'} (${u.id})`);
    }
    return;
  }

  const limit =
    config.maxUnfollow > 0
      ? Math.min(config.maxUnfollow, targets.length)
      : targets.length;

  logger.info(
    `Mulai unfollow ${limit} akun. Delay ${config.unfollowDelayMs}ms, pause tiap ${config.pauseEvery} akun.`
  );

  let ok = 0;
  let fail = 0;

  for (let i = 0; i < limit; i++) {
    const u = targets[i];
    const tag = `[${i + 1}/${limit}] @${u.username || '?'} (${u.id})`;

    try {
      await api.unfollow(me.id, u.id);
      ok += 1;
      logger.info(`${tag} ✓ unfollowed`);
    } catch (err) {
      fail += 1;
      logger.error(`${tag} ✗ ${err.message}`, { status: err.status });

      if (err.status === 401 || err.status === 403) {
        logger.error('Auth invalid / akun kena flag, stop.');
        break;
      }
      if (err.status === 429) {
        logger.warn('Rate limit, tidur 5 menit...');
        await sleep(5 * 60 * 1000);
      }
    }

    const isLast = i === limit - 1;
    if (isLast) break;

    if (config.pauseEvery > 0 && (i + 1) % config.pauseEvery === 0) {
      logger.info(
        `Pause anti-burst ${Math.round(config.pauseDurationMs / 1000)}s...`
      );
      await sleep(config.pauseDurationMs);
    } else {
      await sleep(config.unfollowDelayMs);
    }
  }

  logger.info(`Selesai. ok=${ok} fail=${fail} log=${logger.runFile}`);
}

main().catch((err) => {
  logger.error('Fatal: ' + err.message, { stack: err.stack });
  process.exit(1);
});
