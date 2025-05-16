# Hướng dẫn chạy

1. Giải nén.
2. Vào Intelij Idea mở folder file code (QLPT).
3. Xóa folder "venv" đi.
4. Mở MongodbCompass và connect database.
5. Gõ vào terminal lần lượt các lệnh sau (chờ cho chạy xong mới gõ lệnh tiếp theo): 

`virtualenv venv`

`venv\Scripts\activate`

`pip install -r requirements.txt`

`fastapi dev main.py`

6. Nếu lệnh cuối báo lỗi không chạy thì chạy file main.py như bình thường.
