import os
import re
import secrets
from fastapi import BackgroundTasks  
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta, timezone, date
from collections import defaultdict
from typing import Optional
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, Request, status, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi_mail import FastMail, MessageSchema, ConnectionConfig
from jose import jwt, JWTError
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from sqlalchemy import and_, func

from database import SessionLocal
from models import User, College, Notification, UserNotification, Conversation, Message, Document, AcademicEvent, KnowledgeChunk
from schemas import (
    SignupRequest,
    LoginRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    VerifyResetCodeRequest,
    VerifyEmailRequest,
    ResendVerificationCodeRequest,
    UpdateUserProfileRequest,
    ChangePasswordRequest,
    UpdateAdminProfileRequest,
    UserProfileResponse,
    CreateNotificationRequest,
    UpdateNotificationRequest,
    NotificationResponse,
    NotificationListResponse,
    NotificationCreate,
    MessageCreate,
    MessageResponse,
    GuestChatRequest,
    ConversationResponse,
    ConversationTitleRequest
)
import rag as rag
import agent as agent

from database import engine
from models import Base

Base.metadata.create_all(bind=engine)

import os
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")
load_dotenv(ENV_PATH)

app = FastAPI(title="Mujeeb KAU API")
scheduler = BackgroundScheduler()
scheduler.start()

# ==============================
# ENV / CONFIG
# ==============================

SECRET_KEY = os.getenv("SECRET_KEY", "change-this-in-env-now")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

MAIL_PORT = int(os.getenv("MAIL_PORT", "587"))

mail_config = ConnectionConfig(
    MAIL_USERNAME=os.getenv("MAIL_USERNAME"),
    MAIL_PASSWORD=os.getenv("MAIL_PASSWORD"),
    MAIL_FROM=os.getenv("MAIL_FROM"),
    MAIL_PORT=MAIL_PORT,
    MAIL_SERVER=os.getenv("MAIL_SERVER"),
    MAIL_FROM_NAME=os.getenv("MAIL_FROM_NAME", "Mujeeb KAU"),
    MAIL_STARTTLS=True,
    MAIL_SSL_TLS=False,
    USE_CREDENTIALS=True
)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

# ==============================
# CORS
# ==============================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==============================
# SIMPLE RATE LIMIT STORE
# ==============================

rate_limit_store = defaultdict(list)

RATE_LIMIT_RULES = {
    "login": {"max_requests": 5, "window_seconds": 60},
    "verify_email": {"max_requests": 5, "window_seconds": 600},
    "verify_reset_code": {"max_requests": 5, "window_seconds": 600},
    "signup": {"max_requests": 5, "window_seconds": 300},
}

# ==============================
# DB DEPENDENCY
# ==============================

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ==============================
# HELPERS
# ==============================

def now_utc():
    return datetime.now(timezone.utc).replace(tzinfo=None)

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def validate_password_strength(password: str) -> None:
    password_pattern = r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$"
    if not re.match(password_pattern, password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters and include uppercase, lowercase, and a number"
        )

def generate_6_digit_code() -> str:
    return str(secrets.randbelow(900000) + 100000)

def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    expire = now_utc() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

def check_rate_limit(request: Request, key_suffix: str, rule_name: str):
    rule = RATE_LIMIT_RULES[rule_name]
    ip = get_client_ip(request)
    key = f"{rule_name}:{ip}:{key_suffix}".lower()

    current_time = now_utc()
    window_start = current_time - timedelta(seconds=rule["window_seconds"])

    rate_limit_store[key] = [t for t in rate_limit_store[key] if t > window_start]

    if len(rate_limit_store[key]) >= rule["max_requests"]:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please try again later."
        )

    rate_limit_store[key].append(current_time)

def ensure_cooldown(last_sent_at: datetime | None, seconds: int, message: str):
    if last_sent_at:
        diff = (now_utc() - last_sent_at).total_seconds()
        if diff < seconds:
            remaining = int(seconds - diff)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"{message} Please wait {remaining} seconds."
            )

def get_college_by_name(db: Session, college_name: str | None):
    if not college_name:
        return None
    return db.query(College).filter(College.Name == college_name).first()

def send_html_email(subject: str, recipient: str, html_body: str):
    message = MessageSchema(
        subject=subject,
        recipients=[recipient],
        body=html_body,
        subtype="html"
    )
    fm = FastMail(mail_config)
    import asyncio
    asyncio.run(fm.send_message(message))

def build_user_profile_response(db: Session, user: User) -> UserProfileResponse:
    college_name = None
    if user.CollegeID:
        college = db.query(College).filter(College.CollegeID == user.CollegeID).first()
        if college:
            college_name = college.Name

    return UserProfileResponse(
        user_id=user.UserID,
        first_name=user.FirstName,
        last_name=user.LastName,
        email=user.Email,
        user_type=user.UserType,
        gender=user.Gender,
        college_name=college_name,
        is_verified=user.IsVerified,
        is_active=user.IsActive
    )


def normalize_email(email: str) -> str:
    return email.strip().lower()



def send_scheduled_notifications():
    db = SessionLocal()
    try:
        now = datetime.utcnow()

        notifications = db.query(Notification).filter(
            Notification.Status == "scheduled",
            Notification.ScheduleTime <= now
        ).all()

        if notifications:
            print(f"[WORKER] Found {len(notifications)} notifications to process (Current UTC: {now})")

        for notif in notifications:
            notif_id = notif.NotificationID
            notif_title = notif.Title
            
            print(f"[WORKER] Processing notification {notif_id}: '{notif_title}'")

            # 1. MARK AS SENT IMMEDIATELY and COMMIT 
            # This prevents other worker threads from picking up the same notification.
            notif.Status = "sent"
            db.commit()

            # 2. FETCH USERS AND SEND
            users = db.query(User).join(UserNotification).filter(
                UserNotification.NotificationID == notif_id
            ).all()

            sent_count = 0
            for user in users:
                try:
                    send_html_email(
                        subject=notif.Title,
                        recipient=user.Email,
                        html_body=f"<p>{notif.Message}</p>"
                    )
                    sent_count += 1
                except Exception as email_err:
                    print(f"[WORKER] Failed email to {user.Email} for notif {notif_id}: {email_err}")

            print(f"[WORKER] Notification {notif_id} sent to {sent_count} users.")

    except Exception as e:
        db.rollback()
        print(f"[WORKER] Error in send_scheduled_notifications: {e}")
    finally:
        db.close()

