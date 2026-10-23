const $ = (s) => document.querySelector(s);
const state = { projects: [], mode: 'ui' };
function showNotice(message) { const el = $('#notice'); el.textContent = message; el.hidden = !message; }
async function api(path) { const response = await fetch(path); const data = await response.json(); if (!response.ok) throw new Error((data.warnings || ['请求失败']).join('; ')); return data; }
function render(items) {
  const root = $('#results');
  if (!items.length) { root.innerHTML = '<div class="notice">没有找到已索引资产。请先运行 <code>atlas index</code>，或降低筛选条件。</div>'; return; }
  root.innerHTML = items.map(item => {
    const features = item.features || [];
    const shot = item.screenshot_status === 'available';
    return `<article class="card"><div class="thumb ${shot ? 'available' : ''}">${shot ? '真实截图已导入' : '未采集截图 · 静态资产'}</div><div class="card-body"><h3>${escapeHtml(item.name || item.relative_path || '未命名资产')}</h3><div class="meta">${escapeHtml(item.project_name || item.project_id || '')}<br>${escapeHtml(item.relative_path || '')}</div><div class="tags">${features.map(x => `<span class="tag">${escapeHtml(x)}</span>`).join('') || '<span class="tag">源码映射</span>'}</div><div class="card-actions"><button class="link" data-detail="${escapeHtml(item.asset_id || '')}">查看详情 →</button><span class="meta">${escapeHtml(item.confidence || 'inferred')}</span></div></div></article>`;
  }).join('');
  root.querySelectorAll('[data-detail]').forEach(btn => btn.addEventListener('click', () => openDetail(btn.dataset.detail)));
}
function escapeHtml(value) { return String(value).replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c])); }
async function loadProjects() { const data = await api('/api/projects?limit=50'); state.projects = data.results || []; $('#projectCount').textContent = state.projects.length; $('#project').insertAdjacentHTML('beforeend', state.projects.map(p => `<option value="${p.project_id}">${escapeHtml(p.name)}</option>`).join('')); }
async function search(mode='ui') { state.mode = mode; const q = encodeURIComponent($('#query').value); const project = encodeURIComponent($('#project').value); showNotice('正在查询本地索引…'); try { const data = mode === 'ui' ? await api(`/api/ui?q=${q}&project_id=${project}&limit=24`) : await api(`/api/search?q=${q}&project_id=${project}&limit=24`); render(data.results || []); showNotice((data.warnings || []).join(' · ')); } catch (error) { render([]); showNotice(error.message); } }
async function openDetail(id) { try { const data = await api(`/api/ui/${encodeURIComponent(id)}`); const a = data.asset; $('#detailBody').innerHTML = `<h2>${escapeHtml(a.name)}</h2><p class="sub">${escapeHtml(a.project_name)} · ${escapeHtml(a.relative_path)}</p><div class="detail-block"><strong>截图状态：</strong>${escapeHtml(a.screenshot_status)}<br><strong>特征：</strong>${escapeHtml((a.features || []).join('、') || '未识别')}<br><strong>源码：</strong>${escapeHtml(a.relative_path)} 行 ${a.start_line}-${a.end_line}<br><strong>可信度：</strong>${escapeHtml(a.confidence)}</div><div class="detail-block"><strong>Agent 参考提示词</strong><p>${escapeHtml(a.reference_prompt)}</p></div>`; $('#detail').showModal(); } catch (error) { showNotice(error.message); } }
$('#search').addEventListener('click', () => search('ui')); $('#code').addEventListener('click', () => search('code')); $('#close').addEventListener('click', () => $('#detail').close()); $('#theme').addEventListener('click', () => document.documentElement.classList.toggle('light')); loadProjects().then(() => search('ui')).catch(error => showNotice(error.message));

