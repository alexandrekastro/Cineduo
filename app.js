'use strict';
const $ = id => document.getElementById(id);
const state = { movies: [], settings: {has_key:false}, view:'tiers',
  term:'', sort:'manual', activeId:null, selectedSearch:null, syncBusy:false, actorsIncludeSeries:false, actorPhotos:new Map(), enrichingCast:false, cancelCast:false, sagas:[], selectedSaga:null, sagaBusy:false, sagaError:null, sagaLoading:false };
const COLORS={10:'#fe5958',9:'#ffa22e',8:'#ffe054',7:'#94db6d',6:'#5fc9b0',5:'#6fc1e6',4:'#a3a0f3',3:'#d58ed0',2:'#9ba0b7',1:'#737a8e',0:'#575d6c'};
const TITLES={10:'EXCEPCIONAL',9:'INCRÍVEL',8:'MUITO BOM',7:'BOM',6:'LEGAL',5:'REGULAR',4:'FRACO',3:'RUIM',2:'MUITO RUIM',1:'PÉSSIMO',0:'NÃO CURTIMOS'};
const h = s => String(s??'').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const norm=s=>String(s??'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
const val=id=>$(id).value.trim();
const pct = (n,d) => d ? Math.round(n/d*100):0;
const num = v=> Number.isFinite(Number(v)) ? Number(v) : -1;
const posterUrl=src=>{ const s=String(src||''); return s.startsWith('/posters/')||/^https:\/\//.test(s)?s:''; };

async function api(path,method='GET',data){
  const opts={method,headers:{'Accept':'application/json'}};
  if(data!==undefined){opts.headers['Content-Type']='application/json';opts.body=JSON.stringify(data)}
  let response;
  try{response=await fetch(path,opts)}catch{throw Error('Sem conexão com o aplicativo. Ele ainda está aberto no computador?')}
  let result;
  try{result=await response.json()}catch{throw Error('A resposta do servidor não pôde ser lida.')}
  if(!response.ok)throw Error(result.error||'Não foi possível completar a operação.');
  return result;
}
let toastTimeout;
function toast(message,type='success'){
  const el=$('toast');el.textContent=message;el.className='toast '+type;
  clearTimeout(toastTimeout);toastTimeout=setTimeout(()=>el.classList.add('hidden'),4800);
}
let progressHideTimer=null;
let progressTaskId=0;
function progressBegin(label,total){
  clearTimeout(progressHideTimer);
  const task=++progressTaskId;
  const box=$('sync-progress');
  box.className='progress task-progress';
  $('progress-heading').textContent=label;
  $('progress-current').textContent='Preparando consulta...';
  $('sync-details').textContent='';
  progressUpdate(task,0,total,'Aguardando primeira resposta');
  return task;
}
function progressUpdate(task,done,total,current='',message=''){
  if(task!==progressTaskId)return;
  const safeTotal=Math.max(0,Number(total)||0);
  const count=Math.min(Math.max(0,Number(done)||0),safeTotal);
  const remaining=Math.max(safeTotal-count,0);
  const percent=pct(count,safeTotal);
  $('progress-counter').textContent=`${count} / ${safeTotal}`;
  $('progress-text').textContent=`${count} de ${safeTotal} consultados`;
  $('progress-remaining').textContent=`${remaining} ${remaining===1?'restante':'restantes'}`;
  $('progress-current').textContent=current;
  $('sync-details').textContent=message;
  $('progress-fill').style.width=percent+'%';
  $('sync-progress').querySelector('[role="progressbar"]').setAttribute('aria-valuenow',String(percent));
}
function progressFinish(task,summary,details='',hasError=false){
  if(task!==progressTaskId)return;
  const box=$('sync-progress');
  box.classList.toggle('task-progress-error',hasError);
  box.classList.toggle('task-progress-done',!hasError);
  $('progress-heading').textContent=hasError?'Consulta finalizada com avisos':'Atualização concluída';
  $('progress-current').textContent=summary;
  $('sync-details').textContent=details;
  $('progress-remaining').textContent='Finalizado';
  // Não inventar 100% quando a pesquisa foi interrompida com falha.
  progressHideTimer=setTimeout(()=>{
    if(task===progressTaskId)box.classList.add('hidden');
  },hasError?6500:4200);
}
function optionsScore(selected=null){
  const choices=['<option value="">A avaliar (sem nota)</option>'];
  for(let i=10;i>=0;i--)choices.push(`<option value="${i}" ${selected===i?'selected':''}>${i} / 10 — ${TITLES[i]}</option>`);
  return choices.join('');
}
function setScore(id,v){$(id).innerHTML=optionsScore(v);$(id).value=v===null?'':String(v)}
function scoreFrom(id){let x=$(id).value;return x===''?null:Number(x)}
function ratingText(v){return v===null||v===undefined?'A avaliar':`${v}/10`}
function filteredMovies(){
  let a=state.movies.filter(m=>{
    if(state.term&&!norm(`${m.title} ${m.original_title||''} ${m.genre||''} ${m.director||''}`).includes(norm(state.term)))return false;
    return true;
  });
  const sorting={
    title:(a,b)=>a.title.localeCompare(b.title,'pt-BR'),
    imdb:(a,b)=>num(b.imdb_rating)-num(a.imdb_rating),
    critics:(a,b)=>num(b.metascore)-num(a.metascore),
    year:(a,b)=>num(b.year)-num(a.year),
    manual:(a,b)=>(a.sort_order??0)-(b.sort_order??0)||a.id-b.id
  };
  return a.sort(sorting[state.sort]);
}
function posterMarkup(m){
  const src=posterUrl(m.poster_url);
  const imdb=m.imdb_rating&&m.imdb_rating!=='N/A'?h(String(m.imdb_rating).replace('.',',')):'—';
  const meta=m.metascore&&m.metascore!=='N/A'?h(m.metascore):'—';
  const metaNumber=Number(m.metascore);
  const metaColor=meta==='—'?'unknown':metaNumber>=61?'positive':metaNumber>=40?'mixed':'negative';
  return `<div class="poster-shell">
    <div class="poster-fallback"><span class="poster-fallback-icon">🎞</span><span class="poster-fallback-title">${h(m.title)}</span></div>
    ${src?`<img class="poster-img" loading="lazy" src="${h(src)}" alt="Capa de ${h(m.title)}">`:''}
    </div>
    <div class="poster-score-row">
      <span class="score-imdb" title="IMDb: ${imdb}/10" aria-label="IMDb ${imdb} de 10"><span class="score-star" aria-hidden="true">★</span><strong>${imdb}</strong></span>
      <span class="score-meta ${metaColor}" title="Metascore da crítica: ${meta}/100" aria-label="Metascore ${meta} de 100"><strong>${meta}</strong></span>
    </div>`;
}

function movieCard(m){
  return `<div class="movie-card" data-id="${m.id}" draggable="${state.sort==='manual'&&state.view==='tiers'&&!state.term}">
    <button class="poster-button" type="button" data-open="${m.id}" title="Abrir ${h(m.title)}">
      ${posterMarkup(m)}<span class="movie-title">${h(m.title)}</span><span class="movie-year">${m.content_type==='series'?'<b class="series-tag">SÉRIE</b> · ':''}${h(m.year||'Ano não informado')}</span>
    </button></div>`;
}
function rankingRow(m,position){
  const src=posterUrl(m.poster_url);
  const imdb=m.imdb_rating&&m.imdb_rating!=='N/A'?h(String(m.imdb_rating).replace('.',',')):'—';
  const meta=m.metascore&&m.metascore!=='N/A'?h(m.metascore):'—';
  const criticsValue=Number(m.metascore);
  const criticColor=meta==='—'?'unknown':criticsValue>=61?'positive':criticsValue>=40?'mixed':'negative';
  const top=position!==null&&position<=3;
  const score=m.top3_position?'11':m.personal_rating===null?'—':String(m.personal_rating);
  const title=position===null?'Ainda sem nota':`${position}º lugar`;
  const medal=m.top3_position?['🥇','🥈','🥉'][Number(m.top3_position)-1]:'';
  const podiumLabel=m.top3_position?`TOP ${m.top3_position}`:'';
  return `<article class="rank-entry ${top?'rank-top':''}" style="--score-color:${COLORS[m.personal_rating]||'#8f8f9e'}">
    <button type="button" class="rank-open" data-open="${m.id}" title="${h(title)}: ${h(m.title)} — abrir ficha">
      <span class="rank-position ${top?'rank-podium':''}" aria-label="${h(title)}">${position===null?'—':String(position)}<small>${position===null?'SEM NOTA':'º'}</small></span>
      <span class="rank-cover">
        <span class="rank-cover-fallback">🎞</span>
        ${src?`<img class="rank-cover-img" loading="lazy" src="${h(src)}" alt="Capa de ${h(m.title)}">`:''}
      </span>
      <span class="rank-info">
        <strong class="rank-title">${m.top3_position?`<span class="rank-crown medal-${m.top3_position}">${medal} ${podiumLabel}</span> `:''}${h(m.title)}</strong>
        <span class="rank-year">${m.content_type==='series'?'SÉRIE · ':''}${h(m.year||'Ano não informado')}</span>
        <span class="rank-external">
          <span class="rank-imdb" aria-label="IMDb ${imdb} de 10"><span aria-hidden="true">★</span> ${imdb}</span>
          <span class="rank-meta ${criticColor}" aria-label="Metascore ${meta} de 100">${meta}</span>
          <span class="rank-meta-label">Metascore</span>
        </span>
      </span>
      <span class="rank-personal"><span>${m.top3_position?'NÍVEL ESPECIAL':'NOSSA NOTA'}</span><strong>${score}</strong><small>${m.top3_position?'TOP 3':position===null?'A avaliar':'/10'}</small></span>
      <span class="rank-chevron" aria-hidden="true">›</span>
    </button>
  </article>`;
}
function top3Markup(allVisible){
  // A ordem visual do pódio é prata · ouro · bronze; o ranking real continua 1/2/3.
  const selected=state.movies.filter(m=>m.top3_position).sort((a,b)=>a.top3_position-b.top3_position);
  const allowed=new Set(allVisible.map(m=>m.id));
  const cards=[2,1,3].map(place=>{
    const m=selected.find(item=>Number(item.top3_position)===place);
    const rankName=['','OURO','PRATA','BRONZE'][place];
    const title=m?h(m.title):'Posição disponível';
    const src=m?posterUrl(m.poster_url):'';
    const poster=m && src?`<img src="${h(src)}" loading="lazy" alt="Capa de ${title}">`:m?`<span class="podium-poster-fallback">${title}</span>`:'<span class="podium-placeholder">＋</span>';
    return `<div class="podium-item podium-place-${place} ${m&&!allowed.has(m.id)?'top3-muted':''} ${m?'':'podium-vacant'}">
      <div class="podium-card">
        <div class="podium-label"><span class="podium-medal" aria-hidden="true">${['','🥇','🥈','🥉'][place]}</span><span>${place}º LUGAR</span></div>
        ${m?`<button type="button" class="podium-poster" data-open="${m.id}" title="Abrir ${title}">${poster}</button>`:
        `<div class="podium-poster" aria-label="Posição disponível">${poster}</div>`}
        <div class="podium-info"><strong>${title}</strong><small>${m?h(m.year||''):'Escolha um filme no catálogo'}</small></div>
        ${m?`<div class="podium-controls">
          <button type="button" data-top3-action="up" data-top3-id="${m.id}" ${place===1?'disabled':''} aria-label="Subir ${title} no pódio" title="Subir">↑</button>
          <button type="button" data-top3-action="down" data-top3-id="${m.id}" ${place===3?'disabled':''} aria-label="Descer ${title} no pódio" title="Descer">↓</button>
          <button type="button" data-top3-action="remove" data-top3-id="${m.id}" aria-label="Retirar ${title} do Top 3" title="Retirar do Top 3">×</button>
        </div>`:'<div class="podium-controls podium-controls-empty">—</div>'}
      </div>
      <div class="podium-base"><strong>${place}</strong><span>${rankName}</span></div>
    </div>`;
  }).join('');
  return `<section class="podium-section" aria-label="Pódio Top 3 do CineDuo">
    <div class="podium-heading"><div><span class="eyebrow minor">DESTAQUES</span><h3>Top 3 <span>· Pódio</span></h3></div><span class="podium-count">${selected.length} / 3 selecionados</span></div>
    <div class="podium-grid">${cards}</div>
  </section>`;
}
function artistsRanking(){
  const groups=new Map();
  for(const m of state.movies){
    if(!state.actorsIncludeSeries && m.content_type==='series') continue;
    const already=new Set();
    // Após validação TMDb, SOMENTE cast de atuação; nunca misturar
    // Cinemeta/Wikidata/OMDb antigos com os créditos verificados.
    const verified=m.cast_status==='verified'&&Array.isArray(m.verified_actors);
    const candidateNames=verified?m.verified_actors:(state.settings.has_tmdb_key?[]:String(m.actors||'').split(','));
    const list=[...candidateNames,...(Array.isArray(m.manual_actors)?m.manual_actors:[])];
    for(const person of list){
      const raw=person.trim(), name=['zendaya coleman','zendaya maree stoermer coleman'].includes(norm(raw))?'Zendaya':raw, key=norm(name);
      if(!name || ['n/a','na','unknown'].includes(key)|| already.has(key))continue;
      already.add(key);
      if(!groups.has(key))groups.set(key,{name,appearances:0,titles:[]});
      const group=groups.get(key); group.appearances++;group.titles.push(m);
    }
  }
  const sorted=[...groups.values()].sort((a,b)=>b.appearances-a.appearances||a.name.localeCompare(b.name,'pt-BR'));let last=0;return sorted.map((p,i)=>{if(i===0||p.appearances!==sorted[i-1].appearances)last=i+1;return {...p,rank:last}});
}
function artistMarkup(){
  const q=norm(state.term);
  const allActors=artistsRanking();
  const matching=q?allActors.filter(a=>norm(a.name).includes(q)||a.titles.some(m=>norm(m.title).includes(q))):allActors;
  const actors=q?matching:matching.slice(0,100);
  if(!actors.length) return '<div class="empty-search">Nenhum artista encontrado nesta pesquisa. Confira o nome ou complete os elencos pela TMDb.</div>';
  const verifiedCount=state.movies.filter(m=>m.cast_status==='verified').length;
  const limitMessage=q?`${actors.length} resultado(s) encontrados em todo o ranking.`:`Exibindo os ${actors.length} primeiros de ${allActors.length} artistas. Use a busca para localizar qualquer outro nome, mesmo fora dos 100 primeiros.`;
  return `<div class="actor-summary"><strong>${h(limitMessage)}</strong> ${state.actorsIncludeSeries?'Incluindo séries.':'Somente filmes.'} <strong>${verifiedCount} de ${state.movies.length} títulos</strong> com elenco validado pela TMDb. Contagem por títulos assistidos, não por episódios.</div>`+
  actors.map(a=>`<article class="actor-entry">
    <div class="actor-rank">${a.rank}<small>º</small></div>
    <div class="actor-avatar" data-photo-name="${h(a.name)}" title="Foto de ${h(a.name)}"><span>${h(a.name.split(/\s+/).slice(0,2).map(x=>x[0]||'').join('').toUpperCase())}</span></div>
    <div class="actor-data"><h3>${h(a.name)}</h3><span>${a.appearances} ${a.appearances===1?'participação':'participações'}</span><div class="actor-actions"><button class="actor-add-action" type="button" data-artist-manual="${h(a.name)}">＋ Corrigir participação</button><button class="actor-photo-action" type="button" data-artist-photo="${h(a.name)}">📷 Editar foto</button></div></div>
    <div class="actor-movies">${a.titles.map(m=>{
      const poster=posterUrl(m.poster_url);
      return `<button type="button" data-open="${m.id}" class="actor-film" title="Abrir ${h(m.title)}">
        <span class="actor-thumb">${poster?`<img loading="lazy" src="${h(poster)}" alt="">`:'🎞'}</span>
        <span>${h(m.title)}<small>${h(m.year||'')}${m.content_type==='series'?' · Série':''}</small></span>
      </button>`;
    }).join('')}</div>
  </article>`).join('');
}
let actorPhotoObserver=null;
let actorPhotoPending=[];
let actorPhotosInFlight=0;
function loadActorPhotos(){
  if(actorPhotoObserver)actorPhotoObserver.disconnect();
  actorPhotoPending=[];
  const elems=[...document.querySelectorAll('[data-photo-name]')];
  if('IntersectionObserver' in window){
    actorPhotoObserver=new IntersectionObserver(entries=>{
      for(const entry of entries){
        if(!entry.isIntersecting)continue;
        actorPhotoObserver.unobserve(entry.target);
        enqueueActorPhoto(entry.target);
      }
    },{rootMargin:'280px 0px',threshold:0.01});
    elems.forEach(el=>{
      if(state.actorPhotos.has(norm(el.dataset.photoName)))applyActorPhoto(el,state.actorPhotos.get(norm(el.dataset.photoName)));
      else actorPhotoObserver.observe(el);
    });
  }else elems.slice(0,24).forEach(enqueueActorPhoto);
}
function enqueueActorPhoto(el){
  if(!el.isConnected||el.dataset.queued)return;
  const name=el.dataset.photoName;
  if(state.actorPhotos.has(norm(name))){applyActorPhoto(el,state.actorPhotos.get(norm(name)));return}
  el.dataset.queued='1';actorPhotoPending.push(el);pumpActorPhotos();
}
function pumpActorPhotos(){
  while(actorPhotosInFlight<3&&actorPhotoPending.length){
    const el=actorPhotoPending.shift();
    if(!el.isConnected)continue;
    const name=el.dataset.photoName;
    actorPhotosInFlight++;
    api('/api/actor-photo?name='+encodeURIComponent(name))
      .then(result=>{
        const url=result.url&&/^https:\/\/(?:upload\.wikimedia\.org\/|commons\.wikimedia\.org\/wiki\/Special:FilePath\/|image\.tmdb\.org\/t\/p\/w185\/|m\.media-amazon\.com\/)/.test(result.url)?result.url:'';
        state.actorPhotos.set(norm(name),url);
        document.querySelectorAll('[data-photo-name]').forEach(current=>{
          if(norm(current.dataset.photoName)===norm(name))applyActorPhoto(current,url);
        });
      }).catch(()=>state.actorPhotos.set(norm(name),''))
      .finally(()=>{actorPhotosInFlight--;pumpActorPhotos()});
  }
}
function applyActorPhoto(el,url){
  if(!url||!el.isConnected||el.querySelector('img'))return;
  const img=document.createElement('img');img.loading='lazy';img.alt='Foto de '+el.dataset.photoName;
  img.referrerPolicy='no-referrer';img.src=url;
  img.addEventListener('error',()=>img.remove());el.appendChild(img);
}
async function editArtistPhoto(name){
  const current=state.actorPhotos.get(norm(name))||'';
  const entry=prompt(`Foto de ${name}\n\nCole a URL HTTPS da imagem (ou o link da página do arquivo no Wikimedia Commons).\nPara remover, apague o conteúdo e confirme.`,current);
  if(entry===null)return;
  try{
    const result=await api('/api/actor-photo','POST',{name,photo_url:entry.trim()});
    state.actorPhotos.set(norm(name),result.url||'');
    render();
    toast(result.url?'Foto de '+name+' salva!':'Foto removida. A busca automática poderá preencher depois.');
  }catch(e){toast(e.message,'error')}
}

async function enrichAllCast(){
  if(state.enrichingCast){
    state.cancelCast=true;
    $('progress-current').textContent='Interrompendo após o grupo atual...';
    return;
  }
  const candidates=state.movies.filter(m=>/^tt\d{7,10}$/i.test(m.imdb_id||''));
  if(!candidates.length){toast('Cadastre IDs do IMDb para identificar o elenco dos títulos.','error');return}
  if(!confirm(`Validar apenas atores e atrizes em ${candidates.length} título(s)?\n\nA TMDb precisa estar configurada. Créditos de voz, arquivo, música e equipe serão excluídos da contagem. O elenco anterior será preservado como histórico. Nenhuma nota será alterada.`))return;
  state.enrichingCast=true;state.cancelCast=false;
  const btn=$('enrich-actors');btn.textContent='■ Parar atualização';
  const task=progressBegin('Completando elencos e fotos',candidates.length);
  let done=0,added=0,found=0,errors=0,tmdbSuccess=0; const details=[];
  let criticalError=null;
  try{
    for(let i=0;i<candidates.length;i+=3){
      if(state.cancelCast)break;
      const group=candidates.slice(i,i+3);
      progressUpdate(task,done,candidates.length,`Consultando: ${group.map(m=>m.title).join(' · ')}`,
        `${found} elencos validados · ${errors} falhas`);
      const outcomes=await Promise.all(group.map(m=>api('/api/actors/enrich','POST',{id:m.id})
        .catch(e=>({error:e.message,title:m.title}))));
      done+=group.length;
      for(const o of outcomes){
        if(o.error){errors++;if(details.length<6)details.push((o.title||'Título')+': '+o.error)}
        else{
          added+=o.added;found+=o.sources.length?1:0;
          if(o.sources.includes('TMDb'))tmdbSuccess++;
          if(o.note && details.length<6)details.push((o.title||'Título')+': '+o.note);
        }
      }
      progressUpdate(task,done,candidates.length,`Últimos consultados: ${group.map(m=>m.title).join(' · ')}`,
        `${found} elencos validados · ${errors} falhas`);
      const prevScroll=window.scrollY;
      state.actorPhotos.clear();
      state.movies=await api('/api/movies');
      if(state.view==='actors')render();
      window.scrollTo({top:prevScroll,behavior:'instant'});
      await new Promise(resolve=>setTimeout(resolve,60));
    }
    const diagnostics=await api('/api/actors/diagnostics').catch(()=>null);
    const summary=state.cancelCast?'Consulta interrompida.':`${done} títulos consultados · ${tmdbSuccess} elencos validados pela TMDb.`;
    const info=errors?`${errors} falhas. ${details.slice(0,2).join(' | ')}`:
      `Fotos salvas no banco: ${diagnostics?.with_photo??'—'}.`;
    progressFinish(task,summary,info,errors>0||state.cancelCast||!diagnostics?.tmdb_key_configured);
    if(!diagnostics?.tmdb_key_configured)toast('Configure a TMDb em Ajustes para validar os elencos.','error');
    else toast(`Elencos revisados: ${tmdbSuccess} títulos validados.`);
  }catch(err){criticalError=err;progressFinish(task,'A atualização dos elencos falhou.',err.message,true);toast(err.message,'error')}
  finally{state.enrichingCast=false;state.cancelCast=false;btn.textContent='↻ Completar elencos'}
}

async function loadSagas(){
  state.sagaError=null;
  const response=await api('/api/sagas');
  if(!Array.isArray(response.sagas))throw Error('Resposta de sagas inválida. Atualize os quatro arquivos do CineDuo 1.11.');
  state.sagas=response.sagas;
  return state.sagas;
}
async function showSagas(){
  state.view='sagas';state.term='';$('library-search').value='';
  state.sagaLoading=true;state.sagaError=null;
  render();  // A tela muda imediatamente, mesmo se a rede/servidor falhar.
  try{await loadSagas()}
  catch(e){state.sagaError=e.message;toast('Não foi possível abrir sagas: '+e.message,'error')}
  finally{state.sagaLoading=false;render()}
}

function sagaSeenPoster(part){const movie=part.movie;return posterUrl(movie?.poster_url||part.poster)}
function sagaAverageText(value){
  if(value===null||value===undefined||!Number.isFinite(Number(value)))return '—';
  return Number(value).toLocaleString('pt-BR',{minimumFractionDigits:1,maximumFractionDigits:1});
}
function sagaAverageChips(folder,compact=false){
  const values=[
    {cls:'ours',symbol:'♥',label:'Nossa média',value:sagaAverageText(folder.movie_average),count:folder.movie_average_count,denom:'10'},
    {cls:'imdb',symbol:'★',label:'IMDb',value:sagaAverageText(folder.imdb_average),count:folder.imdb_average_count,denom:'10'},
    {cls:'critic',symbol:'▣',label:'Metascore',value:sagaAverageText(folder.metascore_average),count:folder.metascore_average_count,denom:'100'}
  ];
  return `<div class="saga-averages ${compact?'saga-averages-compact':''}">${values.map(v=>`<span class="saga-average saga-average-${v.cls}" title="${h(v.label)} · ${v.count||0} de ${folder.registered} títulos cadastrados com nota">
    <span class="saga-average-label">${v.symbol} ${h(v.label)}</span><strong>${v.value}${v.value==='—'?'':`<small>/${v.denom}</small>`}</strong>
  </span>`).join('')}</div>`;
}
function sagaFolders(){
  const q=norm(state.term);
  const list=state.sagas.filter(x=>!q||norm(x.name).includes(q)||x.parts.some(p=>norm(p.title).includes(q)));
  if(!list.length)return '<div class="empty-search">Nenhuma saga corresponde à busca. Clique em “Descobrir mais sagas” para consultar a TMDb, ou crie uma pasta manualmente.</div>';
  return `<div class="saga-folder-grid">${list.map((f,idx)=>{
    const previews=[...f.parts].filter(p=>p.movie).slice(0,3);
    const remainder=f.parts.filter(p=>!p.movie).slice(0,Math.max(0,3-previews.length));
    const thumbs=[...previews,...remainder].slice(0,3);
    const cards=thumbs.map(part=>{const src=sagaSeenPoster(part);const absent=!part.movie;
      return `<span class="saga-collage-poster ${absent?'saga-inactive':''}">${src?`<img src="${h(src)}" loading="lazy" alt="">`:'<span>🎞</span>'}</span>`}).join('');
    const percentage=f.total?Math.round(f.registered/f.total*100):0;
    return `<button type="button" class="saga-folder ${f.complete?'saga-folder-complete':''}" data-saga-open="${h(f.key)}" aria-label="Abrir saga ${h(f.name)}">
      <div class="saga-folder-preview"><div class="saga-collage">${cards}</div><span class="saga-folder-count">${f.registered}/${f.total}</span>${f.complete?'<span class="saga-complete-emblem">★ SAGA COMPLETA</span>':''}</div>
      <div class="saga-folder-info"><strong>${f.movie_average!==null?`<span class="saga-rank-index">${idx+1}º</span> `:''}${h(f.name)}</strong><span>${f.complete?'✓ Todos os filmes cadastrados':f.missing?`${f.missing} ${f.missing===1?'título ainda não cadastrado':'títulos ainda não cadastrados'}`:'Pasta sem capítulos'}</span></div>
      <div class="saga-meter"><span style="width:${percentage}%"></span></div>
      ${sagaAverageChips(f,true)}
      <div class="saga-folder-footer"><span>▣ ${f.order_basis==='story'?'🕰 Cronologia da história':f.order_basis==='custom'?'🕰 Ordem personalizada':f.source==='manual'?'Criada por vocês':f.source==='tmdb'?'TMDb · ordem ajustável':'Coleção identificada'}</span><span>${f.complete?'★ Completa':'Médias dos cadastrados'}</span></div>
    </button>`}).join('')}</div>`;
}
function sagaDetailsMarkup(saga){
  const rows=saga.parts.map((part,i)=>{
    const seen=!!part.movie;
    const url=sagaSeenPoster(part);
    const storyYear=part.timeline_year&&part.timeline_year!==part.year?` · <span class="saga-story-year">História: ${h(part.timeline_year)}</span>`:'';
    return `<div class="saga-part ${seen?'saga-watched':'saga-pending'}">
       <div class="saga-part-number">${String(i+1).padStart(2,'0')}</div>
       <div class="saga-part-poster">${url?`<img src="${h(url)}" loading="lazy" alt="Capa de ${h(part.title)}">`:'<span>🎞</span>'}${!seen?'<span class="saga-pending-lock">◇</span>':''}</div>
       <div class="saga-part-info"><strong>${h(part.movie?.title||part.title)}</strong><span>${h(part.movie?.year||part.year||'Ano a confirmar')}${storyYear}</span><small>${seen?'✓ Já está no ranking'+(part.movie.personal_rating!==null?' · Nossa nota '+part.movie.personal_rating+'/10':''):'○ Ainda não cadastrado'}</small></div>
       <div class="saga-part-actions"><div class="saga-sort-controls" aria-label="Ordenar os capítulos pela história">
         <button type="button" data-saga-move="up" data-saga-index="${i}" ${i===0?'disabled':''} title="Anterior na cronologia">↑</button>
         <button type="button" data-saga-move="down" data-saga-index="${i}" ${i===saga.parts.length-1?'disabled':''} title="Posterior na cronologia">↓</button>
       </div>
       <button type="button" class="btn ${seen?'ghost':'outline'} saga-part-action" ${seen?`data-open="${part.movie.id}"`:`data-saga-add="${h(saga.key)}" data-saga-index="${i}"`}>${seen?'Abrir ficha':'＋ Adicionar'}</button></div>
    </div>`}).join('');
  const manual=saga.source==='manual'?`<form id="saga-part-form" class="saga-add-form">
      <strong>Adicionar capítulo à pasta</strong><div class="two-col"><label class="field"><span>Título</span><input id="saga-part-title" required placeholder="Título do filme"></label><label class="field"><span>Ano (opcional)</span><input id="saga-part-year" maxlength="4" placeholder="2026"></label></div>
      <label class="field"><span>ID IMDb (opcional)</span><input id="saga-part-id" placeholder="tt1234567"></label><button type="submit" class="btn outline">＋ Adicionar capítulo</button>
    </form>`:'';
  const orderHelp=saga.order_basis==='story'
    ?'Ordem cronológica da história (acontecimentos principais).'
    :saga.order_basis==='custom'?'Ordem da história ajustada por vocês.'
    :saga.order_basis==='release'?'A TMDb informa a data de estreia, não a cronologia da trama. Ajuste a ordem pelos botões ↑ ↓ abaixo.'
    :'Capítulos na ordem da sequência. Use ↑ ↓ para corrigir a cronologia.';
  return `<div class="saga-overview ${saga.complete?'saga-overview-complete':''}">
    <div><div class="saga-progress-numbers"><strong>${saga.registered}</strong> de <strong>${saga.total}</strong> no ranking ${saga.complete?'<span class="saga-detail-complete">★ Completa</span>':''}</div>
    <p><strong>🕰 Ordem dos capítulos:</strong> ${h(orderHelp)} As médias usam apenas filmes cadastrados e com nota. Os escurecidos ainda não foram adicionados.</p></div>
    ${sagaAverageChips(saga)}
  </div><div class="saga-parts-list">${rows||'<p class="note-info">Pasta vazia. Adicione o primeiro filme abaixo.</p>'}</div>${manual}`;
}
async function openSaga(key){
  const saga=state.sagas.find(s=>s.key===key);if(!saga)return toast('Atualize a lista de sagas.','error');
  state.selectedSaga=key;$('saga-modal-title').textContent=saga.name;
  $('saga-modal-content').innerHTML=sagaDetailsMarkup(saga);
  openModal('saga');
}
async function moveSagaPart(index,action){
  if(!state.selectedSaga)return;
  const key=state.selectedSaga;
  try{
    await api('/api/sagas/reorder','POST',{key,index,action});
    await loadSagas();render();openSaga(key);
    toast('Ordem da saga atualizada.');
  }catch(e){toast('Não foi possível reordenar: '+e.message,'error')}
}

async function scanSagas(){
  if(state.sagaBusy){
    state.sagaCancel=true;
    $('progress-current').textContent='Interrompendo após o grupo atual...';
    return;
  }
  state.sagaBusy=true;state.sagaCancel=false;
  const btn=$('scan-sagas');btn.textContent='■ Parar pesquisa';
  const task=progressBegin('Descobrindo sagas e continuações',state.movies.length);
  let processed=0,total=state.movies.length,found=0,errors=0;
  try{
    for(let offset=0;offset<200;offset+=6){
      if(state.sagaCancel)break;
      const next=state.movies.slice(offset,offset+6).map(m=>m.title).join(' · ');
      progressUpdate(task,processed,total,`Consultando: ${next||'Coleções da TMDb'}`);
      const result=await api('/api/sagas/scan','POST',{offset,limit:6});
      total=result.total;processed+=result.attempted;found+=result.collections;errors+=result.errors.length;
      await loadSagas();render();
      progressUpdate(task,processed,total,`Último grupo consultado: ${next||'Coleções'}`,
        `${found} coleções encontradas · ${errors} falhas`);
      if(processed>=total||result.attempted===0)break;
    }
    const stopped=state.sagaCancel;
    progressFinish(task,stopped?'Pesquisa interrompida. Pastas encontradas foram salvas.':`${found} coleções identificadas.`,
      `${processed} de ${total} títulos consultados${errors?' · '+errors+' falhas':''}.`,stopped||errors>0);
    toast(stopped?'Pesquisa interrompida.':'Pesquisa de sagas concluída.');
  }catch(e){progressFinish(task,'Não foi possível descobrir novas sagas.',e.message,true);toast(e.message,'error')}
  finally{state.sagaBusy=false;state.sagaCancel=false;btn.textContent='↻ Descobrir mais sagas'}
}
async function createSaga(){
  const name=prompt('Qual o nome da nova saga ou trilogia?');if(!name||!name.trim())return;
  try{const folder=await api('/api/sagas','POST',{name:name.trim()});await loadSagas();render();openSaga(folder.key);
      toast('Pasta criada! Adicione os capítulos.')}catch(e){toast(e.message,'error')}
}
async function addSagaPart(e){e.preventDefault();const key=state.selectedSaga;if(!key)return;
  try{await api('/api/sagas/part','POST',{key,title:val('saga-part-title'),year:val('saga-part-year'),imdb_id:val('saga-part-id')});
    await loadSagas();render();openSaga(key);toast('Capítulo incluído na pasta!');}catch(err){toast(err.message,'error')}
}
async function addMissingSagaFilm(key,index){
  const folder=state.sagas.find(s=>s.key===key);const part=folder?.parts?.[index];if(!part)return;
  openAdd();
  if(state.settings.has_key){
    toggleAddTab('search');$('search-type').value='movie';$('omdb-search').value=part.imdb_id||part.title;
    searchOMDb();
  }else{
    toggleAddTab('manual');$('manual-title').value=part.title;$('manual-year').value=part.year||'';
    $('manual-imdb').value=part.imdb_id||'';
  }
}
async function saveArtistManual(e){e.preventDefault();
  try{const name=val('actor-manual-name');const id=Number($('actor-manual-movie').value);
    await api('/api/actors/manual','POST',{name,movie_id:id,photo_url:val('actor-manual-photo')});
    state.actorPhotos.delete(norm(name));$('actor-manual-photo').value='';await reload();closeModal();toast('Participação incluída. O ranking foi recalculado!');
  }catch(err){toast(err.message,'error')}
}
function actorMovieSelect(){
  const sel=$('actor-manual-movie');const previous=sel.value;
  sel.innerHTML='<option value="">Selecione um título...</option>'+state.movies.map(m=>`<option value="${m.id}">${h(m.title)} (${h(m.year||'')})</option>`).join('');
  if([...sel.options].some(o=>o.value===previous))sel.value=previous;
}

function render(){
  const all=state.movies;
  const scored=all.filter(m=>m.personal_rating!==null);
  const average=scored.length?scored.reduce((sum,m)=>sum+(m.top3_position?11:m.personal_rating),0)/scored.length:0;
  const filmCount=all.filter(m=>m.content_type!=='series').length;
  const seriesCount=all.length-filmCount;
  $('stat-total').textContent=all.length;
  $('stat-total-label').textContent=`${filmCount} ${filmCount===1?'filme':'filmes'} · ${seriesCount} ${seriesCount===1?'série':'séries'}`;
  $('stat-avg').textContent=scored.length?average.toFixed(1).replace('.',','):'—';
  $('stat-ten').textContent=all.filter(m=>m.personal_rating===10&&!m.top3_position).length;
  const shown=filteredMovies();
  $('current-count').textContent=`(${shown.length})`;
  $('tiers-view').classList.toggle('active',state.view==='tiers');
  $('grid-view').classList.toggle('active',state.view==='grid');
  $('actors-view').classList.toggle('active',state.view==='actors');
  $('sagas-view').classList.toggle('active',state.view==='sagas');
  $('sort-select').classList.toggle('hidden',state.view!=='tiers');
  $('refresh-all').classList.toggle('hidden',state.view==='actors'||state.view==='sagas');
  $('saga-head-actions').classList.toggle('hidden',state.view!=='sagas');
  $('enrich-actors').classList.toggle('hidden',state.view!=='actors');
  $('actors-options').classList.toggle('hidden',state.view!=='actors');
  $('actors-source-status').textContent=state.settings.has_tmdb_key?'TMDb configurada · valide os elencos para excluir dubladores e equipe':'TMDb não configurada · os créditos antigos ainda não foram validados';
  $('sagas-options').classList.toggle('hidden',state.view!=='sagas');
  $('tiers-container').classList.toggle('hidden',state.view!=='tiers');
  $('grid-container').classList.toggle('hidden',state.view!=='grid');
  $('artists-container').classList.toggle('hidden',state.view!=='actors');
  $('sagas-container').classList.toggle('hidden',state.view!=='sagas');
  $('library-search').placeholder=state.view==='actors'?'Buscar artista ou obra assistida...':state.view==='sagas'?'Buscar saga ou capítulo...':'Buscar filme ou série no nosso ranking...';
  if(state.view==='sagas'){
    $('current-count').textContent=`(${state.sagas.length} pastas)`;
    $('sagas-container').innerHTML=state.sagaLoading
      ?'<div class="saga-loading" role="status">⏳ Buscando as pastas de sagas...</div>'
      :state.sagaError
      ?`<div class="saga-error" role="alert"><strong>Não foi possível carregar as sagas.</strong><p>${h(state.sagaError)}</p><button type="button" class="btn primary" id="retry-sagas">Tentar novamente</button><small>Se continuar, substitua os quatro arquivos juntos e pressione Ctrl+F5.</small></div>`
      :sagaFolders();
  }else if(state.view==='actors'){
    actorMovieSelect();
    $('artists-container').innerHTML=artistMarkup();
    loadActorPhotos();
  }else if(!shown.length){
    const txt=state.movies.length
      ?'<div class="empty-search">Nenhum título corresponde à busca. Tente outro termo.</div>'
      :'<div class="empty-search empty-catalog"><span class="empty-catalog-icon">▤</span><h3>Seu catálogo está vazio</h3><p>Adicione um filme ou série pela pesquisa do IMDb ou importe um backup do CineDuo.</p><div class="empty-catalog-actions"><button type="button" class="btn primary" data-empty-add>＋ Adicionar primeiro título</button><button type="button" class="btn ghost" data-empty-import>Importar backup</button></div></div>';
    $('tiers-container').innerHTML=(state.movies.length?'':top3Markup([]))+txt;
    $('grid-container').innerHTML=txt;
  }else if(state.view==='grid'){
    // O Top 3 ocupa os primeiros lugares; os demais seguem por nota pessoal.
    const ranking=[...state.movies].sort((a,b)=>{
      const ta=Number(a.top3_position)||999, tb=Number(b.top3_position)||999;
      if(ta!==tb)return ta-tb;
      const sa=a.personal_rating===null?-1:Number(a.personal_rating);
      const sb=b.personal_rating===null?-1:Number(b.personal_rating);
      return sb-sa || (a.sort_order??0)-(b.sort_order??0) || a.id-b.id;
    });
    const ranks=new Map(ranking.map((m,i)=>[m.id,i+1]));
    const visible=new Set(shown.map(m=>m.id));
    $('grid-container').innerHTML=ranking.filter(m=>visible.has(m.id))
      .map(m=>rankingRow(m,ranks.get(m.id))).join('');
  }else{
    const ranks=[10,9,8,7,6,5,4,3,2,1,0,null];
    $('tiers-container').innerHTML=top3Markup(shown)+ranks.map(s=>{
      // TOP 3 é uma categoria própria, acima da nota 10: não duplica na faixa.
      const movies=shown.filter(m=>m.personal_rating===s&&!m.top3_position);
      if(!movies.length&&s!==null&&s<7)return '';
      if(s===null&&!movies.length)return '';
      const color= s===null?'#7a7d88':COLORS[s];
      const darkInk=s!==null&&s>=5;
      const label=s===null?'—':s;
      const tierName=s===null?'A AVALIAR':TITLES[s];
      const unit=movies.length===1?'título':'títulos';
      return `<section class="tier-row ${!movies.length?'empty':''}" style="--tier:${color};--tier-ink:${darkInk?'#15171e':'#fff'}" data-score="${s===null?'':s}">
        <div class="tier-label"><span class="tier-number">${label}</span><small>${h(tierName)}</small><span class="tier-total">${movies.length} ${unit}</span></div>
        <div class="tier-zone" data-score="${s===null?'':s}">${movies.map(m=>movieCard(m)).join('')||
        `<button class="empty-note" data-addscore="${s===null?'':s}" type="button" style="background:none;border:0;text-align:left">＋ Adicionar título nesta nota</button>`}</div></section>`;
    }).join('');
    bindDrag();
  }
  document.querySelectorAll('.poster-img,.rank-cover-img,.top3-cover img,.actor-thumb img').forEach(img=>img.addEventListener('error',()=>img.remove()));
}

function bindDrag(){
  document.querySelectorAll('.movie-card[draggable="true"]').forEach(card=>{
    card.addEventListener('dragstart',e=>{e.dataTransfer.effectAllowed='move';e.dataTransfer.setData('text/plain',card.dataset.id);card.classList.add('dragging')});
    card.addEventListener('dragend',()=>{card.classList.remove('dragging');document.querySelectorAll('.drop-before,.tier-over').forEach(el=>el.classList.remove('drop-before','tier-over'))});
    card.addEventListener('dragover',e=>{e.preventDefault();e.stopPropagation();card.classList.add('drop-before');e.dataTransfer.dropEffect='move'});
    card.addEventListener('dragleave',()=>card.classList.remove('drop-before'));
    card.addEventListener('drop',async e=>{
      e.preventDefault();e.stopPropagation();card.classList.remove('drop-before');
      const id=Number(e.dataTransfer.getData('text/plain'));
      if(id===Number(card.dataset.id))return;
      await move(id,card.closest('.tier-zone').dataset.score,Number(card.dataset.id));
    });
  });
  document.querySelectorAll('.tier-zone').forEach(zone=>{
    zone.addEventListener('dragover',e=>{e.preventDefault();zone.closest('.tier-row').classList.add('tier-over')});
    zone.addEventListener('dragleave',e=>{if(!zone.contains(e.relatedTarget))zone.closest('.tier-row').classList.remove('tier-over')});
    zone.addEventListener('drop',async e=>{
      e.preventDefault();zone.closest('.tier-row').classList.remove('tier-over');
      const id=Number(e.dataTransfer.getData('text/plain'));if(id)await move(id,zone.dataset.score,null);
    });
  });
}
async function move(id,score,before){
  try{await api('/api/move','POST',{id,personal_rating:score===''?null:Number(score),before_id:before});
      await reload();toast('Filme reposicionado!')}
  catch(e){toast(e.message,'error')}
}
async function reload(){state.movies=await api('/api/movies');if(state.view==='sagas')await loadSagas();render()}
async function changeTop3(id,action){
  try{
    await api('/api/top3','POST',{id,action});await reload();
    if(state.activeId===id)openDetail(id);
    toast(action==='add'?'Filme colocado no Top 3!':action==='remove'?'Filme removido do Top 3.':'Top 3 reorganizado.');
  }catch(e){toast(e.message,'error')}
}

function openModal(name){
  $('modal-backdrop').classList.remove('hidden');$('modal-backdrop').setAttribute('aria-hidden','false');
  ['add','detail','settings','saga','artist'].forEach(n=>{ $('modal-'+n).classList.toggle('hidden',n!==name) });
  document.body.style.overflow='hidden';
}
function closeModal(){
  $('modal-backdrop').classList.add('hidden');$('modal-backdrop').setAttribute('aria-hidden','true');
  document.body.style.overflow='';state.activeId=null;
  const player=$('trailer-player');if(player)player.innerHTML='';
}
function toggleAddTab(which){
  $('tab-search').classList.toggle('active',which==='search');
  $('tab-manual').classList.toggle('active',which==='manual');
  $('add-search-panel').classList.toggle('hidden',which!=='search');
  $('manual-form').classList.toggle('hidden',which!=='manual');
}
function openAdd(score=null){
  state.selectedSearch=null;
  $('omdb-search').value='';$('search-results').innerHTML='';$('chosen-preview').classList.add('hidden');
  $('manual-form').reset();$('manual-type').value='movie';$('search-type').value='movie';setScore('manual-score',score);
  $('chosen-preview').dataset.score=score===null?'':String(score);
  toggleAddTab(state.settings.has_key?'search':'manual');
  openModal('add');
  if(!state.settings.has_key){
    $('search-results').innerHTML='<p class="note-info">Para buscar capas e notas automaticamente, configure a chave OMDb em Ajustes.</p>';
  }
}
async function searchOMDb(){
  const q=val('omdb-search'); if(q.length<2)return toast('Digite ao menos 2 letras para buscar.','error');
  const container=$('search-results');container.innerHTML='<p class="note-info">Buscando título na OMDb...</p>';
  $('chosen-preview').classList.add('hidden');
  try{
    const data=await api('/api/search?q='+encodeURIComponent(q)+'&type='+encodeURIComponent($('search-type').value));
    const results=data.Search||[];
    container.innerHTML=results.length?results.map(r=>{
      const src=posterUrl(r.Poster);return `<button class="search-result" data-choose="${h(r.imdbID)}" type="button">
        ${src?`<img src="${h(src)}" alt="">`:'<span class="search-result-placeholder">🎬</span>'}
        <span><strong>${h(r.Title)}</strong><small>${h(r.Year)} · ${h(r.Type||'Filme')} · IMDb ${h(r.imdbID)}</small></span></button>`;
    }).join(''):'<p class="note-info">Nenhum filme encontrado. Tente o título original ou cadastre manualmente.</p>';
    state.searchResults=results;
    // Ao encontrar um ID exato, abra diretamente a ficha de cadastro.
    if(data.searchMode==='imdb_id'&&results.length===1)chooseResult(results[0].imdbID);
  }catch(e){
    const usedId=/tt\d{7,10}/i.test(q);
    const message=usedId&&/não encontrado|not found/i.test(e.message)
      ? 'Esse código existe no IMDb, mas ainda pode não estar disponível na OMDb. Você pode cadastrar pela aba Inserir manualmente. Detalhe: '+e.message
      :e.message;
    container.innerHTML=`<p class="note-info">${h(message)}</p>`;
    toast(message,'error');
  }
}
async function chooseResult(id){
  const candidate=(state.searchResults||[]).find(r=>r.imdbID===id);
  if(!candidate)return;
  state.selectedSearch=candidate;
  const src=posterUrl(candidate.Poster);
  const score=$('chosen-preview').dataset.score;
  $('chosen-preview').innerHTML=`<div class="chosen-preview-head">
    ${src?`<img src="${h(src)}" alt="Capa">`:'<div class="search-result-placeholder">🎬</div>'}
    <div><h3>${h(candidate.Title)}</h3><p>${h(candidate.Year)} · IMDb ${h(candidate.imdbID)}</p></div></div>
    <div class="two-col"><div class="field"><label for="add-score">Nossa nota</label><select id="add-score" class="select"></select></div>
    <div class="field"><label for="add-date">Quando vimos</label><input id="add-date" type="date"></div></div>
    <div class="field"><label for="add-notes">Nossa opinião (opcional)</label><textarea id="add-notes" rows="2" placeholder="O que achamos?"></textarea></div>
    <button class="btn primary" type="button" id="save-omdb">＋ Salvar na nossa coleção</button>`;
  setScore('add-score',score===''?null:Number(score));
  $('chosen-preview').classList.remove('hidden');
  $('chosen-preview').scrollIntoView({behavior:'smooth',block:'nearest'});
}
async function addFromOMDb(){
  if(!state.selectedSearch)return;
  const btn=$('save-omdb');btn.disabled=true;btn.textContent='Adicionando...';
  try{
    await api('/api/movies','POST',{imdb_id:state.selectedSearch.imdbID,lookup:true,
        personal_rating:scoreFrom('add-score'),watched_on:val('add-date')||null,notes:val('add-notes'),
        content_type:state.selectedSearch.Type==='series'?'series':'movie'});
    await reload();closeModal();toast('Título adicionado ao ranking! 🍿');
  }catch(e){toast(e.message,'error')}
  finally{btn.disabled=false;btn.textContent='＋ Salvar na nossa coleção'}
}
async function addManual(e){
  e.preventDefault();
  try{
    const m=await api('/api/movies','POST',{title:val('manual-title'),year:val('manual-year')||null,
      imdb_id:val('manual-imdb')||null,poster:val('manual-poster')||null,plot:val('manual-plot')||null,
      trailer_url:val('manual-trailer')||null,content_type:val('manual-type'),actors:val('manual-actors')||null,
      personal_rating:scoreFrom('manual-score'),notes:val('manual-notes')});
    await reload();closeModal();toast('Título adicionado!');
    if(state.settings.has_key&&m.imdb_id){try{await api('/api/movies/'+m.id+'/sync','POST');await reload()}catch{}}
  }catch(err){toast(err.message,'error')}
}
function trailerMarkup(m){
  const saved=String(m.trailer_url||'');
  const match=saved.match(/^https:\/\/www\.youtube\.com\/watch\?v=([A-Za-z0-9_-]{11})$/);
  const id=match?match[1]:'';
  // A OMDb fornece o pôster e avaliações, mas não garante URLs dos trailers.
  const q=[m.original_title||m.title,m.year,'official trailer'].filter(Boolean).join(' ');
  const searchLink='https://www.youtube.com/results?search_query='+encodeURIComponent(q);
  if(id){
    return `<div class="trailer-head"><span class="trailer-title">TRAILER DO FILME</span><span class="trailer-help">Assista sem sair do CineDuo</span></div>
    <div class="trailer-actions"><button type="button" class="btn trailer-play" data-play-trailer="${h(id)}">▶ Assistir ao trailer</button>
    <a class="trailer-search" href="${h(saved)}" target="_blank" rel="noopener noreferrer">Abrir no YouTube ↗</a></div>
    <div id="trailer-player" class="trailer-player" aria-live="polite"></div>`;
  }
  return `<div class="trailer-head"><span class="trailer-title">TRAILER DO FILME</span><span class="trailer-help">Encontre o vídeo oficial</span></div>
  <div class="trailer-actions"><a class="btn trailer-play" href="${h(searchLink)}" target="_blank" rel="noopener noreferrer">▶ Ver trailer no YouTube ↗</a>
  <span class="trailer-note">Para assistir aqui, cole o link em “Editar informações do filme manualmente”.</span></div>
  <div id="trailer-player" class="trailer-player"></div>`;
}
function toggleTrailer(){
  const btn=document.querySelector('[data-play-trailer]');
  const player=$('trailer-player');
  if(!btn||!player)return;
  if(player.querySelector('iframe')){
    player.replaceChildren();btn.textContent='▶ Assistir ao trailer';return;
  }
  const id=btn.dataset.playTrailer;
  if(!/^[A-Za-z0-9_-]{11}$/.test(id))return;
  const iframe=document.createElement('iframe');
  iframe.src=`https://www.youtube-nocookie.com/embed/${id}?rel=0&autoplay=1`;
  iframe.title='Trailer do filme — YouTube';
  iframe.referrerPolicy='strict-origin-when-cross-origin';
  iframe.setAttribute('allow','accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share');
  iframe.setAttribute('allowfullscreen','');
  player.replaceChildren(iframe);
  btn.textContent='■ Fechar trailer';
  player.scrollIntoView({block:'nearest',behavior:'smooth'});
}
function detailsMarkup(m){
  const src=posterUrl(m.poster_url);
  const imdb=m.imdb_rating&&m.imdb_rating!=='N/A'?`<span class="rating-badge"><b>★ IMDb</b> ${h(m.imdb_rating)}/10</span>`:'';
  const critics=m.metascore&&m.metascore!=='N/A'?`<span class="rating-badge critics"><b>● Crítica</b> ${h(m.metascore)}/100</span>`:'';
  const rotten=m.rotten_tomatoes?`<span class="rating-badge rotten"><b>● Rotten Tomatoes</b> ${h(m.rotten_tomatoes)}</span>`:'';
  const facts=[m.content_type==='series'?'Série':'Filme',m.year,m.runtime,m.genre].filter(Boolean).map(h).join(' · ');
  const imdbLink=/^tt\d{7,10}$/.test(m.imdb_id||'')?`<a class="imdb-link" href="https://www.imdb.com/title/${h(m.imdb_id)}/" target="_blank" rel="noopener noreferrer">Ver ficha no IMDb ↗</a>`:'';
  return `<div class="detail-poster">${src?`<img src="${h(src)}" alt="Capa de ${h(m.title)}">`:'<span style="font-size:46px">🎞</span>'}</div>
    <div class="detail-info"><h3>${h(m.title)}</h3><div class="detail-facts">${facts||'Informações não disponíveis'}</div>
    <div class="rating-badges">${imdb||'<span class="rating-badge">IMDb: —</span>'}${critics||'<span class="rating-badge critics">Crítica: —</span>'}${rotten}</div>
    <div class="detail-plot">${h(m.plot||'Sinopse não cadastrada. Atualize o filme para tentar buscar automaticamente.')}</div>
    ${m.director?`<div class="more-info"><b>Direção:</b> ${h(m.director)}</div>`:''}
    ${m.actors?`<div class="more-info"><b>Elenco:</b> ${h(m.actors)}</div>`:''}
    ${imdbLink}</div>`;
}
function openDetail(id){
  const m=state.movies.find(m=>m.id===Number(id));if(!m)return;
  state.activeId=m.id;$('detail-title').textContent=m.content_type==='series'?'Detalhes da série':'Detalhes do filme';
  $('detail-hero').innerHTML=detailsMarkup(m);
  $('trailer-section').innerHTML=trailerMarkup(m);
  setScore('edit-score',m.personal_rating);
  $('edit-date').value=m.watched_on||'';
  $('edit-notes').value=m.notes||'';
  $('edit-type').value=m.content_type||'movie';
  $('detail-top3').classList.toggle('hidden',m.content_type==='series');
  $('detail-top3').textContent=m.top3_position?'★ Remover do Top 3':'☆ Adicionar ao Top 3';
  $('sync-imdb-id').value=m.imdb_id||'';
  $('sync-feedback').textContent=m.imdb_id?'ID atual: '+m.imdb_id:'Sem identificação IMDb. Cole o ID correto acima.';
  ['title','year','imdb-id','imdb-rating','metascore','rotten','poster','plot','trailer','actors'].forEach((key,i)=>{
    const props=['title','year','imdb_id','imdb_rating','metascore','rotten_tomatoes','poster','plot','trailer_url','actors'];
    $('edit-'+key).value=m[props[i]]||'';
  });
  document.querySelector('.edit-metadata').open=false;
  openModal('detail');
}
async function saveDetail(e){
  e.preventDefault();if(state.activeId===null)return;
  const id=state.activeId;
  const changes={personal_rating:scoreFrom('edit-score'),watched_on:val('edit-date')||null,
    notes:val('edit-notes'),title:val('edit-title'),
    year:val('edit-year')||null,imdb_id:val('sync-imdb-id')||null,imdb_rating:val('edit-imdb-rating')||null,
    metascore:val('edit-metascore')||null,rotten_tomatoes:val('edit-rotten')||null,
    poster:val('edit-poster')||null,plot:val('edit-plot')||null,
    trailer_url:val('edit-trailer')||null,content_type:val('edit-type'),actors:val('edit-actors')||null};
  const original=state.movies.find(m=>m.id===id);
  const modified=Object.fromEntries(Object.entries(changes).filter(([k,v])=>{
    return String(v??'')!==String(original[k]??'');
  }));
  if(!Object.keys(modified).length){closeModal();return toast('Nenhuma alteração necessária.');}
  try{
    // Se o ID mudou, busca automaticamente ficha nova. Não reenvia capa/notas
    // antigas do formulário, que contaminariam os dados recebidos da OMDb.
    if(modified.imdb_id){
      if(modified.content_type){await api('/api/movies/'+id,'PATCH',{content_type:modified.content_type});}
      await api('/api/movies/'+id+'/sync','POST',{imdb_id:modified.imdb_id});
      const personalKeys=['personal_rating','watched_on','notes','title','trailer_url'];
      const personal=Object.fromEntries(Object.entries(modified).filter(([k])=>personalKeys.includes(k)));
      if(Object.keys(personal).length)await api('/api/movies/'+id,'PATCH',personal);
      toast('ID corrigido! Capa e notas consultadas automaticamente.');
    }else{
      await api('/api/movies/'+id,'PATCH',modified);
      toast('Alterações salvas.');
    }
    await reload();closeModal();
  }catch(e){toast(e.message,'error')}
}
async function syncOne(){
  if(state.activeId===null)return;
  const btn=$('sync-one');btn.disabled=true;btn.textContent='Buscando...';
  const feedback=$('sync-feedback');feedback.textContent='Consultando a OMDb pelo ID informado...';
  try{
    const desired=val('sync-imdb-id');
    const payload=desired?{imdb_id:desired}:{};
    const updated=await api(`/api/movies/${state.activeId}/sync`,'POST',payload);
    await reload();openDetail(updated.id);
    const missing=updated._sync?.missing||[];
    const msg=missing.length
      ?`Filme identificado. A OMDb ainda não disponibilizou ${missing.join(' e ')}; os demais dados foram atualizados.`
      :'Filme identificado e avaliações atualizadas!';
    $('sync-feedback').textContent=msg;toast(msg);
  }catch(e){feedback.textContent='⚠ '+e.message;toast(e.message,'error')}
  finally{btn.disabled=false;btn.textContent='↻ Atualizar filme'}
}

async function deleteOne(){
  if(state.activeId===null)return;
  const m=state.movies.find(m=>m.id===state.activeId);
  if(!confirm(`Excluir "${m?.title||'este filme'}" do ranking? Essa ação não pode ser desfeita.`))return;
  try{await api(`/api/movies/${state.activeId}`,'DELETE');await reload();closeModal();toast('Filme excluído.')}
  catch(e){toast(e.message,'error')}
}
function openSettings(){
  $('api-key').value='';
  $('key-status').textContent=state.settings.has_key?'✓ Chave configurada. Digite outra para substituir.':'Nenhuma chave configurada. Você ainda pode usar o ranking manualmente.';
  $('omdb-test-result').textContent='';$('import-result').textContent='';
  $('tmdb-test-result').textContent='';$('tmdb-key').value='';$('tmdb-status').textContent=state.settings.has_tmdb_key?'✓ Chave TMDb configurada.':'Opcional: sem ela, o CineDuo tenta Cinemeta e Wikidata para completar elencos.';
  openModal('settings');
}
async function saveSettings(e){
  e.preventDefault();const key=val('api-key');
  if(!key)return toast('Cole a chave OMDb antes de salvar.','error');
  try{await api('/api/settings','POST',{omdb_key:key});state.settings=await api('/api/settings');
      $('api-key').value='';$('key-status').textContent='✓ Chave salva no computador.';toast('Chave configurada! Agora você pode atualizar as capas.')}
  catch(err){toast(err.message,'error')}
}
async function saveTMDb(e){
  e.preventDefault();
  const key=val('tmdb-key');
  try{await api('/api/tmdb-settings','POST',{tmdb_key:key});
    state.settings=await api('/api/settings');
    $('tmdb-test-result').textContent='';$('tmdb-key').value='';$('tmdb-status').textContent=key?'✓ Chave TMDb salva. Use Completar elencos no ranking de artistas.':'Chave TMDb removida.';
    toast('Configuração do elenco atualizada!');
  }catch(err){toast(err.message,'error')}
}
async function testTMDb(){
  const result=$('tmdb-test-result');
  const btn=$('test-tmdb');
  result.textContent='Testando a conexão TMDb...';btn.disabled=true;
  try{
    const response=await api('/api/test-tmdb');
    result.textContent='✓ '+response.message;toast('Chave TMDb funcionando!');
  }catch(e){result.textContent='⚠ '+e.message;toast(e.message,'error')}
  finally{btn.disabled=false}
}

async function testOMDb(){
  const result=$('omdb-test-result');const btn=$('test-omdb');
  if(!state.settings.has_key){result.textContent='Salve a chave antes de testar.';return}
  btn.disabled=true;result.textContent='Testando a conexão com a OMDb...';
  try{const resultAPI=await api('/api/test-omdb');result.textContent='✓ '+resultAPI.message;toast('Chave OMDb validada!')}
  catch(err){result.textContent='⚠ '+err.message;toast('Falha na conexão: confira a mensagem nos Ajustes.','error')}
  finally{btn.disabled=false}
}
async function importFile(e){
  const file=e.target.files?.[0];if(!file)return;
  try{
    const content=await file.text();
    let mode='merge';
    if(file.name.toLowerCase().endsWith('.json')){
      let parsed;try{parsed=JSON.parse(content)}catch{throw Error('JSON inválido.')}
      if(parsed?.format==='CineDuo'&&[1,2,3].includes(parsed?.version)){
        if(!confirm('Restaurar backup do CineDuo? Isso substituirá TODO o ranking atual pelo conteúdo do arquivo. Faça um backup do estado atual antes de continuar.'))return;
        mode='replace';
      }
    }
    const outcome=await api('/api/import','POST',{filename:file.name,content,mode});
    await reload();$('import-result').textContent=`✓ ${outcome.inserted} filmes adicionados; ${outcome.skipped} já existentes ou ignorados. ${outcome.problems?.join(' | ')||''}`;
    toast(`${outcome.inserted} filmes importados!`);
  }catch(err){toast(err.message,'error')}
  finally{e.target.value=''}
}
async function syncAll(){
  if(state.syncBusy)return;
  if(!state.settings.has_key){openSettings();return toast('Configure primeiro a chave OMDb.','error')}
  const movies=state.movies;
  if(!movies.length)return toast('Adicione seu primeiro filme antes de atualizar.');
  state.syncBusy=true;$('refresh-all').disabled=true;
  const task=progressBegin('Atualizando capas e notas',movies.length);
  let success=0,fail=0,errors=[],stopped=false,done=0;
  try{
    for(let i=0;i<movies.length;i++){
      const title=movies[i].title;
      progressUpdate(task,done,movies.length,`Atualizando: ${title}`,
        `${success} atualizados · ${fail} falhas`);
      try{await api(`/api/movies/${movies[i].id}/sync`,'POST');success++}
      catch(e){
        fail++;errors.push(`${title}: ${e.message}`);
        const lower=e.message.toLowerCase();
        if(lower.includes('chave')||lower.includes('conectar')||lower.includes('conexão')||
           lower.includes('http ')||lower.includes('limite')||lower.includes('certificado')||
           lower.includes('inesperado')||lower.includes('tempo esgotado')){stopped=true;done++;break}
      }
      done++;
      progressUpdate(task,done,movies.length,`Último consultado: ${title}`,
        `${success} atualizados · ${fail} falhas`);
    }
    await reload();
    const summary=stopped?'Atualização interrompida por erro de comunicação.':`${success} título(s) consultado(s), ${fail} falha(s).`;
    const details=errors.length?errors.slice(0,3).join(' | '):'Notas indisponíveis na OMDb continuam como —.';
    progressFinish(task,summary,details,stopped||fail>0);
    if(fail)toast(`Atenção: ${fail} falha(s). ${errors[0]||''}`,'error');
    else toast(`${success} títulos consultados com sucesso!`);
  }catch(e){progressFinish(task,'Não foi possível concluir a atualização.',e.message,true);toast(e.message,'error')}
  finally{state.syncBusy=false;$('refresh-all').disabled=false}
}
function listeners(){
  document.querySelectorAll('.add-activate').forEach(el=>el.addEventListener('click',()=>openAdd()));
  document.querySelectorAll('.settings-activate').forEach(el=>el.addEventListener('click',openSettings));
  document.querySelectorAll('.modal-close').forEach(el=>el.addEventListener('click',closeModal));
  $('modal-backdrop').addEventListener('click',e=>{if(e.target===$('modal-backdrop'))closeModal()});
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!$('modal-backdrop').classList.contains('hidden'))closeModal()});
  document.addEventListener('click',e=>{
    if(e.target.closest('[data-empty-add]')){openAdd();return}
    if(e.target.closest('[data-empty-import]')){$('import-file').click();return}
    if(e.target.closest('#retry-sagas')){showSagas();return}
    const photoButton=e.target.closest('[data-artist-photo]');
    if(photoButton){editArtistPhoto(photoButton.dataset.artistPhoto);return}
    const sagaMove=e.target.closest('[data-saga-move]');if(sagaMove){moveSagaPart(Number(sagaMove.dataset.sagaIndex),sagaMove.dataset.sagaMove);return}
    const folder=e.target.closest('[data-saga-open]');if(folder){openSaga(folder.dataset.sagaOpen);return}
    const adding=e.target.closest('[data-saga-add]');if(adding){addMissingSagaFilm(adding.dataset.sagaAdd,Number(adding.dataset.sagaIndex));return}
    const actorManual=e.target.closest('[data-artist-manual]');if(actorManual){
      $('actor-manual-name').value=actorManual.dataset.artistManual;
      actorMovieSelect();openModal('artist');$('actor-manual-movie').focus();return}
    const top3=e.target.closest('[data-top3-action]');
    if(top3){changeTop3(Number(top3.dataset.top3Id),top3.dataset.top3Action);return}
    const open=e.target.closest('[data-open]');if(open){openDetail(open.dataset.open);return}
    const add=e.target.closest('[data-addscore]');if(add){openAdd(add.dataset.addscore===''?null:Number(add.dataset.addscore));return}
    const choose=e.target.closest('[data-choose]');if(choose){chooseResult(choose.dataset.choose);return}
    if(e.target.closest('#save-omdb'))addFromOMDb();
  });
  $('library-search').addEventListener('input',e=>{state.term=e.target.value;render()});
  $('sort-select').addEventListener('change',e=>{state.sort=e.target.value;render()});
  $('tiers-view').addEventListener('click',()=>{state.view='tiers';render()});
  $('grid-view').addEventListener('click',()=>{state.view='grid';render()});
  $('actors-view').addEventListener('click',()=>{state.view='actors';render()});
  $('sagas-view').addEventListener('click',showSagas);
  $('scan-sagas').addEventListener('click',scanSagas);
  $('create-saga').addEventListener('click',createSaga);
  $('actor-manual-form').addEventListener('submit',saveArtistManual);
  $('modal-saga').addEventListener('submit',e=>{if(e.target.id==='saga-part-form')addSagaPart(e)});
  $('actors-include-series').addEventListener('change',e=>{state.actorsIncludeSeries=e.target.checked;render()});
  $('enrich-actors').addEventListener('click',enrichAllCast);
  $('detail-top3').addEventListener('click',()=>{if(state.activeId!==null){
    const m=state.movies.find(x=>x.id===state.activeId);
    changeTop3(state.activeId,m?.top3_position?'remove':'add');
  }});
  $('tab-search').addEventListener('click',()=>toggleAddTab('search'));
  $('tab-manual').addEventListener('click',()=>toggleAddTab('manual'));
  $('search-omdb').addEventListener('click',searchOMDb);
  $('omdb-search').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();searchOMDb()}});
  $('manual-form').addEventListener('submit',addManual);
  $('edit-form').addEventListener('submit',saveDetail);
  $('edit-imdb-id').addEventListener('input',e=>{$('sync-imdb-id').value=e.target.value});
  $('sync-imdb-id').addEventListener('input',e=>{$('edit-imdb-id').value=e.target.value});
  $('sync-one').addEventListener('click',syncOne);
  $('delete-one').addEventListener('click',deleteOne);
  $('settings-form').addEventListener('submit',saveSettings);
  $('tmdb-form').addEventListener('submit',saveTMDb);
  $('test-omdb').addEventListener('click',testOMDb);
  $('test-tmdb').addEventListener('click',testTMDb);
  $('import-activate').addEventListener('click',()=>$('import-file').click());
  $('import-file').addEventListener('change',importFile);
  $('refresh-all').addEventListener('click',syncAll);
  document.addEventListener('click',e=>{
    const trigger=e.target.closest('[data-play-trailer]');if(trigger)toggleTrailer();
  });
}
async function init(){
  setScore('manual-score',null);setScore('edit-score',null);listeners();
  try{state.settings=await api('/api/settings');await reload()}
  catch(e){toast(e.message,'error');$('tiers-container').innerHTML='<p class="empty-search">O CineDuo não conseguiu se conectar ao banco de dados.</p>'}
}
document.addEventListener('DOMContentLoaded',init);
