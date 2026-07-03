// 报告页面：知识图谱 + 任务树 + 追问 + 删除 + 选中深入研究
let currentTaskId = null;
let currentSummary = null;

document.addEventListener('DOMContentLoaded', async () => {
  const params = new URLSearchParams(location.search);
  const taskId = params.get('id');
  if (!taskId) {
    document.getElementById('reportContent').innerHTML = '<div class="empty-state">缺少任务ID</div>';
    return;
  }
  currentTaskId = taskId;
  document.getElementById('taskId').textContent = taskId;

  try {
    const task = await apiCall(`/tasks/${taskId}`);
    document.getElementById('taskQuery').textContent = task.query;
    document.getElementById('taskCreated').textContent =
      new Date(task.created_at * 1000).toLocaleString('zh-CN');

    if (task.status !== 'completed') {
      document.getElementById('reportContent').innerHTML =
        `<div class="empty-state">任务${task.status === 'failed' ? '失败' : '尚未完成'}<br>
         <a href="/dashboard">返回控制台</a></div>`;
      return;
    }

    // 并行加载报告、摘要、任务树
    const [md, summary, tree] = await Promise.all([
      fetchReportMd(taskId),
      apiCall(`/tasks/${taskId}/summary`),
      apiCall(`/tasks/${taskId}/tree`).catch(() => null),
    ]);

    document.getElementById('reportContent').innerHTML = renderMarkdown(md);
    currentSummary = summary.data || summary;
    renderGraph(currentSummary);
    if (tree && tree.children && tree.children.length > 0) {
      renderTree(tree);
      document.getElementById('treeCard').style.display = 'block';
    }
  } catch (err) {
    document.getElementById('reportContent').innerHTML =
      `<div class="empty-state">加载失败: ${err.message}</div>`;
  }

  // 绑定追问表单
  const followupForm = document.getElementById('followupForm');
  if (followupForm) {
    followupForm.addEventListener('submit', submitFollowup);
  }

  // 选中文字深入研究
  setupSelectionDeepDive();
});

async function fetchReportMd(taskId) {
  const resp = await fetch(`${API_BASE}/tasks/${taskId}/report`, {
    headers: { 'Authorization': `Bearer ${getToken()}` },
  });
  if (!resp.ok) throw new Error('获取报告失败');
  return await resp.text();
}

// ============ 知识图谱渲染 ============
function renderGraph(summary) {
  const svg = document.getElementById('graphSvg');
  if (!svg || !summary || !summary.nodes) return;
  svg.innerHTML = '';

  const nodes = summary.nodes || [];
  const edges = summary.edges || [];
  if (nodes.length === 0) return;

  const width = svg.clientWidth || 800;
  const height = 400;
  const cx = width / 2, cy = height / 2;
  const radius = Math.min(width, height) * 0.35;

  // 圆形布局
  const positions = {};
  nodes.forEach((n, i) => {
    const angle = (i / nodes.length) * 2 * Math.PI - Math.PI / 2;
    positions[n.id] = {
      x: cx + radius * Math.cos(angle),
      y: cy + radius * Math.sin(angle),
    };
  });

  const svgNS = 'http://www.w3.org/2000/svg';

  // 先画边
  edges.forEach(e => {
    const from = positions[e.from_id], to = positions[e.to_id];
    if (!from || !to) return;
    const line = document.createElementNS(svgNS, 'line');
    line.setAttribute('x1', from.x); line.setAttribute('y1', from.y);
    line.setAttribute('x2', to.x); line.setAttribute('y2', to.y);
    line.setAttribute('class', 'graph-edge-line');
    svg.appendChild(line);

    // 边上的关系标签
    const mid = { x: (from.x + to.x) / 2, y: (from.y + to.y) / 2 };
    const text = document.createElementNS(svgNS, 'text');
    text.setAttribute('x', mid.x); text.setAttribute('y', mid.y);
    text.setAttribute('class', 'graph-edge-text');
    text.textContent = e.relation;
    svg.appendChild(text);
  });

  // 再画节点
  nodes.forEach(n => {
    const pos = positions[n.id];
    const g = document.createElementNS(svgNS, 'g');

    const circle = document.createElementNS(svgNS, 'circle');
    circle.setAttribute('cx', pos.x); circle.setAttribute('cy', pos.y);
    circle.setAttribute('r', 28);
    circle.setAttribute('class', 'graph-node-circle');
    circle.addEventListener('click', () => showNodeDetail(n));
    g.appendChild(circle);

    const text = document.createElementNS(svgNS, 'text');
    text.setAttribute('x', pos.x); text.setAttribute('y', pos.y + 4);
    text.setAttribute('class', 'graph-node-text');
    text.textContent = n.keyword.length > 6 ? n.keyword.slice(0,5) + '…' : n.keyword;
    g.appendChild(text);

    svg.appendChild(g);
  });
}

