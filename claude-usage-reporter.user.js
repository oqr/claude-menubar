// ==UserScript==
// @name         Claude Usage Reporter
// @namespace    https://claude.ai
// @version      1.0
// @description  Sends Claude usage data to the local menu bar app
// @match        https://claude.ai/*
// @grant        GM_xmlhttpRequest
// @connect      127.0.0.1
// @run-at       document-idle
// ==/UserScript==

(function() {
    'use strict';

    // Discover org ID from bootstrap API rather than hardcoding it
    let orgId = null;
    async function getOrgId() {
        if (orgId) return orgId;
        try {
            const r = await fetch('/api/bootstrap', { credentials: 'include' });
            const d = await r.json();
            orgId = d?.account?.memberships?.[0]?.organization?.uuid
                 || d?.organization?.uuid
                 || null;
        } catch (e) {}
        return orgId;
    }
    const LOCAL_ENDPOINT = 'http://127.0.0.1:19222/usage';
    const POLL_INTERVAL = 60000; // 60 seconds

    async function fetchAndReport() {
        try {
            const id = await getOrgId();
            if (!id) return;
            const USAGE_URL = `/api/organizations/${id}/usage`;
            const resp = await fetch(USAGE_URL, { credentials: 'include' });
            if (!resp.ok) return;
            const data = await resp.json();
            if (!data.five_hour) return;

            // Send to local menu bar app
            // Use GM_xmlhttpRequest to bypass CORS (Tampermonkey privilege)
            if (typeof GM_xmlhttpRequest !== 'undefined') {
                GM_xmlhttpRequest({
                    method: 'POST',
                    url: LOCAL_ENDPOINT,
                    headers: { 'Content-Type': 'application/json' },
                    data: JSON.stringify(data),
                });
            } else {
                // Fallback: direct fetch (may fail on CORS)
                fetch(LOCAL_ENDPOINT, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data),
                    mode: 'no-cors',
                }).catch(() => {});
            }
        } catch (e) {
            // Silently fail -- menu bar app will show stale data
        }
    }

    // Initial fetch after a short delay (let page settle)
    setTimeout(fetchAndReport, 3000);

    // Then poll every 60 seconds
    setInterval(fetchAndReport, POLL_INTERVAL);
})();
