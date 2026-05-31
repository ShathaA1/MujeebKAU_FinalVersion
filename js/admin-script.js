/* =========================================
   MUJEEBKAU/js/admin-script.js
   Admin Dashboard Controller & Logic
   Handles: Overview stats, updates, notifications
========================================= */

/* =========================================
   SHARED STORAGE — UPDATES HISTORY
========================================= */

/**
 * Format date as dd/mm/yyyy
 * @param {Date|string} dateInput - Date to format
 * @returns {string} Formatted date string
 */
function formatDate(dateInput) {
  let date;

  // If it's already in dd/mm/yyyy format, return it
  if (typeof dateInput === 'string' && /^\d{2}\/\d{2}\/\d{4}$/.test(dateInput)) {
    return dateInput;
  }

  // Try to parse the date
  if (dateInput instanceof Date) {
    date = dateInput;
  } else if (typeof dateInput === 'string') {
    date = new Date(dateInput);
  } else {
    date = new Date();
  }

  // If invalid date, use current date
  if (isNaN(date.getTime())) {
    date = new Date();
  }

  const day = String(date.getDate()).padStart(2, '0');
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const year = date.getFullYear();

  return `${day}/${month}/${year}`;
}

/**
 * Migrate old date formats to dd/mm/yyyy
 * Ensures backward compatibility with older data
 */
function migrateUpdatesDates() {
  let needsSave = false;

  updatesHistory = updatesHistory.map(update => {
    if (update.date && !/^\d{2}\/\d{2}\/\d{4}$/.test(update.date)) {
      needsSave = true;
      return {
        ...update,
        date: formatDate(update.date)
      };
    }
    return update;
  });

  if (needsSave) {
    saveUpdatesHistory();
  }
}

/**
 * Save updates history to localStorage
 */
function saveUpdatesHistory() {
  localStorage.setItem("adminUpdates", JSON.stringify(updatesHistory));
}

//sara-start (2)
/* =========================================
   SHARED STORAGE — NOTIFICATIONS
========================================= */

let notificationsList = [];
let currentEditId = null;

let editScheduleFlatpickrInstance = null;
let filterDateFromInstance = null;
let filterDateToInstance = null;
let sendDateFlatpickrInstance = null;

function formatDisplayTime(dateValue) {

  const date = new Date(dateValue + "Z");

  return date.toLocaleString("en-US", {
    timeZone: "Asia/Riyadh",
    year: "numeric",
    month: "long",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: true
  });
}

function normalizeAudienceForDisplay(audience) {
  if (audience === "student") return "student";
  if (audience === "faculty") return "faculty";
  return "all";
}

function normalizeCollegeForDisplay(college) {
  if (!college || college === "all") return "All Colleges";
  return college;
}

function getCurrentFilters() {
  return {
    audience: $("filterAudience")?.value || "all",
    type: $("filterType")?.value || "all",
    status: $("filterStatus")?.value || "all",
    college: $("filterCollege")?.value || "all",
    dateFrom: $("filterDateFrom")?.value || "",
    dateTo: $("filterDateTo")?.value || ""
  };
}

async function fetchNotifications(filters = {}) {
  const params = new URLSearchParams();

  if (filters.audience && filters.audience !== "all") {
    params.append("audience", filters.audience);
  }

  if (filters.type && filters.type !== "all") {
    params.append("notification_type", filters.type);
  }

  if (filters.status && filters.status !== "all") {
    params.append("status_filter", filters.status);
  }

  if (filters.college && filters.college !== "all") {
    params.append("college_name", filters.college);
  }

  if (filters.dateFrom) {
    params.append("date_from", filters.dateFrom);
  }

  if (filters.dateTo) {
    params.append("date_to", filters.dateTo);
  }

  const queryString = params.toString()
    ? `?${params.toString()}`
    : "";

  const data = await request(
    `${API_BASE_URL}/admin/notifications${queryString}`,
    {
      method: "GET",
      headers: getAuthHeaders(false)
    }
  );

  return data.notifications || [];
}

async function refreshNotificationsHistory(filters = null) {
  const activeFilters = filters || getCurrentFilters();
  notificationsList = await fetchNotifications(activeFilters);
  loadNotificationsHistory(notificationsList);
}
//sara-end (2)

/* =========================================
   ADMIN MODEL (OVERVIEW DATA)
========================================= */
const AdminModel = {
  stats: { users: 0, docs: 0, notifications: 0 },
  uploads: [],
  activityLog: [
    { week: "Week 1", month: "Jan", uploads: 2, notifications: 1 },
    { week: "Week 2", month: "Jan", uploads: 1, notifications: 3 },
    { week: "Week 3", month: "Feb", uploads: 4, notifications: 2 }
  ],
  timeMode: "weekly",
  activityFilter: "all"
};

/* =========================================
   OVERVIEW PAGE VIEW FUNCTIONS
========================================= */
let activityChart;
let timelineChart;

