/* view-state.js — view state in the URL hash
   "#trends?range=7d" reopens a view with the same range, direction or filter after
   a reload or from a shared link. Views apply the state when they open and write it
   when the user changes it; replaceState keeps the browser history clean. */
function docsightReadViewState(view) {
    var hash = location.hash.replace('#', '');
    var qIdx = hash.indexOf('?');
    if (qIdx === -1 || hash.substring(0, qIdx) !== view) return {};
    var params = {};
    new URLSearchParams(hash.substring(qIdx + 1)).forEach(function(value, key) { params[key] = value; });
    return params;
}

function docsightWriteViewState(view, params) {
    if (typeof currentView !== 'undefined' && currentView !== view) return;
    var query = new URLSearchParams();
    Object.keys(params).forEach(function(key) {
        var value = params[key];
        if (value !== null && value !== undefined && value !== '') query.set(key, String(value));
    });
    var text = query.toString();
    var hash = '#' + view + (text ? '?' + text : '');
    if (location.hash !== hash) history.replaceState(null, '', hash);
}

/* Selects the option of a segmented group whose `attr` equals `value`; false when none does. */
function docsightSelectSegment(groupId, attr, value) {
    var group = document.getElementById(groupId);
    if (!group || value === undefined || value === null) return false;
    var wanted = String(value);
    var matches = function(option) { return option.getAttribute(attr) === wanted; };
    if (!Array.prototype.some.call(group.querySelectorAll('.segmented-option'), matches)) return false;
    syncSegments(group, matches);
    return true;
}
