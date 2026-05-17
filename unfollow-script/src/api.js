import { config } from './config.js';

const headers = () => ({
  Authorization: `Bearer ${config.authToken}`,
  'Content-Type': 'application/json',
});

async function request(method, path, { body, query } = {}) {
  const url = new URL(config.baseUrl + path);
  if (query) {
    for (const [k, v] of Object.entries(query)) {
      if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, v);
    }
  }

  const res = await fetch(url, {
    method,
    headers: headers(),
    body: body ? JSON.stringify(body) : undefined,
  });

  let data = null;
  try {
    data = await res.json();
  } catch {
    /* non-JSON */
  }

  if (!res.ok) {
    const detail =
      data?.errors?.[0]?.detail ||
      data?.errors?.[0]?.title ||
      `HTTP ${res.status}`;
    const err = new Error(detail);
    err.status = res.status;
    err.body = data;
    throw err;
  }
  return data;
}

export const api = {
  me: () => request('GET', '/2/users/me'),

  following: (userId, paginationToken) =>
    request('GET', `/2/users/${userId}/following`, {
      query: { max_results: 100, pagination_token: paginationToken },
    }),

  followers: (userId, paginationToken) =>
    request('GET', `/2/users/${userId}/followers`, {
      query: { max_results: 100, pagination_token: paginationToken },
    }),

  unfollow: (sourceId, targetId) =>
    request('DELETE', `/2/users/${sourceId}/following/${targetId}`),
};
