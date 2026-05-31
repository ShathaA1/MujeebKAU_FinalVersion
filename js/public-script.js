function getBasePathFromSARA() {
  return "../";
}

/* ======================================== */

function goPublic(pageKey) {
  const base = getBasePathFromSARA();

  const map = {
    landing: "public/landing.html",
    signup: "public/signup.html",
    login: "public/login.html",
    forgotPassword: "public/forgot-password.html",
    resetPassword: "public/reset-password.html",
    verifyResetCode: "public/verify-reset-code.html",
    guestChat: "public/guest-chat.html"
  };

  window.location.href = base + map[pageKey];
}

/* ======================================== */

function goToPage(fileName) {
  window.location.href = fileName;
}

/* ======================================== */

async function handleSignup() {
  const signupBtn = $("signupBtn");

  const firstName = $("signupFirstName").value.trim();
  const lastName = $("signupLastName").value.trim();
  const email = $("signupEmail").value.trim();
  const password = $("signupPassword").value.trim();
  const confirmPassword = $("signupConfirmPassword").value.trim();
  const type = $("signupType").value;
  const gender = $("signupGender").value;
  const department = $("signupDepartment").value;

  if (!firstName || !lastName || !email || !password || !confirmPassword || !type || !gender || !department) {
    showFeedback("Please fill all fields.", "error", { duration: 4000 });
    return;
  }

  const emailPattern = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;
  if (!emailPattern.test(email)) {

    showFeedback("Please enter a valid email address.", "error", { duration: 4000 });
    return;
  }


  // 🔥 هذا الجديد
  const kauEmailPattern = /^[a-zA-Z0-9._%+-]+@(stu\.kau\.edu\.sa|kau\.edu\.sa)$/;

  if (!kauEmailPattern.test(email)) {
    showFeedback(
      "Only KAU emails are allowed (stu.kau.edu.sa or kau.edu.sa)",
      "error",
      { duration: 4000 }
    );
    return;
  }

  const strongPasswordPattern = /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$/;
  if (!strongPasswordPattern.test(password)) {
    showFeedback(
      "Password must be at least 8 characters and include uppercase, lowercase, and a number.",
      "error",
      { duration: 5000 }
    );
    return;
  }

  if (password !== confirmPassword) {
    showFeedback("Passwords do not match!", "error", { duration: 4000 });
    return;
  }

  const originalText = signupBtn.textContent;
  signupBtn.disabled = true;
  signupBtn.textContent = "Creating account...";

  try {
    const response = await fetch(`${API_BASE_URL}/signup`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        first_name: firstName,
        last_name: lastName,
        email: email,
        password: password,
        confirm_password: confirmPassword,
        gender: gender,
        user_type: type,
        college_name: department
      })
    });

    const data = await response.json();

    if (!response.ok) {
      showFeedback(getErrorMessage(data, "Failed to create account."), "error", { duration: 5000 });
      return;
    }

    localStorage.setItem("verify_email", email);

    showFeedback("Account created successfully! Please verify your email.", "success", { duration: 2500 });

    setTimeout(() => {
      window.location.href = "verify-email.html";
    }, 1200);
  } catch (error) {
    console.error(error);
    showFeedback("Cannot connect to server.", "error", { duration: 4000 });
  } finally {
    signupBtn.disabled = false;
    signupBtn.textContent = originalText;
  }
}

/* ======================================== */

function startGuestChat() {
  localStorage.setItem("mk_user_type", "guest");
  goPublic("guestChat");
}

/* ======================================== */

