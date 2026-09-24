"""Nạp chặng mẫu cho Ghép cặp. Chạy lại nhiều lần không sinh trùng.

Mỗi lần chạy, bộ cặp của các chặng mẫu (theo `code` trong STAGES) bị xóa và
nạp lại toàn bộ từ đầu, để đổi thứ tự hay chèn/xóa từ trong STAGES không bao
giờ vỡ ràng buộc duy nhất; các chặng biên tập tay khác (code không nằm trong
STAGES) không bị đụng tới.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.gamification.models import MatchPairsStage, MatchPairsWord

STAGES = [
    {
        "code": "the-gioi-quanh-ta",
        "title_vi": "Thế giới quanh ta",
        "subtitle_vi": "Những từ quen thuộc mỗi ngày",
        "symbol": "✦",
        "level": "A1",
        "order": 0,
        "pairs": [
            ("Sun", "Mặt trời"),
            ("Moon", "Mặt trăng"),
            ("House", "Ngôi nhà"),
            ("Book", "Quyển sách"),
            ("Tree", "Cây xanh"),
            ("Flower", "Bông hoa"),
            ("Water", "Nước"),
            ("Cloud", "Đám mây"),
            ("Bird", "Con chim"),
            ("Cat", "Con mèo"),
            ("Dog", "Con chó"),
            ("Star", "Ngôi sao"),
        ],
    },
    {
        "code": "bua-an-sac-mau",
        "title_vi": "Bữa ăn sắc màu",
        "subtitle_vi": "Khám phá từ vựng về đồ ăn",
        "symbol": "◈",
        "level": "A1",
        "order": 1,
        "pairs": [
            ("Apple", "Quả táo"),
            ("Bread", "Bánh mì"),
            ("Rice", "Cơm"),
            ("Milk", "Sữa"),
            ("Egg", "Trứng"),
            ("Fish", "Cá"),
            ("Chicken", "Thịt gà"),
            ("Banana", "Quả chuối"),
            ("Carrot", "Cà rốt"),
            ("Cheese", "Phô mai"),
            ("Soup", "Súp"),
            ("Cake", "Bánh ngọt"),
        ],
    },
    {
        "code": "di-muon-noi",
        "title_vi": "Đi muôn nơi",
        "subtitle_vi": "Sẵn sàng cho chuyến đi mới",
        "symbol": "➜",
        "level": "A2",
        "order": 2,
        "pairs": [
            ("Airport", "Sân bay"),
            ("Ticket", "Vé"),
            ("Train", "Tàu hỏa"),
            ("Bus", "Xe buýt"),
            ("Hotel", "Khách sạn"),
            ("Beach", "Bãi biển"),
            ("Mountain", "Ngọn núi"),
            ("Map", "Bản đồ"),
            ("Passport", "Hộ chiếu"),
            ("Suitcase", "Va li"),
            ("Bridge", "Cây cầu"),
            ("Street", "Đường phố"),
        ],
    },
    {
        "code": "ngay-lam-viec",
        "title_vi": "Ngày làm việc",
        "subtitle_vi": "Từ vựng công sở thường gặp",
        "symbol": "◆",
        "level": "B1",
        "order": 3,
        "pairs": [
            ("Meeting", "Cuộc họp"),
            ("Deadline", "Hạn chót"),
            ("Report", "Báo cáo"),
            ("Manager", "Quản lý"),
            ("Salary", "Lương"),
            ("Contract", "Hợp đồng"),
            ("Customer", "Khách hàng"),
            ("Office", "Văn phòng"),
            ("Schedule", "Lịch làm việc"),
            ("Colleague", "Đồng nghiệp"),
            ("Project", "Dự án"),
            ("Interview", "Phỏng vấn"),
        ],
    },
]


class Command(BaseCommand):
    help = "Nạp chặng mẫu cho trò chơi Ghép cặp"

    @transaction.atomic
    def handle(self, *args, **options):
        for spec in STAGES:
            stage, _ = MatchPairsStage.objects.update_or_create(
                code=spec["code"],
                defaults={
                    "title_vi": spec["title_vi"],
                    "subtitle_vi": spec["subtitle_vi"],
                    "symbol": spec["symbol"],
                    "level": spec["level"],
                    "order": spec["order"],
                    "is_active": True,
                },
            )
            stage.pairs.all().delete()
            MatchPairsWord.objects.bulk_create(
                MatchPairsWord(stage=stage, order=index, english=english, vietnamese=vietnamese)
                for index, (english, vietnamese) in enumerate(spec["pairs"])
            )
        self.stdout.write(self.style.SUCCESS(f"Đã nạp {len(STAGES)} chặng Ghép cặp"))
