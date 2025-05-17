from fastapi import APIRouter, Depends, status, Form, Request, HTTPException, File, UploadFile
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from .deps import get_account_service
from .schemas import CreateAccountSchema, AccountSchema, TokenSchema, AccountType
from .auth_logic import AuthLogic
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
# from config import db, SECRET_KEY
from datetime import datetime, date, timezone, timedelta, time
from email.message import EmailMessage
import os
import smtplib
import uuid
from dotenv import load_dotenv
import certifi
from motor.motor_asyncio import AsyncIOMotorClient
from config import get_db, SECRET_KEY

load_dotenv()

templates = Jinja2Templates(directory="templates")
account_router = APIRouter(prefix='/account', tags=['account'])

# Serializer dùng chung để sign/verify token
# SECRET_KEY = os.getenv("SECRET_KEY")
# MONGODB_URI = os.getenv("MONGODB_URI")
# if not MONGODB_URI:
#     raise RuntimeError("MONGODB_URI chưa được thiết lập!")


# async def get_db():
#     """
#     Mỗi lần có request, ta khởi tạo một client mới trên event‐loop hiện tại,
#     và đóng nó khi xong request.
#     """
#     client = AsyncIOMotorClient(
#         MONGODB_URI,
#         tls=True,
#         tlsCAFile=certifi.where(),
#     )
#     try:
#         yield client["hotel_database"]
#     finally:
#         client.close()


serializer = URLSafeTimedSerializer(SECRET_KEY)

# --- cấu hình SMTP ---
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")

router_data = {
    'registration': {
        'path': '/registration',
        'status_code': status.HTTP_201_CREATED,
        'response_model': AccountSchema,
        'response_model_by_alias': False
    },
    'login': {
        'path': '/login',
        'status_code': status.HTTP_200_OK,
        'response_model': TokenSchema
    }
}

# --- helper gửi mail ---


async def send_reset_email(request: Request, to_email: str, token: str):
    """
    Gửi thư đổi mật khẩu, link sẽ là:
      {base_url}/account/reset-password/{token}
    Có hiệu lực 1 giờ.
    """
    path = request.url_for("reset_password_page", token=token)
    reset_link = f"{path}"

    msg = EmailMessage()
    msg["Subject"] = "QLPT: Đặt lại mật khẩu"
    msg["From"] = SMTP_USER
    msg["To"] = to_email
    msg.set_content(f"""Xin chào,

Bạn (hoặc ai đó) đã yêu cầu đặt lại mật khẩu cho tài khoản QLPT của bạn.
Vui lòng nhấp vào đường link bên dưới để đặt lại mật khẩu (hiệu lực 1 giờ):

{reset_link}

Nếu bạn không yêu cầu, vui lòng bỏ qua email này.

Trân trọng,
Đội ngũ QLPT
""")

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)


@account_router.get("/register", tags=["account"])
async def register_page(request: Request, db=Depends(get_db)):
    """Render the registration page"""
    return templates.TemplateResponse("register.html", {"request": request})


@account_router.post(
    "/registration",
    status_code=status.HTTP_201_CREATED,
    response_model=AccountSchema,
    response_model_by_alias=False
)
async def register(
    request: Request,
    account_data: CreateAccountSchema,
    service_data=Depends(get_account_service),
    db=Depends(get_db)
):
    """Handle registration API request"""
    try:
        user_dict = await AuthLogic(**service_data).save_user(account_data=account_data)
        # validate/convert to AccountSchema (Pydantic v2)
        user = AccountSchema.model_validate(user_dict)

        request.session["user"] = {
            "email": user.email,
            "full_name": f"{user.first_name or ''} {user.last_name or ''}".strip(),
            "is_owner": user.account_type == AccountType.AGENT
        }

        return user  # Already a Pydantic model

    except Exception as e:
        # For API clients, raise an HTTP exception
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@account_router.post(**router_data.get('login'))
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    service_data=Depends(get_account_service),
    db=Depends(get_db)
):
    try:
        # 1) authenticate & get JWT
        token_data = await AuthLogic(**service_data).login(email=email, password=password)

        # 2) fetch full user, validate into Pydantic model
        user_dict = await AuthLogic(**service_data).get_user_by_email(email)
        user = AccountSchema.model_validate(user_dict)

        # 3) store whatever you need in session
        request.session["user"] = {
            "email":     user.email,
            "full_name": f"{user.first_name or ''} {user.last_name or ''}".strip(),
            "is_owner":  user.account_type == AccountType.AGENT
        }
        # (optionally) keep the token if you need it for JS/API calls:
        request.session["token"] = token_data["token"]

        # 4) redirect to home (instead of returning the JSON)
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    except Exception as e:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": str(e)},
            status_code=400
        )


