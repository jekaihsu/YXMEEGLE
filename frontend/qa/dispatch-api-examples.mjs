import fs from 'node:fs';
const captured=JSON.parse(fs.readFileSync(new URL('../../docs/dispatch-publish-api-examples.json',import.meta.url),'utf8'));
export const examples=captured.examples;
export function example(name){const found=examples.find(e=>e.name===name);if(!found)throw Error(`Missing captured example ${name}`);return structuredClone(found)}
export const response=name=>example(name).response.body;
