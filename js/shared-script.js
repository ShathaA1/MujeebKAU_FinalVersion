/* =========================================================
   MUJEEBKAU/sharing/shared.js
   Shared Sidebar + Shared UI Utilities
========================================================= */


/* ========================================
   API + AUTH HELPERS
======================================== */

const API_BASE_URL = "http://127.0.0.1:8000";


/** Short helper to get an element by its ID */
function $(id) {
  return document.getElementById(id);
}


/** Get saved JWT token */
function getToken() {
  return localStorage.getItem("mk_token");
}


/** Build auth headers */
function getAuthHeaders(includeJson = true) {
  const headers = {};

  if (includeJson) {
    headers["Content-Type"] = "application/json";
  }

  const token = getToken();

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  return headers;
}


/** Extract backend error message safely */
function getErrorMessage(data, fallback = "Something went wrong.") {
  if (!data) return fallback;
  return data.detail || data.error || data.message || fallback;
}


/** Clear all saved user/admin session data from localStorage */
function clearSessionStorage() {
  localStorage.removeItem("mk_token");
  localStorage.removeItem("mk_user_id");
  localStorage.removeItem("mk_user_first_name");
  localStorage.removeItem("mk_user_last_name");
  localStorage.removeItem("mk_user_name");
  localStorage.removeItem("mk_user_email");
  localStorage.removeItem("mk_user_type");
  localStorage.removeItem("mk_user_gender");
  localStorage.removeItem("mk_user_department");
  localStorage.removeItem("mk_pref_notifications");
  // ✅ Always clear the active conversation so stale IDs never bleed across sessions
  localStorage.removeItem("active_conversation_id");

  localStorage.removeItem("mk_admin_id");
  localStorage.removeItem("mk_admin_email");
  localStorage.removeItem("mk_admin_name");
}


/** Handle expired or unauthorized session */
function handleUnauthorized() {
  clearSessionStorage();

  if (typeof showFeedback === "function") {
    showFeedback(
      "Your session has expired. Please log in again.",
      "error",
      { duration: 3500 }
    );
  }

  setTimeout(() => {
    window.location.href = "../public/login.html";
  }, 1200);
}


/** Generic fetch wrapper with auth/session handling */
async function request(url, options = {}) {
  const response = await fetch(url, options);

  let data = null;

  try {
    data = await response.json();
  } catch {
    data = null;
  }

  if (response.status === 401 || response.status === 403) {
    handleUnauthorized();
    throw new Error("Unauthorized");
  }

  if (!response.ok) {
    throw new Error(getErrorMessage(data, "Request failed"));
  }

  return data;
}


/* ========================================
   CONFIG (Edit only if folder depth changes)
======================================== */

const SIDEBAR_CONFIG = {
  // Base path from the current page to the project root
  BASE_TO_ROOT: "../../",

  // Shared sidebar HTML path (relative to project root)
  SIDEBAR_HTML: "sharing/sidebar.html",

  // Shared logo path (relative to project root)
  LOGO_PATH: "sharing/logo.png",

  // Redirect destination after logout (relative to project root)
  LOGOUT_TO: "public/landing.html"
};


/* ========================================
   HELPERS
======================================== */

/** Return the configured path to the project root */
function getRoot() {
  return SIDEBAR_CONFIG.BASE_TO_ROOT;
}


/* ========================================
   SHARED SIDEBAR LOADER
======================================== */

/** Load sidebar HTML into a mount element (default: #sidebarMount) */
async function loadSharedSidebar(mountId = "sidebarMount") {
  const mount = $(mountId);
  if (!mount) return;

  const root = getRoot();

  // Fetch sidebar HTML
  const res = await fetch(root + SIDEBAR_CONFIG.SIDEBAR_HTML);
  const html = await res.text();

  // Inject sidebar HTML
  mount.innerHTML = html;

  // Fix logo path inside injected sidebar
  mount.querySelectorAll("img[src='logo.png']").forEach((img) => {
    img.src = root + SIDEBAR_CONFIG.LOGO_PATH;
  });

  // Bind click navigation (data-link)
  mount.querySelectorAll("[data-link]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = btn.getAttribute("data-link");
      if (!target) return;

      // Root-relative if contains folders, otherwise direct
      if (target.includes("/")) {
        window.location.href = root + target;
      } else {
        window.location.href = target;
      }

      closeSidebar();
    });
  });

  // Apply access rules after sidebar is injected
  applyUserTypeAccess();

  // ── Load conversation history into sidebar (authenticated users only) ────
  const isGuest = localStorage.getItem("mk_user_type") === "guest";
  if (!isGuest && getToken()) {
    loadConversations();
  }
}


