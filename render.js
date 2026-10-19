"use strict";
function initials(p){return palDisplayName(p).replace(/[（）()・\s]/g,"").slice(0,2)}
function formId(p){return String(p.sourceId||p.id)}
function formIdHTML(p,visible=false){return `<div class="form-id"${visible?"":" hidden"}>形態ID ${esc(formId(p))}</div>`}
function matchesWorkFilter(p,work,minimumLevel){
 if(!work)return true;
 const actual=Number(p.work?.[work])||0;
 return actual>0&&(minimumLevel<=0||actual>=minimumLevel);
}
function displayNo(p,padded=false){
 const raw=String(p.displayNo||`${p.no}${p.suffix||""}`);
 if(!padded)return raw;
 const match=raw.match(/^(\d+)(.*)$/);return match?match[1].padStart(3,"0")+match[2]:raw;
}
function mark(p,sm=false,informative=false){
 if(!p)return `<span class="palmark ${sm?"sm":""} placeholder" aria-hidden="true"><span class="palmark-fallback">＋</span></span>`;
 const alt=informative?`${palDisplayName(p)}のアイコン`:"";
 return `<span class="palmark ${sm?"sm":""}"${informative?"":' aria-hidden="true"'}><img class="palmark-image" src="${esc(p.icon)}" alt="${esc(alt)}" loading="lazy" decoding="async"><span class="palmark-fallback" hidden aria-hidden="true">${esc(initials(p))}</span></span>`;
}
function showPalIconFallback(image){
 image.hidden=true;
 const fallback=image.nextElementSibling;
 if(!fallback?.classList.contains("palmark-fallback"))return;
 fallback.hidden=false;
 if(image.alt){fallback.removeAttribute("aria-hidden");fallback.setAttribute("role","img");fallback.setAttribute("aria-label",image.alt)}
 image.closest(".palmark")?.classList.add("icon-error");
}
document.addEventListener("error",event=>{
 const image=event.target;
 if(image instanceof HTMLImageElement&&image.classList.contains("palmark-image"))showPalIconFallback(image);
},true);
function palHTML(p,sm=true){return `<div class="pal-inline">${mark(p,sm)}<div class="pal-info"><strong>${esc(palDisplayName(p))}</strong><div class="enname">${esc(p.en)} · No.${esc(displayNo(p,true))}</div>${formIdHTML(p)}</div></div>`}
function slotHTML(p,label,child=false){
 return `<span class="slot-label">${esc(label)}</span>${mark(p)}<div class="slot-info">${p?`<div class="jpname">${esc(palDisplayName(p))}</div><div class="enname">${esc(p.en)}</div><div class="no">No.${esc(displayNo(p,true))}</div>${formIdHTML(p)}`:`<div class="jpname">パルを選択</div><div class="enname">タップして検索</div>`}</div>${child?"":`<span class="slot-change">${p?"選び直す":"選ぶ"}</span>`}`;
}
function multiResultSlotHTML(results){
 return `<span class="slot-label">生まれる子</span><div class="multi-icons">${results.map(r=>mark(r.child,true,true)).join("")}</div><div class="slot-info"><div class="jpname">性別で${results.length}通り</div><div class="enname">下の条件別結果で確認できます</div></div>`;
}
function pickButtonHTML(p,label){return p?`${mark(p,true)}<span class="grow"><small>${esc(label)}</small><strong>${esc(palDisplayName(p))}</strong><small>${esc(p.en)} · No.${esc(displayNo(p))}</small>${formIdHTML(p)}</span><b>変更 ↗</b>`:`${mark(null,true)}<span class="grow"><small>${esc(label)}</small><strong>パルを選択</strong><small>名前・図鑑番号で検索できます</small></span><b>選択 ↗</b>`}
function usePalButton(p,destination,label){return `<button class="text-action" type="button" data-use-pal="${esc(p.uid)}" data-destination="${destination}">${esc(label)}</button>`}
function openPairButton(first,second){return `<button class="result-open" type="button" data-open-pair="true" data-first="${esc(first.uid)}" data-second="${esc(second.uid)}" aria-label="${esc(palDisplayName(first))}と${esc(palDisplayName(second))}の配合を開く">この組み合わせを使う <span aria-hidden="true">→</span></button>`}
function resultRow(r,context="list"){
 const action=context==="parents"?usePalButton(r.child,"parents","この子を親にする"):openPairButton(r.first,r.second);
 return `<article class="result-row" data-pair="${esc(pairKey(r.first.uid,r.second.uid))}" data-child="${esc(r.child.uid)}">${palHTML(r.first)}<span class="arrow" aria-hidden="true">＋</span>${palHTML(r.second)}<span class="arrow" aria-hidden="true">→</span>${palHTML(r.child)}${r.note?`<div class="note">${esc(r.note)}</div>`:""}<div class="result-actions">${action}</div></article>`;
}
function offspringGroupRow(parent,group){
 if(group.results.length===1){const result=group.results[0];return resultRow({first:parent,second:group.partner,child:result.child,note:result.note})}
 const children=group.results.map(result=>`<div class="offspring-option" data-child="${esc(result.child.uid)}">${palHTML(result.child)}<span class="note">${esc(result.note)}</span></div>`).join("");
 return `<article class="result-row grouped" data-pair="${esc(pairKey(parent.uid,group.partner.uid))}">${palHTML(parent)}<span class="arrow" aria-hidden="true">＋</span>${palHTML(group.partner)}<span class="arrow" aria-hidden="true">→</span><div class="offspring-options">${children}</div><div class="result-actions">${openPairButton(parent,group.partner)}</div></article>`;
}
function getResults(a,b){return a&&b?playableResults(pairMap.get(pairKey(a.uid,b.uid))||[]):[]}
function renderParents(){
 for(const [key,element,label] of [["a","#parentA","親 A"],["b","#parentB","親 B"]]){
  const button=$(element),pal=selected[key];button.innerHTML=slotHTML(pal,label);button.classList.toggle("selected",Boolean(pal));button.setAttribute("aria-label",`${label}：${pal?`${palDisplayName(pal)}を変更`:"パルを選択"}`);
 }
 const rs=getResults(selected.a,selected.b),child=$("#childSlot");
 child.innerHTML=rs.length===1?slotHTML(rs[0].child,"生まれる子",true):rs.length>1?multiResultSlotHTML(rs):`<span class="slot-label">生まれる子</span><span class="palmark placeholder" aria-hidden="true"><span class="palmark-fallback">?</span></span><div class="slot-info"><div class="jpname">配合結果</div><div class="enname">${selected.a||selected.b?"もう1体の親を選んでください":"親を2体選ぶと表示されます"}</div></div>`;
 $("#childActions").innerHTML=rs.length===1?`${isBreedableParent(rs[0].child)?usePalButton(rs[0].child,"parents","この子を親にする"):""}${usePalButton(rs[0].child,"target","他の親を探す")}${usePalButton(rs[0].child,"tree","配合ツリー")}`:"";
 $("#parentResults").innerHTML=rs.length>1?rs.map(r=>resultRow(r,"parents")).join(""):"";
 $("#swapParents").disabled=!selected.a&&!selected.b;$("#clearParents").disabled=!selected.a&&!selected.b;$("#copyParents").disabled=!rs.length;
}
function normalizeSearch(value){return String(value??"").normalize("NFKC").toLowerCase().replace(/[ぁ-ゖ]/g,c=>String.fromCharCode(c.charCodeAt(0)+0x60)).replace(/花付キ|花ツキ/g,"花ツキ")}
function searchTokens(q){return normalizeSearch(q).trim().split(/\s+/).filter(Boolean)}
function palSearchText(p){return normalizeSearch([palDisplayName(p),p.jp,p.en,p.id,formId(p),displayNo(p),displayNo(p,true),`No.${displayNo(p,true)}`,String(p.no)].join(" "))}
function searchable(p,q){const text=palSearchText(p);return searchTokens(q).every(token=>text.includes(token))}
function searchableGroup(group,q){const text=group.map(palSearchText).join(" ");return searchTokens(q).every(token=>text.includes(token))}
function updateSearchClear(id){const button=document.querySelector(`[data-clear="${id}"]`);if(button)button.hidden=!$("#"+id).value}
function emptyHTML(title,description="",reset=""){return `<div class="empty"><strong>${esc(title)}</strong>${description?`<p>${esc(description)}</p>`:""}${reset?`<button type="button" class="action" data-reset-scope="${reset}">絞り込みを解除</button>`:""}</div>`}
function renderTarget(){
 $("#targetPick").innerHTML=pickButtonHTML(selected.target,"作りたいパル");
 const all=selected.target?playableResults(parentsByChild.get(selected.target.uid)||[]):[],q=$("#targetFilter").value||"";
 let list=all.filter(r=>searchableGroup([r.first,r.second],q));
 const sort=$("#targetSort").value;
 list.sort((x,y)=>(sort==="name"?palDisplayName(x.first).localeCompare(palDisplayName(y.first),"ja"):sort==="power"?x.first.power-y.first.power:palSort(x.first,y.first))||palSort(x.second,y.second));
 $("#targetCount").textContent=selected.target?`${list.length.toLocaleString()}組`:"";
 $("#targetResults").innerHTML=list.length?list.map(r=>resultRow(r)).join(""):!selected.target?emptyHTML("作りたいパルを選んでください","入手に必要な親の組み合わせを一覧にします。"):!all.length?emptyHTML("配合では入手できません",`${palDisplayName(selected.target)}を子にする親候補はありません。`):emptyHTML("見つかりませんでした","親の名前を変えるか、絞り込みを解除してください。","target");
 updateSearchClear("targetFilter");
}
function playableOffspringGroups(parent){
 if(!parent||!isBreedableParent(parent))return [];
 return (offspringByParent.get(parent.uid)||[]).map(group=>({...group,results:playableResults(group.results)})).filter(group=>isBreedableParent(group.partner)&&group.results.length);
}
function renderOffspring(){
 $("#singleParentPick").innerHTML=pickButtonHTML(selected.parent,"基準にする親");
 const all=playableOffspringGroups(selected.parent),q=$("#offspringFilter").value||"";
 let list=all.filter(group=>searchableGroup([group.partner,...group.results.map(result=>result.child)],q));
 const sort=$("#offspringSort").value,primary=group=>group.results[0].child;
 list.sort((x,y)=>(sort==="partner"?palSort(x.partner,y.partner):sort==="name"?palDisplayName(primary(x)).localeCompare(palDisplayName(primary(y)),"ja"):palSort(primary(x),primary(y)))||palSort(x.partner,y.partner));
 $("#offspringCount").textContent=selected.parent?`${list.length.toLocaleString()}組`:"";
 $("#offspringResults").innerHTML=list.length?list.map(group=>offspringGroupRow(selected.parent,group)).join(""):selected.parent?emptyHTML("見つかりませんでした","相手や子の名前を変えるか、絞り込みを解除してください。","offspring"):emptyHTML("親にするパルを選んでください","配合相手と、生まれる子をまとめて確認できます。");
 updateSearchClear("offspringFilter");
}
function renderDex(){
 let list=[...pals],q=$("#dexSearch").value||"",v=$("#dexVariant").value,el=$("#dexElement").value,w=$("#dexWork").value,l=+$("#dexWorkLevel").value;
 $("#dexWorkLevel").disabled=!w;
 list=list.filter(p=>searchable(p,q)&&(v==="all"||(v==="variant")===p.variant)&&(!el||p.elements.includes(el))&&matchesWorkFilter(p,w,l));
 const s=$("#dexSort").value;list.sort((a,b)=>s==="desc"?palSort(b,a):s==="jp"?palDisplayName(a).localeCompare(palDisplayName(b),"ja"):s==="power"?a.power-b.power:palSort(a,b));
 $("#dexCount").textContent=`${list.length}形態`;
 $("#dexReset").disabled=!(q||v!=="all"||el||w||l);
 $("#dexGrid").innerHTML=list.length?list.map(p=>`<article class="pal-card" data-id="${esc(p.uid)}"><div class="pal-card-main">${mark(p,true)}<div><div class="no">No.${esc(displayNo(p,true))}</div><strong>${esc(palDisplayName(p))}</strong><div class="enname">${esc(p.en)}</div></div></div><div class="tags">${p.elements.map(e=>`<span class="tag element-tag">${esc(ELEMENT_JP[e]||e)}</span>`).join("")}${Object.entries(p.work).filter(([,x])=>x).map(([k,x])=>`<span class="tag">${esc(WORK_JP[k]||k)}Lv.${x}</span>`).join("")}${isBreedableParent(p)?"":'<span class="tag">配合牧場に配置不可</span>'}</div><div class="pal-card-actions">${isBreedableParent(p)?usePalButton(p,"offspring","このパルを親にする"):""}${usePalButton(p,"target","作り方を探す")}</div><details class="pal-details"><summary>データ詳細</summary>${formIdHTML(p,true)}<div class="no">配合値 ${p.power}</div></details></article>`).join(""):emptyHTML(pals.length?"見つかりませんでした":document.body.dataset.dataState==="error"?"データを読み込めませんでした":"データを読み込んでいます",pals.length?"名前や条件を変えて検索してください。":document.body.dataset.dataState==="error"?"上のデータ状態を押して再試行してください。":"",pals.length?"dex":"");
 updateSearchClear("dexSearch");
}
function fillFilterOptions(){
 const elements=[...new Set(pals.flatMap(p=>p.elements))],works=[...new Set(pals.flatMap(p=>Object.keys(p.work)))];
 elements.sort((a,b)=>Object.keys(ELEMENT_JP).indexOf(a)-Object.keys(ELEMENT_JP).indexOf(b));works.sort((a,b)=>Object.keys(WORK_JP).indexOf(a)-Object.keys(WORK_JP).indexOf(b));
 for(const id of ["dexElement","pickerElement"]){const el=$("#"+id);el.innerHTML='<option value="">全属性</option>';for(const e of elements)el.insertAdjacentHTML("beforeend",`<option value="${esc(e)}">${esc(ELEMENT_JP[e]||e)}</option>`)}
 for(const id of ["dexWork","pickerWork"]){const el=$("#"+id);el.innerHTML='<option value="">全作業適性</option>';for(const w of works)el.insertAdjacentHTML("beforeend",`<option value="${esc(w)}">${esc(WORK_JP[w]||w)}</option>`)}
}
