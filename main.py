from fastapi import FastAPI, Request, Form, HTTPException, status, UploadFile, File
import re
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from account.routers import account_router
from starlette.middleware.sessions import SessionMiddleware
from fastapi.responses import RedirectResponse, HTMLResponse, FileResponse
import os
import uuid
from datetime import datetime, timezone, date, timedelta
from math import ceil
from typing import List, Tuple, Optional
from urllib.parse import urlparse
import smtplib
from email.message import EmailMessage
from passlib.context import CryptContext
# from producer import producer
from contextlib import asynccontextmanager

# ← import db và SECRET_KEY từ config
from config import db, SECRET_KEY


# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     # startup
#     await producer.start()
#     yield
#     # shutdown
#     await producer.stop()


app = FastAPI(title="hotel_service")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def format_price(value):
    """
    Chuyển value (float/int) thành chuỗi với dấu '.' mỗi 3 chữ số,
    không có phần thập phân.
    Ví dụ: 1500000.0 → "1.500.000"
    """
    try:
        v = float(value)
    except (ValueError, TypeError):
        return value
    # {:,.0f} sẽ chèn dấu phẩy mỗi 3 chữ số, không có decimal
    s = "{:,.0f}".format(v)
    # thay dấu phẩy thành dấu chấm
    return s.replace(",", ".")


templates.env.filters["format_price"] = format_price

# ─── SESSION MIDDLEWARE ──────────────────────────────────────────────────────
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    session_cookie="session",
    max_age=14 * 24 * 60 * 60,
    same_site="lax",
    https_only=True,
)

app.include_router(account_router)

# ─── Danh sách cố định các Quận/Huyện Hà Nội ────────────────────────────────
district_map = {
    "dong_da": "Quận Đống Đa",
    "hai_ba_trung": "Quận Hai Bà Trưng",
    "cau_giay": "Quận Cầu Giấy",
    "tay_ho": "Quận Tây Hồ",
    "thanh_xuan": "Quận Thanh Xuân",
    "ha_dong": "Quận Hà Đông",
    "hoang_mai": "Quận Hoàng Mai",
    "bac_tu_liem": "Quận Bắc Từ Liêm",
    "nam_tu_liem": "Quận Nam Từ Liêm",
    "ba_dinh": "Quận Ba Đình",
    "hoan_kiem": "Quận Hoàn Kiếm",
    "long_bien": "Quận Long Biên",
}
# Chuyển sang list để duyệt theo thứ tự cố định
district_options: List[Tuple[str, str]] = list(district_map.items())

# ─── Danh sách cố định các LOẠI phòng ──────────────────────────────────────
type_map = {
    "phong_tro": "Phòng trọ",
    "nha_nguyen_can": "Nhà nguyên căn",
    "chung_cu": "Chung cư",
    "biet_thu": "Biệt thự",
}
type_options: List[Tuple[str, str]] = list(type_map.items())

# -------------- SMTP CẤU HÌNH --------------
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = "anhbqtq@gmail.com"
SMTP_PASSWORD = "sfutttrhnrklalui"


async def send_reset_email(request: Request, to_email: str, token: str):
    """
    Gửi thư đổi mật khẩu, link sẽ là:
      {base_url}/account/reset-password/{token}
    Có hiệu lực 1 giờ.
    """
    base = str(request.base_url).rstrip("/")
    path = request.url_for("reset_password_page", token=token)
    reset_link = f"{base}{path}"

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


@app.get("/", tags=["listing"])
async def root(
    request: Request,
    page: int = 1,
    district: str | None = None,
    price: str | None = None,
    type: str | None = None,
):
    page_size = 6

    # 1) Build filter
    filt: dict = {}
    if district:
        # Dùng regex để so khớp case‐insensitive
        filt["district"] = re.compile(
            f"^{re.escape(district)}$", re.IGNORECASE)
    if type:
        filt["type"] = type

    price_map = {
        "0-2000000": (0, 2_000_000),
        "2000000-5000000": (2_000_000, 5_000_000),
        "5000000-10000000": (5_000_000, 10_000_000),
        "10000000-": (10_000_000, None),
    }
    if price and price in price_map:
        low, high = price_map[price]
        cond: dict = {}
        if low is not None:
            cond["$gte"] = low
        if high is not None:
            cond["$lte"] = high
        filt["price"] = cond

    # 2) Count & pagination
    total = await db.listings.count_documents(filt)
    pages = ceil(total / page_size) if total else 1
    page = max(1, min(page, pages))

    # 3) Query this page
    cursor = db.listings.find(filt).sort("created_at", -1)
    docs = await cursor.skip((page - 1) * page_size).limit(page_size).to_list(page_size)

    # 4) Render
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "listings": docs,
            "page": page,
            "pages": pages,
            "district": district or "",
            "price": price or "",
            "type": type or "",
            "districts": district_options,
        }
    )


