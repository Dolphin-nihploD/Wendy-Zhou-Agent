/* ===================================================================
   Wendy Zhou interface — frontend logic
   =================================================================== */

/* ---------- view switching ---------- */
const navItems = document.querySelectorAll('.nav-item');
const views = document.querySelectorAll('.view');
navItems.forEach(btn => btn.addEventListener('click', () => {
  navItems.forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  const v = btn.dataset.view;
  views.forEach(sec => sec.classList.toggle('hidden', sec.id !== 'view-' + v));
  if (v === 'calendar') renderCalendar();
  if (v === 'memories') loadMemories();
  if (v === 'work') renderWorkTodos();
}));

/* ---------- collapse / expand the left bars (main nav + chat list) ----------
   Click the ☰ button to hide both left bars for more room, click again to
   bring them back. The choice is remembered across reloads. */
(function(){
  const navToggle = document.getElementById('navToggle');
  const appEl = document.querySelector('.app');
  if (!navToggle || !appEl) return;
  if (localStorage.getItem('navCollapsed') === '1') appEl.classList.add('nav-collapsed');
  navToggle.addEventListener('click', () => {
    appEl.classList.toggle('nav-collapsed');
    localStorage.setItem('navCollapsed', appEl.classList.contains('nav-collapsed') ? '1' : '0');
  });
})();

/* ---------- dashboard context (date + greeting) ---------- */
fetch('/api/context').then(r => r.json()).then(c => {
  document.getElementById('dashDate').textContent = c.date;
  document.getElementById('dashGreeting').textContent = c.greeting;
  const dot = document.getElementById('agentDot');
  const st  = document.getElementById('agentStatus');
  if (c.agent_connected){ dot.classList.add('on'); st.textContent = 'Agent connected'; }
  else { dot.classList.add('off'); st.textContent = 'Agent not linked'; }
}).catch(()=>{});

/* ---------- load news on dashboard --------- */
function loadNews(){
  const container = document.getElementById('newsContainer');
  fetch('/api/news?days=7').then(r => r.json()).then(data => {
    if (!data.success || !data.articles.length){
      container.innerHTML = '<div class="news-loading">No recent news found.</div>';
      return;
    }
    const html = data.articles.slice(0, 5).map(article => `
      <a href="${article.url}" target="_blank" rel="noopener" class="news-item">
        <div class="news-title">${article.title}</div>
        <div class="news-meta">
          <span class="news-source">${article.source}</span> • ${new Date(article.published_at).toLocaleDateString()}
        </div>
      </a>
    `).join('');
    container.innerHTML = html;
  }).catch(err => {
    container.innerHTML = '<div class="news-loading">Could not load news.</div>';
  });
}
loadNews();
// refresh news every hour
setInterval(loadNews, 3600000);

/* ---------- load stocks (market watch) ---------- */
function loadStocks(){
  const el = document.getElementById('stocksContainer');
  fetch('/api/stocks').then(r => r.json()).then(data => {
    if (!data.success || !data.quotes.length){
      el.innerHTML = `<div class="news-loading">${data.error || 'No stock data.'}</div>`;
      return;
    }
    el.innerHTML = data.quotes.map(q => {
      if (q.error) return `<div class="stock-row"><span class="stock-tk">${q.ticker}</span><span class="stock-err">${q.error}</span></div>`;
      const up = (q.change || 0) >= 0;
      const cls = up ? 'up' : 'down';
      const arrow = up ? '▲' : '▼';
      return `<div class="stock-row">
        <span class="stock-tk">${q.ticker}</span>
        <span class="stock-px">$${q.price.toFixed(2)}</span>
        <span class="stock-ch ${cls}">${arrow} ${q.change>=0?'+':''}${q.change.toFixed(2)} (${q.percent>=0?'+':''}${q.percent.toFixed(2)}%)</span>
      </div>`;
    }).join('');
  }).catch(() => { el.innerHTML = '<div class="news-loading">Could not load stocks.</div>'; });
}
loadStocks();
setInterval(loadStocks, 300000);   // every 5 min

/* ---------- load weather ---------- */
function loadWeather(){
  const el = document.getElementById('weatherContainer');
  fetch('/api/weather').then(r => r.json()).then(w => {
    if (!w.success || !w.current){
      el.innerHTML = `<div class="news-loading">${w.error || 'No weather data.'}</div>`;
      return;
    }
    const c = w.current;
    const days = w.forecast.map(f => `
      <div class="wx-day">
        <div class="wx-emoji">${f.emoji}</div>
        <div class="wx-date">${new Date(f.date).toLocaleDateString(undefined,{weekday:'short'})}</div>
        <div class="wx-range">${Math.round(f.min)}° / ${Math.round(f.max)}°</div>
      </div>`).join('');
    el.innerHTML = `
      <div class="wx-now">
        <div class="wx-now-emoji">${c.emoji}</div>
        <div>
          <div class="wx-temp">${Math.round(c.temp)}°C</div>
          <div class="wx-desc">${c.description} · feels ${Math.round(c.feels_like)}°</div>
          <div class="wx-place">${w.place}</div>
        </div>
      </div>
      <div class="wx-forecast">${days}</div>`;
  }).catch(() => { el.innerHTML = '<div class="news-loading">Could not load weather.</div>'; });
}
loadWeather();
setInterval(loadWeather, 1800000);  // every 30 min

/* ---------- load daily briefing ---------- */
// Colors signed percentages (+7.59%, -6.21%, ...) green/red inside a rendered
// element, matching the Market Watch card's .stock-ch.up/.down colors. Walks
// text nodes only (skips code/math) so it can't corrupt markup.
// Claude doesn't always write negative numbers with a plain ASCII hyphen
// (U+002D) — it sometimes uses a typographic minus sign (U+2212) or an en
// dash (U+2013), which is why only the "+" side was matching before. Cover
// every sign character Claude is likely to use.
const SIGN_CHARS = '+\\-\\u2212\\u2013';
// Non-global — used only for a stateless "does this contain a match" test.
const PCT_RE_TEST = new RegExp(`[${SIGN_CHARS}]\\d+(?:\\.\\d+)?%`);
const PCT_RE_FULL = new RegExp(`^([${SIGN_CHARS}])\\d+(?:\\.\\d+)?%$`);
// split() takes its own regex and ignores/resets lastIndex itself, so a
// fresh 'g' instance here (separate from PCT_RE_TEST above) is safe to reuse.
const PCT_RE_SPLIT = new RegExp(`([${SIGN_CHARS}]\\d+(?:\\.\\d+)?%)`, 'g');

function colorizeBriefingNumbers(root){
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(node){
      if (node.parentElement && node.parentElement.closest('pre, code, .eq, .eq-in')) return NodeFilter.FILTER_REJECT;
      return PCT_RE_TEST.test(node.nodeValue) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP;
    }
  });
  const nodes = [];
  let n;
  while ((n = walker.nextNode())) nodes.push(n);
  nodes.forEach(node => {
    const parts = node.nodeValue.split(PCT_RE_SPLIT);
    if (parts.length < 2) return;
    const frag = document.createDocumentFragment();
    parts.forEach(part => {
      const m = part.match(PCT_RE_FULL);
      if (m){
        const span = document.createElement('span');
        span.className = 'pct-' + (m[1] === '+' ? 'up' : 'down');
        span.textContent = part;
        frag.appendChild(span);
      } else if (part){
        frag.appendChild(document.createTextNode(part));
      }
    });
    node.parentNode.replaceChild(frag, node);
  });
}

function loadBriefing(force){
  const body = document.getElementById('briefingBody');
  const foot = document.getElementById('briefingFoot');
  if (force) body.innerHTML = '<div class="news-loading">Regenerating your briefing…</div>';
  fetch('/api/briefing' + (force ? '?force=1' : '')).then(r => r.json()).then(d => {
    if (d.error){
      body.innerHTML = `<div class="news-loading">Briefing unavailable: ${d.error}</div>`;
      foot.textContent = '';
      return;
    }
    body.innerHTML = renderMarkdown(d.briefing || '');
    colorizeBriefingNumbers(body);
    if (window.Prism) setTimeout(() => Prism.highlightAllUnder(body), 0);
    const when = d.generated_at ? new Date(d.generated_at).toLocaleString() : '';
    foot.textContent = (d.cached ? 'Generated ' : 'Just generated ') + when;
  }).catch(() => { body.innerHTML = '<div class="news-loading">Could not load briefing.</div>'; });
}
document.getElementById('briefingRefresh').addEventListener('click', () => loadBriefing(true));
loadBriefing(false);