/* ========================================
   SIDEBAR TOGGLE (Mobile)
======================================== */

/** Open sidebar + show overlay */
function openSidebar() {
  $("authArea")?.classList.add("sidebar-open");
  $("sidebarOverlay")?.classList.remove("hidden");
}


/** Close sidebar + hide overlay */
function closeSidebar() {
  $("authArea")?.classList.remove("sidebar-open");
  $("sidebarOverlay")?.classList.add("hidden");
}


/** Toggle sidebar open/close */
function toggleSidebar() {
  const auth = $("authArea");
  if (!auth) return;

  auth.classList.contains("sidebar-open")
    ? closeSidebar()
    : openSidebar();
}


/* ========================================
   CHAT HISTORY (Sidebar)
======================================== */

/** Expand/collapse chat history list (sidebar) */
function toggleChatHistory() {
  const history = document.getElementById("chatHistory");
  const arrow = document.getElementById("chatArrow");

  history.classList.toggle("hidden");

  if (history.classList.contains("hidden")) {
    arrow.textContent = "▶";
  } else {
    arrow.textContent = "▼";
  }
}



/** Delete one conversation — removes from UI; auto-creates new chat if it was active */
async function deleteConversation(id, icon, event) {
  event.stopPropagation();

  const confirmed = await mkConfirmDelete();
  if (!confirmed) return;

  try {
    const res = await fetch(API_BASE_URL + `/conversations/${id}`, {
      method: "DELETE",
      headers: { "Authorization": `Bearer ${getToken()}` }
    });

    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      showFeedback(data.detail || "Delete failed", "error");
      return;
    }

    // Remove the item from the sidebar
    const item = icon.closest(".conversation-item");
    if (item) item.remove();

    // If no conversations remain, show empty state
    const container = document.getElementById("chatHistory");
    if (container) {
      const remaining = container.querySelectorAll(".conversation-item").length;
      if (remaining === 0) {
        container.querySelectorAll(".convo-empty").forEach(el => el.remove());
        const empty = document.createElement("p");
        empty.className = "convo-empty";
        empty.textContent = "No conversations yet";
        container.appendChild(empty);
      }
    }

    showFeedback("Conversation deleted", "success");

    // ── If the deleted conversation was active, navigate to chat for a fresh start ──
    const activeId = localStorage.getItem("active_conversation_id");
    if (activeId && String(activeId) === String(id)) {
      localStorage.removeItem("active_conversation_id");
      if (window.location.pathname.toLowerCase().includes("chat.html")) {
        // Already on chat — reset in-place
        if (typeof _showWelcome === "function") {
          const chatMessages = document.getElementById("chatMessages");
          if (chatMessages) _showWelcome(chatMessages);
        }
        const input = document.getElementById("chatInput");
        if (input) input.value = "";
      } else {
        window.location.href = getRoot() + "User-view/chat.html";
      }
    }

  } catch (err) {
    showFeedback(err.message || "Delete failed", "error");
  }
}

/** Create a new conversation, save it, reset chat in-place or navigate to chat page */
async function createNewChat() {
  try {
    const data = await request(`${API_BASE_URL}/conversations`, {
      method: "POST",
      headers: getAuthHeaders()
    });

    const convoId = data.conversation_id;

    // Mark as the active conversation
    localStorage.setItem("active_conversation_id", convoId);

    // ── If already on the chat page, reset the UI in-place (no navigation) ────────
    if (window.location.pathname.toLowerCase().includes("chat.html")) {
      closeSidebar();

      // Reset chat messages to the welcome bubble
      if (typeof _showWelcome === "function") {
        const chatMessages = document.getElementById("chatMessages");
        if (chatMessages) _showWelcome(chatMessages);
      }

      // Clear any input text
      const input = document.getElementById("chatInput");
      if (input) input.value = "";

      // Re-fetch the full conversation list from the server so the sidebar
      // shows ALL conversations (including the previous one with its correct
      // persisted title) and highlights the newly created one as active.
      // localStorage.active_conversation_id is already set above, so
      // loadConversations() will automatically mark the new item as active.
      await loadConversations();

    } else {
      // Navigate from another page (notifications, GPA, etc.)
      window.location.href = getRoot() + "User-view/chat.html";
    }

  } catch (err) {
    showFeedback(err.message, "error");
  }
}