@account_router.get("/logout", tags=["account"])
async def logout(request: Request, db=Depends(get_db)):
    # Clear session
    request.session.pop("user", None)
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@account_router.get(
    "/forgot-password",
    response_class=HTMLResponse,
    tags=["account"],
    name="forgot_password_page"
)
async def forgot_password_page(request: Request, db=Depends(get_db)):
    """
    Hiển thị form nhập email để gửi link đặt lại mật khẩu
    """
    return templates.TemplateResponse("forgot_password.html", {"request": request})


@account_router.post(
    "/forgot-password",
    response_class=HTMLResponse,
    tags=["account"],
    name="forgot_password"
)
async def forgot_password(
    request: Request,
    email: str = Form(...),
    db=Depends(get_db)
):
    """
    Xử lý form quên mật khẩu, sinh token và gửi email qua SMTP
    """
    # 1) Kiểm tra user
    user = await db.account.find_one({"email": email})
    if user:
        # 2) Tạo token và lưu vào DB
        token = uuid.uuid4().hex
        expires = datetime.now(timezone.utc) + timedelta(hours=1)
        await db.password_resets.insert_one({
            "token":      token,
            "email":      email,
            "expires_at": expires
        })
        # 3) Gửi email
        await send_reset_email(request, email, token)

    # Không phân biệt tồn tại hay không, vẫn redirect về trang "đã gửi"
    return RedirectResponse(
        request.url_for("forgot_password_sent"),
        status_code=status.HTTP_303_SEE_OTHER
    )


@account_router.get(
    "/forgot-password/sent",
    response_class=HTMLResponse,
    tags=["account"],
    name="forgot_password_sent"
)
async def forgot_password_sent(request: Request, db=Depends(get_db)):
    return templates.TemplateResponse("forgot_password_sent.html", {"request": request})


@account_router.get("/reset-password")
async def reset_password_page(request: Request, token: str | None = None, db=Depends(get_db)):
    """
    Hiển thị form đặt lại mật khẩu nếu token hợp lệ
    """
    if not token:
        return RedirectResponse("/account/login", status_code=status.HTTP_303_SEE_OTHER)
    try:
        email = serializer.loads(
            token, salt="password-reset-salt", max_age=3600)
    except SignatureExpired:
        return templates.TemplateResponse(
            "forgot_password.html",
            {"request": request, "error": "Liên kết đã hết hạn. Vui lòng gửi lại yêu cầu."}
        )
    except BadSignature:
        return templates.TemplateResponse(
            "forgot_password.html",
            {"request": request, "error": "Liên kết không hợp lệ."}
        )
    return templates.TemplateResponse("reset_password.html", {"request": request, "token": token})


@account_router.post("/reset-password")
async def reset_password(
    request: Request,
    token: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    db=Depends(get_db)
):
    """
    Xử lý form đặt lại mật khẩu
    """
    if password != confirm_password:
        return templates.TemplateResponse(
            "reset_password.html",
            {"request": request, "token": token,
                "error": "Mật khẩu xác nhận không khớp."}
        )
    try:
        email = serializer.loads(
            token, salt="password-reset-salt", max_age=3600)
    except SignatureExpired:
        return templates.TemplateResponse(
            "forgot_password.html",
            {"request": request, "error": "Liên kết đã hết hạn. Vui lòng gửi lại yêu cầu."}
        )
    except BadSignature:
        return templates.TemplateResponse(
            "forgot_password.html",
            {"request": request, "error": "Liên kết không hợp lệ."}
        )
    # Cập nhật mật khẩu mới (nên hash lại nếu dùng production)
    await db.users.update_one({"email": email}, {"$set": {"password": password}})
    success = "Đặt lại mật khẩu thành công. Vui lòng đăng nhập lại."
    return templates.TemplateResponse("login.html", {"request": request, "info": success})


