
/**
 * UserView-script.js
 * Core logic for User View: Chat, Conversations, Notifications, and GPA Calculator.
 * Maintains state and handles interactions with the MujeebKAU API.
 */

/* =========================================================
   CHAT SYSTEM
   ========================================================= */

/**
 * Validates or creates a conversation ID in localStorage.
 * Ensures that the current user has a valid session for messaging.
 */
async function ensureConversation() {
    const isGuest = localStorage.getItem("mk_user_type") === "guest";
    if (isGuest) return null;

    let conversationId = localStorage.getItem("active_conversation_id");

    // Initialize new conversation if none exists
    if (!conversationId || conversationId === "null" || conversationId === "undefined") {
        return await createFreshConversation();
    }

    // Validate ownership of the stored conversation ID
    try {
        await request(`${API_BASE_URL}/messages/${conversationId}`, {
            headers: getAuthHeaders(false)
        });
        return parseInt(conversationId);
    } catch (err) {
        console.warn("[Chat] Stored ID invalid, resetting...", err.message);
        localStorage.removeItem("active_conversation_id");
        return await createFreshConversation();
    }
}

/**
 * Creates a new conversation entry in the backend and stores the ID locally.
 */
async function createFreshConversation() {
    const res = await request(`${API_BASE_URL}/conversations`, {
        method: "POST",
        headers: getAuthHeaders(true)
    });
    const convoId = res.conversation_id;
    localStorage.setItem("active_conversation_id", convoId);
    return convoId;
}

/**
 * Handles sending messages from the user to the assistant.
 * Manages UI state, typing indicators, and backend communication.
 */
async function sendMessage() {
    const input = $("chatInput");
    const msg = input.value.trim();
    if (!msg) return;

    const isGuest = localStorage.getItem("mk_user_type") === "guest";
    let conversationId = null;

    // Validate session for non-guest users
    if (!isGuest) {
        try {
            conversationId = await ensureConversation();
        } catch (err) {
            handleUIError(err.message || "Could not start conversation");
            return;
        }
    }

    // UI Cleanup: Clear welcome hero and placeholders
    const chatMessages = $("chatMessages");
    if (!chatMessages) return;
    
    $("chatPlaceholder")?.style.setProperty("display", "none");
    chatMessages.querySelector(".welcome-hero")?.remove();

    // Track first message for sidebar title update
    const isFirstMessage = chatMessages.querySelectorAll(".message.user").length === 0;

    // Render User Message
    appendMessage(chatMessages, "user", msg);
    input.value = "";
    scrollToBottom(chatMessages);

    // Render Typing Indicator
    showTypingIndicator(chatMessages);
    scrollToBottom(chatMessages);

    try {
        const url = isGuest ? `${API_BASE_URL}/guest-chat` : `${API_BASE_URL}/messages`;
        const bodyData = isGuest ? { content: msg } : { conversation_id: conversationId, content: msg };

        const res = await request(url, {
            method: "POST",
            headers: getAuthHeaders(true),
            body: JSON.stringify(bodyData)
        });

        removeTypingIndicator();

        // Sync conversation ID if backend generated a new one
        if (!isGuest && res.conversation_id) {
            if (String(res.conversation_id) !== String(conversationId)) {
                localStorage.setItem("active_conversation_id", res.conversation_id);
                conversationId = res.conversation_id;
            }
        }

        // Render Assistant Response
        appendMessage(chatMessages, "assistant", res.content);
        scrollToBottom(chatMessages);

        // Update sidebar title on first interaction
        if (!isGuest && isFirstMessage && conversationId) {
            if (typeof _updateConvoLabel === "function") _updateConvoLabel(conversationId, msg);
        }

    } catch (err) {
        removeTypingIndicator();
        handleUIError(err.message || "Request failed");
    }
}

/* =========================================================
   MESSAGE RENDERING HELPERS
   ========================================================= */

/**
 * Appends a message bubble to the chat container.
 * @param {HTMLElement} container - The chat messages container.
 * @param {string} role - "user" or "assistant".
 * @param {string} content - The message text/markdown.
 */
function appendMessage(container, role, content) {
    const div = document.createElement("div");
    div.className = `message ${role}`;

    const safeContent = role === "user" ? 
        content.replace(/</g, "&lt;").replace(/>/g, "&gt;") : 
        (window.marked ? marked.parse(content) : content);

    const mdClass = role === "assistant" ? " markdown-body" : "";

    if (role === "assistant") {
        div.innerHTML = `
            <div class="message-bubble${mdClass}">
                <div class="response-text">${safeContent}</div>
                ${getAssistantActionsHtml()}
            </div>
        `;
    } else {
        div.innerHTML = `<div class="message-bubble${mdClass}">${safeContent}</div>`;
    }

    container.appendChild(div);
}