/**
 * Fetch all conversations from the backend and render them in the sidebar.
 * Uses a direct fetch (NOT the request() wrapper) so that a 401/403 response
 * never triggers handleUnauthorized() and never redirects the user away.
 */
async function loadConversations() {
  const token = getToken();
  if (!token) return; // Not logged in — nothing to load

  const container = document.getElementById("chatHistory");
  if (!container) return;

  let conversations = [];

  try {
    const res = await fetch(`${API_BASE_URL}/conversations`, {
      headers: { "Authorization": `Bearer ${token}` }
    });

    if (!res.ok) {
      // Silent fail — don't redirect, don't crash the page
      console.warn("[Sidebar] GET /conversations returned", res.status);
      return;
    }

    const data = await res.json();
    conversations = data.conversations || [];

  } catch (err) {
    console.error("[Sidebar] Failed to load conversations:", err.message);
    return; // Network error — leave sidebar as-is
  }

  // Remove previously rendered conversation items (keep "New Chat" button)
  container.querySelectorAll(".conversation-item").forEach(el => el.remove());
  container.querySelectorAll(".convo-empty").forEach(el => el.remove());

  const activeId = localStorage.getItem("active_conversation_id");

  // Sort newest first by start_at (server returns pre-sorted, this is a safety net)
  const sorted = conversations.slice().sort((a, b) => {
    const dateA = a.start_at ? new Date(a.start_at).getTime() : a.id;
    const dateB = b.start_at ? new Date(b.start_at).getTime() : b.id;
    return dateB - dateA;
  });

  if (sorted.length === 0) {
    const empty = document.createElement("p");
    empty.className = "convo-empty";
    empty.textContent = "No conversations yet";
    container.appendChild(empty);
    return;
  }

  sorted.forEach(convo => {
    const isActive = String(convo.id) === String(activeId);

    const btn = document.createElement("button");
    btn.className = "side-link sub-item conversation-item" + (isActive ? " convo-active" : "");
    btn.dataset.convoId = convo.id;

    // ── Build label: use persisted title if available, else generic fallback ──
    const label = convo.title || "New conversation";

    btn.innerHTML = `
      <span class="convo-label" title="${label}">${label}</span>
      <span class="delete-convo" onclick="deleteConversation(${convo.id}, this, event)" title="Delete">🗑</span>
    `;

    btn.addEventListener("click", (e) => {
      if (e.target.classList.contains("delete-convo")) return;

      localStorage.setItem("active_conversation_id", convo.id);

      container.querySelectorAll(".conversation-item").forEach(el => el.classList.remove("convo-active"));
      btn.classList.add("convo-active");

      if (window.location.pathname.toLowerCase().includes("chat.html")) {
        closeSidebar();
        if (typeof loadMessages === "function") loadMessages();
      } else {
        window.location.href = getRoot() + "User-view/chat.html";
      }
    });

    container.appendChild(btn);
  });
}

/** Add a single newly-created conversation to the top of the sidebar list */
function addConversationToSidebar(id) {
  const container = document.getElementById("chatHistory");
  if (!container) return;

  // Remove any empty-state placeholder
  container.querySelectorAll(".convo-empty").forEach(el => el.remove());

  // De-highlight any currently active item
  container.querySelectorAll(".conversation-item").forEach(el => el.classList.remove("convo-active"));

  const btn = document.createElement("button");
  btn.className = "side-link sub-item conversation-item convo-active";
  btn.dataset.convoId = id;

  btn.innerHTML = `
    <span class="convo-label">New conversation</span>
    <span class="delete-convo" onclick="deleteConversation(${id}, this, event)" title="Delete">🗑</span>
  `;

  btn.addEventListener("click", (e) => {
    if (e.target.classList.contains("delete-convo")) return;
    localStorage.setItem("active_conversation_id", id);
    container.querySelectorAll(".conversation-item").forEach(el => el.classList.remove("convo-active"));
    btn.classList.add("convo-active");
    if (window.location.pathname.toLowerCase().includes("chat.html")) {
      closeSidebar();
      if (typeof loadMessages === "function") loadMessages();
    } else {
      window.location.href = getRoot() + "User-view/chat.html";
    }
  });

  // Insert directly after the "New Chat" button (stable id anchor)
  const newChatBtn = container.querySelector("#newChatBtn");
  if (newChatBtn && newChatBtn.nextSibling) {
    container.insertBefore(btn, newChatBtn.nextSibling);
  } else {
    container.appendChild(btn);
  }
}