async function handleLogin() {
  const loginBtn = $("loginBtn");
  const email = $("loginEmail").value.trim();
  const password = $("loginPassword").value.trim();

  if (!email || !password) {
    showFeedback("Please enter email and password.", "error", { duration: 4000 });
    return;
  }

  const emailPattern = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;
  if (!emailPattern.test(email)) {
    showFeedback("Please enter a valid email address.", "error", { duration: 4000 });
    return;
  }

  const originalText = loginBtn.textContent;
  loginBtn.disabled = true;
  loginBtn.textContent = "Logging in...";

  try {
    const response = await fetch(`${API_BASE_URL}/login`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        email: email,
        password: password
      })
    });

    const data = await response.json();

    if (!response.ok) {
      const msg = getErrorMessage(data, "Login failed.");

      if (msg.includes("verify your email")) {
        localStorage.setItem("verify_email", email);

        showFeedback("Please verify your email first.", "warning");

        setTimeout(() => {
          window.location.href = "verify-email.html";
        }, 1200);

        return;
      }

      showFeedback(msg, "error");
      return;
    }

    localStorage.setItem("mk_token", data.access_token);

    if (data.user_type === "admin") {
      localStorage.setItem("mk_admin_id", data.user_id);
      localStorage.setItem("mk_admin_email", data.email || email);
      localStorage.setItem(
        "mk_admin_name",
        `${data.first_name || ""} ${data.last_name || ""}`.trim()
      );

      localStorage.removeItem("mk_user_id");
      localStorage.removeItem("mk_user_first_name");
      localStorage.removeItem("mk_user_last_name");
      localStorage.removeItem("mk_user_name");
      localStorage.removeItem("mk_user_email");
      localStorage.removeItem("mk_user_type");
      localStorage.removeItem("mk_user_gender");
      localStorage.removeItem("mk_user_department");

      showFeedback("Logged in as Admin!", "success", { duration: 1500 });

      setTimeout(() => {
        window.location.href = "../admin-view/admin-overview.html";
      }, 800);

      return;
    }

    localStorage.setItem("mk_user_id", data.user_id);
    localStorage.setItem("mk_user_first_name", data.first_name);
    localStorage.setItem("mk_user_last_name", data.last_name);
    localStorage.setItem("mk_user_name", `${data.first_name || ""} ${data.last_name || ""}`.trim());
    localStorage.setItem("mk_user_type", data.user_type);
    localStorage.setItem("mk_user_email", data.email || email);

    localStorage.removeItem("mk_admin_id");
    localStorage.removeItem("mk_admin_email");
    localStorage.removeItem("mk_admin_name");

    showFeedback("Logged in successfully!", "success", { duration: 1500 });

    setTimeout(() => {
      window.location.href = "../User-view/chat.html";
    }, 800);
  } catch (error) {
    console.error(error);
    showFeedback("Cannot connect to server.", "error", { duration: 4000 });
  } finally {
    loginBtn.disabled = false;
    loginBtn.textContent = originalText;
  }
}

/* ======================================== */

async function handlePasswordForgot() {
  const email = $("resetEmail").value.trim();
  const btn = $("forgotBtn");

  if (!email) {
    showFeedback("Please enter your registered email.", "error", { duration: 4000 });
    return;
  }

  try {
    btn.disabled = true;
    btn.innerText = "Checking...";

    const response = await fetch(`${API_BASE_URL}/forgot-password`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        email: email
      })
    });

    const data = await response.json();

    if (!response.ok) {
      showFeedback(getErrorMessage(data, "Failed to send reset code."), "error", { duration: 5000 });
      return;
    }

    showFeedback("Reset code sent to your email.", "success", { duration: 3000 });

    localStorage.setItem("reset_email", email);
    localStorage.removeItem("reset_code");
    localStorage.removeItem("reset_code_verified");

    setTimeout(() => {
      goPublic("verifyResetCode");
    }, 1200);
  } catch (err) {
    console.error(err);
    showFeedback("Server error. Please try again.", "error", { duration: 4000 });
  } finally {
    btn.disabled = false;
    btn.innerText = "Send Reset Link";
  }
}

/* ======================================== */

async function handleVerifyResetCode() {
  const code = $("verifyResetCode").value.trim();
  const btn = $("verifyCodeBtn");
  const email = localStorage.getItem("reset_email");

  if (!email) {
    showFeedback("Missing reset email. Please start again.", "error", { duration: 4000 });
    return;
  }

  if (!code) {
    showFeedback("Please enter the reset code.", "error", { duration: 4000 });
    return;
  }

  const originalText = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Verifying...";

  try {
    const response = await fetch(`${API_BASE_URL}/verify-reset-code`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        email: email,
        reset_code: code
      })
    });

    const data = await response.json();

    if (!response.ok) {
      showFeedback(getErrorMessage(data, "Invalid reset code."), "error", { duration: 5000 });
      return;
    }

    localStorage.setItem("reset_code_verified", "1");
    localStorage.setItem("reset_code", code);

    showFeedback("Code verified successfully!", "success", { duration: 2500 });

    setTimeout(() => {
      window.location.href = "reset-password.html";
    }, 1200);
  } catch (error) {
    console.error("Verify code error:", error);
    showFeedback("Cannot connect to server.", "error", { duration: 4000 });
  } finally {
    btn.disabled = false;
    btn.textContent = originalText;
  }
}

