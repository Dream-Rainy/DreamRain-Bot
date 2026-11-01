"use strict";
(()=>{
 const $=id=>document.getElementById(id),el=(...a)=>window.clanUI.el(...a);
 let profile,view="status",offset=0,generation=0,aliasMounted=false,settings,revision=0,closed=false,expiryTimer;
 const cached=new Map(),pending=new Map();
 const routes={clanbattle:"/manage/clanbattle/",aliases:"/manage/aliases/"};
 const tabs={status:"会战状态",daily:"今日出刀",members:"五日明细",ranges:"刀伤分档",queues:"登记队列",carryover:"补偿库存",settings:"播报设置",people:"人员管理",records:"出刀纠正"};
 const readable=path=>/^clanbattle\/(status|daily|members|ranges|queues|carryover|people|records)\?/.test(path);
 function notice(text,error=false){$("notice").textContent=text;$("notice").className=error?"error":"";$("notice").hidden=!text;}
 function invalidate(){revision++;cached.clear();pending.clear();clearTimeout(expiryTimer);}
 function timing(name,start){performance.clearMeasures(name);performance.measure(name,{start,end:performance.now()});}
 async function api(path,body){
   const reading=body===undefined&&readable(path),version=revision,key=version+":"+path;
   if(reading&&pending.has(key))return pending.get(key);
   const send=async()=>{const start=performance.now();try{
     const response=await window.editorRelay.request(path,body),data=await response.json();
     if(!response.ok){if([401,403].includes(response.status))invalidate();const error=new Error(data.detail||"操作失败");error.status=response.status;throw error;}
     if(body!==undefined&&!path.split("?")[0].endsWith("/preview"))invalidate();
     else if(version!==revision||closed)throw new Error("数据已变化，请刷新核对。");
     return data;
   }finally{timing("management.rpc",start);}};
   const task=send();if(reading)pending.set(key,task);
   try{return await task;}finally{if(pending.get(key)===task)pending.delete(key);}
 }
 function query(path,group=$("group-id").value){const params=new URLSearchParams({group,offset,limit:30});
   if(path===view&&['people','records'].includes(view))for(const field of $("editor-filters").querySelectorAll('[name]'))if(field.value)params.set(field.name,field.value);
   return "clanbattle/"+path+"?"+params;}
 function previousResult(path){
   for(const [key,entry] of cached){if(entry.expires<=performance.now())cached.delete(key);else if(entry.path===path){cached.delete(key);cached.set(key,entry);return entry;}}
 }
 function remember(path,group,data,started){
   const info=data.freshness;
   if(!info||!Number.isFinite(info.valid_until)||!Number.isFinite(info.as_of))return;
   for(const [key,entry] of cached)if(entry.group===group&&(entry.info.period_id!==info.period_id||entry.info.game_day!==info.game_day||entry.path===path))cached.delete(key);
   const key=path+"|"+info.period_id+"|"+info.game_day,expires=started+Math.min(10,info.valid_until-info.as_of)*1000;
   if(expires>performance.now())cached.set(key,{path,group,data,info,expires});
   while(cached.size>16)cached.delete(cached.keys().next().value);
 }
 function refreshState(text,stale=false){$("refresh-state").textContent=text;$("refresh-state").classList.toggle("stale",stale);}
 function display(data,target,group,page,stamp,stale){
   $("permission").textContent=stale?"刷新中 · 操作暂不可用":data.editable?"群管理权限":target==="people"?"成员 · 自助登记":"成员 · 只读";
   $("report-title").textContent=tabs[target];$("report-meta").textContent="群 "+group;
   if(target==="settings"){settings=data.settings;renderSettings(data.editable,group);$("report-note").textContent="关闭普通播报仍继续采集。监控群默认收到期末档线。";$("page-number").textContent="";return;}
   if(['people','records'].includes(target)){
     window.clanUI.manage(target,data,$("report"),{stale,
       request:async(path,body)=>{if(stale||stamp!==generation)throw new Error("请等待最新数据后再操作。");const result=await api(query(path,group),body);if(body===undefined&&stamp!==generation)throw new Error("页面已切换，请重新打开详情。");return result;},
       refresh:load,notice,focusRecords:uid=>chooseView('records',uid)});
     $("report-meta").textContent="群 "+group+" · 第"+data.period_id+"期 · "+data.total+"条";
     $("report-note").textContent=target==='records'?"修正先预览整日影响；保存后可查看历史并撤销。":"QQ身份关联仅作用于会战调度。";
   }else{const report=data.report;$("report-title").textContent=report.title;$("report-meta").textContent=report.metadata+(report.caption?"\n"+report.caption:"");$("report-note").textContent=report.note;window.clanUI.render(report,$("report"));}
   $("previous").disabled=page===0;$("next").disabled=!data.has_more;$("page-number").textContent="第 "+(page/30+1)+" 页";
 }
 async function load(){
   window.clanUI.editorFilters(view,$("editor-filters"),()=>{offset=0;load();});
   if(!$("group-id").checkValidity()){notice("请先输入有效群号",true);return;}
   const stamp=++generation,group=$("group-id").value,target=view,page=offset,path=query(target,group),started=performance.now(),old=previousResult(path);
   clearTimeout(expiryTimer);
   notice("");$("refresh").disabled=true;$("previous").disabled=$("next").disabled=true;
   if(old){display(old.data,target,group,page,stamp,true);refreshState("上次结果 · 刷新中",true);timing("management.display",started);
     expiryTimer=setTimeout(()=>{if(stamp===generation){$("report").replaceChildren();refreshState("结果已过期，请刷新",true);}},Math.max(0,old.expires-performance.now()));}
   else{$("report").replaceChildren(el("p","正在读取…","empty"));$("permission").textContent="核验中";$("report-title").textContent=tabs[target];$("report-meta").textContent="群 "+group;$("report-note").textContent="";refreshState("刷新中");}
   try{
     const data=await api(path);if(stamp!==generation||closed)return;
     const info=data.freshness;
     if(info&&started+Math.min(10,info.valid_until-info.as_of)*1000<=performance.now()){
       invalidate();$("report").replaceChildren();throw new Error("结果已过期，请重新刷新。");
     }
     clearTimeout(expiryTimer);
     if(readable(path))remember(path,group,data,started);
     display(data,target,group,page,stamp,false);
     refreshState("已刷新 "+new Date().toLocaleTimeString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}));timing("management.display",started);
   }catch(e){if(stamp===generation&&!closed){const denied=[401,403].includes(e.status);if(!old||denied)$("report").replaceChildren();$("permission").textContent=denied?"无访问权限":"操作不可用";refreshState(old&&!denied?"上次结果 · 刷新失败，操作不可用":"刷新失败",!!old);notice(e.message,true);}}
   finally{if(stamp===generation)$("refresh").disabled=false;}
 }
 function renderSettings(editable,group){const card=el("form",undefined,"settings-card");for(const [key,label,detail] of [["broadcast","普通监控播报","结算与常规排名消息"],["rankline","期末档线订阅","当期最后一天 23:55"]]){const row=el("div",undefined,"setting-row"),labelNode=el("label",label),input=el("input");input.id="setting-"+key;input.type="checkbox";input.checked=settings[key];input.disabled=!editable;labelNode.htmlFor=input.id;labelNode.append(el("small",detail));row.append(labelNode,input);card.append(row);}const button=el("button","保存设置");button.disabled=!editable;card.append(button);card.addEventListener("submit",async event=>{event.preventDefault();button.disabled=true;try{const changes={broadcast:$("setting-broadcast").checked,rankline:$("setting-rankline").checked};await api(query("settings",group),{expected:settings,changes});await load();notice("设置已保存");}catch(e){notice(e.message+"；请刷新核对后再操作。",true);}finally{if(button.isConnected)button.disabled=!editable;}});$("report").replaceChildren(card);}
 async function select(module,push=true){
   if(closed||!profile)return;
   const stamp=++generation,allowed=!!routes[module]&&profile.modules.some(m=>m.id===module);
   clearTimeout(expiryTimer);$("welcome").hidden=true;
   $("clan-panel").hidden=!allowed||module!=="clanbattle";$("aliases-panel").hidden=!allowed||module!=="aliases";
   for(const b of $("modules").children)b.setAttribute("aria-current",allowed&&b.dataset.module===module?"page":"false");
   if(!allowed){$("page-title").textContent="管理工作台";notice(module?"当前账号无此模块访问权限":"当前没有可访问的模块",true);return;}
   if(push&&location.pathname!==routes[module])history.pushState(null,"",routes[module]);
   notice("");$("page-title").textContent=module==="clanbattle"?"公会战指挥台":"别名工作台";
   if(module==="clanbattle"){if($("group-id").value)await load();}
   else if(!aliasMounted){aliasMounted=true;try{await window.mountAliasPortal($("aliases-panel"),{request:(path,body)=>window.editorRelay.request("aliases/"+path,body),socket:window.editorRelay.socket},logout);}catch(e){aliasMounted=false;if(stamp===generation&&!closed)notice(e.message,true);}}
 }
 async function followLocation(){
   if(!profile||closed)return;
   if(location.pathname==="/manage/")return select((profile.modules.find(m=>m.id==="clanbattle")||profile.modules[0])?.id,false);
   const module=Object.keys(routes).find(id=>routes[id]===location.pathname);
   if(module)return select(module,false);
   generation++;clearTimeout(expiryTimer);$("welcome").hidden=$("clan-panel").hidden=$("aliases-panel").hidden=true;
   $("page-title").textContent="管理工作台";notice("页面不存在",true);
 }
 async function logout(){invalidate();generation++;try{await api("logout",{});}finally{closed=true;window.editorRelay.socket?.close();$("clan-panel").hidden=$("aliases-panel").hidden=true;$("report").replaceChildren();$("modules").replaceChildren();notice("会话已退出，请重新获取链接。");}}
 function chooseView(id,pcrid=''){view=id;offset=0;for(const b of $("clan-tabs").children)b.setAttribute("aria-current",b.dataset.view===id?"page":"false");
   window.clanUI.editorFilters(view,$("editor-filters"),()=>{offset=0;load();});if(pcrid)$("editor-filters").elements.pcrid.value=pcrid;load();}
 for(const [id,title] of Object.entries(tabs)){const button=el("button",title);button.dataset.view=id;button.setAttribute("aria-current",id===view?"page":"false");button.onclick=()=>chooseView(id);$("clan-tabs").append(button);}
 $("group-form").onsubmit=e=>{e.preventDefault();offset=0;load();};$("refresh").onclick=load;$("previous").onclick=()=>{offset=Math.max(0,offset-30);load();};$("next").onclick=()=>{offset+=30;load();};$("logout").onclick=logout;
 window.addEventListener("editorclosed",()=>{closed=true;invalidate();generation++;$("report").replaceChildren();$("clan-panel").hidden=$("aliases-panel").hidden=true;$("modules").replaceChildren();$("logout").hidden=true;});
 window.addEventListener("popstate",()=>followLocation());
 (async()=>{try{profile=await api("me");$("identity").textContent=profile.label;$("logout").hidden=false;$("group-id").value=profile.group_id||"";for(const m of profile.modules){const b=el("button",m.title);b.dataset.module=m.id;b.onclick=()=>select(m.id);$("modules").append(b);}await followLocation();}catch(e){notice(e.message,true);}})();
})();
