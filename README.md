# MujeebKAU


Mujeeb KAU is an AI-powered academic assistant for King Abdulaziz University.  
The system helps students and faculty access academic information faster by asking questions in natural language and receiving grounded answers based on university documents, academic calendars, and stored knowledge.

## Overview

Mujeeb KAU is not a basic chatbot. It combines:

- FastAPI backend
- PostgreSQL database
- ChromaDB vector database
- OCR document processing
- RAG retrieval pipeline
- Agentic AI tool-calling layer
- Academic calendar extraction
- User authentication
- Admin document management
- Notifications system

The assistant is designed to answer academic questions using trusted university-related data instead of relying on general AI knowledge.

## Main Features

### AI Academic Assistant

Users can ask academic questions in Arabic or English.  
The system retrieves relevant information from the knowledge base and generates a clear answer.

### Agentic AI Layer

Mujeeb uses an AI Agent that decides which tool to use depending on the question type:

- Academic event search for date-related questions
- Knowledge base search for policies, regulations, admission rules, and requirements
- GPA calculator for grade and credit-hour calculations

This makes the assistant more accurate than a normal chatbot because it can choose the right source or action before answering.

### Retrieval-Augmented Generation

The project uses a RAG pipeline to search university documents stored as chunks in ChromaDB.

The pipeline includes:

- Query embedding
- Vector search
- Relevance filtering
- Neighbor chunk expansion
- LLM-based reranking
- Context construction
- Grounded answer generation

### Document Processing

Admins can upload academic documents such as:

- Academic calendars
- Regulations
- Admission guides

The system processes uploaded files, extracts text, structures the content, saves it to the database, and syncs it with the vector database.

### OCR and Academic Calendar Extraction

For academic calendar files, the system uses OCR to extract text and detect academic events such as registration dates, exams, semester starts, and deadlines.

Detected events are saved into the database and can later be used by the AI Agent.

### Notifications

The system supports admin-created notifications and automatic academic-event reminders.  
It can notify users about upcoming academic events, announcements, deadlines, warnings, and updates.

### Authentication and User Management

The backend supports:

- Signup using KAU email only
- Email verification
- Login with JWT authentication
- Password reset
- Profile management
- Role-based access for students, faculty, and admins

## Tech Stack

- Python
- FastAPI
- PostgreSQL
- SQLAlchemy
- ChromaDB
- OpenAI-compatible API through deep.sa
- Gemini model
- Deep.sa embeddings
- PyMuPDF
- OCR API
- APScheduler
- JWT Authentication
