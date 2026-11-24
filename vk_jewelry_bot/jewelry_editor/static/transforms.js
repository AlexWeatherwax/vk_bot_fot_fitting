/* Geometry shared by the canvas editor and its offline tests. */
(function (root) {
  "use strict";
  const clamp = (value, lo, hi) => Math.max(lo, Math.min(hi, value));
  function normalizeAngle(value) {
    const angle = ((value + 180) % 360 + 360) % 360 - 180;
    return Math.abs(angle) < 1e-9 ? 0 : angle;
  }
  function layerState(layer, settings, snapshot, unit) {
    const ratio = layer.scale_with_item === false ? 1 : settings.anchor_scale / snapshot.anchor_scale;
    const dx = (settings.offset_x - snapshot.offset_x) * unit * (layer.sign || 1);
    const dy = (settings.offset_y - snapshot.offset_y) * unit;
    let height = layer.height * ratio;
    if (layer.height_with_item_offset) {
      const axis = layer.height_axis || [0, 1];
      const hasRawHeight = Number.isFinite(layer.height_offset_origin);
      const origin = hasRawHeight ? layer.height_offset_origin : layer.height;
      height = origin + dx * axis[0] + dy * axis[1];
      if (hasRawHeight) height = Math.round(height);
      height = Math.max(layer.min_height || 1, height);
    }
    return {
      ...layer,
      x: layer.x + dx,
      y: layer.y + dy,
      width: layer.width * ratio,
      height,
      rotation: layer.rotation + (layer.rotate_with_item === false ? 0 : settings.rotation_offset - snapshot.rotation_offset),
    };
  }
  function point(layer, u, v) {
    const anchor = layer.anchor || [0.5, 0.5];
    const x = (u - anchor[0]) * layer.width;
    const y = (v - anchor[1]) * layer.height;
    const radians = -layer.rotation * Math.PI / 180;
    return {x: layer.x + x * Math.cos(radians) - y * Math.sin(radians),
      y: layer.y + x * Math.sin(radians) + y * Math.cos(radians)};
  }
  function corners(layer) {
    return [[0, 0], [1, 0], [1, 1], [0, 1]].map(([u, v]) => point(layer, u, v));
  }
  function contains(layer, position, padding = 0) {
    const radians = layer.rotation * Math.PI / 180;
    const dx = position.x - layer.x, dy = position.y - layer.y;
    const x = dx * Math.cos(radians) - dy * Math.sin(radians);
    const y = dx * Math.sin(radians) + dy * Math.cos(radians);
    const anchor = layer.anchor || [0.5, 0.5];
    return x >= -anchor[0] * layer.width - padding && x <= (1 - anchor[0]) * layer.width + padding
      && y >= -anchor[1] * layer.height - padding && y <= (1 - anchor[1]) * layer.height + padding;
  }
  function translate(settings, dx, dy, unit, sign = 1) {
    return {...settings, offset_x: clamp(settings.offset_x + dx / unit / sign, -3, 3),
      offset_y: clamp(settings.offset_y + dy / unit, -3, 3)};
  }
  function resize(settings, origin, start, current) {
    const oldDistance = Math.hypot(start.x - origin.x, start.y - origin.y);
    const distance = Math.hypot(current.x - origin.x, current.y - origin.y);
    if (oldDistance < 1) return {...settings};
    return {...settings, anchor_scale: clamp(settings.anchor_scale * distance / oldDistance, 0.05, 5)};
  }
  function rotate(settings, origin, start, current, snap = false) {
    const oldAngle = Math.atan2(start.y - origin.y, start.x - origin.x);
    const angle = Math.atan2(current.y - origin.y, current.x - origin.x);
    let value = normalizeAngle(settings.rotation_offset - (angle - oldAngle) * 180 / Math.PI);
    if (snap) value = Math.round(value / 15) * 15;
    return {...settings, rotation_offset: value};
  }
  const api = {clamp, normalizeAngle, layerState, point, corners, contains, translate, resize, rotate};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.JewelryTransforms = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