@account_router.get(
    "/bookings",
    response_class=HTMLResponse,
    tags=["booking"],
    name="my_bookings"
)
async def my_bookings(request: Request, db=Depends(get_db)):
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/account/login", status_code=status.HTTP_303_SEE_OTHER)

    # 1) Tìm các listing do user làm chủ
    owned_listings = await db.listings.find({"owner": user["email"]}).to_list(length=100)
    owned_ids = [l["id"] for l in owned_listings]

    # 2) Lấy về tất cả booking mà user là tenant hoặc là chủ của listing đó
    cursor = db.bookings.find({
        "$or": [
            {"tenant": user["email"]},
            {"listing_id": {"$in": owned_ids}}
        ]
    }).sort("start_date", -1)
    bookings = await cursor.to_list(length=100)

    # 3) Gắn thêm thông tin để template dễ render
    for b in bookings:
        lst = await db.listings.find_one({"id": b["listing_id"]})
        b["listing_title"] = lst["title"]
        b["is_owner"] = (lst["owner"] == user["email"])
        # owner_signature chỉ tồn tại sau khi chủ ký
        b["owner_signature"] = b.get("owner_signature")

    return templates.TemplateResponse("my_bookings.html", {
        "request":  request,
        "bookings": bookings,
    })


@account_router.get(
    "/bookings/{booking_id}/renew",
    response_class=HTMLResponse,
    name="renew_request_page",
    tags=["booking"]
)
async def renew_request_page(request: Request, booking_id: str, db=Depends(get_db)):
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/account/login", status_code=status.HTTP_303_SEE_OTHER)

    # Lấy notification
    notif = await db.notifications.find_one({
        "booking_id": booking_id,
        "type":       "renew_request",
        "user":       user["email"]
    })
    if not notif:
        raise HTTPException(404, "Không tìm thấy yêu cầu gia hạn.")

    booking = await db.bookings.find_one({"id": booking_id})
    listing = await db.listings.find_one({"id": booking["listing_id"]})

    return templates.TemplateResponse("renew_contract.html", {
        "request":     request,
        "booking":     booking,
        "listing":     listing,
        "notif":       notif,
        "user":        user
    })


@account_router.post(
    "/bookings/{booking_id}/renew",
    response_class=HTMLResponse,
    name="renew_request_action",
    tags=["booking"]
)
async def renew_request_action(
    request: Request,
    booking_id: str,
    action: str = Form(...),  # "accept" hoặc "reject"
    db=Depends(get_db)
):
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/account/login", status_code=status.HTTP_303_SEE_OTHER)

    # Lấy notification
    notif = await db.notifications.find_one({
        "booking_id": booking_id,
        "type":       "renew_request",
        "user":       user["email"]
    })
    if not notif:
        raise HTTPException(404, "Không tìm thấy yêu cầu gia hạn.")

    now = datetime.now(timezone.utc)

    if action == "accept":
        # 1) Cập nhật booking với new_end_date
        await db.bookings.update_one(
            {"id": booking_id},
            {"$set": {
                "end_date":   notif["new_end_date"],
                "updated_at": now
            }}
        )
        # 2) Cập nhật notification
        await db.notifications.update_one(
            {"id": notif["id"]},
            {"$set": {
                "status":       "accepted",
                "read":         True,
                "responded_at": now,
                "message":      f"Đã chấp nhận yêu cầu gia hạn đến {notif['new_end_date'].date()}"
            }}
        )
    else:
        # reject
        await db.notifications.update_one(
            {"id": notif["id"]},
            {"$set": {
                "status":       "rejected",
                "read":         True,
                "responded_at": now,
                "message":      "Từ chối yêu cầu gia hạn"
            }}
        )

    return RedirectResponse(
        request.url_for("my_bookings"),
        status_code=status.HTTP_303_SEE_OTHER
    )


@account_router.get(
    "/bookings/{booking_id}/sign",
    response_class=HTMLResponse,
    name="sign_contract_page"
)
async def sign_contract_page(request: Request, booking_id: str, db=Depends(get_db)):
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/account/login", status_code=status.HTTP_303_SEE_OTHER)

    booking = await db.bookings.find_one({"id": booking_id})
    if not booking:
        raise HTTPException(status_code=404, detail="Không tìm thấy booking.")

    listing = await db.listings.find_one({"id": booking["listing_id"]})
    # chỉ tenant hoặc owner mới được xem
    if user["email"] not in (booking["tenant"], listing["owner"]):
        raise HTTPException(status_code=403, detail="Không có quyền.")

    return templates.TemplateResponse("sign_contract.html", {
        "request": request,
        "booking": booking,
        "listing": listing,
        "user":    user
    })


