"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const panels = {
  "try-full": { hidden: true },
  "try-sift": { hidden: false },
};
const buttons = ["full", "sift"].map((view) => ({
  dataset: { demoView: view },
  attributes: {},
  handler: null,
  addEventListener(_event, callback) {
    this.handler = callback;
  },
  setAttribute(name, value) {
    this.attributes[name] = value;
  },
}));
const document = {
  querySelectorAll(selector) {
    if (selector === '[role="tab"]') return [];
    if (selector === "[data-demo-view]") return buttons;
    throw new Error(`unexpected selector: ${selector}`);
  },
  getElementById(id) {
    assert.ok(panels[id], `unknown panel ${id}`);
    return panels[id];
  },
};

vm.runInNewContext(fs.readFileSync("site/script.js", "utf8"), { document });
assert.equal(typeof buttons[0].handler, "function");
assert.equal(typeof buttons[1].handler, "function");

buttons[0].handler();
assert.equal(panels["try-full"].hidden, false);
assert.equal(panels["try-sift"].hidden, true);
assert.equal(buttons[0].attributes["aria-pressed"], "true");
assert.equal(buttons[1].attributes["aria-pressed"], "false");

buttons[1].handler();
assert.equal(panels["try-full"].hidden, true);
assert.equal(panels["try-sift"].hidden, false);
assert.equal(buttons[0].attributes["aria-pressed"], "false");
assert.equal(buttons[1].attributes["aria-pressed"], "true");

process.stdout.write("Site demo toggles: both panels and aria-pressed states switch correctly.\n");
