# Tokenless Web updates — QTS authentication integration (experimental)

Goal: Remove manual token copying and use QTS administrator identity for explicit Web QPKG updates.

Current release v0.1.5 uses a manual local token. The new integration is **not ready for deployment** and must remain an unmerged draft until QTS 5.x device validation.

QNAP's authLogin.cgi has an admin flag in documented XML responses, but the documentation is old. On QTS 5.x, HTTP/HTTPS redirection, 2FA, session invalidation, and permissions vary with device settings. Loopback authentication may behave differently from the user's browser session. Do not assume that a QTS login in another tab grants permission to this app at :8778.

Requirements before shipping:
- Serve the update interface through authenticated QTS HTTPS proxy or independently secured HTTPS endpoint. Never collect NAS admin passwords over unencrypted port 8778.
- Validate QTS administrative authorization against current session and handle 2FA without bypassing it; no plain password-based loopback shortcut.
- Strong session expiration, HttpOnly/Secure/SameSite cookies, CSRF defenses, rate limits, logout, and re-auth for destructive update.
- Keep fixed GitHub repo and asset allowlist, package SHA256 verification, restricted installer command, detached update worker, and failure recovery.
- In UI, only "Check updates" then "Install" plus confirmation, no token controls.
- Tests against unauthorized requests, forged origins, missing cookies, expired session, 2FA requirements, and NAS reboot.
- If the QTS session integration cannot be validated on TS-253Be, leave update API token-protected (existing implementation) and do not expose an unauthenticated replacement.

This draft contains an exploratory adapter only; it is not wired into the running server and must not be merged as proof of security.
