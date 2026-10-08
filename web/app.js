const $ = id => document.getElementById(id);
async function call(name, args = {}) {
  const response = await fetch('/api/call', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,arguments:args})});
  const data = await response.json(); if (!response.ok) throw new Error(data.error || 'Request failed'); return data;
}
async function action(fn) {
  $('status').className=''; $('status').textContent='Working…';
  try {await fn(); $('status').textContent='Done. Evidence updated.';} catch(error){$('status').className='error';$('status').textContent=error.message;}
}
function show(data){$('result').textContent=JSON.stringify(data,null,2);}
async function refresh(){
 const data=await call('list_products');const root=$('products');root.replaceChildren();$('alert-product').replaceChildren();
 if(!data.products.length){root.textContent='No products yet. Record an observation to begin.';return;}
 const table=document.createElement('table');const head=table.createTHead().insertRow();for(const text of ['Select','Product','Latest capture','Inspect']){const th=document.createElement('th');th.textContent=text;head.append(th);}
 for(const row of data.products){const tr=table.insertRow();const check=document.createElement('input');check.type='checkbox';check.value=row.product.id;check.setAttribute('aria-label','Compare '+row.product.title);tr.insertCell().append(check);
 tr.insertCell().textContent=row.product.title+' · '+row.product.variant;const o=row.observation;tr.insertCell().textContent=o?`${o.price} ${o.currency} · ${o.stale?'stale':o.availability}`:'Not yet observed';
 const inspect=document.createElement('button');inspect.textContent='History';inspect.onclick=()=>action(async()=>show({history:await call('get_price_history',{product_id:row.product.id}),change:await call('explain_change',{product_id:row.product.id})}));tr.insertCell().append(inspect);
 const option=document.createElement('option');option.value=row.product.id;option.textContent=row.product.title;$('alert-product').append(option);
 }root.append(table);
}
$('record').onsubmit=e=>{e.preventDefault();action(async()=>{const observation={price:$('price').value,currency:$('currency').value,availability:$('availability').value};if($('captured').value)observation.captured_at=$('captured').value;show(await call('record_product',{url:$('url').value,title:$('title').value,variant:$('variant').value,observation}));await refresh();});};
$('snapshot').onsubmit=e=>{e.preventDefault();action(async()=>{show(await call('record_product',{url:$('snapshot-url').value,html:$('html').value}));await refresh();});};
$('alert').onsubmit=e=>{e.preventDefault();action(async()=>show(await call('set_price_alert',{product_id:$('alert-product').value,threshold:$('threshold').value,currency:$('alert-currency').value})));};
$('refresh').onclick=()=>action(refresh);$('check-alerts').onclick=()=>action(async()=>show(await call('check_alerts')));
$('compare').onclick=()=>action(async()=>show(await call('compare_products',{product_ids:[...document.querySelectorAll('#products input:checked')].map(x=>x.value)})));
action(refresh);
