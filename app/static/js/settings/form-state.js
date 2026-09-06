(function(root) {
    'use strict';
    function record(field) {
        var result = {
            key: JSON.stringify([field.name, field.id || '', field.type, field.index || 0]),
            name: field.name,
            id: field.id || '',
            type: field.type,
            owner: field.owner || 'config',
            instant: field.instant === true
        };
        if (field.secret) result.secretEditVersion = Number(field.secretEditVersion || 0);
        else result.value = field.value;
        return result;
    }
    function project(records, manualOnly) {
        return records.filter(function(field) { return !manualOnly || !field.instant; })
            .slice().sort(function(a, b) { return a.key < b.key ? -1 : a.key > b.key ? 1 : 0; });
    }
    function dirty(current, baseline, manualOnly) {
        return JSON.stringify(project(current, manualOnly)) !== JSON.stringify(project(baseline, manualOnly));
    }
    function acknowledge(baseline, sent, owner) {
        return baseline.filter(function(field) { return field.owner !== owner; })
            .concat(sent.filter(function(field) { return field.owner === owner; }));
    }
    var state = {record: record, project: project, dirty: dirty, acknowledge: acknowledge};
    if (typeof module === 'object' && module.exports) module.exports = state;
    else root.DOCSightSettings = {state: state};
})(typeof window === 'undefined' ? globalThis : window);
