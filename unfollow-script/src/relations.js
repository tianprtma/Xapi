import { api } from './api.js';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/**
 * Paginate semua halaman dari endpoint following/followers.
 * Kembalikan array { id, username, name } unik.
 */
async function paginateAll(fetcher, label) {
  const seen = new Map();
  let cursor = null;
  let prevCursor = null;
  let page = 0;
  let stagnantPages = 0; // page berturut-turut tanpa item baru
  const MAX_STAGNANT = 2;

  while (true) {
    page += 1;
    let resp;
    try {
      resp = await fetcher(cursor);
    } catch (err) {
      console.error(`\n[${label}] page ${page} gagal: ${err.message}`);
      if (err.status === 429) {
        console.warn(`[${label}] rate limited, tidur 60s lalu retry...`);
        await sleep(60000);
        continue;
      }
      throw err;
    }

    const items = resp?.data || [];
    const before = seen.size;
    for (const u of items) {
      if (!u?.id) continue;
      seen.set(u.id, {
        id: u.id,
        username: u.username,
        name: u.name,
        protected: u.protected,
      });
    }
    const added = seen.size - before;

    const next = resp?.meta?.next_token;
    process.stdout.write(
      `\r[${label}] page ${page} → total ${seen.size} (+${added})${
        next ? ' (next…)' : ''
      }       `
    );

    // stop kondisi
    if (!next) {
      process.stdout.write('\n');
      break;
    }
    if (next === prevCursor || next === cursor) {
      process.stdout.write(
        `\n[${label}] cursor stuck (sama dgn sebelumnya), stop.\n`
      );
      break;
    }
    if (items.length === 0) {
      process.stdout.write(`\n[${label}] page kosong, stop.\n`);
      break;
    }
    if (added === 0) {
      stagnantPages += 1;
      if (stagnantPages >= MAX_STAGNANT) {
        process.stdout.write(
          `\n[${label}] ${MAX_STAGNANT} page berturut tanpa item baru, stop.\n`
        );
        break;
      }
    } else {
      stagnantPages = 0;
    }

    prevCursor = cursor;
    cursor = next;
    await sleep(1500);
  }

  return [...seen.values()];
}

export async function fetchMe() {
  const me = await api.me();
  const id = me?.data?.id;
  const username = me?.data?.username;
  if (!id) throw new Error('Gagal ambil user ID dari /2/users/me');
  return { id, username, name: me?.data?.name };
}

export async function fetchFollowing(userId) {
  return paginateAll((cursor) => api.following(userId, cursor), 'following');
}

export async function fetchFollowers(userId) {
  return paginateAll((cursor) => api.followers(userId, cursor), 'followers');
}

/**
 * Hitung following yang TIDAK followback.
 * = following \ followers
 */
export function diffNotFollowback(following, followers, whitelist) {
  const followerIds = new Set(followers.map((u) => u.id));
  return following.filter((u) => {
    if (followerIds.has(u.id)) return false;
    if (whitelist.ids.has(u.id)) return false;
    if (u.username && whitelist.usernames.has(u.username.toLowerCase()))
      return false;
    return true;
  });
}
