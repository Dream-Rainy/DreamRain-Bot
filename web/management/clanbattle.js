"use strict";
window.clanUI={
 el(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;},
 cell(value){const e=this.el("td");if(!value||typeof value!=="object"){e.textContent=value??"—";return e;}
   if(value.type==="knife"){const main=this.el("span",value.text,"cell-main");main.style.color=value.color;main.style.background=value.background||"transparent";e.append(main,this.el("small",value.detail,"cell-detail"));}
   else if(value.type==="tags"){const tags=this.el("div",undefined,"tags");for(const name of value.items){const tag=this.el("span",name,"tag");tag.style.color=value.filled?"white":value.color;if(value.filled)tag.style.background=value.color;tags.append(tag);}e.append(tags);}
   else if(value.type==="hp"){const track=this.el("div",undefined,"hp-track"),fill=this.el("div",undefined,"hp-fill");fill.style.width=Math.max(0,Math.min(100,value.ratio*100))+"%";fill.style.background=value.color;track.append(fill);e.append(this.el("div",value.label,"hp-value"),track,this.el("div",value.caption,"hp-zone"));}
   return e;
 },
 render(data,root){root.replaceChildren();if(data.cards?.length){const cards=this.el("div",undefined,"stat-cards");for(const [value,label] of data.cards){const card=this.el("div",undefined,"stat-card");card.append(this.el("small",label),this.el("strong",value));cards.append(card);}root.append(cards);}if(data.columns){const grid=this.el("div",undefined,"range-grid");for(const col of data.columns){const card=this.el("section",undefined,"range-column");card.append(this.el("h3",col.title),this.el("p",col.subtitle,"muted"));for(const [i,group] of col.groups.entries()){const box=this.el("div",undefined,"range-group"),title=this.el("div",group.range,"range-title");box.style.borderLeftColor=["#315bba","#5579c1","#7f99ce","#a2b4d8"][i];title.append(this.el("small",group.count+"人"));box.append(title);for(const [name,count] of group.members){const m=this.el("div",undefined,"range-member");m.append(this.el("span",name),this.el("small",count+"刀"));box.append(m);}card.append(box);}if(!col.groups.length)card.append(this.el("p","暂无样本","empty"));grid.append(card);}root.append(grid);}
   for(const [title,columns,rows] of data.sections||[]){const section=this.el("section",undefined,"report-section");if(title)section.append(this.el("h3",title));const wrap=this.el("div",undefined,"table-card"),table=this.el("table"),head=this.el("thead"),tr=this.el("tr"),body=this.el("tbody");for(const c of columns)tr.append(this.el("th",c));head.append(tr);for(const row of rows){const line=this.el("tr");for(const value of row)line.append(this.cell(value));body.append(line);}table.append(head,body);wrap.append(table);if(!rows.length)wrap.append(this.el("p","暂无记录","empty"));section.append(wrap);root.append(section);}
 }
};

window.clanUI.editorFilters=function(view,root,apply){
  root.hidden=!['people','records'].includes(view);
  if(root.dataset.view===view)return;
  root.dataset.view=view;root.replaceChildren();
  if(root.hidden)return;
  const el=(...args)=>this.el(...args);
  function input(name,label,options){const box=el('label',label),field=el(options?'select':'input');field.name=name;
    if(options)for(const [value,text] of options)field.append(new Option(text,value));
    else{field.type='search';field.maxLength=100;}
    box.append(field);root.append(box);}
  input('q','搜索');
  if(view==='people')input('state','成员状态',[['','全部'],['unbound','未绑定'],['invalid','失效关联'],['conflict','关联冲突'],['pending','刀型待核验'],['queue','有登记']]);
  else{input('pcrid','游戏ID');input('day','活动日',[['','全部'],...[1,2,3,4,5].map(i=>[String(i),'第'+i+'天'])]);
    input('boss','目标王',[['','全部'],...[1,2,3,4,5].map(i=>[String(i),i+'王'])]);
    input('kind','刀型',[['','全部'],['pending','待核验'],['manual','人工修正'],['full','完整刀'],['tail','尾刀'],['comp','补偿刀']]);}
  const submit=el('button','筛选');root.append(submit);root.onsubmit=event=>{event.preventDefault();apply();};
};

