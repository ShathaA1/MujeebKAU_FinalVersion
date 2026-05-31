/* =========================================
   MUJEEBKAU/js/admin-notifications.js
   Admin Notifications Only
========================================= */

// const API_BASE_URL = "http://127.0.0.1:8000";

// let notificationsList = [];
// let currentEditId = null;

// let editScheduleFlatpickrInstance = null;
// let filterDateFromInstance = null;
// let filterDateToInstance = null;
// let sendDateFlatpickrInstance = null;

// function $(id) {
//   return document.getElementById(id);
// }

// function getToken() {
//   return localStorage.getItem("mk_token");
// }

// function getAuthHeaders(includeJson = true) {
//   const headers = {};

//   if (includeJson) {
//     headers["Content-Type"] = "application/json";
//   }

//   const token = getToken();
//   if (token) {
//     headers["Authorization"] = `Bearer ${token}`;
//   }

//   return headers;
// }

// async function request(url, options = {}) {
//   const response = await fetch(url, options);

//   let data = null;
//   try {
//     data = await response.json();
//   } catch {
//     data = null;
//   }

//   if (!response.ok) {
//     const errorMessage =
//       (data && (data.detail || data.message || data.error)) ||
//       "Request failed";
//     throw new Error(errorMessage);
//   }

//   return data;
// }

// function formatDisplayTime(dateValue) {
//   const date = new Date(dateValue);

//   return date.toLocaleString("en-US", {
//     year: "numeric",
//     month: "long",
//     day: "numeric",
//     hour: "2-digit",
//     minute: "2-digit",
//     hour12: true
//   });
// }

// function normalizeAudienceForDisplay(audience) {
//   if (audience === "student") return "student";
//   if (audience === "faculty") return "faculty";
//   return "all";
// }

// function normalizeCollegeForDisplay(college) {
//   if (!college || college === "all") return "All Colleges";
//   return college;
// }

// function getCurrentFilters() {
//   return {
//     audience: $("filterAudience")?.value || "all",
//     type: $("filterType")?.value || "all",
//     status: $("filterStatus")?.value || "all",
//     college: $("filterCollege")?.value || "all",
//     dateFrom: $("filterDateFrom")?.value || "",
//     dateTo: $("filterDateTo")?.value || ""
//   };
// }

// async function fetchNotifications(filters = {}) {
//   const params = new URLSearchParams();

//   if (filters.audience && filters.audience !== "all") {
//     params.append("audience", filters.audience);
//   }

//   if (filters.type && filters.type !== "all") {
//     params.append("notification_type", filters.type);
//   }

//   if (filters.status && filters.status !== "all") {
//     params.append("status_filter", filters.status);
//   }

//   if (filters.college && filters.college !== "all") {
//     params.append("college_name", filters.college);
//   }

//   if (filters.dateFrom) {
//     params.append("date_from", filters.dateFrom);
//   }

//   if (filters.dateTo) {
//     params.append("date_to", filters.dateTo);
//   }

//   const queryString = params.toString()
//     ? `?${params.toString()}`
//     : "";

//   const data = await request(
//     `${API_BASE_URL}/admin/notifications${queryString}`,
//     {
//       method: "GET",
//       headers: getAuthHeaders(false)
//     }
//   );

//   return data.notifications || [];
// }

// async function refreshNotificationsHistory(filters = null) {
//   const activeFilters = filters || getCurrentFilters();
//   notificationsList = await fetchNotifications(activeFilters);
//   loadNotificationsHistory(notificationsList);
// }


//-----------------------------------------------


// const AdminNotifyController = {
//   applyTemplate(value) {
//     if (!value) return;

//     const messageInput = $("notifyMessage");
//     if (messageInput) {
//       messageInput.value = value;
//     }

//     this.updatePreview();
//   },

//   updatePreview() {
//     const titleInput = $("notifyTitle");
//     const messageInput = $("notifyMessage");
//     const previewTitle = $("previewTitle");
//     const previewMessage = $("previewMessage");

//     if (!previewTitle || !previewMessage) return;

//     previewTitle.textContent =
//       titleInput?.value.trim() || "Title will appear here";

//     previewMessage.textContent =
//       messageInput?.value.trim() || "Message preview will appear here";
//   },