def check_upcoming_academic_events():
    """
    Background job to detect academic events starting in 3 days
    and generate notifications for the target audience.
    """
    db = SessionLocal()
    try:
        # 1. Calculate target date: exactly 3 days from now
        target_date = (datetime.utcnow() + timedelta(days=3)).date()
        print(f"[EVENT_NOTIF] Checking for events on {target_date}")

        events = db.query(AcademicEvent).filter(
            AcademicEvent.StartDate == target_date
        ).all()

        for event in events:
            # 2. Map audience (Handle variations like 'All Users')
            raw_audience = (event.UserType or "all").strip().lower()
            if "student" in raw_audience:
                normalized_audience = "student"
            elif "faculty" in raw_audience:
                normalized_audience = "faculty"
            else:
                normalized_audience = "all"
            
            db_user_type = None if normalized_audience == "all" else normalized_audience

            # 3. Robust Duplicate Prevention
            # We check again inside the loop to be safe in multi-worker scenarios
            existing = db.query(Notification).filter(
                Notification.AcadEventID == event.AcadEventID,
                Notification.NotificationType == "academic_event",
                Notification.UserType == db_user_type
            ).first()

            if existing:
                continue

            # 4. Create Notification record
            notification = Notification(
                Title="موعد أكاديمي قادم",
                Message=f"يتبقى 3 أيام على: {event.Title}",
                UserType=db_user_type,
                NotificationType="academic_event",
                AcadEventID=event.AcadEventID,
                EventDate=event.StartDate,
                UploadAt=datetime.utcnow(),
                ScheduleTime=datetime.utcnow(), # Send immediately via email job
                Status="scheduled"
            )
            db.add(notification)
            db.flush() # Get NotificationID

            # 5. Get target users for this audience
            target_users, _ = get_target_users_for_notification(db, normalized_audience, "all")
            
            # 6. Create UserNotification links
            user_notif_rows = [
                UserNotification(
                    NotificationID=notification.NotificationID,
                    UserID=user.UserID
                )
                for user in target_users
            ]
            
            if user_notif_rows:
                db.add_all(user_notif_rows)
            
            # COMMIT PER EVENT to prevent duplicates in high-concurrency
            db.commit()
            print(f"[EVENT_NOTIF] Generated notification for event '{event.Title}' (ID: {event.AcadEventID}) for {len(user_notif_rows)} users.")
        
    except Exception as e:
        db.rollback()
        print(f"[EVENT_NOTIF] Error: {e}")
    finally:
        db.close()

scheduler.add_job(send_scheduled_notifications, "interval", seconds=30)
scheduler.add_job(check_upcoming_academic_events, "cron", hour=8, minute=0)


# ==============================
# HELPERS notification
# ==============================


def normalize_db_datetime(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def normalize_audience(audience: str) -> str:
    value = audience.strip().lower()
    if value == "students":
        return "student"
    if value in {"all", "student", "faculty"}:
        return value
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Invalid audience value"
    )


def get_notification_status_by_time(schedule_time: datetime) -> str:
    schedule_time = normalize_db_datetime(schedule_time)
    return "sent" if schedule_time <= datetime.utcnow() else "scheduled"

def get_notification_college_name(db: Session, college_id: int | None) -> str:
    if not college_id:
        return "All Colleges"

    college = db.query(College).filter(College.CollegeID == college_id).first()
    return college.Name if college else "All Colleges"


def build_notification_response(db: Session, notification: Notification) -> NotificationResponse:
    audience = notification.UserType if notification.UserType else "all"

    return NotificationResponse(
        id=notification.NotificationID,
        title=notification.Title,
        message=notification.Message,
        audience=audience,
        type=notification.NotificationType or "",
        college=get_notification_college_name(db, notification.CollegeID),
        schedule_time=notification.ScheduleTime,
        status=notification.Status or "scheduled",
        event_date=notification.EventDate
    )

def get_target_users_for_notification(db: Session, audience: str, college_name: str):
    audience = normalize_audience(audience)

    query = db.query(User).filter(User.IsActive == True)

    if audience == "student":
        query = query.filter(User.UserType == "student")
    elif audience == "faculty":
        query = query.filter(User.UserType == "faculty")
    else:
        query = query.filter(User.UserType.in_(["student", "faculty"]))

    if college_name.strip().lower() != "all":
        college = db.query(College).filter(
            func.lower(College.Name) == college_name.strip().lower()
        ).first()

        if not college:
            raise HTTPException(status_code=404, detail="College not found")

        query = query.filter(User.CollegeID == college.CollegeID)
        return query.all(), college

    return query.all(), None

def ensure_notification_editable(notification: Notification):
    current_status = get_notification_status_by_time(notification.ScheduleTime)

    if current_status == "sent" or notification.Status == "sent":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot modify a notification that has already been sent"
        )

# ==============================
# AUTH DEPENDENCIES
# ==============================

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    token = credentials.credentials

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")

        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token"
            )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token"
        )

    user = db.query(User).filter(User.UserID == int(user_id)).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )

    if not user.IsActive:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive"
        )

    return user

def get_current_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.UserType != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user

# ==============================
# ROOT
# ==============================

from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, ".."))

# Mount all frontend folders as static directories so assets load correctly
app.mount("/css", StaticFiles(directory=os.path.join(PROJECT_ROOT, "css")), name="css")
app.mount("/js", StaticFiles(directory=os.path.join(PROJECT_ROOT, "js")), name="js")
app.mount("/public", StaticFiles(directory=os.path.join(PROJECT_ROOT, "public")), name="public")
app.mount("/sharing", StaticFiles(directory=os.path.join(PROJECT_ROOT, "sharing")), name="sharing")
app.mount("/User-view", StaticFiles(directory=os.path.join(PROJECT_ROOT, "User-View")), name="User-View")
app.mount("/admin-view", StaticFiles(directory=os.path.join(PROJECT_ROOT, "admin-view")), name="admin-view")

@app.get("/")
def home():
    landing_page = os.path.join(PROJECT_ROOT, "public", "landing.html")
    if os.path.exists(landing_page):
        return FileResponse(landing_page)
    return {"message": "Landing page not found."}

# ==============================
# AUTH / PUBLIC ENDPOINTS
# ==============================

