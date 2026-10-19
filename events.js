"use strict";
const HOWTO_BY_TAB={parents:["親Aを選ぶ","親Bを選ぶ","生まれる子を確認"],target:["作りたい子を選ぶ","親を絞り込む","組み合わせを使う"],offspring:["手持ちの親を選ぶ","相手や子を検索","組み合わせを使う"],tree:["起点パルを選ぶ","世代を選ぶ","候補を切り替える"],dex:["名前で検索","属性・適性で絞る","配合に使う"]};
let activeTab="parents";
function updateHowto(tab){const steps=HOWTO_BY_TAB[tab]||HOWTO_BY_TAB.parents;document.querySelectorAll(".howto span").forEach((el,i)=>{el.textContent=steps[i]||""})}
function activateTab(tab,{persist=true,focus=false,scroll=false}={}){
 if(!Object.hasOwn(HOWTO_BY_TAB,tab))return;
 activeTab=tab;
 document.querySelectorAll(".tabs button").forEach(button=>{const selectedTab=button.dataset.tab===tab;button.classList.toggle("active",selectedTab);button.setAttribute("aria-selected",String(selectedTab));button.tabIndex=selectedTab?0:-1});
 document.querySelectorAll(".view").forEach(view=>{view.hidden=view.id!=="view-"+tab});updateHowto(tab);
 if(tab==="tree")renderTree();
 if(focus)$("#tab-"+tab).focus({preventScroll:true});
 if(scroll)$("#tabs").scrollIntoView({block:"start",behavior:"auto"});
 if(persist)writeUIState();
}
function buildShareURL(){
 const params=new URLSearchParams({view:activeTab});
 const set=(key,value,defaultValue="")=>{if(value!==null&&value!==undefined&&String(value)!==String(defaultValue))params.set(key,String(value))};
 if(activeTab==="parents"){set("a",selected.a?.uid);set("b",selected.b?.uid)}
 if(activeTab==="target"){set("target",selected.target?.uid);set("q",$("#targetFilter").value);set("sort",$("#targetSort").value,"no")}
 if(activeTab==="offspring"){set("parent",selected.parent?.uid);set("q",$("#offspringFilter").value);set("sort",$("#offspringSort").value,"child")}
 if(activeTab==="tree"){
  set("tree",selected.tree?.uid);set("depth",$("#treeDepth").value,"4");set("direction",treeOrientation,"result");
  const choices=[...treeSelections].filter(([,index])=>index>0).sort(([a],[b])=>a.localeCompare(b)).map(([path,index])=>`${path}:${index}`).join(",");set("pairs",choices);
 }
 if(activeTab==="dex")for(const [key,id,defaultValue] of [["q","dexSearch",""],["sort","dexSort","asc"],["variant","dexVariant","all"],["element","dexElement",""],["work","dexWork",""],["level","dexWorkLevel","0"]])set(key,$("#"+id).value,defaultValue);
 const url=new URL(location.href);url.hash=params.toString();return url;
}
function writeUIState(){if(document.body.dataset.dataState==="ready")history.replaceState(null,"",buildShareURL())}
function restoreUIState(render=true){
 if(document.body.dataset.dataState!=="ready")return;
 const params=new URLSearchParams(location.hash.slice(1)),tab=params.get("view");if(!tab||!Object.hasOwn(HOWTO_BY_TAB,tab))return;
 let invalid=false;
 const readPal=(key,parentOnly=false)=>{const id=params.get(key);if(!id)return null;const pal=byId.get(id.toLowerCase());if(!pal||(parentOnly&&!isBreedableParent(pal))){invalid=true;return null}return pal};
 const selectValue=(id,value,fallback)=>{const select=$("#"+id);select.value=Array.from(select.options).some(option=>option.value===value)?value:fallback};
 const query=(params.get("q")||"").slice(0,120);
 if(tab==="parents"){selected.a=readPal("a",true);selected.b=readPal("b",true)}
 if(tab==="target"){selected.target=readPal("target");$("#targetFilter").value=query;selectValue("targetSort",params.get("sort"),"no")}
 if(tab==="offspring"){selected.parent=readPal("parent",true);$("#offspringFilter").value=query;selectValue("offspringSort",params.get("sort"),"child")}
 if(tab==="tree"){
  treeOrientation=params.get("direction")==="parent"?"parent":"result";selected.tree=readPal("tree",treeOrientation==="parent");selectValue("treeDepth",params.get("depth"),"4");treeSelections.clear();
  for(const choice of (params.get("pairs")||"").split(",").slice(0,31)){
   const [path,index]=choice.split(":");if(/^(r[ab]{0,4}|dc{0,4})$/.test(path)&&/^\d{1,5}$/.test(index||""))treeSelections.set(path,+index);
  }
  document.querySelectorAll("[data-orient]").forEach(button=>{const selectedDirection=button.dataset.orient===treeOrientation;button.classList.toggle("active",selectedDirection);button.setAttribute("aria-pressed",String(selectedDirection))});
  zoom=1;panX=panY=0;
 }
 if(tab==="dex"){
  $("#dexSearch").value=query;
  for(const [key,id,fallback] of [["sort","dexSort","asc"],["variant","dexVariant","all"],["element","dexElement",""],["work","dexWork",""],["level","dexWorkLevel","0"]])selectValue(id,params.get(key),fallback);
  if(!$("#dexWork").value)$("#dexWorkLevel").value="0";
 }
 activateTab(tab,{persist:false});
 if(render){renderParents();renderTarget();renderOffspring();renderDex();renderTree()}
 if(invalid){toast("リンク内の選べない親や見つからないパルを除きました");writeUIState()}
}
async function copyText(text){
 if(navigator.clipboard?.writeText){try{await navigator.clipboard.writeText(text);return}catch{}}
 const previous=document.activeElement,textarea=document.createElement("textarea");textarea.value=text;textarea.style.cssText="position:fixed;left:0;top:0;opacity:0;width:1px;height:1px";document.body.append(textarea);textarea.focus();textarea.select();
 let success=false;try{success=document.execCommand("copy")}finally{textarea.remove();previous?.focus({preventScroll:true})}
 if(!success)throw new Error("コピーできませんでした");
}
function resetFilters(scope){
 if(scope==="picker"){resetPickerFilters();renderPicker();$("#pickerSearch").focus();return}
 if(scope==="target"){$("#targetFilter").value="";renderTarget()}
 if(scope==="offspring"){$("#offspringFilter").value="";renderOffspring()}
 if(scope==="dex"){
  $("#dexSearch").value="";$("#dexVariant").value="all";$("#dexElement").value="";$("#dexWork").value="";$("#dexWorkLevel").value="0";renderDex();
 }
 writeUIState();
}
$("#tabs").addEventListener("click",event=>{const button=event.target.closest("button[data-tab]");if(button)activateTab(button.dataset.tab)});
$("#tabs").addEventListener("keydown",event=>{
 if(!["ArrowLeft","ArrowRight","Home","End"].includes(event.key))return;
 const tabs=Array.from(document.querySelectorAll("#tabs [data-tab]")),current=tabs.findIndex(button=>button.dataset.tab===activeTab);
 const index=event.key==="Home"?0:event.key==="End"?tabs.length-1:(current+(event.key==="ArrowRight"?1:-1)+tabs.length)%tabs.length;
 event.preventDefault();activateTab(tabs[index].dataset.tab,{focus:true});tabs[index].scrollIntoView({block:"nearest",inline:"nearest"});
});
$("#parentA").onclick=()=>openPicker(p=>{selected.a=p;renderParents();writeUIState()},"親Aを選択",true);
$("#parentB").onclick=()=>openPicker(p=>{selected.b=p;renderParents();writeUIState()},"親Bを選択",true);
$("#targetPick").onclick=()=>openPicker(p=>{selected.target=p;$("#targetFilter").value="";renderTarget();writeUIState()},"作りたいパルを選択");
$("#singleParentPick").onclick=()=>openPicker(p=>{selected.parent=p;$("#offspringFilter").value="";renderOffspring();writeUIState()},"親にするパルを選択",true);
$("#treePick").onclick=()=>openPicker(p=>{selected.tree=p;treeSelections.clear();zoom=1;panX=panY=0;renderTree();writeUIState()},"ツリーの起点パルを選択",treeOrientation==="parent");
$("#swapParents").onclick=()=>{[selected.a,selected.b]=[selected.b,selected.a];renderParents();writeUIState()};
$("#clearParents").onclick=()=>{selected.a=selected.b=null;renderParents();writeUIState()};
$("#copyParents").onclick=async()=>{
 const results=getResults(selected.a,selected.b);if(!results.length)return;
 const copyName=pal=>`${palDisplayName(pal)} [${formId(pal)}]`;
 const text=results.map(result=>`${copyName(result.first)} + ${copyName(result.second)} → ${copyName(result.child)}${isGenderSpecific(result)?`（${result.note}）`:""}`).join("\n");
 try{await copyText(text);toast("コピーしました")}catch{toast("コピーできませんでした。ブラウザーの共有機能をご利用ください。")}
};
$("#shareView").onclick=async()=>{try{await copyText(buildShareURL().href);toast("選択中のパルを開けるリンクをコピーしました")}catch{toast("リンクをコピーできませんでした。ブラウザーの共有機能をご利用ください。")}};
for(const [ids,render] of [[["targetFilter","targetSort"],renderTarget],[["offspringFilter","offspringSort"],renderOffspring],[["dexSearch","dexSort","dexVariant","dexElement","dexWork","dexWorkLevel"],renderDex]])for(const id of ids){
 $("#"+id).addEventListener(/Filter$|Search$/.test(id)?"input":"change",()=>{if(id==="dexWork"&&!$("#dexWork").value)$("#dexWorkLevel").value="0";render();writeUIState()});
}
$("#dexReset").onclick=()=>resetFilters("dex");$("#pickerReset").onclick=()=>resetFilters("picker");
document.addEventListener("click",event=>{
 const clearButton=event.target.closest("[data-clear]");
 if(clearButton){const input=$("#"+clearButton.dataset.clear);input.value="";input.dispatchEvent(new Event("input",{bubbles:true}));input.focus();return}
 const resetButton=event.target.closest("[data-reset-scope]");if(resetButton){resetFilters(resetButton.dataset.resetScope);return}
 const pairButton=event.target.closest("[data-open-pair]");
 if(pairButton){const first=byId.get(pairButton.dataset.first),second=byId.get(pairButton.dataset.second);if(!first||!second||!isBreedableParent(first)||!isBreedableParent(second))return;selected.a=first;selected.b=second;renderParents();activateTab("parents",{scroll:true});return}
 const useButton=event.target.closest("[data-use-pal]");if(!useButton)return;
 const pal=byId.get(useButton.dataset.usePal),destination=useButton.dataset.destination;if(!pal)return;
 if((destination==="parents"||destination==="offspring")&&!isBreedableParent(pal))return;
 if(destination==="parents"){selected.a=pal;selected.b=null;renderParents()}
 if(destination==="target"){selected.target=pal;$("#targetFilter").value="";renderTarget()}
 if(destination==="offspring"){selected.parent=pal;$("#offspringFilter").value="";renderOffspring()}
 if(destination==="tree"){
  selected.tree=pal;treeOrientation="result";treeSelections.clear();zoom=1;panX=panY=0;
  document.querySelectorAll("[data-orient]").forEach(button=>{const isResult=button.dataset.orient==="result";button.classList.toggle("active",isResult);button.setAttribute("aria-pressed",String(isResult))});
 }
 activateTab(destination,{scroll:true});
});
$("#pickerClose").onclick=closePicker;$("#pickerModal").addEventListener("click",event=>{if(event.target===$("#pickerModal"))closePicker()});
for(const id of ["pickerSearch","pickerSort","pickerVariant","pickerElement","pickerWork","pickerLevel"]){
 $("#"+id).addEventListener(id==="pickerSearch"?"input":"change",()=>{if(id==="pickerWork"&&!$("#pickerWork").value)$("#pickerLevel").value="0";renderPicker();$("#pickerList").scrollTop=0});
}
$("#pickerList").addEventListener("click",event=>{const button=event.target.closest("button[data-id]");if(!button)return;const pal=byId.get(button.dataset.id);if(!pal||(pickerParentOnly&&!isBreedableParent(pal)))return;const callback=pickerCallback;closePicker();callback?.(pal)});
document.querySelector(".seg").addEventListener("click",event=>{
 const button=event.target.closest("[data-orient]");if(!button)return;
 treeOrientation=button.dataset.orient;document.querySelectorAll("[data-orient]").forEach(other=>{const selectedDirection=other===button;other.classList.toggle("active",selectedDirection);other.setAttribute("aria-pressed",String(selectedDirection))});
 if(treeOrientation==="parent"&&selected.tree&&!isBreedableParent(selected.tree)){selected.tree=null;toast("配合できる親を選んでください")}
 treeSelections.clear();zoom=1;panX=panY=0;renderTree();writeUIState();
});
$("#treeDepth").onchange=()=>{treeSelections.clear();renderTree();writeUIState()};
$("#treeCanvas").addEventListener("click",event=>{
 const button=event.target.closest("[data-nav]");if(!button||button.disabled)return;const path=button.dataset.nav,direction=+button.dataset.d;
 for(const key of treeSelections.keys())if(key!==path&&key.startsWith(path))treeSelections.delete(key);
 treeSelections.set(path,Math.max(0,(treeSelections.get(path)||0)+direction));renderTree();writeUIState();
 const replacement=document.querySelector(`#treeCanvas [data-nav="${path}"][data-d="${direction}"]`);if(replacement&&!replacement.disabled)replacement.focus({preventScroll:true});
});
$("#zoomIn").onclick=()=>{zoom=Math.min(2,zoom+.15);applyTreeTransform()};$("#zoomOut").onclick=()=>{zoom=Math.max(.08,zoom-.15);applyTreeTransform()};$("#zoomReset").onclick=resetTreeView;$("#zoomFit").onclick=fitTree;
const vp=$("#treeViewport");let lastX=0,lastY=0,pointers=new Map(),pinchDist=0;
vp.addEventListener("pointerdown",event=>{
 if(event.target.closest("button,a,input,select,summary"))return;
 vp.setPointerCapture(event.pointerId);pointers.set(event.pointerId,{x:event.clientX,y:event.clientY});lastX=event.clientX;lastY=event.clientY;vp.classList.add("dragging");
 if(pointers.size===2){const points=[...pointers.values()];pinchDist=Math.hypot(points[0].x-points[1].x,points[0].y-points[1].y)}
});
vp.addEventListener("pointermove",event=>{
 if(!pointers.has(event.pointerId))return;pointers.set(event.pointerId,{x:event.clientX,y:event.clientY});
 if(pointers.size===2){const points=[...pointers.values()],distance=Math.hypot(points[0].x-points[1].x,points[0].y-points[1].y);if(pinchDist&&distance)zoom=Math.max(.08,Math.min(2,zoom*distance/pinchDist));pinchDist=distance;applyTreeTransform();return}
 panX+=event.clientX-lastX;panY+=event.clientY-lastY;lastX=event.clientX;lastY=event.clientY;applyTreeTransform();
});
function endPointer(event){
 pointers.delete(event.pointerId);pinchDist=0;if(!pointers.size)vp.classList.remove("dragging");else{const point=[...pointers.values()][0];lastX=point.x;lastY=point.y}
}
vp.addEventListener("pointerup",endPointer);vp.addEventListener("pointercancel",endPointer);vp.addEventListener("lostpointercapture",endPointer);
vp.addEventListener("wheel",event=>{event.preventDefault();zoom=Math.max(.08,Math.min(2,zoom+(event.deltaY<0?.1:-.1)));applyTreeTransform()},{passive:false});
vp.addEventListener("keydown",event=>{
 if(event.target!==vp)return;
 const movements={ArrowLeft:[40,0],ArrowRight:[-40,0],ArrowUp:[0,40],ArrowDown:[0,-40]};
 if(movements[event.key]){event.preventDefault();panX+=movements[event.key][0];panY+=movements[event.key][1];applyTreeTransform()}
 if(event.key==="+"||event.key==="="){event.preventDefault();zoom=Math.min(2,zoom+.15);applyTreeTransform()}
 if(event.key==="-"){event.preventDefault();zoom=Math.max(.08,zoom-.15);applyTreeTransform()}
 if(event.key==="Home"){event.preventDefault();resetTreeView()}
});
document.addEventListener("keydown",event=>{
 if(!$("#pickerModal").classList.contains("open"))return;
 if(event.key==="Escape"){event.preventDefault();closePicker();return}
 if(event.key!=="Tab")return;
 const focusable=Array.from($("#pickerModal").querySelectorAll("button:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex='0']")).filter(element=>element.getClientRects().length),first=focusable[0],last=focusable.at(-1);
 if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus()}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus()}
});
window.addEventListener("hashchange",()=>restoreUIState());window.addEventListener("resize",()=>{if(activeTab==="tree")applyTreeTransform()});
updateHowto("parents");renderAll();void load();
