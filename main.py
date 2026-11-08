from fastapi import FastAPI, Depends, HTTPException, Request, UploadFile, File
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
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
os.makedirs(os.path.join(BASE_DIR, "static", "avatars"), exist_ok=True)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_current_user(request: Request, db: Session = Depends(get_db)):
    # Пытаемся взять токен из куки
    token = request.cookies.get("access_token")
    # Если нет, пытаемся из заголовка
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

def get_password_hash(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return get_password_hash(plain_password) == hashed_password

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

@app.post("/register")
def register(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == form_data.username).first():
        raise HTTPException(status_code=400, detail="Email занят")
    new_user = User(email=form_data.username, hashed_password=get_password_hash(form_data.password), is_active=True)
    db.add(new_user)
    db.commit()
    return {"message": "OK"}

@app.post("/token")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
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

@app.post("/api/confirm_payment/{order_id}")
def confirm_payment(order_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id, Order.user_id == user.id).first()
    if order:
        order.status = "paid"
        db.commit()
    return {"status": "ok"}

# --- ЧАТ ---
class ChatMessage(BaseModel):
    text: str

@app.post("/api/chat/send")
def send_chat_message(msg: ChatMessage, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    new_msg = Message(user_id=user.id, text=msg.text, is_from_admin=False)
    db.add(new_msg)
    db.commit()
    return {"status": "ok"}

# --- ФАЙЛЫ ---
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

@app.get("/")
def read_index(): return FileResponse(os.path.join(BASE_DIR, "static", "index.html"))
@app.get("/login")
def read_login(): return FileResponse(os.path.join(BASE_DIR, "static", "login.html"))
@app.get("/register")
def read_register(): return FileResponse(os.path.join(BASE_DIR, "static", "register.html"))
@app.get("/dashboard")
def read_dashboard(): return FileResponse(os.path.join(BASE_DIR, "static", "dashboard.html"))
@app.get("/privacy")
def read_privacy(): return FileResponse(os.path.join(BASE_DIR, "static", "privacy.html"))
@app.get("/terms")
def read_terms(): return FileResponse(os.path.join(BASE_DIR, "static", "terms.html"))
@app.get("/offer")
def read_offer(): return FileResponse(os.path.join(BASE_DIR, "static", "offer.html"))