@app.post("/signup")
def signup(data: SignupRequest, request: Request, db: Session = Depends(get_db)):
    check_rate_limit(request, data.email, "signup")

    email = normalize_email(data.email)

    # ✅ تحقق من إيميل الجامعة
    if not re.match(r"^[a-zA-Z0-9._%+-]+@(stu\.kau\.edu\.sa|kau\.edu\.sa)$", email):
         raise HTTPException(
             status_code=status.HTTP_400_BAD_REQUEST,
              detail="Only KAU emails are allowed (stu.kau.edu.sa or kau.edu.sa)"
                          )

    existing_user = db.query(User).filter(
    func.lower(User.Email) == email
).first()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered"
        )

    validate_password_strength(data.password)

    if data.password != data.confirm_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Passwords do not match"
        )

    college = db.query(College).filter(College.Name == data.college_name).first()
    if not college:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="College not found"
        )

    verification_code = generate_6_digit_code()
    verification_expire = now_utc() + timedelta(minutes=10)

    new_user = User(
        FirstName=data.first_name.strip(),
        LastName=data.last_name.strip(),
        Email=data.email.lower().strip(),
        Password=hash_password(data.password),
        UserType=data.user_type,
        Gender=data.gender,
        CollegeID=college.CollegeID,
        IsActive=True,
        IsVerified=False,
        VerificationCode=verification_code,
        VerificationCodeExpire=verification_expire,
        VerificationCodeSentAt=now_utc()
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    html_body = f"""
    <h3>Email Verification</h3>
    <p>Hello {new_user.FirstName},</p>
    <p>Your verification code for Mujeeb KAU is:</p>
    <h2>{verification_code}</h2>
    <p>This code will expire in 10 minutes.</p>
    """

    try:
        send_html_email(
            subject="Mujeeb KAU - Verify Your Email",
            recipient=new_user.Email,
            html_body=html_body
        )
    except Exception:
        # لا نخرب إنشاء الحساب لو الإيميل فشل
        pass

    return {
        "message": "Account created. Please verify your email.",
        "email": new_user.Email
    }

@app.post("/verify-email")
def verify_email(data: VerifyEmailRequest, request: Request, db: Session = Depends(get_db)):
    check_rate_limit(request, data.email, "verify_email")

    email = normalize_email(data.email)

    user = db.query(User).filter(
    func.lower(User.Email) == email
).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found"
        )

    if user.IsVerified:
        return {"message": "Email already verified"}

    if not user.VerificationCode:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No verification request found"
        )

    if user.VerificationCodeExpire and now_utc() > user.VerificationCodeExpire:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification code expired"
        )

    if user.VerificationCode != data.verification_code.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification code"
        )

    user.IsVerified = True
    user.VerificationCode = None
    user.VerificationCodeExpire = None
    user.VerificationCodeSentAt = None

    db.commit()

    return {"message": "Email verified successfully"}

@app.post("/resend-verification-code")
def resend_verification_code(
    data: ResendVerificationCodeRequest,
    db: Session = Depends(get_db)
):
    email = normalize_email(data.email)

    user = db.query(User).filter(
    func.lower(User.Email) == email
).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found"
        )

    if user.IsVerified:
        return {"message": "Email already verified"}

    ensure_cooldown(
        user.VerificationCodeSentAt,
        seconds=60,
        message="Verification code was sent recently."
    )

    new_code = generate_6_digit_code()
    new_expire = now_utc() + timedelta(minutes=10)

    user.VerificationCode = new_code
    user.VerificationCodeExpire = new_expire
    user.VerificationCodeSentAt = now_utc()

    db.commit()

    html_body = f"""
    <h3>Verify Your Email</h3>
    <p>Hello {user.FirstName},</p>
    <p>Your new verification code for Mujeeb KAU is:</p>
    <h2>{new_code}</h2>
    <p>This code will expire in 10 minutes.</p>
    """

    try:
        send_html_email(
            subject="Mujeeb KAU - New Verification Code",
            recipient=user.Email,
            html_body=html_body
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send verification email"
        )

    return {"message": "New verification code sent successfully"}

@app.post("/login")
def login(data: LoginRequest, request: Request, db: Session = Depends(get_db)):
    check_rate_limit(request, data.email, "login")

    email = normalize_email(data.email)

    user = db.query(User).filter(
    func.lower(User.Email) == email
).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No account found with this email"
        )

    if not user.IsActive:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is inactive"
        )

    if not verify_password(data.password, user.Password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect password"
        )

    if user.UserType != "admin" and not user.IsVerified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please verify your email before logging in"
        )

    access_token = create_access_token(
        data={"sub": str(user.UserID), "user_type": user.UserType},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )

    return {
        "message": "Login successful",
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in_minutes": ACCESS_TOKEN_EXPIRE_MINUTES,
        "user_id": user.UserID,
        "user_type": user.UserType,
        "first_name": user.FirstName,
        "last_name": user.LastName,
        "email": user.Email
    }

@app.post("/forgot-password")
def forgot_password(data: ForgotPasswordRequest, db: Session = Depends(get_db)):
    email = normalize_email(data.email)

    user = db.query(User).filter(
    func.lower(User.Email) == email
).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No account found with this email"
        )

    ensure_cooldown(
        user.ResetCodeSentAt,
        seconds=60,
        message="Reset code was sent recently."
    )

    reset_code = generate_6_digit_code()
    reset_code_expire = now_utc() + timedelta(minutes=15)

    user.ResetCode = reset_code
    user.ResetCodeExpire = reset_code_expire
    user.ResetCodeSentAt = now_utc()

    db.commit()

    html_body = f"""
    <html>
      <body>
        <h2>Mujeeb KAU - Password Reset Code</h2>
        <p>Hello {user.FirstName},</p>
        <p>You requested to reset your password.</p>
        <p>Your reset code is:</p>
        <h1>{reset_code}</h1>
        <p>This code will expire in 15 minutes.</p>
      </body>
    </html>
    """

    try:
        send_html_email(
            subject="Mujeeb KAU - Reset Code",
            recipient=user.Email,
            html_body=html_body
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send reset email"
        )

    return {"message": "Reset code sent successfully"}

@app.post("/verify-reset-code")
def verify_reset_code(data: VerifyResetCodeRequest, request: Request, db: Session = Depends(get_db)):
    check_rate_limit(request, data.email, "verify_reset_code")

    email = normalize_email(data.email)

    user = db.query(User).filter(
    func.lower(User.Email) == email
).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No account found with this email"
        )

    if not user.ResetCode:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No reset code found for this account"
        )

    if user.ResetCodeExpire and now_utc() > user.ResetCodeExpire:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset code has expired"
        )

    if user.ResetCode != data.reset_code.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid reset code"
        )

    return {"message": "Code verified successfully"}