@app.get("/account/login", tags=["account"])
async def login_page(request: Request):
    return templates.TemplateResponse(
        "login.html",
        {"request": request}
    )


@app.get("/account/register", tags=["account"])
async def register_page(request: Request):
    return templates.TemplateResponse(
        "register.html",
        {"request": request}
    )


@app.get("/dang-tin", tags=["listing"])
async def create_listing_page(request: Request):
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/account/login", status_code=status.HTTP_303_SEE_OTHER)
    if not user.get("is_owner"):
        return templates.TemplateResponse(
            "access_denied.html",
            {"request": request, "message": "Chỉ chủ trọ mới có thể đăng tin."},
            status_code=status.HTTP_403_FORBIDDEN
        )
    return templates.TemplateResponse("dang_tin.html", {"request": request})


@app.post("/dang-tin", response_class=HTMLResponse, tags=["listing"])
async def create_listing(
    request: Request,
    title: str = Form(...),
    description: str = Form(...),
    price: float = Form(...),
    area: float = Form(...),
    district: str = Form(...),
    type: str = Form(...),
    phone: str = Form(...),
    slots: int = Form(...),
    images: list[UploadFile] = File([]),
    contract_images: list[UploadFile] = File([]),
):
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/account/login", status_code=status.HTTP_303_SEE_OTHER)
    if not user.get("is_owner"):
        return templates.TemplateResponse(
            "access_denied.html",
            {"request": request, "message": "Chỉ chủ trọ mới có thể đăng tin."},
            status_code=status.HTTP_403_FORBIDDEN
        )

    # 1) Lưu ảnh phòng
    upload_dir = "static/uploads"
    os.makedirs(upload_dir, exist_ok=True)
    new_paths: list[str] = []
    for img in images:
        if not img.filename:
            continue
        fn = f"{uuid.uuid4().hex}_{img.filename}"
        dst = os.path.join(upload_dir, fn)
        with open(dst, "wb") as f:
            f.write(await img.read())
        new_paths.append(f"/static/uploads/{fn}")

    # 2) Lưu ảnh hợp đồng
    contract_dir = "static/uploads/contracts"
    os.makedirs(contract_dir, exist_ok=True)
    contract_paths: list[str] = []
    for cimg in contract_images:
        if not cimg.filename:
            continue
        fn = f"{uuid.uuid4().hex}_{cimg.filename}"
        dst = os.path.join(contract_dir, fn)
        with open(dst, "wb") as f:
            f.write(await cimg.read())
        contract_paths.append(f"/static/uploads/contracts/{fn}")

    # 3) Tạo record mới
    new_listing = {
        "id": uuid.uuid4().hex,
        "title": title,
        "description": description,
        "price": price,
        "area": area,
        "district": district,
        "type": type,
        "phone": phone,
        "slots": slots,
        "owner": user["email"],
        "images": new_paths,
        "contract_images": contract_paths,
        "created_at": datetime.now(timezone.utc),
    }
    await db.listings.insert_one(new_listing)

    # 4) Redirect về chi tiết
    return RedirectResponse(f"/listing/{new_listing['id']}", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/listing/{listing_id}", response_class=HTMLResponse, tags=["listing"])
async def listing_detail(request: Request, listing_id: str):
    listing = await db.listings.find_one({"id": listing_id})
    if not listing:
        raise HTTPException(404, "Không tìm thấy bài đăng.")

    # Lấy URL quay lại
    referer = request.headers.get("referer", "")
    back_url = "/"
    if referer:
        parts = urlparse(referer)
        if parts.path == "/":
            back_url = parts.path + (f"?{parts.query}" if parts.query else "")

    # Kiểm tra nếu user đã có hợp đồng thuê listing này
    user = request.session.get("user")
    booking = None
    if user:
        booking = await db.bookings.find_one({
            "listing_id": listing_id,
            "tenant": user["email"]
        })

    return templates.TemplateResponse("listing_detail.html", {
        "request":     request,
        "listing":     listing,
        "district_map": district_map,
        "type_map":     type_map,
        "back_url":    back_url,
        "booking":     booking,
    })


@app.get("/listing/{listing_id}/edit", response_class=HTMLResponse, tags=["listing"])
async def edit_listing_page(request: Request, listing_id: str):
    # 1) Bắt login
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/account/login", status_code=status.HTTP_303_SEE_OTHER)

    # 2) Tìm listing
    listing = await db.listings.find_one({"id": listing_id})
    if not listing:
        raise HTTPException(status_code=404, detail="Không tìm thấy bài đăng.")

    # 3) Chỉ cho owner sửa
    if listing["owner"] != user["email"]:
        raise HTTPException(
            status_code=403, detail="Bạn không có quyền sửa tin này.")

    # 4) Render form
    return templates.TemplateResponse(
        "edit_listing.html",
        {
            "request": request,
            "listing": listing,
            "district_map": district_map,
            "type_map": type_map,
        },
    )


@app.post("/listing/{listing_id}/edit", response_class=HTMLResponse, tags=["listing"])
async def edit_listing(
    request: Request,
    listing_id: str,
    title: str = Form(...),
    description: str = Form(...),
    price: float = Form(...),
    area: float = Form(...),
    district: str = Form(...),
    type: str = Form(...),
    phone: str = Form(...),
    slots: int = Form(...),
    images: List[UploadFile] = File([]),
    contract_images: List[UploadFile] = File([]),
    remove_images: List[str] = Form([]),
    remove_contract_images: List[str] = Form([]),
):
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/account/login", status_code=status.HTTP_303_SEE_OTHER)

    listing = await db.listings.find_one({"id": listing_id})
    if not listing:
        raise HTTPException(status_code=404, detail="Không tìm thấy bài đăng.")
    if listing["owner"] != user["email"]:
        raise HTTPException(
            status_code=403, detail="Bạn không có quyền sửa tin này.")

    # --- 1) XÓA file ảnh phòng cũ trên ổ đĩa ---
    for img_url in remove_images:
        path_on_disk = img_url.lstrip("/")
        if os.path.exists(path_on_disk):
            os.remove(path_on_disk)

    # --- 2) XÓA file ảnh hợp đồng cũ trên ổ đĩa ---
    for url in remove_contract_images:
        path_on_disk = url.lstrip("/")
        if os.path.exists(path_on_disk):
            os.remove(path_on_disk)

    # --- 3) LƯU ảnh phòng mới ---
    upload_dir = "static/uploads"
    os.makedirs(upload_dir, exist_ok=True)
    new_paths: List[str] = []
    for img in images:
        if not img.filename:
            continue
        fn = f"{uuid.uuid4().hex}_{img.filename}"
        dst = os.path.join(upload_dir, fn)
        with open(dst, "wb") as f:
            f.write(await img.read())
        new_paths.append(f"/static/uploads/{fn}")

    # --- 4) LƯU ảnh hợp đồng mới ---
    contract_dir = "static/uploads/contracts"
    os.makedirs(contract_dir, exist_ok=True)
    new_contract_paths: List[str] = []
    for cimg in contract_images:
        if not cimg.filename:
            continue
        fn = f"{uuid.uuid4().hex}_{cimg.filename}"
        dst = os.path.join(contract_dir, fn)
        with open(dst, "wb") as f:
            f.write(await cimg.read())
        new_contract_paths.append(f"/static/uploads/contracts/{fn}")

    # --- 5) TÍNH mảng images CUỐI CÙNG ---
    existing = listing.get("images", [])
    remaining = [url for url in existing if url not in remove_images]
    final_images = remaining + new_paths

    # 4) CẬP NHẬT document
    update_data = {
        "title": title,
        "description": description,
        "price": price,
        "area": area,
        "district": district,
        "type": type,
        "phone": phone,
        "slots": slots,
        "images": final_images,
    }
    await db.listings.update_one({"id": listing_id}, {"$set": update_data})

    return RedirectResponse(f"/listing/{listing_id}", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/listing/{listing_id}/delete", response_class=HTMLResponse, tags=["listing"])
async def delete_listing(request: Request, listing_id: str):
    """
    Xóa hẳn một tin đăng (và file ảnh đi kèm), rồi trả về landing page.
    """
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/account/login", status_code=status.HTTP_303_SEE_OTHER)

    listing = await db.listings.find_one({"id": listing_id})
    if not listing:
        raise HTTPException(status_code=404, detail="Không tìm thấy bài đăng.")
    if listing["owner"] != user["email"]:
        raise HTTPException(
            status_code=403, detail="Bạn không có quyền xóa tin này.")

    # 1) Xóa file ảnh trên ổ đĩa
    for img_url in listing.get("images", []):
        path_on_disk = img_url.lstrip("/")  # "/static/…jpg" → "static/…jpg"
        if os.path.exists(path_on_disk):
            os.remove(path_on_disk)

    # 2) Xóa document khỏi DB
    await db.listings.delete_one({"id": listing_id})

    # 3) Chuyển hướng về trang chủ (hoặc trang tìm kiếm)
    return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/account/listings", response_class=HTMLResponse, tags=["account"])
async def my_listings(request: Request):
    # 1) Kiểm tra login
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/account/login", status_code=status.HTTP_303_SEE_OTHER)

    # 2) Query tất cả listings do user sở hữu, sắp xếp mới nhất lên trước
    cursor = db.listings.find({"owner": user["email"]}).sort("created_at", -1)
    listings = await cursor.to_list(length=100)  # giới hạn tối đa 100 items

    # 3) Render template
    return templates.TemplateResponse("my_listings.html", {
        "request": request,
        "listings": listings,
        "district_map": district_map,
        "type_map": type_map,
    })


@app.get(
    "/listing/{listing_id}/book",
    response_class=HTMLResponse,
    tags=["booking"],
    name="book_listing_page"     # ← đặt tên rõ ràng
)
async def book_listing_page(request: Request, listing_id: str):
    user = request.session.get("user")
    if not user:
        return RedirectResponse(request.url_for("login"), status_code=status.HTTP_303_SEE_OTHER)

    listing = await db.listings.find_one({"id": listing_id})
    if not listing:
        raise HTTPException(status_code=404, detail="Không tìm thấy tin đăng.")

    # Nếu trước đó user đã ký hợp đồng với listing này, chúng ta trả luôn booking đó
    booking = await db.bookings.find_one({
        "listing_id": listing_id,
        "tenant":     user["email"]
    })

    # today dưới dạng ISO yyyy-mm-dd để khớp input type="date"
    today = date.today().isoformat()

    return templates.TemplateResponse("book_listing.html", {
        "request": request,
        "listing": listing,
        "booking": booking,
        "today":   today
    })


@app.post(
    "/listing/{listing_id}/book",
    response_class=HTMLResponse,
    tags=["booking"],
    name="book_listing"
)
async def book_listing(
    request:       Request,
    listing_id:    str,
    # Với renew: chỉ cần end_date
    start_date:    Optional[date] = Form(None),
    end_date:      date = Form(...),
    # Với new booking...
    tenant_name:   Optional[str] = Form(None),
    tenant_phone:  Optional[str] = Form(None),
    tenant_id_card: Optional[str] = Form(None),
    signature:     Optional[UploadFile] = File(None),
):
    user = request.session.get("user")
    if not user:
        return RedirectResponse(request.url_for("login"), status_code=status.HTTP_303_SEE_OTHER)

    listing = await db.listings.find_one({"id": listing_id})
    if not listing:
        raise HTTPException(status_code=404, detail="Không tìm thấy tin đăng.")

    # --- nếu đã book rồi, giữ nguyên logic renew cũ ---
    booking = await db.bookings.find_one({
        "listing_id": listing_id,
        "tenant":     user["email"]
    })

    now = datetime.now(timezone.utc)
    if booking:
        # 1) Chuyển end_date → datetime UTC midnight
        from datetime import datetime as _dt, time as _time
        new_end_dt = _dt.combine(
            end_date, _time.min).replace(tzinfo=timezone.utc)

        # 2) Đảm bảo old_end có tzinfo
        old_end = booking["end_date"]
        if isinstance(old_end, datetime) and old_end.tzinfo is None:
            old_end = old_end.replace(tzinfo=timezone.utc)

        # 3) So sánh
        if new_end_dt <= old_end:
            raise HTTPException(
                400, "Ngày kết thúc mới phải sau ngày hiện tại.")

        # 4) Thay vì cập nhật ngay, ta tạo một notification đến chủ nhà
        await db.notifications.insert_one({
            "id":            uuid.uuid4().hex,
            "user":          listing["owner"],
            "type":          "renew_request",
            "booking_id":    booking["id"],
            "listing_id":    listing_id,
            "new_end_date":  new_end_dt,
            "status":        "pending",
            "created_at":    now,
            "read":          False,
            "message":       f"{user['email']} yêu cầu gia hạn đến {new_end_dt.date()}"
        })

        # 5) Redirect tenant về trang của họ với thông báo "đã gửi yêu cầu"
        return RedirectResponse(
            request.url_for("my_bookings"),
            status_code=status.HTTP_303_SEE_OTHER
        )

    # New booking: bắt buộc có tất cả các field tenant & chữ ký
    if not all([start_date, tenant_name, tenant_phone, tenant_id_card, signature]):
        raise HTTPException(
            status_code=400,
            detail="Vui lòng cung cấp đầy đủ ngày, thông tin cá nhân và chữ ký."
        )

    # convert date → datetime để MongoDB chấp nhận
    from datetime import datetime as _dt, time as _time
    start_dt = _dt.combine(start_date, _time.min).replace(tzinfo=timezone.utc)
    end_dt = _dt.combine(end_date,   _time.min).replace(tzinfo=timezone.utc)

    # lưu file chữ ký tenant
    sig_dir = "static/uploads/signatures"
    os.makedirs(sig_dir, exist_ok=True)
    fn = f"{uuid.uuid4().hex}_{signature.filename}"
    dst = os.path.join(sig_dir, fn)
    with open(dst, "wb") as f:
        f.write(await signature.read())
    sig_url = f"/static/uploads/signatures/{fn}"

    # tạo booking mới
    new_booking = {
        "id":               uuid.uuid4().hex,
        "listing_id":       listing_id,
        "tenant":           user["email"],
        "start_date":       start_dt,
        "end_date":         end_dt,
        "tenant_name":      tenant_name,
        "tenant_phone":     tenant_phone,
        "tenant_id_card":   tenant_id_card,
        "tenant_signature": sig_url,
        "status":           "pending",
        "created_at":       now,
        "updated_at":       now
    }
    await db.bookings.insert_one(new_booking)
    # notification cho owner
    await db.notifications.insert_one({
        "id":          uuid.uuid4().hex,
        "user":        listing["owner"],
        "type":        "booking_request",
        "booking_id":  new_booking["id"],
        "listing_id":  listing_id,
        "message":     f"{user['email']} yêu cầu ký hợp đồng phòng '{listing['title']}'",
        "status":      "pending",
        "created_at":  now,
        "read":        False
    })

    # redirect tenant về view hợp đồng
    return RedirectResponse(
        request.url_for("view_contract", booking_id=new_booking["id"]),
        status_code=status.HTTP_303_SEE_OTHER
    )


@app.get("/account/bookings/{booking_id}/sign", response_class=HTMLResponse, tags=["booking"])
async def sign_contract_page(request: Request, booking_id: str):
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

    # Chỉ owner hoặc tenant mới vào được
    if user["email"] not in (booking["tenant"], listing["owner"]):
        raise HTTPException(
            status_code=403, detail="Bạn không có quyền xem trang này.")

    return templates.TemplateResponse("sign_contract.html", {
        "request":  request,
        "user":     user,
        "listing":  listing,
        "booking":  booking,
        "district_map": district_map,
        "type_map":     type_map,
    })


@app.post("/account/bookings/{booking_id}/sign", response_class=HTMLResponse, tags=["booking"])
async def sign_contract(
    request: Request,
    booking_id: str,
    signature: UploadFile = File(...)
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

    email = user["email"]
    if email == listing["owner"]:
        role_field = "owner_signature"
    elif email == booking["tenant"]:
        role_field = "tenant_signature"
    else:
        raise HTTPException(
            status_code=403, detail="Bạn không có quyền ký hợp đồng này.")

    # Lưu file chữ ký
    sig_dir = "static/uploads/signatures"
    os.makedirs(sig_dir, exist_ok=True)
    fn = f"{uuid.uuid4().hex}_{signature.filename}"
    dst = os.path.join(sig_dir, fn)
    with open(dst, "wb") as f:
        f.write(await signature.read())
    sig_url = f"/static/uploads/signatures/{fn}"

    # Cập nhật booking với trường owner_signature hoặc tenant_signature
    await db.bookings.update_one(
        {"id": booking_id},
        {"$set": {role_field: sig_url}}
    )

    return RedirectResponse(
        f"/account/bookings/{booking_id}/sign",
        status_code=status.HTTP_303_SEE_OTHER
    )

# -------------- QUÊN MẬT KHẨU --------------


@app.get("/account/forgot-password", response_class=HTMLResponse, tags=["account"])
async def forgot_password_page(request: Request):
    return templates.TemplateResponse("forgot_password.html", {"request": request})


@app.post("/account/forgot-password", response_class=HTMLResponse, tags=["account"])
async def forgot_password(
    request: Request,
    email: str = Form(...)
):
    # 1) Kiểm tra user
    user = await db.users.find_one({"email": email})
    if user:
        # 2) Tạo token và lưu vào DB
        token = uuid.uuid4().hex
        expires = datetime.utcnow() + timedelta(hours=1)
        await db.password_resets.insert_one({
            "token":      token,
            "email":      email,
            "expires_at": expires
        })
        # 3) Gửi email
        await send_reset_email(request, email, token)

    # Không phân biệt tồn tại hay không, vẫn redirect về trang "đã gửi"
    return RedirectResponse("/account/forgot-password/sent", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/account/forgot-password/sent", response_class=HTMLResponse, tags=["account"])
async def forgot_password_sent(request: Request):
    return templates.TemplateResponse("forgot_password_sent.html", {"request": request})


# -------------- ĐẶT LẠI MẬT KHẨU --------------
@app.get("/account/reset-password/{token}", response_class=HTMLResponse, tags=["account"])
async def reset_password_page(request: Request, token: str):
    rec = await db.password_resets.find_one({"token": token})
    if not rec:
        return templates.TemplateResponse("reset_password_invalid.html", {"request": request})

    # --- CHỐNG LỖI naive vs aware ---
    expires = rec["expires_at"]
    if isinstance(expires, datetime) and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)

    if expires < datetime.now(timezone.utc):
        return templates.TemplateResponse("reset_password_invalid.html", {"request": request})

    return templates.TemplateResponse("reset_password.html", {
        "request": request,
        "token":   token
    })


@app.post("/account/reset-password/{token}", response_class=HTMLResponse, tags=["account"])
async def reset_password(
    request: Request,
    token:    str,
    password: str = Form(...),
    confirm:  str = Form(...)
):
    if password != confirm:
        return templates.TemplateResponse("reset_password.html", {
            "request": request,
            "token":   token,
            "error":   "Mật khẩu không khớp."
        })

    rec = await db.password_resets.find_one({"token": token})
    if not rec:
        return templates.TemplateResponse("reset_password_invalid.html", {"request": request})

    # --- CHỐNG LỖI naive vs aware ---
    expires = rec["expires_at"]
    if isinstance(expires, datetime) and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)

    if expires < datetime.now(timezone.utc):
        return templates.TemplateResponse("reset_password_invalid.html", {"request": request})

    # 4) Hash password rồi cập nhật vào collection 'account'
    hashed_pw = pwd_context.hash(password)
    await db.account.update_one(
        {"email": rec["email"]},
        {"$set": {"password": hashed_pw}}
    )
    # 5) Xóa token
    await db.password_resets.delete_one({"token": token})

    return RedirectResponse("/account/login?reset=success", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """
    Trả về favicon để khỏi bị 404 log lỗi.
    """
    # hoặc nếu dùng public/static:
    fp = os.path.join("public", "static", "favicon.ico")
    return FileResponse(fp)


# if __name__ == "__main__":
#     uvicorn.run(app, host="127.0.0.1", port=8000)