/* =========================================
   OVERVIEW PAGE CONTROLLER (FILTERS + DOWNLOAD)
========================================= */
const AdminController = {

  /**
   * Filter timeline chart by activity type
   * @param {string} type - Activity type: "all", "uploads", or "notifications"
   */
  setActivityFilter(type) {
    AdminModel.activityFilter = type;
    AdminView.updateTimelineChart();
  },

  /**
   * Switch time mode between weekly and monthly
   * @param {string} mode - Time mode: "weekly" or "monthly"
   */
  setTimeMode(mode) {
    AdminModel.timeMode = mode;
    AdminView.updateTimelineChart();
  },

  /**
   * Download chart as PNG image
   * @param {string} chartId - Canvas element ID
   */
  downloadChart(chartId) {
    const canvas = document.getElementById(chartId);
    if (!canvas) return;

    const link = document.createElement("a");
    link.href = canvas.toDataURL("image/png");
    link.download = chartId + ".png";
    link.click();
  }
};

/* =========================================
   ADMIN VIEW - OVERVIEW PAGE UPDATES
========================================= */
const AdminView = {

  /**
   * Update statistics cards on overview page
   */
  updateOverviewStats() {
    if (!$("statUsers")) return;

    $("statUsers").textContent = AdminModel.stats.users;
    $("statDocs").textContent = AdminModel.stats.docs;
    $("statNotifications").textContent = AdminModel.stats.notifications;
  },

  /**
   * Update latest activity section
   */
  updateLatestActivity() {
    if (!$("lastUpload")) return;

    const lastUpload = updatesHistory.at(-1);
    const lastNotification = notificationsList.at(-1);

    $("lastUpload").textContent = lastUpload
      ? `${lastUpload.filename || lastUpload.file} (${lastUpload.category})`
      : "No uploads yet";

    $("lastNotification").textContent = lastNotification
      ? `${lastNotification.title} → ${lastNotification.audience}`
      : "No notifications yet";
  },

  /**
   * Update doughnut chart showing activity distribution
   */
  updateChart() {
    const ctx = $("activityChart");
    if (!ctx) return;

    const data = {
      labels: ["Users", "Documents", "Notifications"],
      datasets: [{
        data: [
          AdminModel.stats.users,
          AdminModel.stats.docs,
          AdminModel.stats.notifications
        ],
        backgroundColor: ["#8e44ad", "#4caf50", "#2196f3"]
      }]
    };

    if (activityChart) {
      activityChart.data = data;
      activityChart.update();
    } else {
      activityChart = new Chart(ctx, {
        type: "doughnut",
        data,
        options: { plugins: { legend: { position: "bottom" } } }
      });
    }
  },

  /**
   * Update timeline chart with filters applied
   */
  updateTimelineChart() {
    const ctx = $("timelineChart");
    if (!ctx) return;

    // Group activity data by time period
    const grouped = {};
    AdminModel.activityLog.forEach(r => {
      const key = AdminModel.timeMode === "monthly" ? r.month : r.week;
      if (!grouped[key]) grouped[key] = { uploads: 0, notifications: 0 };
      grouped[key].uploads += r.uploads;
      grouped[key].notifications += r.notifications;
    });

    const labels = Object.keys(grouped);
    const uploadsData = labels.map(k => grouped[k].uploads);
    const notifData = labels.map(k => grouped[k].notifications);

    const datasets = [];

    // Add datasets based on activity filter
    if (AdminModel.activityFilter === "all" || AdminModel.activityFilter === "uploads") {
      datasets.push({
        label: "Uploads",
        data: uploadsData,
        borderColor: "#4caf50",
        backgroundColor: "rgba(76,175,80,0.2)",
        fill: true
      });
    }

    if (AdminModel.activityFilter === "all" || AdminModel.activityFilter === "notifications") {
      datasets.push({
        label: "Notifications",
        data: notifData,
        borderColor: "#2196f3",
        backgroundColor: "rgba(33,150,243,0.2)",
        fill: true
      });
    }

    if (timelineChart) {
      timelineChart.data = { labels, datasets };
      timelineChart.update();
    } else {
      timelineChart = new Chart(ctx, {
        type: "line",
        data: { labels, datasets },
        options: { plugins: { legend: { position: "bottom" } } }
      });
    }
  }
};


/* =========================================
   UPDATE PAGE CONTROLLER
========================================= */

// Stores temporary data related to uploaded documents and extracted academic events.
let extractedEvents = [];
let processedDocumentData = null;

