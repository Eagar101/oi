// 文档问答页：文档库 + RAG 问答
let selectedDocs = new Set();

document.addEventListener('DOMContentLoaded', () => {
  loadDocuments();
  document.getElementById('fileInput').addEventListener('change', uploadFiles);
  document.getElementById('chatForm').addEventListener('submit', submitChat);
  // textarea 自适应高度
  const ta = document.querySelector('#chatForm textarea');
  ta.addEventListener('input', () => {
    ta.style.height = 'auto';
    ta.style.height = Math.min(ta.scrollHeight, 160) + 'px';
  });
});

async function loadDocuments() {
  const container = document.getElementById('docList');
  try {
    const data = await apiCall('/documents');
    if (!data.documents || data.documents.length === 0) {
      container.innerHTML = '<div class="empty-state">暂无文档</div>';
      return;
    }
    container.innerHTML = data.documents.map(d => {
      const size = (d.char_count / 1000).toFixed(1) + 'k字';
      const checked = selectedDocs.has(d.id) ? 'checked' : '';
      return `
        <div class="doc-item">
          <label>
            <input type="checkbox" value="${d.id}" ${checked}
              onchange="toggleDoc(${d.id}, this.checked)">
            <span class="doc-name" title="${escapeHtml(d.filename)}">${escapeHtml(d.filename)}</span>
          </label>
          <div class="doc-meta">
            <span>${size} · ${d.chunk_count}片</span>
            <button class="btn-ghost btn-xs" onclick="deleteDoc(${d.id})">删</button>
          </div>
        </div>
      `;
    }).join('');
  } catch (err) {
    container.innerHTML = `<div class="empty-state">加载失败: ${err.message}</div>`;
  }
}

function toggleDoc(id, checked) {
  if (checked) selectedDocs.add(id);
  else selectedDocs.delete(id);
}

async function uploadFiles(e) {
  const files = Array.from(e.target.files);
  if (!files.length) return;
  for (const file of files) {
    const formData = new FormData();
    formData.append('file', file);
    try {
      const resp = await fetch(`${API_BASE}/documents/upload`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${getToken()}` },
        body: formData,
      });
      if (resp.status === 401) {
        clearToken(); window.location.href = '/login'; return;
      }
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || '上传失败');
      showToast(`${file.name} 上传成功（${data.chunk_count}片）`, 'success');
    } catch (err) {
      showToast(`${file.name} 上传失败: ${err.message}`, 'error');
    }
  }
  e.target.value = '';
  loadDocuments();
}

async function deleteDoc(id) {
  if (!confirm('确认删除该文档？')) return;
  try {
    await apiCall(`/documents/${id}`, { method: 'DELETE' });
    selectedDocs.delete(id);
    showToast('已删除', 'success');
    loadDocuments();
  } catch (err) {
    showToast(err.message, 'error');
  }
}

function appendMessage(role, text, sources = []) {
  const list = document.getElementById('messageList');
  // 清空空状态
  if (list.querySelector('.empty-state')) list.innerHTML = '';

  const msg = document.createElement('div');
  msg.className = `message message-${role}`;

  const avatar = role === 'user' ? '🧑' : '🤖';
  let sourcesHtml = '';
  if (sources.length) {
    sourcesHtml = `<div class="message-sources">
      <details><summary>📎 来源 (${sources.length})</summary>
      ${sources.map(s => `
        <div class="source-item">
          <div class="source-name">${escapeHtml(s.filename)} · 相似度 ${(s.score * 100).toFixed(1)}%</div>
          <div class="source-snippet">${escapeHtml(s.snippet)}</div>
        </div>`).join('')}
      </details></div>`;
  }

  msg.innerHTML = `
    <div class="message-avatar">${avatar}</div>
    <div class="message-body">
      <div class="message-text">${role === 'user' ? escapeHtml(text).replace(/\n/g, '<br>') : renderMarkdown(text)}</div>
      ${sourcesHtml}
    </div>
  `;
  list.appendChild(msg);
  list.scrollTop = list.scrollHeight;
}

async function submitChat(e) {
  e.preventDefault();
  const question = e.target.question.value.trim();
  if (!question) return;

  appendMessage('user', question);
  e.target.question.value = '';
  e.target.question.style.height = 'auto';

  const btn = document.getElementById('sendBtn');
  btn.disabled = true; btn.textContent = '思考中...';

  // 占位回答
  const list = document.getElementById('messageList');
  const placeholder = document.createElement('div');
  placeholder.className = 'message message-assistant';
  placeholder.innerHTML = `
    <div class="message-avatar">🤖</div>
    <div class="message-body"><div class="message-text">检索文档中...</div></div>`;
  list.appendChild(placeholder);
  list.scrollTop = list.scrollHeight;

  try {
    const docIds = selectedDocs.size ? Array.from(selectedDocs) : null;
    const data = await apiCall('/chat', {
      method: 'POST',
      body: JSON.stringify({ question, document_ids: docIds }),
    });
    placeholder.remove();
    appendMessage('assistant', data.answer, data.sources || []);
  } catch (err) {
    placeholder.remove();
    appendMessage('assistant', `❌ ${err.message}`);
  } finally {
    btn.disabled = false; btn.textContent = '发送';
  }
}
