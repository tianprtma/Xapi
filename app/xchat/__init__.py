"""XChat package — keep a real Chromium tab logged into X so the frontend
performs E2E decryption, then expose plaintext rows to Xapi consumers.

Public surface:
- :class:`bridge.XChatBridge` — persistent browser context per bot account
- :class:`bridge.XChatBridgeRegistry` — singleton registry, one bridge per
  (auth_token, user_id)
- :func:`events.read_xchat_events` — pull plaintext message rows from chat.db
"""