/* ======================================== */

async function handleResetPassword() {
  const newPass = $("newPassword").value.trim();
  const confirmPass = $("confirmPassword").value.trim();
  const btn = $("resetBtn");

  const email = localStorage.getItem("reset_email");
  const isVerified = localStorage.getItem("reset_code_verified");
  const resetCode = localStorage.getItem("reset_code");

  if (!email || isVerified !== "1" || !resetCode) {
    showFeedback("Invalid reset flow. Please start again.", "error", { duration: 4000 });
    return;
  }

  if (!newPass || !confirmPass) {
    showFeedback("Please fill both fields.", "error", { duration: 4000 });
    return;
  }

  const strongPasswordPattern = /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$/;
  if (!strongPasswordPattern.test(newPass)) {
    showFeedback(
      "Password must be at least 8 characters and include uppercase, lowercase, and a number.",
      "error",
      { duration: 5000 }
    );
    return;
  }

  if (newPass !== confirmPass) {
    showFeedback("Passwords do not match.", "error", { duration: 4000 });
    return;
  }

  const originalText = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Resetting...";

  try {
    const response = await fetch(`${API_BASE_URL}/reset-password`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        email: email,
        reset_code: resetCode,
        new_password: newPass,
        confirm_password: confirmPass
      })
    });

    const data = await response.json();

    if (!response.ok) {
      showFeedback(getErrorMessage(data, "Failed to reset password."), "error", { duration: 5000 });
      return;
    }

    localStorage.removeItem("reset_email");
    localStorage.removeItem("reset_code_verified");
    localStorage.removeItem("reset_code");

    showFeedback("Password reset successfully!", "success", { duration: 2500 });

    setTimeout(() => {
      window.location.href = "login.html";
    }, 1200);
  } catch (error) {
    console.error("Reset password error:", error);
    showFeedback("Cannot connect to server.", "error", { duration: 4000 });
  } finally {
    btn.disabled = false;
    btn.textContent = originalText;
  }
}

/* ======================================== */

async function handleVerifyEmail() {
  const code = $("verifyEmailCode").value.trim();
  const btn = $("verifyEmailBtn");
  const email = localStorage.getItem("verify_email");

  if (!email) {
    showFeedback("Missing email. Please sign up or log in again.", "error", { duration: 4000 });
    return;
  }

  if (!code) {
    showFeedback("Please enter the verification code.", "error", { duration: 4000 });
    return;
  }

  const originalText = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Verifying...";

  try {
    const response = await fetch(`${API_BASE_URL}/verify-email`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        email: email,
        verification_code: code
      })
    });

    const data = await response.json();

    if (!response.ok) {
      showFeedback(getErrorMessage(data, "Failed to verify email."), "error", { duration: 5000 });
      return;
    }

    localStorage.removeItem("verify_email");

    showFeedback("Email verified successfully!", "success", { duration: 2500 });

    setTimeout(() => {
      window.location.href = "login.html";
    }, 1200);
  } catch (error) {
    console.error("Verify email error:", error);
    showFeedback("Cannot connect to server.", "error", { duration: 4000 });
  } finally {
    btn.disabled = false;
    btn.textContent = originalText;
  }
}

/* ======================================== */

