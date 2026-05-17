// Xapi — X (Twitter) Cookie API reference catalog.
// Sections + detailed endpoint definitions extracted from app/routers/*.py.
// Items in `sections` not present in `endpoints` render as stub pages.
window.XDOC_DATA = (function () {
  // Base URL detection priority:
  //   1. window.XAPI_BASE_URL  (override via <script>window.XAPI_BASE_URL="…"</script>)
  //   2. ?api=…                (override via query string, useful for testing)
  //   3. localStorage.xapi_base (sticky override per-browser)
  //   4. window.location.origin (default — same host as docs UI)
  const qs = new URLSearchParams(window.location.search);
  const BASE = (
    window.XAPI_BASE_URL ||
    qs.get('api') ||
    localStorage.getItem('xapi_base') ||
    window.location.origin
  ).replace(/\/+$/, '');
  if (qs.get('api')) localStorage.setItem('xapi_base', qs.get('api'));

  const sections = [
    {
      id: 'start', label: 'Getting started', icon: '/',
      items: [
        { id: 'overview',     label: 'Overview',       kind: 'page' },
        { id: 'quickstart',   label: 'Quickstart',     kind: 'page' },
        { id: 'auth',         label: 'Authentication', kind: 'page' },
        { id: 'raw-mode',     label: 'Raw mode',       kind: 'page' },
        { id: 'errors',       label: 'Errors',         kind: 'page' },
      ],
    },
    {
      id: 'infra', label: 'Infra', icon: '~',
      items: [
        { id: 'root',          label: 'Service root', method: 'GET',  path: '/' },
        { id: 'login',         label: 'Validate token', method: 'GET', path: '/login' },
        { id: 'search-legacy', label: 'Search (legacy)', method: 'POST', path: '/search' },
      ],
    },
    {
      id: 'tweets', label: 'Tweets', icon: '#',
      items: [
        { id: 'create-tweet',     label: 'Create tweet',        method: 'POST', path: '/2/tweets' },
        { id: 'bulk-tweets',      label: 'Bulk lookup',         method: 'GET',  path: '/2/tweets' },
        { id: 'tweet-by-id',      label: 'Get a tweet',         method: 'GET',  path: '/2/tweets/:id' },
        { id: 'delete-tweet',     label: 'Delete tweet',        method: 'DEL',  path: '/2/tweets/:id' },
        { id: 'tweet-detail',     label: 'Tweet + replies',     method: 'GET',  path: '/2/tweets/:id/detail' },
        { id: 'hide-reply',       label: 'Hide / unhide reply', method: 'PUT',  path: '/2/tweets/:id/hidden' },
        { id: 'liking-users',     label: 'Liking users',        method: 'GET',  path: '/2/tweets/:id/liking_users' },
        { id: 'retweeted-by',     label: 'Retweeted by',        method: 'GET',  path: '/2/tweets/:id/retweeted_by' },
        { id: 'tweet-retweets',   label: 'Retweets',            method: 'GET',  path: '/2/tweets/:id/retweets' },
        { id: 'quote-tweets',     label: 'Quote tweets',        method: 'GET',  path: '/2/tweets/:id/quote_tweets' },
        { id: 'recent-search',    label: 'Search recent',       method: 'GET',  path: '/2/tweets/search/recent' },
        { id: 'like-tweet',       label: 'Like',                method: 'POST', path: '/2/users/:user_id/likes' },
        { id: 'unlike-tweet',     label: 'Unlike',              method: 'DEL',  path: '/2/users/:user_id/likes/:tweet_id' },
        { id: 'retweet',          label: 'Retweet',             method: 'POST', path: '/2/users/:user_id/retweets' },
        { id: 'unretweet',        label: 'Unretweet',           method: 'DEL',  path: '/2/users/:user_id/retweets/by/source_tweet_id/:source_tweet_id' },
      ],
    },
    {
      id: 'users', label: 'Users', icon: '@',
      items: [
        { id: 'me',                    label: 'Authenticated user',     method: 'GET',  path: '/2/users/me' },
        { id: 'lookup-user',           label: 'Lookup by username',     method: 'GET',  path: '/2/users/by/username/:username' },
        { id: 'lookup-users',          label: 'Bulk lookup by handle',  method: 'GET',  path: '/2/users/by' },
        { id: 'bulk-users',            label: 'Bulk lookup by id',      method: 'GET',  path: '/2/users' },
        { id: 'user-by-id',            label: 'Get user by id',         method: 'GET',  path: '/2/users/:id' },
        { id: 'user-search',           label: 'Search users',           method: 'GET',  path: '/2/users/search' },
        { id: 'user-tweets',           label: 'User tweets',            method: 'GET',  path: '/2/users/:id/tweets' },
        { id: 'user-tweets-replies',   label: 'User tweets + replies',  method: 'GET',  path: '/2/users/:id/tweets/replies' },
        { id: 'user-mentions',         label: 'User mentions',          method: 'GET',  path: '/2/users/:id/mentions' },
        { id: 'user-media',            label: 'User media',             method: 'GET',  path: '/2/users/:id/media' },
        { id: 'user-liked',            label: 'Liked tweets',           method: 'GET',  path: '/2/users/:id/liked_tweets' },
        { id: 'user-followers',        label: 'Followers',              method: 'GET',  path: '/2/users/:id/followers' },
        { id: 'user-following',        label: 'Following',              method: 'GET',  path: '/2/users/:id/following' },
        { id: 'follow-user',           label: 'Follow user',            method: 'POST', path: '/2/users/:id/following' },
        { id: 'unfollow-user',         label: 'Unfollow user',          method: 'DEL',  path: '/2/users/:src/following/:tgt' },
        { id: 'user-blocking',         label: 'Blocking list',          method: 'GET',  path: '/2/users/:id/blocking' },
        { id: 'block-user',            label: 'Block user',             method: 'POST', path: '/2/users/:id/blocking' },
        { id: 'unblock-user',          label: 'Unblock user',           method: 'DEL',  path: '/2/users/:src/blocking/:tgt' },
        { id: 'user-muting',           label: 'Muting list',            method: 'GET',  path: '/2/users/:id/muting' },
        { id: 'mute-user',             label: 'Mute user',              method: 'POST', path: '/2/users/:id/muting' },
        { id: 'unmute-user',           label: 'Unmute user',            method: 'DEL',  path: '/2/users/:src/muting/:tgt' },
        { id: 'pin-tweet',             label: 'Pin tweet',              method: 'POST', path: '/2/users/:id/pinned_tweets' },
        { id: 'unpin-tweet',           label: 'Unpin tweet',            method: 'DEL',  path: '/2/users/:id/pinned_tweets/:tweet_id' },
        { id: 'reposts-of-me',         label: 'Reposts of me',          method: 'GET',  path: '/2/users/reposts_of_me' },
        { id: 'user-affiliates',       label: 'Affiliates',             method: 'GET',  path: '/2/users/:id/affiliates' },
      ],
    },
    {
      id: 'timelines', label: 'Timelines', icon: '=',
      items: [
        { id: 'home-timeline',  label: 'Home timeline',          method: 'GET', path: '/2/home_timeline' },
        { id: 'reverse-chrono', label: 'Reverse chronological',  method: 'GET', path: '/2/users/:id/timelines/reverse_chronological' },
      ],
    },
    {
      id: 'lists', label: 'Lists', icon: '+',
      items: [
        { id: 'list-create',        label: 'Create list',         method: 'POST', path: '/2/lists' },
        { id: 'list-get',           label: 'Get list',            method: 'GET',  path: '/2/lists/:id' },
        { id: 'list-update',        label: 'Update list',         method: 'PUT',  path: '/2/lists/:id' },
        { id: 'list-delete',        label: 'Delete list',         method: 'DEL',  path: '/2/lists/:id' },
        { id: 'list-by-owner',      label: 'Lists by owner',      method: 'GET',  path: '/2/lists/by/owner/:user_id' },
        { id: 'list-followers',     label: 'List followers',      method: 'GET',  path: '/2/lists/:id/followers' },
        { id: 'list-members',       label: 'List members',        method: 'GET',  path: '/2/lists/:id/members' },
        { id: 'list-add-member',    label: 'Add member',          method: 'POST', path: '/2/lists/:id/members' },
        { id: 'list-remove-member', label: 'Remove member',       method: 'DEL',  path: '/2/lists/:id/members/:user_id' },
        { id: 'list-pin',           label: 'Pin list',            method: 'POST', path: '/2/lists/:id/pinned' },
        { id: 'list-unpin',         label: 'Unpin list',          method: 'DEL',  path: '/2/lists/:id/pinned' },
        { id: 'list-tweets',        label: 'List tweets',         method: 'GET',  path: '/2/lists/:id/tweets' },
        { id: 'list-followed',      label: 'Followed lists',      method: 'GET',  path: '/2/users/:id/followed_lists' },
        { id: 'list-follow',        label: 'Follow list',         method: 'POST', path: '/2/users/:id/followed_lists' },
        { id: 'list-unfollow',      label: 'Unfollow list',       method: 'DEL',  path: '/2/users/:id/followed_lists/:list_id' },
        { id: 'list-memberships',   label: 'List memberships',    method: 'GET',  path: '/2/users/:id/list_memberships' },
        { id: 'list-owned',         label: 'Owned lists',         method: 'GET',  path: '/2/users/:id/owned_lists' },
        { id: 'list-pinned',        label: 'Pinned lists',        method: 'GET',  path: '/2/users/:id/pinned_lists' },
      ],
    },
    {
      id: 'bookmarks', label: 'Bookmarks', icon: '*',
      items: [
        { id: 'bookmarks-list',    label: 'Bookmarks',         method: 'GET',  path: '/2/users/:id/bookmarks' },
        { id: 'bookmark-add',      label: 'Add bookmark',      method: 'POST', path: '/2/users/:id/bookmarks' },
        { id: 'bookmark-folders',  label: 'Folders',           method: 'GET',  path: '/2/users/:id/bookmarks/folders' },
        { id: 'bookmark-folder',   label: 'Folder bookmarks',  method: 'GET',  path: '/2/users/:id/bookmarks/folders/:folder_id' },
        { id: 'bookmark-remove',   label: 'Remove bookmark',   method: 'DEL',  path: '/2/users/:id/bookmarks/:tweet_id' },
      ],
    },
    {
      id: 'dm', label: 'Direct messages', icon: '>',
      items: [
        { id: 'dm-send',          label: 'Send message',        method: 'POST', path: '/2/dm_conversations/with/:participant_id/messages' },
        { id: 'dm-conv-create',   label: 'Create conversation', method: 'POST', path: '/2/dm_conversations' },
        { id: 'dm-events',        label: 'List events',         method: 'GET',  path: '/2/dm_events' },
        { id: 'dm-events-conv',   label: 'Conversation events', method: 'GET',  path: '/2/dm_conversations/:id/dm_events' },
        { id: 'dm-events-with',   label: 'Events with user',    method: 'GET',  path: '/2/dm_conversations/with/:participant_id/dm_events' },
        { id: 'dm-event-get',     label: 'Get event',           method: 'GET',  path: '/2/dm_events/:event_id' },
        { id: 'dm-event-delete',  label: 'Delete event',        method: 'DEL',  path: '/2/dm_events/:event_id' },
        { id: 'dm-block',         label: 'Block from DM',       method: 'POST', path: '/2/users/:id/dm/block' },
        { id: 'dm-unblock',       label: 'Unblock from DM',     method: 'POST', path: '/2/users/:id/dm/unblock' },
        { id: 'chat-conv-list',   label: 'Chat conversations',  method: 'GET',  path: '/2/chat/conversations' },
      ],
    },
    {
      id: 'communities', label: 'Communities', icon: '%',
      items: [
        { id: 'community-search', label: 'Search communities', method: 'GET', path: '/2/communities/search' },
        { id: 'community-get',    label: 'Get community',      method: 'GET', path: '/2/communities/:id' },
      ],
    },
    {
      id: 'spaces', label: 'Spaces', icon: '^',
      items: [
        { id: 'spaces-bulk',     label: 'Bulk lookup',     method: 'GET', path: '/2/spaces' },
        { id: 'spaces-creator',  label: 'By creator',      method: 'GET', path: '/2/spaces/by/creator_ids' },
        { id: 'spaces-search',   label: 'Search spaces',   method: 'GET', path: '/2/spaces/search' },
        { id: 'space-get',       label: 'Get space',       method: 'GET', path: '/2/spaces/:id' },
        { id: 'space-buyers',    label: 'Ticket buyers',   method: 'GET', path: '/2/spaces/:id/buyers' },
        { id: 'space-tweets',    label: 'Space tweets',    method: 'GET', path: '/2/spaces/:id/tweets' },
      ],
    },
    {
      id: 'birdwatch', label: 'Community Notes', icon: '!',
      items: [
        { id: 'note-create',     label: 'Submit note',         method: 'POST', path: '/2/notes' },
        { id: 'note-evaluate',   label: 'Evaluate note',       method: 'POST', path: '/2/evaluate_note' },
        { id: 'notes-written',   label: 'Notes I wrote',       method: 'GET',  path: '/2/notes/search/notes_written' },
        { id: 'notes-eligible',  label: 'Posts eligible',      method: 'GET',  path: '/2/notes/search/posts_eligible_for_notes' },
        { id: 'note-delete',     label: 'Delete note',         method: 'DEL',  path: '/2/notes/:id' },
      ],
    },
    {
      id: 'trends', label: 'Trends', icon: '&',
      items: [
        { id: 'trends-global',       label: 'Trends',              method: 'GET', path: '/2/trends' },
        { id: 'trends-woeid',        label: 'Trends by WOEID',     method: 'GET', path: '/2/trends/by/woeid/:woeid' },
        { id: 'trends-personalized', label: 'Personalized',        method: 'GET', path: '/2/users/personalized_trends' },
      ],
    },
    {
      id: 'media', label: 'Media', icon: '$',
      items: [
        { id: 'media-upload',     label: 'Simple upload',  method: 'POST', path: '/2/media/upload' },
        { id: 'media-init',       label: 'Init upload',    method: 'POST', path: '/2/media/upload/initialize' },
        { id: 'media-append',     label: 'Append chunk',   method: 'POST', path: '/2/media/upload/:id/append' },
        { id: 'media-finalize',   label: 'Finalize',       method: 'POST', path: '/2/media/upload/:id/finalize' },
        { id: 'media-metadata',   label: 'Set metadata',   method: 'POST', path: '/2/media/metadata' },
      ],
    },
    {
      id: 'meta', label: 'Operations', icon: '?',
      items: [
        { id: 'admin-stats', label: 'Admin stats',  kind: 'page' },
        { id: 'rate-limits', label: 'Rate limits',  kind: 'page' },
        { id: 'changelog',   label: 'Changelog',    kind: 'page' },
      ],
    },
  ];

  // ─────────── Detailed endpoint definitions ───────────
  const COMMON_AUTH = 'Cookie auth_token via `Authorization: Bearer <auth_token>` atau `?auth_token=`';
  const COMMON_SCOPE = ['cookie:auth_token'];
  const COMMON_HEADERS = {
    'content-type': 'application/json',
    'x-engine': 'graphql',
    'x-cache': 'miss',
  };

  // ─────────── Helpers untuk batch endpoint definitions ───────────
  const ERR_401 = '{\n  "title": "Unauthorized",\n  "detail": "auth_token missing or invalid",\n  "status": 401\n}';
  const ERR_501 = '{\n  "title": "Not Implemented",\n  "detail": "Butuh OAuth2 user-context / dev portal subscription. Belum tersedia di mirror cookie.",\n  "type": "not_implemented",\n  "status": 501\n}';
  const ERR_502 = '{\n  "title": "Upstream Error",\n  "detail": "Upstream X GraphQL/REST returned error or Playwright timeout",\n  "status": 502\n}';

  // common reusable param sets
  const P_PAGINATION = [
    { name: 'max_results',      loc: 'query', type: 'integer', required: false, desc: '1-100. Default 20.' },
    { name: 'pagination_token', loc: 'query', type: 'string',  required: false, desc: 'Cursor dari response sebelumnya.' },
  ];
  const P_RAW = { name: 'raw', loc: 'query', type: 'integer', required: false, desc: '`1` untuk bypass formatter v2.' };

  function _mkExamples(method, path, body) {
    const m = method === 'DEL' ? 'DELETE' : method;
    const ml = m.toLowerCase();
    const hasBody = (m === 'POST' || m === 'PUT') && Array.isArray(body) && body.length > 0;
    const sample = hasBody
      ? body.reduce((o, p) => { o[p.name] = p.example !== undefined ? p.example : (p.type === 'integer' ? 1 : (p.type.endsWith('[]') ? [] : '...')); return o; }, {})
      : null;
    const sampleJSON = sample ? JSON.stringify(sample) : null;
    const samplePy = sample ? JSON.stringify(sample).replace(/"/g, '"').replace(/null/g, 'None').replace(/true/g, 'True').replace(/false/g, 'False') : null;

    if (hasBody) {
      return {
        curl: `curl -X ${m} "${BASE}${path}" \\
  -H "Authorization: Bearer $AUTH_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '${sampleJSON}'`,
        javascript: `await fetch("${BASE}${path}", {
  method: "${m}",
  headers: {
    "Authorization": \`Bearer \${process.env.AUTH_TOKEN}\`,
    "Content-Type": "application/json",
  },
  body: JSON.stringify(${sampleJSON}),
});`,
        python: `import os, requests
requests.${ml}(
    "${BASE}${path}",
    headers={"Authorization": f"Bearer {os.environ['AUTH_TOKEN']}"},
    json=${samplePy},
)`,
      };
    }
    return {
      curl: `curl -X ${m} "${BASE}${path}" \\
  -H "Authorization: Bearer $AUTH_TOKEN"`,
      javascript: `const res = await fetch("${BASE}${path}", {
  method: "${m}",
  headers: { "Authorization": \`Bearer \${process.env.AUTH_TOKEN}\` },
});`,
      python: `import os, requests
res = requests.${ml}(
    "${BASE}${path}",
    headers={"Authorization": f"Bearer {os.environ['AUTH_TOKEN']}"},
)`,
    };
  }

  function ep(spec) {
    const status = spec.status || 200;
    const okBody = spec.ok || '{\n  "data": {}\n}';
    const headers = { ...COMMON_HEADERS };
    if (spec.op) headers['x-graphql-op'] = spec.op;
    if (spec.engine) headers['x-engine'] = spec.engine;
    const responses = spec.stub
      ? [{ code: 501, label: 'Not Implemented', body: ERR_501 }]
      : [
          { code: status, label: status === 201 ? 'Created' : (status === 200 ? 'OK' : String(status)), body: okBody },
          { code: 401, label: 'Invalid token', body: ERR_401 },
          ...(spec.errors || []),
        ];
    return {
      method: spec.method,
      path: spec.path,
      name: spec.name,
      summary: spec.summary,
      auth: COMMON_AUTH,
      scope: COMMON_SCOPE,
      params: spec.params,
      body: spec.body,
      responses,
      examples: spec.examples || _mkExamples(spec.method, spec.path, spec.body),
      mockOk: { status, headers, body: okBody },
    };
  }

  const endpoints = {
    // ── Infra ──────────────────────────────────────────────────────────────
    'login': {
      method: 'GET', path: '/login', name: 'Validate auth_token',
      summary: 'Verifikasi cookie auth_token dengan call ke `/1.1/account/settings.json`. Return profil + screen_name kalau valid, `401` kalau expired.',
      auth: 'Public — cookie ditaruh di query.',
      scope: ['public'],
      params: [
        { name: 'auth_token', loc: 'query', type: 'string', required: true, desc: 'Cookie `auth_token` dari sesi web x.com. Min 10 chars.' },
      ],
      responses: [
        { code: 200, label: 'Valid',     body: '{\n  "status": "valid",\n  "user_id": "44196397",\n  "screen_name": "elonmusk",\n  "name": "Elon Musk",\n  "verified": true\n}' },
        { code: 401, label: 'Invalid',   body: '{\n  "status": "invalid",\n  "error": "auth_token expired or revoked"\n}' },
        { code: 502, label: 'Upstream',  body: '{\n  "status": "error",\n  "error": "Upstream request failed: ConnectTimeout"\n}' },
      ],
      examples: {
        curl: `curl "${BASE}/login?auth_token=$AUTH_TOKEN"`,
        javascript: `const res = await fetch(\`${BASE}/login?auth_token=\${process.env.AUTH_TOKEN}\`);
const profile = await res.json();
console.log(profile.screen_name);`,
        python: `import os, requests
res = requests.get(
    "${BASE}/login",
    params={"auth_token": os.environ["AUTH_TOKEN"]},
)
print(res.json())`,
      },
      mockOk: {
        status: 200,
        headers: { ...COMMON_HEADERS },
        body: '{\n  "status": "valid",\n  "user_id": "44196397",\n  "screen_name": "elonmusk",\n  "name": "Elon Musk",\n  "verified": true\n}',
      },
    },

    'root': {
      method: 'GET', path: '/', name: 'Service root',
      summary: 'Minimal banner dengan title, version, link ke `/docs`. Tidak meng-expose route inventory.',
      auth: 'Public.',
      scope: ['public'],
      responses: [
        { code: 200, label: 'OK', body: '{\n  "service": "X (Twitter) Cookie API",\n  "version": "2.3.0",\n  "docs": "/docs"\n}' },
      ],
      examples: {
        curl: `curl ${BASE}/`,
        javascript: `const res = await fetch("${BASE}/");\nconst info = await res.json();`,
        python: `import requests\nprint(requests.get("${BASE}/").json())`,
      },
      mockOk: {
        status: 200, headers: { ...COMMON_HEADERS },
        body: '{\n  "service": "X (Twitter) Cookie API",\n  "version": "2.3.0",\n  "docs": "/docs"\n}',
      },
    },

    'search-legacy': {
      method: 'POST', path: '/search', name: 'Search via Playwright (legacy)',
      summary: 'Endpoint awal sebelum mirror v2 lengkap. Pakai Playwright headless karena X selalu memblokir SearchTimeline httpx call. Latency ~3–6s. Untuk app baru pakai `GET /2/tweets/search/recent`.',
      auth: 'Public — auth_token di body.',
      scope: ['cookie:auth_token'],
      body: [
        { name: 'auth_token', type: 'string', required: true, desc: 'Cookie auth_token. Min 10 chars.' },
        { name: 'q',          type: 'string', required: true, desc: 'Keyword pencarian. Min 1 char.' },
        { name: 'type',       type: 'enum',   required: false, desc: '`Latest` (default) | `Top` | `People` | `Media`.' },
      ],
      responses: [
        { code: 200, label: 'OK',       body: '{\n  "engine": "playwright",\n  "status": "ok",\n  "query": { "q": "fastapi", "type": "Latest" },\n  "data": { "tweets": [/* … */] }\n}' },
        { code: 401, label: 'Invalid',  body: '{\n  "engine": "playwright",\n  "status": "invalid",\n  "error": "auth_token expired"\n}' },
        { code: 502, label: 'Upstream', body: '{\n  "status": "error",\n  "error": "Upstream request failed"\n}' },
      ],
      examples: {
        curl: `curl -X POST ${BASE}/search \\
  -H "Content-Type: application/json" \\
  -d '{"auth_token":"'"$AUTH_TOKEN"'","q":"fastapi","type":"Latest"}'`,
        javascript: `const res = await fetch("${BASE}/search", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    auth_token: process.env.AUTH_TOKEN,
    q: "fastapi",
    type: "Latest",
  }),
});`,
        python: `import os, requests
res = requests.post("${BASE}/search", json={
    "auth_token": os.environ["AUTH_TOKEN"],
    "q": "fastapi",
    "type": "Latest",
})`,
      },
      mockOk: {
        status: 200,
        headers: { ...COMMON_HEADERS, 'x-engine': 'playwright' },
        body: '{\n  "engine": "playwright",\n  "status": "ok",\n  "http_status": 200,\n  "query": { "q": "fastapi", "type": "Latest" },\n  "data": { "tweets": [] }\n}',
      },
    },

    // ── Tweets ─────────────────────────────────────────────────────────────
    'create-tweet': {
      method: 'POST', path: '/2/tweets', name: 'Create tweet',
      summary: 'Publish tweet baru. Mendukung reply, quote, dan attachment media (max 4 IDs). Kembalikan objek tweet hasil GraphQL `CreateTweet`.',
      auth: COMMON_AUTH, scope: COMMON_SCOPE,
      body: [
        { name: 'text',           type: 'string',   required: true,  desc: 'Body tweet. Max 4000 chars (verified) atau 280 chars default.' },
        { name: 'reply_to',       type: 'string',   required: false, desc: 'Tweet ID yang di-reply.' },
        { name: 'quote_tweet_id', type: 'string',   required: false, desc: 'Tweet ID yang di-quote (akan di-attach sebagai URL).' },
        { name: 'media_ids',      type: 'string[]', required: false, desc: 'Up to 4 media IDs dari `/2/media/upload/finalize`.' },
      ],
      responses: [
        { code: 200, label: 'Created', body: '{\n  "data": {\n    "create_tweet": {\n      "tweet_results": {\n        "result": {\n          "rest_id": "1786394285310038016",\n          "legacy": { "full_text": "hello world", "created_at": "Thu May 17 09:14:00 +0000 2026" }\n        }\n      }\n    }\n  }\n}' },
        { code: 401, label: 'Invalid token', body: '{\n  "title": "Unauthorized",\n  "detail": "auth_token missing or invalid",\n  "type": "invalid_token",\n  "status": 401\n}' },
        { code: 502, label: 'Upstream', body: '{\n  "title": "Upstream Error",\n  "detail": "GraphQL CreateTweet returned 503",\n  "status": 502\n}' },
      ],
      examples: {
        curl: `curl -X POST "${BASE}/2/tweets" \\
  -H "Authorization: Bearer $AUTH_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"text":"hello from xapi"}'`,
        javascript: `const res = await fetch("${BASE}/2/tweets", {
  method: "POST",
  headers: {
    "Authorization": \`Bearer \${process.env.AUTH_TOKEN}\`,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({ text: "hello from xapi" }),
});
const { data } = await res.json();`,
        python: `import os, requests
res = requests.post(
    "${BASE}/2/tweets",
    headers={"Authorization": f"Bearer {os.environ['AUTH_TOKEN']}"},
    json={"text": "hello from xapi"},
)
print(res.json())`,
      },
      mockOk: {
        status: 200,
        headers: { ...COMMON_HEADERS, 'x-graphql-op': 'CreateTweet' },
        body: '{\n  "data": {\n    "create_tweet": {\n      "tweet_results": {\n        "result": {\n          "rest_id": "1786394285310038016"\n        }\n      }\n    }\n  }\n}',
      },
    },

    'tweet-by-id': {
      method: 'GET', path: '/2/tweets/:id', name: 'Get a tweet',
      summary: 'Fetch single tweet by ID. Mirror `TweetResultByRestId`.',
      auth: COMMON_AUTH, scope: COMMON_SCOPE,
      params: [
        { name: 'tweet_id', loc: 'path',  type: 'string', required: true,  desc: 'Numeric tweet ID. Pattern `^\\d+$`.' },
        { name: 'raw',      loc: 'query', type: 'integer', required: false, desc: '`1` untuk bypass formatter v2 dan return raw GraphQL payload.' },
      ],
      responses: [
        { code: 200, label: 'OK',         body: '{\n  "data": {\n    "id": "1786394285310038016",\n    "text": "hello world",\n    "author_id": "44196397",\n    "created_at": "2026-05-17T09:14:00Z",\n    "public_metrics": { "like_count": 12, "reply_count": 0, "retweet_count": 1 }\n  }\n}' },
        { code: 401, label: 'Invalid',    body: '{\n  "title": "Unauthorized",\n  "status": 401\n}' },
        { code: 404, label: 'Not found',  body: '{\n  "title": "Not Found",\n  "detail": "tweet 999 not found or deleted",\n  "status": 404\n}' },
      ],
      examples: {
        curl: `curl "${BASE}/2/tweets/1786394285310038016" \\
  -H "Authorization: Bearer $AUTH_TOKEN"`,
        javascript: `const res = await fetch("${BASE}/2/tweets/1786394285310038016", {
  headers: { "Authorization": \`Bearer \${process.env.AUTH_TOKEN}\` },
});`,
        python: `import os, requests
res = requests.get(
    "${BASE}/2/tweets/1786394285310038016",
    headers={"Authorization": f"Bearer {os.environ['AUTH_TOKEN']}"},
)`,
      },
      mockOk: {
        status: 200,
        headers: { ...COMMON_HEADERS, 'x-graphql-op': 'TweetResultByRestId' },
        body: '{\n  "data": {\n    "id": "1786394285310038016",\n    "text": "hello world",\n    "author_id": "44196397",\n    "public_metrics": { "like_count": 12 }\n  }\n}',
      },
    },

    'bulk-tweets': {
      method: 'GET', path: '/2/tweets', name: 'Bulk tweet lookup',
      summary: 'Fan-out paralel ke `TweetResultByRestId` untuk daftar ID. Max 100 per call. Hasil di-merge dengan `data` + `includes` (users, media, refs).',
      auth: COMMON_AUTH, scope: COMMON_SCOPE,
      params: [
        { name: 'ids', loc: 'query', type: 'string', required: true, desc: 'Comma-separated tweet IDs. Max 100 entries.' },
        { name: 'raw', loc: 'query', type: 'integer', required: false, desc: '`1` untuk return raw GraphQL responses.' },
      ],
      responses: [
        { code: 200, label: 'OK',  body: '{\n  "data": [\n    { "id": "111", "text": "first" },\n    { "id": "222", "text": "second" }\n  ],\n  "includes": {\n    "users": [{ "id": "44196397", "username": "elonmusk" }]\n  },\n  "meta": { "result_count": 2 }\n}' },
        { code: 400, label: 'Bad request', body: '{\n  "title": "Bad Request",\n  "detail": "ids kosong",\n  "status": 400\n}' },
      ],
      examples: {
        curl: `curl "${BASE}/2/tweets?ids=111,222,333" \\
  -H "Authorization: Bearer $AUTH_TOKEN"`,
        javascript: `const url = new URL("${BASE}/2/tweets");
url.searchParams.set("ids", "111,222,333");
const res = await fetch(url, {
  headers: { "Authorization": \`Bearer \${process.env.AUTH_TOKEN}\` },
});`,
        python: `import os, requests
res = requests.get(
    "${BASE}/2/tweets",
    params={"ids": "111,222,333"},
    headers={"Authorization": f"Bearer {os.environ['AUTH_TOKEN']}"},
)`,
      },
      mockOk: {
        status: 200,
        headers: { ...COMMON_HEADERS },
        body: '{\n  "data": [\n    { "id": "111", "text": "first" },\n    { "id": "222", "text": "second" }\n  ],\n  "meta": { "result_count": 2 }\n}',
      },
    },

    'recent-search': {
      method: 'GET', path: '/2/tweets/search/recent', name: 'Search recent tweets',
      summary: 'Search tweet 7 hari terakhir lewat Playwright (`SearchTimeline`). httpx engine sudah deprecated. Return `data` array hasil format v2.',
      auth: COMMON_AUTH, scope: COMMON_SCOPE,
      params: [
        { name: 'query',       loc: 'query', type: 'string',  required: true,  desc: 'Keyword pencarian.' },
        { name: 'max_results', loc: 'query', type: 'integer', required: false, desc: '1–100. Default 20.' },
        { name: 'next_token',  loc: 'query', type: 'string',  required: false, desc: 'Cursor dari response sebelumnya.' },
        { name: 'type',        loc: 'query', type: 'enum',    required: false, desc: '`Latest` (default) | `Top` | `People` | `Media`.' },
        { name: 'raw',         loc: 'query', type: 'integer', required: false, desc: '`1` untuk raw payload Playwright.' },
      ],
      responses: [
        { code: 200, label: 'OK',  body: '{\n  "data": [\n    { "id": "1786394285310038016", "text": "fastapi rocks" }\n  ],\n  "meta": { "result_count": 1, "next_token": "scroll:abc..." }\n}' },
        { code: 502, label: 'Upstream', body: '{\n  "title": "Upstream Error",\n  "detail": "Playwright timeout",\n  "status": 502\n}' },
      ],
      examples: {
        curl: `curl "${BASE}/2/tweets/search/recent?query=fastapi&max_results=25" \\
  -H "Authorization: Bearer $AUTH_TOKEN"`,
        javascript: `const url = new URL("${BASE}/2/tweets/search/recent");
url.searchParams.set("query", "fastapi");
url.searchParams.set("max_results", "25");
const res = await fetch(url, {
  headers: { "Authorization": \`Bearer \${process.env.AUTH_TOKEN}\` },
});`,
        python: `import os, requests
res = requests.get(
    "${BASE}/2/tweets/search/recent",
    params={"query": "fastapi", "max_results": 25},
    headers={"Authorization": f"Bearer {os.environ['AUTH_TOKEN']}"},
)`,
      },
      mockOk: {
        status: 200,
        headers: { ...COMMON_HEADERS, 'x-engine': 'playwright' },
        body: '{\n  "data": [\n    { "id": "1786394285310038016", "text": "fastapi rocks" }\n  ],\n  "meta": { "result_count": 1 }\n}',
      },
    },

    'delete-tweet': {
      method: 'DEL', path: '/2/tweets/:id', name: 'Delete tweet',
      summary: 'Hapus tweet milik authenticated user. Mirror `DeleteTweet` GraphQL.',
      auth: COMMON_AUTH, scope: COMMON_SCOPE,
      params: [
        { name: 'tweet_id', loc: 'path', type: 'string', required: true, desc: 'Tweet ID milik user.' },
      ],
      responses: [
        { code: 200, label: 'Deleted', body: '{\n  "data": { "delete_tweet": { "tweet_results": {} } }\n}' },
        { code: 401, label: 'Invalid', body: '{\n  "title": "Unauthorized",\n  "status": 401\n}' },
        { code: 403, label: 'Forbidden', body: '{\n  "title": "Forbidden",\n  "detail": "you don\'t own this tweet",\n  "status": 403\n}' },
      ],
      examples: {
        curl: `curl -X DELETE "${BASE}/2/tweets/1786394285310038016" \\
  -H "Authorization: Bearer $AUTH_TOKEN"`,
        javascript: `await fetch("${BASE}/2/tweets/1786394285310038016", {
  method: "DELETE",
  headers: { "Authorization": \`Bearer \${process.env.AUTH_TOKEN}\` },
});`,
        python: `import os, requests
requests.delete(
    "${BASE}/2/tweets/1786394285310038016",
    headers={"Authorization": f"Bearer {os.environ['AUTH_TOKEN']}"},
)`,
      },
      mockOk: {
        status: 200,
        headers: { ...COMMON_HEADERS, 'x-graphql-op': 'DeleteTweet' },
        body: '{\n  "data": { "delete_tweet": { "tweet_results": {} } }\n}',
      },
    },

    'like-tweet': {
      method: 'POST', path: '/2/users/:user_id/likes', name: 'Like tweet',
      summary: 'Like tweet via GraphQL `FavoriteTweet`. `user_id` di path harus sama dengan authenticated user ID.',
      auth: COMMON_AUTH, scope: COMMON_SCOPE,
      params: [
        { name: 'user_id', loc: 'path', type: 'string', required: true, desc: 'Authenticated user ID.' },
      ],
      body: [
        { name: 'tweet_id', type: 'string', required: true, desc: 'Tweet ID yang di-like.' },
      ],
      responses: [
        { code: 200, label: 'OK', body: '{\n  "data": { "favorite_tweet": "Done" }\n}' },
      ],
      examples: {
        curl: `curl -X POST "${BASE}/2/users/me/likes" \\
  -H "Authorization: Bearer $AUTH_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"tweet_id":"1786394285310038016"}'`,
        javascript: `await fetch(\`${BASE}/2/users/\${userId}/likes\`, {
  method: "POST",
  headers: {
    "Authorization": \`Bearer \${process.env.AUTH_TOKEN}\`,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({ tweet_id: "1786394285310038016" }),
});`,
        python: `import os, requests
requests.post(
    f"${BASE}/2/users/{user_id}/likes",
    headers={"Authorization": f"Bearer {os.environ['AUTH_TOKEN']}"},
    json={"tweet_id": "1786394285310038016"},
)`,
      },
      mockOk: {
        status: 200,
        headers: { ...COMMON_HEADERS, 'x-graphql-op': 'FavoriteTweet' },
        body: '{\n  "data": { "favorite_tweet": "Done" }\n}',
      },
    },

    'retweet': {
      method: 'POST', path: '/2/users/:user_id/retweets', name: 'Retweet',
      summary: 'Retweet via GraphQL `CreateRetweet`.',
      auth: COMMON_AUTH, scope: COMMON_SCOPE,
      params: [
        { name: 'user_id', loc: 'path', type: 'string', required: true, desc: 'Authenticated user ID.' },
      ],
      body: [
        { name: 'tweet_id', type: 'string', required: true, desc: 'Tweet ID yang di-retweet.' },
      ],
      responses: [
        { code: 200, label: 'OK', body: '{\n  "data": { "create_retweet": { "retweet_results": { "result": { "rest_id": "999" } } } }\n}' },
      ],
      examples: {
        curl: `curl -X POST "${BASE}/2/users/me/retweets" \\
  -H "Authorization: Bearer $AUTH_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"tweet_id":"1786394285310038016"}'`,
        javascript: `await fetch(\`${BASE}/2/users/\${userId}/retweets\`, {
  method: "POST",
  headers: {
    "Authorization": \`Bearer \${process.env.AUTH_TOKEN}\`,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({ tweet_id: "1786394285310038016" }),
});`,
        python: `import os, requests
requests.post(
    f"${BASE}/2/users/{user_id}/retweets",
    headers={"Authorization": f"Bearer {os.environ['AUTH_TOKEN']}"},
    json={"tweet_id": "1786394285310038016"},
)`,
      },
      mockOk: {
        status: 200,
        headers: { ...COMMON_HEADERS, 'x-graphql-op': 'CreateRetweet' },
        body: '{\n  "data": { "create_retweet": { "retweet_results": { "result": { "rest_id": "999" } } } }\n}',
      },
    },

    // ── Users ──────────────────────────────────────────────────────────────
    'me': {
      method: 'GET', path: '/2/users/me', name: 'Authenticated user',
      summary: 'Resolve user dari `twid` cookie + warm session. Return profil lengkap formatter v2.',
      auth: COMMON_AUTH, scope: COMMON_SCOPE,
      responses: [
        { code: 200, label: 'OK', body: '{\n  "data": {\n    "id": "44196397",\n    "username": "elonmusk",\n    "name": "Elon Musk",\n    "verified": true,\n    "public_metrics": { "followers_count": 219384921, "following_count": 822, "tweet_count": 56392 }\n  }\n}' },
        { code: 401, label: 'Invalid', body: '{\n  "title": "Unauthorized",\n  "status": 401\n}' },
      ],
      examples: {
        curl: `curl "${BASE}/2/users/me" \\
  -H "Authorization: Bearer $AUTH_TOKEN"`,
        javascript: `const res = await fetch("${BASE}/2/users/me", {
  headers: { "Authorization": \`Bearer \${process.env.AUTH_TOKEN}\` },
});`,
        python: `import os, requests
res = requests.get(
    "${BASE}/2/users/me",
    headers={"Authorization": f"Bearer {os.environ['AUTH_TOKEN']}"},
)`,
      },
      mockOk: {
        status: 200,
        headers: { ...COMMON_HEADERS, 'x-graphql-op': 'UserByRestId' },
        body: '{\n  "data": {\n    "id": "44196397",\n    "username": "elonmusk",\n    "name": "Elon Musk",\n    "verified": true\n  }\n}',
      },
    },

    'lookup-user': {
      method: 'GET', path: '/2/users/by/username/:username', name: 'Lookup by username',
      summary: 'Resolve handle → user object via `UserByScreenName`. Case-insensitive.',
      auth: COMMON_AUTH, scope: COMMON_SCOPE,
      params: [
        { name: 'username', loc: 'path', type: 'string', required: true, desc: 'Handle tanpa `@`. 1–15 char alphanumeric + underscore.' },
      ],
      responses: [
        { code: 200, label: 'OK',  body: '{\n  "data": {\n    "id": "44196397",\n    "name": "Elon Musk",\n    "username": "elonmusk",\n    "verified": true\n  }\n}' },
        { code: 404, label: 'Not found', body: '{\n  "title": "Not Found",\n  "detail": "user @ghost not found",\n  "status": 404\n}' },
      ],
      examples: {
        curl: `curl "${BASE}/2/users/by/username/elonmusk" \\
  -H "Authorization: Bearer $AUTH_TOKEN"`,
        javascript: `const res = await fetch("${BASE}/2/users/by/username/elonmusk", {
  headers: { "Authorization": \`Bearer \${process.env.AUTH_TOKEN}\` },
});`,
        python: `import os, requests
res = requests.get(
    "${BASE}/2/users/by/username/elonmusk",
    headers={"Authorization": f"Bearer {os.environ['AUTH_TOKEN']}"},
)`,
      },
      mockOk: {
        status: 200,
        headers: { ...COMMON_HEADERS, 'x-graphql-op': 'UserByScreenName' },
        body: '{\n  "data": {\n    "id": "44196397",\n    "name": "Elon Musk",\n    "username": "elonmusk",\n    "verified": true\n  }\n}',
      },
    },

    'follow-user': {
      method: 'POST', path: '/2/users/:id/following', name: 'Follow user',
      summary: 'Follow target via REST `friendships/create.json`.',
      auth: COMMON_AUTH, scope: COMMON_SCOPE,
      params: [
        { name: 'user_id', loc: 'path', type: 'string', required: true, desc: 'Authenticated user ID.' },
      ],
      body: [
        { name: 'target_user_id', type: 'string', required: true, desc: 'User ID yang mau di-follow.' },
      ],
      responses: [
        { code: 200, label: 'OK', body: '{\n  "data": { "following": true, "id": "12" }\n}' },
      ],
      examples: {
        curl: `curl -X POST "${BASE}/2/users/me/following" \\
  -H "Authorization: Bearer $AUTH_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"target_user_id":"12"}'`,
        javascript: `await fetch(\`${BASE}/2/users/\${userId}/following\`, {
  method: "POST",
  headers: {
    "Authorization": \`Bearer \${process.env.AUTH_TOKEN}\`,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({ target_user_id: "12" }),
});`,
        python: `import os, requests
requests.post(
    f"${BASE}/2/users/{user_id}/following",
    headers={"Authorization": f"Bearer {os.environ['AUTH_TOKEN']}"},
    json={"target_user_id": "12"},
)`,
      },
      mockOk: {
        status: 200,
        headers: { ...COMMON_HEADERS, 'x-engine': 'rest' },
        body: '{\n  "data": { "following": true, "id": "12" }\n}',
      },
    },

    'user-followers': {
      method: 'GET', path: '/2/users/:id/followers', name: 'Followers',
      summary: 'Followers list via GraphQL `Followers` (cursor pagination).',
      auth: COMMON_AUTH, scope: COMMON_SCOPE,
      params: [
        { name: 'user_id',          loc: 'path',  type: 'string',  required: true,  desc: 'Target user ID.' },
        { name: 'max_results',      loc: 'query', type: 'integer', required: false, desc: '1–100. Default 20.' },
        { name: 'pagination_token', loc: 'query', type: 'string',  required: false, desc: 'Cursor dari response sebelumnya.' },
      ],
      responses: [
        { code: 200, label: 'OK', body: '{\n  "data": [\n    { "id": "11", "username": "alice" },\n    { "id": "12", "username": "bob" }\n  ],\n  "meta": { "result_count": 2, "next_token": "0|1751456..." }\n}' },
      ],
      examples: {
        curl: `curl "${BASE}/2/users/44196397/followers?max_results=50" \\
  -H "Authorization: Bearer $AUTH_TOKEN"`,
        javascript: `const url = new URL(\`${BASE}/2/users/\${id}/followers\`);
url.searchParams.set("max_results", "50");
const res = await fetch(url, {
  headers: { "Authorization": \`Bearer \${process.env.AUTH_TOKEN}\` },
});`,
        python: `import os, requests
res = requests.get(
    f"${BASE}/2/users/{user_id}/followers",
    params={"max_results": 50},
    headers={"Authorization": f"Bearer {os.environ['AUTH_TOKEN']}"},
)`,
      },
      mockOk: {
        status: 200,
        headers: { ...COMMON_HEADERS, 'x-graphql-op': 'Followers' },
        body: '{\n  "data": [\n    { "id": "11", "username": "alice" }\n  ],\n  "meta": { "result_count": 1 }\n}',
      },
    },

    'user-tweets': {
      method: 'GET', path: '/2/users/:id/tweets', name: 'User tweets',
      summary: 'Timeline tweets user via `UserTweets`. Filter retweet & reply by default ada di formatter.',
      auth: COMMON_AUTH, scope: COMMON_SCOPE,
      params: [
        { name: 'user_id',          loc: 'path',  type: 'string',  required: true,  desc: 'Target user ID.' },
        { name: 'max_results',      loc: 'query', type: 'integer', required: false, desc: '1–100. Default 20.' },
        { name: 'pagination_token', loc: 'query', type: 'string',  required: false, desc: 'Cursor pagination.' },
      ],
      responses: [
        { code: 200, label: 'OK', body: '{\n  "data": [\n    { "id": "111", "text": "first" }\n  ],\n  "meta": { "result_count": 1 }\n}' },
      ],
      examples: {
        curl: `curl "${BASE}/2/users/44196397/tweets" \\
  -H "Authorization: Bearer $AUTH_TOKEN"`,
        javascript: `const res = await fetch(\`${BASE}/2/users/\${id}/tweets\`, {
  headers: { "Authorization": \`Bearer \${process.env.AUTH_TOKEN}\` },
});`,
        python: `import os, requests
res = requests.get(
    f"${BASE}/2/users/{user_id}/tweets",
    headers={"Authorization": f"Bearer {os.environ['AUTH_TOKEN']}"},
)`,
      },
      mockOk: {
        status: 200,
        headers: { ...COMMON_HEADERS, 'x-graphql-op': 'UserTweets' },
        body: '{\n  "data": [\n    { "id": "111", "text": "first" }\n  ],\n  "meta": { "result_count": 1 }\n}',
      },
    },

    // ── Timelines ──────────────────────────────────────────────────────────
    'home-timeline': {
      method: 'GET', path: '/2/home_timeline', name: 'Home timeline',
      summary: 'For-You / Following timeline authenticated user via `HomeTimeline` / `HomeLatestTimeline`.',
      auth: COMMON_AUTH, scope: COMMON_SCOPE,
      params: [
        { name: 'max_results',      loc: 'query', type: 'integer', required: false, desc: '1–100. Default 20.' },
        { name: 'pagination_token', loc: 'query', type: 'string',  required: false, desc: 'Cursor pagination.' },
      ],
      responses: [
        { code: 200, label: 'OK', body: '{\n  "data": [\n    { "id": "111", "text": "ranked tweet", "author_id": "12" }\n  ],\n  "meta": { "result_count": 1, "next_token": "DAACCgQB..." }\n}' },
      ],
      examples: {
        curl: `curl "${BASE}/2/home_timeline" \\
  -H "Authorization: Bearer $AUTH_TOKEN"`,
        javascript: `const res = await fetch("${BASE}/2/home_timeline", {
  headers: { "Authorization": \`Bearer \${process.env.AUTH_TOKEN}\` },
});`,
        python: `import os, requests
res = requests.get(
    "${BASE}/2/home_timeline",
    headers={"Authorization": f"Bearer {os.environ['AUTH_TOKEN']}"},
)`,
      },
      mockOk: {
        status: 200,
        headers: { ...COMMON_HEADERS, 'x-graphql-op': 'HomeTimeline' },
        body: '{\n  "data": [\n    { "id": "111", "text": "ranked tweet" }\n  ],\n  "meta": { "result_count": 1 }\n}',
      },
    },

    // ── DM ─────────────────────────────────────────────────────────────────
    'dm-send': {
      method: 'POST', path: '/2/dm_conversations/with/:participant_id/messages', name: 'Send DM',
      summary: 'Kirim DM ke user. Otomatis resolve / create conversation. Mendukung text + media.',
      auth: COMMON_AUTH, scope: COMMON_SCOPE,
      params: [
        { name: 'participant_id', loc: 'path', type: 'string', required: true, desc: 'Target user ID.' },
      ],
      body: [
        { name: 'text',         type: 'string', required: false, desc: 'Body pesan. Wajib ada salah satu (`text` atau `media_id`).' },
        { name: 'attachments',  type: 'object[]', required: false, desc: 'Array `{ media_id }`.' },
      ],
      responses: [
        { code: 200, label: 'OK', body: '{\n  "data": {\n    "dm_event_id": "1786394285310038016",\n    "dm_conversation_id": "44196397-12"\n  }\n}' },
      ],
      examples: {
        curl: `curl -X POST "${BASE}/2/dm_conversations/with/12/messages" \\
  -H "Authorization: Bearer $AUTH_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"text":"hello"}'`,
        javascript: `await fetch(\`${BASE}/2/dm_conversations/with/\${participantId}/messages\`, {
  method: "POST",
  headers: {
    "Authorization": \`Bearer \${process.env.AUTH_TOKEN}\`,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({ text: "hello" }),
});`,
        python: `import os, requests
requests.post(
    f"${BASE}/2/dm_conversations/with/{participant_id}/messages",
    headers={"Authorization": f"Bearer {os.environ['AUTH_TOKEN']}"},
    json={"text": "hello"},
)`,
      },
      mockOk: {
        status: 200,
        headers: { ...COMMON_HEADERS, 'x-engine': 'dm' },
        body: '{\n  "data": {\n    "dm_event_id": "1786394285310038016",\n    "dm_conversation_id": "44196397-12"\n  }\n}',
      },
    },

    // ── Trends ─────────────────────────────────────────────────────────────
    'trends-global': {
      method: 'GET', path: '/2/trends', name: 'Trends',
      summary: 'Global / personalized trending topics. Pakai `TrendsByDeviceFn` / `TrendsByPlace`.',
      auth: COMMON_AUTH, scope: COMMON_SCOPE,
      params: [
        { name: 'count', loc: 'query', type: 'integer', required: false, desc: 'Jumlah item. Default 50.' },
      ],
      responses: [
        { code: 200, label: 'OK', body: '{\n  "data": [\n    { "name": "#FastAPI", "tweet_volume": 12_842 },\n    { "name": "Bali", "tweet_volume": 4_201 }\n  ]\n}' },
      ],
      examples: {
        curl: `curl "${BASE}/2/trends" \\
  -H "Authorization: Bearer $AUTH_TOKEN"`,
        javascript: `const res = await fetch("${BASE}/2/trends", {
  headers: { "Authorization": \`Bearer \${process.env.AUTH_TOKEN}\` },
});`,
        python: `import os, requests
res = requests.get(
    "${BASE}/2/trends",
    headers={"Authorization": f"Bearer {os.environ['AUTH_TOKEN']}"},
)`,
      },
      mockOk: {
        status: 200,
        headers: { ...COMMON_HEADERS },
        body: '{\n  "data": [\n    { "name": "#FastAPI", "tweet_volume": 12842 }\n  ]\n}',
      },
    },

    // ── Media ──────────────────────────────────────────────────────────────
    'media-init': {
      method: 'POST', path: '/2/media/upload/initialize', name: 'Initialize media upload',
      summary: 'Step 1 chunked upload. Reserve `media_id` based on size + media_type.',
      auth: COMMON_AUTH, scope: COMMON_SCOPE,
      body: [
        { name: 'total_bytes',     type: 'integer', required: true,  desc: 'Total bytes file.' },
        { name: 'media_type',      type: 'string',  required: true,  desc: 'MIME type, mis. `image/png`, `video/mp4`.' },
        { name: 'media_category',  type: 'enum',    required: false, desc: '`tweet_image` | `tweet_video` | `tweet_gif` | `dm_image` | `dm_video`.' },
      ],
      responses: [
        { code: 200, label: 'OK', body: '{\n  "data": {\n    "media_id": 1786394285310038016,\n    "media_id_string": "1786394285310038016",\n    "expires_after_secs": 86400\n  }\n}' },
      ],
      examples: {
        curl: `curl -X POST "${BASE}/2/media/upload/initialize" \\
  -H "Authorization: Bearer $AUTH_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"total_bytes":204800,"media_type":"image/png"}'`,
        javascript: `await fetch("${BASE}/2/media/upload/initialize", {
  method: "POST",
  headers: {
    "Authorization": \`Bearer \${process.env.AUTH_TOKEN}\`,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({ total_bytes: 204800, media_type: "image/png" }),
});`,
        python: `import os, requests
requests.post(
    "${BASE}/2/media/upload/initialize",
    headers={"Authorization": f"Bearer {os.environ['AUTH_TOKEN']}"},
    json={"total_bytes": 204800, "media_type": "image/png"},
)`,
      },
      mockOk: {
        status: 200,
        headers: { ...COMMON_HEADERS, 'x-engine': 'upload' },
        body: '{\n  "data": {\n    "media_id_string": "1786394285310038016",\n    "expires_after_secs": 86400\n  }\n}',
      },
    },
  };

  // ─────────── Bulk-defined endpoints (compact via ep() helper) ───────────
  Object.assign(endpoints, {
    // ── Tweets (sisanya) ─────────────────────────────────────────
    'tweet-detail': ep({
      method: 'GET', path: '/2/tweets/:id/detail', name: 'Tweet detail + replies',
      summary: 'Mirror `TweetDetail` GraphQL — return tweet + thread replies. Cursor-paged.',
      params: [
        { name: 'tweet_id', loc: 'path',  type: 'string', required: true, desc: 'Numeric tweet ID.' },
        { name: 'cursor',   loc: 'query', type: 'string', required: false, desc: 'Pagination cursor.' },
        P_RAW,
      ],
      op: 'TweetDetail',
      ok: '{\n  "data": [\n    { "id": "111", "text": "root", "author_id": "12" }\n  ],\n  "includes": { "users": [] },\n  "meta": { "result_count": 1 }\n}',
    }),
    'hide-reply': ep({
      method: 'PUT', path: '/2/tweets/:id/hidden', name: 'Hide / unhide reply',
      summary: 'Toggle hidden state pada reply via `ModerateTweet`. Hanya author thread asli yang bisa.',
      params: [
        { name: 'tweet_id', loc: 'path', type: 'string', required: true, desc: 'Reply tweet ID.' },
      ],
      op: 'ModerateTweet',
      ok: '{\n  "data": { "moderate_tweet": { "tweet_results": {} } }\n}',
    }),
    'liking-users': ep({
      method: 'GET', path: '/2/tweets/:id/liking_users', name: 'Liking users',
      summary: 'List user yang me-like tweet — `Favoriters` GraphQL.',
      params: [
        { name: 'tweet_id', loc: 'path', type: 'string', required: true, desc: 'Tweet ID.' },
        ...P_PAGINATION,
        P_RAW,
      ],
      op: 'Favoriters',
      ok: '{\n  "data": [\n    { "id": "11", "username": "alice" }\n  ],\n  "meta": { "result_count": 1 }\n}',
    }),
    'retweeted-by': ep({
      method: 'GET', path: '/2/tweets/:id/retweeted_by', name: 'Retweeted by',
      summary: 'List user yang retweet — `Retweeters`.',
      params: [
        { name: 'tweet_id', loc: 'path', type: 'string', required: true, desc: 'Tweet ID.' },
        ...P_PAGINATION,
        P_RAW,
      ],
      op: 'Retweeters',
      ok: '{\n  "data": [\n    { "id": "11", "username": "alice" }\n  ],\n  "meta": { "result_count": 1 }\n}',
    }),
    'tweet-retweets': ep({
      method: 'GET', path: '/2/tweets/:id/retweets', name: 'Tweet retweets',
      summary: 'Alias dari `/retweeted_by` — same `Retweeters` operation.',
      params: [
        { name: 'tweet_id', loc: 'path', type: 'string', required: true, desc: 'Tweet ID.' },
        ...P_PAGINATION,
        P_RAW,
      ],
      op: 'Retweeters',
      ok: '{\n  "data": [\n    { "id": "11", "username": "alice" }\n  ],\n  "meta": { "result_count": 1 }\n}',
    }),
    'quote-tweets': ep({
      method: 'GET', path: '/2/tweets/:id/quote_tweets', name: 'Quote tweets',
      summary: 'Quote tweets via `SearchTimeline` (filter `quoted_tweet_id:`). Pakai Playwright.',
      params: [
        { name: 'tweet_id', loc: 'path', type: 'string', required: true, desc: 'Tweet ID.' },
        ...P_PAGINATION,
        P_RAW,
      ],
      engine: 'playwright',
      ok: '{\n  "data": [\n    { "id": "222", "text": "quoting!" }\n  ],\n  "meta": { "result_count": 1 }\n}',
    }),
    'unlike-tweet': ep({
      method: 'DEL', path: '/2/users/:user_id/likes/:tweet_id', name: 'Unlike tweet',
      summary: 'Unlike via `UnfavoriteTweet`.',
      params: [
        { name: 'user_id',  loc: 'path', type: 'string', required: true, desc: 'Authenticated user ID.' },
        { name: 'tweet_id', loc: 'path', type: 'string', required: true, desc: 'Tweet ID.' },
      ],
      op: 'UnfavoriteTweet',
      ok: '{\n  "data": { "unfavorite_tweet": "Done" }\n}',
    }),
    'unretweet': ep({
      method: 'DEL', path: '/2/users/:user_id/retweets/by/source_tweet_id/:source_tweet_id', name: 'Unretweet',
      summary: 'Unretweet via `DeleteRetweet`. Pakai source_tweet_id, bukan retweet ID.',
      params: [
        { name: 'user_id',         loc: 'path', type: 'string', required: true, desc: 'Authenticated user ID.' },
        { name: 'source_tweet_id', loc: 'path', type: 'string', required: true, desc: 'Tweet ID asli.' },
      ],
      op: 'DeleteRetweet',
      ok: '{\n  "data": { "unretweet": { "source_tweet_results": {} } }\n}',
    }),

    // ── Users (sisanya) ──────────────────────────────────────────
    'lookup-users': ep({
      method: 'GET', path: '/2/users/by', name: 'Bulk lookup by username',
      summary: 'Fan-out paralel ke `UserByScreenName`. Max 100 handles.',
      params: [
        { name: 'usernames', loc: 'query', type: 'string', required: true, desc: 'Comma-separated handles. Max 100.' },
        P_RAW,
      ],
      op: 'UserByScreenName',
      ok: '{\n  "data": [\n    { "id": "11", "username": "alice" }\n  ],\n  "meta": { "result_count": 1 }\n}',
    }),
    'bulk-users': ep({
      method: 'GET', path: '/2/users', name: 'Bulk lookup by id',
      summary: 'Fan-out paralel ke `UserByRestId` via Playwright. Max 100 IDs.',
      params: [
        { name: 'ids', loc: 'query', type: 'string', required: true, desc: 'Comma-separated user IDs. Max 100.' },
        P_RAW,
      ],
      op: 'UserByRestId',
      engine: 'playwright',
      ok: '{\n  "data": [\n    { "id": "44196397", "username": "elonmusk" }\n  ],\n  "meta": { "result_count": 1 }\n}',
    }),
    'user-by-id': ep({
      method: 'GET', path: '/2/users/:id', name: 'Get user by id',
      summary: 'Fetch single user via Playwright `UserByRestId` (CF-gated).',
      params: [
        { name: 'user_id', loc: 'path',  type: 'string', required: true, desc: 'User ID.' },
        P_RAW,
      ],
      op: 'UserByRestId',
      engine: 'playwright',
      ok: '{\n  "data": {\n    "id": "44196397",\n    "username": "elonmusk",\n    "name": "Elon Musk"\n  }\n}',
    }),
    'user-search': ep({
      method: 'GET', path: '/2/users/search', name: 'Search users',
      summary: 'Search user via `SearchTimeline` (product=People). Pakai Playwright.',
      params: [
        { name: 'query',       loc: 'query', type: 'string',  required: true,  desc: 'Keyword pencarian.' },
        { name: 'max_results', loc: 'query', type: 'integer', required: false, desc: '1-100. Default 20.' },
        P_RAW,
      ],
      engine: 'playwright',
      ok: '{\n  "data": [\n    { "id": "11", "username": "alice", "name": "Alice" }\n  ],\n  "meta": { "result_count": 1 }\n}',
    }),
    'user-tweets-replies': ep({
      method: 'GET', path: '/2/users/:id/tweets/replies', name: 'User tweets + replies',
      summary: '`UserTweetsAndReplies` GraphQL dengan Playwright fallback kalau CF.',
      params: [
        { name: 'user_id', loc: 'path', type: 'string', required: true, desc: 'Target user ID.' },
        ...P_PAGINATION,
        P_RAW,
      ],
      op: 'UserTweetsAndReplies',
      ok: '{\n  "data": [\n    { "id": "111", "text": "@alice yes", "in_reply_to_user_id": "11" }\n  ],\n  "meta": { "result_count": 1 }\n}',
    }),
    'user-mentions': ep({
      method: 'GET', path: '/2/users/:id/mentions', name: 'User mentions',
      summary: 'Mentions via `SearchTimeline` (`@handle`). Auto-resolve username dari user_id.',
      params: [
        { name: 'user_id',  loc: 'path',  type: 'string', required: true,  desc: 'Target user ID.' },
        { name: 'username', loc: 'query', type: 'string', required: false, desc: 'Override handle (skip resolve).' },
        ...P_PAGINATION,
        P_RAW,
      ],
      engine: 'playwright',
      ok: '{\n  "data": [\n    { "id": "111", "text": "@elonmusk hi" }\n  ],\n  "meta": { "result_count": 1 }\n}',
    }),
    'user-media': ep({
      method: 'GET', path: '/2/users/:id/media', name: 'User media',
      summary: 'Tweets dengan media saja — `UserMedia` GraphQL.',
      params: [
        { name: 'user_id', loc: 'path', type: 'string', required: true, desc: 'Target user ID.' },
        ...P_PAGINATION,
        P_RAW,
      ],
      op: 'UserMedia',
      ok: '{\n  "data": [\n    { "id": "111", "text": "lihat foto ini", "attachments": { "media_keys": ["13_111"] } }\n  ],\n  "meta": { "result_count": 1 }\n}',
    }),
    'user-liked': ep({
      method: 'GET', path: '/2/users/:id/liked_tweets', name: 'Liked tweets',
      summary: 'Tweets yang di-like user — `Likes` GraphQL.',
      params: [
        { name: 'user_id', loc: 'path', type: 'string', required: true, desc: 'Target user ID.' },
        ...P_PAGINATION,
        P_RAW,
      ],
      op: 'Likes',
      ok: '{\n  "data": [\n    { "id": "111", "text": "first" }\n  ],\n  "meta": { "result_count": 1 }\n}',
    }),
    'user-following': ep({
      method: 'GET', path: '/2/users/:id/following', name: 'Following',
      summary: 'Following list via `Following` GraphQL.',
      params: [
        { name: 'user_id', loc: 'path', type: 'string', required: true, desc: 'Target user ID.' },
        ...P_PAGINATION,
        P_RAW,
      ],
      op: 'Following',
      ok: '{\n  "data": [\n    { "id": "11", "username": "alice" }\n  ],\n  "meta": { "result_count": 1 }\n}',
    }),
    'unfollow-user': ep({
      method: 'DEL', path: '/2/users/:src/following/:tgt', name: 'Unfollow user',
      summary: 'Unfollow via REST `friendships/destroy.json`.',
      params: [
        { name: 'source_user_id', loc: 'path', type: 'string', required: true, desc: 'Authenticated user ID.' },
        { name: 'target_user_id', loc: 'path', type: 'string', required: true, desc: 'User yang di-unfollow.' },
      ],
      engine: 'rest',
      ok: '{\n  "data": { "following": false, "id": "12" }\n}',
    }),
    'user-blocking': ep({
      method: 'GET', path: '/2/users/:id/blocking', name: 'Blocking list',
      summary: 'List user yang di-block (own only) — `BlockedAccountsAll`.',
      params: [
        { name: 'user_id', loc: 'path', type: 'string', required: true, desc: 'Authenticated user ID.' },
        ...P_PAGINATION,
        P_RAW,
      ],
      op: 'BlockedAccountsAll',
      ok: '{\n  "data": [\n    { "id": "99", "username": "spammer" }\n  ],\n  "meta": { "result_count": 1 }\n}',
    }),
    'block-user': ep({
      method: 'POST', path: '/2/users/:id/blocking', name: 'Block user',
      summary: 'Block via REST `blocks/create.json`.',
      params: [
        { name: 'user_id', loc: 'path', type: 'string', required: true, desc: 'Authenticated user ID.' },
      ],
      body: [
        { name: 'target_user_id', type: 'string', required: true, desc: 'User ID yang di-block.', example: '99' },
      ],
      engine: 'rest',
      ok: '{\n  "data": { "blocking": true, "id": "99" }\n}',
    }),
    'unblock-user': ep({
      method: 'DEL', path: '/2/users/:src/blocking/:tgt', name: 'Unblock user',
      summary: 'Unblock via REST `blocks/destroy.json`. Fallback Playwright UI click kalau CF.',
      params: [
        { name: 'source_user_id', loc: 'path', type: 'string', required: true, desc: 'Authenticated user ID.' },
        { name: 'target_user_id', loc: 'path', type: 'string', required: true, desc: 'User yang di-unblock.' },
      ],
      engine: 'rest',
      ok: '{\n  "data": { "blocking": false, "id": "99" }\n}',
    }),
    'user-muting': ep({
      method: 'GET', path: '/2/users/:id/muting', name: 'Muting list',
      summary: 'List user yang di-mute (own only) — `MutedAccounts`.',
      params: [
        { name: 'user_id', loc: 'path', type: 'string', required: true, desc: 'Authenticated user ID.' },
        ...P_PAGINATION,
        P_RAW,
      ],
      op: 'MutedAccounts',
      ok: '{\n  "data": [\n    { "id": "99", "username": "noisy" }\n  ],\n  "meta": { "result_count": 1 }\n}',
    }),
    'mute-user': ep({
      method: 'POST', path: '/2/users/:id/muting', name: 'Mute user',
      summary: 'Mute via REST `mutes/users/create.json`.',
      params: [
        { name: 'user_id', loc: 'path', type: 'string', required: true, desc: 'Authenticated user ID.' },
      ],
      body: [
        { name: 'target_user_id', type: 'string', required: true, desc: 'User ID yang di-mute.', example: '99' },
      ],
      engine: 'rest',
      ok: '{\n  "data": { "muting": true, "id": "99" }\n}',
    }),
    'unmute-user': ep({
      method: 'DEL', path: '/2/users/:src/muting/:tgt', name: 'Unmute user',
      summary: 'Unmute via REST `mutes/users/destroy.json`.',
      params: [
        { name: 'source_user_id', loc: 'path', type: 'string', required: true, desc: 'Authenticated user ID.' },
        { name: 'target_user_id', loc: 'path', type: 'string', required: true, desc: 'User yang di-unmute.' },
      ],
      engine: 'rest',
      ok: '{\n  "data": { "muting": false, "id": "99" }\n}',
    }),
    'pin-tweet': ep({
      method: 'POST', path: '/2/users/:id/pinned_tweets', name: 'Pin tweet',
      summary: 'Pin tweet ke profile via `PinTweet` GraphQL.',
      params: [
        { name: 'user_id', loc: 'path', type: 'string', required: true, desc: 'Authenticated user ID.' },
      ],
      body: [
        { name: 'tweet_id', type: 'string', required: true, desc: 'Tweet ID untuk pin.', example: '111' },
      ],
      op: 'PinTweet',
      ok: '{\n  "data": { "pin_tweet": "Done" }\n}',
    }),
    'unpin-tweet': ep({
      method: 'DEL', path: '/2/users/:id/pinned_tweets/:tweet_id', name: 'Unpin tweet',
      summary: 'Unpin via `UnpinTweet` GraphQL.',
      params: [
        { name: 'user_id',  loc: 'path', type: 'string', required: true, desc: 'Authenticated user ID.' },
        { name: 'tweet_id', loc: 'path', type: 'string', required: true, desc: 'Tweet ID untuk unpin.' },
      ],
      op: 'UnpinTweet',
      ok: '{\n  "data": { "unpin_tweet": "Done" }\n}',
    }),
    'reposts-of-me': ep({
      method: 'GET', path: '/2/users/reposts_of_me', name: 'Reposts of me',
      summary: 'Tweets yang me-retweet milikku, via `SearchTimeline` (`filter:nativeretweets from:<me>`).',
      params: [
        { name: 'max_results', loc: 'query', type: 'integer', required: false, desc: '1-100. Default 20.' },
        P_RAW,
      ],
      engine: 'playwright',
      ok: '{\n  "data": [\n    { "id": "111", "text": "RT @me: …" }\n  ],\n  "meta": { "result_count": 1 }\n}',
    }),
    'user-affiliates': ep({
      method: 'GET', path: '/2/users/:id/affiliates', name: 'Affiliates (501)',
      summary: 'Akun-akun yang afiliasi (verified org). Belum di-discover di mirror cookie.',
      stub: true,
    }),

    // ── Timelines ────────────────────────────────────────────────
    'reverse-chrono': ep({
      method: 'GET', path: '/2/users/:id/timelines/reverse_chronological', name: 'Reverse chronological',
      summary: 'Following timeline ordered by recency — `HomeLatestTimeline`.',
      params: [
        { name: 'user_id', loc: 'path', type: 'string', required: true, desc: 'Authenticated user ID.' },
        ...P_PAGINATION,
        P_RAW,
      ],
      op: 'HomeLatestTimeline',
      ok: '{\n  "data": [\n    { "id": "111", "text": "latest first" }\n  ],\n  "meta": { "result_count": 1 }\n}',
    }),

    // ── Lists ────────────────────────────────────────────────────
    'list-create': ep({
      method: 'POST', path: '/2/lists', name: 'Create list',
      summary: 'Create list via `CreateList` GraphQL.',
      body: [
        { name: 'name',        type: 'string',  required: true,  desc: 'Nama list.', example: 'tech-folks' },
        { name: 'description', type: 'string',  required: false, desc: 'Deskripsi.', example: '' },
        { name: 'is_private',  type: 'boolean', required: false, desc: 'Private list.', example: false },
      ],
      op: 'CreateList',
      status: 201,
      ok: '{\n  "data": { "create_list": { "list_results": { "result": { "rest_id": "1700000000000000000" } } } }\n}',
    }),
    'list-get': ep({
      method: 'GET', path: '/2/lists/:id', name: 'Get list',
      summary: 'Detail list via `ListByRestId`.',
      params: [
        { name: 'list_id', loc: 'path', type: 'string', required: true, desc: 'List ID.' },
        P_RAW,
      ],
      op: 'ListByRestId',
      ok: '{\n  "data": {\n    "list": { "id_str": "1700000000000000000", "name": "tech-folks", "member_count": 12 }\n  }\n}',
    }),
    'list-update': ep({
      method: 'PUT', path: '/2/lists/:id', name: 'Update list',
      summary: 'Update list metadata via `UpdateList` GraphQL.',
      params: [
        { name: 'list_id', loc: 'path', type: 'string', required: true, desc: 'List ID.' },
      ],
      body: [
        { name: 'name',        type: 'string',  required: false, desc: 'Nama baru.', example: 'devs' },
        { name: 'description', type: 'string',  required: false, desc: 'Deskripsi baru.' },
        { name: 'is_private',  type: 'boolean', required: false, desc: 'Private toggle.' },
      ],
      op: 'UpdateList',
      ok: '{\n  "data": { "update_list": {} }\n}',
    }),
    'list-delete': ep({
      method: 'DEL', path: '/2/lists/:id', name: 'Delete list',
      summary: 'Delete via `DeleteList` GraphQL.',
      params: [
        { name: 'list_id', loc: 'path', type: 'string', required: true, desc: 'List ID.' },
      ],
      op: 'DeleteList',
      ok: '{\n  "data": { "delete_list": { "list_results": {} } }\n}',
    }),
    'list-by-owner': ep({
      method: 'GET', path: '/2/lists/by/owner/:user_id', name: 'Lists by owner',
      summary: 'Legacy. Pakai `/2/users/{id}/owned_lists` sebagai canonical.',
      params: [
        { name: 'user_id', loc: 'path', type: 'string', required: true, desc: 'Owner user ID.' },
        ...P_PAGINATION,
        P_RAW,
      ],
      op: 'ListsManagementPageTimeline',
      ok: '{\n  "data": [\n    { "id_str": "1700…", "name": "tech-folks" }\n  ],\n  "meta": { "result_count": 1 }\n}',
    }),
    'list-followers': ep({
      method: 'GET', path: '/2/lists/:id/followers', name: 'List followers',
      summary: 'Subscriber timeline via `ListSubscribers`.',
      params: [
        { name: 'list_id', loc: 'path', type: 'string', required: true, desc: 'List ID.' },
        ...P_PAGINATION,
        P_RAW,
      ],
      op: 'ListSubscribers',
      ok: '{\n  "data": [\n    { "id": "11", "username": "alice" }\n  ],\n  "meta": { "result_count": 1 }\n}',
    }),
    'list-members': ep({
      method: 'GET', path: '/2/lists/:id/members', name: 'List members',
      summary: 'Member timeline via `ListMembers`.',
      params: [
        { name: 'list_id', loc: 'path', type: 'string', required: true, desc: 'List ID.' },
        ...P_PAGINATION,
        P_RAW,
      ],
      op: 'ListMembers',
      ok: '{\n  "data": [\n    { "id": "11", "username": "alice" }\n  ],\n  "meta": { "result_count": 1 }\n}',
    }),
    'list-add-member': ep({
      method: 'POST', path: '/2/lists/:id/members', name: 'Add member',
      summary: 'Add user ke list via `ListAddMember`.',
      params: [
        { name: 'list_id', loc: 'path', type: 'string', required: true, desc: 'List ID.' },
      ],
      body: [
        { name: 'user_id', type: 'string', required: true, desc: 'User ID untuk ditambah.', example: '11' },
      ],
      op: 'ListAddMember',
      ok: '{\n  "data": { "list_add_member": {} }\n}',
    }),
    'list-remove-member': ep({
      method: 'DEL', path: '/2/lists/:id/members/:user_id', name: 'Remove member',
      summary: 'Remove user dari list via `ListRemoveMember`.',
      params: [
        { name: 'list_id', loc: 'path', type: 'string', required: true, desc: 'List ID.' },
        { name: 'user_id', loc: 'path', type: 'string', required: true, desc: 'User ID untuk di-remove.' },
      ],
      op: 'ListRemoveMember',
      ok: '{\n  "data": { "list_remove_member": {} }\n}',
    }),
    'list-pin': ep({
      method: 'POST', path: '/2/lists/:id/pinned', name: 'Pin list',
      summary: 'Legacy. Pakai `POST /2/users/{id}/pinned_lists`.',
      params: [
        { name: 'list_id', loc: 'path', type: 'string', required: true, desc: 'List ID.' },
      ],
      op: 'PinTimeline',
      ok: '{\n  "data": { "pin_timeline": "Done" }\n}',
    }),
    'list-unpin': ep({
      method: 'DEL', path: '/2/lists/:id/pinned', name: 'Unpin list',
      summary: 'Legacy. Pakai `DELETE /2/users/{id}/pinned_lists/{list_id}`.',
      params: [
        { name: 'list_id', loc: 'path', type: 'string', required: true, desc: 'List ID.' },
      ],
      op: 'UnpinTimeline',
      ok: '{\n  "data": { "unpin_timeline": "Done" }\n}',
    }),
    'list-tweets': ep({
      method: 'GET', path: '/2/lists/:id/tweets', name: 'List tweets',
      summary: 'Latest tweets dari member list — `ListLatestTweetsTimeline`.',
      params: [
        { name: 'list_id', loc: 'path', type: 'string', required: true, desc: 'List ID.' },
        ...P_PAGINATION,
        P_RAW,
      ],
      op: 'ListLatestTweetsTimeline',
      ok: '{\n  "data": [\n    { "id": "111", "text": "from member" }\n  ],\n  "meta": { "result_count": 1 }\n}',
    }),
    'list-followed': ep({
      method: 'GET', path: '/2/users/:id/followed_lists', name: 'Followed lists (501)',
      summary: 'List yang di-subscribe user. Operasi `ListSubscriptions` belum di-discover.',
      stub: true,
    }),
    'list-follow': ep({
      method: 'POST', path: '/2/users/:id/followed_lists', name: 'Follow list',
      summary: 'Subscribe ke list via `ListSubscribe`.',
      params: [
        { name: 'user_id', loc: 'path',  type: 'string', required: true, desc: 'Authenticated user ID.' },
        { name: 'list_id', loc: 'query', type: 'string', required: true, desc: 'List ID.' },
      ],
      op: 'ListSubscribe',
      ok: '{\n  "data": { "list_subscribe": {} }\n}',
    }),
    'list-unfollow': ep({
      method: 'DEL', path: '/2/users/:id/followed_lists/:list_id', name: 'Unfollow list',
      summary: 'Unsubscribe via `ListUnsubscribe`.',
      params: [
        { name: 'user_id', loc: 'path', type: 'string', required: true, desc: 'Authenticated user ID.' },
        { name: 'list_id', loc: 'path', type: 'string', required: true, desc: 'List ID.' },
      ],
      op: 'ListUnsubscribe',
      ok: '{\n  "data": { "list_unsubscribe": {} }\n}',
    }),
    'list-memberships': ep({
      method: 'GET', path: '/2/users/:id/list_memberships', name: 'List memberships',
      summary: 'List dimana user adalah member — `ListMemberships`.',
      params: [
        { name: 'user_id', loc: 'path', type: 'string', required: true, desc: 'User ID.' },
        ...P_PAGINATION,
        P_RAW,
      ],
      op: 'ListMemberships',
      ok: '{\n  "data": [\n    { "id_str": "1700…", "name": "engineers" }\n  ],\n  "meta": { "result_count": 1 }\n}',
    }),
    'list-owned': ep({
      method: 'GET', path: '/2/users/:id/owned_lists', name: 'Owned lists',
      summary: 'List yang dibuat user — `ListsManagementPageTimeline` (canonical).',
      params: [
        { name: 'user_id', loc: 'path', type: 'string', required: true, desc: 'User ID.' },
        ...P_PAGINATION,
        P_RAW,
      ],
      op: 'ListsManagementPageTimeline',
      ok: '{\n  "data": [\n    { "id_str": "1700…", "name": "tech-folks" }\n  ],\n  "meta": { "result_count": 1 }\n}',
    }),
    'list-pinned': ep({
      method: 'GET', path: '/2/users/:id/pinned_lists', name: 'Pinned lists',
      summary: 'Pinned timelines via `PinnedTimelines`.',
      params: [
        { name: 'user_id', loc: 'path', type: 'string', required: true, desc: 'User ID.' },
        P_RAW,
      ],
      op: 'PinnedTimelines',
      ok: '{\n  "data": [\n    { "id_str": "1700…", "name": "tech-folks", "pinned": true }\n  ]\n}',
    }),

    // ── Bookmarks ────────────────────────────────────────────────
    'bookmarks-list': ep({
      method: 'GET', path: '/2/users/:id/bookmarks', name: 'Bookmarks',
      summary: 'Bookmark list (own only) via `Bookmarks` GraphQL.',
      params: [
        { name: 'user_id', loc: 'path', type: 'string', required: true, desc: 'Authenticated user ID.' },
        ...P_PAGINATION,
        P_RAW,
      ],
      op: 'Bookmarks',
      ok: '{\n  "data": [\n    { "id": "111", "text": "saved this" }\n  ],\n  "meta": { "result_count": 1 }\n}',
    }),
    'bookmark-add': ep({
      method: 'POST', path: '/2/users/:id/bookmarks', name: 'Add bookmark',
      summary: 'Bookmark tweet via `CreateBookmark`. Fallback Playwright UI click kalau CF.',
      params: [
        { name: 'user_id', loc: 'path', type: 'string', required: true, desc: 'Authenticated user ID.' },
      ],
      body: [
        { name: 'tweet_id', type: 'string', required: true, desc: 'Tweet ID untuk di-bookmark.', example: '111' },
      ],
      op: 'CreateBookmark',
      ok: '{\n  "data": { "tweet_bookmark_put": "Done" }\n}',
    }),
    'bookmark-folders': ep({
      method: 'GET', path: '/2/users/:id/bookmarks/folders', name: 'Bookmark folders',
      summary: 'List folder bookmarks — `BookmarkFoldersSlice`.',
      params: [
        { name: 'user_id', loc: 'path', type: 'string', required: true, desc: 'Authenticated user ID.' },
        ...P_PAGINATION,
        P_RAW,
      ],
      op: 'BookmarkFoldersSlice',
      ok: '{\n  "data": [\n    { "id": "1", "name": "Reading list" }\n  ],\n  "meta": { "result_count": 1 }\n}',
    }),
    'bookmark-folder': ep({
      method: 'GET', path: '/2/users/:id/bookmarks/folders/:folder_id', name: 'Folder bookmarks',
      summary: 'Tweet di dalam folder — `BookmarkFolderTimeline`.',
      params: [
        { name: 'user_id',   loc: 'path', type: 'string', required: true, desc: 'Authenticated user ID.' },
        { name: 'folder_id', loc: 'path', type: 'string', required: true, desc: 'Folder ID.' },
        ...P_PAGINATION,
        P_RAW,
      ],
      op: 'BookmarkFolderTimeline',
      ok: '{\n  "data": [\n    { "id": "111", "text": "in folder" }\n  ],\n  "meta": { "result_count": 1 }\n}',
    }),
    'bookmark-remove': ep({
      method: 'DEL', path: '/2/users/:id/bookmarks/:tweet_id', name: 'Remove bookmark',
      summary: 'Unbookmark via `DeleteBookmark`. Fallback Playwright UI click kalau CF.',
      params: [
        { name: 'user_id',  loc: 'path', type: 'string', required: true, desc: 'Authenticated user ID.' },
        { name: 'tweet_id', loc: 'path', type: 'string', required: true, desc: 'Tweet ID.' },
      ],
      op: 'DeleteBookmark',
      ok: '{\n  "data": { "tweet_bookmark_delete": "Done" }\n}',
    }),

    // ── Direct Messages ──────────────────────────────────────────
    'dm-conv-create': ep({
      method: 'POST', path: '/2/dm_conversations', name: 'Create DM conversation',
      summary: 'Create DM conv (auto via REST `dm/new2.json`). Bisa group atau 1-on-1.',
      body: [
        { name: 'conversation_type', type: 'string', required: false, desc: '`Group` (default) atau `OneToOne`.', example: 'Group' },
        { name: 'participant_ids',   type: 'string[]', required: true, desc: 'Min 1 user ID.', example: ['11', '12'] },
        { name: 'message',           type: 'object', required: true, desc: '`{text: "..."}`. Required.', example: { text: 'hi' } },
      ],
      engine: 'dm',
      status: 201,
      ok: '{\n  "data": {\n    "dm_event_id": "1786394285310038016",\n    "dm_conversation_id": "44196397-12"\n  }\n}',
    }),
    'dm-events': ep({
      method: 'GET', path: '/2/dm_events', name: 'List DM events',
      summary: 'DM events di seluruh inbox — `inbox_initial_state.json` REST 1.1.',
      params: [
        { name: 'max_results', loc: 'query', type: 'integer', required: false, desc: '1-100. Default 50.' },
        { name: 'event_types', loc: 'query', type: 'string',  required: false, desc: 'Filter, comma-separated. mis. `MessageCreate,Reaction`.' },
        P_RAW,
      ],
      engine: 'dm',
      ok: '{\n  "data": [\n    { "id": "1786…", "event_type": "MessageCreate", "text": "hi" }\n  ],\n  "meta": { "result_count": 1 }\n}',
    }),
    'dm-events-conv': ep({
      method: 'GET', path: '/2/dm_conversations/:id/dm_events', name: 'Conversation events',
      summary: 'DM events di satu conversation — `conversation/<id>.json`.',
      params: [
        { name: 'conversation_id', loc: 'path', type: 'string', required: true, desc: 'Conversation ID.' },
        ...P_PAGINATION,
        P_RAW,
      ],
      engine: 'dm',
      ok: '{\n  "data": [\n    { "id": "1786…", "event_type": "MessageCreate", "text": "hi" }\n  ],\n  "meta": { "result_count": 1 }\n}',
    }),
    'dm-events-with': ep({
      method: 'GET', path: '/2/dm_conversations/with/:participant_id/dm_events', name: 'Events with user',
      summary: 'DM events dengan user tertentu (auto-resolve conv ID).',
      params: [
        { name: 'participant_id', loc: 'path', type: 'string', required: true, desc: 'Target user ID.' },
        ...P_PAGINATION,
        P_RAW,
      ],
      engine: 'dm',
      ok: '{\n  "data": [\n    { "id": "1786…", "event_type": "MessageCreate", "text": "hi" }\n  ],\n  "meta": { "result_count": 1 }\n}',
    }),
    'dm-event-get': ep({
      method: 'GET', path: '/2/dm_events/:event_id', name: 'Get DM event',
      summary: 'Single DM event detail.',
      params: [
        { name: 'event_id', loc: 'path', type: 'string', required: true, desc: 'DM event ID.' },
        P_RAW,
      ],
      engine: 'dm',
      ok: '{\n  "data": { "id": "1786…", "event_type": "MessageCreate", "text": "hi", "sender_id": "11" }\n}',
    }),
    'dm-event-delete': ep({
      method: 'DEL', path: '/2/dm_events/:event_id', name: 'Delete DM event',
      summary: 'Delete DM event (own messages only).',
      params: [
        { name: 'event_id', loc: 'path', type: 'string', required: true, desc: 'DM event ID.' },
      ],
      engine: 'dm',
      ok: '{\n  "data": { "deleted": true }\n}',
    }),
    'dm-block': ep({
      method: 'POST', path: '/2/users/:id/dm/block', name: 'Block from DM',
      summary: 'Block user dari kirim DM (tetep follow).',
      params: [
        { name: 'user_id', loc: 'path', type: 'string', required: true, desc: 'Target user ID.' },
      ],
      engine: 'dm',
      ok: '{\n  "data": { "dm_blocked": true }\n}',
    }),
    'dm-unblock': ep({
      method: 'POST', path: '/2/users/:id/dm/unblock', name: 'Unblock from DM',
      summary: 'Unblock user untuk kirim DM lagi.',
      params: [
        { name: 'user_id', loc: 'path', type: 'string', required: true, desc: 'Target user ID.' },
      ],
      engine: 'dm',
      ok: '{\n  "data": { "dm_blocked": false }\n}',
    }),
    'chat-conv-list': ep({
      method: 'GET', path: '/2/chat/conversations', name: 'Chat conversations (501)',
      summary: 'Endpoint X chat baru (E2EE). Butuh OAuth2 user-context dengan dev portal subscription.',
      stub: true,
    }),

    // ── Communities ──────────────────────────────────────────────
    'community-search': ep({
      method: 'GET', path: '/2/communities/search', name: 'Search communities (501)',
      summary: 'Search community. Operasi `CommunitiesSearchSlideQuery` belum di-wire.',
      stub: true,
    }),
    'community-get': ep({
      method: 'GET', path: '/2/communities/:id', name: 'Get community',
      summary: 'Detail community via `CommunityByRestId`.',
      params: [
        { name: 'community_id', loc: 'path', type: 'string', required: true, desc: 'Community ID.' },
        P_RAW,
      ],
      op: 'CommunityByRestId',
      ok: '{\n  "data": {\n    "id": "1700000000000000000",\n    "name": "FastAPI Folks",\n    "member_count": 8421,\n    "created_at": "2024-01-15T00:00:00Z"\n  }\n}',
    }),

    // ── Spaces (semua stub karena enterprise tier) ─────────────────
    'spaces-bulk':    ep({ method: 'GET', path: '/2/spaces',                  name: 'Bulk lookup spaces (501)',  summary: 'Operasi `AudioSpaceById` (fan-out) belum di-wire.', stub: true }),
    'spaces-creator': ep({ method: 'GET', path: '/2/spaces/by/creator_ids',  name: 'By creator (501)',          summary: 'Operasi `AudioSpacesByCreator` belum di-discover.', stub: true }),
    'spaces-search':  ep({ method: 'GET', path: '/2/spaces/search',           name: 'Search spaces (501)',       summary: 'Operasi `AudioSpaceSearch` belum di-discover.', stub: true }),
    'space-get':      ep({ method: 'GET', path: '/2/spaces/:id',              name: 'Get space (501)',           summary: 'Operasi `AudioSpaceById` belum di-wire.', stub: true }),
    'space-buyers':   ep({ method: 'GET', path: '/2/spaces/:id/buyers',       name: 'Ticket buyers (501)',       summary: 'Butuh OAuth2 user-context.', stub: true }),
    'space-tweets':   ep({ method: 'GET', path: '/2/spaces/:id/tweets',       name: 'Space tweets (501)',        summary: 'Operasi `AudioSpaceTweets` belum di-wire.', stub: true }),

    // ── Birdwatch / Community Notes ──────────────────────────────
    'note-create': ep({
      method: 'POST', path: '/2/notes', name: 'Submit Birdwatch note',
      summary: 'Create note via `BirdwatchCreateNote`. Hanya untuk Birdwatch contributor.',
      body: [
        { name: 'tweet_id',                 type: 'string',  required: true,  desc: 'Tweet target.', example: '1786394285310038016' },
        { name: 'is_media_note',            type: 'boolean', required: false, desc: 'Note tentang media (vs caption).', example: false },
        { name: 'is_helpful_for_all_posts', type: 'boolean', required: false, desc: 'Berlaku ke semua post serupa.', example: false },
        { name: 'data',                     type: 'object',  required: true,  desc: 'Note data v1 schema.', example: { agree_with_post: 'NO_DISAGREE' } },
      ],
      op: 'BirdwatchCreateNote',
      status: 201,
      ok: '{\n  "data": { "note_id": "1700000000000000000", "status": "Submitted" }\n}',
    }),
    'note-evaluate': ep({
      method: 'POST', path: '/2/evaluate_note', name: 'Rate Birdwatch note',
      summary: 'Rate note (helpful / not helpful) via `BirdwatchCreateRating`.',
      body: [
        { name: 'note_id',         type: 'string', required: true,  desc: 'Note yang di-rate.', example: '1700…' },
        { name: 'tweet_id',        type: 'string', required: true,  desc: 'Tweet pengikut note.', example: '111' },
        { name: 'data',            type: 'object', required: true,  desc: 'Rating data v2.', example: { helpful: 'HELPFUL' } },
        { name: 'rating_source',   type: 'string', required: false, desc: 'Source rating UI.' },
        { name: 'source_platform', type: 'string', required: false, desc: 'Platform: web / android / ios.' },
        { name: 'for_live_note',   type: 'boolean', required: false, desc: 'Live note flag.', example: false },
      ],
      op: 'BirdwatchCreateRating',
      status: 201,
      ok: '{\n  "data": { "rating_id": "1700…", "status": "Submitted" }\n}',
    }),
    'notes-written': ep({
      method: 'GET', path: '/2/notes/search/notes_written', name: 'Notes I wrote',
      summary: 'Notes by Birdwatch contributor alias — `BirdwatchFetchContributorNotesSlice`.',
      params: [
        { name: 'alias',       loc: 'query', type: 'string',  required: true,  desc: 'Birdwatch alias slug.' },
        { name: 'max_results', loc: 'query', type: 'integer', required: false, desc: '1-100. Default 10.' },
        { name: 'pagination_token', loc: 'query', type: 'string', required: false, desc: 'Cursor.' },
        P_RAW,
      ],
      op: 'BirdwatchFetchContributorNotesSlice',
      ok: '{\n  "data": [\n    { "note_id": "1700…", "tweet_id": "111", "summary": "context: …" }\n  ],\n  "meta": { "result_count": 1 }\n}',
    }),
    'notes-eligible': ep({
      method: 'GET', path: '/2/notes/search/posts_eligible_for_notes', name: 'Posts eligible for notes',
      summary: 'BatSignal — apakah tweet eligible untuk Birdwatch note.',
      params: [
        { name: 'tweet_id', loc: 'query', type: 'string', required: true, desc: 'Tweet target.' },
        P_RAW,
      ],
      op: 'BirdwatchFetchBatSignal',
      ok: '{\n  "data": { "tweet_id": "111", "eligible": true, "reason": null }\n}',
    }),
    'note-delete': ep({
      method: 'DEL', path: '/2/notes/:id', name: 'Delete Birdwatch note',
      summary: 'Delete note via `BirdwatchDeleteNote`.',
      params: [
        { name: 'note_id', loc: 'path', type: 'string', required: true, desc: 'Note ID.' },
      ],
      op: 'BirdwatchDeleteNote',
      ok: '{\n  "data": { "deleted": true }\n}',
    }),

    // ── Trends ───────────────────────────────────────────────────
    'trends-woeid': ep({
      method: 'GET', path: '/2/trends/by/woeid/:woeid', name: 'Trends by WOEID',
      summary: 'Canonical: trends untuk Where-On-Earth ID. 1=worldwide, 23424977=US, 23424775=ID.',
      params: [
        { name: 'woeid', loc: 'path', type: 'integer', required: true, desc: 'WOEID region code.' },
        P_RAW,
      ],
      engine: 'rest',
      ok: '{\n  "data": [\n    { "name": "#FastAPI", "tweet_volume": 12842 }\n  ],\n  "meta": { "woeid": 1, "as_of": "2026-05-17T09:14:00Z" }\n}',
    }),
    'trends-personalized': ep({
      method: 'GET', path: '/2/users/personalized_trends', name: 'Personalized trends',
      summary: 'Personalized trends untuk authenticated user. Ranked berdasar follow + engagement.',
      params: [P_RAW],
      engine: 'rest',
      ok: '{\n  "data": [\n    { "name": "#FastAPI", "tweet_volume": 12842 }\n  ],\n  "meta": { "as_of": "2026-05-17T09:14:00Z" }\n}',
    }),

    // ── Media ────────────────────────────────────────────────────
    'media-upload': ep({
      method: 'POST', path: '/2/media/upload', name: 'Simple upload',
      summary: 'Upload media one-shot (raw body bytes). Auto chunked init/append/finalize.',
      params: [
        { name: 'media_type',     loc: 'query', type: 'string', required: true,  desc: 'MIME, mis. `image/jpeg`, `video/mp4`, `image/gif`.' },
        { name: 'media_category', loc: 'query', type: 'string', required: false, desc: '`tweet_image` | `tweet_video` | `tweet_gif` | `dm_image` | `dm_video`. Auto kalau kosong.' },
        P_RAW,
      ],
      engine: 'upload',
      ok: '{\n  "data": {\n    "media_id": "1786394285310038016",\n    "media_key": "13_1786…",\n    "size": 204800,\n    "expires_after_secs": 86400\n  }\n}',
      examples: {
        curl: `# Body: raw image bytes
curl -X POST "${BASE}/2/media/upload?media_type=image/png" \\
  -H "Authorization: Bearer $AUTH_TOKEN" \\
  --data-binary @photo.png`,
        javascript: `const fileBuf = await Deno.readFile('photo.png'); // or fetch
const url = new URL("${BASE}/2/media/upload");
url.searchParams.set("media_type", "image/png");
const res = await fetch(url, {
  method: "POST",
  headers: { "Authorization": \`Bearer \${process.env.AUTH_TOKEN}\` },
  body: fileBuf,
});`,
        python: `import os, requests
with open("photo.png", "rb") as f:
    res = requests.post(
        "${BASE}/2/media/upload",
        params={"media_type": "image/png"},
        headers={"Authorization": f"Bearer {os.environ['AUTH_TOKEN']}"},
        data=f.read(),
    )`,
      },
    }),
    'media-append':   ep({ method: 'POST', path: '/2/media/upload/:id/append',   name: 'Append chunk (501)',  summary: 'Pakai `POST /2/media/upload` (one-shot) — chunked handled internally.', stub: true }),
    'media-finalize': ep({ method: 'POST', path: '/2/media/upload/:id/finalize', name: 'Finalize (501)',      summary: 'Pakai `POST /2/media/upload` (one-shot).', stub: true }),
    'media-metadata': ep({
      method: 'POST', path: '/2/media/metadata', name: 'Set media metadata',
      summary: 'Alt-text untuk media via `media/metadata/create.json` REST 1.1.',
      body: [
        { name: 'media_id', type: 'string', required: true, desc: 'Media ID dari upload.', example: '1786394285310038016' },
        { name: 'alt_text', type: 'object', required: true, desc: '`{text: "..."}`.', example: { text: 'A cat looking smug' } },
      ],
      engine: 'rest',
      ok: '{\n  "data": {}\n}',
    }),
  });


  // ─────────── Page content (sidebar items dengan kind:'page') ─────────
  const pages = {
    quickstart: {
      title: 'Quickstart',
      lead: 'Mirror X v2 dengan cookie auth_token. Setup di bawah 60 detik.',
      sections: [
        { kicker: '01', title: 'Ambil cookie auth_token', body: 'Login ke x.com di browser. Buka DevTools → Application → Cookies → x.com → salin nilai cookie `auth_token`. Cookie ini bertindak sebagai bearer token untuk semua endpoint Xapi.' },
        { kicker: '02', title: 'Set environment variable', code: 'export AUTH_TOKEN="abc123…"' },
        { kicker: '03', title: 'Validasi token', body: 'Endpoint `/login` mengembalikan profile + screen_name kalau cookie hidup, atau 401 kalau expired/revoked.', code: `curl "${BASE}/login?auth_token=$AUTH_TOKEN"` },
        { kicker: '04', title: 'Authenticated request', body: 'Pakai header `Authorization: Bearer <auth_token>` untuk semua endpoint /2/...', code: `curl "${BASE}/2/users/me" -H "Authorization: Bearer $AUTH_TOKEN"` },
        { kicker: '05', title: 'Mode raw', body: 'Tambah `?raw=1` untuk bypass formatter v2 dan dapat raw GraphQL/REST payload — berguna untuk debug field baru.' },
      ],
    },
    auth: {
      title: 'Authentication',
      lead: 'Cookie-based auth, no OAuth2, no dev portal.',
      sections: [
        { kicker: 'OVERVIEW', title: 'Cookie-based auth', body: 'Xapi tidak pakai OAuth2 atau dev portal. Yang dipakai adalah cookie `auth_token` dari sesi web x.com yang sudah login. Cookie di-pass via header bearer atau query string.' },
        { kicker: 'METHODS', title: 'Dua cara kirim token', body: 'Endpoint menerima `Authorization: Bearer <auth_token>` (preferred) atau query string `?auth_token=<value>` (fallback). Hanya satu yang dipakai per request.' },
        { kicker: 'SECURITY', title: 'Hati-hati', body: 'Cookie auth_token = full account access. Jangan commit ke repo, jangan log, jangan share. Token rotates kalau user logout di X. Pakai dedicated burner account untuk testing.' },
        { kicker: 'EXPIRY', title: 'Token lifecycle', body: 'auth_token valid sampai user logout atau X auto-expire (biasanya 1+ tahun untuk session aktif). Kalau dapat 401 dengan status `invalid`, ambil token baru dari browser.' },
      ],
    },
    'raw-mode': {
      title: 'Raw mode',
      lead: 'Bypass formatter v2 untuk dapat raw payload dari X.',
      sections: [
        { kicker: 'WHY', title: 'Kapan pakai raw=1', body: 'Default response sudah di-format ke shape v2 (`{data, includes, meta}`). Tambah `?raw=1` untuk dapat raw GraphQL/REST response — berguna untuk debugging field baru atau inspect data yang formatter buang.' },
        { kicker: 'EXAMPLE', title: 'Compare formatted vs raw', code: `# Formatted (default)\ncurl "${BASE}/2/tweets/111" -H "Authorization: Bearer $AUTH_TOKEN"\n# → { "data": { "id": "111", "text": "...", "public_metrics": {...} } }\n\n# Raw GraphQL payload\ncurl "${BASE}/2/tweets/111?raw=1" -H "Authorization: Bearer $AUTH_TOKEN"\n# → { "engine": "graphql", "status": "ok", "data": { "tweetResult": {...} } }` },
        { kicker: 'PROD', title: 'Disable di produksi', body: 'Set env `ENABLE_RAW=0` untuk reject `?raw=1` di prod (return 403). Default enabled.' },
      ],
    },
    errors: {
      title: 'Errors',
      lead: 'RFC 7807 problem+json. Predictable status codes.',
      sections: [
        { kicker: 'SHAPE', title: 'problem+json', body: 'Error response ikuti RFC 7807 — `{title, detail, type, status}`. Field `type` adalah error code yang bisa dipakai untuk programmatic handling.' },
        { kicker: 'CODES', title: 'HTTP status code', body: '`200` OK · `201` Created · `400` Bad Request · `401` Unauthorized (token invalid/expired) · `403` Forbidden · `404` Not Found · `429` Rate Limited · `501` Not Implemented (endpoint stub) · `502` Upstream Error.' },
        { kicker: 'EXAMPLE', title: '401 invalid token', code: '{\n  "title": "Unauthorized",\n  "detail": "auth_token expired or revoked",\n  "type": "unauthorized",\n  "status": 401\n}' },
        { kicker: 'RETRY', title: 'Retry strategy', body: 'Kalau dapat 502 upstream, retry dengan exponential backoff (max 3 attempts default, configurable via env `RETRY_MAX_ATTEMPTS`). Untuk 429, baca header `x-rate-limit-reset` dan tunggu sampai window berikutnya.' },
      ],
    },
    'admin-stats': {
      title: 'Admin stats',
      lead: 'Diagnostic endpoint behind ADMIN_TOKEN.',
      sections: [
        { kicker: 'GET', title: '/admin/stats', body: 'Return statistik infra: session cache hit/miss, TID provider stats, HTTP client pool stats, response cache stats, plus inventory route v2 (implemented vs stub).' },
        { kicker: 'AUTH', title: 'Locked behind ADMIN_TOKEN', body: 'Endpoint require header `X-Admin-Token` matching env `ADMIN_TOKEN`. Kalau env tidak set, return 404 (hidden). Kalau header tidak match, return 401.' },
        { kicker: 'EXAMPLE', title: 'curl', code: `curl "${BASE}/admin/stats" -H "X-Admin-Token: $ADMIN_TOKEN"` },
      ],
    },
    'rate-limits': {
      title: 'Rate limits',
      lead: 'Limit upstream X, propagated via headers.',
      sections: [
        { kicker: 'UPSTREAM', title: 'X (Twitter) limits', body: 'Xapi proxy ke X — rate limit yang berlaku adalah rate limit X, bukan limit Xapi. Setiap session cookie punya budget terpisah per endpoint, biasanya 15-min sliding window.' },
        { kicker: 'HEADERS', title: 'Rate limit headers', body: 'Response include `x-rate-limit-limit`, `x-rate-limit-remaining`, `x-rate-limit-reset` (Unix timestamp). Pantau ini untuk avoid 429.' },
        { kicker: 'POOL', title: 'Multi-account', body: 'Pakai pool of cookies (rotate per request) untuk distribute load. Env `CLIENT_POOL_MAX` (default 50) batasi jumlah concurrent sessions.' },
      ],
    },
    changelog: {
      title: 'Changelog',
      lead: 'Recent changes ke Xapi mirror.',
      sections: [
        { kicker: 'v2.3.0', title: 'Current', body: 'Mirror lengkap X v2 endpoint family: tweets, users, timelines, lists, bookmarks, DM, communities, spaces (stub), birdwatch, trends, media. GraphQL via httpx + Playwright fallback untuk CF-gated.' },
        { kicker: 'BREAKING', title: 'Migration dari /search legacy', body: 'POST /search dengan body `{auth_token, q}` deprecated. Pakai GET `/2/tweets/search/recent?query=...` dengan bearer header.' },
        { kicker: 'REMOVED', title: 'Enterprise tier endpoints', body: 'Streams, Compliance, Webhooks, Account Activity, Search Counts/All, Insights, Analytics, News, Media library di-hapus karena butuh OAuth2 app-only bearer + dev portal subscription.' },
      ],
    },
  };

  return { sections, endpoints, pages, base: BASE };
})();
