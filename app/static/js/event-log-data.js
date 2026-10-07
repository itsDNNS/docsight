/* ── Event log data rules ──
   Pure functions behind the event log: day sections, runs of repeated events
   and acknowledgement bookkeeping. No DOM access, so they run unchanged in the
   browser and in Node tests. */
(function (root, factory) {
    'use strict';
    var api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) Object.defineProperty(root, 'DOCSightEventLogData', {
        configurable: false,
        writable: false,
        value: api
    });
})(typeof window !== 'undefined' ? window : null, function () {
    'use strict';

    var SEVERITY_RANK = {info: 0, warning: 1, critical: 2};

    function severity(event) {
        var value = String((event && event.severity) || '').toLowerCase();
        return Object.prototype.hasOwnProperty.call(SEVERITY_RANK, value) ? value : 'info';
    }

    function worstSeverity(events) {
        return events.reduce(function (worst, event) {
            var current = severity(event);
            return SEVERITY_RANK[current] > SEVERITY_RANK[worst] ? current : worst;
        }, 'info');
    }

    /* Timestamps arrive already localized to the configured time zone, so the
       calendar day is the date part of the string. */
    function dayKey(event) {
        var match = /^(\d{4}-\d{2}-\d{2})/.exec(String((event && event.timestamp) || ''));
        return match ? match[1] : '';
    }

    function unacknowledged(events) {
        return events.filter(function (event) { return !event.acknowledged; });
    }

    /* Events are newest first. Consecutive events of the same type on the same day
       collapse into one run (e.g. a flapping health state); single events stay as they are. */
    function buildTimeline(events) {
        var days = [];
        var currentDay = null;
        var run = null;

        function closeRun() {
            if (!run) return;
            if (run.length === 1) {
                currentDay.items.push({kind: 'event', key: 'e' + run[0].id, event: run[0]});
            } else {
                currentDay.items.push({
                    kind: 'group',
                    key: 'g' + run[0].id,
                    eventType: run[0].event_type,
                    severity: worstSeverity(run),
                    events: run,
                    newest: run[0],
                    oldest: run[run.length - 1],
                    unacknowledged: unacknowledged(run).length
                });
            }
            run = null;
        }

        (events || []).forEach(function (event) {
            var day = dayKey(event);
            if (!currentDay || currentDay.day !== day) {
                closeRun();
                currentDay = {day: day, items: [], count: 0};
                days.push(currentDay);
            }
            currentDay.count += 1;
            if (run && run[0].event_type === event.event_type) {
                run.push(event);
                return;
            }
            closeRun();
            run = [event];
        });
        closeRun();
        return days;
    }

    function unacknowledgedIds(events) {
        return unacknowledged(events || []).map(function (event) { return event.id; });
    }

    /* Marks the given ids acknowledged in place and returns how many changed. */
    function markAcknowledged(events, ids) {
        var wanted = {};
        (ids || []).forEach(function (id) { wanted[id] = true; });
        var changed = 0;
        (events || []).forEach(function (event) {
            if (wanted[event.id] && !event.acknowledged) {
                event.acknowledged = 1;
                changed += 1;
            }
        });
        return changed;
    }

    /* Undoes markAcknowledged for the given ids and returns how many changed. */
    function markUnacknowledged(events, ids) {
        var wanted = {};
        (ids || []).forEach(function (id) { wanted[id] = true; });
        var changed = 0;
        (events || []).forEach(function (event) {
            if (wanted[event.id] && event.acknowledged) {
                event.acknowledged = 0;
                changed += 1;
            }
        });
        return changed;
    }

    /* Journal notes join the day sections they belong to. Notes carry a date
       but no time, so they lead their day. Only days inside the loaded span get
       notes: from oldestDay (null while every older event is loaded) to newestDay;
       a day with notes but no events gets its own section. */
    function addNotes(days, notes, span) {
        var oldest = span && span.oldestDay;
        var newest = span && span.newestDay;
        var result = (days || []).map(function (day) {
            return {day: day.day, items: day.items.slice(), count: day.count};
        });
        var byDay = {};
        result.forEach(function (day) { byDay[day.day] = day; });
        var inSpan = (notes || []).filter(function (note) {
            var day = String(note.date || '');
            return /^\d{4}-\d{2}-\d{2}$/.test(day) && (!oldest || day >= oldest) && (!newest || day <= newest);
        }).sort(function (a, b) { return b.id - a.id; });
        var leading = {};
        inSpan.forEach(function (note) {
            var day = byDay[note.date];
            if (!day) {
                day = {day: note.date, items: [], count: 0};
                byDay[note.date] = day;
                result.push(day);
            }
            var at = leading[note.date] || 0;
            day.items.splice(at, 0, {kind: 'note', key: 'n' + note.id, note: note});
            leading[note.date] = at + 1;
        });
        return result.sort(function (a, b) { return a.day < b.day ? 1 : a.day > b.day ? -1 : 0; });
    }

    return {
        severity: severity,
        worstSeverity: worstSeverity,
        dayKey: dayKey,
        buildTimeline: buildTimeline,
        unacknowledgedIds: unacknowledgedIds,
        markAcknowledged: markAcknowledged,
        markUnacknowledged: markUnacknowledged,
        addNotes: addNotes
    };
});
