"use strict";
let pickerParentOnly=false,pickerReturnFocus=null,toastTimer=null;
function resetPickerFilters(){
 $("#pickerSearch").value="";$("#pickerSort").value="asc";$("#pickerVariant").value="all";$("#pickerElement").value="";$("#pickerWork").value="";$("#pickerLevel").value="0";$("#pickerLevel").disabled=true;
}
function openPicker(cb,title="パルを選択",parentOnly=false){
 if(!pals.length){toast(document.body.dataset.dataState==="error"?"データを読み込めませんでした。上のデータ状態を押して再試行してください。":"データを読み込んでいます");return}
 pickerReturnFocus=document.activeElement;pickerCallback=cb;pickerParentOnly=parentOnly;resetPickerFilters();$("#pickerTitle").textContent=title;
 $("#pickerModal").classList.add("open");$("#pickerModal").setAttribute("aria-hidden","false");document.body.classList.add("picker-open");document.querySelector(".app").inert=true;
 renderPicker();$("#pickerList").scrollTop=0;$("#pickerSearch").focus({preventScroll:true});
}
function closePicker(){
 if(!$("#pickerModal").classList.contains("open"))return;
 $("#pickerModal").classList.remove("open");$("#pickerModal").setAttribute("aria-hidden","true");document.body.classList.remove("picker-open");document.querySelector(".app").inert=false;pickerCallback=null;
 if(pickerReturnFocus?.isConnected)pickerReturnFocus.focus({preventScroll:true});pickerReturnFocus=null;
}
function pickerFiltered(){
 const q=$("#pickerSearch").value||"",v=$("#pickerVariant").value,el=$("#pickerElement").value,w=$("#pickerWork").value,l=+$("#pickerLevel").value,s=$("#pickerSort").value;
 let list=pals.filter(p=>(!pickerParentOnly||isBreedableParent(p))&&searchable(p,q)&&(v==="all"||(v==="variant")===p.variant)&&(!el||p.elements.includes(el))&&matchesWorkFilter(p,w,l));
 list.sort((a,b)=>s==="desc"?palSort(b,a):s==="jp"?palDisplayName(a).localeCompare(palDisplayName(b),"ja"):palSort(a,b));return list;
}
function renderPicker(){
 const list=pickerFiltered();
 $("#pickerLevel").disabled=!$("#pickerWork").value;$("#pickerCount").textContent=`${list.length}形態${pickerParentOnly?" · 配合できる親から選択":"から選択"}`;
 $("#pickerList").innerHTML=list.length?list.map(p=>`<button class="picker-item" type="button" data-id="${esc(p.uid)}" aria-label="${esc(palDisplayName(p))}、図鑑番号${esc(displayNo(p))}を選択">${mark(p,true)}<span style="min-width:0"><small class="picker-no">No.${esc(displayNo(p,true))}</small><strong>${esc(palDisplayName(p))}</strong><small class="enname">${esc(p.en)}</small>${formIdHTML(p)}</span></button>`).join(""):emptyHTML("見つかりませんでした","名前や図鑑番号を変えるか、絞り込みを解除してください。","picker");
 const hasFilter=$("#pickerSearch").value||$("#pickerVariant").value!=="all"||$("#pickerElement").value||$("#pickerWork").value||+$("#pickerLevel").value;
 $("#pickerReset").disabled=!hasFilter;updateSearchClear("pickerSearch");
}
function toast(msg){const t=$("#toast");clearTimeout(toastTimer);t.textContent=msg;t.classList.add("show");toastTimer=setTimeout(()=>t.classList.remove("show"),2800)}
function renderTree(){
 const canvas=$("#treeCanvas");
 $("#treePick").textContent=selected.tree?`${palDisplayName(selected.tree)}を変更`:"起点パルを選択";
 if(!selected.tree){canvas.innerHTML='<div class="empty tree-empty"><span class="empty-icon" aria-hidden="true">⌘</span><strong>起点にするパルを選んでください</strong><p>親から子へ、子から親へ。配合のつながりをたどれます。</p></div>';applyTreeTransform();return}
 const depth=+$("#treeDepth").value;
 canvas.innerHTML=treeOrientation==="result"?ancestorNode(selected.tree,0,depth,"r","",new Set()):descendantNode(selected.tree,0,depth,"d",new Set());applyTreeTransform();
}
function isGenderSpecific(result){return result&&(result.parent1Gender!=="WILDCARD"||result.parent2Gender!=="WILDCARD")}
function requiredGenderFor(result,pal){
 if(!result)return "";
 if(pal.uid===result.first.uid)return genderMark(result.parent1Gender);
 if(pal.uid===result.second.uid)return genderMark(result.parent2Gender);
 return "";
}
function orderedAncestorPairs(p){
 return playableResults(parentsByChild.get(p.uid)||[]).sort((a,b)=>{
  const aCycles=Number(a.first.uid===p.uid||a.second.uid===p.uid),bCycles=Number(b.first.uid===p.uid||b.second.uid===p.uid);
  return aCycles-bCycles||palSort(a.first,b.first)||palSort(a.second,b.second);
 });
}
function orderedDescendantPairs(p){
 return playableOffspringGroups(p).flatMap(group=>group.results.map(result=>({...result,partner:group.partner}))).sort((a,b)=>Number(a.child.uid===p.uid)-Number(b.child.uid===p.uid)||palSort(a.child,b.child)||palSort(a.partner,b.partner));
}
function nodeCard(p,pairs,path,requiredGender="",condition="",label=""){
 const idx=Math.min(treeSelections.get(path)||0,Math.max(0,pairs.length-1));treeSelections.set(path,idx);
 return `<div class="tree-node">${label?`<div class="tree-role">${esc(label)}</div>`:""}${palHTML(p,true)}${requiredGender?`<div class="tree-gender">必要性別 ${esc(requiredGender)}</div>`:""}${condition?`<div class="tree-condition">${esc(condition)}</div>`:""}${pairs.length>1?`<div class="combo-nav"><button type="button" data-nav="${path}" data-d="-1" aria-label="${esc(palDisplayName(p))}の前の配合候補"${idx===0?" disabled":""}>‹</button><span>${idx+1} / ${pairs.length}</span><button type="button" data-nav="${path}" data-d="1" aria-label="${esc(palDisplayName(p))}の次の配合候補"${idx>=pairs.length-1?" disabled":""}>›</button></div>`:""}</div>`;
}
function ancestorNode(p,level,max,path,requiredGender="",ancestors=new Set()){
 const label=level===0?"作りたいパル":"親";
 if(ancestors.has(p.uid))return `<div class="tree-branch">${nodeCard(p,[],path,requiredGender,"同じパルに戻るため、ここで表示を終了",label)}</div>`;
 const nextAncestors=new Set(ancestors);nextAncestors.add(p.uid);
 const pairs=orderedAncestorPairs(p),idx=Math.min(treeSelections.get(path)||0,Math.max(0,pairs.length-1)),r=pairs[idx];
 if(level>=max||!r)return `<div class="tree-branch">${nodeCard(p,[],path,requiredGender,!r?"配合では入手できません":"",label)}</div>`;
 return `<div class="tree-branch">${nodeCard(p,pairs,path,requiredGender,isGenderSpecific(r)?r.note:"",label)}<div class="tree-edge"></div><div class="tree-children">${ancestorNode(r.first,level+1,max,path+"a",requiredGenderFor(r,r.first),nextAncestors)}${ancestorNode(r.second,level+1,max,path+"b",requiredGenderFor(r,r.second),nextAncestors)}</div></div>`;
}
function descendantNode(p,level,max,path,ancestors=new Set()){
 const label=level===0?"起点の親":"生まれる子";
 if(ancestors.has(p.uid))return `<div class="tree-branch">${nodeCard(p,[],path,"","同じパルに戻るため、ここで表示を終了",label)}</div>`;
 const nextAncestors=new Set(ancestors);nextAncestors.add(p.uid);
 const pairs=orderedDescendantPairs(p),idx=Math.min(treeSelections.get(path)||0,Math.max(0,pairs.length-1)),r=pairs[idx];
 if(level>=max||!r)return `<div class="tree-branch">${nodeCard(p,[],path,"",!r?"配合の親にはできません":"",label)}</div>`;
 return `<div class="tree-branch">${nodeCard(p,pairs,path,requiredGenderFor(r,p),isGenderSpecific(r)?r.note:"",label)}<div class="tree-edge"></div><div class="tree-children"><div class="tree-branch">${nodeCard(r.partner,[],path+"p",requiredGenderFor(r,r.partner),"","相手の親")}</div>${descendantNode(r.child,level+1,max,path+"c",nextAncestors)}</div></div>`;
}
function applyTreeTransform(){
 const canvas=$("#treeCanvas");canvas.style.marginLeft=`${-canvas.offsetWidth*zoom/2}px`;canvas.style.transform=`translate(${panX}px,${panY}px) scale(${zoom})`;
 $("#zoomReset").textContent=`${Math.round(zoom*100)}%`;$("#zoomOut").disabled=zoom<=.08;$("#zoomIn").disabled=zoom>=2;
}
function fitTree(){
 const canvas=$("#treeCanvas"),viewport=$("#treeViewport");if(!canvas.offsetWidth||!canvas.offsetHeight)return;
 zoom=Math.max(.08,Math.min(1,(viewport.clientWidth-32)/canvas.offsetWidth,(viewport.clientHeight-52)/canvas.offsetHeight));panX=panY=0;applyTreeTransform();
}
function resetTreeView(){zoom=1;panX=panY=0;applyTreeTransform()}
function renderAll(){
 if(document.body.dataset.dataState==="ready"&&typeof restoreUIState==="function")restoreUIState(false);
 renderParents();renderTarget();renderOffspring();renderDex();renderTree();
}