/* ---------- helpers ---------- */
function bubble(text, who, images, files){
  const d = document.createElement('div');
  d.className = 'msg ' + who;
  // show any attached images at the top of the bubble
  if (images && images.length){
    const gal = document.createElement('div');
    gal.className = 'msg-imgs';
    images.forEach(im => {
      const el = document.createElement('img');
      el.src = `data:${im.media_type};base64,${im.data}`;
      el.className = 'msg-img';
      gal.appendChild(el);
    });
    d.appendChild(gal);
  }
  // show any attached non-image files as small chips
  if (files && files.length){
    const fl = document.createElement('div');
    fl.className = 'msg-files';
    files.forEach(f => {
      const c = document.createElement('span');
      c.className = 'msg-file';
      const ico = f.kind === 'pdf' ? '📄' : (f.kind === 'doc' ? '📎' : (f.kind === 'audio' ? '🎙️' : '📃'));
      c.textContent = ico + ' ' + (f.name || 'file');
      fl.appendChild(c);
    });
    d.appendChild(fl);
  }
  if (who === 'bot'){
    const body = document.createElement('div');
    body.className = 'md';
    body.innerHTML = renderMarkdown(text || '');
    d.appendChild(body);
    // highlight code blocks with Prism (VS Code-like colors)
    if (window.Prism) setTimeout(() => Prism.highlightAllUnder(body), 0);
  } else if (text){
    const span = document.createElement('div');
    span.textContent = text;
    d.appendChild(span);
  }
  return d;
}

/* ---- shared image-attachment helpers ----
   Each "surface" (quick chat / full chat) keeps a small pending[] list of
   {media_type, data} objects. We read files as base64, show thumbnails,
   and let the user remove one before sending.                            */
const MAX_IMG_BYTES   = 5 * 1024 * 1024;    // Claude's 5 MB per-image limit
const MAX_FILE_BYTES  = 30 * 1024 * 1024;   // generous cap for PDFs / Word / Excel / text
const MAX_AUDIO_BYTES = 300 * 1024 * 1024;  // matches agent/transcribe.py's local Whisper cap (was 25MB under the old OpenAI API, raised 2026-07-09)

const AUDIO_EXTENSIONS = ['mp3', 'mp4', 'mpeg', 'mpga', 'm4a', 'wav', 'webm'];

// decide how an attachment should be handled
function classifyFile(file){
  const t = (file.type || '').toLowerCase();
  const n = (file.name || '').toLowerCase();
  if (t.startsWith('image/')) return 'image';
  if (t === 'application/pdf' || n.endsWith('.pdf')) return 'pdf';
  if (n.endsWith('.docx') || t.includes('wordprocessingml')) return 'doc';
  if (n.endsWith('.xlsx') || t.includes('spreadsheetml')) return 'doc';
  if (n.endsWith('.csv') || n.endsWith('.txt') || n.endsWith('.md') ||
      n.endsWith('.json') || n.endsWith('.log') || t.startsWith('text/')) return 'text';
  // Phase 11b: audio/video -> transcribed server-side (agent/transcribe.py)
  if (t.startsWith('audio/') || t.startsWith('video/') ||
      AUDIO_EXTENSIONS.some(ext => n.endsWith('.' + ext))) return 'audio';
  return '';   // unsupported
}

function fileToAttachment(file){
  return new Promise((resolve, reject) => {
    const kind = classifyFile(file);
    if (!kind) return reject((file.name || 'That file') + ' — unsupported type. Try an image, PDF, Word, Excel, text, or audio/video file.');
    const limit = kind === 'image' ? MAX_IMG_BYTES : (kind === 'audio' ? MAX_AUDIO_BYTES : MAX_FILE_BYTES);
    if (file.size > limit) return reject((file.name || 'File') + ' is too large (limit ' + Math.round(limit / (1024 * 1024)) + ' MB).');
    const reader = new FileReader();
    reader.onload = () => {
      const base64 = String(reader.result).split(',')[1] || '';
      resolve({ name: file.name || 'file', media_type: file.type || 'application/octet-stream', data: base64, kind });
    };
    reader.onerror = () => reject('could not read file');
    reader.readAsDataURL(file);
  });
}

/* Build an attachment controller bound to a preview element. */
function makeAttacher(previewEl){
  const pending = [];
  function render(){
    previewEl.innerHTML = '';
    pending.forEach((att, idx) => {
      let chip;
      if (att.kind === 'image'){
        chip = document.createElement('div');
        chip.className = 'thumb';
        const im = document.createElement('img');
        im.src = `data:${att.media_type};base64,${att.data}`;
        chip.appendChild(im);
      } else {
        chip = document.createElement('div');
        chip.className = 'file-chip';
        const ico = document.createElement('span');
        ico.className = 'file-chip-ico';
        ico.textContent = att.kind === 'pdf' ? '📄' : (att.kind === 'doc' ? '📎' : (att.kind === 'audio' ? '🎙️' : '📃'));
        const nm = document.createElement('span');
        nm.className = 'file-chip-name';
        nm.textContent = att.name;
        chip.appendChild(ico); chip.appendChild(nm);
      }
      const x = document.createElement('button');
      x.className = att.kind === 'image' ? 'thumb-x' : 'file-chip-x';
      x.type = 'button'; x.textContent = '×'; x.title = 'Remove';
      x.onclick = () => { pending.splice(idx, 1); render(); };
      chip.appendChild(x);
      previewEl.appendChild(chip);
    });
    previewEl.classList.toggle('has-imgs', pending.length > 0);
  }
  async function addFiles(fileList){
    for (const f of fileList){
      try { pending.push(await fileToAttachment(f)); }
      catch (msg) { alert(typeof msg === 'string' ? msg : 'Could not add that file.'); }
    }
    render();
  }
  return {
    addFiles,
    take(){ const copy = pending.slice(); pending.length = 0; render(); return copy; },
    get count(){ return pending.length; },
  };
}

/* ---- self-contained Markdown renderer (no external library) ----
   Handles: headers, bold, italic, inline code, code fences, links,
   blockquotes, bullet/numbered lists, tables, horizontal rules.    */
function escapeHtml(s){
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
/* Convert a chunk of LaTeX into clean, readable plain text using Unicode.
   No external library — this can never break the layout.                 */
function latexToText(tex){
  let s = tex;
  // common commands → symbols
  const sym = {
    '\\times':'×', '\\cdot':'·', '\\div':'÷', '\\pm':'±', '\\mp':'∓',
    '\\leq':'≤', '\\geq':'≥', '\\neq':'≠', '\\approx':'≈', '\\equiv':'≡',
    '\\infty':'∞', '\\partial':'∂', '\\nabla':'∇', '\\degree':'°', '\\circ':'°',
    '\\alpha':'α','\\beta':'β','\\gamma':'γ','\\delta':'δ','\\theta':'θ',
    '\\lambda':'λ','\\mu':'μ','\\pi':'π','\\rho':'ρ','\\sigma':'σ','\\phi':'φ',
    '\\omega':'ω','\\Delta':'Δ','\\Sigma':'Σ','\\Omega':'Ω',
    '\\rightarrow':'→','\\to':'→','\\leftarrow':'←','\\Rightarrow':'⇒',
    '\\sum':'∑','\\int':'∫','\\sqrt':'√','\\angle':'∠','\\perp':'⊥',
    '\\quad':'  ','\\qquad':'    ','\\,':' ','\\;':' ','\\!':'',
  };
  // \frac{a}{b} → (a)/(b)
  s = s.replace(/\\frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}/g, '($1)/($2)');
  // \sqrt{x} → √(x)
  s = s.replace(/\\sqrt\s*\{([^{}]*)\}/g, '√($1)');
  // \vec{x} → x⃗ (combining arrow), \hat{x} → x̂, \bar{x} → x̄
  s = s.replace(/\\vec\s*\{([^{}]*)\}/g, '$1⃗');
  s = s.replace(/\\hat\s*\{([^{}]*)\}/g, '$1̂');
  s = s.replace(/\\bar\s*\{([^{}]*)\}/g, '$1̄');
  // \text{...} and \mathrm{...} → just the contents
  s = s.replace(/\\(?:text|mathrm|mathbf|operatorname)\s*\{([^{}]*)\}/g, '$1');
  // \left and \right are just sizing hints → drop them, keep the bracket
  s = s.replace(/\\left\s*/g, '').replace(/\\right\s*/g, '');
  // named functions: keep the name as plain text
  s = s.replace(/\\(sin|cos|tan|cot|sec|csc|arcsin|arccos|arctan|sinh|cosh|tanh|log|ln|exp|lim|max|min|det|gcd)\b/g, '$1');
  // remaining named symbols
  for (const k in sym) s = s.split(k).join(sym[k]);
  // superscripts: ^2, ^{10}, ^{-1}  → Unicode where possible
  const sup = {'0':'⁰','1':'¹','2':'²','3':'³','4':'⁴','5':'⁵','6':'⁶','7':'⁷','8':'⁸','9':'⁹','+':'⁺','-':'⁻','=':'⁼','(':'⁽',')':'⁾','n':'ⁿ','i':'ⁱ'};
  const sub = {'0':'₀','1':'₁','2':'₂','3':'₃','4':'₄','5':'₅','6':'₆','7':'₇','8':'₈','9':'₉','+':'₊','-':'₋','=':'₌','(':'₍',')':'₎'};
  const toUni = (str, map) => str.split('').map(c => map[c] || c).join('');
  s = s.replace(/\^\{([^{}]+)\}/g, (_,g)=> /^[0-9+\-=()ni]+$/.test(g) ? toUni(g,sup) : '^('+g+')');
  s = s.replace(/\^(\w)/g, (_,g)=> sup[g] || '^'+g);
  // subscripts: keep as _x / _(xy) since Unicode subscript letters are incomplete
  s = s.replace(/_\{([^{}]+)\}/g, (_,g)=> /^[0-9+\-=()]+$/.test(g) ? toUni(g,sub) : '_'+g);
  s = s.replace(/_(\w)/g, (_,g)=> sub[g] || '_'+g);
  // strip any leftover braces and stray backslash-commands
  s = s.replace(/\\[a-zA-Z]+/g, '').replace(/[{}]/g,'');
  return s.replace(/\s+/g,' ').trim();
}

