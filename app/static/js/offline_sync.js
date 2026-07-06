(function () {
    const queueKey = 'turnjoy_assignment_sync_queue';

    function readQueue() {
        try {
            return JSON.parse(localStorage.getItem(queueKey) || '[]');
        } catch (error) {
            return [];
        }
    }

    function writeQueue(items) {
        localStorage.setItem(queueKey, JSON.stringify(items));
    }

    function enqueueAssignment(payload) {
        const items = readQueue();
        items.push(Object.assign({}, payload, {
            client_sync_id: payload.client_sync_id || `${Date.now()}-${Math.random().toString(16).slice(2)}`
        }));
        writeQueue(items);
    }

    async function flushAssignments() {
        const items = readQueue();
        if (!items.length || !navigator.onLine) {
            return;
        }

        const response = await fetch('/admin/api/offline-sync/assignments', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify({ items })
        });

        if (!response.ok) {
            return;
        }

        const result = await response.json();
        const syncedIds = new Set((result.items || [])
            .filter((item) => item.status === 'synced')
            .map((item) => item.client_sync_id));
        writeQueue(items.filter((item) => !syncedIds.has(item.client_sync_id)));
    }

    window.TurnjoyOfflineSync = {
        enqueueAssignment,
        flushAssignments
    };

    window.addEventListener('online', flushAssignments);
    document.addEventListener('visibilitychange', function () {
        if (!document.hidden) {
            flushAssignments();
        }
    });
})();
