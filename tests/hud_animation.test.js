const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

test("ring positions remain continuous when audio level and state change", () => {
  const html = fs.readFileSync(path.join(__dirname, "..", "hud.html"), "utf8");
  const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
  let nextFrame;
  let rotations = [];
  let arcs = [];
  const gradient = { addColorStop() {} };
  const context = {
    createRadialGradient: () => gradient,
    createConicGradient: () => gradient,
    rotate: angle => rotations.push(angle),
    arc: (x, y, radius, start) => arcs.push({ radius, start }),
  };
  for (const method of ["beginPath", "stroke", "clearRect", "fill", "save", "restore",
    "translate", "moveTo", "lineTo", "setLineDash", "fillText"]) {
    context[method] = () => {};
  }
  const elements = {
    c: { getContext: () => context },
    heard: {},
    reply: {},
    lines: { classList: { toggle() {} } },
  };
  const sandbox = {
    document: {
      getElementById: id => elements[id],
      documentElement: { style: { setProperty() {} } },
    },
    performance: { now: () => 0 },
    requestAnimationFrame: callback => { nextFrame = callback; },
    window: { addEventListener() {} },
  };
  vm.runInNewContext(script, sandbox);

  function draw(time) {
    rotations = [];
    arcs = [];
    nextFrame(time);
    return [
      rotations[0],
      arcs.find(arc => arc.radius === 276).start,
      arcs.find(arc => arc.radius === 250).start,
    ];
  }

  let previous = draw(3600000);
  for (const [time, update] of [
    [3600016, { level: 1 }],
    [3600032, { state: "off" }],
    [3600048, { state: "listen", level: 0 }],
  ]) {
    sandbox.window.hud.update(update);
    const current = draw(time);
    for (let i = 0; i < current.length; i++) {
      assert.ok(Math.abs(current[i] - previous[i]) < 0.05, `ring ${i} jumped after state change`);
    }
    previous = current;
  }
});