function inlineMd(s){
  // inline code first (protect its contents), then bold/italic/links
  s = s.replace(/`([^`]+)`/g, (_,c)=>`<code>${escapeHtml(c)}</code>`);
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  s = s.replace(/(^|[^*])\*([^*]+)\*/g, '$1<em>$2</em>');
  s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g,
        '<a href="$2" target="_blank" rel="noopener">$1</a>');
  return s;
}
/* Auto-detect programming language from code content.
   Checks for distinctive keywords/patterns for each language. */
function autoDetectLang(code){
  const s = code.trim();
  // Python — def/import/from/elif/print with colons
  if (/^\s*(def |class |import |from |async def )/m.test(s) ||
      /\belif\b|\bTrue\b|\bFalse\b|\bNone\b/.test(s)) return 'python';
  // JavaScript / TypeScript
  if (/^\s*(const |let |var |function |class |import |export )/m.test(s) ||
      /=>\s*\{|\.then\(|console\.log/.test(s)) return 'javascript';
  // C / C++ / Arduino
  if (/#include\s*[<"]|void setup\(\)|void loop\(\)|int main\s*\(/.test(s) ||
      /std::|cout\s*<<|cin\s*>>/.test(s)) return 'cpp';
  // Java
  if (/public\s+(class|static|void)|System\.out\.print/.test(s)) return 'java';
  // Bash / shell
  if (/^(#!\/bin\/|pip |apt |npm |yarn |cd |ls |echo |export )/m.test(s) ||
      /\$\(|\bsudo\b|\bchmod\b/.test(s)) return 'bash';
  // JSON
  if (/^\s*[\{\[]/.test(s) && /"\s*:\s*/.test(s)) return 'json';
  // CSS
  if (/^\s*[\w.#*:[][\w\s-]*\s*\{/m.test(s) && /:\s*[\w#"'(]/.test(s)) return 'css';
  // HTML/XML
  if (/<\w+[\s>]/.test(s) && /<\/\w+>/.test(s)) return 'html';
  // SQL
  if (/^\s*(SELECT|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER)\b/im.test(s)) return 'sql';
  // default — plain text, no highlighting
  return 'none';
}

function renderMarkdown(src){
  // Convert LaTeX math to readable Unicode text BEFORE Markdown runs, and
  // protect the result from Markdown so its symbols survive untouched.
  // Display math ($$...$$) becomes its own centered-ish line.
  const math = [];
  const stash = (s, block) => {
    const id = math.length;
    math.push(block ? `<div class="eq">${escapeHtml(s)}</div>` : `<span class="eq-in">${escapeHtml(s)}</span>`);
    return `@@MATH${id}@@`;
  };
  src = src.replace(/\$\$([\s\S]+?)\$\$/g, (_, m) => stash(latexToText(m), true));
  src = src.replace(/\\\[([\s\S]+?)\\\]/g, (_, m) => stash(latexToText(m), true));
  src = src.replace(/\$([^$\n]+?)\$/g,     (_, m) => stash(latexToText(m), false));
  src = src.replace(/\\\(([^\n]+?)\\\)/g,  (_, m) => stash(latexToText(m), false));

  const lines = src.replace(/\r\n/g,'\n').split('\n');
  let html = '', i = 0;
  while (i < lines.length){
    let line = lines[i];

    // fenced code block ```lang
    if (/^```/.test(line)){
      let lang = line.replace(/^```/, '').trim().toLowerCase() || '';
      let code = '';
      i++;
      while (i < lines.length && !/^```/.test(lines[i])){ code += lines[i] + '\n'; i++; }
      i++; // skip closing fence
      // auto-detect language if not specified
      if (!lang) lang = autoDetectLang(code);
      const langClass = lang ? ` class="language-${lang}"` : '';
      html += `<pre><code${langClass}>${escapeHtml(code.replace(/\n$/,''))}</code></pre>`;
      continue;
    }
    // horizontal rule
    if (/^\s*---+\s*$/.test(line)){ html += '<hr>'; i++; continue; }
    // headers
    let h = line.match(/^(#{1,3})\s+(.*)$/);
    if (h){ const n=h[1].length; html += `<h${n}>${inlineMd(escapeHtml(h[2]))}</h${n}>`; i++; continue; }
    // blockquote
    if (/^>\s?/.test(line)){
      let q = '';
      while (i < lines.length && /^>\s?/.test(lines[i])){ q += lines[i].replace(/^>\s?/,'') + ' '; i++; }
      html += `<blockquote>${inlineMd(escapeHtml(q.trim()))}</blockquote>`;
      continue;
    }
    // table (a header row followed by a |---| separator)
    if (/\|/.test(line) && i+1 < lines.length && /^\s*\|?[\s:|-]+\|?\s*$/.test(lines[i+1]) && /-/.test(lines[i+1])){
      const splitRow = r => r.replace(/^\s*\|/,'').replace(/\|\s*$/,'').split('|').map(c=>c.trim());
      const head = splitRow(line); i += 2;
      let t = '<table><thead><tr>' + head.map(c=>`<th>${inlineMd(escapeHtml(c))}</th>`).join('') + '</tr></thead><tbody>';
      while (i < lines.length && /\|/.test(lines[i]) && lines[i].trim()!==''){
        const cells = splitRow(lines[i]);
        t += '<tr>' + cells.map(c=>`<td>${inlineMd(escapeHtml(c))}</td>`).join('') + '</tr>';
        i++;
      }
      html += t + '</tbody></table>';
      continue;
    }
    // unordered list
    if (/^\s*[-*]\s+/.test(line)){
      let items = '';
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])){
        items += `<li>${inlineMd(escapeHtml(lines[i].replace(/^\s*[-*]\s+/,'')))}</li>`; i++;
      }
      html += `<ul>${items}</ul>`;
      continue;
    }
    // ordered list
    if (/^\s*\d+\.\s+/.test(line)){
      let items = '';
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])){
        items += `<li>${inlineMd(escapeHtml(lines[i].replace(/^\s*\d+\.\s+/,'')))}</li>`; i++;
      }
      html += `<ol>${items}</ol>`;
      continue;
    }
    // blank line
    if (line.trim()===''){ i++; continue; }
    // paragraph (gather consecutive non-blank, non-special lines)
    let para = '';
    while (i < lines.length && lines[i].trim()!=='' &&
           !/^(#{1,3}\s|>|```|\s*---+\s*$|\s*[-*]\s+|\s*\d+\.\s+)/.test(lines[i]) &&
           !(/\|/.test(lines[i]) && i+1<lines.length && /^\s*\|?[\s:|-]+\|?\s*$/.test(lines[i+1]) && /-/.test(lines[i+1]))){
      para += (para?' ':'') + lines[i]; i++;
    }
    if (para) html += `<p>${inlineMd(escapeHtml(para))}</p>`;
  }
  // restore the protected LaTeX so MathJax can typeset it
  html = html.replace(/@@MATH(\d+)@@/g, (_, n) => math[+n]);
  return html;
}
function typingBubble(){
  const d = document.createElement('div');
  d.className = 'msg bot typing';
  d.innerHTML = '<span></span><span></span><span></span>';
  return d;
}
/* render source citations under a bot bubble (your prompt requires sources) */
function renderCitations(bubbleEl, citations){
  if (!citations || !citations.length) return;
  const wrap = document.createElement('div');
  wrap.className = 'citations';
  const label = document.createElement('div');
  label.className = 'citations-label';
  label.textContent = 'Sources';
  wrap.appendChild(label);
  citations.forEach((c, i) => {
    const a = document.createElement('a');
    a.className = 'citation';
    a.href = c.url; a.target = '_blank'; a.rel = 'noopener';
    a.textContent = `[${i+1}] ${c.title || c.url}`;
    wrap.appendChild(a);
  });
  bubbleEl.appendChild(wrap);
}

/* render a graph the agent asked for, inside a bot bubble */
function renderGraph(holder, graph){
  if (!graph || !graph.type) return;
  const layout = {
    title: graph.title || '',
    paper_bgcolor:'#0F1C29', plot_bgcolor:'#0F1C29',
    font:{ color:'#EAF6F4', family:'Inter' },
    margin:{ l:40, r:20, t:graph.title?40:20, b:40 },
    scene:{ xaxis:{color:'#9FB6C4'}, yaxis:{color:'#9FB6C4'}, zaxis:{color:'#9FB6C4'} }
  };
  let traces = graph.data;
  if (!Array.isArray(traces)) traces = [traces];
  // tint default colours toward the Moss mint if none supplied
  traces.forEach(t => {
    if (!t.marker && !t.line && !t.colorscale){
      t.marker = { color:'#FFFFFF' };
      t.line   = { color:'#FFFFFF' };
    }
  });
  Plotly.newPlot(holder, traces, layout, {displayModeBar:false, responsive:true});
}

