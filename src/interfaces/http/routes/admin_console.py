"""
Visual admin console for provisioning external chatbot widgets.

Served at ``GET /admin/console`` on the main app (strict CORS, internal). It is a
thin, dependency-free single page that drives the existing admin + grounded-
document APIs over same-origin fetch: create/edit/delete bots, live-preview the
theme as you change it, copy the embed snippet, and crawl a website into a bot's
knowledge collection. This is what makes the "re-skin per company with no code"
story usable without hand-writing JSON.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(prefix="/admin", tags=["Admin · Console"])


ADMIN_CONSOLE_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Widget Console</title>
<style>
  :root {
    --bg:#f5f1ea; --panel:#fffdf8; --ink:#1f2a2e; --muted:#5f6c70; --line:#e0d8cb;
    --accent:#0f766e; --accent-soft:#d7efe9; --danger:#9a3412;
  }
  * { box-sizing:border-box; }
  body { margin:0; font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
    background:var(--bg); color:var(--ink); }
  header { padding:18px 24px; border-bottom:1px solid var(--line); background:var(--panel); }
  header h1 { margin:0; font-size:1.3rem; }
  header p { margin:4px 0 0; color:var(--muted); font-size:.85rem; }
  .wrap { max-width:1240px; margin:0 auto; padding:20px 24px 60px; }
  .grid { display:grid; grid-template-columns:1.1fr .9fr; gap:20px; align-items:start; }
  .card { background:var(--panel); border:1px solid var(--line); border-radius:14px; padding:18px; margin-bottom:18px; }
  .card h2 { margin:0 0 14px; font-size:1rem; }
  label { display:block; font-size:.78rem; color:var(--muted); margin:10px 0 4px; font-weight:600; }
  input[type=text], input[type=url], textarea, select {
    width:100%; border:1px solid #cfc6b8; border-radius:9px; padding:9px 11px; font:inherit;
    background:#fff; color:var(--ink); }
  textarea { min-height:64px; resize:vertical; }
  .row { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
  .row3 { display:grid; grid-template-columns:1fr 1fr 1fr; gap:12px; }
  .swatch { display:flex; align-items:center; gap:8px; }
  .swatch input[type=color] { width:42px; height:34px; padding:0; border:1px solid #cfc6b8; border-radius:8px; background:#fff; }
  .btn { border:none; border-radius:9px; padding:10px 16px; font:inherit; font-weight:600; cursor:pointer; }
  .btn.primary { background:var(--accent); color:#fff; }
  .btn.ghost { background:transparent; border:1px solid var(--line); color:var(--ink); }
  .btn.danger { background:transparent; border:1px solid var(--danger); color:var(--danger); }
  .btn.sm { padding:6px 10px; font-size:.8rem; }
  .actions { display:flex; gap:10px; margin-top:16px; flex-wrap:wrap; }
  .hint { font-size:.74rem; color:var(--muted); margin-top:4px; }
  .toast { position:fixed; bottom:18px; left:50%; transform:translateX(-50%); background:var(--ink); color:#fff;
    padding:10px 16px; border-radius:9px; font-size:.85rem; opacity:0; transition:opacity .2s; pointer-events:none; z-index:50; }
  .toast.show { opacity:1; }
  .bot { border:1px solid var(--line); border-radius:11px; padding:12px 14px; margin-bottom:10px; }
  .bot .top { display:flex; justify-content:space-between; align-items:center; gap:10px; }
  .bot .name { font-weight:600; }
  .bot .meta { font-size:.74rem; color:var(--muted); }
  .snippet { background:#2b2b2b; color:#e8e8e8; font-family:ui-monospace,Consolas,monospace; font-size:.72rem;
    padding:8px 10px; border-radius:8px; margin-top:8px; word-break:break-all; }
  .warn { background:#fdf2e7; border:1px solid #f0c9a3; color:var(--danger); padding:8px 10px; border-radius:8px; font-size:.78rem; margin-top:8px; }
  .ok { background:var(--accent-soft); border:1px solid #aee0d6; color:#0c5b54; padding:8px 10px; border-radius:8px; font-size:.78rem; margin-top:8px; }

  /* ---- live preview mock (mirrors the real widget's CSS-variable theming) ---- */
  .preview-stage { position:relative; background:repeating-linear-gradient(45deg,#eee,#eee 12px,#e7e7e7 12px,#e7e7e7 24px);
    border:1px solid var(--line); border-radius:12px; height:520px; overflow:hidden; }
  .pv { position:absolute; bottom:84px; right:18px; width:320px; max-width:calc(100% - 36px);
    background:var(--p-surface); color:var(--p-text); border-radius:var(--p-radius); box-shadow:0 16px 40px rgba(0,0,0,.28);
    display:flex; flex-direction:column; overflow:hidden; font-family:var(--p-font); }
  .pv.left { right:auto; left:18px; }
  .pv-head { background:var(--p-primary); color:#fff; padding:12px 14px; display:flex; align-items:center; gap:9px; }
  .pv-head img { width:24px; height:24px; border-radius:50%; object-fit:cover; background:#fff; }
  .pv-head .nm { font-weight:600; font-size:14px; flex:1; }
  .pv-body { padding:14px; display:flex; flex-direction:column; gap:9px; min-height:150px; }
  .pv-msg { max-width:86%; padding:9px 12px; border-radius:13px; font-size:13px; line-height:1.4; }
  .pv-bot { align-self:flex-start; background:rgba(0,0,0,.05); }
  .pv-user { align-self:flex-end; background:var(--p-user); color:#fff; }
  .pv-chips { display:flex; flex-wrap:wrap; gap:7px; }
  .pv-chip { border:1px solid var(--p-accent); color:var(--p-accent); border-radius:15px; padding:6px 11px; font-size:12px; }
  .pv-src { margin-top:6px; font-size:11px; }
  .pv-src a { color:var(--p-accent); text-decoration:none; }
  .pv-input { display:flex; gap:7px; padding:11px; border-top:1px solid rgba(0,0,0,.1); }
  .pv-input .fake { flex:1; border:1px solid rgba(0,0,0,.18); border-radius:9px; padding:8px 11px; font-size:13px; color:#888; background:#fff; }
  .pv-input .send { background:var(--p-primary); color:#fff; border-radius:9px; padding:8px 12px; font-size:13px; }
  .pv-launch { position:absolute; bottom:18px; right:18px; width:56px; height:56px; border-radius:50%;
    background:var(--p-primary); color:#fff; display:flex; align-items:center; justify-content:center; box-shadow:0 6px 18px rgba(0,0,0,.3); }
  .pv-launch.left { right:auto; left:18px; }
  .pv-launch svg { width:26px; height:26px; }
  @media (max-width:980px){ .grid{ grid-template-columns:1fr; } }
</style>
</head>
<body>
<header>
  <h1>Widget Console</h1>
  <p>Create, theme, and preview an embeddable chatbot for any company — then paste one script tag on their site.</p>
</header>
<div class="wrap">
  <div class="grid">
    <!-- LEFT: config -->
    <div>
      <div class="card">
        <h2 id="formTitle">Create a bot</h2>
        <div class="row">
          <div><label>Tenant ID</label><input id="tenant_id" type="text" value="acme"></div>
          <div><label>Collection ID (knowledge base)</label><input id="collection_id" type="text" value="acme-kb"></div>
        </div>
        <label>Display name</label><input id="display_name" type="text" value="Acme Assistant">
        <label>Greeting</label><input id="greeting" type="text" value="Hi! How can I help you today?">
        <label>Suggested prompts <span class="hint">— one per line, format: <code>Label | the actual question</code></span></label>
        <textarea id="prompts">Pricing | What are your prices?
Support | How do I contact support?</textarea>
        <label>Allowed origins <span class="hint">— one per line (exact scheme://host[:port]); required to enable</span></label>
        <textarea id="origins">http://localhost:5500</textarea>
      </div>

      <div class="card">
        <h2>Theme</h2>
        <div class="row3">
          <div><label>Primary</label><div class="swatch"><input id="primary_color" type="color" value="#2d6a4f"></div></div>
          <div><label>Accent</label><div class="swatch"><input id="accent_color" type="color" value="#8a5a2b"></div></div>
          <div><label>User bubble</label><div class="swatch"><input id="user_bubble_color" type="color" value="#2d6a4f"></div></div>
        </div>
        <div class="row3">
          <div><label>Surface</label><div class="swatch"><input id="surface_color" type="color" value="#fffbf4"></div></div>
          <div><label>Text</label><div class="swatch"><input id="text_color" type="color" value="#1d2b2a"></div></div>
          <div><label>Corner radius</label><input id="corner_radius_px" type="range" min="0" max="32" value="16"></div>
        </div>
        <div class="row3">
          <div><label>Launcher position</label>
            <select id="launcher_position"><option value="bottom-right">bottom-right</option><option value="bottom-left">bottom-left</option></select></div>
          <div><label>Font family</label><input id="font_family" type="text" value="system-ui, sans-serif"></div>
          <div><label>Logo URL (optional)</label><input id="logo_url" type="url" placeholder="https://…"></div>
        </div>
        <div class="actions">
          <button class="btn primary" id="saveBtn" onclick="createOrSave()">Create bot</button>
          <button class="btn ghost" onclick="resetForm()">Reset / New</button>
          <span id="editingNote" class="hint"></span>
        </div>
        <div id="formMsg"></div>
      </div>

      <div class="card">
        <h2>Knowledge — crawl a website</h2>
        <label>Start URL</label><input id="crawl_url" type="url" placeholder="https://company.com">
        <div class="row3" style="margin-top:10px">
          <div><label>Max pages</label><input id="crawl_pages" type="text" value="15"></div>
          <div><label>Max depth</label><input id="crawl_depth" type="text" value="2"></div>
          <div style="display:flex;align-items:flex-end"><button class="btn primary" style="width:100%" onclick="runCrawl()">Crawl into collection</button></div>
        </div>
        <div class="hint">Crawls into the Collection ID above. Static/SSR sites only — JS-rendered SPAs return little text.</div>
        <div id="crawlMsg"></div>
      </div>
    </div>

    <!-- RIGHT: live preview + bots -->
    <div>
      <div class="card">
        <h2>Live preview</h2>
        <div class="preview-stage">
          <div class="pv" id="pv">
            <div class="pv-head"><img id="pvLogo" alt="" style="display:none"><span class="nm" id="pvName">Acme Assistant</span><span>&times;</span></div>
            <div class="pv-body">
              <div class="pv-msg pv-bot" id="pvGreeting">Hi! How can I help you today?</div>
              <div class="pv-chips" id="pvChips"></div>
              <div class="pv-msg pv-user">What are your prices?</div>
              <div class="pv-msg pv-bot">Our Standard plan is $29/mo and Pro is $79/mo.
                <div class="pv-src">Sources: <a href="#">[1] pricing (p.1)</a></div></div>
            </div>
            <div class="pv-input"><div class="fake">Type your message…</div><div class="send">Send</div></div>
          </div>
          <div class="pv-launch" id="pvLaunch"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 3C7 3 3 6.6 3 11c0 2 .9 3.8 2.4 5.2L4.5 20l4-1.3c1.1.4 2.3.6 3.5.6 5 0 9-3.6 9-8s-4-8.3-9-8.3z"/></svg></div>
        </div>
        <div class="hint">This mock updates live as you edit the theme. After saving, use “Live preview” on a bot for the real widget.</div>
      </div>

      <div class="card">
        <h2>Bots <button class="btn ghost sm" onclick="loadBots()" style="float:right">Refresh</button></h2>
        <div id="botList"><div class="hint">Loading…</div></div>
      </div>
    </div>
  </div>
</div>
<div class="toast" id="toast"></div>

<script>
const API = window.location.origin;
let editingBotId = null;

function $(id){ return document.getElementById(id); }
function toast(msg){ const t=$('toast'); t.textContent=msg; t.classList.add('show'); setTimeout(()=>t.classList.remove('show'),2200); }

function themeFromForm(){
  return {
    primary_color:$('primary_color').value, accent_color:$('accent_color').value,
    surface_color:$('surface_color').value, text_color:$('text_color').value,
    user_bubble_color:$('user_bubble_color').value, font_family:$('font_family').value,
    logo_url:$('logo_url').value||null, launcher_position:$('launcher_position').value,
    corner_radius_px:parseInt($('corner_radius_px').value,10), dark_mode:false
  };
}
function parsePrompts(){
  return $('prompts').value.split('\n').map(l=>l.trim()).filter(Boolean).map(l=>{
    const i=l.indexOf('|'); if(i<0) return {label:l, prompt:l};
    return {label:l.slice(0,i).trim(), prompt:l.slice(i+1).trim()};
  });
}
function parseOrigins(){ return $('origins').value.split('\n').map(s=>s.trim()).filter(Boolean); }

function applyPreview(){
  const t=themeFromForm(); const pv=$('pv'); const s=pv.style;
  s.setProperty('--p-primary',t.primary_color); s.setProperty('--p-accent',t.accent_color);
  s.setProperty('--p-surface',t.surface_color); s.setProperty('--p-text',t.text_color);
  s.setProperty('--p-user',t.user_bubble_color); s.setProperty('--p-font',t.font_family);
  s.setProperty('--p-radius',t.corner_radius_px+'px');
  $('pvLaunch').style.setProperty('--p-primary',t.primary_color);
  pv.classList.toggle('left', t.launcher_position==='bottom-left');
  $('pvLaunch').classList.toggle('left', t.launcher_position==='bottom-left');
  $('pvName').textContent=$('display_name').value||'Assistant';
  $('pvGreeting').textContent=$('greeting').value||'Hi!';
  const logo=$('logo_url').value; const li=$('pvLogo');
  if(logo){ li.src=logo; li.style.display=''; } else { li.style.display='none'; }
  const chips=$('pvChips'); chips.innerHTML='';
  parsePrompts().slice(0,4).forEach(p=>{ const c=document.createElement('span'); c.className='pv-chip'; c.textContent=p.label; chips.appendChild(c); });
}
document.addEventListener('input', e=>{ if(e.target.closest('.card')) applyPreview(); });

function payloadFromForm(){
  return {
    tenant_id:$('tenant_id').value.trim(), collection_id:$('collection_id').value.trim(),
    display_name:$('display_name').value.trim(), greeting:$('greeting').value.trim(),
    suggested_prompts:parsePrompts(), allowed_origins:parseOrigins(), theme:themeFromForm()
  };
}

async function createOrSave(){
  const body=payloadFromForm();
  const url = editingBotId ? `${API}/admin/bots/${editingBotId}` : `${API}/admin/bots`;
  const method = editingBotId ? 'PUT' : 'POST';
  const r = await fetch(url,{method, headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  const j = await r.json();
  if(!r.ok){ $('formMsg').innerHTML=`<div class="warn">${(j.detail)||'Failed'}</div>`; return; }
  $('formMsg').innerHTML='';
  toast(editingBotId?'Saved':'Bot created');
  if(j.warnings && j.warnings.length) $('formMsg').innerHTML=`<div class="warn">${j.warnings.join(' ')}</div>`;
  editingBotId=j.config.bot_id; setEditing(j.config.bot_id);
  loadBots();
}

function setEditing(id){
  editingBotId=id;
  $('formTitle').textContent = id ? 'Edit bot' : 'Create a bot';
  $('saveBtn').textContent = id ? 'Save changes' : 'Create bot';
  $('editingNote').textContent = id ? ('editing '+id) : '';
}
function resetForm(){ setEditing(null); $('formMsg').innerHTML=''; $('crawlMsg').innerHTML=''; }

function editBot(c){
  $('tenant_id').value=c.tenant_id; $('collection_id').value=c.collection_id;
  $('display_name').value=c.display_name; $('greeting').value=c.greeting;
  $('prompts').value=(c.suggested_prompts||[]).map(p=>`${p.label} | ${p.prompt}`).join('\n');
  $('origins').value=(c.allowed_origins||[]).join('\n');
  const t=c.theme||{};
  ['primary_color','accent_color','surface_color','text_color','user_bubble_color'].forEach(k=>{ if(t[k]) $(k).value=t[k]; });
  $('font_family').value=t.font_family||''; $('logo_url').value=t.logo_url||'';
  $('launcher_position').value=t.launcher_position||'bottom-right';
  $('corner_radius_px').value=t.corner_radius_px!=null?t.corner_radius_px:16;
  setEditing(c.bot_id); applyPreview(); window.scrollTo({top:0,behavior:'smooth'});
}

async function deleteBot(id){
  if(!confirm('Delete '+id+'?')) return;
  await fetch(`${API}/admin/bots/${id}`,{method:'DELETE'});
  if(editingBotId===id) resetForm();
  toast('Deleted'); loadBots();
}

async function loadBots(){
  const r=await fetch(`${API}/admin/bots`); const list=await r.json();
  const el=$('botList');
  if(!list.length){ el.innerHTML='<div class="hint">No bots yet — create one above.</div>'; return; }
  el.innerHTML='';
  list.forEach(v=>{
    const c=v.config;
    const div=document.createElement('div'); div.className='bot';
    div.innerHTML=`<div class="top"><div><div class="name">${c.display_name}</div>
      <div class="meta">${c.bot_id} · tenant ${c.tenant_id} · ${c.enabled?'enabled':'disabled'}</div></div>
      <div style="display:flex;gap:6px;flex-wrap:wrap">
        <button class="btn ghost sm" data-act="edit">Edit</button>
        <a class="btn ghost sm" target="_blank" href="${API}/widget/preview?bot_id=${c.bot_id}">Live preview</a>
        <button class="btn ghost sm" data-act="copy">Copy embed</button>
        <button class="btn danger sm" data-act="del">Delete</button>
      </div></div>
      <div class="snippet">${v.embed_snippet.replace(/</g,'&lt;')}</div>`;
    div.querySelector('[data-act=edit]').onclick=()=>editBot(c);
    div.querySelector('[data-act=del]').onclick=()=>deleteBot(c.bot_id);
    div.querySelector('[data-act=copy]').onclick=()=>{ navigator.clipboard.writeText(v.embed_snippet); toast('Embed snippet copied'); };
    el.appendChild(div);
  });
}

async function runCrawl(){
  const url=$('crawl_url').value.trim(); if(!url){ toast('Enter a URL'); return; }
  const body={ start_url:url, tenant_id:$('tenant_id').value.trim(), domain:'general',
    max_pages:parseInt($('crawl_pages').value,10)||15, max_depth:parseInt($('crawl_depth').value,10)||2 };
  $('crawlMsg').innerHTML='<div class="hint">Crawling… this can take a moment.</div>';
  const r=await fetch(`${API}/grounded-documents/collections/${$('collection_id').value.trim()}/crawl`,
    {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  const j=await r.json();
  if(!r.ok){ $('crawlMsg').innerHTML=`<div class="warn">${j.detail||'Crawl failed'}</div>`; return; }
  let html=`<div class="ok">Crawled ${j.pages_crawled} page(s); collection now has ${j.collection.document_count} document(s).</div>`;
  if(j.warnings && j.warnings.length) html+=`<div class="warn">${j.warnings.join(' ')}</div>`;
  $('crawlMsg').innerHTML=html; toast('Crawl complete');
}

applyPreview(); loadBots();
</script>
</body>
</html>
"""


@router.get("/console", response_class=HTMLResponse, summary="Visual widget admin console")
async def admin_console() -> HTMLResponse:
    return HTMLResponse(content=ADMIN_CONSOLE_HTML)