@app.post("/reset-password")
def reset_password(data: ResetPasswordRequest, db: Session = Depends(get_db)):
    email = normalize_email(data.email)

    user = db.query(User).filter(
    func.lower(User.Email) == email
).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No account found with this email"
        )

    if not user.ResetCode:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No reset request found for this account"
        )

    if user.ResetCodeExpire and now_utc() > user.ResetCodeExpire:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset code has expired"
        )

    if user.ResetCode != data.reset_code.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid reset code"
        )

    validate_password_strength(data.new_password)

    if data.new_password != data.confirm_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Passwords do not match"
        )

    user.Password = hash_password(data.new_password)
    user.ResetCode = None
    user.ResetCodeExpire = None
    user.ResetCodeSentAt = None

    db.commit()

    return {"message": "Password reset successfully"}

# ==============================
# USER PROTECTED ENDPOINTS
# ==============================

@app.get("/user/profile", response_model=UserProfileResponse)
def get_user_profile(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return build_user_profile_response(db, current_user)

@app.put("/user/profile")
def update_user_profile(
    data: UpdateUserProfileRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    current_user.FirstName = data.first_name.strip()
    current_user.LastName = data.last_name.strip()

    if data.college_name:
        college = get_college_by_name(db, data.college_name.strip())
        if not college:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="College not found"
            )
        current_user.CollegeID = college.CollegeID

    db.commit()

    return {"message": "Profile updated successfully"}

@app.put("/user/change-password")
def change_user_password(
    data: ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if not verify_password(data.current_password, current_user.Password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect"
        )

    validate_password_strength(data.new_password)

    if data.new_password != data.confirm_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Passwords do not match"
        )

    current_user.Password = hash_password(data.new_password)
    db.commit()

    return {"message": "Password changed successfully"}

# ==============================
# ADMIN PROTECTED ENDPOINTS
# ==============================

@app.put("/admin/profile")
def update_admin_profile(
    data: UpdateAdminProfileRequest,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin)
):
    full_name = data.full_name.strip()
    name_parts = full_name.split()

    current_admin.FirstName = name_parts[0]
    current_admin.LastName = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

    db.commit()

    return {"message": "Admin profile updated successfully"}



# ==============================
#  NOTIFICATION ENDPOINTS
# ==============================

@app.post("/admin/notifications", response_model=NotificationResponse)
def create_notification(
    data: CreateNotificationRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin)
):
    try:
        title = data.title.strip()
        message = data.message.strip()
        audience = normalize_audience(data.audience)
        college_name = data.college_name.strip()
        schedule_time = normalize_db_datetime(data.schedule_time)

        if not title or not message:
            raise HTTPException(status_code=400, detail="Title and message are required")

        target_users, college = get_target_users_for_notification(db, audience, college_name)
        now_utc_val = datetime.utcnow()
        is_instant = schedule_time <= now_utc_val

        print(f"[DEBUG] create_notification: Title='{title}', ScheduleTime={schedule_time}, CurrentUTC={now_utc_val}, is_instant={is_instant}")
        print("AUDIENCE:", audience)
        print("COLLEGE NAME:", college_name)
        print("TARGET USERS COUNT:", len(target_users))
        print("TARGET USER IDS:", [u.UserID for u in target_users])

        notification = Notification(
            Title=title,
            Message=message,
            UserType=None if audience == "all" else audience,
            NotificationType=data.notification_type,
            UploadAt=datetime.utcnow(),
            ScheduleTime=schedule_time,
            Status=get_notification_status_by_time(schedule_time),
            CollegeID=college.CollegeID if college else None,
            AcadEventID=None,
            EventDate=schedule_time.date()
        )

        db.add(notification)
        db.flush()  # instead of commit, to get notification id

        user_notification_rows = [
            UserNotification(
                NotificationID=notification.NotificationID,
                UserID=user.UserID
            )
            for user in target_users
        ]

        if user_notification_rows:
            db.add_all(user_notification_rows)

        db.commit()
        db.refresh(notification)

        # =========================
        # SEND EMAILS (INSTANT ONLY)
        # =========================
        if is_instant:
            for user in target_users:
                background_tasks.add_task(
                    send_html_email,
                    notification.Title,
                    user.Email,
                    f"<p>{notification.Message}</p>"
                )

        return {
            "id": notification.NotificationID,
            "title": notification.Title,
            "message": notification.Message,
            "audience": notification.UserType if notification.UserType else "all",
            "type": notification.NotificationType,
            "schedule_time": notification.ScheduleTime,
            "status": notification.Status,
            "college": college.Name if college else "All Colleges",
            "event_date": notification.EventDate
        }

    except Exception as e:
        db.rollback()
        raise e

#-------------------------------------------

@app.get("/admin/notifications", response_model=NotificationListResponse)
def list_notifications(
    audience: Optional[str] = None,
    notification_type: Optional[str] = None,
    status_filter: Optional[str] = None,
    college_name: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin)
):
    notifications = db.query(Notification).all()

    results = []

    for n in notifications:
        current_status = get_notification_status_by_time(n.ScheduleTime)
        if n.Status != current_status:
            n.Status = current_status

        audience_value = n.UserType if n.UserType else "all"
        college_value = get_notification_college_name(db, n.CollegeID)

        if audience and audience != "all":
            normalized_filter = normalize_audience(audience)
            if audience_value != normalized_filter:
                continue

        if notification_type and notification_type != "all":
            if n.NotificationType != notification_type:
                continue

        if status_filter and status_filter != "all":
            if current_status != status_filter:
                continue

        if college_name and college_name != "all":
            if college_value != college_name:
                continue

        notif_date = n.ScheduleTime.date() if n.ScheduleTime else None

        if date_from and notif_date and notif_date < date_from:
            continue

        if date_to and notif_date and notif_date > date_to:
            continue

        results.append(build_notification_response(db, n))

    db.commit()

    results.sort(key=lambda x: x.schedule_time, reverse=True)

    return {"notifications": results}


#------------------------------------------------------

@app.get("/admin/notifications/{notification_id}", response_model=NotificationResponse)
def get_notification(
    notification_id: int,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin)
):
    notification = db.query(Notification).filter(
        Notification.NotificationID == notification_id
    ).first()

    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found"
        )

    current_status = get_notification_status_by_time(notification.ScheduleTime)
    if notification.Status != current_status:
        notification.Status = current_status
        db.commit()
        db.refresh(notification)

    return build_notification_response(db, notification)



#-----------------------------------------------------