async function handleResendResetCode() {
  const email = localStorage.getItem("reset_email");
  const btn = $("resendResetCodeBtn");

  if (!email) {
    showFeedback("Missing email. Please start again.", "error", { duration: 4000 });
    return;
  }

  const originalText = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Sending...";

  try {
    const response = await fetch(`${API_BASE_URL}/forgot-password`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        email: email
      })
    });

    const data = await response.json();

    if (!response.ok) {
      showFeedback(getErrorMessage(data, "Failed to resend reset code."), "error", { duration: 5000 });
      return;
    }

    localStorage.removeItem("reset_code");
    localStorage.removeItem("reset_code_verified");

    showFeedback("A new reset code has been sent to your email.", "success", { duration: 3000 });
  } catch (error) {
    console.error("Resend reset code error:", error);
    showFeedback("Cannot connect to server.", "error", { duration: 4000 });
  } finally {
    btn.disabled = false;
    btn.textContent = originalText;
  }
}

/* ======================================== */

async function handleResendVerificationCode() {
  const email = localStorage.getItem("verify_email");
  const btn = $("resendEmailCodeBtn");

  if (!email) {
    showFeedback("Missing email. Please sign up or log in again.", "error", { duration: 4000 });
    return;
  }

  const originalText = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Sending...";

  try {
    const response = await fetch(`${API_BASE_URL}/resend-verification-code`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        email: email
      })
    });

    const data = await response.json();

    if (!response.ok) {
      showFeedback(getErrorMessage(data, "Failed to resend verification code."), "error", { duration: 5000 });
      return;
    }

    showFeedback("A new verification code has been sent to your email.", "success", { duration: 3000 });
  } catch (error) {
    console.error("Resend verification code error:", error);
    showFeedback("Cannot connect to server.", "error", { duration: 4000 });
  } finally {
    btn.disabled = false;
    btn.textContent = originalText;
  }
}

/* ======================================== */

function togglePassword(inputId, btn) {
  const input = document.getElementById(inputId);
  if (!input) return;

  const isHidden = input.type === "password";
  input.type = isHidden ? "text" : "password";

  if (btn) btn.textContent = isHidden ? "🙈" : "👁";
}

/* ======================================== */

function showUserPage(page) {
  const pages = ["profile"];

  pages.forEach((p) => $(p + "Page")?.classList.add("hidden"));
  $(page + "Page")?.classList.remove("hidden");

  if (page === "profile") {
    loadUserProfile();
  }
}

/* ======================================== */

function showAdminPage(page) {
  const pages = ["adminProfile"];

  pages.forEach((p) => $(p + "Page")?.classList.add("hidden"));
  $(page + "Page")?.classList.remove("hidden");

  if (page === "adminProfile") {
    loadAdminProfile();
  }
}

/* ======================================== */

async function loadUserProfile() {
  const userId = localStorage.getItem("mk_user_id");
  const token = getToken();

  if (!userId || !token) {
    showFeedback("User not logged in.", "error", { duration: 4000 });
    return;
  }

  try {
    const response = await fetch(`${API_BASE_URL}/user/profile`, {
      headers: getAuthHeaders(false)
    });

    const data = await response.json();

    if (response.status === 401 || response.status === 403) {
      handleUnauthorized();
      return;
    }

    if (!response.ok) {
      showFeedback(getErrorMessage(data, "Failed to load profile."), "error", { duration: 4000 });
      return;
    }

    $("profileFirstName").value = data.first_name || "";
    $("profileLastName").value = data.last_name || "";
    $("profileEmail").value = data.email || "";

    if (data.user_type === "student") {
      $("profileType").value = "Student";
    } else if (data.user_type === "faculty") {
      $("profileType").value = "Faculty Member";
    } else {
      $("profileType").value = data.user_type || "";
    }

    if (data.gender === "male") {
      $("profileGender").value = "Male";
    } else if (data.gender === "female") {
      $("profileGender").value = "Female";
    } else {
      $("profileGender").value = data.gender || "";
    }

    if ($("profileDepartment")) {
      $("profileDepartment").value = data.college_name || "";
    }
  } catch (error) {
    console.error(error);
    showFeedback("Failed to load profile.", "error", { duration: 4000 });
  }
}

/* ======================================== */