/* ========================================
   LOGOUT
======================================== */

/** Logout current user/admin and redirect to landing page */
function handleLogout() {
  closeSidebar();

  localStorage.removeItem("mk_token");

  localStorage.removeItem("mk_user_id");
  localStorage.removeItem("mk_user_first_name");
  localStorage.removeItem("mk_user_last_name");
  localStorage.removeItem("mk_user_name");
  localStorage.removeItem("mk_user_email");
  localStorage.removeItem("mk_user_type");
  localStorage.removeItem("mk_user_gender");
  localStorage.removeItem("mk_user_department");
  localStorage.removeItem("mk_pref_notifications");
  // ✅ Clear active conversation so the next login starts fresh
  localStorage.removeItem("active_conversation_id");

  localStorage.removeItem("mk_admin_id");
  localStorage.removeItem("mk_admin_email");
  localStorage.removeItem("mk_admin_name");

  const root = getRoot();
  window.location.href = root + SIDEBAR_CONFIG.LOGOUT_TO;
}


/* ========================================
   ROLE SWITCHING (User/Admin menus)
======================================== */

/** Switch sidebar menu view: "user" or "admin" */
function setSidebarRole(role) {
  const userMenu = $("userMenu");
  const adminMenu = $("adminMenu");
  const topLabel = $("topbarRoleLabel");

  if (topLabel) {
    topLabel.textContent =
      role === "admin" ? "Admin Dashboard" : "User Dashboard";
  }

  userMenu?.classList.add("hidden");
  adminMenu?.classList.add("hidden");

  if (role === "admin") {
    adminMenu?.classList.remove("hidden");
  } else {
    userMenu?.classList.remove("hidden");
  }
}


/* ========================================
   ACCESS RULES (User Type)
======================================== */

/** Hide GPA button for faculty users */
function applyUserTypeAccess() {
  const type = localStorage.getItem("mk_user_type") || "";
  const gpaBtn = $("gpaNavBtn");

  // Show by default
  gpaBtn?.classList.remove("hidden");

  // Hide for faculty
  if (type === "faculty") {
    gpaBtn?.classList.add("hidden");
  }
}


/* ========================================
   SHARED TOAST FEEDBACK
   Requires: MUJEEBKAU/sharing/toast.html
======================================== */

/** Load toast host (once per page) */
async function loadSharedToast() {
  if (document.getElementById("mkToastHost")) return;

  const root = getRoot();
  const res = await fetch(root + "sharing/toast.html");
  const html = await res.text();

  document.body.insertAdjacentHTML("beforeend", html);
}


/** Show toast feedback message */
function showFeedback(message, type = "info", opts = {}) {
  const host = document.getElementById("mkToastHost");

  // Fallback
  if (!host) {
    alert(message);
    return;
  }

  const titleMap = {
    success: "Success",
    error: "Error",
    info: "Info",
    warning: "Warning"
  };

  const iconMap = {
    success: "✅",
    error: "❌",
    info: "ℹ️",
    warning: "⚠️"
  };

  const title = opts.title || titleMap[type] || "Info";
  const icon = opts.icon || iconMap[type] || "ℹ️";
  const duration =
    typeof opts.duration === "number" ? opts.duration : 2500;

  const toast = document.createElement("div");
  toast.className = `mk-toast ${type}`;

  toast.innerHTML = `
    <div class="mk-icon">${icon}</div>
    <div class="mk-body">
      <div class="mk-title">${title}</div>
      <div class="mk-msg">${message}</div>
    </div>
    <button class="mk-close" aria-label="Close">×</button>
  `;

  host.appendChild(toast);

  requestAnimationFrame(() => toast.classList.add("show"));

  toast
    .querySelector(".mk-close")
    .addEventListener("click", () => removeFeedback(toast));

  if (duration > 0) {
    setTimeout(() => removeFeedback(toast), duration);
  }
}


/** Remove toast with exit animation */
function removeFeedback(toast) {
  if (!toast) return;

  toast.classList.remove("show");
  setTimeout(() => toast.remove(), 200);
}


/* ========================================
   SHARED CONFIRM DIALOG
   Requires: MUJEEBKAU/sharing/confirm.html
======================================== */