@app.delete("/admin/notifications/{notification_id}")
def delete_notification_endpoint(
    notification_id: int,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin)
):
    notification = db.query(Notification).filter(
        Notification.NotificationID == notification_id
    ).first()

    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found"
        )

    ensure_notification_editable(notification)

    db.query(UserNotification).filter(
        UserNotification.NotificationID == notification_id
    ).delete()

    db.delete(notification)
    db.commit()

    return {"message": "Notification deleted successfully"}


#--------------------------------------------

@app.put("/admin/notifications/{notification_id}", response_model=NotificationResponse)
def update_notification(
    notification_id: int,
    data: UpdateNotificationRequest,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin)
):
    try:
        notification = db.query(Notification).filter(
            Notification.NotificationID == notification_id
        ).first()

        if not notification:
            raise HTTPException(status_code=404, detail="Notification not found")

        if notification.Status == "sent":
            raise HTTPException(status_code=400, detail="Cannot edit a sent notification")

        title = data.title.strip()
        message = data.message.strip()
        audience = normalize_audience(data.audience)
        college_name = data.college_name.strip()
        schedule_time = normalize_db_datetime(data.schedule_time)

        target_users, college = get_target_users_for_notification(db, audience, college_name)

        notification.Title = title
        notification.Message = message
        notification.UserType = None if audience == "all" else audience
        notification.NotificationType = data.notification_type
        notification.ScheduleTime = schedule_time
        notification.Status = get_notification_status_by_time(schedule_time)
        notification.CollegeID = college.CollegeID if college else None
        notification.EventDate = schedule_time.date()

        db.query(UserNotification).filter(
            UserNotification.NotificationID == notification_id
        ).delete()

        new_rows = [
            UserNotification(
                NotificationID=notification.NotificationID,
                UserID=user.UserID
            )
            for user in target_users
        ]

        if new_rows:
            db.add_all(new_rows)

        db.commit()
        db.refresh(notification)


        return {
            "id": notification.NotificationID,
            "title": notification.Title,
            "message": notification.Message,
            "audience": notification.UserType if notification.UserType else "all",
            "type": notification.NotificationType,
            "schedule_time": notification.ScheduleTime,
            "status": notification.Status,
            "college": college.Name if college else "All Colleges",
            "event_date": notification.EventDate
        }

    except Exception as e:
        db.rollback()
        raise e
    


    #-------------- 
    # conversation endpoints moved to bottom of file (CHAT / RAG ENDPOINTS section)
    #--------------

#-------------------
# user notification
#-------------------
from datetime import datetime

