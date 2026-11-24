"use strict";
const $ = id => document.getElementById(id);
const T = window.JewelryTransforms;
const canvas = $("canvas"), ctx = canvas.getContext("2d");
const layerCanvas = document.createElement("canvas");
const defaults = {
  anchor_scale: 1, offset_x: 0, offset_y: 0, rotation_offset: 0,
  overlay_anchor: null, pair_overlay_anchors: null, pair_image: false, single_ear: false,
  brooch_side: "left", chain_color: "silver", kaffy_side: "left", kaffy_anchor_y: .8,
  hairpin_style: "updo", hairpin_side: "left", hairpin_head_fraction: null,
};
const categoryNames = {earrings:"Серьги",pendant:"Кулон",ring:"Кольцо",beads:"Колье / бусы",diadem:"Диадема",hairpin:"Заколка / шпилька",brooch:"Брошь",bracelet:"Браслет",kaffy:"Кафф",set:"Набор"};
const sideOptions = [["left","Слева"],["right","Справа"]];
const fields = [
  ["offset_x","Положение по горизонтали",0,-3,3,.0001],
  ["offset_y","Положение по вертикали",0,-3,3,.0001],
  ["overlay_anchor_x","Крепление внутри изображения: X","",0,1,.001],
  ["overlay_anchor_y","Крепление внутри изображения: Y","",0,1,.001],
  ["chain_color","Цепочка","silver",[
    ["silver","Серебристая"],["gold","Золотистая"],["none","Без цепочки"],
    ["front_v3_silver","Серебро · фронтальная"],["front_v3_copper","Медь · фронтальная"],
    ["curated_silver","Серебро · тонкая"],["curated_gold","Золото · тонкая"],
    ["curated_brass","Латунь"],["curated_copper","Медь"],["curated_dark_silver","Тёмное серебро"],
  ]],
  ["brooch_side","Сторона броши","left",sideOptions],
  ["kaffy_side","Ухо для каффа","left",sideOptions],
  ["kaffy_anchor_y","Крепление каффа по высоте",.8,0,1,.001],
  ["hairpin_style","Расположение заколки","updo",[["updo","На макушке"],["side","Над ухом"],["bun","В пучке"]]],
  ["hairpin_side","Сторона заколки","left",sideOptions],
  ["hairpin_head_fraction","Конец декоративной головки","",.001,.999,.001],
];
for (const [id,labelText,value,options,max,step] of fields) {
  const label = document.createElement("label");
  label.textContent = labelText;
  const input = document.createElement(Array.isArray(options) ? "select" : "input");
  input.id = id;
  if (Array.isArray(options)) {
    label.classList.add("wide");
    for (const [key,title] of options) input.add(new Option(title,key));
  } else {
    input.type = "number"; input.min = options; input.max = max; input.step = step;
  }
  input.value = value;
  label.append(input); $("fields").append(label);
}
const S = {
  entries:[], references:[], referenceDefaults:{}, catalogRevision:"", editRevision:"",
  entry:null, parentSet:null, asset:null, photo:null, customPhoto:false, pairAnchors:null,
  result:null, referenceImage:null, selectedLayer:0, live:false, handles:true,
  dirty:false, busy:false, version:0, serial:0, epoch:0, referenceSerial:0,
  timer:null, checkTimer:null, history:[], initialFit:null, drag:null, sliderStart:null,
};
function status(text,error=false) {
  $("status").textContent = text; $("status").classList.toggle("error",error);
}
function renderStatus(text,error=false) {
  $("renderStatus").textContent = text; $("renderStatus").classList.toggle("error",error);
}
function settings() {
  const p = {...defaults, name:$("name").value.trim() || "Предпросмотр", category:$("category").value};
  p.anchor_scale = Number($("anchor_scale").value);
  p.rotation_offset = Number($("rotation_offset").value);
  for (const [id,,,options] of fields) p[id] = Array.isArray(options) ? $(id).value : ($(id).value === "" ? null : Number($(id).value));
  const x = p.overlay_anchor_x, y = p.overlay_anchor_y;
  p.overlay_anchor = x === null && y === null ? null : [x,y];
  delete p.overlay_anchor_x; delete p.overlay_anchor_y;
  p.pair_image = p.category === "earrings" && $("earMode").value === "pair";
  p.single_ear = p.category === "earrings" && $("earMode").value === "mono";
  p.pair_overlay_anchors = p.pair_image ? S.pairAnchors : null;
  if (p.category !== "hairpin") p.hairpin_head_fraction = null;
  return p;
}
function payload() {
  return {settings:settings(), asset:S.asset, photo:S.photo, revision:S.editRevision,
    editing_id:S.parentSet?.id || S.entry?.id || null,
    component_id:S.parentSet && S.entry?.category !== "set" ? S.entry.id : null,
    replace:!!S.entry};
}
function applyValues(entry) {
  const p = {...defaults,...entry};
  $("name").value = entry.name || "";
  $("category").value = entry.category || "earrings";
  $("anchor_scale").value = p.anchor_scale;
  $("rotation_offset").value = p.rotation_offset;
  for (const [id,,,options] of fields) if (!id.startsWith("overlay_anchor_")) $(id).value = p[id] ?? "";
  $("overlay_anchor_x").value = p.overlay_anchor?.[0] ?? "";
  $("overlay_anchor_y").value = p.overlay_anchor?.[1] ?? "";
  $("earMode").value = p.pair_image ? "pair" : p.single_ear ? "mono" : "single";
  S.pairAnchors = p.pair_overlay_anchors;
  visibility(); syncControls();
}
function applyFit(p) {
  for (const key of ["anchor_scale","rotation_offset","offset_x","offset_y"]) $(key).value = p[key];
  syncControls();
}
function syncControls() {
  const scale = Number($("anchor_scale").value), angle = Number($("rotation_offset").value);
  $("scaleNumber").value = (scale * 100).toFixed(1);
  $("rotationNumber").value = angle.toFixed(1);
  $("scaleOutput").textContent = (scale * 100).toFixed(0) + "%";
  $("rotationOutput").textContent = angle.toFixed(1) + "°";
  $("undo").disabled = !S.history.length || S.busy;
  $("resetFit").disabled = !S.asset || !S.initialFit || S.busy;
  $("preview").disabled = !S.asset || S.busy;
  $("save").disabled = !S.asset || !S.dirty || S.busy || S.entry?.editable === false;
  $("delete").hidden = !S.entry;
  $("delete").disabled = S.busy;
  $("delete").textContent = S.parentSet ? "Удалить набор из каталога" : "Удалить из каталога";
  $("component").disabled = S.busy;
  $("renameSet").disabled = S.busy;
  $("save").textContent = S.entry ? "Сохранить изменения" : "Добавить в каталог";
  $("saveState").textContent = S.busy ? "Сохраняем…" : S.dirty ? "Есть несохранённые изменения" : S.entry ? "Сохранено в каталоге" : "Новый черновик";
  $("saveState").classList.toggle("dirty",S.dirty);
}
function visibility() {
  const cat = $("category").value;
  for (const [id] of fields) {
    const visible = id.startsWith("kaffy") ? cat === "kaffy" :
      id.startsWith("hairpin") ? cat === "hairpin" : id === "chain_color" ? cat === "pendant" :
      id === "brooch_side" ? cat === "brooch" : true;
    $(id).parentElement.hidden = !visible;
  }
  $("earModeField").hidden = cat !== "earrings";
}
function markDirty() {
  S.dirty = true; S.version++; syncControls();
  $("workspaceTitle").textContent = (S.entry?.category === "set" ? $("setName").value : $("name").value).trim() || "Новое украшение";
}
function pushHistory(p=settings()) {
  const last = S.history.at(-1);
  if (!last || JSON.stringify(last) !== JSON.stringify(p)) S.history.push(structuredClone(p));
  if (S.history.length > 40) S.history.shift();
  syncControls();
}
function invalidate() {
  clearTimeout(S.timer); S.serial++; S.result = null; S.live = false;
  $("canvasLoading").hidden = true; draw();
}
async function api(url,data,method="POST",raw=false) {
  const response = await fetch(url,data === undefined ? {} : {
    method, headers:{"X-Editor-Request":"1",...(!raw ? {"Content-Type":"application/json"} : {})},
    body:raw ? data : JSON.stringify(data),
  });
  let value;
  try { value = await response.json(); } catch { throw Error("Не удалось прочитать ответ сервера."); }
  if (!response.ok) throw Error(typeof value.detail === "string" ? value.detail : "Проверьте введённые значения.");
  return value;
}
function loadImage(url) {
  return new Promise((resolve,reject) => {
    const image = new Image(); image.onload = () => resolve(image);
    image.onerror = () => reject(Error("Не удалось открыть изображение.")); image.src = url;
  });
}
async function confirmAction(title,text,label="Продолжить",danger=false) {
  const dialog = $("confirmDialog");
  $("dialogTitle").textContent = title; $("dialogText").textContent = text;
  $("dialogConfirm").textContent = label;
  $("dialogConfirm").classList.toggle("danger-confirm",danger);
  dialog.returnValue = ""; dialog.showModal(); $("dialogCancel").focus();
  return new Promise(resolve => dialog.addEventListener("close",() => resolve(dialog.returnValue === "confirm"),{once:true}));
}
async function discardAllowed() {
  return !S.dirty || await confirmAction("Оставить изменения?","В этом черновике есть несохранённые изменения. Перейти к другому украшению и не сохранять их?","Не сохранять");
}
function renderCatalog() {
  const query = $("catalogSearch").value.trim().toLocaleLowerCase("ru");
  const cat = $("catalogFilter").value;
  const items = S.entries.filter(e => (!cat || e.category === cat) && e.name.toLocaleLowerCase("ru").includes(query));
  $("catalogCount").textContent = S.entries.length;
  const list = $("catalogList"); list.replaceChildren();
  for (const entry of items) {
    const button = document.createElement("button");
    button.type = "button"; button.className = "catalog-item";
    button.classList.toggle("selected",(S.parentSet?.id || S.entry?.id) === entry.id);
    button.setAttribute("aria-pressed",String((S.parentSet?.id || S.entry?.id) === entry.id));
    button.dataset.id = entry.id;
    const image = document.createElement("img");
    image.className = "catalog-thumb"; image.alt = ""; image.loading = "lazy";
    image.src = "api/image/" + encodeURIComponent(entry.id) + "?v=" + S.catalogRevision.slice(0,10);
    const text = document.createElement("span"), name = document.createElement("strong"), category = document.createElement("small");
    name.textContent = entry.name; category.textContent = categoryNames[entry.category] || entry.category;
    text.append(name,category); button.append(image,text);
    button.addEventListener("click",() => openEntry(entry)); list.append(button);
  }
  if (!items.length) {
    const empty = document.createElement("p"); empty.className = "empty-list";
    empty.textContent = S.entries.length ? "По вашему запросу ничего не найдено." : "Пока здесь пусто. Добавьте первое украшение.";
    list.append(empty);
  }
}
async function refreshCatalog(initial=false) {
  const data = await api("api/catalog"); S.entries = data.entries; S.catalogRevision = data.revision;
  if (initial) {
    for (const cat of data.categories) $("category").add(new Option(categoryNames[cat.value] || cat.title,cat.value));
    for (const cat of [...data.categories,{value:"set",title:"Наборы"}]) $("catalogFilter").add(new Option(categoryNames[cat.value] || cat.title,cat.value));
  }
  renderCatalog();
}
async function chooseReference(id) {
  if (!id) return;
  const n = ++S.referenceSerial; S.serial++; clearTimeout(S.timer);
  const [data,image] = await Promise.all([api("api/reference/" + encodeURIComponent(id),{}),loadImage("api/reference/" + encodeURIComponent(id))]);
  if (n !== S.referenceSerial) return;
  S.photo = data.token; S.customPhoto = false; S.referenceImage = image; $("reference").value = id;
  S.result = null; draw();
}
async function matchingReference() {
  if (S.customPhoto) return;
  const cat = $("category").value;
  const key = cat === "hairpin" && $("hairpin_style").value === "bun" ? "bun" : S.referenceDefaults[cat];
  if (key && (key !== $("reference").value || !S.photo)) await chooseReference(key);
}
function schedulePreview(delay=300) {
  clearTimeout(S.timer);
  if (S.asset && S.entry?.editable !== false) S.timer = setTimeout(preview,delay);
}
async function preview() {
  clearTimeout(S.timer);
  if (!S.asset || S.entry?.editable === false || S.busy || S.drag) return;
  const epoch = S.epoch, serial = ++S.serial, snapshot = payload();
  $("canvasLoading").hidden = false; renderStatus("Обновляем точную примерку…");
  try {
    const response = await api("api/preview",snapshot);
    const [precise,base,images,masks] = await Promise.all([
      loadImage(response.image),loadImage(response.base_image || response.image),
      Promise.all((response.layers || []).map(layer => loadImage(layer.image))),
      Promise.all((response.layers || []).map(layer => layer.occlusion_mask ? loadImage(layer.occlusion_mask) : null)),
    ]);
    if (epoch !== S.epoch || serial !== S.serial || S.drag) return;
    S.result = {...response, precise,base,images,masks,snapshot:response.settings || snapshot.settings};
    S.selectedLayer = Math.max(0,(response.layers || []).findIndex(layer => layer.editable !== false));
    S.live = false; draw();
    renderStatus("Посадка актуальна. Перемещайте украшение или тяните метки рамки.");
  } catch(error) {
    if (epoch !== S.epoch || serial !== S.serial) return;
    renderStatus(error.message,true);
  } finally {
    if (epoch === S.epoch && serial === S.serial) $("canvasLoading").hidden = true;
    syncControls();
  }
}
function currentLayers() {
  if (!S.result?.layers) return [];
  const p = settings();
  return S.result.layers.map(layer => T.layerState(layer,p,S.result.snapshot,S.result.unit));
}
function layerFrame(layer) {
  const corners = T.corners(layer), top = T.point(layer,.5,0);
  const factor = canvas.width / Math.max(1,canvas.getBoundingClientRect().width);
  const r = -layer.rotation * Math.PI / 180;
  return {corners,rotate:{x:top.x + Math.sin(r)*30*factor,y:top.y - Math.cos(r)*30*factor},top,factor};
}
function drawPreviewLayer(context,layer,image,mask,surface,width,height) {
  const target = mask ? surface.getContext("2d") : context;
  if (mask) {
    if (surface.width !== width || surface.height !== height) { surface.width = width; surface.height = height; }
    target.clearRect(0,0,width,height);
  }
  target.save(); target.translate(layer.x,layer.y); target.rotate(-layer.rotation*Math.PI/180);
  const anchor = layer.anchor || [.5,.5];
  target.drawImage(image,-anchor[0]*layer.width,-anchor[1]*layer.height,layer.width,layer.height);
  target.restore();
  if (mask) {
    // The face mask belongs to the photograph, so dragging the chain cannot move it.
    target.save(); target.globalCompositeOperation = "destination-out";
    target.drawImage(mask,0,0,width,height); target.restore();
    context.drawImage(surface,0,0,width,height);
  }
}
function draw() {
  const result = S.result;
  const background = result?.base || S.referenceImage;
  if (!background) {
    ctx.clearRect(0,0,canvas.width,canvas.height); $("canvasEmpty").hidden = false;
    $("canvasEmpty").classList.remove("reference-visible"); return;
  }
  const width = result?.width || background.naturalWidth, height = result?.height || background.naturalHeight;
  if (canvas.width !== width || canvas.height !== height) { canvas.width = width; canvas.height = height; }
  ctx.clearRect(0,0,width,height);
  const layers = currentLayers();
  if (result && !S.live) ctx.drawImage(result.precise,0,0,width,height);
  else {
    ctx.drawImage(background,0,0,width,height);
    layers.forEach((layer,i) => {
      drawPreviewLayer(ctx,layer,result.images[i],result.masks?.[i],layerCanvas,width,height);
    });
  }
  $("canvasEmpty").hidden = !!S.asset || S.entry?.editable === false;
  $("canvasEmpty").classList.add("reference-visible");
  canvas.classList.toggle("interactive",layers.some(layer => layer.editable !== false) && !S.busy);
  if (!S.handles || !layers.length || S.busy) return;
  const layer = layers[S.selectedLayer]; if (!layer || layer.editable === false) return;
  const f = layerFrame(layer), radius = 4*f.factor;
  ctx.save(); ctx.strokeStyle = "#fdfdf4"; ctx.lineWidth = 2.5*f.factor;
  ctx.beginPath(); f.corners.forEach((p,i) => i ? ctx.lineTo(p.x,p.y) : ctx.moveTo(p.x,p.y)); ctx.closePath(); ctx.stroke();
  ctx.strokeStyle = "#355a48"; ctx.lineWidth = 1*f.factor; ctx.stroke();
  ctx.beginPath(); ctx.moveTo(f.top.x,f.top.y); ctx.lineTo(f.rotate.x,f.rotate.y); ctx.stroke();
  for (const point of [...f.corners,f.rotate]) {
    ctx.beginPath(); ctx.arc(point.x,point.y,radius,0,Math.PI*2);
    ctx.fillStyle="#fffef5"; ctx.fill(); ctx.stroke();
  }
  ctx.beginPath(); ctx.arc(layer.x,layer.y,3*f.factor,0,Math.PI*2); ctx.fillStyle="#b99567"; ctx.fill();
  ctx.restore();
}
function position(event) {
  const rect = canvas.getBoundingClientRect();
  return {x:(event.clientX-rect.left)*canvas.width/rect.width,y:(event.clientY-rect.top)*canvas.height/rect.height};
}
function hit(position) {
  const layers = currentLayers(), selected = layers[S.selectedLayer];
  if (selected && S.handles) {
    const frame = layerFrame(selected), radius = 14*frame.factor;
    if (Math.hypot(position.x-frame.rotate.x,position.y-frame.rotate.y) < radius) return {mode:"rotate",index:S.selectedLayer};
    if (frame.corners.some(p => Math.hypot(position.x-p.x,position.y-p.y) < radius)) return {mode:"resize",index:S.selectedLayer};
  }
  for (let i=layers.length-1;i>=0;i--) if (layers[i].editable !== false && T.contains(layers[i],position,8*(canvas.width/Math.max(1,canvas.clientWidth)))) return {mode:"move",index:i};
  return null;
}
canvas.addEventListener("pointerdown",event => {
  if (!S.result || S.busy || event.button !== 0) return;
  const point = position(event), target = hit(point); if (!target) return;
  clearTimeout(S.timer); S.serial++; $("canvasLoading").hidden = true;
  S.selectedLayer = target.index;
  const p = settings(), layer = currentLayers()[target.index];
  S.drag = {mode:target.mode,start:point,origin:{x:layer.x,y:layer.y},settings:p,sign:layer.sign || 1,moved:false};
  canvas.focus(); canvas.setPointerCapture(event.pointerId); canvas.classList.add("dragging"); event.preventDefault(); draw();
});
canvas.addEventListener("pointermove",event => {
  const point = position(event);
  if (!S.drag) {
    const target = S.result && !S.busy ? hit(point) : null;
    canvas.style.cursor = target?.mode === "move" ? "grab" : target?.mode === "rotate" ? "crosshair" : target?.mode === "resize" ? "nwse-resize" : "default";
    return;
  }
  const d = S.drag;
  if (!d.moved) { pushHistory(d.settings); d.moved = true; }
  let p;
  if (d.mode === "move") p = T.translate(d.settings,point.x-d.start.x,point.y-d.start.y,S.result.unit,d.sign);
  else if (d.mode === "resize") p = T.resize(d.settings,d.origin,d.start,point);
  else p = T.rotate(d.settings,d.origin,d.start,point,event.shiftKey);
  applyFit(p); S.live = true; markDirty(); draw();
});
function finishDrag(event) {
  if (!S.drag) return;
  const moved = S.drag.moved; S.drag = null; canvas.classList.remove("dragging");
  if (event && canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
  if (moved) preview();
}
canvas.addEventListener("pointerup",finishDrag);
canvas.addEventListener("pointercancel",finishDrag);
canvas.addEventListener("lostpointercapture",finishDrag);
canvas.addEventListener("keydown",event => {
  if (S.busy || !S.result || !["ArrowLeft","ArrowRight","ArrowUp","ArrowDown","+","=","-","[","]"].includes(event.key)) return;
  event.preventDefault(); const p = settings(); pushHistory(p);
  const step = event.shiftKey ? 10 : 1;
  const layer = currentLayers()[S.selectedLayer];
  if (event.key.startsWith("Arrow")) {
    const dx = event.key === "ArrowLeft" ? -step : event.key === "ArrowRight" ? step : 0;
    const dy = event.key === "ArrowUp" ? -step : event.key === "ArrowDown" ? step : 0;
    applyFit(T.translate(p,dx,dy,S.result.unit,layer.sign || 1));
  } else if (event.key === "[" || event.key === "]") {
    p.rotation_offset = T.normalizeAngle(p.rotation_offset + (event.key === "[" ? -1 : 1)*step); applyFit(p);
  } else {
    p.anchor_scale = T.clamp(p.anchor_scale*(event.key === "-" ? .98 : 1.02),.05,5); applyFit(p);
  }
  S.live = true; markDirty(); draw(); schedulePreview();
});
function setBusy(value) {
  S.busy = value;
  for (const input of $("editorForm").querySelectorAll("input,select")) input.disabled = value;
  $("reference").disabled = value || S.entry?.editable === false;
  $("photo").disabled = value || S.entry?.editable === false;
  $("setName").disabled = value;
  $("new").disabled = value; $("refresh").disabled = value;
  syncControls(); draw();
}
function setControls(parent,componentId="") {
  $("setNotice").hidden = !parent;
  if (!parent) return;
  $("setTitle").textContent = parent.name;
  $("component").replaceChildren(new Option("Обзор комплекта",""));
  for (const part of parent.components) $("component").add(new Option(part.name,part.id));
  $("component").value = componentId;
  $("setName").value = parent.name;
  $("setMetadata").hidden = !!componentId;
}
async function openEntry(entry,componentId=null) {
  if (S.busy || !await discardAllowed()) return;
  const epoch = ++S.epoch; invalidate(); setBusy(true); status("");
  try {
    if (entry.category === "set" && !componentId) {
      const image = await loadImage("api/image/" + encodeURIComponent(entry.id));
      if (epoch !== S.epoch) return;
      S.entry = {...entry,editable:false}; S.parentSet = entry; S.asset = null; S.photo = null;
      S.customPhoto = false;
      S.editRevision=S.catalogRevision;
      S.referenceImage = image; S.history=[]; S.dirty=false;
      $("workspaceTitle").textContent=entry.name; $("inspectorTitle").textContent="Комплект украшений";
      $("editorForm").hidden=true; setControls(entry);
      $("save").hidden=true; $("saveCaption").hidden=true;
      $("modeBadge").textContent="Набор"; $("canvasEmpty").hidden=true;
      renderStatus("Обзор готового набора"); draw(); renderCatalog(); return;
    }
    const data = await api("api/load/" + encodeURIComponent(entry.id) + (componentId ? "?component_id="+encodeURIComponent(componentId) : ""),{});
    if (epoch !== S.epoch) return;
    S.entry={...data.entry,editable:true}; S.parentSet=data.parent || null;
    S.asset=data.asset; S.editRevision=data.revision;
    S.history=[]; S.dirty=false; S.selectedLayer=0;
    $("editorForm").hidden=false; setControls(S.parentSet,componentId || "");
    $("save").hidden=false; $("saveCaption").hidden=false;
    applyValues(data.entry); S.initialFit=structuredClone(settings());
    $("workspaceTitle").textContent=data.entry.name; $("inspectorTitle").textContent="Редактирование";
    $("modeBadge").textContent="В каталоге";
    $("jewelryThumb").src="api/asset/"+encodeURIComponent(data.asset);
    $("jewelryThumb").hidden=false; $("uploadZone").classList.add("has-image");
    $("uploadTitle").textContent="Заменить изображение";
    $("uploadDescription").textContent="Посадку можно изменить прямо на фото";
    await matchingReference(); renderCatalog(); status("Украшение открыто. Измените посадку или данные и сохраните.");
  } catch(error) { status(error.message,true); }
  finally {
    if (epoch === S.epoch) { setBusy(false); if (S.asset) preview(); }
  }
}
async function newEntry(skipConfirmation=false) {
  if (S.busy || (!skipConfirmation && !await discardAllowed())) return;
  ++S.epoch; invalidate();
  S.entry=null; S.parentSet=null; S.asset=null; S.editRevision=S.catalogRevision; S.history=[]; S.dirty=false;
  $("editorForm").hidden=false; $("setNotice").hidden=true; $("save").hidden=false; $("saveCaption").hidden=false;
  $("jewelry").value=""; $("jewelryThumb").removeAttribute("src"); $("jewelryThumb").hidden=true;
  $("uploadZone").classList.remove("has-image");
  $("uploadTitle").textContent="Добавить украшение"; $("uploadDescription").textContent="PNG или WebP с прозрачным фоном";
  $("workspaceTitle").textContent="Новое украшение"; $("inspectorTitle").textContent="Создайте своё";
  $("modeBadge").textContent="Черновик"; $("duplicate").hidden=true;
  applyValues({}); S.initialFit=structuredClone(settings()); status(""); renderStatus("");
  renderCatalog(); await matchingReference(); draw(); syncControls();
}
async function uploadFile(kind,file) {
  if (!file || S.busy) return;
  if (file.size > 12*1024*1024) { status("Выберите файл размером до 12 МБ.",true); return; }
  const epoch = S.epoch;
  setBusy(true); status(kind === "jewelry" ? "Загружаем украшение…" : "Загружаем референс…");
  try {
    const data = await api("api/upload/" + kind + "?crop=" + (kind === "jewelry" && $("crop").checked),file,"POST",true);
    if (epoch !== S.epoch) return;
    const image = await loadImage("api/asset/" + encodeURIComponent(data.token));
    invalidate();
    if (kind === "jewelry") {
      S.asset=data.token;
      S.pairAnchors=null; $("overlay_anchor_x").value=""; $("overlay_anchor_y").value="";
      $("jewelryThumb").src=image.src; $("jewelryThumb").hidden=false; $("uploadZone").classList.add("has-image");
      $("uploadTitle").textContent="Заменить изображение"; $("uploadDescription").textContent=file.name;
      S.initialFit=structuredClone(settings());
    } else {
      S.photo=data.token; S.customPhoto=true; S.referenceSerial++; S.referenceImage=image;
      if (!$("reference").querySelector('option[value="custom"]')) $("reference").add(new Option("Моё фото","custom"));
      $("reference").value="custom";
    }
    markDirty(); draw(); status("Изображение загружено.");
  } catch(error) { status(error.message,true); }
  finally { if (epoch === S.epoch) { setBusy(false); if (S.asset) preview(); } }
}
async function checkName() {
  const name=$("name").value.trim(); if (!name) { $("duplicate").hidden=true; return; }
  try {
    const result=await api("api/check?name="+encodeURIComponent(name));
    if (name !== $("name").value.trim()) return;
    const conflict=result.matches.some(entry => entry.id !== S.entry?.id);
    $("duplicate").hidden=!conflict;
    $("duplicate").textContent=conflict ? "Такое название уже есть. Откройте эту позицию в каталоге или выберите другое название." : "";
  } catch(error) { status(error.message,true); }
}
async function saveEntry() {
  if (S.busy || !S.asset || !S.dirty) return;
  if (!$("name").value.trim()) { status("Укажите название украшения.",true); $("name").focus(); return; }
  if (!$("category").value) { status("Выберите тип украшения.",true); return; }
  const p=payload(); S.serial++; clearTimeout(S.timer); $("canvasLoading").hidden=true;
  setBusy(true); status("Сохраняем украшение и его посадку…");
  try {
    const result=await api("api/save",p);
    S.entry={...result.entry,editable:true}; S.parentSet=result.parent || null;
    setControls(S.parentSet,S.parentSet ? S.entry.id : ""); S.editRevision=result.revision;
    S.dirty=false; S.initialFit=structuredClone(settings()); S.history=[];
    $("modeBadge").textContent="В каталоге"; $("inspectorTitle").textContent="Редактирование";
    await refreshCatalog(); status("Сохранено. Изменения уже доступны в каталоге бота.");
    syncControls();
  } catch(error) { status(error.message,true); }
  finally { setBusy(false); if (!S.dirty && S.asset) preview(); }
}
async function removeEntry() {
  if (S.busy || !S.entry) return;
  const entry=S.parentSet || S.entry;
  if (!await confirmAction("Удалить украшение?","«"+entry.name+"» исчезнет из каталога примерочной. Текущие изменения этой карточки не сохранятся.","Удалить из каталога",true)) return;
  setBusy(true); status("Удаляем позицию…");
  try {
    const response=await api("api/items/"+encodeURIComponent(entry.id),{revision:S.catalogRevision,confirm:true},"DELETE");
    S.catalogRevision=response.revision; S.dirty=false;
    await refreshCatalog(); setBusy(false); await newEntry(true);
    status("«"+entry.name+"» удалено из каталога.");
  } catch(error) { status(error.message,true); }
  finally { setBusy(false); }
}
$("catalogSearch").addEventListener("input",renderCatalog);
$("catalogFilter").addEventListener("change",renderCatalog);
$("new").addEventListener("click",() => newEntry());
$("refresh").addEventListener("click",async () => {
  if (S.busy) return;
  try {
    await refreshCatalog();
    if (!S.asset && !S.entry) S.editRevision=S.catalogRevision;
    status("Список обновлён. Открытая карточка и её несохранённые изменения сохранены.");
  } catch(error) { status(error.message,true); }
});
$("name").addEventListener("input",() => { markDirty(); clearTimeout(S.checkTimer); S.checkTimer=setTimeout(checkName,250); });
$("editorForm").addEventListener("submit",event => { event.preventDefault(); saveEntry(); });
$("category").addEventListener("change",async () => {
  if (S.busy) return; markDirty(); visibility(); invalidate();
  try { await matchingReference(); preview(); } catch(error) { status(error.message,true); }
});
$("earMode").addEventListener("change",() => { markDirty(); invalidate(); schedulePreview(0); });
for (const [id] of fields) {
  $(id).addEventListener("change",async () => {
    markDirty();
    if (id === "offset_x" || id === "offset_y") { S.live=true; draw(); schedulePreview(); }
    else {
      invalidate();
      try { if (id === "hairpin_style") await matchingReference(); schedulePreview(0); }
      catch(error) { status(error.message,true); }
    }
  });
}
for (const key of ["anchor_scale","rotation_offset"]) {
  $(key).addEventListener("pointerdown",() => { S.sliderStart=structuredClone(settings()); });
  $(key).addEventListener("input",() => {
    if (S.busy) return;
    if (S.sliderStart) { pushHistory(S.sliderStart); S.sliderStart=null; }
    S.serial++; clearTimeout(S.timer); $("canvasLoading").hidden=true;
    S.live=true; syncControls(); markDirty(); draw();
  });
  $(key).addEventListener("change",() => { S.sliderStart=null; schedulePreview(0); });
}
for (const [id,key,factor] of [["scaleNumber","anchor_scale",.01],["rotationNumber","rotation_offset",1]]) {
  $(id).addEventListener("change",() => {
    const raw=Number($(id).value); if (!Number.isFinite(raw)) { syncControls(); return; }
    pushHistory();
    $(key).value=key === "anchor_scale" ? T.clamp(raw*factor,.05,5) : T.clamp(raw,-180,180);
    S.live=true; markDirty(); syncControls(); draw(); schedulePreview();
  });
}
$("reference").addEventListener("change",async () => {
  if (S.busy || $("reference").value === "custom") return;
  try { await chooseReference($("reference").value); preview(); }
  catch(error) { status(error.message,true); }
});
$("jewelry").addEventListener("change",() => uploadFile("jewelry",$("jewelry").files[0]));
$("photo").addEventListener("change",() => uploadFile("photo",$("photo").files[0]));
for (const eventName of ["dragenter","dragover"]) $("uploadZone").addEventListener(eventName,event => {
  event.preventDefault(); if (!S.busy) $("uploadZone").classList.add("dragover");
});
$("uploadZone").addEventListener("dragleave",() => $("uploadZone").classList.remove("dragover"));
$("uploadZone").addEventListener("drop",event => {
  event.preventDefault(); $("uploadZone").classList.remove("dragover"); uploadFile("jewelry",event.dataTransfer.files[0]);
});
$("save").addEventListener("click",saveEntry);
$("delete").addEventListener("click",removeEntry);
$("component").addEventListener("change",async () => {
  const parent=S.parentSet;
  if (parent) await openEntry(parent,$("component").value || null);
  // A cancelled unsaved-changes dialog must restore the current selection.
  if (S.parentSet) $("component").value=S.entry?.category === "set" ? "" : S.entry.id;
});
$("setName").addEventListener("input",markDirty);
$("renameSet").addEventListener("click",async () => {
  if (S.busy || !S.parentSet) return;
  setBusy(true);
  try {
    const response=await api("api/items/"+encodeURIComponent(S.parentSet.id),
      {name:$("setName").value,revision:S.editRevision},"PATCH");
    S.entry={...response.entry,editable:false}; S.parentSet=response.entry; S.editRevision=response.revision; S.dirty=false;
    setControls(S.parentSet); $("workspaceTitle").textContent=response.entry.name;
    await refreshCatalog(); status("Название набора сохранено.");
  } catch(error) { status(error.message,true); }
  finally { setBusy(false); }
});
$("preview").addEventListener("click",preview);
$("toggleHandles").addEventListener("click",() => {
  S.handles=!S.handles; $("toggleHandles").setAttribute("aria-pressed",String(S.handles));
  $("toggleHandles").textContent=S.handles ? "Скрыть метки" : "Показать метки"; draw();
});
$("undo").addEventListener("click",() => {
  if (!S.history.length || S.busy) return;
  applyFit(S.history.pop()); S.live=true; markDirty(); draw(); schedulePreview(0);
});
$("resetFit").addEventListener("click",() => {
  if (!S.initialFit || S.busy) return;
  pushHistory(); applyFit(S.initialFit); S.live=true; markDirty(); draw(); schedulePreview(0);
});
window.addEventListener("beforeunload",event => { if (S.dirty) { event.preventDefault(); event.returnValue=""; } });
window.addEventListener("resize",draw);
(async () => {
  if (location.protocol === "file:" || new URLSearchParams(location.search).get("view") === "design") {
    document.querySelector(".brand").href=location.href;
    for (const [value,title] of Object.entries(categoryNames)) if (value !== "set") $("category").add(new Option(title,value));
    applyValues({});
    $("reference").replaceChildren(new Option("Референсы доступны в запущенной мастерской",""));
    $("catalogList").replaceChildren();
    const note=document.createElement("p"); note.className="empty-list";
    note.textContent="Оформление мастерской. Для работы с каталогом откройте редактор через локальный сервер.";
    $("catalogList").append(note); $("catalogCount").textContent="—";
    for (const input of document.querySelectorAll("button,input,select")) input.disabled=true;
    $("saveState").textContent="Просмотр оформления";
    status("Чтобы загружать и сохранять украшения, откройте мастерскую по адресу сервера, например http://127.0.0.1:8765/.");
    return;
  }
  try {
    await refreshCatalog(true);
    const refs=await api("api/references"); S.references=refs.references; S.referenceDefaults=refs.defaults;
    $("reference").replaceChildren();
    for (const ref of S.references) $("reference").add(new Option(ref.title,ref.id));
    await newEntry(true);
  } catch(error) { status(error.message,true); renderStatus("Не удалось открыть мастерскую. Обновите страницу после восстановления подключения.",true); }
})();