//   async sendNotification() {
//     const title = $("notifyTitle")?.value.trim() || "";
//     const message = $("notifyMessage")?.value.trim() || "";
//     const audience = $("notifyAudience")?.value || "all";
//     const type = $("notifyType")?.value || "announcement";
//     const college = $("notifyCollege")?.value || "";
//     const scheduleValue = $("notifyDateTime")?.value || "";

//     if (!title || !message) {
//       showFeedback("Please enter both title and message", "error");
//       return;
//     }

//     if (!college) {
//       showFeedback("Please select college", "error");
//       return;
//     }

//     if (!scheduleValue) {
//       showFeedback("Please select date and time", "error");
//       return;
//     }

//     const parsedDate = new Date(scheduleValue);
//     if (isNaN(parsedDate.getTime())) {
//       showFeedback("Invalid date format. Please select again.", "error");
//       return;
//     }

//     try {
//       await request(`${API_BASE_URL}/admin/notifications`, {
//         method: "POST",
//         headers: getAuthHeaders(true),
//         body: JSON.stringify({
//           title: title,
//           message: message,
//           audience: audience,
//           notification_type: type,
//           college_name: college,
//           schedule_time: parsedDate.toISOString()
//         })
//       });

//       showFeedback("Notification scheduled successfully", "success");

//       if ($("notifyTitle")) $("notifyTitle").value = "";
//       if ($("notifyMessage")) $("notifyMessage").value = "";
//       if ($("notifyCollege")) $("notifyCollege").value = "";
//       if ($("notifyAudience")) $("notifyAudience").value = "all";
//       if ($("notifyType")) $("notifyType").value = "announcement";
//       if ($("notifyDateTime")) $("notifyDateTime").value = "";

//       if (sendDateFlatpickrInstance) {
//         sendDateFlatpickrInstance.clear();
//       }

//       this.updatePreview();
//       await refreshNotificationsHistory();

//     } catch (error) {
//       console.error("Send notification error:", error);
//       showFeedback(error.message || "Cannot connect to server.", "error");
//     }
//   }
// };

// function loadNotificationsHistory(filteredList = notificationsList) {
//   const table = $("notificationsHistoryTable");
//   if (!table) return;

//   table.innerHTML = "";

//   if (!filteredList.length) {
//     table.innerHTML = `
//       <tr>
//         <td colspan="7" style="text-align:center; color:#888;">
//           No notifications sent yet
//         </td>
//       </tr>
//     `;
//     return;
//   }

//   filteredList.forEach((n) => {
//     const isSent = n.status === "sent";
//     const row = document.createElement("tr");

//     row.innerHTML = `
//       <td>${n.title}</td>
//       <td>${normalizeAudienceForDisplay(n.audience)}</td>
//       <td>${n.type}</td>
//       <td>${normalizeCollegeForDisplay(n.college)}</td>
//       <td>${formatDisplayTime(n.schedule_time)}</td>
//       <td>
//         <span class="status-badge ${isSent ? "sent" : "scheduled"}">
//           ${isSent ? "Sent" : "Scheduled"}
//         </span>
//       </td>
//       <td class="actions-cell">
//         <button class="icon-btn view" onclick="viewNotification(${n.id})" title="View">
//           <svg viewBox="0 0 24 24"><path d="M12 5c-7 0-10 7-10 7s3 7 10 7 10-7 10-7-3-7-10-7zm0 11a4 4 0 1 1 0-8 4 4 0 0 1 0 8z"/></svg>
//         </button>
//         ${
//           isSent
//             ? ""
//             : `
//           <button class="icon-btn edit" onclick="editNotification(${n.id})" title="Edit">
//             <svg viewBox="0 0 24 24"><path d="M3 17.25V21h3.75l11-11.03-3.75-3.75L3 17.25zm18-11.5a1 1 0 0 0 0-1.41l-1.34-1.34a1 1 0 0 0-1.41 0l-1.83 1.83 3.75 3.75L21 5.75z"/></svg>
//           </button>
//           <button class="icon-btn delete" onclick="deleteNotification(${n.id})" title="Delete">
//             <svg viewBox="0 0 24 24"><path d="M6 7h12l-1 14H7L6 7zm3-3h6l1 2H8l1-2z"/></svg>
//           </button>
//         `
//         }
//       </td>
//     `;