window.clanUI.manage=function(view,data,root,actions){
  const ui=this,el=(...args)=>ui.el(...args),labels={'bound':'已关联','unbound':'未绑定','invalid':'失效关联','conflict':'关联冲突'};
  const sourceText=row=>row.carry_source_id?'#'+row.carry_source_id:row.manual_source?'人工指定 #'+row.manual_source+'（待核验）':'待核验 / 未使用';
  const kind=value=>value===0?'完整刀':value===1?'尾刀':value===.5?'补偿刀':'待核验';
  const number=value=>value===null||value===undefined?'—':String(value).replace(/\B(?=(\d{3})+(?!\d))/g,',');
  root.replaceChildren();
  function button(text,fn,cls='secondary'){const b=el('button',text,cls);b.type='button';b.disabled=!!actions.stale;b.onclick=async()=>{if(actions.stale)return;b.disabled=true;let enabled=true;try{enabled=(await fn())!==false;}catch(error){actions.notice(error.message,true);}finally{if(b.isConnected)b.disabled=!enabled;}};return b;}
  function table(headers){const wrap=el('div',undefined,'table-card'),t=el('table'),thead=el('thead'),tr=el('tr'),tbody=el('tbody');
    for(const h of headers)tr.append(el('th',h));thead.append(tr);t.append(thead,tbody);wrap.append(t);return {wrap,tbody};}
  function dialog(title){const d=el('dialog',undefined,'editor-dialog');d.setAttribute('aria-label',title);
    const head=el('div',undefined,'dialog-heading');head.append(el('h2',title),button('关闭',()=>d.close()));d.append(head);root.append(d);
    d.addEventListener('close',()=>d.remove(),{once:true});d.showModal();return d;}
  function field(form,label,node){const box=el('label',label,'editor-field');box.append(node);form.append(box);return node;}
  function errorNode(){const n=el('p','', 'inline-error');n.setAttribute('role','status');return n;}
  async function confirmChange(title,text,perform){const d=dialog(title);d.append(el('p',text,'muted'));const error=errorNode();
    d.append(error,button('确认',async()=>{try{await perform();d.close();await actions.refresh();}catch(e){error.textContent=e.message;}}));}
  function linkEditor(row){const d=dialog('关联会战成员'),form=el('form');form.onsubmit=e=>e.preventDefault();
    const qq=el('input');qq.value=data.editable?(row.qq[0]||data.actor):data.actor;qq.readOnly=!data.editable;qq.inputMode='numeric';qq.maxLength=20;
    const uid=el('input');uid.value=/^[0-9]+$/.test(row.pcrid)?row.pcrid:'';uid.readOnly=!!uid.value;uid.inputMode='numeric';uid.maxLength=20;
    field(form,'QQ号',qq);field(form,'游戏ID',uid);const error=errorNode();form.append(error,button('保存关联',async()=>{
      try{const result=await actions.request('people/link',{period_id:data.period_id,expected:data.version,qq:qq.value.trim(),uid:uid.value.trim()});
        d.close();await actions.refresh();actions.notice(result.message);}catch(e){error.textContent=e.message;}}));d.append(form);
  }
  if(view==='people'){
    const summary=el('div',undefined,'management-summary');summary.append(el('span','本期成员与身份登记'),el('small',data.total+'条 · 关联维护不会改变游戏名册'));root.append(summary);
    const {wrap,tbody}=table(['成员 / 游戏ID','QQ关联','今日折算 / 补偿','当前登记','管理']);
    for(const row of data.items){const tr=el('tr'),name=el('td'),identity=el('td'),daily=el('td'),queues=el('td'),operations=el('td');
      name.append(el('strong',row.name),el('small',row.pcrid,'subtext'));identity.append(el('span',labels[row.state]||row.state,'state-badge '+row.state));
      for(const qq of row.qq)identity.append(el('small','QQ '+qq,'subtext'));
      daily.append(el('strong',row.knife===null?'—':row.knife+'刀'+(row.pending?' *':'')),el('small',row.inventory.filter(v=>v!=='—').join('；'),'subtext'));
      for(const entry of row.registrations){const item=el('div',undefined,'queue-item');item.append(el('span',entry.boss+'王 · '+{apply:'申请',tree:'挂树',subscribe:'预约'}[entry.kind]),el('small',entry.text||'无留言','subtext'));
        if(data.editable)item.append(button('清理',()=>confirmChange('清理登记',row.name+' · '+entry.boss+'王 · '+entry.text,
          ()=>actions.request('queues/delete',{period_id:data.period_id,id:entry.id,kind:entry.kind,expected:entry.expected}))));queues.append(item);}
      if(!row.registrations.length)queues.textContent='—';
      const opts=el('div',undefined,'row-actions');
      if(data.editable||row.state==='unbound'||row.qq.includes(data.actor))opts.append(button('关联',()=>linkEditor(row)));
      for(const qq of row.qq)if(data.editable||qq===data.actor)opts.append(button('解绑 '+qq,()=>confirmChange('解除关联',row.name+' ↔ QQ '+qq,
        ()=>actions.request('people/link',{period_id:data.period_id,expected:data.version,qq,uid:null}))));
      if(/^[0-9]+$/.test(row.pcrid))opts.append(button('查看出刀',()=>actions.focusRecords(row.pcrid)));operations.append(opts);
      tr.append(name,identity,daily,queues,operations);tbody.append(tr);
    }root.append(wrap);if(!data.items.length)root.append(el('p','没有符合条件的成员','empty'));return;
  }
  const {wrap,tbody}=table(['记录 / 结算时间','成员 / 目标','原始刀伤','起始 / 实际时长','刀型','核验状态','操作']);
  for(const row of data.items){const tr=el('tr'),id=el('td'),member=el('td'),type=el('td');id.append(el('strong','#'+row.id),el('small',row.time_text,'subtext'));
    member.append(el('strong',row.name),el('small',row.lap+'周目'+row.boss+'王','subtext'));type.append(el('strong',kind(row.flag)),el('small','原始：'+kind(row.raw_flag),'subtext'));
    const action=el('td');action.append(button(data.editable?'核对 / 纠正':'详情',()=>openRecord(row.id)));
    tr.append(id,member,el('td',number(row.damage)),el('td',row.remain_time>0?row.remain_time+'s / '+row.battle_time+'s':'未采集'),type,
      el('td',row.manual_flag!==null?'人工修正'+(row.pending?' · 待核验':''):row.pending?'待核验':'已识别'),action);tbody.append(tr);}
  root.append(wrap);if(!data.items.length)root.append(el('p','没有符合条件的记录','empty'));

  async function openRecord(id){const details=await actions.request('records/'+id),row=details.record,d=dialog('出刀核对 · #'+id+' · '+row.name);
    const facts=el('div',undefined,'record-facts');
    for(const [label,value] of [['结算',row.time_text],['目标',row.lap+'周目'+row.boss+'王'],['原始刀伤',number(row.damage)],['有效扣血',number(row.effective_damage)],
      ['起始 / 实际时长',row.remain_time>0?row.remain_time+'s / '+row.battle_time+'s':'未采集'],['原始标记',kind(row.raw_flag)],['当前结果',kind(row.flag)],['补偿来源',sourceText(row)]]){
      const box=el('div');box.append(el('small',label),el('strong',value));facts.append(box);}d.append(facts);
    if(details.editable){const form=el('form',undefined,'correction-form');form.onsubmit=e=>e.preventDefault();
      const choices=el('div',undefined,'correction-fields'),flag=el('select'),source=el('select'),reason=el('textarea');
      flag.id='correction-kind';source.id='correction-source';reason.id='correction-reason';reason.maxLength=200;reason.rows=2;reason.required=true;
      for(const [value,text] of [['full','完整刀'],['tail','尾刀'],['comp','补偿刀'],['auto','撤销人工修正，恢复推断']])flag.append(new Option(text,value));
      flag.value=row.manual_flag!==null?({0:'full',1:'tail',0.5:'comp'}[row.manual_flag]):({0:'full',1:'tail',0.5:'comp'}[row.flag]||'auto');
      source.append(new Option('按整日记录推断',''));
      for(const r of details.sources)source.append(new Option('#'+r.id+' · '+r.time_text+' · '+r.lap+'周目'+r.boss+'王',String(r.id)));
      source.value=row.manual_source?String(row.manual_source):'';source.disabled=flag.value!=='comp';
      field(choices,'修正刀型',flag);field(choices,'补偿来源',source);field(form,'修正原因',reason);form.prepend(choices);
      const previewArea=el('div',undefined,'correction-preview');previewArea.id='correction-preview';const error=errorNode(),controls=el('div',undefined,'row-actions');
      let preview=null,operation=null,editVersion=0;
      const save=button('确认保存',async()=>{if(!preview)return false;try{await actions.request('records/'+id+'/save',{...operation,expected:preview.version});d.close();await actions.refresh();actions.notice('修正已保存，相关刀型与补偿库存已重算。');}
        catch(e){error.textContent=e.message;preview=null;save.disabled=true;return false;}});save.id='correction-save';save.disabled=true;
      const previewButton=button('预览整日影响',async()=>{error.textContent='';save.disabled=true;if(!reason.value.trim()){error.textContent='请填写修正原因';return;}
        operation={period_id:details.period_id,flag:flag.value,source_id:flag.value==='comp'&&source.value?Number(source.value):null,reason:reason.value.trim()};
        try{const stamp=editVersion,result=await actions.request('records/'+id+'/preview',operation);if(stamp!==editVersion)return;preview=result;renderPreview(preview,previewArea);save.disabled=false;}catch(e){preview=null;previewArea.replaceChildren();error.textContent=e.message;}});previewButton.id='correction-preview-button';
      for(const control of [flag,source,reason])control.addEventListener('input',()=>{editVersion++;source.disabled=flag.value!=='comp';preview=null;save.disabled=true;previewArea.replaceChildren();});
      controls.append(previewButton,save);form.append(error,controls,previewArea);d.append(form);
    }
    const history=el('section',undefined,'correction-history');history.append(el('h3','修正历史 · 最近20条'));
    for(const entry of row.history){const item=el('div',undefined,'history-entry');item.append(el('strong','#'+entry.revision+' · '+entry.actor+' · '+entry.reason),
      el('small',new Date(entry.time*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})+' · '+manualText(entry.before)+' → '+manualText(entry.after),'subtext'));history.append(item);}
    if(!row.history.length)history.append(el('p','暂无人工修正记录','muted'));d.append(history);
  }
  function manualText(value){return value.manual_flag===undefined?'自动推断':kind(value.manual_flag)+(value.manual_source?'，来源 #'+value.manual_source:'');}
  function renderPreview(preview,container){container.replaceChildren(el('h3','整日影响预览'));
    container.append(el('p','记录折算 '+preview.before.knife+' → '+preview.after.knife+'刀；库存：'+preview.after.inventory.filter(v=>v!=='—').join('；'),'preview-summary'));
    if(preview.after.status!=='ok')container.append(el('p',preview.after.issue||'采集不足，补偿库存仍待核验','inline-warning'));
    const {wrap,tbody}=table(['记录','原结果','预览结果','来源']);
    for(const after of preview.after.records){const before=preview.before.records.find(r=>r.id===after.id);const tr=el('tr');tr.append(el('td','#'+after.id+' '+after.time_text),el('td',kind(before?.flag)),el('td',kind(after.flag)),el('td',sourceText(after)));tbody.append(tr);}container.append(wrap);
  }
};