async function updateProfile() {
  const firstName = $("profileFirstName").value.trim();
  const lastName = $("profileLastName").value.trim();
  const college = $("profileDepartment").value;
  const token = getToken();

  if (!token) {
    handleUnauthorized();
    return;
  }

  if (!firstName || !lastName) {
    showFeedback("Please enter first and last name.", "error");
    return;
  }

  try {
    const response = await fetch(`${API_BASE_URL}/user/profile`, {
      method: "PUT",
      headers: getAuthHeaders(true),
      body: JSON.stringify({
        first_name: firstName,
        last_name: lastName,
        college_name: college
      })
    });

    const data = await response.json();

    if (response.status === 401 || response.status === 403) {
      handleUnauthorized();
      return;
    }

    if (!response.ok) {
      showFeedback(getErrorMessage(data, "Update failed."), "error");
      return;
    }

    localStorage.setItem("mk_user_first_name", firstName);
    localStorage.setItem("mk_user_last_name", lastName);
    localStorage.setItem("mk_user_name", `${firstName} ${lastName}`.trim());

    showFeedback("Profile updated successfully!", "success");
  } catch (error) {
    console.error(error);
    showFeedback("Update failed", "error");
  }
}

/* ======================================== */

function toggleChangePassword() {
  $("changePasswordBox")?.classList.toggle("hidden");
}

/* ======================================== */

async function saveNewPassword() {
  const current = $("userCurrentPassword")?.value.trim() || "";
  const newPass = $("newProfilePassword")?.value.trim() || "";
  const confirm = $("confirmNewProfilePassword")?.value.trim() || "";
  const btn = $("savePasswordBtn");
  const token = getToken();

  if (!token) {
    handleUnauthorized();
    return;
  }

  if (!current || !newPass || !confirm) {
    showFeedback("Please fill all password fields.", "error", { duration: 4000 });
    return;
  }

  const strongPasswordPattern = /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$/;
  if (!strongPasswordPattern.test(newPass)) {
    showFeedback(
      "Password must be at least 8 characters and include uppercase, lowercase, and a number.",
      "error",
      { duration: 5000 }
    );
    return;
  }

  if (newPass !== confirm) {
    showFeedback("New passwords do not match.", "error", { duration: 4000 });
    return;
  }

  const originalText = btn?.textContent || "Save New Password";
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Saving...";
  }

  try {
    const response = await fetch(`${API_BASE_URL}/user/change-password`, {
      method: "PUT",
      headers: getAuthHeaders(true),
      body: JSON.stringify({
        current_password: current,
        new_password: newPass,
        confirm_password: confirm
      })
    });

    const data = await response.json();

    if (response.status === 401 || response.status === 403) {
      handleUnauthorized();
      return;
    }

    if (!response.ok) {
      showFeedback(getErrorMessage(data, "Failed to change password."), "error", { duration: 4000 });
      return;
    }

    showFeedback("Password changed successfully.", "success", { duration: 2500 });

    if ($("userCurrentPassword")) $("userCurrentPassword").value = "";
    if ($("newProfilePassword")) $("newProfilePassword").value = "";
    if ($("confirmNewProfilePassword")) $("confirmNewProfilePassword").value = "";

    $("changePasswordBox")?.classList.add("hidden");
  } catch (error) {
    console.error(error);
    showFeedback("Failed to change password.", "error", { duration: 4000 });
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = originalText;
    }
  }
}

/* ======================================== */

function savePreferences() {
  const isOn = $("prefNotifications")?.checked ? "1" : "0";
  localStorage.setItem("mk_pref_notifications", isOn);
  showFeedback("Preferences updated.", "success", { duration: 2000 });
}

/* ======================================== */

async function loadAdminProfile() {
  const adminId = localStorage.getItem("mk_admin_id");
  const token = getToken();

  if (!adminId || !token) {
    showFeedback("Admin not logged in.", "error", { duration: 4000 });
    return;
  }

  try {
    const response = await fetch(`${API_BASE_URL}/user/profile`, {
      headers: getAuthHeaders(false)
    });

    const data = await response.json();

    if (response.status === 401 || response.status === 403) {
      handleUnauthorized();
      return;
    }

    if (!response.ok) {
      showFeedback(getErrorMessage(data, "Failed to load admin profile."), "error", { duration: 4000 });
      return;
    }

    const fullName = `${data.first_name || ""} ${data.last_name || ""}`.trim();

    if ($("adminProfileName")) $("adminProfileName").value = fullName;
    if ($("adminProfileEmail")) $("adminProfileEmail").value = data.email || "";

    if ($("adminRole")) {
      if (data.user_type === "admin") $("adminRole").value = "Admin";
      else $("adminRole").value = data.user_type || "";
    }

    if ($("adminGender")) {
      if (data.gender === "male") $("adminGender").value = "Male";
      else if (data.gender === "female") $("adminGender").value = "Female";
      else $("adminGender").value = data.gender || "";
    }

    if ($("adminCollege")) {
      $("adminCollege").value = data.college_name || "";
    }

    $("adminChangePasswordBox")?.classList.add("hidden");
  } catch (error) {
    console.error(error);
    showFeedback("Failed to load admin profile.", "error", { duration: 4000 });
  }
}