function showNodeDetail(node) {
  const detail = document.getElementById('nodeDetail');
  if (!detail) return;
  const sources = (node.sources || []).map(s =>
    `<div><a href="${s.url}" target="_blank">${escapeHtml(s.title)}</a></div>`
  ).join('');
  detail.innerHTML = `
    <h4>${escapeHtml(node.keyword)}</h4>
    <p>${escapeHtml(node.summary)}</p>
    ${sources ? `<div class="sources"><strong>来源:</strong>${sources}</div>` : ''}
  `;
}

// ============ 任务树 ============
function renderTree(tree) {
  const container = document.getElementById('treeContainer');
  if (!container) return;
  const root = tree.root;
  const children = tree.children || [];

  const rootDate = new Date(root.created_at * 1000).toLocaleString('zh-CN');
  let html = `
    <div class="tree-node tree-root">
      <strong>主任务:</strong> ${escapeHtml(root.query)}
      <span class="tree-node-status">${statusText(root.status)} · ${rootDate}</span>
    </div>
  `;
  children.forEach(c => {
    const cDate = new Date(c.created_at * 1000).toLocaleString('zh-CN');
    html += `
      <div class="tree-node tree-child">
        <strong>追问:</strong> ${escapeHtml(c.query)}
        <span class="tree-node-status">${statusText(c.status)} · ${cDate}</span>
        ${c.status === 'completed' ? `<button class="btn-ghost" onclick="openReport('${c.id}')">查看</button>` : ''}
      </div>
    `;
  });
  container.innerHTML = html;
}

function statusText(s) {
  return {pending:'等待中', running:'运行中', completed:'已完成', failed:'失败'}[s] || s;
}

// ============ 追问 ============
async function submitFollowup(e) {
  e.preventDefault();
  const query = e.target.query.value.trim();
  if (!query) return showToast('请输入追问问题', 'error');

  const btn = e.target.querySelector('button[type="submit"]');
  btn.disabled = true; btn.textContent = '提交中...';

  try {
    const data = await apiCall('/tasks', {
      method: 'POST',
      body: JSON.stringify({ query, parent_task_id: currentTaskId }),
    });
    showToast('追问已提交，正在生成追加章节', 'success');
    // 跳转到控制台显示进度
    setTimeout(() => {
      window.location.href = `/dashboard?task=${data.task_id}`;
    }, 1000);
  } catch (err) {
    showToast(err.message, 'error');
    btn.disabled = false; btn.textContent = '提交追问';
  }
}

// ============ 删除报告 ============
async function deleteCurrentReport() {
  if (!currentTaskId) return;
  if (!confirm('确认删除该报告及其所有追问任务？此操作不可恢复。')) return;
  try {
    await apiCall(`/tasks/${currentTaskId}`, { method: 'DELETE' });
    showToast('已删除', 'success');
    setTimeout(() => { window.location.href = '/dashboard'; }, 800);
  } catch (err) {
    showToast(err.message, 'error');
  }
}

