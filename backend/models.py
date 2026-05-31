from sqlalchemy import Column, Integer, String, Text, Boolean, ForeignKey, TIMESTAMP, Numeric, Date
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, Boolean, DateTime
from datetime import datetime


Base = declarative_base()


class College(Base):
    __tablename__ = "college"

    CollegeID = Column("collegeid", Integer, primary_key=True, index=True)
    Name = Column("name", String(150), nullable=False)
    FPre = Column("fpre", Numeric(3, 2), nullable=True)
    MPre = Column("mpre", Numeric(3, 2), nullable=True)


class User(Base):
    __tablename__ = "User"

    UserID = Column("userid", Integer, primary_key=True, index=True)
    FirstName = Column("firstname", String(100), nullable=False)
    LastName = Column("lastname", String(100), nullable=False)
    UserType = Column("usertype", String(20), nullable=False)
    Email = Column("email", String(255), unique=True, nullable=False)
    Password = Column("password", Text, nullable=False)
    CreatedAt = Column("createdat", TIMESTAMP, server_default=func.now())  # DB col: createdat
    Gender = Column("gender", String(10), nullable=True)
    IsActive = Column("isactive", Boolean, default=True)
    CollegeID = Column("collegeid", Integer, ForeignKey("college.collegeid"), nullable=True)

    ResetCode = Column("resetcode", String, nullable=True)
    ResetCodeExpire = Column("resetcodeexpire", TIMESTAMP, nullable=True)
    ResetCodeSentAt = Column("resetcodesentat", TIMESTAMP, nullable=True)

    IsVerified = Column("isverified", Boolean, default=False)
    VerificationCode = Column("verificationcode", String, nullable=True)
    VerificationCodeExpire = Column("verificationcodeexpire", TIMESTAMP, nullable=True)
    VerificationCodeSentAt = Column("verificationcodesentat", TIMESTAMP, nullable=True)



class Notification(Base):
    __tablename__ = "notification"

    NotificationID = Column("notificationid", Integer, primary_key=True, index=True)
    Title = Column("title", String(255), nullable=False)
    Message = Column("message", Text, nullable=False)
    UserType = Column("usertype", String(20), nullable=True)
    NotificationType = Column("notificationtype", String(50), nullable=True)
    CreateAt = Column("createat", TIMESTAMP, server_default=func.now())
    UploadAt = Column("uploadat", TIMESTAMP, nullable=True)
    ScheduleTime = Column("scheduletime", TIMESTAMP, nullable=True)
    Status = Column("status", String(20), nullable=True)
    CollegeID = Column("collegeid", Integer, ForeignKey("college.collegeid"), nullable=True)
    AcadEventID = Column("acadeventid", Integer, nullable=True)
    EventDate = Column("eventdate", Date, nullable=True)

class UserNotification(Base):
    __tablename__ = "usernotification"

    NotificationID = Column(
        "notificationid",
        Integer,
        ForeignKey("notification.notificationid"),
        primary_key=True
    )
    UserID = Column(
        "userid",
        Integer,
        ForeignKey('User.userid'),
        primary_key=True
    )

    is_read = Column(Boolean, default=False)
    is_deleted = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

#-----------------------------
#cnversatin
#-----------------------------

class Conversation(Base):
    __tablename__ = "conversation"

    ConversationID = Column("conversationid", Integer, primary_key=True, index=True)
    UserID = Column("userid", Integer, ForeignKey("User.userid"))
    StartAt = Column("startat", TIMESTAMP, server_default=func.now())
    Title = Column("title", String(100), nullable=True)  # set from first user message

    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "message"

    MessageID = Column("messageid", Integer, primary_key=True, index=True)

    ConversationID = Column(
        "conversationid",
        Integer,
        ForeignKey("conversation.conversationid", ondelete="CASCADE")  # 🔥 هنا السحر
    )

    SendType = Column("sendtype", String(20))
    Content = Column("content", Text)
    CreatedAt = Column("createat", TIMESTAMP, server_default=func.now())  # DB col: createat (no 'd')

    conversation = relationship("Conversation", back_populates="messages")


class Document(Base):
    __tablename__ = "document"

    DocumentID = Column("documentid", Integer, primary_key=True, index=True)

    FileName = Column("filename", String(255), nullable=False)
    FilePath = Column("filepath", Text, nullable=False)

    DocumentType = Column("documenttype", String(50), nullable=True)
    WordExtract = Column("wordextract", Text, nullable=True)

    PagesDetected = Column("pagesdetected", Integer, nullable=True)
    StatusMessage = Column("statusmessage", Text, nullable=True)

    UploadAt = Column("uploadat", TIMESTAMP, server_default=func.now())

    UserType = Column("usertype", String(20), nullable=True)

    CollegeID = Column("collegeid", Integer, ForeignKey("college.collegeid"), nullable=True)

    Events = relationship(
        "AcademicEvent",
        back_populates="Document",
        cascade="all, delete-orphan",
        passive_deletes=True
    )

    Chunks = relationship(
        "KnowledgeChunk",
        back_populates="Document",
        cascade="all, delete-orphan",
        passive_deletes=True
    )


class AcademicEvent(Base):
    __tablename__ = "academicevent"

    AcadEventID = Column("acadeventid", Integer, primary_key=True, index=True)
    Title = Column("title", String(255), nullable=False)
    UserType = Column("usertype", String(20), nullable=True)

    StartDate = Column("startdate", Date, nullable=True)
    EndDate = Column("enddate", Date, nullable=True)

    HStartDate = Column("histartdate", Date, nullable=True)
    HEndDate = Column("hienddate", Date, nullable=True)

    DocID = Column(
        "docid",
        Integer,
        ForeignKey("document.documentid", ondelete="CASCADE"),
        nullable=False
    )

    Document = relationship("Document", back_populates="Events")


class KnowledgeChunk(Base):
    __tablename__ = "knowledgechunk"

    ChunkID = Column("chunkid", Integer, primary_key=True, index=True)
    DocID = Column(
        "docid",
        Integer,
        ForeignKey("document.documentid", ondelete="CASCADE"),
        nullable=False
    )

    ChunkText = Column("chunktext", Text, nullable=False)

    PageNumber = Column("pagenumber", Integer, nullable=True)
    ChunkOrder = Column("chunkorder", Integer, nullable=True)

    CreatedAt = Column("createdat", TIMESTAMP, server_default=func.now())

    Document = relationship("Document", back_populates="Chunks")