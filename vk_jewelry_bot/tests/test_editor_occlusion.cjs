"use strict";
/* Pixel checks in a real browser; no server, catalogue or user photos. */
const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
let chromium;
for (const candidate of [process.env.PLAYWRIGHT_MODULE,"playwright"].filter(Boolean)) {
  try { chromium = require(candidate).chromium; break; } catch {}
}
const chrome = process.env.CHROME_PATH;
const source = fs.readFileSync(path.join(__dirname,"../jewelry_editor/static/app.js"),"utf8");
const helper = source.match(/^function drawPreviewLayer\([^]*?^}/m)?.[0];
assert(helper,"The tested renderer must come from the production editor");

test("live photo occlusion hides only chain pixels and stays fixed during movement", {
  skip: !chromium || (chrome && !fs.existsSync(chrome)),
}, async () => {
  const browser = await chromium.launch({headless:true,...(chrome ? {executablePath:chrome} : {}),
    args:["--no-first-run","--no-default-browser-check"]});
  try {
    const page = await browser.newPage();
    await page.addScriptTag({content:helper});
    const result = await page.evaluate(() => {
      const makeCanvas = (width,height,color) => {
        const canvas = document.createElement("canvas"); canvas.width=width; canvas.height=height;
        if (color) { const c=canvas.getContext("2d"); c.fillStyle=color; c.fillRect(0,0,width,height); }
        return canvas;
      };
      const canvas=makeCanvas(100,100),context=canvas.getContext("2d"),surface=makeCanvas(1,1);
      const chain=makeCanvas(80,20,"rgb(255,0,0)"),pendant=makeCanvas(10,10,"rgb(255,255,0)");
      const mask=makeCanvas(100,100),maskContext=mask.getContext("2d");
      maskContext.fillStyle="white"; maskContext.fillRect(45,0,10,60);
      maskContext.fillStyle="rgba(255,255,255,0.5)"; maskContext.fillRect(35,0,10,60);
      const base=()=>{context.fillStyle="rgb(20,40,60)";context.fillRect(0,0,100,100);};
      const pixel=(x,y)=>Array.from(context.getImageData(x,y,1,1).data);
      const layer={x:50,y:40,width:80,height:20,rotation:0,anchor:[.5,.5]};
      base();
      drawPreviewLayer(context,layer,chain,mask,surface,100,100);
      const maskedFace=pixel(50,32),visibleChain=pixel(20,40),softEdge=pixel(40,40),baseOutside=pixel(50,10);
      drawPreviewLayer(context,{...layer,width:10,height:10},pendant,null,surface,100,100);
      const visiblePendant=pixel(50,40);
      base();
      drawPreviewLayer(context,{...layer,x:70,y:50,rotation:30},chain,mask,surface,100,100);
      const stationaryMask=pixel(50,45),movedChain=pixel(70,50),clearedOldPixels=pixel(20,40);
      base();
      drawPreviewLayer(context,layer,chain,null,surface,100,100);
      const unmaskedLegacy=pixel(50,40);
      return {maskedFace,visibleChain,softEdge,baseOutside,visiblePendant,stationaryMask,
        movedChain,clearedOldPixels,unmaskedLegacy,surfaceSize:[surface.width,surface.height]};
    });
    const base=[20,40,60,255],red=[255,0,0,255],yellow=[255,255,0,255];
    assert.deepEqual(result.maskedFace,base,"Masking must preserve the underlying photograph");
    assert.deepEqual(result.baseOutside,base);
    assert.deepEqual(result.visibleChain,red);
    assert.deepEqual(result.visiblePendant,yellow,"Pendant must remain in front even inside the face mask");
    assert.deepEqual(result.stationaryMask,base,"Moving/rotating a layer must not move the photo mask");
    assert.deepEqual(result.movedChain,red);
    assert.deepEqual(result.clearedOldPixels,base,"Reused offscreen canvas must not retain old chain pixels");
    assert.deepEqual(result.unmaskedLegacy,red,"Responses without masks must preserve legacy composition");
    assert.deepEqual(result.surfaceSize,[100,100]);
    for (let i=0;i<4;i++) assert(Math.abs(result.softEdge[i]-[137,20,30,255][i])<=1,
      "Soft confidence must erase only the corresponding fraction of chain alpha");
  } finally { await browser.close(); }
});