/* ===================================================================
   QUICK CHAT (dashboard card)
   =================================================================== */
const qcForm = document.getElementById('qcForm');
const qcInput = document.getElementById('qcInput');
const qcScroll = document.getElementById('qcScroll');
const qcAttacher = makeAttacher(document.getElementById('qcPreview'));
let qcStarted = false;
let qcHistory = [];

// attach button → open file picker; file picker → add images
document.getElementById('qcAttach').addEventListener('click', () => document.getElementById('qcFile').click());
document.getElementById('qcFile').addEventListener('change', e => { qcAttacher.addFiles(e.target.files); e.target.value=''; });
// paste an image directly into the input
qcInput.addEventListener('paste', e => {
  const imgs = [...(e.clipboardData?.items || [])].filter(i => i.type.startsWith('image/'));
  if (imgs.length){ e.preventDefault(); qcAttacher.addFiles(imgs.map(i => i.getAsFile())); }
});

/* ---------- textarea auto-grow + Shift+Enter handling ---------- */
// manualFloorPx: if the user has dragged a textarea taller than its content
// needs (via the drag handle below), autoGrow won't shrink it back below
// that height on the next keystroke — it only grows further if the text
// itself needs more room. Cleared on send so the box returns to compact.
const manualFloorPx = new WeakMap();
function autoGrow(el){
  const floor = manualFloorPx.get(el) || 0;
  el.style.height = 'auto';
  // grow the box to fit the text, up to half the window height, then let it scroll.
  // keep this cap in sync with max-height in the .qc-input,.chat-input CSS rule.
  const maxH = Math.round(window.innerHeight * 0.5);
  const target = Math.max(el.scrollHeight, floor);
  el.style.height = Math.min(target, maxH) + 'px';
}
function addTextareaHandlers(el, formEl){
  el.addEventListener('input', () => autoGrow(el));
  el.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey){
      e.preventDefault();
      formEl.dispatchEvent(new Event('submit', {cancelable:true, bubbles:true}));
    }
    // Shift+Enter → natural newline (default textarea behavior, do nothing)
  });
}

/* Drag-to-resize handle above a textarea (same mousedown/move/up pattern as
   the artifact panel's resizer). Dragging up grows the box; dragging down
   shrinks it, down to a sane minimum. The resulting height becomes a floor
   so typing doesn't immediately snap it back to fit the content. */
function makeInputResizer(handleEl, textareaEl){
  if (!handleEl || !textareaEl) return;
  let dragging = false, startY = 0, startH = 0;
  handleEl.addEventListener('mousedown', (e) => {
    dragging = true; startY = e.clientY; startH = textareaEl.getBoundingClientRect().height;
    document.body.style.cursor = 'row-resize';
    document.body.style.userSelect = 'none';
    e.preventDefault();
  });
  document.addEventListener('mousemove', (e) => {
    if (!dragging) return;
    const maxH = Math.round(window.innerHeight * 0.7);
    let h = startH + (startY - e.clientY);          // drag up → taller
    h = Math.max(44, Math.min(h, maxH));
    textareaEl.style.height = h + 'px';
    manualFloorPx.set(textareaEl, h);
  });
  document.addEventListener('mouseup', () => {
    if (dragging){ dragging = false; document.body.style.cursor = ''; document.body.style.userSelect = ''; }
  });
}
addTextareaHandlers(qcInput, qcForm);

qcForm.addEventListener('submit', async e => {
  e.preventDefault();
  const rawText = qcInput.value.trim();
  const atts = qcAttacher.take();
  const images = atts.filter(a => a.kind === 'image');
  const docs = atts.filter(a => a.kind !== 'image');
  if (!rawText && !atts.length) return;
  const quote = pendingQuote; clearPendingQuote();
  const text = quote ? ('> ' + quote.replace(/\s+/g,' ').trim() + '\n\n' + rawText) : rawText;
  if (!qcStarted){ qcScroll.innerHTML = ''; qcStarted = true; }

  if (quote){
    const qb = document.createElement('div');
    qb.className = 'quote-bubble';
    qb.textContent = quote;
    qcScroll.appendChild(qb);
  }
  qcScroll.appendChild(bubble(rawText, 'user', images, docs));
  qcHistory.push({ role:'user', content:text });
  qcInput.value = '';
  autoGrow(qcInput);
  qcScroll.scrollTop = qcScroll.scrollHeight;

  const typing = typingBubble();
  qcScroll.appendChild(typing);
  qcScroll.scrollTop = qcScroll.scrollHeight;

  const data = await send(text, qcHistory, images, null, docs);
  typing.remove();
  if (data.todos && data.todos.length){ loadTodos(); renderWorkTodos(); }
  if (data.email_result){ showToast((data.email_result.ok ? '✅ ' : '⚠️ ') + data.email_result.message, data.email_result.ok ? '📧' : '⚠️'); }

  const b = bubble(data.reply || '…', 'bot');
  qcScroll.appendChild(b);
  renderCitations(b, data.citations);
  if (data.graph){
    const holder = document.createElement('div');
    holder.className = 'graph-holder';
    b.appendChild(holder);
    renderGraph(holder, data.graph);
  }
  qcHistory.push({ role:'assistant', content:data.reply || '' });
  renderDownloadButtons(b, data.reply || '');
  renderOptions(b, data.options, 'qc');
  qcScroll.scrollTop = qcScroll.scrollHeight;            // autoscroll to newest
});

/* ===================================================================
   FULL CHAT VIEW (with conversation list)
   =================================================================== */
const chatForm = document.getElementById('chatForm');
const chatInput = document.getElementById('chatInput');
const chatScroll = document.getElementById('chatScroll');
const chatListEl = document.getElementById('chatList');
const newChatBtn = document.getElementById('newChat');
const chatAttacher = makeAttacher(document.getElementById('chatPreview'));

// "+" button → small menu (Claude-app style) → "Add files or photos" opens the
// real file picker. Same open/close pattern as the skill/model pickers below.
const chatAttachBtn  = document.getElementById('chatAttach');
const chatAttachMenu = document.getElementById('chatAttachMenu');
chatAttachBtn.addEventListener('click', (e) => { e.stopPropagation(); chatAttachMenu.classList.toggle('hidden'); });
chatAttachMenu.addEventListener('click', e => e.stopPropagation());
document.addEventListener('click', () => chatAttachMenu.classList.add('hidden'));
document.getElementById('chatAttachFilesItem').addEventListener('click', () => {
  chatAttachMenu.classList.add('hidden');
  document.getElementById('chatFile').click();
});
document.getElementById('chatFile').addEventListener('change', e => { chatAttacher.addFiles(e.target.files); e.target.value=''; });
chatInput.addEventListener('paste', e => {
  const imgs = [...(e.clipboardData?.items || [])].filter(i => i.type.startsWith('image/'));
  if (imgs.length){ e.preventDefault(); chatAttacher.addFiles(imgs.map(i => i.getAsFile())); }
});

let conversations = [];   // [{id, title, updated_at}] — metadata only, from server
let activeId = null;
let activeMessages = [];  // messages of the currently open conversation

async function loadConversationList(){
  try{
    const r = await fetch('/api/conversations');
    conversations = await r.json();
  }catch(e){ conversations = []; }
  renderChatList();
}

async function openConversation(id){
  activeId = id;
  renderChatList();
  chatScroll.innerHTML = '<div class="news-loading">Loading conversation…</div>';
  try{
    const r = await fetch(`/api/conversations/${id}`);
    activeMessages = await r.json();
  }catch(e){ activeMessages = []; }
  renderActiveChat();
}

function newConversation(){
  activeId = null;         // server assigns an id on the first message
  activeMessages = [];
  renderChatList();
  renderActiveChat();
}

let openChatMenuId = null;   // which chip's "⋯" menu is currently open, if any

function renderChatList(){
  chatListEl.innerHTML = '';
  conversations.forEach(c => {
    const row = document.createElement('div');
    row.className = 'chat-chip-row' + (c.id === activeId ? ' active' : '');

    const chip = document.createElement('button');
    chip.className = 'chat-chip';
    chip.type = 'button';
    if (c.pinned) {
      const pin = document.createElement('span');
      pin.className = 'chat-chip-pin';
      pin.textContent = '📌';
      chip.appendChild(pin);
    }
    const label = document.createElement('span');
    label.className = 'chat-chip-label';
    label.textContent = c.title;
    chip.appendChild(label);
    chip.onclick = () => openConversation(c.id);

    const moreBtn = document.createElement('button');
    moreBtn.className = 'chat-chip-more';
    moreBtn.type = 'button';
    moreBtn.textContent = '⋯';
    moreBtn.title = 'More';
    moreBtn.onclick = (e) => { e.stopPropagation(); toggleChatMenu(c.id); };

    row.appendChild(chip);
    row.appendChild(moreBtn);

    if (openChatMenuId === c.id){
      row.appendChild(buildChatMenu(c));
    }
    chatListEl.appendChild(row);
  });
}