@account_router.post(
    "/bookings/{booking_id}/sign",
    response_class=HTMLResponse,
    name="sign_contract"
)
async def sign_contract(
    request: Request,
    booking_id: str,
    # chung cho cả owner và tenant
    signature:       UploadFile = File(None),
    # riêng tenant
    tenant_name:     str = Form(None),
    tenant_phone:    str = Form(None),
    tenant_id_card:  str = Form(None),
    # riêng owner
    action:          str = Form("accepted"),
    db=Depends(get_db)
):
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/account/login", status_code=status.HTTP_303_SEE_OTHER)

    booking = await db.bookings.find_one({"id": booking_id})
    if not booking:
        raise HTTPException(status_code=404, detail="Không tìm thấy hợp đồng.")

    listing = await db.listings.find_one({"id": booking["listing_id"]})
    if not listing:
        raise HTTPException(
            status_code=404, detail="Không tìm thấy tin đăng liên quan.")

    now = datetime.now(timezone.utc)
    # ---- Tenant ký hợp đồng ----
    if user["email"] == booking["tenant"]:
        # validate
        if not all([tenant_name, tenant_phone, tenant_id_card, signature]):
            raise HTTPException(
                status_code=400, detail="Vui lòng cung cấp đủ thông tin và chữ ký.")
        # lưu file chữ ký
        fn = f"{uuid.uuid4().hex}_{signature.filename}"
        dirp = os.path.join("static", "uploads", "signatures")
        os.makedirs(dirp, exist_ok=True)
        fp = os.path.join(dirp, fn)
        with open(fp, "wb") as f:
            f.write(await signature.read())
        sig_url = f"/static/uploads/signatures/{fn}"

        # update booking với thông tin tenant
        await db.bookings.update_one(
            {"id": booking_id},
            {"$set": {
                "tenant_name":     tenant_name,
                "tenant_phone":    tenant_phone,
                "tenant_id_card":  tenant_id_card,
                "tenant_signature": sig_url,
                "updated_at":      now
            }}
        )
        # tạo/đánh dấu notification cho owner xem contract mới
        await db.notifications.update_one(
            {"booking_id": booking_id, "type": "booking_request"},
            {"$set": {"read": False, "updated_at": now}}
        )

    # ---- Owner ký (lưu chữ ký chủ và update status) ----
    elif user["email"] == listing["owner"]:
        if not signature:
            raise HTTPException(
                status_code=400, detail="Vui lòng upload chữ ký.")
        # 1) Lưu file chữ ký owner
        fn = f"{uuid.uuid4().hex}_{signature.filename}"
        dirp = os.path.join("static", "uploads", "signatures")
        os.makedirs(dirp, exist_ok=True)
        fp = os.path.join(dirp, fn)
        with open(fp, "wb") as f:
            f.write(await signature.read())
        owner_sig_url = f"/static/uploads/signatures/{fn}"

        # 2) Update booking: owner_signature + status
        await db.bookings.update_one(
            {"id": booking_id},
            {"$set": {
                "owner_signature": owner_sig_url,
                "status":         "accepted",
                "updated_at":     now
            }}
        )
        # 3) Cập nhật notification (đổi type thành response, ẩn button)
        await db.notifications.update_one(
            {"booking_id": booking_id,
                "user": listing["owner"], "type": "booking_request"},
            {"$set": {
                "type":    "booking_response",
                "status":  "accepted",
                "read":    True,
                "message": f"Đã chấp nhận yêu cầu hợp đồng phòng '{listing['title']}'",
                "responded_at": now
            }}
        )

    else:
        raise HTTPException(
            status_code=403, detail="Bạn không có quyền thực hiện hành động này.")

    return RedirectResponse(
        request.url_for("view_contract", booking_id=booking_id),
        status_code=status.HTTP_303_SEE_OTHER
    )


@account_router.get(
    "/notifications",
    response_class=HTMLResponse,
    tags=["notification"],
    name="notifications_page"
)
async def notifications_page(request: Request, db=Depends(get_db)):
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/account/login", status_code=status.HTTP_303_SEE_OTHER)
    # load tất cả thông báo
    notifs = await db.notifications\
        .find({"user": user["email"]})\
        .sort("created_at", -1)\
        .to_list(length=100)
    # để template dễ render thêm booking/listing
    for n in notifs:
        n["booking"] = await db.bookings.find_one({"id": n["booking_id"]})
        n["listing"] = await db.listings.find_one({"id": n["listing_id"]})
    return templates.TemplateResponse("notifications.html", {
        "request":       request,
        "notifications": notifs
    })


