// 控制台逻辑：提交任务、WebSocket进度、历史列表
let currentTaskId = null;
let wsConnection = null;

const AGENT_STEPS = ['planner', 'search', 'summary', 'write'];
const STEP_NAMES = {
  planner: 'Planner 提取关键词',
  search: 'Search 多轮搜索',
  summary: 'Summary CoT清洗',
  write: 'Write 生成报告',
};

document.addEventListener('DOMContentLoaded', () => {
  // 设置表单
  const taskForm = document.getElementById('taskForm');
  if (taskForm) {
    taskForm.addEventListener('submit', submitTask);
  }

  // 加载历史任务
  loadHistory();

  // 处理 ?task=xxx 参数：来自报告页追问提交后的跳转
  const params = new URLSearchParams(location.search);
  const taskParam = params.get('task');
  if (taskParam) {
    reopenTask(taskParam);
  }
});

async function submitTask(e) {
  e.preventDefault();
  const form = e.target;
  const query = form.query.value.trim();
  if (!query) return showToast('请输入研究问题', 'error');

  const btn = document.getElementById('submitBtn');
  btn.disabled = true;
  btn.textContent = '提交中...';

  try {
    const data = await apiCall('/tasks', {
      method: 'POST',
      body: JSON.stringify({ query }),
    });
    currentTaskId = data.task_id;
    showToast('任务已提交', 'success');

    // 显示进度卡片
    document.getElementById('progressCard').style.display = 'block';
    document.getElementById('resultActions').style.display = 'none';
    resetPipeline();
    addEvent('任务已提交，开始执行...', 'info');

    // 连接WebSocket
    connectWebSocket(data.task_id);

    btn.disabled = false;
    btn.textContent = '开始研究';
    form.query.value = '';
  } catch (err) {
    showToast(err.message, 'error');
    btn.disabled = false;
    btn.textContent = '开始研究';
  }
}

function resetPipeline() {
  AGENT_STEPS.forEach(step => {
    const node = document.querySelector(`.agent-node[data-agent="${step}"]`);
    if (node) {
      node.classList.remove('active', 'done');
    }
  });
  updateProgress(0, '等待中...');
  document.getElementById('eventLog').innerHTML = '';
}

function setAgentActive(step) {
  AGENT_STEPS.forEach(s => {
    const node = document.querySelector(`.agent-node[data-agent="${s}"]`);
    if (!node) return;
    if (s === step) {
      node.classList.add('active');
      node.classList.remove('done');
    } else if (AGENTS_BEFORE(s, step)) {
      node.classList.add('done');
      node.classList.remove('active');
    }
  });
}

function AGENTS_BEFORE(a, b) {
  return AGENT_STEPS.indexOf(a) < AGENT_STEPS.indexOf(b);
}

function setAllDone() {
  AGENT_STEPS.forEach(s => {
    const node = document.querySelector(`.agent-node[data-agent="${s}"]`);
    if (node) {
      node.classList.add('done');
      node.classList.remove('active');
    }
  });
}

function updateProgress(percent, text) {
  document.getElementById('progressBar').style.width = percent + '%';
  document.getElementById('progressPercent').textContent = percent + '%';
  document.getElementById('progressText').textContent = text;
}

function addEvent(message, type = 'info') {
  const log = document.getElementById('eventLog');
  if (!log) return;
  const item = document.createElement('div');
  item.className = `event-item event-${type}`;
  const time = new Date().toLocaleTimeString('zh-CN');
  item.textContent = `[${time}] ${message}`;
  log.appendChild(item);
  log.scrollTop = log.scrollHeight;
}

function connectWebSocket(taskId) {
  if (wsConnection) wsConnection.close();

  const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
  const wsUrl = `${protocol}://${location.host}/api/v1/ws/tasks/${taskId}`;
  wsConnection = new WebSocket(wsUrl);

  wsConnection.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    handleWSMessage(msg);
  };

  wsConnection.onerror = () => {
    addEvent('WebSocket连接异常', 'error');
  };

  wsConnection.onclose = () => {
    addEvent('WebSocket已断开', 'info');
  };
}

function handleWSMessage(msg) {
  switch (msg.type) {
    case 'status':
      if (msg.current_step && msg.current_step !== 'done') {
        setAgentActive(msg.current_step);
      }
      updateProgress(msg.progress || 0, STEP_NAMES[msg.current_step] || msg.status);
      break;

    case 'step':
      setAgentActive(msg.step);
      updateProgress(msg.progress || 0, msg.message);
      addEvent(msg.message, 'info');
      break;

    case 'search_round':
      const tag = msg.is_deep ? '[深度]' : '[基础]';
      addEvent(`${tag} 搜索 "${msg.query}" → ${msg.count}条结果`, 'search');
      break;

    case 'data':
      if (msg.step === 'planner') {
        const kws = (msg.data.keywords || []).join(', ');
        addEvent(`关键词: ${kws}`, 'data');
      } else if (msg.step === 'summary') {
        const nodeCount = (msg.data.nodes || []).length;
        const filtered = msg.data.filtering_log?.removed_count || 0;
        addEvent(`生成${nodeCount}个知识节点，CoT过滤${filtered}条无效信息`, 'data');
      }
      break;

    case 'complete':
      setAllDone();
      updateProgress(100, '研究完成');
      addEvent(msg.message, 'complete');
      document.getElementById('resultActions').style.display = 'flex';
      loadHistory();
      break;

    case 'error':
      addEvent(msg.message, 'error');
      showToast(msg.message, 'error');
      break;
  }
}

async function loadHistory() {
  const container = document.getElementById('taskHistory');
  if (!container) return;

  try {
    const data = await apiCall('/tasks');
    if (!data.tasks || data.tasks.length === 0) {
      container.innerHTML = '<div class="empty-state">暂无历史任务</div>';
      return;
    }

    container.innerHTML = data.tasks.map(t => {
      const date = new Date(t.created_at * 1000).toLocaleString('zh-CN');
      const statusClass = `status-${t.status}`;
      const statusText = {pending: '等待中', running: '运行中', completed: '已完成', failed: '失败'}[t.status] || t.status;
      const viewBtn = t.status === 'completed'
        ? `<button class="btn-ghost" onclick="openReport('${t.id}')">查看报告</button>`
        : `<button class="btn-ghost" onclick="reopenTask('${t.id}')">继续查看</button>`;
      return `
        <div class="task-item">
          <div class="task-info">
            <div class="task-query">${escapeHtml(t.query)}</div>
            <div class="task-meta">
              <span class="status-badge ${statusClass}">${statusText}</span>
              <span>${date}</span>
              <span>进度: ${t.progress || 0}%</span>
            </div>
          </div>
          <div class="task-actions">
            ${viewBtn}
          </div>
        </div>
      `;
    }).join('');
  } catch (err) {
    container.innerHTML = `<div class="empty-state">加载失败: ${err.message}</div>`;
  }
}

function reopenTask(taskId) {
  currentTaskId = taskId;
  document.getElementById('progressCard').style.display = 'block';
  document.getElementById('resultActions').style.display = 'none';
  resetPipeline();
  addEvent('重新连接任务...', 'info');
  connectWebSocket(taskId);
  document.getElementById('progressCard').scrollIntoView({behavior: 'smooth'});
}

function viewReport() {
  if (currentTaskId) openReport(currentTaskId);
}

function openReport(taskId) {
  window.location.href = `/report?id=${taskId}`;
}

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

function escapeHtml(s) {
  const div = document.createElement('div');
  div.textContent = s;
  return div.innerHTML;
}