@app.get("/user/notifications")
def get_user_notifications(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    links = db.query(UserNotification).filter(
        UserNotification.UserID == current_user.UserID,
        UserNotification.is_deleted == False
    ).all()

    result = []

    for link in links:
        notif = db.query(Notification).filter(
            Notification.NotificationID == link.NotificationID
        ).first()

        result.append({
            "id": notif.NotificationID,
            "title": notif.Title,
            "message": notif.Message,
            "schedule_time": notif.ScheduleTime,
            "is_read": link.is_read,
            "created_at": link.created_at
        })

    return {"notifications": result}




@app.put("/user/notifications/{notification_id}/read")
def mark_as_read(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    link = db.query(UserNotification).filter(
        UserNotification.NotificationID == notification_id,
        UserNotification.UserID == current_user.UserID
    ).first()

    if not link:
        raise HTTPException(status_code=404, detail="Not found")

    link.is_read = True
    db.commit()

    return {"message": "Marked as read"}


#for delete all notifications 

@app.delete("/user/notifications/delete-all")
def delete_all_notifications(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    db.query(UserNotification).filter(
        UserNotification.UserID == current_user.UserID,
        UserNotification.is_deleted == False
    ).update({"is_deleted": True})

    db.commit()

    return {"message": "All notifications deleted successfully"}


@app.delete("/user/notifications/{notification_id}")
def delete_notification(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    link = db.query(UserNotification).filter(
        UserNotification.NotificationID == notification_id,
        UserNotification.UserID == current_user.UserID
    ).first()

    if not link:
        raise HTTPException(status_code=404, detail="Not found")

    link.is_deleted = True
    db.commit()

    return {"message": "Hidden"}


@app.put("/user/notifications/read-all")
def mark_all_read(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    db.query(UserNotification).filter(
        UserNotification.UserID == current_user.UserID,
        UserNotification.is_deleted == False
    ).update({"is_read": True})

    db.commit()

    return {"message": "All marked as read"}


# =========================================================
# RECENT ACADEMIC UPDATES PAGE
# =========================================================

# Endpoint: GET /admin/documents
# Benefit:
#     Returns a list of all uploaded documents for the admin dashboard.
#
# What it does:
#     Reads all documents from the database, orders them from newest to oldest,
#     attaches the related college name if the document belongs to a college,
#     then returns a clean list of document details with the total count.
#
# Notes:
#     This endpoint is mainly used to display uploaded files in the admin panel.
@app.get("/admin/documents")
def list_documents(db: Session = Depends(get_db)):

    # Get all documents from the database.
    # The newest uploaded documents appear first.
    docs = db.query(Document).order_by(Document.UploadAt.desc()).all()

    # This list will store the formatted document data returned to the frontend.
    result = []

    # Loop through each document record from the database.
    for d in docs:

        # Default college name is None.
        # This is used when the document is not linked to any college.
        college_name = None

        # If the document has a CollegeID, fetch the related college record.
        if d.CollegeID:
            college = db.query(College).filter(College.CollegeID == d.CollegeID).first()

            # If the college exists, use its name.
            # If not found, keep college_name as None to avoid breaking the response.
            college_name = college.Name if college else None

        # Add one formatted document object to the response list.
        # Field names here are frontend-friendly and easier to use in the UI.
        result.append({
            "doc_id": d.DocumentID,
            "filename": d.FileName,
            "doc_type": d.DocumentType,
            "category": d.UserType,
            "college": college_name,
            "created_at": d.UploadAt,
            "status": d.StatusMessage or "uploaded"
        })

    # Return the document list and the total number of documents.
    return {
        "documents": result,
        "count": len(result)
    }


# Endpoint: DELETE /admin/documents/{doc_id}
# Benefit:
#     Allows the admin to delete an uploaded document from the system.
#
# What it does:
#     Finds the document by ID, deletes it from the database, removes its vectors
#     from ChromaDB, deletes the physical file from storage if it exists, then
#     returns a success response.
#
# Notes:
#     The database deletion happens first. ChromaDB cleanup is handled as best-effort,
#     meaning the document can still be deleted even if vector cleanup fails.
@app.delete("/admin/documents/{doc_id}")
def delete_document(doc_id: int, db: Session = Depends(get_db)):

    # Search for the document using its database ID.
    doc = db.query(Document).filter(Document.DocumentID == doc_id).first()

    # If no document is found, return a 404 error to the frontend.
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Save the file path before deleting the database record.
    # After deleting the document object, this path is still needed to remove the file.
    file_path = doc.FilePath

    # Delete the document record from the database.
    # If KnowledgeChunk rows are linked with cascade delete,
    # they should be removed automatically after commit.
    db.delete(doc)
    db.commit()

    # ── Remove vectors from ChromaDB ──────────────────────────────────────────
    # Do this AFTER the DB commit so the cascade delete of KnowledgeChunk rows
    # has already happened. Chroma removal is best-effort; a failure here must
    # not prevent the HTTP response from being returned.
    try:
        # Remove all vector embeddings related to this document from ChromaDB.
        # This prevents deleted documents from still appearing in RAG search results.
        remove_document_from_chroma(doc_id)

    except Exception as chroma_err:
        # If ChromaDB cleanup fails, only log the warning.
        # The API should still return success because the main database deletion worked.
        print(f"[DELETE] WARNING: could not remove doc_id={doc_id} from Chroma: {chroma_err}")

    # If the original uploaded file still exists on disk, delete it.
    if file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
        except Exception:
            # Ignore file deletion errors so they do not block the admin response.
            pass

    # Return a success message to confirm the document was deleted.
    return {
        "message": "Deleted successfully",
        "doc_id": doc_id
    }


# Endpoint: GET /admin/overview
# Benefit:
#     Provides summary statistics for the admin dashboard overview page.
#
# What it does:
#     Counts users, uploaded documents, and notifications. It also gets the most
#     recently uploaded document and the latest scheduled notification so the
#     dashboard can show recent system activity.
#
# Notes:
#     This endpoint requires the current user to be an admin.
@app.get("/admin/overview")
def get_admin_overview(
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin)
):

    # Count all non-admin users.
    # Admin accounts are excluded because the dashboard focuses on system users.
    total_users = db.query(User).filter(User.UserType != "admin").count()

    # Count all uploaded documents.
    total_documents = db.query(Document).count()

    # Count all notifications in the system.
    total_notifications = db.query(Notification).count()

    # Get the latest uploaded document based on upload time.
    latest_document = db.query(Document).order_by(Document.UploadAt.desc()).first()

    # Get the latest notification based on scheduled time.
    latest_notification = db.query(Notification).order_by(Notification.ScheduleTime.desc()).first()

    # Default value if there are no uploaded documents.
    latest_document_data = None

    # If a latest document exists, prepare only the fields needed by the dashboard.
    if latest_document:
        latest_document_data = {
            "filename": latest_document.FileName,
            "category": latest_document.UserType
        }

    # Default value if there are no notifications.
    latest_notification_data = None

    # If a latest notification exists, prepare only the fields needed by the dashboard.
    if latest_notification:
        latest_notification_data = {
            "title": latest_notification.Title,
            "audience": latest_notification.UserType if latest_notification.UserType else "all"
        }

    # Return dashboard statistics and latest activity data.
    return {
        "stats": {
            "users": total_users,
            "docs": total_documents,
            "notifications": total_notifications
        },
        "latest_activity": {
            "last_upload": latest_document_data,
            "last_notification": latest_notification_data
        }
    }


# Endpoint: GET /admin/activity
# Benefit:
#     Returns monthly activity data for uploads and notifications.
#
# What it does:
#     Reads all documents and notifications, groups them by year and month,
#     counts how many uploads and notifications happened in each month,
#     then returns the activity summary.
#
# Notes:
#     The returned format is useful for charts in the admin dashboard,
#     such as monthly upload and notification activity graphs.
@app.get("/admin/activity")
def get_activity(db: Session = Depends(get_db)):

    # Get all uploaded documents from the database.
    docs = db.query(Document).all()

    # Get all notifications from the database.
    notifs = db.query(Notification).all()

    # This dictionary will store monthly activity.
    # Example:
    # {
    #     "2026-05": {"uploads": 3, "notifications": 2}
    # }
    activity = {}

    # Documents
    # Loop through each document and count it under its upload month.
    for d in docs:

        # Extract only the date part from the upload timestamp.
        date = d.UploadAt.date()

        # Convert the date into a year-month key, such as "2026-05".
        key = date.strftime("%Y-%m")

        # If this month does not exist yet in the activity dictionary,
        # initialize it with zero counts.
        if key not in activity:
            activity[key] = {"uploads": 0, "notifications": 0}

        # Increase upload count for this month.
        activity[key]["uploads"] += 1

    # Notifications
    # Loop through each notification and count it under its scheduled month.
    for n in notifs:

        # Extract the date part from ScheduleTime if it exists.
        date = n.ScheduleTime.date() if n.ScheduleTime else None

        # Skip notifications that do not have a scheduled date.
        if not date:
            continue

        # Convert the schedule date into a year-month key, such as "2026-05".
        key = date.strftime("%Y-%m")

        # If this month does not exist yet in the activity dictionary,
        # initialize it with zero counts.
        if key not in activity:
            activity[key] = {"uploads": 0, "notifications": 0}

        # Increase notification count for this month.
        activity[key]["notifications"] += 1

    # Return monthly activity grouped by year-month.
    return activity


###################ocr#############################


from ocr import extract_text_from_file, extract_academic_events
from pdf_structure import extract_structured_chunks_from_pdf
from chroma_sync import sync_document_chunks, remove_document_from_chroma


# Endpoint: POST /admin/process-and-save-document
# Benefit:
#     Allows the admin to upload a document, process its content, save the extracted
#     information in the database, and sync searchable chunks with ChromaDB when needed.
#
# What it does:
#     Receives an uploaded file with its metadata, saves the file locally, creates a
#     Document record, then chooses the correct processing pipeline based on the
#     document type:
#
#     - Academic Calendar:
#         Uses OCR to extract text, extracts academic events, and saves them into
#         AcademicEvent table.
#
#     - Other document types:
#         Uses the structured PDF pipeline to extract page chunks, saves them into
#         KnowledgeChunk table, and syncs them with ChromaDB for RAG search.
#
# Why it is useful:
#     This endpoint is the main admin upload pipeline. It connects file upload,
#     OCR/PDF processing, database storage, and vector search indexing in one flow.
@app.post("/admin/process-and-save-document")
async def process_and_save_document(
    file: UploadFile = File(...),
    document_type: str = Form(...),
    user_type: str = Form(...),
    college_name: str = Form(...),
    db: Session = Depends(get_db)
):
    try:
        # Debug logs to confirm that the endpoint started correctly
        # and received the expected file and document type.
        print("A- process_and_save_document started")
        print("B- file received:", file.filename)
        print("C- document_type:", document_type)

        # Define the local folder where uploaded documents will be stored.
        upload_folder = "uploads"

        # Create the uploads folder if it does not already exist.
        # exist_ok=True prevents an error if the folder already exists.
        os.makedirs(upload_folder, exist_ok=True)

        # Build the full file path using the upload folder and original filename.
        file_path = os.path.join(upload_folder, file.filename)

        # Save the uploaded file to the server.
        # The file is read asynchronously from the request and written in binary mode.
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)

        # Default college_id is None.
        # This means the document is not linked to a specific college unless
        # a valid college name is provided.
        college_id = None

        # If the admin selected a specific college instead of "all",
        # search for that college in the database.
        if college_name and college_name.lower() != "all":
            college = db.query(College).filter(College.Name == college_name).first()

            # If the college exists, store its ID so it can be linked to the document.
            if college:
                college_id = college.CollegeID

        # Create a new Document database record.
        # At this stage, the document is marked as "Processing" because extraction
        # and saving are not completed yet.
        new_doc = Document(
            FileName=file.filename,
            FilePath=file_path,
            DocumentType=document_type,
            WordExtract=None,
            PagesDetected=None,
            StatusMessage="Processing",
            UserType=user_type,
            CollegeID=college_id
        )

        # Add the new document to the current database session.
        db.add(new_doc)

        # Commit now so the document gets saved and receives a DocumentID.
        db.commit()

        # Refresh the object to load generated database values such as DocumentID.
        db.refresh(new_doc)

        # Counters used to track how many records were created during processing.
        saved_events_count = 0
        saved_chunks_count = 0

        # These values will be calculated after extraction.
        pages_count = 0
        words_count = 0

        # Debug log showing the created document ID.
        print("D- document saved with ID:", new_doc.DocumentID)

        # Academic Calendar documents follow a special pipeline.
        # They are processed with OCR and converted into AcademicEvent records
        # instead of KnowledgeChunk records.
        if document_type == "Academic Calendar":
            print("E- using alOCR for Academic Calendar")

            # Extract full text from the uploaded file using OCR.
            extracted_text = extract_text_from_file(file_path)

            # Count detected pages based on PAGE_BREAK separators added by OCR.
            pages_count = extracted_text.count("PAGE_BREAK") + 1 if extracted_text else 0

            # Count extracted words for reporting back to the admin dashboard.
            words_count = len(extracted_text.split()) if extracted_text else 0

            # Convert the raw OCR academic calendar text into structured event data.
            extracted_events = extract_academic_events(extracted_text)

            # Save each extracted academic event into the AcademicEvent table.
            for ev in extracted_events:
                db_event = AcademicEvent(
                    Title=ev["title"],
                    UserType=user_type,
                    StartDate=ev["startdate"],
                    EndDate=ev["enddate"],
                    HStartDate=ev["histartdate"],
                    HEndDate=ev["hienddate"],
                    DocID=new_doc.DocumentID
                )

                # Add the event to the database session.
                db.add(db_event)

                # Increase the saved events counter.
                saved_events_count += 1

            # Store the full extracted OCR text in the Document record.
            new_doc.WordExtract = extracted_text

            # Store the number of detected pages in the Document record.
            new_doc.PagesDetected = pages_count

        # All non-Academic Calendar documents follow the general structured PDF pipeline.
        # This includes regulations, admission guides, policies, manuals, and other PDFs.
        else:
            print("E- using PyMuPDF + LLM for structured chunks")

            # Extract structured chunks from the PDF.
            # The pipeline uses PyMuPDF first, OCR fallback when needed,
            # and AI organization when use_ai=True.
            chunks = extract_structured_chunks_from_pdf(
                pdf_path=file_path,
                document_type=document_type,
                use_ai=True
            )

            # Save each extracted chunk into the KnowledgeChunk table.
            for chunk in chunks:
                db_chunk = KnowledgeChunk(
                    DocID=new_doc.DocumentID,
                    ChunkText=chunk["chunk_text"],
                    PageNumber=chunk["page_number"],
                    ChunkOrder=chunk["chunk_order"]
                )

                # Add the chunk to the database session.
                db.add(db_chunk)

                # Increase the saved chunks counter.
                saved_chunks_count += 1

            # Count pages based on the number of chunks returned by the PDF pipeline.
            pages_count = len(chunks)

            # Count the total number of words across all chunk texts.
            words_count = sum(len(chunk["chunk_text"].split()) for chunk in chunks)

            # Store all chunks as one combined text in the Document record.
            # PAGE_BREAK is used to keep separation between chunks/pages.
            new_doc.WordExtract = "\n\nPAGE_BREAK\n\n".join(
                chunk["chunk_text"] for chunk in chunks
            )

            # Store the number of detected pages/chunks.
            new_doc.PagesDetected = pages_count

        # Mark the document as successfully saved after processing is complete.
        new_doc.StatusMessage = "Saved to Knowledge Base"

        # Commit all changes:
        # - AcademicEvent records for Academic Calendar
        # - KnowledgeChunk records for other PDFs
        # - updated Document fields
        db.commit()

        # Refresh the document object after commit to ensure it contains latest DB values.
        db.refresh(new_doc)

        # Debug logs showing how many records were created.
        print("O- saved_events_count:", saved_events_count)
        print("P- saved_chunks_count:", saved_chunks_count)

        # ── Chroma sync (Regulations / Admission Guide only) ──────────────────
        # Academic Calendar goes straight to AcademicEvent; no KnowledgeChunk
        # rows are created for it, so we only sync non-Calendar document types.
        if document_type != "Academic Calendar":
            try:
                # Sync the saved KnowledgeChunk rows with ChromaDB.
                # This makes the document searchable by the RAG system.
                indexed = sync_document_chunks(new_doc.DocumentID, db)

                # Debug log showing how many chunks were indexed in ChromaDB.
                print(f"Q- chroma_sync indexed {indexed} chunk(s) for doc_id={new_doc.DocumentID}")

            except Exception as sync_err:
                # Chroma sync failure must NOT roll back the DB commit — the
                # document and chunks are already safely stored. Log and continue.
                print(f"Q- WARNING: chroma_sync failed for doc_id={new_doc.DocumentID}: {sync_err}")

        # Return a success response to the frontend.
        # The response includes counts so the admin can see what was processed.
        return {
            "message": "Document processed and saved successfully",
            "document_id": new_doc.DocumentID,
            "saved_events_count": saved_events_count,
            "saved_chunks_count": saved_chunks_count,
            "pages_detected": pages_count,
            "words_extracted": words_count
        }

    except Exception as e:
        # Roll back any uncommitted database changes if an error happens.
        # This prevents partial or broken records from being saved.
        db.rollback()

        # Print the error in the backend logs for debugging.
        print("ERROR in /admin/process-and-save-document:", str(e))

        # Return a 500 error response to the frontend with the error details.
        raise HTTPException(status_code=500, detail=str(e))



# ==============================
# CHAT / RAG ENDPOINTS
# ==============================

@app.post("/conversations", response_model=ConversationResponse)
def create_conversation(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    new_convo = Conversation(UserID=current_user.UserID)
    db.add(new_convo)
    db.commit()
    db.refresh(new_convo)
    return {
        "conversation_id": new_convo.ConversationID,
        "start_at": new_convo.StartAt,
        "messages": []
    }

@app.get("/conversations")
def list_conversations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    conversations = db.query(Conversation).filter(Conversation.UserID == current_user.UserID).order_by(Conversation.StartAt.desc()).all()
    return {
        "conversations": [
            {
                "id": c.ConversationID,
                "start_at": c.StartAt,
                "title": c.Title or None,  # null when no first message yet
            }
            for c in conversations
        ]
    }

@app.delete("/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    convo = db.query(Conversation).filter(Conversation.ConversationID == conversation_id, Conversation.UserID == current_user.UserID).first()
    if not convo:
        raise HTTPException(status_code=404, detail="Conversation not found")
    db.delete(convo)
    db.commit()
    return {"message": "Conversation deleted"}


@app.patch("/conversations/{conversation_id}/title")
def rename_conversation(
    conversation_id: int,
    data: ConversationTitleRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Persist a display title for a conversation.
    Body: { "title": "<raw first message text>" }
    The backend trims, collapses whitespace, and caps at 50 chars.
    Only the conversation owner may rename it.
    """
    import re as _re
    raw = data.title.strip()
    if not raw:
        raise HTTPException(status_code=400, detail="title is required")

    # Clean: collapse whitespace, strip emoji, truncate to 50 chars
    title = _re.sub(r"\s+", " ", raw)
    title = _re.sub(r"[\U0001F600-\U0001FFFF]", "", title, flags=_re.UNICODE).strip()
    if len(title) > 50:
        title = title[:48].rstrip() + "\u2026"
    if not title:
        raise HTTPException(status_code=400, detail="title is empty after cleaning")


    convo = db.query(Conversation).filter(
        Conversation.ConversationID == conversation_id,
        Conversation.UserID == current_user.UserID
    ).first()
    if not convo:
        raise HTTPException(status_code=404, detail="Conversation not found")

    convo.Title = title
    db.commit()
    return {"conversation_id": conversation_id, "title": title}



@app.get("/messages/{conversation_id}")
def get_messages(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    convo = db.query(Conversation).filter(Conversation.ConversationID == conversation_id, Conversation.UserID == current_user.UserID).first()
    if not convo:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    messages = db.query(Message).filter(Message.ConversationID == conversation_id).order_by(Message.CreatedAt.asc()).all()
    return {"messages": [{"id": m.MessageID, "sendtype": m.SendType, "content": m.Content, "created_at": m.CreatedAt} for m in messages]}

@app.post("/messages")
def send_message(
    data: MessageCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # ✅ Auto-create a conversation if the client sends 0 or a non-existent ID
    if data.conversation_id == 0:
        convo = Conversation(UserID=current_user.UserID)
        db.add(convo)
        db.commit()
        db.refresh(convo)
    else:
        convo = db.query(Conversation).filter(
            Conversation.ConversationID == data.conversation_id,
            Conversation.UserID == current_user.UserID
        ).first()
        if not convo:
            # Stale/wrong ID — create a fresh conversation automatically
            convo = Conversation(UserID=current_user.UserID)
            db.add(convo)
            db.commit()
            db.refresh(convo)

    # Save user message
    user_msg = Message(
        ConversationID=convo.ConversationID,
        SendType="user",
        Content=data.content
    )
    db.add(user_msg)
    db.commit()

    # ── Auto-set title from the first user message ──────────────────────────
    # Refresh so we see the latest DB state (Title may have been set by a
    # concurrent request or a previous partial commit).
    db.refresh(convo)
    if not convo.Title:                         # catches None AND ""
        import re as _re
        raw_title = data.content.strip()
        clean_title = _re.sub(r"\s+", " ", raw_title)
        clean_title = _re.sub(r"[\U0001F600-\U0001FFFF]", "", clean_title,
                               flags=_re.UNICODE).strip()
        if len(clean_title) > 50:
            clean_title = clean_title[:48].rstrip() + "\u2026"
        if clean_title:
            convo.Title = clean_title
            db.commit()
            db.refresh(convo)

    # Retrieve history
    past_messages = db.query(Message).filter(Message.ConversationID == convo.ConversationID).order_by(Message.CreatedAt.asc()).all()
    history = [{"role": m.SendType, "content": m.Content} for m in past_messages]

    # AGENT — ReAct loop with tool calling; falls back to ask_rag on error
    answer = agent.run_agent(data.content, history, db=db, user_type=current_user.UserType or "all")

    # Save assistant message
    bot_msg = Message(
        ConversationID=convo.ConversationID,
        SendType="assistant",
        Content=answer
    )
    db.add(bot_msg)
    db.commit()
    db.refresh(bot_msg)

    return {
        "message_id": bot_msg.MessageID,
        "conversation_id": convo.ConversationID,  # always the real ID (may differ from data.conversation_id if auto-created)
        "sendtype": bot_msg.SendType,
        "content": bot_msg.Content,
        "created_at": bot_msg.CreatedAt
    }

@app.post("/guest-chat")
def guest_chat(data: GuestChatRequest, db: Session = Depends(get_db)):
    # Guest chat: stateless — routed through the agent (no conversation history)
    answer = agent.run_agent(data.content, history=[], db=db, user_type="guest")
    return {"content": answer}