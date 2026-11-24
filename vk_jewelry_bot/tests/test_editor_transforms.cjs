"use strict";
const {test} = require("node:test");
const assert = require("node:assert/strict");
const transforms = require("../jewelry_editor/static/transforms.js");

const close = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-8,
  `Expected ${expected}, got ${actual}`);
const snapshot = {anchor_scale: 1, offset_x: 0, offset_y: 0, rotation_offset: 0};
const layer = {x: 100, y: 200, width: 30, height: 90, rotation: 12,
  anchor: [0.2, 0.05], sign: 1, editable: true};

test("dragging either earring follows the pointer and keeps paired calibration linked", () => {
  const left = {...layer, x: 60, sign: -1};
  const right = {...layer, x: 240, sign: 1};
  const settings = transforms.translate(snapshot, 24, 12, 120, -1);
  close(settings.offset_x, -0.2);
  close(settings.offset_y, 0.1);
  const movedLeft = transforms.layerState(left, settings, snapshot, 120);
  const movedRight = transforms.layerState(right, settings, snapshot, 120);
  close(movedLeft.x, 84);
  close(movedRight.x, 216);
  close(movedLeft.y, 212);
  close(movedRight.y, 212);
});

test("the image anchor stays fixed while an off-center layer rotates and resizes", () => {
  for (const rotation of [-180, -71, 0, 23, 179]) {
    const current = {...layer, rotation, width: 135, height: 405};
    const anchor = transforms.point(current, ...current.anchor);
    close(anchor.x, current.x);
    close(anchor.y, current.y);
    const inside = transforms.point(current, 0.6, 0.7);
    assert.equal(transforms.contains(current, inside), true);
    const outside = transforms.point(current, 1.2, 0.7);
    assert.equal(transforms.contains(current, outside), false);
  }
});

test("live positions convert normalized calibration into exact pixel deltas", () => {
  const current = {anchor_scale: 1.75, offset_x: -0.125,
    offset_y: 0.2, rotation_offset: 37};
  const result = transforms.layerState(layer, current, snapshot, 200);
  close(result.x, 75);
  close(result.y, 240);
  close(result.width, 52.5);
  close(result.height, 157.5);
  close(result.rotation, 49);
});

test("pendant chain follows the attachment and adjusts height while retaining width and angle", () => {
  const chain = {...layer, editable: false, scale_with_item: false, rotate_with_item: false,
    height_with_item_offset: true, height_axis: [0, 1], min_height: 1};
  const settings = {anchor_scale: 2, offset_x: 0.15, offset_y: -0.2, rotation_offset: 50};
  const result = transforms.layerState(chain, settings, snapshot, 100);
  close(result.x, 115);
  close(result.y, 180);
  close(result.width, layer.width);
  close(result.height, layer.height - 20);
  close(result.rotation, layer.rotation);
});

test("chain height follows the body's tilted down axis while its top stays on the neckline", () => {
  const chain = {...layer, width: 30, height: 50, rotation: -36.86989764584402,
    anchor: [.5, 1], editable: false, scale_with_item: false, rotate_with_item: false,
    height_with_item_offset: true, height_axis: [-.6, .8], min_height: 1};
  const settings = {...snapshot, offset_x: -.12, offset_y: .16};
  const result = transforms.layerState(chain, settings, snapshot, 100);
  close(result.x, 88);
  close(result.y, 216);
  close(result.height, 70);
  const before = transforms.point(chain, .5, 0);
  const after = transforms.point(result, .5, 0);
  close(after.x, before.x);
  close(after.y, before.y);
});

test("chain height remains positive and does not follow pendant size or rotation", () => {
  const chain = {...layer, height: 50, scale_with_item: false, rotate_with_item: false,
    height_with_item_offset: true, height_axis: [0, 1], min_height: 1};
  const adjusted = transforms.layerState(chain,
    {...snapshot, anchor_scale: 3, rotation_offset: 80}, snapshot, 100);
  close(adjusted.width, chain.width);
  close(adjusted.height, chain.height);
  close(adjusted.rotation, chain.rotation);
  const aboveNeck = transforms.layerState(chain,
    {...snapshot, offset_y: -2}, snapshot, 100);
  close(aboveNeck.height, 1);
});

test("a chain clamped above its neckline only lengthens once the attachment passes it", () => {
  const chain = {...layer, height: 1, scale_with_item: false, rotate_with_item: false,
    height_with_item_offset: true, height_axis: [0, 1], min_height: 1,
    height_offset_origin: -10.4};
  const belowStart = transforms.layerState(chain,
    {...snapshot, offset_y: .05}, snapshot, 100);
  close(belowStart.height, 1);
  const pastNeck = transforms.layerState(chain,
    {...snapshot, offset_y: .15}, snapshot, 100);
  close(pastNeck.height, 5);
});

test("corner resizing preserves proportions and uses the same saved scale factor", () => {
  const settings = {...snapshot, anchor_scale: 1.2};
  const resized = transforms.resize(settings, {x: 100, y: 100},
    {x: 200, y: 200}, {x: 300, y: 300});
  close(resized.anchor_scale, 2.4);
  const rendered = transforms.layerState(layer, resized, settings, 100);
  close(rendered.width / rendered.height, layer.width / layer.height);
  close(rendered.width, layer.width * 2);
});

test("rotation handle follows clockwise pointer motion with Pillow's angle convention", () => {
  const rotated = transforms.rotate(snapshot, {x: 100, y: 100},
    {x: 150, y: 100}, {x: 100, y: 150});
  close(rotated.rotation_offset, -90);
  const point = transforms.point({x: 100, y: 100, width: 100, height: 100,
    rotation: rotated.rotation_offset, anchor: [.5, .5]}, 1, .5);
  close(point.x, 100);
  close(point.y, 150);
});

test("rotation crossing the angular seam stays continuous and can snap to fifteen degrees", () => {
  const start = {x: Math.cos(179 * Math.PI / 180), y: Math.sin(179 * Math.PI / 180)};
  const end = {x: Math.cos(-179 * Math.PI / 180), y: Math.sin(-179 * Math.PI / 180)};
  const rotated = transforms.rotate(snapshot, {x: 0, y: 0}, start, end);
  close(rotated.rotation_offset, -2);
  const snapped = transforms.rotate({...snapshot, rotation_offset: 11},
    {x: 0, y: 0}, {x: 1, y: 0}, {x: 1, y: 0}, true);
  close(snapped.rotation_offset, 15);
});

test("interactive changes respect backend bounds and ignore degenerate resize handles", () => {
  const moved = transforms.translate(snapshot, 10000, -10000, 100, 1);
  assert.equal(moved.offset_x, 3);
  assert.equal(moved.offset_y, -3);
  const huge = transforms.resize(snapshot, {x: 0, y: 0}, {x: 1, y: 0}, {x: 1000, y: 0});
  assert.equal(huge.anchor_scale, 5);
  const tiny = transforms.resize(snapshot, {x: 0, y: 0}, {x: 1000, y: 0}, {x: 1, y: 0});
  assert.equal(tiny.anchor_scale, 0.05);
  const degenerate = transforms.resize(snapshot, {x: 0, y: 0}, {x: 0, y: 0}, {x: 50, y: 50});
  assert.deepEqual(degenerate, snapshot);
});