/* ======================================== */

async function saveAdminProfile() {
  const adminId = localStorage.getItem("mk_admin_id");
  const name = $("adminProfileName")?.value.trim() || "";
  const token = getToken();

  if (!adminId || !token) {
    showFeedback("Admin not logged in.", "error", { duration: 4000 });
    return;
  }

  if (!name) {
    showFeedback("Please enter admin name.", "error", { duration: 4000 });
    return;
  }

  try {
    const response = await fetch(`${API_BASE_URL}/admin/profile`, {
      method: "PUT",
      headers: getAuthHeaders(true),
      body: JSON.stringify({
        full_name: name
      })
    });

    const data = await response.json();

    if (response.status === 401 || response.status === 403) {
      handleUnauthorized();
      return;
    }

    if (!response.ok) {
      showFeedback(getErrorMessage(data, "Failed to update admin profile."), "error", { duration: 4000 });
      return;
    }

    localStorage.setItem("mk_admin_name", name);
    showFeedback("Admin profile updated successfully.", "success", { duration: 2500 });
  } catch (error) {
    console.error(error);
    showFeedback("Failed to update admin profile.", "error", { duration: 4000 });
  }
}

/* ======================================== */

function toggleAdminChangePassword() {
  const box = $("adminChangePasswordBox");
  if (!box) return;
  box.classList.toggle("hidden");
}

/* ======================================== */

async function saveAdminNewPassword() {
  const adminId = localStorage.getItem("mk_admin_id");
  const current = $("adminCurrentPassword")?.value.trim() || "";
  const newPass = $("adminNewPassword")?.value.trim() || "";
  const confirm = $("adminConfirmNewPassword")?.value.trim() || "";
  const token = getToken();

  if (!adminId || !token) {
    showFeedback("Admin not logged in.", "error", { duration: 4000 });
    return;
  }

  if (!current || !newPass || !confirm) {
    showFeedback("Please fill all password fields.", "error", { duration: 4000 });
    return;
  }

  const strongPasswordPattern = /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$/;
  if (!strongPasswordPattern.test(newPass)) {
    showFeedback(
      "Password must be at least 8 characters and include uppercase, lowercase, and a number.",
      "error",
      { duration: 5000 }
    );
    return;
  }

  if (newPass !== confirm) {
    showFeedback("New passwords do not match.", "error", { duration: 4000 });
    return;
  }

  try {
    const response = await fetch(`${API_BASE_URL}/user/change-password`, {
      method: "PUT",
      headers: getAuthHeaders(true),
      body: JSON.stringify({
        current_password: current,
        new_password: newPass,
        confirm_password: confirm
      })
    });

    const data = await response.json();

    if (response.status === 401 || response.status === 403) {
      handleUnauthorized();
      return;
    }

    if (!response.ok) {
      showFeedback(getErrorMessage(data, "Failed to change admin password."), "error", { duration: 4000 });
      return;
    }

    if ($("adminCurrentPassword")) $("adminCurrentPassword").value = "";
    if ($("adminNewPassword")) $("adminNewPassword").value = "";
    if ($("adminConfirmNewPassword")) $("adminConfirmNewPassword").value = "";
    $("adminChangePasswordBox")?.classList.add("hidden");

    showFeedback("Admin password changed successfully.", "success", { duration: 2500 });
  } catch (error) {
    console.error(error);
    showFeedback("Failed to change admin password.", "error", { duration: 4000 });
  }
}