const AdminUpdateController = {
  /**
   * Benefit:
   *     Uploads a selected document and saves it into the knowledge base.
   *
   * What it does:
   *     Validates the upload form, sends the file and metadata to the backend,
   *     tracks upload/processing progress, handles success or failure, then
   *     refreshes the admin dashboard and clears the form.
   */
  addToKnowledgeBase: async function () {
    const fileInput = $("adminFileInput");
    const category = $("adminTargetCategory").value;
    const docType = $("documentType").value;
    const college = $("updateCollege").value;

    const kbStatus = $("kbStatus");
    const progressWrap = $("progressContainer");
    const progressBar = $("progressBar");
    const kbButton = $("kbButton");

    if (!fileInput.files[0] || !category || !docType) {
      showFeedback("Please select file, type, and category", "error");
      return;
    }

    const formData = new FormData();
    formData.append("file", fileInput.files[0]);
    formData.append("document_type", docType);
    formData.append("user_type", category);
    formData.append("college_name", college);

    let progressInterval = null;

    try {
      kbButton.disabled = true;

      kbStatus.textContent = "Uploading and processing...";
      progressWrap.classList.remove("hidden");
      progressBar.style.width = "0%";

      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${API_BASE_URL}/admin/process-and-save-document`);

      let progressInterval = null;

      // Track real upload progress until the file reaches the backend.
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) {
          const percentComplete = Math.round((event.loaded / event.total) * 50);
          progressBar.style.width = percentComplete + "%";
        }
      };

      // Show simulated progress while the backend processes and saves the document.
      xhr.upload.onload = () => {
        let fakeProgress = 50;
        progressInterval = setInterval(() => {
          if (fakeProgress < 90) {
            fakeProgress += 1;
            progressBar.style.width = fakeProgress + "%";
          }
        }, 1000);
      };

      // Handle the final backend response after processing is completed.
      xhr.onload = async () => {
        if (progressInterval) clearInterval(progressInterval);

        if (xhr.status >= 200 && xhr.status < 300) {
          const data = JSON.parse(xhr.responseText);

          progressBar.style.width = "100%";

          let successMessage = "Document saved successfully.";
          if (docType === "Academic Calendar") {
            successMessage = `Academic calendar saved with ${data.saved_events_count || 0} event(s).`;
          } else if (docType === "Regulations") {
            successMessage = `Regulation saved with ${data.saved_chunks_count || 0} chunk(s).`;
          } else if (docType === "Admission Guide") {
            successMessage = `Admission Guide saved with ${data.saved_chunks_count || 0} chunk(s).`;
          }

          kbStatus.textContent = successMessage;
          showFeedback(successMessage, "success", { title: "Uploaded Successfully" });

          await fetchRecentDocuments();
          loadRecentUpdatesPage();
          await fetchAdminOverview();
          AdminView.updateOverviewStats();
          AdminView.updateLatestActivity();
          AdminView.updateChart();
          AdminView.updateTimelineChart();

          // Reset upload form after successful processing.
          if ($("adminFileInput")) $("adminFileInput").value = "";
          if ($("documentType")) $("documentType").value = "";
          if ($("adminTargetCategory")) $("adminTargetCategory").value = "";
          if ($("updateCollege")) $("updateCollege").value = "";
          if ($("fileNamePreview")) $("fileNamePreview").textContent = "";

          setTimeout(() => {
            progressWrap.classList.add("hidden");
            progressBar.style.width = "0%";
            kbButton.disabled = false;
          }, 1500);

        } else {
          let errorMessage = "Failed to save document.";
          try {
            const errData = JSON.parse(xhr.responseText);
            if (errData.detail) errorMessage = errData.detail;
          } catch (e) { }

          handleUploadError(errorMessage);
        }
      };

      xhr.onerror = () => {
        if (progressInterval) clearInterval(progressInterval);
        handleUploadError("Network error occurred during upload.");
      };

      // Reset upload UI and show the error message.
      function handleUploadError(message) {
        progressWrap.classList.add("hidden");
        progressBar.style.width = "0%";
        kbStatus.textContent = message;
        showFeedback(message, "error");
        kbButton.disabled = false;
      }

      xhr.send(formData);

    } catch (error) {
      kbButton.disabled = false;
      progressWrap.classList.add("hidden");
      progressBar.style.width = "0%";
      kbStatus.textContent = error.message;
      showFeedback(error.message, "error");
    }

  }
};


/**
 * Benefit:
 *     Displays extracted academic calendar events in a preview table.
 *
 * What it does:
 *     Shows the events preview section, clears old rows, displays a fallback
 *     message when no events are found, and renders each event with dates and
 *     a target user type selector.
 */
function renderExtractedEventsTable(events, defaultUserType) {
  const table = $("eventsPreviewTable");
  const section = $("eventsPreviewSection");

  if (!table || !section) return;

  section.classList.remove("hidden");
  section.style.display = "block";

  table.innerHTML = "";

  if (!events || !events.length) {
    table.innerHTML = `
      <tr>
        <td colspan="6" style="text-align:center;color:#888;">
          No academic events found
        </td>
      </tr>
    `;
    return;
  }

  events.forEach((event) => {
    const row = document.createElement("tr");

    row.innerHTML = `
      <td>${event.title || "—"}</td>
      <td>${event.startdate || "—"}</td>
      <td>${event.enddate || "—"}</td>
      <td>${event.histartdate || "—"}</td>
      <td>${event.hienddate || "—"}</td>
      <td>
        <select class="event-user-type">
          <option value="student" ${defaultUserType === "student" ? "selected" : ""}>Student</option>
          <option value="faculty" ${defaultUserType === "faculty" ? "selected" : ""}>Faculty</option>
          <option value="all" ${defaultUserType === "all" ? "selected" : ""}>All Users</option>
        </select>
      </td>
    `;

    table.appendChild(row);
  });
}


/* =========================================
   DELETE SELECTED UPDATES
========================================= */

/**
 * Benefit:
 *     Deletes selected updates from the recent updates list.
 *
 * What it does:
 *     Checks selected update rows, asks for confirmation, removes them from
 *     updatesHistory, saves the updated history, reloads the page, and refreshes
 *     dashboard widgets.
 */
async function deleteSelectedUpdates() {
  const checkedBoxes = document.querySelectorAll(".update-check:checked");

  if (checkedBoxes.length === 0) {
    showFeedback("Please select at least one update to delete", "warning");
    return;
  }

  const ok = await mkConfirmDelete();
  if (!ok) return;

  const filesToDelete = Array.from(checkedBoxes).map(cb => cb.value);

  updatesHistory = updatesHistory.filter(u => !filesToDelete.includes(u.file));
  saveUpdatesHistory();
  loadRecentUpdatesPage();

  showFeedback(`${filesToDelete.length} update(s) deleted successfully`, "success");

  AdminView.updateOverviewStats();
  AdminView.updateLatestActivity();
  AdminView.updateChart();
  AdminView.updateTimelineChart();
}


/* =========================================
   FILTER UPDATES BY TYPE AND CATEGORY
========================================= */

/**
 * Benefit:
 *     Filters recent updates based on selected criteria.
 *
 * What it does:
 *     Reads type, category, and college filter values, keeps only matching
 *     updates from updatesHistory, then reloads the recent updates page with
 *     the filtered data.
 */
function filterUpdates() {
  const typeFilter = $("filterType").value;
  const categoryFilter = $("filterCategory").value;
  const collegeFilter = $("filterCollege").value;

  const filtered = updatesHistory.filter(u => {
    const matchType = typeFilter === "all" || u.type === typeFilter;
    const matchCategory = categoryFilter === "all" || u.category === categoryFilter;
    const uCollege = u.college || "all";
    const matchCollege =
      collegeFilter === "all" ||
      uCollege === collegeFilter ||
      uCollege === "all";

    return matchType && matchCategory && matchCollege;
  });

  loadRecentUpdatesPage(filtered);
}


//sara-start (3)
/* =========================================
   NOTIFICATIONS PAGE CONTROLLER
========================================= */
const AdminNotifyController = {


  updatePreview() {
    const titleInput = $("notifyTitle");
    const messageInput = $("notifyMessage");
    const previewTitle = $("previewTitle");
    const previewMessage = $("previewMessage");

    if (!previewTitle || !previewMessage) return;

    previewTitle.textContent =
      titleInput?.value.trim() || "Title will appear here";

    previewMessage.textContent =
      messageInput?.value.trim() || "Message preview will appear here";
  },

  async sendNotification() {
    const title = $("notifyTitle")?.value.trim() || "";
    const message = $("notifyMessage")?.value.trim() || "";
    const audience = $("notifyAudience")?.value || "all";
    const type = $("notifyType")?.value || "announcement";
    const college = $("notifyCollege")?.value || "";
    const scheduleValue = $("notifyDateTime")?.value || "";

    if (!title || !message) {
      showFeedback("Please enter both title and message", "error");
      return;
    }

    if (!college) {
      showFeedback("Please select college", "error");
      return;
    }

    if (!scheduleValue) {
      showFeedback("Please select date and time", "error");
      return;
    }

    const parsedDate = new Date(scheduleValue);
    if (isNaN(parsedDate.getTime())) {
      showFeedback("Invalid date format. Please select again.", "error");
      return;
    }

    try {
      await request(`${API_BASE_URL}/admin/notifications`, {
        method: "POST",
        headers: getAuthHeaders(true),
        body: JSON.stringify({
          title: title,
          message: message,
          audience: audience,
          notification_type: type,
          college_name: college,
          schedule_time: parsedDate.toISOString()
        })
      });

      showFeedback("Notification scheduled successfully", "success");

      if ($("notifyTitle")) $("notifyTitle").value = "";
      if ($("notifyMessage")) $("notifyMessage").value = "";
      if ($("notifyCollege")) $("notifyCollege").value = "";
      if ($("notifyAudience")) $("notifyAudience").value = "all";
      if ($("notifyType")) $("notifyType").value = "announcement";
      if ($("notifyDateTime")) $("notifyDateTime").value = "";

      if (sendDateFlatpickrInstance) {
        sendDateFlatpickrInstance.clear();
      }

      this.updatePreview();
      await refreshNotificationsHistory();

    } catch (error) {
      console.error("Send notification error:", error);
      showFeedback(error.message || "Cannot connect to server.", "error");
    }
  }
};
//sara-end (3)

//sara-start (4)
//يا شذا هذه الدالة حذف 
// /* =========================================
//    NOTIFICATION DISPLAY HELPERS
// ========================================= */
// /**
//  * Get notification status (Sent or Scheduled)
//  * @param {Object} notification - Notification object
//  * @returns {string} Status text
//  */
// function getNotificationStatus(notification) {
//   if (!notification.scheduledDate) return "Sent";

//   const now = new Date();
//   const scheduled = new Date(notification.scheduledDate);

//   return scheduled > now ? "Scheduled" : "Sent";
// }
//sara-end (4)


//sara-start (5)
// /**
//  * Format timestamp for display
//  * @param {number} timestamp - Unix timestamp
//  * @returns {string} Formatted date string
//  */
// function formatDisplayTime(timestamp) {
//   const date = new Date(timestamp);

//   // Force English locale with explicit options
//   return date.toLocaleString("en-US", {
//     year: "numeric",
//     month: "long",
//     day: "numeric",
//     hour: "2-digit",
//     minute: "2-digit",
//     hour12: true,
//     numberingSystem: "latn" // Force Western numerals
//   });
// }

//sara-end (5)


//sara-start (6)
/* =========================================
   LOAD NOTIFICATIONS HISTORY TABLE
========================================= */
function loadNotificationsHistory(filteredList = notificationsList) {
  const table = $("notificationsHistoryTable");
  if (!table) return;

  table.innerHTML = "";

  if (!filteredList.length) {
    table.innerHTML = `
      <tr>
        <td colspan="7" style="text-align:center; color:#888;">
          No notifications sent yet
        </td>
      </tr>
    `;
    return;
  }

  filteredList.forEach((n) => {
    const isSent = n.status === "sent";
    const row = document.createElement("tr");

    row.innerHTML = `
      <td>${n.title}</td>
      <td>${normalizeAudienceForDisplay(n.audience)}</td>
      <td>${n.type}</td>
      <td>${normalizeCollegeForDisplay(n.college)}</td>
      <td>${formatDisplayTime(n.schedule_time)}</td>
      <td>
        <span class="status-badge ${isSent ? "sent" : "scheduled"}">
          ${isSent ? "Sent" : "Scheduled"}
        </span>
      </td>
      <td class="actions-cell">
        <button class="icon-btn view" onclick="viewNotification(${n.id})" title="View">
          <svg viewBox="0 0 24 24"><path d="M12 5c-7 0-10 7-10 7s3 7 10 7 10-7 10-7-3-7-10-7zm0 11a4 4 0 1 1 0-8 4 4 0 0 1 0 8z"/></svg>
        </button>
        ${isSent
        ? ""
        : `
          <button class="icon-btn edit" onclick="editNotification(${n.id})" title="Edit">
            <svg viewBox="0 0 24 24"><path d="M3 17.25V21h3.75l11-11.03-3.75-3.75L3 17.25zm18-11.5a1 1 0 0 0 0-1.41l-1.34-1.34a1 1 0 0 0-1.41 0l-1.83 1.83 3.75 3.75L21 5.75z"/></svg>
          </button>
          <button class="icon-btn delete" onclick="deleteNotification(${n.id})" title="Delete">
            <svg viewBox="0 0 24 24"><path d="M6 7h12l-1 14H7L6 7zm3-3h6l1 2H8l1-2z"/></svg>
          </button>
        `
      }
      </td>
    `;

    table.appendChild(row);
  });
}
//sara-end (6)

//sara-start (7)
/* =========================================
   APPLY NOTIFICATION FILTERS
========================================= */
async function applyNotificationFilters() {
  try {
    await refreshNotificationsHistory(getCurrentFilters());
  } catch (error) {
    console.error("Apply filters error:", error);
    showFeedback(error.message || "Failed to filter notifications.", "error");
  }
}
//sara-end (7)


//sara-start (8)
/* =========================================
   RESET FILTERS
========================================= */
async function resetFilters() {
  if ($("filterAudience")) $("filterAudience").value = "all";
  if ($("filterType")) $("filterType").value = "all";
  if ($("filterStatus")) $("filterStatus").value = "all";
  if ($("filterCollege")) $("filterCollege").value = "all";
  if ($("filterDateFrom")) $("filterDateFrom").value = "";
  if ($("filterDateTo")) $("filterDateTo").value = "";

  if (filterDateFromInstance) filterDateFromInstance.clear();
  if (filterDateToInstance) filterDateToInstance.clear();

  await refreshNotificationsHistory();
  showFeedback("Filters reset successfully", "info", { duration: 1500 });
}
//sara-end(8)


/* =========================================
   NOTIFICATION MODAL - VIEW MODE
========================================= */
//sara-start (9) 
//let currentEditId = null; هذا السطر حذف يا شذا 
//sara-end (9)

//sara-start (10)
async function viewNotification(id) {
  try {
    const n = await request(
      `${API_BASE_URL}/admin/notifications/${id}`,
      {
        method: "GET",
        headers: getAuthHeaders(false)
      }
    );

    $("modalTitle").textContent = n.title;
    $("modalMessage").textContent = n.message;
    $("modalAudience").textContent = normalizeAudienceForDisplay(n.audience);
    $("modalType").textContent = n.type;
    $("modalCollege").textContent = normalizeCollegeForDisplay(n.college);
    $("modalSchedule").textContent = formatDisplayTime(n.schedule_time);

    $("modalViewSection")?.classList.remove("hidden");
    $("modalEditSection")?.classList.add("hidden");
    $("notificationModal")?.classList.remove("hidden");

  } catch (error) {
    console.error("View notification error:", error);
    showFeedback(error.message || "Failed to load notification.", "error");
  }
}
//sara-end (10)

//sara-start (11)
/* =========================================
   NOTIFICATION MODAL - EDIT MODE
========================================= */
function editNotification(id) {
  const n = notificationsList.find((item) => item.id === id);

  if (!n) {
    showFeedback("Notification not found", "error");
    return;
  }

  if (n.status === "sent") {
    showFeedback("Cannot edit a notification that has already been sent", "error");
    return;
  }

  currentEditId = id;

  $("modalViewSection")?.classList.add("hidden");
  $("modalEditSection")?.classList.remove("hidden");

  if ($("editTitle")) $("editTitle").value = n.title;
  if ($("editMessage")) $("editMessage").value = n.message;
  if ($("editAudience")) $("editAudience").value = n.audience;
  if ($("editType")) $("editType").value = n.type;
  if ($("editCollege")) $("editCollege").value = n.college === "All Colleges" ? "all" : n.college;

  const editInput = $("editSchedule");
  if (!editInput) return;

  if (editScheduleFlatpickrInstance) {
    editScheduleFlatpickrInstance.destroy();
    editScheduleFlatpickrInstance = null;
  }

  editInput.value = "";
  editInput.removeAttribute("readonly");
  editInput._flatpickr = undefined;

  const altInput = editInput.parentNode?.querySelector(".flatpickr-input");
  if (altInput && altInput !== editInput) {
    altInput.remove();
  }

  setTimeout(() => {
    editScheduleFlatpickrInstance = flatpickr(editInput, {
      enableTime: true,
      dateFormat: "Y-m-d H:i",
      altInput: true,
      altFormat: "F j, Y h:i K",
      time_24hr: false,
      locale: "en",
      disableMobile: true
    });

    if (n.schedule_time) {
      editScheduleFlatpickrInstance.setDate(new Date(n.schedule_time), true);
    }
  }, 100);

  $("notificationModal")?.classList.remove("hidden");
}
//sara-end (11)


//sara-start (12)
/* =========================================
   SAVE NOTIFICATION EDIT
========================================= */
async function saveEdit() {
  const existing = notificationsList.find((item) => item.id === currentEditId);

  if (!existing) {
    showFeedback("Notification not found", "error");
    return;
  }

  if (existing.status === "sent") {
    showFeedback("Cannot edit a notification that has already been sent", "error");
    return;
  }

  let scheduleISO = null;

  if (editScheduleFlatpickrInstance) {
    const selectedDates = editScheduleFlatpickrInstance.selectedDates;
    if (selectedDates && selectedDates.length > 0) {
      scheduleISO = selectedDates[0].toISOString();
    }
  }

  if (!scheduleISO) {
    showFeedback("Please select date and time", "error");
    return;
  }

  try {
    await request(
      `${API_BASE_URL}/admin/notifications/${currentEditId}`,
      {
        method: "PUT",
        headers: getAuthHeaders(true),
        body: JSON.stringify({
          title: $("editTitle")?.value.trim() || "",
          message: $("editMessage")?.value.trim() || "",
          audience: $("editAudience")?.value || "all",
          notification_type: $("editType")?.value || "announcement",
          college_name: $("editCollege")?.value || "all",
          schedule_time: scheduleISO
        })
      }
    );

    closeModal();
    await refreshNotificationsHistory(getCurrentFilters());
    showFeedback("Notification updated successfully", "success");

  } catch (error) {
    console.error("Save edit error:", error);
    showFeedback(error.message || "Failed to update notification.", "error");
  }
}
//sara-end (12)

/* =========================================
   CLOSE NOTIFICATION MODAL
========================================= */
/**
 * Close notification modal and reset edit state
 */
function closeModal() {
  $("notificationModal").classList.add("hidden");
}

//sara-start (13)
/* =========================================
   DELETE NOTIFICATION
========================================= */
async function deleteNotification(id) {
  const existing = notificationsList.find((item) => item.id === id);

  if (!existing) {
    showFeedback("Notification not found", "error");
    return;
  }

  if (existing.status === "sent") {
    showFeedback("Cannot delete a notification that has already been sent", "error");
    return;
  }

  const ok = await mkConfirmDelete();
  if (!ok) return;

  try {
    await request(
      `${API_BASE_URL}/admin/notifications/${id}`,
      {
        method: "DELETE",
        headers: getAuthHeaders(false)
      }
    );

    await refreshNotificationsHistory(getCurrentFilters());
    showFeedback("Notification deleted successfully", "success");

  } catch (error) {
    console.error("Delete notification error:", error);
    showFeedback(error.message || "Failed to delete notification.", "error");
  }
}
//sara-end (13)

/* =========================================
   PAGE INITIALIZATION
========================================= */
document.addEventListener("DOMContentLoaded", async () => {
  // Migrate old date formats to dd/mm/yyyy
  migrateUpdatesDates();

  // Initialize overview page
  await fetchAdminOverview();
  AdminView.updateOverviewStats();
  AdminView.updateChart();
  await fetchActivityData();
  AdminView.updateTimelineChart();


  // Initialize history pages
  //sara-start (14)
  //loadNotificationsHistory();هذا السطر حذف وبداله اللي تحته
  refreshNotificationsHistory().catch(err => {
    console.error("Initial notifications load error:", err);
  });

  const notifyTitle = $("notifyTitle");
  const notifyMessage = $("notifyMessage");

  if (notifyTitle) {
    notifyTitle.addEventListener("input", () => {
      AdminNotifyController.updatePreview();
    });
  }

  if (notifyMessage) {
    notifyMessage.addEventListener("input", () => {
      AdminNotifyController.updatePreview();
    });
  }
  //sara-end (14)
  await fetchRecentDocuments();
  loadRecentUpdatesPage();

  /* =====================================================
     NOTIFICATION SCHEDULER (SEND PAGE)
     - Stores value in 24-hour format for system processing
     - Displays user-friendly 12-hour format with AM/PM
     - Forces English locale and Western numerals
     - Disables native mobile pickers to ensure consistency
  ====================================================== */
  const dateInput = document.getElementById("notifyDateTime");

  if (dateInput) {
    flatpickr(dateInput, {
      enableTime: true,

      // System storage format (do not modify)
      dateFormat: "Y-m-d H:i",

      // Separate visible input for formatted display
      altInput: true,

      // Display format for users (12-hour with AM/PM)
      altFormat: "F j, Y h:i K",

      time_24hr: false,
      locale: "en",
      disableMobile: true,

      // Ensure English numerals even on non-English systems
      onReady: function (selectedDates, dateStr, instance) {
        if (instance.altInput) {
          instance.altInput.setAttribute("lang", "en");
          instance.altInput.style.direction = "ltr";
        }
      }
    });
  }

  /* =====================================================
     DATE RANGE FILTER (HISTORY PAGE)
     - Filters notifications by date range (from/to)
     - Stores value in ISO format for comparisons
     - Displays formatted English date for users
     - Stores instances globally for reset functionality
  ====================================================== */
  const filterDateFromInput = document.getElementById("filterDateFrom");
  const filterDateToInput = document.getElementById("filterDateTo");

  if (filterDateFromInput) {
    window.flatpickrFromInstance = flatpickr(filterDateFromInput, {
      enableTime: false,

      // Internal filter value format
      dateFormat: "Y-m-d",

      // User display field
      altInput: true,
      altFormat: "F j, Y",

      locale: "en",
      disableMobile: true,

      // Force English numerals and left-to-right layout
      onReady: function (selectedDates, dateStr, instance) {
        if (instance.altInput) {
          instance.altInput.setAttribute("lang", "en");
          instance.altInput.style.direction = "ltr";
        }
      }
    });
  }

  if (filterDateToInput) {
    window.flatpickrToInstance = flatpickr(filterDateToInput, {
      enableTime: false,

      // Internal filter value format
      dateFormat: "Y-m-d",

      // User display field
      altInput: true,
      altFormat: "F j, Y",

      locale: "en",
      disableMobile: true,

      // Force English numerals and left-to-right layout
      onReady: function (selectedDates, dateStr, instance) {
        if (instance.altInput) {
          instance.altInput.setAttribute("lang", "en");
          instance.altInput.style.direction = "ltr";
        }
      }
    });
  }
});


//sara-start (15)
// هذه الاكواد اضافة جديده 

function initNotificationPreviewListeners() {
  const notifyTitle = $("notifyTitle");
  const notifyMessage = $("notifyMessage");

  if (notifyTitle) {
    notifyTitle.addEventListener("input", () => {
      AdminNotifyController.updatePreview();
    });
  }

  if (notifyMessage) {
    notifyMessage.addEventListener("input", () => {
      AdminNotifyController.updatePreview();
    });
  }
}

function initNotificationCreatePageCalendar() {
  const dateInput = $("notifyDateTime");
  if (!dateInput || typeof flatpickr === "undefined") return;

  sendDateFlatpickrInstance = flatpickr(dateInput, {
    enableTime: true,
    dateFormat: "Y-m-d H:i",
    altInput: true,
    altFormat: "F j, Y h:i K",
    time_24hr: false,
    locale: "en",
    disableMobile: true
  });
}

function initNotificationHistoryCalendars() {
  if (typeof flatpickr === "undefined") return;

  const fromInput = $("filterDateFrom");
  const toInput = $("filterDateTo");

  if (fromInput) {
    filterDateFromInstance = flatpickr(fromInput, {
      enableTime: false,
      dateFormat: "Y-m-d",
      altInput: true,
      altFormat: "F j, Y",
      locale: "en",
      disableMobile: true
    });
  }

  if (toInput) {
    filterDateToInstance = flatpickr(toInput, {
      enableTime: false,
      dateFormat: "Y-m-d",
      altInput: true,
      altFormat: "F j, Y",
      locale: "en",
      disableMobile: true
    });
  }
}

async function initAdminNotificationsPage() {
  initNotificationPreviewListeners();
  initNotificationCreatePageCalendar();
  initNotificationHistoryCalendars();
  AdminNotifyController.updatePreview();

  if ($("notificationsHistoryTable")) {
    await refreshNotificationsHistory();
  }
}

//sara-end (15)



// Stores the recent uploaded documents returned from the backend.
// This shared array is used by the table, filters, and delete actions.
let updatesHistory = [];


/**
 * Benefit:
 *     Loads recent uploaded documents from the backend.
 *
 * What it does:
 *     Calls the admin documents API, saves the returned documents into
 *     updatesHistory, and resets the list if the request fails.
 */
async function fetchRecentDocuments() {
  try {
    console.log("fetchRecentDocuments called");

    // Request the latest uploaded documents from the backend.
    const res = await fetch(`${API_BASE_URL}/admin/documents`);
    console.log("documents status:", res.status);

    // Parse the backend response and store the documents list.
    const d = await res.json();
    console.log("documents data:", d);

    // Keep an empty array as fallback if the backend returns no documents.
    updatesHistory = d.documents || [];
  } catch (e) {
    // If loading documents fails, clear the local list to avoid showing stale data.
    console.error("fetchRecentDocuments:", e);
    updatesHistory = [];
  }
}


/**
 * Benefit:
 *     Renders recent uploaded documents in the admin updates table.
 *
 * What it does:
 *     Clears the table, shows an empty-state row if there are no documents,
 *     and displays each document with its filename, type, category, college,
 *     upload date, and selection checkbox.
 */
function loadRecentUpdatesPage(list = updatesHistory) {
  const table = $("recentUpdatesTable");
  if (!table) return;

  // Clear old rows before rendering the current list.
  table.innerHTML = "";

  // Show a clear empty state when there are no uploaded documents.
  if (!list.length) {
    table.innerHTML = `
      <tr>
        <td colspan="6" style="text-align:center;color:#888;">No updates yet</td>
      </tr>
    `;
    return;
  }

  list.forEach(u => {
    // Use fallback values so missing backend fields do not break the table UI.
    const id = u.doc_id ?? "—";
    const name = u.filename ?? "—";
    const type = u.doc_type ?? "—";
    const cat = u.category ?? "—";
    const col = u.college ?? "—";
    const date = u.created_at ?? "";

    const row = document.createElement("tr");

    // Build one table row for each uploaded document.
    row.innerHTML = `
      <td><input type="checkbox" class="update-check" value="${id}"></td>
      <td>${name}</td>
      <td>${type}</td>
      <td>${cat}</td>
      <td>${col}</td>
      <td>${date ? formatDate(date) : "—"}</td>
    `;

    table.appendChild(row);
  });
}


/**
 * Benefit:
 *     Filters the recent documents table using selected filter values.
 *
 * What it does:
 *     Reads document type, category, and college filters, compares them with
 *     updatesHistory, then reloads the table with matching documents only.
 */
function filterUpdates() {
  // Use "all" as the default filter value if an element is missing.
  const t = $("filterType")?.value || "all";
  const c = $("filterCategory")?.value || "all";
  const col = $("filterCollege")?.value || "all";

  const filtered = updatesHistory.filter(u => {
    // Normalize missing values before comparison.
    const uT = u.doc_type || "";
    const uC = u.category || "";
    const uCol = u.college || "";

    // Keep the document only if it matches all selected filters.
    return (
      (t === "all" || uT === t) &&
      (c === "all" || uC === c) &&
      (col === "all" || uCol === col)
    );
  });

  // Re-render the table using the filtered result.
  loadRecentUpdatesPage(filtered);
}


/**
 * Benefit:
 *     Deletes selected uploaded documents.
 *
 * What it does:
 *     Reads checked rows, confirms deletion, sends DELETE requests to the backend,
 *     removes successfully selected documents from local history, reloads the table,
 *     and shows the delete result to the admin.
 */
async function deleteSelectedUpdates() {
  const boxes = document.querySelectorAll(".update-check:checked");

  // Stop deletion if the admin did not select any document.
  if (!boxes.length) {
    showFeedback("Select at least one item", "warning");
    return;
  }

  // Ask for confirmation before deleting documents.
  const ok = await mkConfirmDelete();
  if (!ok) return;

  // Collect selected document IDs from checkbox values.
  const ids = Array.from(boxes).map(b => b.value);

  // Read auth token so protected delete requests can be authorized.
  const token = localStorage.getItem("authToken");
  let count = 0;

  // Delete each selected document from the backend.
  for (const id of ids) {
    try {
      const res = await fetch(`${API_BASE_URL}/admin/documents/${id}`, {
        method: "DELETE",
        headers: {
          ...(token ? { Authorization: `Bearer ${token}` } : {})
        }
      });

      // Count only successful deletions.
      if (res.ok) {
        count++;
      } else {
        console.error(`Delete failed for ID ${id}:`, await res.text());
      }
    } catch (e) {
      console.error("Delete failed:", e);
    }
  }

  // Remove deleted documents from the local table data.
  updatesHistory = updatesHistory.filter(
    u => !ids.includes(String(u.doc_id))
  );

  // Refresh the table and show the final delete count.
  loadRecentUpdatesPage();
  showFeedback(`${count} document(s) deleted`, "success");
}


/**
 * Benefit:
 *     Loads admin dashboard summary statistics.
 *
 * What it does:
 *     Gets totals for users, documents, and notifications, updates AdminModel,
 *     then displays the latest uploaded document and latest notification.
 */
async function fetchAdminOverview() {
  try {
    // Request dashboard overview data from the backend.
    const data = await request(`${API_BASE_URL}/admin/overview`, {
      method: "GET",
      headers: getAuthHeaders(false)
    });

    // Store overview stats in AdminModel so dashboard widgets can use them.
    AdminModel.stats.users = data.stats.users || 0;
    AdminModel.stats.docs = data.stats.docs || 0;
    AdminModel.stats.notifications = data.stats.notifications || 0;

    const lastUpload = data.latest_activity?.last_upload;
    const lastNotification = data.latest_activity?.last_notification;

    // Update latest uploaded document text if the UI element exists.
    if ($("lastUpload")) {
      $("lastUpload").textContent = lastUpload
        ? `${lastUpload.filename} (${lastUpload.category || "—"})`
        : "No uploads yet";
    }

    // Update latest notification text if the UI element exists.
    if ($("lastNotification")) {
      $("lastNotification").textContent = lastNotification
        ? `${lastNotification.title} → ${lastNotification.audience || "all"}`
        : "No notifications yet";
    }

  } catch (error) {
    console.error("fetchAdminOverview error:", error);
  }
}


/**
 * Benefit:
 *     Loads monthly activity data for admin charts.
 *
 * What it does:
 *     Gets monthly uploads and notifications from the backend, then converts
 *     the response into an array format suitable for chart rendering.
 */
async function fetchActivityData() {
  try {
    // Request monthly activity counts from the backend.
    const data = await request(`${API_BASE_URL}/admin/activity`, {
      method: "GET",
      headers: getAuthHeaders(false)
    });

    console.log("activity data:", data);

    // Convert backend object format into chart-friendly array format.
    AdminModel.activityLog = Object.keys(data).map(key => ({
      month: key,
      uploads: data[key].uploads,
      notifications: data[key].notifications
    }));

  } catch (error) {
    console.error("fetchActivityData error:", error);
  }
}


///////////////////////////////////////////