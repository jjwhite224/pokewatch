'use strict';
let state = null, view = 'matches', limit = 30, refreshing = false, refreshError = false, refreshedAt = null;
const hosting = window.POKEWATCH_HOSTING || {mode:'local'};
const hosted = hosting.mode === 'pages';
const stateUrl = hosted ? hosting.stateUrl || './state.json' : './api/state';
const $ = (selector) => document.querySelector(selector);
const searchKey = (value) => String(value).normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/[^a-z0-9]+/g,' ').trim();
const money = (n) => n == null ? 'Unknown' : new Intl.NumberFormat('en-US', {style:'currency',currency:'USD'}).format(n/100);
const ago = (value) => {if(!value)return 'Not checked';const minutes=Math.max(0,Math.floor((Date.now()-new Date(value))/60000));return minutes<1?'Just now':minutes<60?`${minutes}m ago`:minutes<1440?`${Math.floor(minutes/60)}h ago`:new Date(value).toLocaleDateString();};
const intervalSeconds = () => Number.isFinite(Number(state?.interval_seconds)) && Number(state.interval_seconds)>0 ? Number(state.interval_seconds) : 900;
function fresh(value){const checked=Date.parse(value),age=Date.now()-checked;return Number.isFinite(checked)&&age>=0&&age<=intervalSeconds()*2000;}
function currentProduct(item){const stale=Boolean(item.stale)||!fresh(item.checked_at);return {...item,stale,qualifies:Boolean(item.qualifies)&&!stale&&!item.error};}
const currentProducts = () => Object.values(state?.products||{}).map(currentProduct);
function node(tag, attrs={}, text='') {const el=document.createElement(tag);for(const [key,value] of Object.entries(attrs)){if(value!=null)el.setAttribute(key,value);}if(text)el.textContent=text;return el;}
function link(text,url,cls='') {const a=node('a',{target:'_blank',rel:'noopener noreferrer',class:cls},text);try {const parsed=new URL(url);if(parsed.protocol==='https:')a.href=parsed.href;}catch{}return a;}
function badge(text,type=''){return node('span',{class:`badge ${type}`},text);}
function notice(text){$('#notice').hidden=false;$('#notice').textContent=text;}
async function api(path,data){if(hosted)throw new Error('This published dashboard is read-only.');const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-PokeWatch-Token':state.token},body:JSON.stringify(data)});const result=await response.json();if(!response.ok)throw new Error(result.error||'Request failed');return result;}
function selectView(next){view=next;limit=30;$('.tabs').querySelectorAll('button').forEach(b=>{b.classList.toggle('selected',b.dataset.view===view);b.setAttribute('aria-pressed',b.dataset.view===view?'true':'false');});renderResults();}
function referenceDialog(item){if(hosted)return;const form=$('#reference-form');form.reset();form.elements.product_id.value=item.id;form.elements.price.value=item.reference_cents?item.reference_cents/100:'';form.elements.url.value=item.reference_url||'';if(item.reference_kind)form.elements.kind.value=item.reference_kind;$('#reference-title').textContent=item.title;$('#reference-form .form-error').textContent='';$('#reference-dialog').showModal();}
function productCard(item){
  const card=node('article',{class:'product'});
  let image;
  try{if(new URL(item.image).protocol==='https:'){image=node('img',{src:item.image,alt:'',loading:'lazy',class:'product-image',referrerpolicy:'no-referrer'});image.addEventListener('error',()=>image.replaceWith(node('div',{class:'product-image image-empty'},'Pokémon TCG')));}}catch{}
  card.append(image||node('div',{class:'product-image image-empty'},'Pokémon TCG'));
  const body=node('div'), store=node('div',{class:'store-line'});store.append(node('span',{},item.store));
  const stocked=['InStock','PreOrder','PreSale','LimitedAvailability'].includes(item.availability);
  const status=item.stale?'Needs recheck':item.availability==='OutOfStock'?'Sold out':item.availability==='InStoreOnly'?'In-store only':item.availability==='InStock'?'In stock':['PreOrder','PreSale'].includes(item.availability)?'Preorder':item.availability==='LimitedAvailability'?'Limited stock':'Stock unknown';
  store.append(badge(status,item.stale?'warn':stocked?'good':''));if(item.seller_verified===false)store.append(badge(item.seller==='Seller not confirmed by API'?'Seller unverified':'Marketplace','warn'));body.append(store);
  const title=node('h3');title.append(link(item.title,item.url));body.append(title);
  const details=node('div',{class:'product-detail'});
  if(item.reference_cents){details.append(link(item.reference_kind,item.reference_url));}else{details.append(node('span',{},'No verified price reference yet'));}
  if(item.source_id==='dollargeneral')details.append(node('div',{},'Catalog price · confirm price and stock with your selected store'));
  details.append(node('span',{},` · Checked ${ago(item.checked_at)}`));if(item.seller)details.append(node('div',{},`Seller: ${item.seller}${item.seller_verified===false?' · excluded from automatic alerts':''}`));body.append(details);card.append(body);
  const prices=node('div',{class:'price-block'});prices.append(node('span',{class:`price ${item.qualifies?'match':''}`},item.currency==='USD'?money(item.price_cents):'Price unknown'));
  prices.append(node('span',{class:'price-ref'},item.reference_cents?`Reference ${money(item.reference_cents)}`:'Reference needed'));
  if(!hosted){const edit=node('button',{class:'text-button'},item.reference_cents?'Edit reference':'Set reference');edit.addEventListener('click',()=>referenceDialog(item));prices.append(edit);}card.append(prices);return card;
}
function renderResults(){
  if(!state)return;
  const target=$('#results');target.replaceChildren();const query=$('#search').value.toLowerCase();
  const official=view==='releases';$('#store').disabled=official;$('#stock').disabled=official;$('#sort').disabled=official;
  $('#view-note').textContent=official?'Official product announcements. “Discovered” is when this bot first saw a page, not its release date. Open the announcement for launch details.':'Prices are for the product only, before shipping and tax. Availability can change before checkout.';
  let items=official?Object.values(state.releases):currentProducts();
  items=items.filter(p=>searchKey(query).split(/\s+/).every(word=>searchKey(p.title).includes(word)));
  if(!official){items=items.filter(p=>(!$('#store').value||p.store===$('#store').value)&&(!$('#stock').checked||(!p.stale&&['InStock','PreOrder','PreSale','LimitedAvailability'].includes(p.availability))));if(view==='matches')items=items.filter(p=>p.qualifies);if(view==='unverified')items=items.filter(p=>!p.reference_cents);const sorting=$('#sort').value;
    const when=value=>{const parsed=Date.parse(value);return Number.isFinite(parsed)?parsed:0;};
    const numericPrice=item=>Number.isInteger(item.price_cents)&&item.price_cents>0?item.price_cents:null;
    items.sort((a,b)=>{
      if(sorting==='recently-checked')return when(b.checked_at)-when(a.checked_at)||a.title.localeCompare(b.title);
      if(sorting==='price-low'||sorting==='price-high'){
        const pa=numericPrice(a),pb=numericPrice(b);
        if(pa===null)return pb===null?a.title.localeCompare(b.title):1;
        if(pb===null)return -1;
        return (sorting==='price-low'?pa-pb:pb-pa)||a.title.localeCompare(b.title);
      }
      return when(b.listed_at||b.first_seen)-when(a.listed_at||a.first_seen)||a.title.localeCompare(b.title);
    });}else{items.sort((a,b)=>new Date(b.first_seen)-new Date(a.first_seen));}
  if(!items.length){const box=node('div',{class:'empty'});box.append(node('h3',{},!hosted&&state.scanning&&!state.last_scan?'Checking the first listings…':view==='matches'?'No confirmed price matches right now.':'No listings in this view.'));box.append(node('p',{},view==='matches'?`A match needs a recent check, available stock, and a reference for the exact product. ${hosted?'Browse listings or official releases, and check source health for delayed data.':'Browse discovered listings to add a reference, or check the official release feed.'}`:'Try another search or check the source status. Results update automatically.'));if(view==='matches'){const button=node('button',{class:'secondary'},'Browse all listings');button.onclick=()=>selectView('all');box.append(button);}target.append(box);}
  for(const item of items.slice(0,limit)){if(official){const row=node('article',{class:'release'});row.append(link(item.title,item.url),node('p',{},`Pokémon · Official announcement · Discovered ${ago(item.first_seen)}`));target.append(row);}else target.append(productCard(item));}
  $('#more').hidden=items.length<=limit;
}
function render(){
  const products=currentProducts(),sources=Object.values(state.sources),automatic=sources.filter(s=>s.status!=='manual');
  const freshProducts=products.filter(p=>!p.stale);
  const staleCount=products.length-freshProducts.length;
  const unknownCount=products.filter(p=>p.availability==='Unknown'||!p.availability).length;
  const unverifiedCount=products.filter(p=>p.seller_verified===false).length;
  const scanFresh=fresh(state.last_scan);
  $('#confidence-fresh').textContent=freshProducts.length;
  $('#confidence-unknown').textContent=unknownCount;
  $('#confidence-unverified').textContent=unverifiedCount;
  $('#confidence-stale').textContent=staleCount;
  $('#confidence-label').textContent=!state.last_scan?'Awaiting first scan':!scanFresh?'Scan overdue':staleCount?'Mixed freshness':'Recent scan';
  $('#confidence-label').className='badge '+(!state.last_scan||!scanFresh||staleCount?'warn':'good');
  $('#confidence-description').textContent=!state.last_scan
    ?'No scan has been recorded. Listings and store inventory have not been verified.'
    :!scanFresh
      ?'The latest scan is outside the freshness window. Old availability and deal claims cannot be treated as current.'
      :`Last scan ${ago(state.last_scan)}. Fresh product checks show retailer signals, not guaranteed checkout or in-store inventory.`;
  $('#matches').textContent=products.filter(p=>p.qualifies).length;$('#products-count').textContent=products.length;$('#sources-count').textContent=`${automatic.filter(s=>s.status!=='error'&&fresh(s.checked_at)).length} / ${automatic.length}`;
  $('#last-check').textContent=state.last_scan?`Last store check ${ago(state.last_scan)}`:hosted?'No store check recorded':'First check is running';
  $('#check').textContent=hosted?(refreshing?'Refreshing…':'Refresh data'):state.scanning?'Checking…':'Check now';$('#check').disabled=hosted?refreshing:Boolean(state.scanning);
  $('#scan-state').textContent=hosted?(fresh(state.generated_at)?'Published':'Data is stale'):state.scanning?'Checking':'Monitoring';
  $('#schedule').textContent=hosted?`Target: every ${intervalSeconds()/60} minutes`:`Checks every ${intervalSeconds()/60} minutes`;
  if(hosted){$('#hosting-note').textContent=`Hosted, read-only dashboard · Published ${ago(state.generated_at)}${state.generated_at?` (${new Date(state.generated_at).toLocaleString()})`:''} · Page refreshed ${ago(refreshedAt)}. Scheduled checks can be delayed. Listings older than ${intervalSeconds()/30} minutes are excluded from available stock and price matches.`;}
  const selected=$('#store').value;$('#store').replaceChildren(node('option',{value:''},'All stores'));[...new Set(products.map(p=>p.store))].sort().forEach(name=>$('#store').append(node('option',{value:name},name)));$('#store').value=selected;
  $('#sources').replaceChildren();if(!sources.length)$('#sources').append(node('p',{class:'small'},'Contacting Pokémon and retailer catalogs…'));
  for(const source of sources){const row=node('div',{class:'source'}),title=node('div',{class:'source-name'});const sourcePage=source.url.includes('/products.json')?source.url.split('/products.json')[0]:source.url;const manual=source.status==='manual',stale=!fresh(source.checked_at),status=manual?'Check with retailer':source.status==='error'?'Unavailable':stale?'Needs recheck':source.status==='ok'?'Online':'Partial';title.append(link(source.name,sourcePage),badge(status,source.status==='error'?'bad':manual||stale||source.status==='partial'?'warn':'good'));row.append(title,node('p',{},manual?source.message:`${source.coverage==='One specific product'?'One product watch':source.count+' listings'} · ${ago(source.checked_at)}${source.status!=='ok'?` · ${source.message}`:''}`));$('#sources').append(row);}
  $('#alerts').replaceChildren();if(!state.alerts.length)$('#alerts').append(node('p',{class:'small'},'No alerts yet. New official announcements and qualifying restocks will appear here.'));
  for(const alert of state.alerts.slice(-6).reverse()){const row=node('article',{class:'alert'});row.append(link(alert.title,alert.url),node('span',{},alert.kind==='release'?`New announcement · ${ago(alert.at)}`:`${money(alert.price_cents)} · ${alert.store} · ${ago(alert.at)}`));$('#alerts').append(row);}renderResults();
}
async function refresh(){if(refreshing)return;refreshing=true;if(hosted){$('#check').disabled=true;$('#check').textContent='Refreshing…';}try{const response=await fetch(stateUrl,{cache:'no-store'});if(!response.ok)throw new Error();const next=await response.json();if(!next.products||!next.sources||!next.releases||!Array.isArray(next.alerts))throw new Error();state=next;refreshedAt=new Date().toISOString();if(refreshError)$('#notice').hidden=true;refreshError=false;}catch{refreshError=true;notice(hosted?'Published data could not be loaded. The page will retry automatically; any saved listings still expire as they age.':'The local bot is not responding. Run Start PokéWatch.cmd to reconnect.');}finally{refreshing=false;if(state)render();else if(hosted){$('#check').disabled=false;$('#check').textContent='Refresh data';}if(refreshError)$('#scan-state').textContent=hosted?'Refresh failed':'Disconnected';}}
$('.tabs').addEventListener('click',e=>{if(e.target.dataset.view)selectView(e.target.dataset.view);});
for(const id of ['#search','#store','#stock','#sort'])$(id).addEventListener('input',()=>{limit=30;renderResults();});
$('#more').onclick=()=>{limit+=30;renderResults();};
$('#check').onclick=async()=>{if(hosted)return refresh();try{await api('./api/scan',{});await refresh();}catch(e){notice(e.message);}};
$('#add-watch').onclick=()=>{if(hosted)return;$('#watch-form').reset();$('#watch-form .form-error').textContent='';$('#watch-dialog').showModal();};
document.querySelectorAll('.close').forEach(b=>b.onclick=()=>b.closest('dialog').close());
$('#reference-form').onsubmit=async(e)=>{e.preventDefault();try{await api('./api/reference',Object.fromEntries(new FormData(e.target)));$('#reference-dialog').close();notice('Reference saved. The next live check will evaluate this product for an alert.');await refresh();}catch(error){$('#reference-form .form-error').textContent=error.message;}};
$('#watch-form').onsubmit=async(e)=>{e.preventDefault();try{await api('./api/watch',Object.fromEntries(new FormData(e.target)));$('#watch-dialog').close();notice('Product added. Use Check now, or wait for the next scheduled check.');await refresh();}catch(error){$('#watch-form .form-error').textContent=error.message;}};
if(hosted){$('#tracker-mode').textContent='HOSTED · READ-ONLY';$('#alert-scope').textContent='PUBLISHED';$('#add-watch').hidden=true;$('#reference-dialog').hidden=true;$('#watch-dialog').hidden=true;$('#hosting-note').hidden=false;$('#hosting-note').textContent='Loading the latest published snapshot. Refresh data reads the published file; it does not start a store check.';$('#runtime-note').textContent='Scheduled checks publish results here. Desktop notifications are available from the local bot.';$('#results').replaceChildren(node('div',{class:'empty'},'Loading published listings…'));}
refresh();setInterval(refresh,hosted?60000:5000);setInterval(()=>{if(state){render();if(refreshError)$('#scan-state').textContent=hosted?'Refresh failed':'Disconnected';}},15000);
// Expose the same read-only listing search when the browser supports WebMCP.
if(document.modelContext?.registerTool){
  const lifecycle=new AbortController();
  window.addEventListener('pagehide',()=>lifecycle.abort(),{once:true});
  try{Promise.resolve(document.modelContext.registerTool({
    name:'search_pokewatch_listings',title:'Search Pokémon listings',
    description:'Read listings already checked by this tracker, including exact price references, stock, and freshness. Does not contact stores or change watches.',
    inputSchema:{type:'object',properties:{query:{type:'string'},matchesOnly:{type:'boolean'}},additionalProperties:false},
    annotations:{readOnlyHint:true,untrustedContentHint:true},
    execute(input){if(!input||typeof input!=='object'||(input.query!==undefined&&typeof input.query!=='string')||(input.matchesOnly!==undefined&&typeof input.matchesOnly!=='boolean')||Object.keys(input).some(k=>!['query','matchesOnly'].includes(k)))throw new Error('Provide query as text and matchesOnly as a boolean.');if(!state)throw new Error('The tracker has not connected yet.');const q=(input.query||'').toLowerCase();return currentProducts().filter(p=>p.title.toLowerCase().includes(q)&&(!input.matchesOnly||p.qualifies)).slice(0,30).map(({title,store,url,price_cents,reference_cents,reference_kind,availability,stale,checked_at})=>({title,store,url,price_cents,reference_cents,reference_kind,availability,stale,checked_at}));}
  },{signal:lifecycle.signal})).catch(()=>{});}catch{}
}