//     table.appendChild(row);
//   });
// }

// async function applyNotificationFilters() {
//   try {
//     await refreshNotificationsHistory(getCurrentFilters());
//   } catch (error) {
//     console.error("Apply filters error:", error);
//     showFeedback(error.message || "Failed to filter notifications.", "error");
//   }
// }

// async function resetFilters() {
//   if ($("filterAudience")) $("filterAudience").value = "all";
//   if ($("filterType")) $("filterType").value = "all";
//   if ($("filterStatus")) $("filterStatus").value = "all";
//   if ($("filterCollege")) $("filterCollege").value = "all";
//   if ($("filterDateFrom")) $("filterDateFrom").value = "";
//   if ($("filterDateTo")) $("filterDateTo").value = "";

//   if (filterDateFromInstance) filterDateFromInstance.clear();
//   if (filterDateToInstance) filterDateToInstance.clear();

//   await refreshNotificationsHistory();
//   showFeedback("Filters reset successfully", "info", { duration: 1500 });
// }

// async function viewNotification(id) {
//   try {
//     const n = await request(
//       `${API_BASE_URL}/admin/notifications/${id}`,
//       {
//         method: "GET",
//         headers: getAuthHeaders(false)
//       }
//     );

//     $("modalTitle").textContent = n.title;
//     $("modalMessage").textContent = n.message;
//     $("modalAudience").textContent = normalizeAudienceForDisplay(n.audience);
//     $("modalType").textContent = n.type;
//     $("modalCollege").textContent = normalizeCollegeForDisplay(n.college);
//     $("modalSchedule").textContent = formatDisplayTime(n.schedule_time);

//     $("modalViewSection")?.classList.remove("hidden");
//     $("modalEditSection")?.classList.add("hidden");
//     $("notificationModal")?.classList.remove("hidden");

//   } catch (error) {
//     console.error("View notification error:", error);
//     showFeedback(error.message || "Failed to load notification.", "error");
//   }
// }

// function editNotification(id) {
//   const n = notificationsList.find((item) => item.id === id);

//   if (!n) {
//     showFeedback("Notification not found", "error");
//     return;
//   }

//   if (n.status === "sent") {
//     showFeedback("Cannot edit a notification that has already been sent", "error");
//     return;
//   }

//   currentEditId = id;

//   $("modalViewSection")?.classList.add("hidden");
//   $("modalEditSection")?.classList.remove("hidden");

//   if ($("editTitle")) $("editTitle").value = n.title;
//   if ($("editMessage")) $("editMessage").value = n.message;
//   if ($("editAudience")) $("editAudience").value = n.audience;
//   if ($("editType")) $("editType").value = n.type;
//   if ($("editCollege")) $("editCollege").value = n.college === "All Colleges" ? "all" : n.college;

//   const editInput = $("editSchedule");
//   if (!editInput) return;

//   if (editScheduleFlatpickrInstance) {
//     editScheduleFlatpickrInstance.destroy();
//     editScheduleFlatpickrInstance = null;
//   }

//   editInput.value = "";
//   editInput.removeAttribute("readonly");
//   editInput._flatpickr = undefined;

//   const altInput = editInput.parentNode?.querySelector(".flatpickr-input");
//   if (altInput && altInput !== editInput) {
//     altInput.remove();
//   }

//   setTimeout(() => {
//     editScheduleFlatpickrInstance = flatpickr(editInput, {
//       enableTime: true,
//       dateFormat: "Y-m-d H:i",
//       altInput: true,
//       altFormat: "F j, Y h:i K",
//       time_24hr: false,
//       locale: "en",
//       disableMobile: true
//     });

//     if (n.schedule_time) {
//       editScheduleFlatpickrInstance.setDate(new Date(n.schedule_time), true);
//     }
//   }, 100);

//   $("notificationModal")?.classList.remove("hidden");
// }

// async function saveEdit() {
//   const existing = notificationsList.find((item) => item.id === currentEditId);

//   if (!existing) {
//     showFeedback("Notification not found", "error");
//     return;
//   }

//   if (existing.status === "sent") {
//     showFeedback("Cannot edit a notification that has already been sent", "error");
//     return;
//   }