function toggleChatMenu(id){
  openChatMenuId = (openChatMenuId === id) ? null : id;
  renderChatList();
}
// clicking anywhere else closes any open menu
document.addEventListener('click', () => { if (openChatMenuId !== null){ openChatMenuId = null; renderChatList(); } });

function buildChatMenu(c){
  const menu = document.createElement('div');
  menu.className = 'chat-menu';
  menu.onclick = (e) => e.stopPropagation();   // don't let the document-click closer eat this

  const pinBtn = document.createElement('button');
  pinBtn.className = 'chat-menu-item';
  pinBtn.innerHTML = `<span>📌</span> ${c.pinned ? 'Unpin' : 'Pin to top'}`;
  pinBtn.onclick = async () => {
    try{
      const r = await fetch(`/api/conversations/${c.id}/pin`, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ pinned: !c.pinned })
      });
      if (!r.ok) throw new Error(`Server returned ${r.status}`);
    }catch(err){
      alert('Could not pin/unpin this chat: ' + err.message + '\n\nYour server files may be out of date — try restarting the server.');
    }
    openChatMenuId = null;
    await loadConversationList();
  };

  const renameBtn = document.createElement('button');
  renameBtn.className = 'chat-menu-item';
  renameBtn.innerHTML = `<span>✎</span> Rename`;
  renameBtn.onclick = () => { openChatMenuId = null; startRename(c); };

  const mkExport = (label, fn) => {
    const b = document.createElement('button');
    b.className = 'chat-menu-item';
    b.innerHTML = `<span>⬇</span> ${label}`;
    b.onclick = () => { openChatMenuId = null; renderChatList(); fn(); };
    return b;
  };
  const exportMd  = mkExport('Export as Markdown', () => exportConversation(c));
  const exportDoc = mkExport('Export as Word (.docx)', () => { window.location.href = `/api/conversations/${c.id}/export?format=docx`; });
  const exportPdf = mkExport('Export as PDF', () => { window.location.href = `/api/conversations/${c.id}/export?format=pdf`; });

  const delBtn = document.createElement('button');
  delBtn.className = 'chat-menu-item chat-menu-danger';
  delBtn.innerHTML = `<span>🗑</span> Delete`;
  delBtn.onclick = async () => {
    if (!confirm(`Delete "${c.title}"? This can't be undone.`)) return;
    try{
      const r = await fetch(`/api/conversations/${c.id}`, { method:'DELETE' });
      if (!r.ok) throw new Error(`Server returned ${r.status}`);
    }catch(err){
      alert('Could not delete this chat: ' + err.message + '\n\nYour server files may be out of date — try restarting the server.');
    }
    openChatMenuId = null;
    if (activeId === c.id) newConversation();
    await loadConversationList();
  };

  menu.appendChild(pinBtn);
  menu.appendChild(renameBtn);
  menu.appendChild(exportMd);
  menu.appendChild(exportDoc);
  menu.appendChild(exportPdf);
  menu.appendChild(delBtn);
  return menu;
}

function startRename(c){
  const row = [...chatListEl.children].find((_, i) => conversations[i].id === c.id);
  if (!row) return renderChatList();
  row.innerHTML = '';
  const input = document.createElement('input');
  input.className = 'chat-rename-input';
  input.value = c.title;
  const commit = async () => {
    const val = input.value.trim();
    if (val && val !== c.title){
      await fetch(`/api/conversations/${c.id}/rename`, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ title: val })
      });
    }
    await loadConversationList();
  };
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter'){ e.preventDefault(); input.blur(); }
    if (e.key === 'Escape'){ renderChatList(); }
  });
  input.addEventListener('blur', commit);
  row.appendChild(input);
  input.focus(); input.select();
}

function renderActiveChat(){
  chatScroll.innerHTML = '';
  artifactPanel.classList.add('hidden');   // reset; reopens below only if this chat has one
  activeMessages.forEach(m => {
    if (m.role === 'user' && m.quote){
      const qb = document.createElement('div');
      qb.className = 'quote-bubble';
      qb.textContent = m.quote;
      chatScroll.appendChild(qb);
    }
    const b = bubble(m.content, m.role === 'user' ? 'user' : 'bot', m.images, m.docs);
    chatScroll.appendChild(b);
    if (m.role !== 'user'){
      renderCitations(b, m.citations);
      renderDownloadButtons(b, m.content || '');
      if (m.artifact) renderArtifactChip(b, m.artifact);
      renderOptions(b, m.options, 'chat');
    }
    if (m.graph){
      const holder = document.createElement('div');
      holder.className = 'graph-holder';
      b.appendChild(holder);
      renderGraph(holder, m.graph);
    }
  });
  chatScroll.scrollTop = chatScroll.scrollHeight;
}

newChatBtn.addEventListener('click', newConversation);
addTextareaHandlers(chatInput, chatForm);
makeInputResizer(document.getElementById('chatInputResizer'), chatInput);
loadConversationList();   // populate the sidebar as soon as the page loads

chatForm.addEventListener('submit', async e => {
  e.preventDefault();
  const rawText = chatInput.value.trim();
  const atts = chatAttacher.take();
  const images = atts.filter(a => a.kind === 'image');
  const docs = atts.filter(a => a.kind !== 'image');
  if (!rawText && !atts.length) return;
  const quote = pendingQuote; clearPendingQuote();

  activeMessages.push({ role:'user', content:rawText, quote: quote || null, images, docs });
  chatInput.value = '';
  manualFloorPx.delete(chatInput);   // drop any manual resize so the box goes back to compact
  autoGrow(chatInput);
  renderActiveChat();

  const typing = typingBubble();
  chatScroll.appendChild(typing);
  chatScroll.scrollTop = chatScroll.scrollHeight;

  // fold each user message's quote into the text Wendy sees, as a markdown blockquote
  const hist = activeMessages.map(m => ({
    role: m.role,
    content: (m.role === 'user' && m.quote)
      ? ('> ' + m.quote.replace(/\s+/g,' ').trim() + '\n\n' + m.content)
      : m.content
  }));
  const sendText = quote ? ('> ' + quote.replace(/\s+/g,' ').trim() + '\n\n' + rawText) : rawText;
  const data = await send(sendText, hist, images, activeId, docs);
  typing.remove();
  if (data.todos && data.todos.length){ loadTodos(); renderWorkTodos(); }
  if (data.email_result){ showToast((data.email_result.ok ? '✅ ' : '⚠️ ') + data.email_result.message, data.email_result.ok ? '📧' : '⚠️'); }

  activeMessages.push({ role:'assistant', content:data.reply || '…', graph:data.graph || null, citations:data.citations || [], artifact:data.artifact || null, options:data.options || [] });
  // first message of a brand-new chat → server just created the conversation
  if (!activeId && data.conversation_id){
    activeId = data.conversation_id;
    await loadConversationList();   // pick up the new entry + title in the sidebar
  }
  renderActiveChat();
});

/* ---------- the network call shared by both chat surfaces ---------- */
/* ---------- model picker ----------
   Fetches the real list of available models from the server (so adding a
   model later just means editing MODEL_CATALOG in wendy_agent.py — nothing
   to change here) and lets the user pick which one Wendy uses. Persisted in
   localStorage — this is your own deployed site, not a sandboxed preview,
   so localStorage is safe here.                                            */
let wendyModel = localStorage.getItem('wendyModel') || '';
let modelCatalog = [];

const modelPickerBtn   = document.getElementById('modelPickerBtn');
const modelPickerLabel = document.getElementById('modelPickerLabel');
const modelMenu        = document.getElementById('modelMenu');

async function loadModelCatalog(){
  try{
    const r = await fetch('/api/models');
    const data = await r.json();
    modelCatalog = data.models || [];
    if (!wendyModel || !modelCatalog.some(m => m.id === wendyModel)){
      wendyModel = data.default || (modelCatalog[0] && modelCatalog[0].id) || '';
    }
  }catch(e){ modelCatalog = []; }
  renderModelMenu();
  updateModelPickerLabel();
}

function updateModelPickerLabel(){
  const m = modelCatalog.find(x => x.id === wendyModel);
  modelPickerLabel.textContent = m ? m.label : 'Choose model';
}

function renderModelMenu(){
  modelMenu.innerHTML = '';
  modelCatalog.forEach(m => {
    const opt = document.createElement('div');
    opt.className = 'model-option' + (m.id === wendyModel ? ' selected' : '');
    opt.innerHTML = `
      <div class="model-option-top">
        <span class="model-option-name">${escapeHtml(m.label)}</span>
        <span class="model-usage-badge usage-${(m.usage||'').toLowerCase()}">${escapeHtml(m.usage||'')} usage</span>
      </div>
      <div class="model-option-blurb">${escapeHtml(m.blurb||'')}</div>`;
    opt.addEventListener('click', () => {
      wendyModel = m.id;
      localStorage.setItem('wendyModel', wendyModel);
      updateModelPickerLabel();
      renderModelMenu();
      modelMenu.classList.add('hidden');
    });
    modelMenu.appendChild(opt);
  });
}

modelPickerBtn.addEventListener('click', (e) => {
  e.stopPropagation();
  modelMenu.classList.toggle('hidden');
});
document.addEventListener('click', () => modelMenu.classList.add('hidden'));
modelMenu.addEventListener('click', e => e.stopPropagation());