// ============ 选中文字深入研究 ============
function setupSelectionDeepDive() {
  document.getElementById('reportContent').addEventListener('mouseup', () => {
    const sel = window.getSelection();
    const text = sel.toString().trim();
    if (text.length < 4) return;
    // 显示浮动按钮
    let btn = document.getElementById('deepDiveBtn');
    if (!btn) {
      btn = document.createElement('button');
      btn.id = 'deepDiveBtn';
      btn.className = 'btn-primary';
      btn.textContent = '🔬 深入研究选中内容';
      btn.style.cssText = 'position:fixed;background:var(--primary);color:white;' +
        'padding:8px 14px;border:none;border-radius:8px;cursor:pointer;' +
        'font-size:13px;z-index:1000;box-shadow:0 4px 12px rgba(0,0,0,0.15);';
      btn.addEventListener('click', () => {
        const t = btn.dataset.text;
        btn.remove();
        if (t && t.length > 4) {
          // 作为追问提交
          apiCall('/tasks', {
            method: 'POST',
            body: JSON.stringify({
              query: `深入研究以下内容: ${t}`,
              parent_task_id: currentTaskId,
            }),
          }).then(d => {
            showToast('已基于选中内容启动深入研究', 'success');
            setTimeout(() => {
              window.location.href = `/dashboard?task=${d.task_id}`;
            }, 800);
          }).catch(err => showToast(err.message, 'error'));
        }
      });
      document.body.appendChild(btn);
    }
    btn.dataset.text = text;
    const range = sel.getRangeAt(0).getBoundingClientRect();
    btn.style.top = (range.top - 40) + 'px';
    btn.style.left = (range.left + range.width / 2 - 100) + 'px';
  });
}

// ============ 下载与Markdown渲染 ============
async function downloadReport() {
  if (!currentTaskId) return;
  try {
    const resp = await fetch(`${API_BASE}/tasks/${currentTaskId}/report`, {
      headers: { 'Authorization': `Bearer ${getToken()}` },
    });
    if (!resp.ok) throw new Error('下载失败');
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `report_${currentTaskId.slice(0,8)}.md`;
    a.click();
    URL.revokeObjectURL(url);
  } catch (err) {
    showToast(err.message, 'error');
  }
}

function renderMarkdown(md) {
  let html = md;
  html = html.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (m, lang, code) =>
    `<pre><code>${code.trim()}</code></pre>`);
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
  html = html.replace(/^###### (.+)$/gm, '<h6>$1</h6>');
  html = html.replace(/^##### (.+)$/gm, '<h5>$1</h5>');
  html = html.replace(/^#### (.+)$/gm, '<h4>$1</h4>');
  html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
  html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');
  html = html.replace(/^---$/gm, '<hr>');
  html = html.replace(/^&gt; (.+)$/gm, '<blockquote>$1</blockquote>');
  html = html.replace(/^\|(.+)\|\n\|[-:\s|]+\|\n((?:\|.+\|\n?)+)/gm, (m, header, rows) => {
    const hCells = header.split('|').map(c => c.trim()).filter(c => c);
    const hHtml = hCells.map(c => `<th>${c}</th>`).join('');
    const rHtml = rows.trim().split('\n').map(row => {
      const cells = row.split('|').map(c => c.trim()).filter(c => c);
      return '<tr>' + cells.map(c => `<td>${c}</td>`).join('') + '</tr>';
    }).join('');
    return `<table><thead><tr>${hHtml}</tr></thead><tbody>${rHtml}</tbody></table>`;
  });
  html = html.replace(/^[-*] (.+)$/gm, '<li>$1</li>');
  html = html.replace(/(<li>.*<\/li>\n?)+/g, m => `<ul>${m}</ul>`);
  html = html.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');
  html = html.replace(/(<li>.*<\/li>\n?)+/g, m => m.startsWith('<ul>') ? m : `<ol>${m}</ol>`);
  html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>');
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
  html = html.replace(/^(?!<[a-z])(.+)$/gm, '<p>$1</p>');
  html = html.replace(/\n{2,}/g, '\n');
  return html;
}

function escapeHtml(s) {
  const div = document.createElement('div');
  div.textContent = s;
  return div.innerHTML;
}