/** Load confirm dialog host (once per page) */
async function loadSharedConfirm() {
  if (document.getElementById("mkConfirmHost")) return;

  const root = getRoot();
  const res = await fetch(root + "sharing/confirm.html");
  const html = await res.text();

  document.body.insertAdjacentHTML("beforeend", html);

  // Close handlers (backdrop + X)
  const host = document.getElementById("mkConfirmHost");

  host.querySelectorAll("[data-confirm-close]").forEach((el) => {
    el.addEventListener("click", () => mkConfirmClose(false));
  });

  // ESC closes dialog
  document.addEventListener("keydown", (e) => {
    const h = document.getElementById("mkConfirmHost");
    if (!h || h.classList.contains("hidden")) return;

    if (e.key === "Escape") {
      mkConfirmClose(false);
    }
  });
}


// Internal state (one dialog at a time)
let __mkConfirmResolver = null;


/** Close confirm dialog and resolve promise */
function mkConfirmClose(result) {
  const host = document.getElementById("mkConfirmHost");
  if (!host) return;

  host.classList.add("hidden");
  host.setAttribute("aria-hidden", "true");

  if (typeof __mkConfirmResolver === "function") {
    const r = __mkConfirmResolver;
    __mkConfirmResolver = null;
    r(result);
  }
}


/** Show confirm dialog and return true/false */
async function mkConfirm(message = "Are you sure?", opts = {}) {
  await loadSharedConfirm();

  if (__mkConfirmResolver) return false;

  const host = document.getElementById("mkConfirmHost");
  const titleEl = document.getElementById("mkConfirmTitle");
  const msgEl = document.getElementById("mkConfirmMsg");

  const title = opts.title || "Confirm";
  const okText = opts.okText || "OK";
  const cancelText = opts.cancelText || "Cancel";

  titleEl.textContent = title;
  msgEl.textContent = message;

  const okBtn = host.querySelector("[data-confirm-ok]");
  const cancelBtn = host.querySelector("[data-confirm-cancel]");

  okBtn.textContent = okText;
  cancelBtn.textContent = cancelText;

  // Clean old listeners by cloning buttons
  const okClone = okBtn.cloneNode(true);
  const cancelClone = cancelBtn.cloneNode(true);

  okBtn.parentNode.replaceChild(okClone, okBtn);
  cancelBtn.parentNode.replaceChild(cancelClone, cancelBtn);

  host.classList.remove("hidden");
  host.setAttribute("aria-hidden", "false");
  okClone.focus?.();

  return new Promise((resolve) => {
    __mkConfirmResolver = resolve;

    okClone.addEventListener("click", () => mkConfirmClose(true));
    cancelClone.addEventListener("click", () => mkConfirmClose(false));
  });
}


/** Unified delete confirmation dialog */
async function mkConfirmDelete() {
  return mkConfirm("Are you sure you want to delete this?", {
    title: "Delete Confirmation",
    okText: "Delete",
    cancelText: "Cancel"
  });
}


/**
 * Update the sidebar label for a conversation based on the first user message.
 * Persists the title to the backend so it survives page refreshes and re-logins.
 * @param {number|string} convoId  - conversation ID
 * @param {string}        rawText  - the raw first user message
 */
function _updateConvoLabel(convoId, rawText) {
  const container = document.getElementById("chatHistory");
  if (!container) return;

  // Trim, collapse whitespace, remove emoji block, cap at 40 chars
  let title = rawText
    .trim()
    .replace(/\s+/g, " ")
    .replace(/[\u{1F600}-\u{1FFFF}]/gu, "")   // strip emoji
    .trim();

  if (title.length > 40) {
    title = title.slice(0, 38).trimEnd() + "\u2026";
  }

  if (!title) return; // nothing useful — leave the label as-is

  // 1. Update the DOM immediately for instant visual feedback
  const btn = container.querySelector(`.conversation-item[data-convo-id="${convoId}"]`);
  if (btn) {
    const labelEl = btn.querySelector(".convo-label");
    if (labelEl) {
      labelEl.textContent = title;
      labelEl.title = rawText.slice(0, 120);
    }
  }

  // 2. Persist to the backend so the label survives refresh / re-login
  const token = getToken();
  if (token && convoId) {
    fetch(`${API_BASE_URL}/conversations/${convoId}/title`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", "Authorization": `Bearer ${token}` },
      body: JSON.stringify({ title: rawText })
    }).catch(err => console.warn("[Sidebar] Failed to persist conversation title:", err.message));
  }
}