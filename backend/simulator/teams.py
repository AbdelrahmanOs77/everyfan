"""Fictional clubs and players. All names are invented for EveryFan.

Anchor positions are in the TEAM frame: the team attacks towards x = 105 and,
facing that way, its right-hand touchline is y = 0.
"""

from __future__ import annotations

from dataclasses import dataclass

from shared.schemas import PlayerInfo, TeamInfo


NAMES_AR = {'Karim Hafez': 'كريم حافظ', 'Youssef Adel': 'يوسف عادل', 'Tarek Mansour': 'طارق منصور', 'Hany Fathy': 'هاني فتحي', 'Ziad Kamal': 'زياد كمال', 'Mostafa Ragab': 'مصطفى رجب', 'Ahmed Samir': 'أحمد سمير', 'Hassan Nour': 'حسن نور', 'Seif Wahba': 'سيف وهبة', 'Ramy Galal': 'رامي جلال', 'Adham Lotfy': 'أدهم لطفي', 'Nader Hamdy': 'نادر حمدي', 'Khaled Bakr': 'خالد بكر', 'Amr Fouad': 'عمرو فؤاد', 'Sherif Abdelaziz': 'شريف عبد العزيز', 'Mahmoud Reda': 'محمود رضا', 'Islam Zaki': 'إسلام زكي', 'Walid Shawky': 'وليد شوقي', 'Fares Helmy': 'فارس حلمي', 'Ali Darwish': 'علي درويش', 'Mazen Tawfik': 'مازن توفيق', 'Hamza Yassin': 'حمزة ياسين', 'Omar Kandil': 'عمر قنديل', 'Yassin Sabry': 'ياسين صبري', 'Adel Ghoneim': 'عادل غنيم', 'Sameh Labib': 'سامح لبيب', 'Moaz Barakat': 'معاذ بركات', 'Taha Ismail': 'طه إسماعيل'}


@dataclass(frozen=True)
class SquadSlot:
    shirt: int
    name: str
    short_name: str
    position: str
    anchor: tuple[float, float] | None  # None = substitute
    top_speed_kmh: float


NILE_FC = {
    "team_id": "nile_fc",
    "name": "Nile FC",
    "name_ar": "نادي النيل",
    "short_name": "NIL",
    "formation": "4-3-3",
    "primary_color": "#1F6FB2",
    "secondary_color": "#F2C14E",
    "prefix": "nil",
    "squad": [
        SquadSlot(1, "Karim Hafez", "Hafez", "GK", (5, 34), 27.0),
        SquadSlot(2, "Youssef Adel", "Adel", "RB", (31, 11), 33.8),
        SquadSlot(4, "Tarek Mansour", "Mansour", "CB", (25, 26), 31.2),
        SquadSlot(5, "Hany Fathy", "Fathy", "CB", (25, 42), 30.6),
        SquadSlot(3, "Ziad Kamal", "Kamal", "LB", (31, 57), 33.5),
        SquadSlot(6, "Mostafa Ragab", "Ragab", "DM", (42, 34), 30.4),
        SquadSlot(8, "Ahmed Samir", "Samir", "CM", (50, 22), 31.6),
        SquadSlot(10, "Hassan Nour", "Nour", "CM", (52, 46), 32.2),
        SquadSlot(7, "Seif Wahba", "Wahba", "RW", (72, 10), 34.6),
        SquadSlot(9, "Ramy Galal", "Galal", "ST", (78, 34), 33.0),
        SquadSlot(11, "Adham Lotfy", "Lotfy", "LW", (72, 58), 34.2),
        SquadSlot(14, "Nader Hamdy", "Hamdy", "CM", None, 31.0),
        SquadSlot(17, "Khaled Bakr", "Bakr", "RW", None, 34.0),
        SquadSlot(19, "Amr Fouad", "Fouad", "ST", None, 32.8),
    ],
}

DELTA_UTD = {
    "team_id": "delta_utd",
    "name": "Delta United",
    "name_ar": "دلتا يونايتد",
    "short_name": "DEL",
    "formation": "4-2-3-1",
    "primary_color": "#0E9F6E",
    "secondary_color": "#FFFFFF",
    "prefix": "del",
    "squad": [
        SquadSlot(1, "Sherif Abdelaziz", "Abdelaziz", "GK", (5, 34), 26.5),
        SquadSlot(2, "Mahmoud Reda", "Reda", "RB", (30, 11), 33.2),
        SquadSlot(4, "Islam Zaki", "Zaki", "CB", (24, 26), 30.8),
        SquadSlot(5, "Walid Shawky", "Shawky", "CB", (24, 42), 31.0),
        SquadSlot(3, "Fares Helmy", "Helmy", "LB", (30, 57), 33.0),
        SquadSlot(6, "Ali Darwish", "Darwish", "DM", (42, 27), 30.2),
        SquadSlot(8, "Mazen Tawfik", "Tawfik", "DM", (42, 41), 30.9),
        SquadSlot(7, "Hamza Yassin", "Yassin", "RW", (64, 12), 34.4),
        SquadSlot(10, "Omar Kandil", "Kandil", "AM", (64, 34), 31.8),
        SquadSlot(11, "Yassin Sabry", "Sabry", "LW", (64, 56), 34.0),
        SquadSlot(9, "Adel Ghoneim", "Ghoneim", "ST", (79, 34), 32.6),
        SquadSlot(14, "Sameh Labib", "Labib", "AM", None, 31.4),
        SquadSlot(16, "Moaz Barakat", "Barakat", "DM", None, 30.5),
        SquadSlot(18, "Taha Ismail", "Ismail", "ST", None, 33.4),
    ],
}

CLUBS = {c["team_id"]: c for c in (NILE_FC, DELTA_UTD)}


def player_id(club: dict, shirt: int) -> str:
    return f"{club['prefix']}_{shirt:02d}"


def build_team_info(team_id: str, side: str) -> TeamInfo:
    club = CLUBS[team_id]
    players = [
        PlayerInfo(
            player_id=player_id(club, s.shirt),
            team_id=team_id,
            name=s.name,
            short_name=s.short_name,
            name_ar=NAMES_AR.get(s.name),
            shirt_number=s.shirt,
            position=s.position,
            starter=s.anchor is not None,
        )
        for s in club["squad"]
    ]
    return TeamInfo(
        team_id=team_id,
        name=club["name"],
        short_name=club["short_name"],
        name_ar=club.get("name_ar"),
        side=side,
        formation=club["formation"],
        primary_color=club["primary_color"],
        secondary_color=club["secondary_color"],
        players=players,
    )