loadModelCatalog();

/* ---------- skill picker ----------
   Turn on a Wendy "skill" (a saved process like Grill Me / Write a PRD) for the
   conversation. The active skill id rides along with each message and gets
   injected into her system prompt on the server. Pick "Off" to stop. */
let activeSkill = '';
let skillCatalog = [];
const skillPicker      = document.getElementById('skillPicker');
const skillPickerBtn   = document.getElementById('skillPickerBtn');
const skillPickerLabel = document.getElementById('skillPickerLabel');
const skillMenu        = document.getElementById('skillMenu');

async function loadSkills(){
  try{
    const r = await fetch('/api/skills');
    skillCatalog = await r.json();
  }catch(e){ skillCatalog = []; }
  renderSkillMenu();
  updateSkillLabel();
}

function updateSkillLabel(){
  const s = skillCatalog.find(x => x.id === activeSkill);
  skillPickerLabel.textContent = s ? s.name : 'Skills';
  if (skillPicker) skillPicker.classList.toggle('skill-active', !!s);
}

function renderSkillMenu(){
  skillMenu.innerHTML = '';
  const off = document.createElement('div');
  off.className = 'skill-option' + (activeSkill ? '' : ' selected');
  off.innerHTML = `<div class="skill-option-name">Off</div>
      <div class="skill-option-blurb">No skill — normal chat.</div>`;
  off.onclick = () => selectSkill('');
  skillMenu.appendChild(off);

  skillCatalog.forEach(s => {
    const opt = document.createElement('div');
    opt.className = 'skill-option' + (s.id === activeSkill ? ' selected' : '');
    opt.innerHTML = `
      <div class="skill-option-name">${escapeHtml(s.name)}</div>
      <div class="skill-option-blurb">${escapeHtml(s.description || '')}</div>`;
    opt.onclick = () => selectSkill(s.id);
    skillMenu.appendChild(opt);
  });
}

function selectSkill(id){
  activeSkill = id;
  updateSkillLabel();
  renderSkillMenu();
  skillMenu.classList.add('hidden');
}

if (skillPickerBtn){
  skillPickerBtn.addEventListener('click', (e) => { e.stopPropagation(); skillMenu.classList.toggle('hidden'); });
  skillMenu.addEventListener('click', e => e.stopPropagation());
  document.addEventListener('click', () => skillMenu.classList.add('hidden'));
  loadSkills();
}

async function send(message, history, images, conversationId, docs){
  // The browser knows the user's real local time + timezone wherever they are
  // (China, Canada, anywhere) — send it so Wendy resolves "today", "tomorrow",
  // "next Saturday", etc. correctly regardless of where the server is hosted.
  const now = new Date();
  const client_time = now.toLocaleString(undefined, {
    weekday:'long', year:'numeric', month:'long', day:'numeric',
    hour:'2-digit', minute:'2-digit'
  });
  let client_tz = '';
  try { client_tz = Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch(e){}
  try{
    const r = await fetch('/api/chat', {
      method:'POST',
      headers:{ 'Content-Type':'application/json' },
      body: JSON.stringify({ message, history, images: images || [], docs: docs || [], conversation_id: conversationId || null, model: wendyModel, client_time, client_tz, skill: activeSkill || '' })
    });
    return await r.json();
  }catch(err){
    return { reply:'Network error — could not reach the server.', citations:[], graph:null };
  }
}

/* ---------- file download buttons ----------
   After each bot reply, scan for fenced code blocks and offer download.
   Also detects explicit file requests (the word "file", "document", ".py", etc.)
   and extracts the content as a downloadable file.                        */
const FILE_EXT_MAP = {
  python:'py', javascript:'js', js:'js', typescript:'ts', ts:'ts',
  cpp:'cpp', c:'c', java:'java', html:'html', css:'css',
  json:'json', sql:'sql', bash:'sh', shell:'sh', markdown:'md', md:'md',
  txt:'txt', yaml:'yml', toml:'toml', rust:'rs', go:'go',
};

function renderDownloadButtons(bubbleEl, rawText){
  // find all fenced code blocks in the raw text
  const blocks = [];
  const re = /```(\w*)\n([\s\S]*?)```/g;
  let m, idx = 0;
  while ((m = re.exec(rawText)) !== null){
    const lang = m[1].trim().toLowerCase() || 'txt';
    const code = m[2];
    const ext  = FILE_EXT_MAP[lang] || 'txt';
    idx++;
    blocks.push({ lang, code, ext, label: `Download file ${idx > 1 ? idx : ''}(${ext})`.trim() });
  }
  if (!blocks.length) return;

  const bar = document.createElement('div');
  bar.className = 'dl-bar';
  blocks.forEach(b => {
    const btn = document.createElement('button');
    btn.className = 'dl-btn';
    btn.textContent = `⬇ ${b.label}`;
    btn.title = `Download as .${b.ext}`;
    btn.onclick = () => downloadText(b.code, `wendy_output.${b.ext}`);
    bar.appendChild(btn);
  });
  bubbleEl.appendChild(bar);
}

function downloadText(content, filename){
  const blob = new Blob([content], { type:'text/plain' });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

/* ---------- artifact side panel ----------
   Wendy signals a substantial, reusable piece of content (email, document,
   full program, template) with a ```artifact block. Instead of dumping it
   into the chat, we show a small clickable card in the bubble, and the
   full content opens in an editable panel next to the conversation.       */
const artifactPanel  = document.getElementById('artifactPanel');
const artifactEditor = document.getElementById('artifactEditor');
const artifactTitleEl= document.getElementById('artifactTitle');
const artifactBadge  = document.getElementById('artifactTypeBadge');
const artifactStatus = document.getElementById('artifactStatus');

const ARTIFACT_ICONS = { email:'✉️', document:'📄', code:'💻', markdown:'📝', text:'📄' };

function openArtifact(art){
  artifactTitleEl.textContent = art.title || 'Untitled';
  artifactBadge.textContent = (art.type || 'document').replace(/^\w/, c => c.toUpperCase());
  artifactEditor.value = art.content || '';
  artifactEditor.dataset.filename = art.filename || 'wendy_artifact.txt';
  artifactEditor.dataset.title = art.title || 'document';
  // Word/PDF/Excel only make sense for prose/data artifacts, not code files
  const isCode = (art.type || '') === 'code';
  document.querySelectorAll('.artifact-fmt').forEach(b => b.style.display = isCode ? 'none' : '');
  artifactStatus.textContent = 'Editable — changes stay in this panel';
  artifactPanel.classList.remove('hidden');
}
document.getElementById('artifactClose').addEventListener('click', () => {
  artifactPanel.classList.add('hidden');
});
document.getElementById('artifactCopy').addEventListener('click', async () => {
  try{
    await navigator.clipboard.writeText(artifactEditor.value);
    artifactStatus.textContent = 'Copied to clipboard ✓';
    setTimeout(() => artifactStatus.textContent = 'Editable — changes stay in this panel', 1800);
  }catch(e){ artifactStatus.textContent = 'Could not copy — select and copy manually'; }
});
document.getElementById('artifactDownload').addEventListener('click', () => {
  downloadText(artifactEditor.value, artifactEditor.dataset.filename || 'wendy_artifact.txt');
});

/* download the artifact's current content as a real Word / PDF / Excel file */
function artifactSafeName(title){
  return (title || 'document').replace(/[^\w\- ]/g,'').trim().replace(/\s+/g,'_') || 'document';
}
async function downloadArtifactAs(format){
  const title = artifactEditor.dataset.title || artifactTitleEl.textContent || 'document';
  artifactStatus.textContent = 'Building ' + format.toUpperCase() + '…';
  try{
    const r = await fetch('/api/artifact/export', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ title, content: artifactEditor.value, format })
    });
    if (!r.ok){ const j = await r.json().catch(() => ({})); throw new Error(j.error || ('HTTP ' + r.status)); }
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = artifactSafeName(title) + '.' + format;
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    URL.revokeObjectURL(url);
    artifactStatus.textContent = 'Downloaded ' + format.toUpperCase() + ' ✓';
    setTimeout(() => artifactStatus.textContent = 'Editable — changes stay in this panel', 1800);
  }catch(e){
    artifactStatus.textContent = 'Could not export: ' + e.message;
  }
}
document.getElementById('artifactDocx').addEventListener('click', () => downloadArtifactAs('docx'));
document.getElementById('artifactPdf').addEventListener('click', () => downloadArtifactAs('pdf'));
document.getElementById('artifactXlsx').addEventListener('click', () => downloadArtifactAs('xlsx'));

/* ---------- resizable artifact panel ----------
   Drag the handle on the panel's left edge to widen/narrow it, so a PDF or
   document is easier to read. chat-main flexes to fill the rest. */