/**
 * Returns the HTML for assistant action buttons (copy, like, dislike).
 */
function getAssistantActionsHtml() {
    return `
        <div class="chat-actions">
            <button class="action-btn copy" onclick="copyResponse(this)" title="Copy">
                <svg viewBox="0 0 24 24"><path d="M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2v-1M8 5a2 2 0 002 2h2a2 2 0 002-2M8 5a2 2 0 012-2h2a2 2 0 012 2m0 0h2a2 2 0 012 2v3m2 4H10m0 0l3-3m-3 3l3 3"></path></svg>
            </button>
            <button class="action-btn like" onclick="toggleLike(this)" title="Like">
                <svg viewBox="0 0 24 24"><path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"></path></svg>
            </button>
            <button class="action-btn dislike" onclick="toggleDislike(this)" title="Dislike">
                <svg viewBox="0 0 24 24"><path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zm7-13h3a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-3"></path></svg>
            </button>
        </div>
    `;
}

function showTypingIndicator(container) {
    const typingDiv = document.createElement("div");
    typingDiv.className = "message assistant";
    typingDiv.id = "typingIndicator";
    typingDiv.innerHTML = `<div class="message-bubble">...</div>`;
    container.appendChild(typingDiv);
}

function removeTypingIndicator() {
    $("typingIndicator")?.remove();
}

function scrollToBottom(container) {
    container.scrollTop = container.scrollHeight;
}

function handleUIError(message) {
    if (typeof showFeedback === "function") showFeedback(message, "error");
    else alert(message);
}

/* =========================================================
   CONVERSATION HANDLING
   ========================================================= */

/**
 * Loads and renders the message history for the active conversation.
 */
async function loadMessages() {
    const isGuest = localStorage.getItem("mk_user_type") === "guest";
    if (isGuest) return;

    const conversationId = localStorage.getItem("active_conversation_id");
    const chatMessages = $("chatMessages");
    if (!chatMessages) return;

    if (!conversationId) {
        _showWelcome(chatMessages);
        return;
    }

    try {
        const data = await request(`${API_BASE_URL}/messages/${conversationId}`, {
            headers: getAuthHeaders(true)
        });

        if (data.messages && data.messages.length > 0) {
            chatMessages.innerHTML = "";
            data.messages.forEach(msg => appendMessage(chatMessages, msg.sendtype, msg.content));
            scrollToBottom(chatMessages);
        } else {
            _showWelcome(chatMessages);
        }
    } catch (err) {
        console.error("[Chat] Load messages failed:", err.message);
    }
}

/**
 * Displays the default welcome message in the chat area.
 */
function _showWelcome(container) {
    container.innerHTML = `
        <div class="welcome-hero">
            <h1 class="welcome-heading">مرحبًا، أنا مجيب</h1>
            <p class="welcome-subtitle">
                مساعدك الأكاديمي الذكي في جامعة الملك عبدالعزيز.<br>
                اسأل عن القبول، المواعيد الأكاديمية، اللوائح الجامعية، والمزيد.
            </p>
        </div>
    `;
}

/**
 * Toggles like state for an assistant message.
 */
function toggleLike(btn) {
    const actions = btn.closest(".chat-actions");
    actions.querySelector(".dislike")?.classList.remove("active");
    btn.classList.toggle("active");
}

/**
 * Toggles dislike state for an assistant message.
 */
function toggleDislike(btn) {
    const actions = btn.closest(".chat-actions");
    actions.querySelector(".like")?.classList.remove("active");
    btn.classList.toggle("active");
}

/**
 * Copies the text content of a response bubble to the clipboard.
 */
function copyResponse(btn) {
    const text = btn.closest(".message-bubble").querySelector(".response-text").innerText;
    navigator.clipboard.writeText(text);
    btn.classList.add("copied");
    setTimeout(() => btn.classList.remove("copied"), 1200);
}

/* =========================================================
   NOTIFICATIONS SYSTEM
   ========================================================= */

/**
 * Fetches and displays notifications for the authenticated user.
 */
async function loadNotifications() {
    const container = $("notifications-container");
    if (!container) return;

    try {
        const data = await request(`${API_BASE_URL}/user/notifications`, {
            headers: getAuthHeaders()
        });

        const notifications = data.notifications || [];
        container.innerHTML = "";

        if (notifications.length === 0) {
            container.innerHTML = `<p style="text-align:center;">No notifications</p>`;
            return;
        }

        // Sort by time descending
        notifications.sort((a, b) => new Date(b.schedule_time) - new Date(a.schedule_time));

        notifications.forEach(n => {
            const formattedDate = new Date(n.schedule_time + "Z").toLocaleString("en-US", {
                timeZone: "Asia/Riyadh"
            });

            container.innerHTML += `
                <div class="notification ${n.is_read ? 'read' : 'unread'}" data-id="${n.id}">
                    <h4>${n.title}</h4>
                    <p>${n.message}</p>
                    <small>${formattedDate}</small>
                    <div class="actions">
                        <button class="icon-btn read" onclick="markAsRead(${n.id})" title="Mark as read">✓</button>
                        <button class="icon-btn delete" onclick="deleteNotification(${n.id})" title="Delete">✕</button>
                    </div>
                </div>
            `;
        });
    } catch (err) {
        console.error("[Notifications] Load failed:", err.message);
    }
}

