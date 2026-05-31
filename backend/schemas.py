from pydantic import BaseModel, EmailStr, Field
from typing import Literal, Optional, List
from datetime import datetime, date

class SignupRequest(BaseModel):
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    password: str
    confirm_password: str
    gender: Literal["male", "female"]
    user_type: Literal["student", "faculty"]
    college_name: str = Field(..., min_length=1, max_length=150)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class VerifyResetCodeRequest(BaseModel):
    email: EmailStr
    reset_code: str = Field(..., min_length=4, max_length=10)


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    reset_code: str = Field(..., min_length=4, max_length=10)
    new_password: str
    confirm_password: str


class VerifyEmailRequest(BaseModel):
    email: EmailStr
    verification_code: str = Field(..., min_length=4, max_length=10)


class ResendVerificationCodeRequest(BaseModel):
    email: EmailStr


class UpdateUserProfileRequest(BaseModel):
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    college_name: Optional[str] = Field(default=None, max_length=150)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
    confirm_password: str


class UpdateAdminProfileRequest(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=200)


class UserProfileResponse(BaseModel):
    user_id: int
    first_name: str
    last_name: str
    email: EmailStr
    user_type: str
    gender: Optional[str] = None
    college_name: Optional[str] = None
    is_verified: bool
    is_active: bool




class CreateNotificationRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    message: str = Field(..., min_length=1)
    audience: Literal["all", "student", "students", "faculty"]
    notification_type: Literal["announcement", "warning", "deadline", "update"]
    college_name: str = Field(..., min_length=1, max_length=150)
    schedule_time: datetime


class UpdateNotificationRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    message: str = Field(..., min_length=1)
    audience: Literal["all", "student", "students", "faculty"]
    notification_type: Literal["announcement", "warning", "deadline", "update"]
    college_name: str = Field(..., min_length=1, max_length=150)
    schedule_time: datetime


class NotificationResponse(BaseModel):
    id: int
    title: str
    message: str
    audience: str
    type: str
    college: str
    schedule_time: datetime
    status: str
    event_date: Optional[date] = None


class NotificationListResponse(BaseModel):
    notifications: List[NotificationResponse]


from pydantic import BaseModel
from datetime import datetime

class NotificationCreate(BaseModel):
    title: str
    message: str
    notification_type: str
    schedule_time: datetime

################### Shatha ######################
class DocumentResponse(BaseModel):
    doc_id: int
    filename: str
    doc_type: Optional[str] = None
    category: Optional[str] = None
    college: Optional[str] = None
    created_at: Optional[datetime] = None
 ######################################################

class MessageCreate(BaseModel):
    conversation_id: int = Field(default=0, ge=0)   # 0 = auto-create conversation
    content: str = Field(..., min_length=1)

class MessageResponse(BaseModel):
    message_id: int
    conversation_id: int
    sendtype: Literal["user", "assistant"]
    content: str
    created_at: datetime

class GuestChatRequest(BaseModel):
    content: str = Field(..., min_length=1)

class ConversationResponse(BaseModel):
    conversation_id: int
    start_at: datetime
    messages: List[MessageResponse] = []


class ConversationTitleRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)