const artifactResizer = document.getElementById('artifactResizer');
if (artifactResizer){
  let resizing = false;
  artifactResizer.addEventListener('mousedown', (e) => {
    resizing = true;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    e.preventDefault();
  });
  document.addEventListener('mousemove', (e) => {
    if (!resizing) return;
    const layout = document.querySelector('.chat-layout');
    if (!layout) return;
    const rect = layout.getBoundingClientRect();
    let w = rect.right - e.clientX;                 // panel width = mouse → right edge
    const min = 300, max = rect.width - 380;        // keep room for the chat side
    w = Math.max(min, Math.min(w, Math.max(min, max)));
    artifactPanel.style.flex = '0 0 ' + w + 'px';
    artifactPanel.style.width = w + 'px';
  });
  document.addEventListener('mouseup', () => {
    if (resizing){
      resizing = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    }
  });
}

/* ===================================================================
   REMINDERS — while the app is open, check for due reminders and pop a toast.
   The server also emails you (your own address) if email is set up. This is
   the lightweight version: it fires when the app is open/refreshed, not a
   24/7 background service.
   =================================================================== */
function localISO(d){
  const p = n => String(n).padStart(2, '0');
  return d.getFullYear() + '-' + p(d.getMonth()+1) + '-' + p(d.getDate())
       + 'T' + p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds());
}

let toastHost = document.getElementById('toastHost');
if (!toastHost){
  toastHost = document.createElement('div');
  toastHost.id = 'toastHost';
  toastHost.className = 'toast-host';
  document.body.appendChild(toastHost);
}

function showToast(text, icon){
  const t = document.createElement('div');
  t.className = 'toast';
  t.innerHTML = '<span class="toast-ico"></span><span class="toast-text"></span>'
              + '<button class="toast-x" type="button" title="Dismiss">×</button>';
  t.querySelector('.toast-ico').textContent = icon || '⏰';
  t.querySelector('.toast-text').textContent = text;
  t.querySelector('.toast-x').onclick = () => t.remove();
  toastHost.appendChild(t);
  setTimeout(() => t.remove(), 15000);   // auto-dismiss after 15s
}
function showReminderToast(text){ showToast(text, '⏰'); }

async function checkDueReminders(){
  try{
    const r = await fetch('/api/reminders/due', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ now: localISO(new Date()) })
    });
    const data = await r.json();
    (data.due || []).forEach(rem => showReminderToast(rem.text));
  }catch(e){ /* ignore — nothing due or offline */ }
}
checkDueReminders();
setInterval(checkDueReminders, 60000);   // re-check every minute while open

/* the small clickable card that appears inside a bot bubble */
function renderArtifactChip(bubbleEl, art){
  if (!art) return;
  const chip = document.createElement('div');
  chip.className = 'artifact-chip';
  chip.innerHTML = `
    <span class="artifact-chip-icon">${ARTIFACT_ICONS[art.type] || '📄'}</span>
    <span class="artifact-chip-text">
      <div class="artifact-chip-title">${escapeHtml(art.title || 'Untitled')}</div>
      <div class="artifact-chip-sub">${(art.type||'document').replace(/^\w/,c=>c.toUpperCase())} — click to open</div>
    </span>
    <span class="artifact-chip-arrow">→</span>`;
  chip.addEventListener('click', () => openArtifact(art));
  bubbleEl.appendChild(chip);
  // auto-open the newest artifact so the user doesn't have to click for it
  openArtifact(art);
}

/* ===================================================================
   ONGOING WORK (placeholder data — your agent will populate this)
   =================================================================== */
const work = [
  { status:'run',   label:'Running',   title:'Weekly news report', desc:'Compiling engineering & market headlines for Monday.', when:'Updates Mon 8:00' },
  { status:'sched', label:'Scheduled', title:'Send email to Dr. Lee', desc:'Drafted — will send automatically.', when:'Next Fri 9:00' },
  { status:'run',   label:'Running',   title:'Daily email summary', desc:'Summarising unread Gmail each morning.', when:'Daily 7:30' },
  { status:'done',  label:'Done',      title:'Q2 market trend scan', desc:'Flagged 3 favourable trade trends.', when:'Completed today' },
];
const workList = document.getElementById('workList');
work.forEach(w => {
  const el = document.createElement('div');
  el.className = 'work-item';
  el.innerHTML =
    `<span class="work-status ${w.status}">${w.label}</span>
     <div class="work-text"><h3>${w.title}</h3><p>${w.desc}</p></div>
     <span class="work-when">${w.when}</span>`;
  workList.appendChild(el);
});

/* ===================================================================
   CALENDAR (Google-style month grid)
   =================================================================== */
let calDate = new Date();
const sampleEvents = {            // keyed yyyy-m-d ; agent will fill real ones
  // example: '2026-5-24': [{t:'Study session', alt:false}]
};
function renderCalendar(){
  const grid = document.getElementById('calGrid');
  const monthLabel = document.getElementById('calMonth');
  const y = calDate.getFullYear(), m = calDate.getMonth();
  monthLabel.textContent = calDate.toLocaleString('default',{month:'long',year:'numeric'});

  const first = new Date(y, m, 1).getDay();
  const days  = new Date(y, m+1, 0).getDate();
  const prevDays = new Date(y, m, 0).getDate();
  const today = new Date();

  grid.innerHTML = '';
  // leading days from previous month
  for (let i = first-1; i >= 0; i--) addCell(grid, prevDays-i, true);
  // this month
  for (let d = 1; d <= days; d++){
    const isToday = d===today.getDate() && m===today.getMonth() && y===today.getFullYear();
    addCell(grid, d, false, isToday, sampleEvents[`${y}-${m}-${d}`]);
  }
  // trailing to fill grid
  const cells = first + days;
  for (let d = 1; cells + d - 1 < Math.ceil(cells/7)*7; d++) addCell(grid, d, true);
}
function addCell(grid, num, dim, today=false, events){
  const cell = document.createElement('div');
  cell.className = 'cal-cell' + (dim?' dim':'') + (today?' today':'');
  cell.innerHTML = `<span class="cal-num">${num}</span>`;
  (events||[]).forEach(ev => {
    const e = document.createElement('div');
    e.className = 'cal-ev' + (ev.alt?' alt':'');
    e.textContent = ev.t;
    cell.appendChild(e);
  });
  grid.appendChild(cell);
}
document.getElementById('calPrev').onclick  = () => { calDate.setMonth(calDate.getMonth()-1); renderCalendar(); };
document.getElementById('calNext').onclick  = () => { calDate.setMonth(calDate.getMonth()+1); renderCalendar(); };
document.getElementById('calToday').onclick = () => { calDate = new Date(); renderCalendar(); };

/* ---------- memories view ---------- */
const memListEl = document.getElementById('memList');
const memAddForm = document.getElementById('memAddForm');
const memInput = document.getElementById('memInput');
const memCategory = document.getElementById('memCategory');

const MEM_CAT_LABEL = { general:'General', profile:'Profile', preference:'Preference', project:'Project', task:'Task' };

async function loadMemories(){
  memListEl.innerHTML = '<div class="news-loading">Loading memories…</div>';
  try{
    const r = await fetch('/api/memories');
    const mems = await r.json();
    if (!mems.length){
      memListEl.innerHTML = '<div class="news-loading">Nothing saved yet — add one above, or just tell Wendy "remember that…" in chat.</div>';
      return;
    }
    memListEl.innerHTML = '';
    mems.forEach(m => {
      const row = document.createElement('div');
      row.className = 'mem-row';
      row.innerHTML = `
        <span class="mem-tag">${MEM_CAT_LABEL[m.category] || m.category}</span>
        <span class="mem-content">${escapeHtml(m.content)}</span>
        <button class="mem-del" title="Forget this">×</button>`;
      row.querySelector('.mem-del').onclick = async () => {
        await fetch(`/api/memories/${m.id}`, { method:'DELETE' });
        row.remove();
      };
      memListEl.appendChild(row);
    });
  }catch(e){
    memListEl.innerHTML = '<div class="news-loading">Could not load memories.</div>';
  }
}

memAddForm.addEventListener('submit', async e => {
  e.preventDefault();
  const content = memInput.value.trim();
  if (!content) return;
  await fetch('/api/memories', {
    method:'POST',
    headers:{ 'Content-Type':'application/json' },
    body: JSON.stringify({ content, category: memCategory.value })
  });
  memInput.value = '';
  loadMemories();
});

/* ===================================================================
   TO-DO LIST (dashboard "Today's tasks" card — stored in Wendy's own DB)
   No Google Calendar / OAuth needed; add / list / toggle / delete.
   =================================================================== */
const todoForm = document.getElementById('todoForm');
const todoInput = document.getElementById('todoInput');
const todoListEl = document.getElementById('todoList');

async function loadTodos(){
  try{
    const r = await fetch('/api/todos');
    const todos = await r.json();
    if (!todos.length){
      todoListEl.innerHTML = '<div class="qc-empty">No tasks yet — add one above.</div>';
      return;
    }
    todoListEl.innerHTML = '';
    todos.forEach(t => {
      const row = document.createElement('div');
      row.className = 'todo-row' + (t.done ? ' done' : '');

      const box = document.createElement('button');
      box.className = 'todo-check';
      box.type = 'button';
      box.title = t.done ? 'Mark not done' : 'Mark done';
      box.textContent = t.done ? '✓' : '';
      box.onclick = async () => {
        await fetch(`/api/todos/${t.id}/toggle`, {
          method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({ done: !t.done })
        });
        loadTodos();
      };

      const label = document.createElement('span');
      label.className = 'todo-text';
      label.textContent = t.content;

      const del = document.createElement('button');
      del.className = 'todo-del';
      del.type = 'button';
      del.title = 'Delete task';
      del.textContent = '×';
      del.onclick = async () => {
        await fetch(`/api/todos/${t.id}`, { method:'DELETE' });
        loadTodos();
      };

      row.appendChild(box); row.appendChild(label); row.appendChild(del);
      todoListEl.appendChild(row);
    });
  }catch(e){
    todoListEl.innerHTML = '<div class="news-loading">Could not load tasks.</div>';
  }
}

