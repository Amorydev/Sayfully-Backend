"""Kịch bản đóng vai (C44). Mỗi mục: goals ↔ goal_hints cùng độ dài."""

SCENARIOS = [
    {
        "level": "A1",
        "order": 1,
        "scene": "cafe",
        "topic": "Ẩm thực",
        "title_vi": "Gọi món ở quán cà phê",
        "description_vi": "Chào, gọi đồ, hỏi giá",
        "ai_role_vi": "Nhân viên quán",
        "user_role_vi": "Khách hàng",
        "goals": [
            "Chào nhân viên",
            "Gọi một đồ uống",
            "Chọn size",
            "Hỏi giá",
            "Cảm ơn và tạm biệt",
        ],
        "goal_hints": [
            "Good morning!",
            "Can I have an iced latte, please?",
            "Large size, please.",
            "How much is it?",
            "Thank you, have a nice day!",
        ],
        "tip_vi": "Gợi ý: bạn có thể nói 'Can I have a…' hoặc 'How much is…'",
        "system_prompt": (
            "You are a friendly barista at a small coffee shop. The learner is a customer. "
            "Greet them, take their drink order, ask about size, tell the price (2-5 dollars) "
            "and say goodbye."
        ),
        "duration_min": 5,
        "is_premium": False,
    },
    {
        "level": "A1",
        "order": 2,
        "scene": "airport",
        "topic": "Du lịch",
        "title_vi": "Làm thủ tục bay",
        "description_vi": "Check-in, đổi chỗ ngồi",
        "ai_role_vi": "Nhân viên check-in",
        "user_role_vi": "Hành khách",
        "goals": [
            "Chào và đưa hộ chiếu",
            "Nói điểm đến",
            "Xin chỗ ngồi cạnh cửa sổ",
            "Hỏi cửa ra máy bay",
        ],
        "goal_hints": [
            "Hello, here is my passport.",
            "I'm flying to Bangkok.",
            "Can I have a window seat, please?",
            "Which gate is it?",
        ],
        "tip_vi": "Gợi ý: 'I'm flying to…', 'Can I have a window seat?'",
        "system_prompt": (
            "You are an airline check-in agent at an airport. The learner is a passenger. "
            "Ask for their passport, destination, seat preference, and tell them the gate number."
        ),
        "duration_min": 5,
        "is_premium": False,
    },
    {
        "level": "A1",
        "order": 3,
        "scene": "hotel",
        "topic": "Du lịch",
        "title_vi": "Check-in khách sạn",
        "description_vi": "Nhận phòng, hỏi Wi-Fi",
        "ai_role_vi": "Lễ tân",
        "user_role_vi": "Khách lưu trú",
        "goals": ["Nói đã đặt phòng", "Nói tên", "Hỏi giờ ăn sáng", "Hỏi mật khẩu Wi-Fi", "Cảm ơn"],
        "goal_hints": [
            "I have a reservation.",
            "My name is Minh.",
            "What time is breakfast?",
            "What is the Wi-Fi password?",
            "Thank you very much.",
        ],
        "tip_vi": "Gợi ý: 'I have a reservation', 'What time is breakfast?'",
        "system_prompt": (
            "You are a hotel receptionist. The learner is checking in. Confirm the reservation, "
            "ask for their name, tell breakfast time (7-10 am) and the Wi-Fi password if asked."
        ),
        "duration_min": 5,
        "is_premium": False,
    },
    {
        "level": "A1",
        "order": 4,
        "scene": "directions",
        "topic": "Du lịch",
        "title_vi": "Hỏi đường đi bộ",
        "description_vi": "Rẽ trái, bắt xe buýt",
        "ai_role_vi": "Người đi đường",
        "user_role_vi": "Du khách",
        "goals": ["Xin lỗi để hỏi", "Hỏi đường tới nhà ga", "Hỏi đi bộ bao xa", "Cảm ơn"],
        "goal_hints": [
            "Excuse me, can you help me?",
            "How do I get to the train station?",
            "How far is it?",
            "Thanks a lot!",
        ],
        "tip_vi": "Gợi ý: 'Excuse me, how do I get to…?'",
        "system_prompt": (
            "You are a friendly local on the street. The learner is a tourist asking for "
            "directions to the train station. Give simple directions (turn left, go straight, "
            "take bus number 5) and answer how far it is."
        ),
        "duration_min": 4,
        "is_premium": False,
    },
    {
        "level": "A2",
        "order": 1,
        "scene": "shopping",
        "topic": "Mua sắm",
        "title_vi": "Mua áo ở cửa hàng",
        "description_vi": "Hỏi size, thử đồ, mặc cả",
        "ai_role_vi": "Nhân viên bán hàng",
        "user_role_vi": "Khách mua",
        "goals": [
            "Nói đang tìm gì",
            "Hỏi size khác",
            "Xin thử đồ",
            "Hỏi giảm giá",
            "Quyết định mua",
        ],
        "goal_hints": [
            "I'm looking for a T-shirt.",
            "Do you have this in medium?",
            "Can I try it on?",
            "Is there a discount?",
            "I'll take it.",
        ],
        "tip_vi": "Gợi ý: 'Do you have this in…?', 'Can I try it on?'",
        "system_prompt": (
            "You are a shop assistant in a clothes store. The learner wants to buy a T-shirt. "
            "Help with sizes, the fitting room, prices and a small discount."
        ),
        "duration_min": 6,
        "is_premium": True,
    },
    {
        "level": "A2",
        "order": 2,
        "scene": "interview",
        "topic": "Công việc",
        "title_vi": "Phỏng vấn cơ bản",
        "description_vi": "Giới thiệu bản thân",
        "ai_role_vi": "Nhà tuyển dụng",
        "user_role_vi": "Ứng viên",
        "goals": [
            "Giới thiệu bản thân",
            "Nói công việc hiện tại",
            "Nêu một điểm mạnh",
            "Nói lý do ứng tuyển",
            "Hỏi về giờ làm việc",
            "Cảm ơn kết thúc",
        ],
        "goal_hints": [
            "My name is Lan and I'm 24 years old.",
            "I work as a sales assistant.",
            "I'm good at talking to people.",
            "I want this job because I like your products.",
            "What are the working hours?",
            "Thank you for your time.",
        ],
        "tip_vi": "Gợi ý: 'I'm good at…', 'I want this job because…'",
        "system_prompt": (
            "You are a friendly interviewer for a part-time job at a bookstore. Ask simple "
            "interview questions one at a time: introduction, current job, strengths, reason "
            "for applying. Answer questions about working hours."
        ),
        "duration_min": 7,
        "is_premium": True,
    },
    {
        "level": "B1",
        "order": 1,
        "scene": "doctor",
        "topic": "Sức khoẻ",
        "title_vi": "Khám bệnh thông thường",
        "description_vi": "Nêu triệu chứng cảm",
        "ai_role_vi": "Bác sĩ",
        "user_role_vi": "Bệnh nhân",
        "goals": [
            "Nói triệu chứng",
            "Nói bị từ khi nào",
            "Trả lời về dị ứng thuốc",
            "Hỏi cách dùng thuốc",
            "Hỏi khi nào tái khám",
        ],
        "goal_hints": [
            "I have a sore throat and a headache.",
            "It started two days ago.",
            "I'm not allergic to any medicine.",
            "How should I take this medicine?",
            "When should I come back?",
        ],
        "tip_vi": "Gợi ý: 'I have a…', 'It started… ago'",
        "system_prompt": (
            "You are a calm family doctor. The learner has a common cold. Ask about symptoms, "
            "when they started, allergies; explain the medicine and when to come back."
        ),
        "duration_min": 7,
        "is_premium": True,
    },
    {
        "level": "B1",
        "order": 2,
        "scene": "restaurant",
        "topic": "Ẩm thực",
        "title_vi": "Phàn nàn ở nhà hàng",
        "description_vi": "Món sai, xin đổi lịch sự",
        "ai_role_vi": "Quản lý nhà hàng",
        "user_role_vi": "Thực khách",
        "goals": [
            "Gọi nhân viên lịch sự",
            "Nêu vấn đề với món ăn",
            "Đề nghị đổi món",
            "Hỏi về hoá đơn",
            "Cảm ơn",
        ],
        "goal_hints": [
            "Excuse me, could I speak to the manager?",
            "I'm afraid this isn't what I ordered.",
            "Could you change it for the grilled fish?",
            "Will this be on the bill?",
            "Thanks for sorting it out.",
        ],
        "tip_vi": "Gợi ý: 'I'm afraid…', 'Could you…?'",
        "system_prompt": (
            "You are a polite restaurant manager. The learner received the wrong dish. Apologise, "
            "offer to replace it, and explain the bill."
        ),
        "duration_min": 7,
        "is_premium": True,
    },
]

TOPICS = [
    {"code": "travel", "emoji": "✈️", "title_vi": "Du lịch", "opening_en": "travel and holidays"},
    {
        "code": "work",
        "emoji": "💼",
        "title_vi": "Công việc",
        "opening_en": "work and daily routine",
    },
    {"code": "movies", "emoji": "🎬", "title_vi": "Phim & nhạc", "opening_en": "movies and music"},
    {"code": "food", "emoji": "🍜", "title_vi": "Ẩm thực", "opening_en": "food and cooking"},
    {
        "code": "school",
        "emoji": "🏫",
        "title_vi": "Trường học",
        "opening_en": "school and studying",
    },
    {"code": "sports", "emoji": "⚽", "title_vi": "Thể thao", "opening_en": "sports and exercise"},
    {"code": "pets", "emoji": "🐶", "title_vi": "Thú cưng", "opening_en": "pets and animals"},
    {
        "code": "hobbies",
        "emoji": "🎨",
        "title_vi": "Sở thích",
        "opening_en": "hobbies and free time",
    },
    {"code": "random", "emoji": "🎲", "title_vi": "Ngẫu nhiên", "opening_en": "anything you like"},
]