//   let scheduleISO = null;

//   if (editScheduleFlatpickrInstance) {
//     const selectedDates = editScheduleFlatpickrInstance.selectedDates;
//     if (selectedDates && selectedDates.length > 0) {
//       scheduleISO = selectedDates[0].toISOString();
//     }
//   }

//   if (!scheduleISO) {
//     showFeedback("Please select date and time", "error");
//     return;
//   }

//   try {
//     await request(
//       `${API_BASE_URL}/admin/notifications/${currentEditId}`,
//       {
//         method: "PUT",
//         headers: getAuthHeaders(true),
//         body: JSON.stringify({
//           title: $("editTitle")?.value.trim() || "",
//           message: $("editMessage")?.value.trim() || "",
//           audience: $("editAudience")?.value || "all",
//           notification_type: $("editType")?.value || "announcement",
//           college_name: $("editCollege")?.value || "all",
//           schedule_time: scheduleISO
//         })
//       }
//     );

//     closeModal();
//     await refreshNotificationsHistory(getCurrentFilters());
//     showFeedback("Notification updated successfully", "success");

//   } catch (error) {
//     console.error("Save edit error:", error);
//     showFeedback(error.message || "Failed to update notification.", "error");
//   }
// }

// function closeModal() {
//   $("notificationModal")?.classList.add("hidden");
// }

// async function deleteNotification(id) {
//   const existing = notificationsList.find((item) => item.id === id);

//   if (!existing) {
//     showFeedback("Notification not found", "error");
//     return;
//   }

//   if (existing.status === "sent") {
//     showFeedback("Cannot delete a notification that has already been sent", "error");
//     return;
//   }

//   const ok = await mkConfirmDelete();
//   if (!ok) return;

//   try {
//     await request(
//       `${API_BASE_URL}/admin/notifications/${id}`,
//       {
//         method: "DELETE",
//         headers: getAuthHeaders(false)
//       }
//     );

//     await refreshNotificationsHistory(getCurrentFilters());
//     showFeedback("Notification deleted successfully", "success");

//   } catch (error) {
//     console.error("Delete notification error:", error);
//     showFeedback(error.message || "Failed to delete notification.", "error");
//   }
// }

// function initNotificationPreviewListeners() {
//   const notifyTitle = $("notifyTitle");
//   const notifyMessage = $("notifyMessage");

//   if (notifyTitle) {
//     notifyTitle.addEventListener("input", () => {
//       AdminNotifyController.updatePreview();
//     });
//   }

//   if (notifyMessage) {
//     notifyMessage.addEventListener("input", () => {
//       AdminNotifyController.updatePreview();
//     });
//   }
// }

// function initNotificationCreatePageCalendar() {
//   const dateInput = $("notifyDateTime");
//   if (!dateInput || typeof flatpickr === "undefined") return;

//   sendDateFlatpickrInstance = flatpickr(dateInput, {
//     enableTime: true,
//     dateFormat: "Y-m-d H:i",
//     altInput: true,
//     altFormat: "F j, Y h:i K",
//     time_24hr: false,
//     locale: "en",
//     disableMobile: true
//   });
// }

// function initNotificationHistoryCalendars() {
//   if (typeof flatpickr === "undefined") return;

//   const fromInput = $("filterDateFrom");
//   const toInput = $("filterDateTo");

//   if (fromInput) {
//     filterDateFromInstance = flatpickr(fromInput, {
//       enableTime: false,
//       dateFormat: "Y-m-d",
//       altInput: true,
//       altFormat: "F j, Y",
//       locale: "en",
//       disableMobile: true
//     });
//   }

//   if (toInput) {
//     filterDateToInstance = flatpickr(toInput, {
//       enableTime: false,
//       dateFormat: "Y-m-d",
//       altInput: true,
//       altFormat: "F j, Y",
//       locale: "en",
//       disableMobile: true
//     });
//   }
// }

// async function initAdminNotificationsPage() {
//   initNotificationPreviewListeners();
//   initNotificationCreatePageCalendar();
//   initNotificationHistoryCalendars();
//   AdminNotifyController.updatePreview();

//   if ($("notificationsHistoryTable")) {
//     await refreshNotificationsHistory();
//   }
// }