if (todoForm){
  todoForm.addEventListener('submit', async e => {
    e.preventDefault();
    const content = todoInput.value.trim();
    if (!content) return;
    await fetch('/api/todos', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ content })
    });
    todoInput.value = '';
    loadTodos();
  });
  loadTodos();
}

/* Ongoing Work view: show the user's real to-dos ABOVE the placeholder demo
   cards, so the same tasks Wendy adds also surface here. */
async function renderWorkTodos(){
  const el = document.getElementById('workTodos');
  if (!el) return;
  try{
    const r = await fetch('/api/todos');
    const todos = await r.json();
    if (!todos.length){ el.innerHTML = ''; return; }
    const items = todos.map(t => `
      <div class="work-item">
        <span class="work-status ${t.done ? 'done' : 'run'}">${t.done ? 'Done' : 'To do'}</span>
        <div class="work-text"><h3>${escapeHtml(t.content)}</h3></div>
        <span class="work-when">${t.done ? 'Completed' : 'Added ' + String(t.created_at || '').slice(0,10)}</span>
      </div>`).join('');
    el.innerHTML = `<div class="work-todos-head">Your tasks</div>${items}`
                 + `<div class="work-todos-head work-todos-sub">Examples</div>`;
  }catch(e){ el.innerHTML = ''; }
}
renderWorkTodos();

/* ===================================================================
   CONVERSATION SEARCH (keyword search across all past messages)
   Empty box → normal conversation list; typing → grouped results.
   =================================================================== */
const chatSearchInput = document.getElementById('chatSearch');
let chatSearchTimer = null;

async function runChatSearch(q){
  try{
    const r = await fetch('/api/conversations/search?q=' + encodeURIComponent(q));
    const data = await r.json();
    renderSearchResults(data.results || []);
  }catch(e){
    chatListEl.innerHTML = '<div class="news-loading">Search failed.</div>';
  }
}

function renderSearchResults(results){
  chatListEl.innerHTML = '';
  if (!results.length){
    chatListEl.innerHTML = '<div class="qc-empty">No messages match that search.</div>';
    return;
  }
  // group matches by conversation; keep the first (most recent) snippet per chat
  const seen = new Set();
  results.forEach(m => {
    if (seen.has(m.conversation_id)) return;
    seen.add(m.conversation_id);
    const row = document.createElement('button');
    row.className = 'search-result';
    row.type = 'button';
    row.innerHTML = `
      <div class="search-result-title">${escapeHtml(m.title || 'Untitled')}</div>
      <div class="search-result-snippet"><span class="search-result-role">${m.role === 'user' ? 'You' : 'Wendy'}:</span> ${escapeHtml(m.snippet || '')}</div>`;
    row.onclick = () => { chatSearchInput.value = ''; openConversation(m.conversation_id); };
    chatListEl.appendChild(row);
  });
}

if (chatSearchInput){
  chatSearchInput.addEventListener('input', () => {
    const q = chatSearchInput.value.trim();
    clearTimeout(chatSearchTimer);
    if (!q){ renderChatList(); return; }          // empty → restore normal list
    chatSearchTimer = setTimeout(() => runChatSearch(q), 220);   // debounce typing
  });
}

/* ===================================================================
   EXPORT A CONVERSATION AS A DOC (.md) — from the chat ⋯ menu
   Reuses downloadText(); pulls the full thread and formats it.
   =================================================================== */
async function exportConversation(c){
  let msgs = [];
  try{
    const r = await fetch(`/api/conversations/${c.id}`);
    msgs = await r.json();
  }catch(e){ alert('Could not load this conversation to export.'); return; }

  const lines = [`# ${c.title || 'Conversation'}`, ''];
  msgs.forEach(m => {
    const who = m.role === 'user' ? 'You' : 'Wendy';
    lines.push(`## ${who}`);
    lines.push(m.content || '');
    if (m.artifact && m.artifact.content){
      lines.push('');
      lines.push('```');
      lines.push(m.artifact.content);
      lines.push('```');
    }
    lines.push('');
  });

  const safe = (c.title || 'conversation').replace(/[^\w\- ]/g,'').trim().replace(/\s+/g,'_') || 'conversation';
  downloadText(lines.join('\n'), `${safe}.md`);
}

/* ===================================================================
   DATA EXPORT (download a full JSON backup of everything)
   =================================================================== */
const exportAllBtn = document.getElementById('exportAllBtn');
if (exportAllBtn){
  exportAllBtn.addEventListener('click', () => {
    // /api/export streams the file with a Content-Disposition attachment header
    window.location.href = '/api/export';
  });
}

/* ===================================================================
   QUICK-REPLY OPTION BUTTONS
   Wendy offers tappable choices via an ```options block; tapping one sends
   that label as the next message in the same surface (quick chat / full chat).
   =================================================================== */
function renderOptions(bubbleEl, options, surface){
  if (!options || !options.length) return;
  const bar = document.createElement('div');
  bar.className = 'options-bar';
  options.forEach(opt => {
    const btn = document.createElement('button');
    btn.className = 'option-btn';
    btn.type = 'button';
    btn.textContent = opt;
    btn.onclick = () => {
      bar.querySelectorAll('.option-btn').forEach(x => x.disabled = true);
      btn.classList.add('chosen');
      if (surface === 'qc'){
        qcInput.value = opt;
        qcForm.dispatchEvent(new Event('submit', {cancelable:true, bubbles:true}));
      } else {
        chatInput.value = opt;
        chatForm.dispatchEvent(new Event('submit', {cancelable:true, bubbles:true}));
      }
    };
    bar.appendChild(btn);
  });
  bubbleEl.appendChild(bar);
}

/* ===================================================================
   HIGHLIGHT-TO-QUOTE
   Select text in any message → floating "Quote" button → it becomes a
   removable quote chip above the input, then a quote-bubble above your next
   message (and is sent to Wendy as context). Works in both chat surfaces.
   =================================================================== */
let pendingQuote = '';

// build the floating toolbar once
const quoteToolbar = document.createElement('div');
quoteToolbar.className = 'quote-toolbar';
quoteToolbar.style.display = 'none';
quoteToolbar.innerHTML = '<button type="button" class="quote-toolbar-btn">❝ Quote</button>';
document.body.appendChild(quoteToolbar);
const quoteToolbarBtn = quoteToolbar.querySelector('.quote-toolbar-btn');

function hideQuoteToolbar(){ quoteToolbar.style.display = 'none'; }

document.addEventListener('mouseup', (e) => {
  if (quoteToolbar.contains(e.target)) return;      // clicking the toolbar itself
  const sel = window.getSelection();
  const txt = sel ? sel.toString().trim() : '';
  if (!txt){ hideQuoteToolbar(); return; }
  // the selection must start inside a message bubble
  let node = sel.anchorNode, inMsg = false;
  while (node){
    if (node.nodeType === 1 && node.classList && node.classList.contains('msg')){ inMsg = true; break; }
    node = node.parentNode;
  }
  if (!inMsg){ hideQuoteToolbar(); return; }
  const rect = sel.getRangeAt(0).getBoundingClientRect();
  quoteToolbar.dataset.text = txt;
  quoteToolbar.style.display = 'block';
  quoteToolbar.style.top  = Math.max(8, rect.top - 40) + 'px';
  quoteToolbar.style.left = rect.left + 'px';
});

quoteToolbarBtn.addEventListener('click', () => {
  setPendingQuote(quoteToolbar.dataset.text || '');
  hideQuoteToolbar();
  const sel = window.getSelection(); if (sel) sel.removeAllRanges();
});

// hide the toolbar when scrolling any chat region
document.addEventListener('scroll', hideQuoteToolbar, true);

function setPendingQuote(text){ pendingQuote = (text || '').trim(); renderQuoteChips(); }
function clearPendingQuote(){ pendingQuote = ''; renderQuoteChips(); }

function renderQuoteChips(){
  ['qcQuote','chatQuote'].forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    if (!pendingQuote){ el.classList.remove('has-quote'); el.innerHTML = ''; return; }
    el.classList.add('has-quote');
    el.innerHTML = '';
    const chip = document.createElement('div');
    chip.className = 'quote-chip';
    const label = document.createElement('span');
    label.className = 'quote-chip-text';
    label.textContent = pendingQuote;
    const x = document.createElement('button');
    x.className = 'quote-chip-x'; x.type = 'button'; x.textContent = '×'; x.title = 'Remove quote';
    x.onclick = () => clearPendingQuote();
    chip.appendChild(label); chip.appendChild(x);
    el.appendChild(chip);
  });
}