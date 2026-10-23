const $ = (selector) => document.querySelector(selector);
const state = { projects: [], mode: 'ui' };

function showNotice(message) {
  const element = $('#notice');
  element.textContent = message;
  element.hidden = !message;
}

async function api(path) {
  const response = await fetch(path);
  const data = await response.json();
  if (!response.ok) throw new Error((data.warnings || ['请求失败']).join('; '));
  return data;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (character) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
  }[character]));
}

function projectQuery() {
  const value = $('#project').value.trim();
  return value ? `&project_id=${encodeURIComponent(value)}` : '';
}

function render(items) {
  const root = $('#results');
  if (!items.length) {
    root.innerHTML = '<div class="notice">没有找到已索引资产。请先运行 <code>atlas index</code>，或降低筛选条件。</div>';
    return;
  }
  root.innerHTML = items.map((item) => {
    const features = item.features || [];
    const screenshot = item.screenshot_status === 'available';
    const thumbnail = screenshot
      ? `<img src="${escapeHtml(item.screenshot_url || `/assets/${encodeURIComponent(item.asset_id)}`)}" alt="${escapeHtml(item.name || 'UI 截图')}" loading="lazy">`
      : '<div class="thumb-placeholder">未采集截图 · 静态资产</div>';
    return `<article class="card">
      <div class="thumb ${screenshot ? 'available' : ''}">${thumbnail}</div>
      <div class="card-body">
        <h3>${escapeHtml(item.name || item.relative_path || '未命名资产')}</h3>
        <div class="meta">${escapeHtml(item.project_name || item.project_id || '')}<br>${escapeHtml(item.relative_path || '')}</div>
        <div class="tags">${features.map((feature) => `<span class="tag">${escapeHtml(feature)}</span>`).join('') || '<span class="tag">源码映射</span>'}</div>
        <div class="card-actions"><button class="link" data-detail="${escapeHtml(item.asset_id || '')}">查看详情 →</button><span class="meta">${escapeHtml(item.confidence || 'inferred')}</span></div>
      </div>
    </article>`;
  }).join('');
  root.querySelectorAll('[data-detail]').forEach((button) => button.addEventListener('click', () => openDetail(button.dataset.detail)));
}

async function loadProjects() {
  const data = await api('/api/projects?limit=50');
  state.projects = data.results || [];
  $('#projectCount').textContent = state.projects.length;
  $('#project').insertAdjacentHTML('beforeend', state.projects.map((project) => `<option value="${escapeHtml(project.project_id)}">${escapeHtml(project.name)}</option>`).join(''));
}

async function search(mode = 'ui') {
  state.mode = mode;
  const query = encodeURIComponent($('#query').value);
  showNotice('正在查询本地索引…');
  try {
    const suffix = projectQuery();
    const data = mode === 'ui'
      ? await api(`/api/ui?q=${query}${suffix}&limit=24`)
      : await api(`/api/search?q=${query}${suffix}&limit=24`);
    render(data.results || []);
    showNotice((data.warnings || []).join(' · '));
  } catch (error) {
    render([]);
    showNotice(error.message);
  }
}

async function copyPrompt(prompt, button) {
  try {
    await navigator.clipboard.writeText(prompt);
  } catch (error) {
    const helper = document.createElement('textarea');
    helper.value = prompt;
    helper.setAttribute('readonly', '');
    helper.style.position = 'fixed';
    helper.style.opacity = '0';
    document.body.appendChild(helper);
    helper.select();
    const copied = document.execCommand('copy');
    helper.remove();
    if (!copied) throw error;
  }
  button.textContent = '已复制';
  button.dataset.copied = 'true';
  window.setTimeout(() => { button.textContent = '复制参考提示词'; button.dataset.copied = 'false'; }, 1800);
}

async function openDetail(id) {
  try {
    const data = await api(`/api/ui/${encodeURIComponent(id)}`);
    const asset = data.asset;
    const screenshot = asset.screenshot_status === 'available'
      ? `<img class="detail-image" src="${escapeHtml(asset.screenshot_url || `/assets/${encodeURIComponent(asset.asset_id)}`)}" alt="${escapeHtml(asset.name)} 截图">`
      : '<div class="detail-placeholder">未采集截图；当前只展示源码映射</div>';
    $('#detailBody').innerHTML = `<h2>${escapeHtml(asset.name)}</h2>
      <p class="sub">${escapeHtml(asset.project_name)} · ${escapeHtml(asset.relative_path)}</p>
      ${screenshot}
      <div class="detail-block"><strong>截图状态：</strong>${escapeHtml(asset.screenshot_status)}<br><strong>特征：</strong>${escapeHtml((asset.features || []).join('、') || '未识别')}<br><strong>源码：</strong>${escapeHtml(asset.relative_path)} 行 ${asset.start_line}-${asset.end_line}<br><strong>可信度：</strong>${escapeHtml(asset.confidence)}</div>
      <div class="detail-block"><strong>Agent 参考提示词</strong><p>${escapeHtml(asset.reference_prompt)}</p><button class="primary copy-prompt" id="copyPrompt" type="button">复制参考提示词</button><span class="copy-status" aria-live="polite"></span></div>`;
    const button = $('#copyPrompt');
    button.addEventListener('click', () => copyPrompt(asset.reference_prompt, button));
    $('#detail').showModal();
  } catch (error) {
    showNotice(error.message);
  }
}

$('#search').addEventListener('click', () => search('ui'));
$('#code').addEventListener('click', () => search('code'));
$('#project').addEventListener('change', () => search(state.mode));
$('#close').addEventListener('click', () => $('#detail').close());
$('#theme').addEventListener('click', () => document.documentElement.classList.toggle('light'));
loadProjects().then(() => search('ui')).catch((error) => showNotice(error.message));
