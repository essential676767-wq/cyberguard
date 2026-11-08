from fastapi import FastAPI, Depends, HTTPException, Request, UploadFile, File, Form
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from jose import JWTError, jwt
from datetime import datetime, timedelta
import os, hashlib, random, shutil
from pydantic import BaseModel
from dotenv import load_dotenv
from database import SessionLocal, User, Message, Order

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY", "fallback_secret_key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 365 # 1 год

app = FastAPI()

# --- CORS (разрешаем запросы с любых доменов для теста) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs(os.path.join(BASE_DIR, "static", "avatars"), exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, "static", "uploads"), exist_ok=True)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_current_user(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("access_token")
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
    
    if not token:
        raise HTTPException(status_code=401, detail="Не авторизован")
        
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        if email is None:
            raise HTTPException(status_code=401, detail="Неверный токен")
    except JWTError:
        raise HTTPException(status_code=401, detail="Неверный токен")
        
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    return user

def get_admin_user(user: User = Depends(get_current_user)):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Доступ запрещён. Вы не администратор.")
    return user

def get_password_hash(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return get_password_hash(plain_password) == hashed_password

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

# --- АВТОРИЗАЦИЯ И РЕГИСТРАЦИЯ ---

@app.post("/register")
def register(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == form_data.username).first():
        raise HTTPException(status_code=400, detail="Email уже занят")
    
    code = str(random.randint(100000, 999999))
    new_user = User(
        email=form_data.username, 
        hashed_password=get_password_hash(form_data.password), 
        is_active=False, 
        confirmation_token=code
    )
    db.add(new_user)
    db.commit()
    
    # В реальности здесь нужно отправить код на почту через SMTP.
    # Для теста возвращаем код прямо в ответе.
    return {"message": "OK", "code": code}

@app.post("/api/verify_code")
def verify_code(email: str, code: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == email).first()
    if not user or user.confirmation_token != code:
        raise HTTPException(status_code=400, detail="Неверный код подтверждения")
    
    user.is_active = True
    user.confirmation_token = None
    db.commit()
    return {"status": "ok"}

@app.post("/token")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Подтвердите почту перед входом")
        
    return {"access_token": create_access_token(data={"sub": user.email}), "token_type": "bearer"}

@app.get("/api/me")
def read_users_me(user: User = Depends(get_current_user)):
    return {"email": user.email, "is_admin": user.is_admin}

# --- ЗАКАЗЫ ---

class OrderCreate(BaseModel):
    title: str
    amount: int

@app.post("/api/orders")
def create_order(order: OrderCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not order.title or order.amount <= 0:
        raise HTTPException(status_code=400, detail="Некорректные данные")
    new_order = Order(user_id=user.id, title=order.title, amount=order.amount)
    db.add(new_order)
    db.commit()
    db.refresh(new_order)
    return {"order_id": new_order.id, "amount": new_order.amount, "status": new_order.status}

@app.get("/api/orders")
def get_orders(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    orders = db.query(Order).filter(Order.user_id == user.id).order_by(Order.created_at.desc()).all()
    return [{"id": o.id, "title": o.title, "amount": o.amount, "status": o.status} for o in orders]

@app.post("/api/pay/{order_id}")
def pay_order(order_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id, Order.user_id == user.id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Заказ не найден")
    return {"link": "https://yoomoney.ru/to/4100117382674034"}

@app.post("/api/confirm_payment/{order_id}")
def confirm_payment(order_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id, Order.user_id == user.id).first()
    if order:
        order.status = "paid"
        db.commit()
    return {"status": "ok"}

@app.post("/api/upload_file")
def upload_file(file: UploadFile = File(...), user: User = Depends(get_current_user)):
    file_path = os.path.join(BASE_DIR, "static", "uploads", f"{user.id}_{file.filename}")
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return {"status": "ok", "filename": file.filename}

# --- ЧАТ ---

class ChatMessage(BaseModel):
    text: str

@app.post("/api/chat/send")
def send_chat_message(msg: ChatMessage, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    new_msg = Message(user_id=user.id, text=msg.text, is_from_admin=False)
    db.add(new_msg)
    db.commit()
    return {"status": "ok"}

@app.get("/api/chat/history")
def get_chat_history(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    msgs = db.query(Message).filter(Message.user_id == user.id).order_by(Message.created_at).all()
    return [{"text": m.text, "is_admin": m.is_from_admin} for m in msgs]

# --- АДМИН ЧАТ ---

@app.get("/api/admin/chats")
def get_admin_chats(admin: User = Depends(get_admin_user), db: Session = Depends(get_db)):
    users = db.query(User).all()
    result = []
    for u in users:
        msgs = db.query(Message).filter(Message.user_id == u.id).order_by(Message.created_at).all()
        if msgs:
            result.append({
                "user_id": u.id,
                "email": u.email,
                "messages": [{"text": m.text, "is_admin": m.is_from_admin} for m in msgs]
            })
    return result

class AdminReply(BaseModel):
    user_id: int
    text: str

@app.post("/api/admin/reply")
def admin_reply(reply: AdminReply, admin: User = Depends(get_admin_user), db: Session = Depends(get_db)):
    new_msg = Message(user_id=reply.user_id, text=reply.text, is_from_admin=True)
    db.add(new_msg)
    db.commit()
    return {"status": "ok"}

# --- СТАТИКА И СТРАНИЦЫ ---

app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

@app.get("/")
def read_index(): return FileResponse(os.path.join(BASE_DIR, "static", "index.html"))
@app.get("/login")
def read_login(): return FileResponse(os.path.join(BASE_DIR, "static", "login.html"))
@app.get("/register")
def read_register(): return FileResponse(os.path.join(BASE_DIR, "static", "register.html"))
@app.get("/dashboard")
def read_dashboard(): return FileResponse(os.path.join(BASE_DIR, "static", "dashboard.html"))
@app.get("/admin")
def read_admin(): return FileResponse(os.path.join(BASE_DIR, "static", "admin.html"))
@app.get("/privacy")
def read_privacy(): return FileResponse(os.path.join(BASE_DIR, "static", "privacy.html"))
@app.get("/terms")
def read_terms(): return FileResponse(os.path.join(BASE_DIR, "static", "terms.html"))
@app.get("/offer")
def read_offer(): return FileResponse(os.path.join(BASE_DIR, "static", "offer.html"))
@app.get("/verify")
def read_verify(): return FileResponse(os.path.join(BASE_DIR, "static", "verify.html"))
