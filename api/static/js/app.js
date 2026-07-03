// 全局工具函数
const API_BASE = '/api/v1';

function getToken() {
  return localStorage.getItem('token') || getCookie('token');
}

function setToken(token) {
  localStorage.setItem('token', token);
  document.cookie = `token=${token}; path=/; max-age=86400; SameSite=Lax`;
}

function clearToken() {
  localStorage.removeItem('token');
  document.cookie = 'token=; path=/; max-age=0';
}

function getCookie(name) {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) return parts.pop().split(';').shift();
  return null;
}

function showToast(message, type = 'info') {
  const toast = document.getElementById('toast');
  if (!toast) return;
  toast.textContent = message;
  toast.className = `toast show ${type}`;
  setTimeout(() => { toast.className = 'toast'; }, 3000);
}

async function apiCall(path, options = {}) {
  const token = getToken();
  const headers = {
    'Content-Type': 'application/json',
    ...(options.headers || {}),
  };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const resp = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });

  if (resp.status === 401) {
    clearToken();
    window.location.href = '/login';
    throw new Error('未登录或登录已过期');
  }

  const data = await resp.json();
  if (!resp.ok) {
    throw new Error(data.detail || `请求失败 (${resp.status})`);
  }
  return data;
}

function logout() {
  clearToken();
  window.location.href = '/login';
}

// 页面加载完成后初始化认证表单（登录/注册页通用，所有页面都加载app.js）
document.addEventListener('DOMContentLoaded', () => {
  setupAuthForm('loginForm', '/auth/login', '/dashboard');
  setupAuthForm('registerForm', '/auth/register', '/dashboard');
});

// 表单提交处理（登录/注册）
function setupAuthForm(formId, endpoint, successRedirect) {
  const form = document.getElementById(formId);
  if (!form) return;

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const formData = new FormData(form);
    const body = Object.fromEntries(formData.entries());

    // 注册时校验密码一致
    if (body.password2 && body.password !== body.password2) {
      showToast('两次密码不一致', 'error');
      return;
    }
    if (body.password2) delete body.password2;

    const btn = form.querySelector('button[type="submit"]');
    btn.disabled = true;
    btn.textContent = '处理中...';

    try {
      const data = await apiCall(endpoint, {
        method: 'POST',
        body: JSON.stringify(body),
      });
      setToken(data.token);
      showToast('操作成功', 'success');
      setTimeout(() => { window.location.href = successRedirect; }, 500);
    } catch (err) {
      showToast(err.message, 'error');
      btn.disabled = false;
      btn.textContent = formId === 'loginForm' ? '登录' : '注册';
    }
  });
}