/**
 * Marks a single notification as read.
 */
async function markAsRead(id) {
    try {
        await request(`${API_BASE_URL}/user/notifications/${id}/read`, {
            method: "PUT",
            headers: getAuthHeaders()
        });
        loadNotifications();
    } catch (err) {
        handleUIError(err.message);
    }
}

/**
 * Deletes a single notification after user confirmation.
 */
async function deleteNotification(id) {
    if (!await mkConfirmDelete()) return;

    try {
        await request(`${API_BASE_URL}/user/notifications/${id}`, {
            method: "DELETE",
            headers: getAuthHeaders()
        });
        loadNotifications();
        showFeedback("Deleted", "success");
    } catch (err) {
        handleUIError(err.message);
    }
}

/**
 * Deletes all notifications for the current user.
 */
async function deleteAllNotifications() {
    if (!await mkConfirmDelete()) return;

    try {
        await request(`${API_BASE_URL}/user/notifications/delete-all`, {
            method: "DELETE",
            headers: getAuthHeaders()
        });
        loadNotifications();
        showFeedback("All notifications cleared", "success");
    } catch (err) {
        handleUIError(err.message);
    }
}

/**
 * Marks all notifications as read.
 */
async function markAllAsRead() {
    try {
        await request(`${API_BASE_URL}/user/notifications/read-all`, {
            method: "PUT",
            headers: getAuthHeaders()
        });
        loadNotifications();
    } catch (err) {
        handleUIError(err.message);
    }
}

/* =========================================================
   GPA CALCULATOR
   ========================================================= */

/**
 * Adds a new course entry row to the GPA calculator.
 */
function addCourse() {
    const courseList = $("courseList");
    if (!courseList) return;

    const div = document.createElement("div");
    div.className = "course-item";
    div.innerHTML = `
        <select>
            <option value="">Grade</option>
            <option value="5">A+ (5.0)</option>
            <option value="4.75">A (4.75)</option>
            <option value="4.5">B+ (4.5)</option>
            <option value="4">B (4.0)</option>
            <option value="3.5">C+ (3.5)</option>
            <option value="3">C (3.0)</option>
            <option value="2.5">D+ (2.5)</option>
            <option value="2">D (2.0)</option>
            <option value="0">F (0.0)</option>
        </select>
        <input type="number" placeholder="Credit Hours" min="1">
        <button type="button" onclick="removeCourse(this)">Remove</button>
    `;
    courseList.appendChild(div);
}

/**
 * Removes a specific course entry row.
 */
function removeCourse(btn) {
    btn.parentElement?.remove();
}

/**
 * Calculates the new cumulative GPA based on current status and new courses.
 */
function calculateGPA() {
    const currentGPA = parseFloat($("currentGPA")?.value) || 0;
    const completedHours = parseFloat($("completedHours")?.value) || 0;

    const courses = document.querySelectorAll(".course-item");
    let totalPoints = currentGPA * completedHours;
    let totalHours = completedHours;

    courses.forEach(course => {
        const grade = parseFloat(course.querySelector("select").value) || 0;
        const hours = parseFloat(course.querySelector("input").value) || 0;
        totalPoints += grade * hours;
        totalHours += hours;
    });

    const newGPA = totalHours > 0 ? (totalPoints / totalHours).toFixed(2) : "0.00";

    const resultContainer = $("gpaResult");
    if (resultContainer) {
        resultContainer.innerHTML = `
            <div class="card" style="margin-top:15px;">
                <div class="card-header">Result</div>
                <h2 style="font-size:38px;">${newGPA}</h2>
                <p>New Cumulative GPA</p>
            </div>
        `;
    }
}

/* =========================================================
   EVENT LISTENERS & INITIALIZATION
   ========================================================= */

/**
 * Consolidates all page initialization logic.
 */
document.addEventListener("DOMContentLoaded", async () => {
    // Load shared UI components
    await loadSharedToast();
    await loadSharedSidebar("sidebarMount");
    setSidebarRole("user");

    // Initialize chat input listeners
    const chatInput = $("chatInput");
    if (chatInput) {
        chatInput.addEventListener("keypress", (e) => {
            if (e.key === "Enter") {
                e.preventDefault();
                sendMessage();
            }
        });
    }

    // Load page-specific data
    if ($("chatMessages")) loadMessages();
    if ($("notifications-container")) loadNotifications();
});