@account_router.post(
    "/notifications/{notif_id}/respond",
    response_class=HTMLResponse,
    tags=["notification"],
    name="respond_notification"
)
async def respond_notification(
    request: Request,
    notif_id: str,
    action: str = Form(...),
    db=Depends(get_db)
):
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/account/login", status_code=status.HTTP_303_SEE_OTHER)

    # 1) Load notification & related data
    n = await db.notifications.find_one({"id": notif_id})
    if not n or n["user"] != user["email"] or n["type"] != "booking_request":
        raise HTTPException(status_code=403, detail="Không hợp lệ.")
    b = await db.bookings.find_one({"id": n["booking_id"]})
    lst = await db.listings.find_one({"id": n["listing_id"]})

    if action not in ("accepted", "rejected"):
        raise HTTPException(status_code=400, detail="Action không hợp lệ.")

    now = datetime.now(timezone.utc)
    # 2) Cập nhật trạng thái booking
    await db.bookings.update_one(
        {"id": b["id"]},
        {"$set": {"status": action, "updated_at": now}}
    )

    # 3) Override notification cũ với message mới và đổi type
    new_msg = (
        f"Đã chấp nhận yêu cầu hợp đồng phòng '{lst['title']}'"
        if action == "accepted"
        else f"Đã từ chối yêu cầu hợp đồng phòng '{lst['title']}'"
    )
    await db.notifications.update_one(
        {"id": notif_id},
        {"$set": {
            "type":         "booking_response",
            "status":       action,
            "read":         True,
            "message":      new_msg,
            "responded_at": now
        }}
    )

    # 4) (Optional) Tạo notif cho tenant nếu bạn vẫn muốn
    # …

    return RedirectResponse(
        request.url_for("notifications_page"),
        status_code=status.HTTP_303_SEE_OTHER
    )


@account_router.get(
    "/bookings/{booking_id}/contract",
    response_class=HTMLResponse,
    tags=["booking"],
    name="view_contract"
)
async def view_contract(request: Request, booking_id: str, db=Depends(get_db)):
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/account/login", status_code=status.HTTP_303_SEE_OTHER)

    booking = await db.bookings.find_one({"id": booking_id})
    if not booking:
        raise HTTPException(status_code=404, detail="Không tìm thấy hợp đồng.")

    listing = await db.listings.find_one({"id": booking["listing_id"]})
    if user["email"] not in (booking["tenant"], listing["owner"]):
        raise HTTPException(
            status_code=403, detail="Bạn không có quyền xem hợp đồng này.")

    return templates.TemplateResponse("contract_detail.html", {
        "request": request,
        "booking": booking,
        "listing": listing,
        "user":    user
    })


@account_router.post("/listing/{listing_id}/book", name="book_listing")
async def book_listing(
    request: Request,
    listing_id: str,
    start_date: str = Form(...),
    end_date:   str = Form(...),
    db=Depends(get_db)
):
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/account/login", status_code=303)

    # 1) Tạo booking mới
    booking_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    new_booking = {
        "id":            booking_id,
        "listing_id":    listing_id,
        "tenant":        user["email"],
        "start_date":    datetime.fromisoformat(start_date),
        "end_date":      datetime.fromisoformat(end_date),
        "status":        "pending",
        "created_at":    now,
        "updated_at":    now
    }
    await db.bookings.insert_one(new_booking)

    # 2) Tạo notification cho chủ nhà
    listing = await db.listings.find_one({"id": listing_id})
    await db.notifications.insert_one({
        "id":          uuid.uuid4().hex,
        "user":        listing["owner"],
        "type":        "booking_request",
        "booking_id":  booking_id,
        "listing_id":  listing_id,
        "message":     f"{user['email']} yêu cầu ký hợp đồng phòng '{listing['title']}'",
        "status":      "pending",
        "created_at":  now,
        "read":        False
    })

    # 3) Redirect tenant sang trang ký hợp đồng
    return RedirectResponse(
        request.url_for("sign_contract", booking_id=booking_id),
        status_code=303
    )
