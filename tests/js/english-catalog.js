'use strict';

/* The English translations a page gets: the core catalog plus each module catalog
   under `<module id>.<key>` and, unless the key is taken, under the bare key. */
const fs = require('node:fs');
const path = require('node:path');

const app = path.resolve(__dirname, '../../app');
const read = file => JSON.parse(fs.readFileSync(path.join(app, file), 'utf8'));

module.exports = function englishCatalog() {
    const T = read('i18n/en.json');
    delete T._meta;
    for (const dir of fs.readdirSync(path.join(app, 'modules')).sort()) {
        if (!fs.existsSync(path.join(app, 'modules', dir, 'i18n/en.json'))) continue;
        const id = read(`modules/${dir}/manifest.json`).id;
        for (const [key, value] of Object.entries(read(`modules/${dir}/i18n/en.json`))) {
            T[`${id}.${key}`] = value;
            if (!(key in T)) T[key] = value;
        }
    }
    return T;
};
