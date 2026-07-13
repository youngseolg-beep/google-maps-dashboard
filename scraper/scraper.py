import os
import json
import time
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from playwright.sync_api import sync_playwright

DATA_PATH = "public/data/reviews.json"
STATUS_PATH = "public/data/crawl_status.json"

MAX_SCROLL_ROUNDS = 8
STOP_STALLED_ROUNDS = 2
MIN_REVIEWS_TARGET = 50

# Recent-only mode settings
# If a store already has saved reviews, the crawler checks only the latest area.
RECENT_ONLY_MAX_REVIEWS = 20
RECENT_ONLY_EXISTING_HIT_LIMIT = 3
RECENT_ONLY_MIN_CHECKED = 10
RECENT_ONLY_MAX_ROUNDS = 3

KST = ZoneInfo("Asia/Seoul")


def now_kst():
    return datetime.now(KST)


def estimate_review_date(relative_date, base_date=None):
    """Convert Google Maps relative time text to an estimated calendar date."""
    if base_date is None:
        base_date = now_kst().date()

    text = normalize_spaces(relative_date).lower()

    if not text or text in {"unknown", "recent"}:
        return base_date.strftime("%Y-%m-%d")

    # Words used when Google omits a number, e.g. "a day ago".
    text = re.sub(r"\b(?:a|an|one|een|satu)\b", "1", text)

    unit_patterns = [
        (r"(\d+)\s*(?:second|seconds|초|detik|seconde|seconden)", 0),
        (r"(\d+)\s*(?:minute|minutes|분|menit|minuut|minuten)", 0),
        (r"(\d+)\s*(?:hour|hours|시간|jam|uur)", 0),
        (r"(\d+)\s*(?:day|days|일|hari|dag|dagen)", 1),
        (r"(\d+)\s*(?:week|weeks|주|minggu|weken)", 7),
        (r"(\d+)\s*(?:month|months|개월|달|bulan|maand|maanden)", 30),
        (r"(\d+)\s*(?:year|years|년|tahun|jaar|jaren)", 365),
    ]

    for pattern, days_per_unit in unit_patterns:
        match = re.search(pattern, text, re.I)
        if match:
            amount = int(match.group(1))
            estimated = base_date - timedelta(days=amount * days_per_unit)
            return estimated.strftime("%Y-%m-%d")

    # Unrecognized relative values remain usable, but are marked as estimated today.
    return base_date.strftime("%Y-%m-%d")


# Replace the existing STORES section in scraper/scraper.py with this block.

STORES = [{'store_name': "Paik's Noodle Amsterdam",
  'sv': '강소영',
  'country': 'Netherlands',
  'city': 'Amsterdam',
  'url': "https://www.google.com/maps/place/Paik's+Noodle+Amsterdam/@52.3680585,4.8926513,17z/data=!4m18!1m9!3m8!1s0x47c60978a0095be1:0x5c955b954f65db98!2sPaik's+Noodle+Amsterdam!8m2!3d52.3679846!4d4.8925182!9m1!1b1!16s%2Fg%2F11ldxc_3q5!3m7!1s0x47c60978a0095be1:0x5c955b954f65db98!8m2!3d52.3679846!4d4.8925182!9m1!1b1!16s%2Fg%2F11ldxc_3q5?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D"},
 {'store_name': 'Bornga Wolter Monginsidi',
  'sv': '최성환',
  'country': 'Indonesia',
  'city': 'Jakarta',
  'url': 'https://www.google.com/maps/place/Bornga+Wolter+Monginsidi/@-6.2393833,106.8059313,17z/data=!4m8!3m7!1s0x2e69f16794afe1df:0x3fc1a290a209cef6!8m2!3d-6.2393833!4d106.8085062!9m1!1b1!16s%2Fg%2F1tfd9kxv?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D'},
 {'store_name': 'Saemaeul Thailand',
  'sv': '소도희',
  'country': 'Thailand',
  'city': 'Bangkok',
  'url': 'https://www.google.com/maps/place/%EC%83%88%EB%A7%88%EC%9D%84%EC%8B%9D%EB%8B%B9/@13.7305942,100.397158,11z/data=!4m12!1m2!2m1!1sTHAILAND+SAEMAEUL!3m8!1s0x30e29f07225ca6c7:0x5f5dc0b64eff0693!8m2!3d13.7475043!4d100.5395703!9m1!1b1!15sChFUSEFJTEFORCBTQUVNQUVVTFoTIhF0aGFpbGFuZCBzYWVtYWV1bJIBGmtvcmVhbl9iYXJiZWN1ZV9yZXN0YXVyYW504AEA!16s%2Fg%2F11rghd7fwy?entry=ttu&g_ep=EgoyMDI2MDUwNi4wIKXMDSoASAFQAw%3D%3D'},
 {'store_name': "Paik's Noodle Singapore",
  'sv': '이여명',
  'country': 'Singapore',
  'city': 'Singapore',
  'url': "https://www.google.com/maps/place/Paik's+Noodle/@1.2633826,103.8020909,14z/data=!3m1!5s0x31da19af25771877:0x64dca8531f0ccf88!4m12!1m2!2m1!1sSINGAPORE+PAIKS+NOODLE!3m8!1s0x31da191c85c285cf:0xcf1e805f3426a6f7!8m2!3d1.2948016!4d103.8591949!9m1!1b1!15sChZTSU5HQVBPUkUgUEFJS1MgTk9PRExFWhgiFnNpbmdhcG9yZSBwYWlrcyBub29kbGWSARFrb3JlYW5fcmVzdGF1cmFudJoBJENoZERTVWhOTUc5blMwVkpRMEZuU1VSV2FHRmxkWFZCUlJBQuABAPoBBAgYED0!16s%2Fg%2F11vkfsncfp?entry=ttu&g_ep=EgoyMDI2MDUwNi4wIKXMDSoASAFQAw%3D%3D"},
 {'store_name': 'Bornga Makati',
  'sv': '최성환',
  'country': 'Philippines',
  'city': 'Makati',
  'url': 'https://www.google.com/maps/place/Bornga+Korean+Restaurant+Makati+%EB%B3%B8%EA%B0%80/@14.5624132,121.015765,17z/data=!4m8!3m7!1s0x3397c90a27a8ee5b:0x2c1204cbe011bd1!8m2!3d14.5624132!4d121.015765!9m1!1b1!16s%2Fg%2F11bw4v3b72?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D'},
 {'store_name': 'Bornga Siam Discovery',
  'sv': '소도희',
  'country': 'Thailand',
  'city': 'Bangkok',
  'url': 'https://www.google.com/maps/place/%EB%B3%B8%EA%B0%80+%EC%8B%9C%EC%95%94+%EB%94%94%EC%8A%A4%EC%BB%A4%EB%B2%84%EB%A6%AC/@13.7466865,100.5313379,17z/data=!4m8!3m7!1s0x30e29f0073b66f73:0x3fc14d1c72f0febc!8m2!3d13.7466865!4d100.5313379!9m1!1b1!16s%2Fg%2F11vsbjczd0?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D'},
 {'store_name': 'Bornga Bangkok Sukhumvit',
  'sv': '소도희',
  'country': 'Thailand',
  'city': 'Bangkok',
  'url': 'https://www.google.com/maps/place/%EB%B3%B8%EA%B0%80/@13.7375583,100.5698488,17z/data=!4m8!3m7!1s0x30e29fc317e08e6d:0xe4b22a5a50cb2c17!8m2!3d13.7375583!4d100.5698488!9m1!1b1!16s%2Fg%2F11fm3pcdpl?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D'},
 {'store_name': 'Bornga Phnom Penh',
  'sv': '소도희',
  'country': 'Cambodia',
  'city': 'Phnom Penh',
  'url': 'https://www.google.com/maps/place/%EB%B3%B8%EA%B0%80%ED%94%84%EB%86%88%ED%8E%9C/@11.5494755,104.9261378,17z/data=!4m8!3m7!1s0x3109518f8b91ec6f:0xed20192d80d8c125!8m2!3d11.5494755!4d104.9261378!9m1!1b1!16s%2Fg%2F11j1btwtqv?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D'},
 {'store_name': 'Bornga Sihanoukville',
  'sv': '소도희',
  'country': 'Cambodia',
  'city': 'Sihanoukville',
  'url': 'https://www.google.com/maps/place/%EB%B3%B8%EA%B0%80+%EC%8B%9C%EC%95%84%EB%88%84%ED%81%AC%EB%B9%8C/@10.6067884,103.527292,17z/data=!4m8!3m7!1s0x3107e1a626a85bdf:0xdcb46fe355967767!8m2!3d10.6067884!4d103.527292!9m1!1b1!16s%2Fg%2F11v4m9jw49?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D'},
 {'store_name': 'Bornga Adelaide',
  'sv': '소도희',
  'country': 'Australia',
  'city': 'Adelaide',
  'url': 'https://www.google.com/maps/place/Bornga+Adelaide/@-34.9309705,138.5958975,17z/data=!4m8!3m7!1s0x6ab0cf9b51aad971:0xade1b9abaa21170b!8m2!3d-34.9309705!4d138.5958975!9m1!1b1!16s%2Fg%2F11n3kphdtn?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D'},
 {'store_name': 'Bornga Brisbane',
  'sv': '소도희',
  'country': 'Australia',
  'city': 'Brisbane',
  'url': 'https://www.google.com/maps/place/Bornga+Korean+BBQ+Restaurant/@-27.4702658,153.0266005,17z/data=!3m1!5s0x6b915a1b4d3b95d3:0x66949d52895dc60!4m8!3m7!1s0x6b915b6b5e2e7b5d:0x1b4b04be1acdcb93!8m2!3d-27.4702658!4d153.0266005!9m1!1b1!16s%2Fg%2F11lf7gyply?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D'},
 {'store_name': 'Bornga Melbourne',
  'sv': '소도희',
  'country': 'Australia',
  'city': 'Melbourne',
  'url': 'https://www.google.com/maps/place/Bornga/@-37.8119045,144.9669566,17z/data=!4m8!3m7!1s0x6ad642c986b8c52f:0xefcd7b02623b047f!8m2!3d-37.8119045!4d144.9669566!9m1!1b1!16s%2Fg%2F11fx7t_8fp?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D'},
 {'store_name': 'Bornga Sydney',
  'sv': '소도희',
  'country': 'Australia',
  'city': 'Sydney',
  'url': 'https://www.google.com/maps/place/Bornga+Sydney+Korean+BBQ+Restaurant/@-33.8788324,151.2035179,17z/data=!3m1!5s0x6b12ae24bd7acabd:0x9f39f3e7ed99ee03!4m8!3m7!1s0x6b12af19a5c21675:0xb010b70c5a5270a6!8m2!3d-33.8788324!4d151.2035179!9m1!1b1!16s%2Fg%2F11h5s3ksyb?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D'},
 {'store_name': 'Bornga Rhodes Central',
  'sv': '소도희',
  'country': 'Australia',
  'city': 'Sydney',
  'url': 'https://www.google.com/maps/place/Bornga+Korean+BBQ+Restaurant+Rhodes+Central/@-33.8307287,151.0863827,17z/data=!3m1!5s0x6b12a4e4435ad5d7:0x79549d356444dece!4m8!3m7!1s0x6b12a5a90419a3d7:0x3941a9448836f0f6!8m2!3d-33.8307287!4d151.0863827!9m1!1b1!16s%2Fg%2F11sv7bpx95?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D'},
  {'store_name': 'Bornga Dunnan Store',
  'sv': '이여명',
  'country': 'Taiwan',
  'city': 'Taipei',
  'url': 'https://www.google.com/maps/place/%E6%9C%AC%E5%AE%B6BORNGA%E9%9F%93%E5%BC%8F%E7%87%92%E8%82%89+%E6%95%A6%E5%8D%97%E5%BA%97/@25.044463,121.5499789,17z/data=!3m1!5s0x3442abdb36c3dd57:0x31070c64b44f2f5c!4m8!3m7!1s0x3442ab0779763169:0x584a72379db46e23!8m2!3d25.044463!4d121.5499789!9m1!1b1!16s%2Fg%2F11s9g6zd8p?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D'},
 {'store_name': 'Bornga Central Park 2',
  'sv': '최성환',
  'country': 'Indonesia',
  'city': 'Jakarta',
  'url': 'https://www.google.com/maps/place/Bornga+Central+Park+2/@-6.1748813,106.7899516,17z/data=!3m1!5s0x2e69f65efb632d83:0x3730183d2315c437!4m8!3m7!1s0x2e69f65f1bbc5cab:0x3e62fea29e1db986!8m2!3d-6.1748813!4d106.7899516!9m1!1b1!16s%2Fg%2F11c1q93190?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D'},
 {'store_name': 'Bornga Cikarang',
  'sv': '최성환',
  'country': 'Indonesia',
  'city': 'Cikarang',
  'url': 'https://www.google.com/maps/place/%EB%B3%B8%EA%B0%80+%EC%B0%8C%EA%B9%8C%EB%9E%91/@-6.33418,107.1522774,17z/data=!3m1!5s0x2e699bac77b9770f:0x8f14e52e3a27f030!4m8!3m7!1s0x2e699bab778ce14b:0x9f32e70584c5288a!8m2!3d-6.33418!4d107.1522774!9m1!1b1!16s%2Fg%2F11cjh_q_6c?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D'},
 {'store_name': 'Bornga Gading Serpong',
  'sv': '최성환',
  'country': 'Indonesia',
  'city': 'Tangerang',
  'url': 'https://www.google.com/maps/place/Bornga+Gading+Serpong/@-6.2341633,106.6327832,17z/data=!4m8!3m7!1s0x2e69fbf77b134bdf:0x75d5f9aaeafe9e05!8m2!3d-6.2341633!4d106.6327832!9m1!1b1!16s%2Fg%2F11btwt93pw?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D'},
 {'store_name': 'Bornga Lippo Mall Puri',
  'sv': '최성환',
  'country': 'Indonesia',
  'city': 'Jakarta',
  'url': 'https://www.google.com/maps/place/Bornga+Lippo+Mall+Puri/@-6.1892747,106.7387726,17z/data=!3m1!5s0x2e69f7abd51a4083:0x5b3122089bb23682!4m8!3m7!1s0x2e69f76e28d4ace1:0x18d504901c08b841!8m2!3d-6.1892747!4d106.7387726!9m1!1b1!16s%2Fg%2F11bwp1kh50?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D'},
 {'store_name': 'Bornga Kelapa Gading',
  'sv': '최성환',
  'country': 'Indonesia',
  'city': 'Jakarta',
  'url': 'https://www.google.com/maps/place/%EB%B3%B8%EA%B0%80+%EB%81%8C%EB%9D%BC%EB%B9%A0%EA%B0%80%EB%94%A9/@-6.1570837,106.9004827,17z/data=!4m8!3m7!1s0x2e69f539d8a53ef1:0xf51635b9cb589d6b!8m2!3d-6.1570837!4d106.9004827!9m1!1b1!16s%2Fg%2F11b6bwdplb?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D'},
 {'store_name': 'Bornga PIK',
  'sv': '최성환',
  'country': 'Indonesia',
  'city': 'Jakarta',
  'url': 'https://www.google.com/maps/place/Bornga+PIK/@-6.1110856,106.7384253,17z/data=!4m8!3m7!1s0x2e6a1d3bb110877f:0xcd16ef05e4bd591e!8m2!3d-6.1110856!4d106.7384253!9m1!1b1!16s%2Fg%2F11b6_pkjbg?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D'},
 {'store_name': 'Bornga Blok M',
  'sv': '최성환',
  'country': 'Indonesia',
  'city': 'Jakarta',
  'url': 'https://www.google.com/maps/place/Bornga+Blok+M/@-6.2424172,106.7959024,17z/data=!4m8!3m7!1s0x2e69f16b149a7791:0x3e3980cd63ec3aef!8m2!3d-6.2424172!4d106.7959024!9m1!1b1!16s%2Fg%2F1pycky006?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D'},
 {'store_name': 'Bornga Yogyakarta',
  'sv': '최성환',
  'country': 'Indonesia',
  'city': 'Yogyakarta',
  'url': 'https://www.google.com/maps/place/BORNGA/@-7.751018,110.3725242,17z/data=!4m8!3m7!1s0x2e7a58feccea425b:0x2da276a3c45e1c95!8m2!3d-7.751018!4d110.3725242!9m1!1b1!16s%2Fg%2F11f04f0kk9?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D'},
 {'store_name': 'Bornga Bandung',
  'sv': '최성환',
  'country': 'Indonesia',
  'city': 'Bandung',
  'url': 'https://www.google.com/maps/place/Bornga+Korean+Restaurant/@-6.9037419,107.5986924,17z/data=!4m8!3m7!1s0x2e68e641e9792bb7:0xb19cf52702a4fffe!8m2!3d-6.9037419!4d107.5986924!9m1!1b1!16s%2Fg%2F11cm3qdybs?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D'},
 {'store_name': 'Saemaeul Melbourne',
  'sv': '소도희',
  'country': 'Australia',
  'city': 'Melbourne',
  'url': 'https://www.google.com/maps/place/%EC%83%88%EB%A7%88%EC%9D%84%EC%8B%9D%EB%8B%B9+%EB%A9%9C%EB%B2%84%EB%A5%B8%EC%A0%90/@-37.8130562,144.956322,17z/data=!4m8!3m7!1s0x6ad65df435d2aa6d:0xe79cd4f63f32382a!8m2!3d-37.8130562!4d144.956322!9m1!1b1!16s%2Fg%2F11f8cl2v6v?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D'},
 {'store_name': 'Saemaeul Ulaanbaatar 1',
  'sv': '강소영',
  'country': 'Mongolia',
  'city': 'Ulaanbaatar',
  'url': 'https://www.google.com/maps/place/Saemaeul+Korean+Restaurant/@47.9047889,106.9359956,17z/data=!4m8!3m7!1s0x5d96930014bcf947:0xc3d0c5670c5a93a8!8m2!3d47.9047889!4d106.9359956!9m1!1b1!16s%2Fg%2F11ybzw1s2p?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D'},
 {'store_name': 'Saemaeul Ulaanbaatar 2',
  'sv': '강소영',
  'country': 'Mongolia',
  'city': 'Ulaanbaatar',
  'url': 'https://www.google.com/maps/place/%EC%83%88%EB%A7%88%EC%9D%84%EC%8B%9D%EB%8B%B9/@47.9150234,106.9061509,17z/data=!4m8!3m7!1s0x5d96930046343faf:0x451dbdf138d3e19d!8m2!3d47.9150234!4d106.9061509!9m1!1b1!16s%2Fg%2F11xf9zwz8h?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D'},
 {'store_name': 'Saemaeul Mongolia',
  'sv': '강소영',
  'country': 'Mongolia',
  'city': 'Ulaanbaatar',
  'url': 'https://www.google.com/maps/place/Saemaeul+Sikdang+Mongolia/@47.9028125,106.9123126,17z/data=!4m8!3m7!1s0x5d969326f6301cef:0x90899d73cbacfe34!8m2!3d47.9028125!4d106.9123126!9m1!1b1!16s%2Fg%2F11lcd8y4gc?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D'},
 {'store_name': 'Saemaeul Central Chaengwattana',
  'sv': '소도희',
  'country': 'Thailand',
  'city': 'Bangkok',
  'url': 'https://www.google.com/maps/place/Saemaeul+Express+-+Central+Chaengwattana/@13.9044323,100.5276065,17z/data=!4m8!3m7!1s0x30e28595b752584b:0xae89203a55d5765c!8m2!3d13.9044323!4d100.5276065!9m1!1b1!16s%2Fg%2F11n4hjdxbh?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D'},
 {'store_name': 'Saemaeul Central Bangna',
  'sv': '소도희',
  'country': 'Thailand',
  'city': 'Bangkok',
  'url': 'https://www.google.com/maps/place/Saemaeul+Express+-+Central+Bangna/@13.66878,100.6343276,17z/data=!4m8!3m7!1s0x311d439ff03ddd2d:0xe18e54c9b48ce2c7!8m2!3d13.66878!4d100.6343276!9m1!1b1!16s%2Fg%2F11yqnlx69p?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D'},
 {'store_name': 'Saemaeul Central Park',
  'sv': '소도희',
  'country': 'Thailand',
  'city': 'Bangkok',
  'url': 'https://www.google.com/maps/place/Saemaeul+Express+-+Central+Park/@13.7281858,100.5373122,17z/data=!4m8!3m7!1s0x30e29fd0cc02f8d5:0x6f62d838c7e1d4bf!8m2!3d13.7281858!4d100.5373122!9m1!1b1!16s%2Fg%2F11yhw3w3tz?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D'},
 {'store_name': 'Saemaeul Central Rama 3',
  'sv': '소도희',
  'country': 'Thailand',
  'city': 'Bangkok',
  'url': 'https://www.google.com/maps/place/Saemaeul+(%EC%83%88%EB%A7%88%EC%9D%84%EC%8B%9D%EB%8B%B9)+-+Central+Rama3/@13.6982689,100.5381326,17z/data=!4m8!3m7!1s0x30e29ff8d1c1657b:0xd10c7a679503c1e1!8m2!3d13.6982689!4d100.5381326!9m1!1b1!16s%2Fg%2F11x8h9zdlj?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D'},
 {'store_name': 'Saemaeul PIK',
  'sv': '최성환',
  'country': 'Indonesia',
  'city': 'Jakarta',
  'url': 'https://www.google.com/maps/place/Saemaeul+Original+Korean+BBQ+PIK/@-6.0945333,106.7421707,17z/data=!4m8!3m7!1s0x2e6a1d000b9e485f:0xea3548ca575366eb!8m2!3d-6.0945333!4d106.7421707!9m1!1b1!16s%2Fg%2F11xrzdl3zq?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D'},
 {'store_name': 'Saemaeul Gading Serpong',
  'sv': '최성환',
  'country': 'Indonesia',
  'city': 'Tangerang',
  'url': 'https://www.google.com/maps/place/Saemaeul+Korean+BBQ+Gading+Serpong/@-6.2479143,106.6255095,17z/data=!4m8!3m7!1s0x2e69fd222e232f99:0xb9ff91f30382f0a!8m2!3d-6.2479143!4d106.6255095!9m1!1b1!16s%2Fg%2F11y41875ly?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D'},
 {'store_name': 'Saemaeul SCBD',
  'sv': '최성환',
  'country': 'Indonesia',
  'city': 'Jakarta',
  'url': 'https://www.google.com/maps/place/Saemaeul+Original+Korean+BBQ+SCBD/@-6.2281222,106.8094817,17z/data=!4m8!3m7!1s0x2e69f113a37c673b:0xa52fc60fef035750!8m2!3d-6.2281222!4d106.8094817!9m1!1b1!16s%2Fg%2F11vf3rbl6v?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D'},
 {'store_name': 'Saemaeul One Bangkok',
  'sv': '소도희',
  'country': 'Thailand',
  'city': 'Bangkok',
  'url': 'https://www.google.com/maps/place/Saemaeul+(%EC%83%88%EB%A7%88%EC%9D%84%EC%8B%9D%EB%8B%B9)+-+One+Bangkok/@13.7257082,100.5474067,17z/data=!4m8!3m7!1s0x30e29f90649e43bf:0x58831b0686846b25!8m2!3d13.7257082!4d100.5474067!9m1!1b1!16s%2Fg%2F11whdgxd7g?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D'},
 {'store_name': 'Saemaeul Bangkok Siam',
  'sv': '소도희',
  'country': 'Thailand',
  'city': 'Bangkok',
  'url': 'https://www.google.com/maps/place/%EC%83%88%EB%A7%88%EC%9D%84%EC%8B%9D%EB%8B%B9/@13.7475043,100.5395703,17z/data=!4m8!3m7!1s0x30e29f07225ca6c7:0x5f5dc0b64eff0693!8m2!3d13.7475043!4d100.5395703!9m1!1b1!16s%2Fg%2F11rghd7fwy?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D'},
 {'store_name': 'Saemaeul Central Westville',
  'sv': '소도희',
  'country': 'Thailand',
  'city': 'Bangkok',
  'url': 'https://www.google.com/maps/place/Saemaeul+(%EC%83%88%EB%A7%88%EC%9D%84%EC%8B%9D%EB%8B%B9)+-+Central+Westville/@13.8054793,100.4485572,17z/data=!4m8!3m7!1s0x30e29be0fa190193:0xfa65447efed6d9ac!8m2!3d13.8054793!4d100.4485572!9m1!1b1!16s%2Fg%2F11vj3zh00m?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D'},
 {'store_name': 'Saemaeul Mega Bangna',
  'sv': '소도희',
  'country': 'Thailand',
  'city': 'Bangkok',
  'url': 'https://www.google.com/maps/place/Saemaeul+(%EC%83%88%EB%A7%88%EC%9D%84%EC%8B%9D%EB%8B%B9)+-+Mega+bangna/@13.6454854,100.680406,17z/data=!3m1!5s0x311d5e5b6aa2c6e3:0xd8022fa11255c100!4m8!3m7!1s0x311d5f426e39614d:0xe8efe06bf608d39e!8m2!3d13.6454854!4d100.680406!9m1!1b1!16s%2Fg%2F11q3rh2545?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D'},
 {'store_name': 'Saemaeul Central Eastville',
  'sv': '소도희',
  'country': 'Thailand',
  'city': 'Bangkok',
  'url': 'https://www.google.com/maps/place/Saemaeul+(%EC%83%88%EB%A7%88%EC%9D%84%EC%8B%9D%EB%8B%B9)+-+Central+Eastville/@13.8036867,100.6145723,17z/data=!4m8!3m7!1s0x30e29df2eeea54a1:0x484a32408c147d14!8m2!3d13.8036867!4d100.6145723!9m1!1b1!16s%2Fg%2F11s674rmb9?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D'},
 {'store_name': 'Saemaeul Bangkok Ratchada',
  'sv': '소도희',
  'country': 'Thailand',
  'city': 'Bangkok',
  'url': 'https://www.google.com/maps/place/%EC%83%88%EB%A7%88%EC%9D%84%EC%8B%9D%EB%8B%B9/@13.7592587,100.5661981,17z/data=!4m8!3m7!1s0x30e29f60356cfd43:0x73d25a54934ccdfa!8m2!3d13.7592587!4d100.5661981!9m1!1b1!16s%2Fg%2F11tk8pz_9b?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D'},
 {'store_name': 'Saemaeul Central Pinklao',
  'sv': '소도희',
  'country': 'Thailand',
  'city': 'Bangkok',
  'url': 'https://www.google.com/maps/place/Saemaeul+(%EC%83%88%EB%A7%88%EC%9D%84%EC%8B%9D%EB%8B%B9)+-+Central+Pinklao/@13.7782247,100.4765413,17z/data=!4m8!3m7!1s0x30e299c88f3fc6f5:0x1e485f6b26d2b61a!8m2!3d13.7782247!4d100.4765413!9m1!1b1!16s%2Fg%2F11s7zzspn9?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D'},
 {'store_name': 'Saemaeul Central Nakhonpathom',
  'sv': '소도희',
  'country': 'Thailand',
  'city': 'Nakhon Pathom',
  'url': 'https://www.google.com/maps/place/Saemaeul+(%EC%83%88%EB%A7%88%EC%9D%84%EC%8B%9D%EB%8B%B9)+-+Central+Nakhonpathom/@13.8055325,100.0484944,17z/data=!4m8!3m7!1s0x30e2e51896aa543f:0xd77569224a4517fc!8m2!3d13.8055325!4d100.0484944!9m1!1b1!16s%2Fg%2F11y340bwyq?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D'},
 {'store_name': 'Saemaeul Charn At The Avenue',
  'sv': '소도희',
  'country': 'Thailand',
  'city': 'Bangkok',
  'url': 'https://www.google.com/maps/place/Saemaeul+(%EC%83%88%EB%A7%88%EC%9D%84%EC%8B%9D%EB%8B%B9)+-+Charn+At+The+Avenue/@13.894772,100.5587663,17z/data=!4m8!3m7!1s0x30e283f7c8762d79:0xa69b3648cee5288c!8m2!3d13.894772!4d100.5587663!9m1!1b1!16s%2Fg%2F11vy3_hkl7?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D'},
 {'store_name': 'Saemaeul The Mall Lifestore Bangkae',
  'sv': '소도희',
  'country': 'Thailand',
  'city': 'Bangkok',
  'url': 'https://www.google.com/maps/place/Saemaeul+Express+(%EC%83%88%EB%A7%88%EC%9D%84%EC%8B%9D%EB%8B%B9+%EC%9D%B5%EC%8A%A4%ED%94%84%EB%A0%88%EC%8A%A4)+-+The+Mall+Lifestore+Bangkae/@13.7137767,100.4078205,17z/data=!3m1!5s0x30e297c6455fe509:0xdb78b1efb44b3c5!4m8!3m7!1s0x30e297498fdb5f3d:0xad0fd4b9a9f7365d!8m2!3d13.7137767!4d100.4078205!9m1!1b1!16s%2Fg%2F11l2z9s1dh?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D'},
 {'store_name': 'Saemaeul Central Rama 2',
  'sv': '소도희',
  'country': 'Thailand',
  'city': 'Bangkok',
  'url': 'https://www.google.com/maps/place/Saemaeul+(%EC%83%88%EB%A7%88%EC%9D%84%EC%8B%9D%EB%8B%B9)+-+Central+Rama2/@13.6634503,100.4375185,17z/data=!4m8!3m7!1s0x30e2bd831129bfb5:0x6fcaae99e2412fee!8m2!3d13.6634503!4d100.4375185!9m1!1b1!16s%2Fg%2F11kptstbsy?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D'},
 {'store_name': 'Saemaeul The Circle Ratchapruk',
  'sv': '소도희',
  'country': 'Thailand',
  'city': 'Bangkok',
  'url': 'https://www.google.com/maps/place/Saemaeul+(%EC%83%88%EB%A7%88%EC%9D%84%EC%8B%9D%EB%8B%B9)+-+The+Circle+Ratchapruk/@13.767396,100.4435102,17z/data=!4m8!3m7!1s0x30e29921f5950619:0xaac129ce5c48eb38!8m2!3d13.767396!4d100.4435102!9m1!1b1!16s%2Fg%2F11tww3x92x?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D'},
 {'store_name': 'Saemaeul Central Westgate',
  'sv': '소도희',
  'country': 'Thailand',
  'city': 'Nonthaburi',
  'url': 'https://www.google.com/maps/place/Saemaeul+(%EC%83%88%EB%A7%88%EC%9D%84%EC%8B%9D%EB%8B%B9)+-+Central+Westgate/@13.8773873,100.4118121,17z/data=!4m8!3m7!1s0x30e28f911ef213e9:0xdb840334848869f2!8m2!3d13.8773873!4d100.4118121!9m1!1b1!16s%2Fg%2F11l792zlty?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D'},
 {'store_name': "Paik's Noodle Waterway Point",
  'sv': '이여명',
  'country': 'Singapore',
  'city': 'Singapore',
  'url': "https://www.google.com/maps/place/Paik's+Noodle+(Waterway+Point)/@1.4068821,103.9019981,17z/data=!3m1!5s0x31da15e4b0ea6aa5:0x7d8ff3824b33be60!4m8!3m7!1s0x31da15001e25059b:0x7a4b097bf7f2871b!8m2!3d1.4068821!4d103.9019981!9m1!1b1!16s%2Fg%2F11y3xll4xl?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D"},
 {'store_name': "Paik's Noodle Taipei",
  'sv': '이여명',
  'country': 'Taiwan',
  'city': 'Taipei',
  'url': 'https://www.google.com/maps/place/Paik%E2%80%99s+Noodle/@25.0805316,121.5645698,17z/data=!4m8!3m7!1s0x3442ad000cd16415:0xbebca604d664b775!8m2!3d25.0805317!4d121.5694407!9m1!1b1!16s%2Fg%2F11x7n04ypz?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D'},
 {'store_name': "Paik's Noodle Sihanoukville",
  'sv': '소도희',
  'country': 'Cambodia',
  'city': 'Sihanoukville',
  'url': "https://www.google.com/maps/place/Paik's+Noodle+Sihanoukville+%ED%99%8D%EC%BD%A9%EB%B0%98%EC%A0%90+(%EC%8B%9C%ED%95%98%EB%88%84%ED%81%AC%EB%B9%8C)/@10.6030552,103.5308862,17z/data=!4m8!3m7!1s0x3107e10065008423:0x77702d6f926623c1!8m2!3d10.6030552!4d103.5308862!9m1!1b1!16s%2Fg%2F11x2hw733q?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D"},
{
  'store_name': "Paik's Noodle Phnom Penh",
  'sv': '소도희',
  'country': 'Cambodia',
  'city': 'Phnom Penh',
  'url': 'https://www.google.com/maps/place/Paik%E2%80%99s+Noodle+(%ED%99%8D%EC%BD%A9%EB%B0%98%EC%A0%90)/@11.5480722,104.9273662,17z/data=!4m8!3m7!1s0x3109518dad18a92b:0x11d03d197ce8c0a9!8m2!3d11.5480722!4d104.9273662!9m1!1b1!16s%2Fg%2F11t6_lznnc?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D'
},
{
  'store_name': "Paik's Noodle Melbourne CBD",
  'sv': '소도희',
  'country': 'Australia',
  'city': 'Melbourne',
  'url': "https://www.google.com/maps/place/Paik's+Noodle+CBD/@-37.8129948,144.9554991,17z/data=!3m1!5s0x6ad65d4962c360ad:0x1a7c865bc1a0483a!4m8!3m7!1s0x6ad65d6f9d6e42b3:0xa49b59731503e69a!8m2!3d-37.8129948!4d144.9554991!9m1!1b1!16s%2Fg%2F11pzs0dtg8?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D"
},
{
  'store_name': "Paik's Noodle Glen Waverley",
  'sv': '소도희',
  'country': 'Australia',
  'city': 'Melbourne',
  'url': "https://www.google.com/maps/place/Paik's+Noodle+Glen+Waverley/@-37.8790419,145.1647075,17z/data=!4m8!3m7!1s0x6ad63f2b5bc62569:0x12b0b8c774341f16!8m2!3d-37.8790419!4d145.1647075!9m1!1b1!16s%2Fg%2F11kbl425mz?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D"
},
{
  'store_name': "Paik's Bibim NTU",
  'sv': '이여명',
  'country': 'Singapore',
  'city': 'Singapore',
  'url': 'https://www.google.com/maps/place/Paik%27s+Bibim/@1.3471893,103.6781432,17z/data=!3m1!5s0x31da0f0acf7fffa7:0x1bd072911cb0b138!4m8!3m7!1s0x31da0fa07681b695:0x761051396477b994!8m2!3d1.3471893!4d103.6807181!9m1!1b1!16s%2Fg%2F11bwyxtrfh?entry=ttu&g_ep=EgoyMDI2MDUxMi4wIKXMDSoASAFQAw%3D%3D'
},
{
  'store_name': "Paik's Noodle Caulfield Village",
  'sv': '소도희',
  'country': 'Australia',
  'city': 'Melbourne',
  'url': "https://www.google.com/maps/place/Paik's+Noodle+Caulfield+Village/@-37.8764159,145.0380412,17z/data=!3m1!5s0x6ad66992975a9dc5:0xff22e88c2ead0e54!4m8!3m7!1s0x6ad66916a9138f41:0x11695e2dde119ad3!8m2!3d-37.8764159!4d145.0380412!9m1!1b1!16s%2Fg%2F11sjrdh7y5?entry=ttu&g_ep=EgoyMDI2MDUxMS4wIKXMDSoASAFQAw%3D%3D"
},
{
  'store_name': 'Paiks Noodle Mongolia',
  'sv': '강소영',
  'country': 'Mongolia',
  'city': 'Ulaanbaatar',
  'url': "https://www.google.com/maps/place/PAIK'S+NOODLE/@47.8941214,106.905143,17z/data=!4m8!3m7!1s0x5d96930012621e1d:0xcf4424862316ba86!8m2!3d47.8941178!4d106.9077179!9m1!1b1!16s%2Fg%2F11njgt20b_?entry=ttu&g_ep=EgoyMDI2MDUxNy4wIKXMDSoASAFQAw%3D%3D"
}
]

def build_url_candidates(url):
    base = url.strip()
    urls = [base]

    reviews_url = base.split("?")[0].rstrip("/") + "/reviews/"
    if reviews_url not in urls:
        urls.append(reviews_url)

    return urls


def normalize_spaces(text):
    return re.sub(r"\s+", " ", text or "").strip()


def safe_inner_text(locator, default=""):
    try:
        if locator.count() > 0:
            return locator.first.inner_text().strip()
    except:
        pass
    return default


def safe_attr(locator, attr, default=""):
    try:
        if locator.count() > 0:
            value = locator.first.get_attribute(attr)
            return value.strip() if value else default
    except:
        pass
    return default


def parse_rating(label):
    if not label:
        return 5

    match = re.search(r"([1-5])", label)
    return int(match.group(1)) if match else 5


def click_cookie_buttons(page):
    patterns = [
        r"Accept all",
        r"Accept",
        r"I agree",
        r"Agree",
        r"동의",
        r"모두 수락",
        r"Alles accepteren",
        r"Akkoord",
    ]

    for pattern in patterns:
        try:
            btn = page.get_by_role("button", name=re.compile(pattern, re.I)).first
            if btn.count() > 0:
                btn.click(timeout=3000)
                print("✅ 쿠키/동의 버튼 클릭 완료")
                page.wait_for_timeout(1500)
                return
        except:
            pass


def has_review_dom(page):
    selectors = [
        ".jftiEf",
        "div[role='article']",
        ".MyEned",
        ".wiI7pd",
        "div[role='feed']",
    ]

    for selector in selectors:
        try:
            if page.locator(selector).count() > 0:
                return True
        except:
            pass

    return False


def open_reviews_panel(page):
    print("🔘 리뷰 패널 열기 시도 중...")

    click_targets = [
        ("tab reviews", lambda: page.get_by_role("tab", name=re.compile(r"Reviews|리뷰|Recensies|Beoordelingen|Ulasan", re.I)).first),
        ("button reviews", lambda: page.get_by_role("button", name=re.compile(r"Reviews|리뷰|Recensies|Beoordelingen|Ulasan", re.I)).first),
        ("aria reviews", lambda: page.locator("button[aria-label*='Reviews'], button[aria-label*='reviews'], button[aria-label*='리뷰'], button[aria-label*='Recensies'], button[aria-label*='recensies'], button[aria-label*='Beoordelingen'], button[aria-label*='beoordelingen'], button[aria-label*='Ulasan'], button[aria-label*='ulasan']").first),
        ("jsaction moreReviews", lambda: page.locator("button[jsaction*='pane.rating.moreReviews']").first),
        ("text reviews", lambda: page.locator("text=/Reviews|리뷰|Recensies|Beoordelingen|Ulasan/i").first),
    ]

    for name, get_locator in click_targets:
        try:
            locator = get_locator()
            if locator.count() > 0:
                print(f"🔘 클릭 후보 발견: {name}")
                locator.click(timeout=5000, force=True)
                page.wait_for_timeout(6000)
                print(f"✅ 클릭 실행 완료: {name}")

                if has_review_dom(page):
                    print("✅ 클릭 후 리뷰 DOM 감지")
                    return True
        except Exception as e:
            print(f"⚠️ 클릭 실패: {name} / {e}")

    print("⚠️ 리뷰 패널 클릭으로 열기 실패")
    return False


def wait_for_reviews(page):
    selectors = [
        ".jftiEf",
        "div[role='article']",
        ".MyEned",
        ".wiI7pd",
        "div[role='feed']",
    ]

    for attempt in range(8):
        for selector in selectors:
            try:
                count = page.locator(selector).count()
                if count > 0:
                    print(f"✅ 리뷰 영역 감지: {selector} / {count}개")
                    return True
            except:
                pass

        print(f"⏳ 리뷰 패널 대기 중... {attempt + 1}/8")
        page.wait_for_timeout(3000)

    return False


def set_reviews_sort_to_newest(page):
    print("🆕 리뷰 정렬을 최신순으로 변경 시도 중...")

    sort_button_patterns = [
        r"Sort",
        r"정렬",
        r"Sorteer",
        r"Sorteren",
        r"Urutkan",
    ]

    newest_patterns = [
        r"Newest",
        r"Newest first",
        r"Most recent",
        r"Latest",
        r"최신",
        r"최신순",
        r"Nieuwste",
        r"Meest recente",
        r"Terbaru",
        r"Paling baru",
    ]

    try:
        sort_clicked = False

        for pattern in sort_button_patterns:
            try:
                btn = page.get_by_role("button", name=re.compile(pattern, re.I)).first

                if btn.count() > 0:
                    btn.click(timeout=4000, force=True)
                    page.wait_for_timeout(2000)
                    print("✅ 정렬 버튼 클릭 성공")
                    sort_clicked = True
                    break
            except:
                pass

        if not sort_clicked:
            print("⚠️ 정렬 버튼 발견 실패")
            return False

        newest_clicked = False

        for pattern in newest_patterns:
            try:
                option = page.get_by_role("menuitemradio", name=re.compile(pattern, re.I)).first

                if option.count() > 0:
                    option.click(timeout=4000, force=True)
                    page.wait_for_timeout(4000)
                    print("✅ 최신순 정렬 적용 성공")
                    newest_clicked = True
                    break
            except:
                pass

        if not newest_clicked:
            for pattern in newest_patterns:
                try:
                    option = page.get_by_text(re.compile(pattern, re.I)).first

                    if option.count() > 0:
                        option.click(timeout=4000, force=True)
                        page.wait_for_timeout(4000)
                        print("✅ 최신순 정렬 적용 성공")
                        newest_clicked = True
                        break
                except:
                    pass

        if not newest_clicked:
            print("⚠️ 최신순 옵션 클릭 실패")
            return False

        return True

    except Exception as e:
        print(f"⚠️ 최신순 정렬 설정 실패: {e}")
        return False


def click_more_buttons(page):
    patterns = [
        r"More",
        r"Read more",
        r"자세히 보기",
        r"더보기",
        r"Meer",
        r"Meer weergeven",
        r"Volledige review",
        r"Lainnya",
        r"Selengkapnya",
    ]

    for pattern in patterns:
        try:
            buttons = page.get_by_role("button", name=re.compile(pattern, re.I))
            count = min(buttons.count(), 20)

            for i in range(count):
                try:
                    buttons.nth(i).click(timeout=700, force=True)
                    page.wait_for_timeout(80)
                except:
                    pass
        except:
            pass


def click_original_review_buttons(page):
    patterns = [
        r"See original",
        r"Show original",
        r"Original",
        r"원문 보기",
        r"원본 보기",
        r"Bekijk origineel",
        r"Origineel bekijken",
        r"Oorspronkelijke",
        r"Lihat asli",
        r"Tampilkan asli",
    ]

    for pattern in patterns:
        try:
            buttons = page.get_by_role("button", name=re.compile(pattern, re.I))
            count = min(buttons.count(), 30)

            for i in range(count):
                try:
                    buttons.nth(i).click(timeout=700, force=True)
                    page.wait_for_timeout(80)
                except:
                    pass
        except:
            pass


def get_review_cards(page):
    selectors = [
        ".jftiEf",
        "div[role='article']",
        "div[data-review-id]",
    ]

    for selector in selectors:
        try:
            cards = page.locator(selector)
            if cards.count() > 0:
                return cards, selector
        except:
            pass

    return page.locator(".jftiEf"), ".jftiEf"


def get_review_text(card):
    for selector in [".wiI7pd", ".MyEned"]:
        text = normalize_spaces(safe_inner_text(card.locator(selector), ""))
        if text:
            return text

    return ""


def get_review_date(card):
    value = normalize_spaces(safe_inner_text(card.locator(".rsqaof"), ""))
    if value:
        return value

    try:
        all_text = card.inner_text(timeout=1000)

        patterns = [
            r"\b\d+\s+(?:second|minute|hour|day|week|month|year)s?\s+ago\b",
            r"\b\d+\s*(?:초|분|시간|일|주|개월|년)\s*전\b",
            r"\b\d+\s+(?:seconden|minuten|uur|dagen|weken|maanden|jaar)\s+geleden\b",
            r"\b\d+\s+(?:detik|menit|jam|hari|minggu|bulan|tahun)\s+yang\s+lalu\b",
            r"\b(?:a|an)\s+(?:day|week|month|year)\s+ago\b",
            r"\b(?:een)\s+(?:dag|week|maand|jaar)\s+geleden\b",
        ]

        for pattern in patterns:
            match = re.search(pattern, all_text, re.I)
            if match:
                return normalize_spaces(match.group(0))
    except:
        pass

    return "Unknown"


def get_review_author(card):
    author = normalize_spaces(safe_inner_text(card.locator(".d4r55"), ""))
    return author if author else "Anonymous"


def get_review_rating(card):
    rating_label = safe_attr(
        card.locator(
            "span[aria-label*='star'], span[aria-label*='Star'], span[aria-label*='stars'], span[aria-label*='Stars'], span[aria-label*='별'], span[aria-label*='ster'], span[aria-label*='Ster'], span[aria-label*='bintang'], span[aria-label*='Bintang']"
        ),
        "aria-label",
        "",
    )

    return parse_rating(rating_label)


def get_scroll_target(page):
    candidates = [
        "div[role='feed']",
        "div.m6QErb.DxyBCb.kA9KIf.dS8AEf",
        "div.m6QErb[tabindex='-1']",
    ]

    for selector in candidates:
        try:
            target = page.locator(selector).first
            if target.count() > 0:
                return target
        except:
            pass

    return None


def scroll_reviews(page):
    target = get_scroll_target(page)

    try:
        if target:
            target.hover(timeout=2000)
        else:
            page.mouse.move(500, 500)
    except:
        page.mouse.move(500, 500)

    page.mouse.wheel(0, 8000)
    page.wait_for_timeout(900)
    page.keyboard.press("PageDown")
    page.wait_for_timeout(1400)


def load_existing_reviews():
    if not os.path.exists(DATA_PATH):
        return []

    try:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            print(f"📦 기존 리뷰 로드: {len(data)}건")
            return data
    except Exception as e:
        print(f"⚠️ 기존 JSON 로드 실패. 새로 저장 진행: {e}")

    return []


def parse_collected_date(value):
    """Return a date from collected_at, falling back to today's KST date."""
    text = normalize_spaces(value)

    if not text:
        return now_kst().date()

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue

    return now_kst().date()


def migrate_existing_review_dates(existing_reviews):
    """Backfill review_date for legacy reviews using their first collected date."""
    migrated_count = 0
    fallback_count = 0

    for review in existing_reviews:
        if review.get("review_date"):
            continue

        relative_date = review.get("date", "Unknown")
        collected_at = review.get("collected_at", "")
        base_date = parse_collected_date(collected_at)

        review["review_date"] = estimate_review_date(relative_date, base_date)
        review["review_date_source"] = "estimated_from_collected_at"
        migrated_count += 1

        if not collected_at:
            fallback_count += 1

    return migrated_count, fallback_count


def save_migrated_existing_reviews(existing_reviews):
    """Persist legacy review_date migration before the crawl starts."""
    migrated_count, fallback_count = migrate_existing_review_dates(existing_reviews)

    if migrated_count == 0:
        print("✅ 기존 리뷰 날짜 마이그레이션 불필요: 모든 리뷰에 review_date 존재")
        return 0

    os.makedirs("public/data", exist_ok=True)

    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(existing_reviews, f, ensure_ascii=False, indent=4)

    print(f"🗓️ 기존 리뷰 날짜 마이그레이션 완료: {migrated_count}건")

    if fallback_count > 0:
        print(f"⚠️ collected_at 없음으로 오늘 날짜를 기준으로 보정: {fallback_count}건")

    return migrated_count


def make_review_key(review):
    store_name = normalize_spaces(review.get("store_name", "")).lower()
    author = normalize_spaces(review.get("author", "")).lower()
    text = normalize_spaces(review.get("text", "")).lower()

    text = re.sub(r"[^\w\s가-힣ㄱ-ㅎㅏ-ㅣ]", "", text)
    text = re.sub(r"\s+", " ", text).strip()

    if store_name and author and author not in ["anonymous", ""]:
        return f"{store_name}|{author}"

    if store_name and text:
        return f"{store_name}|{text[:180]}"

    return text


def merge_reviews(existing, new_reviews):
    merged = []
    seen = set()

    for review in new_reviews + existing:
        key = make_review_key(review)

        if not key or key in seen:
            continue

        seen.add(key)
        merged.append(review)

    return merged


def count_new_reviews(existing_reviews, new_reviews):
    existing_keys = set()

    for review in existing_reviews:
        key = make_review_key(review)
        if key:
            existing_keys.add(key)

    new_keys = set()

    for review in new_reviews:
        key = make_review_key(review)
        if key:
            new_keys.add(key)

    return len(new_keys - existing_keys)



def get_existing_keys_for_store(existing_reviews, store_name):
    target_store_name = normalize_spaces(store_name).lower()
    keys = set()

    for review in existing_reviews:
        review_store_name = normalize_spaces(review.get("store_name", "")).lower()

        if review_store_name != target_store_name:
            continue

        key = make_review_key(review)

        if key:
            keys.add(key)

    return keys


def extract_reviews(page, store, existing_keys=None):
    collected = []
    processed_keys = set()
    stalled_count = 0
    last_total = 0
    checked_count = 0
    existing_hit_count = 0

    existing_keys = existing_keys or set()
    recent_only_mode = len(existing_keys) > 0

    if recent_only_mode:
        print(f"⚡ 최근 리뷰 모드 적용: {store['store_name']} / 기존 리뷰 key {len(existing_keys)}개")
        max_rounds = min(MAX_SCROLL_ROUNDS, RECENT_ONLY_MAX_ROUNDS)
    else:
        print(f"📦 기존 리뷰 없음: {store['store_name']} / 초기 수집 모드")
        max_rounds = MAX_SCROLL_ROUNDS

    for round_no in range(max_rounds):
        click_more_buttons(page)
        click_original_review_buttons(page)

        cards, used_selector = get_review_cards(page)
        card_count = cards.count()
        found_this_turn = 0

        print(f"🔎 {round_no + 1}회차 리뷰 카드 감지 수: {card_count} / selector={used_selector}")

        for i in range(card_count):
            try:
                card = cards.nth(i)

                text = get_review_text(card)

                if not text or len(text) < 3:
                    continue

                noise_words = [
                    "Drag to change",
                    "Collapse side panel",
                    "Expand side panel",
                    "Keyboard shortcuts",
                    "Terms",
                    "Privacy",
                ]

                if any(word in text for word in noise_words):
                    continue

                relative_date = get_review_date(card)

                review = {
                    "store_name": store["store_name"],
                    "sv": store["sv"],
                    "country": store["country"],
                    "city": store["city"],
                    "author": get_review_author(card),
                    "rating": get_review_rating(card),
                    "text": text,
                    "date": relative_date,
                    "review_date": estimate_review_date(relative_date),
                    "review_date_source": "estimated",
                    "collected_at": now_kst().strftime("%Y-%m-%d"),
                }

                key = make_review_key(review)

                if not key:
                    continue

                if key in processed_keys:
                    continue

                processed_keys.add(key)
                checked_count += 1

                if recent_only_mode and key in existing_keys:
                    existing_hit_count += 1
                    print(
                        f"🟡 기존 리뷰 감지: {existing_hit_count}/{RECENT_ONLY_EXISTING_HIT_LIMIT} "
                        f"/ 확인 {checked_count}/{RECENT_ONLY_MIN_CHECKED}"
                    )

                    if (
                        checked_count >= RECENT_ONLY_MIN_CHECKED
                        and existing_hit_count >= RECENT_ONLY_EXISTING_HIT_LIMIT
                    ):
                        print("✅ 기존 리뷰 충분히 감지. 이 매장 최근 리뷰 확인 종료.")
                        return collected

                    continue

                collected.append(review)
                found_this_turn += 1

                if recent_only_mode and len(collected) >= RECENT_ONLY_MAX_REVIEWS:
                    print(f"✅ 최근 리뷰 신규 후보 상한 도달: {RECENT_ONLY_MAX_REVIEWS}건")
                    return collected

            except Exception as e:
                print(f"⚠️ 개별 리뷰 추출 실패: {e}")
                continue

        if found_this_turn > 0:
            print(f"🔄 {round_no + 1}회차: 신규 후보 {found_this_turn}건 / 이번 매장 누적 {len(collected)}건")
        else:
            print(f"⚠️ {round_no + 1}회차: 신규 후보 없음 / 이번 매장 누적 {len(collected)}건")

        if not recent_only_mode and len(collected) >= MIN_REVIEWS_TARGET:
            print(f"✅ 목표 수집량 도달: {len(collected)}건")
            break

        if len(collected) == last_total:
            stalled_count += 1
        else:
            stalled_count = 0
            last_total = len(collected)

        if stalled_count >= STOP_STALLED_ROUNDS and len(collected) > 0:
            print("✅ 추가 로딩 정체 감지. 빠른 수집 종료.")
            break

        if recent_only_mode and round_no + 1 >= max_rounds:
            print("✅ 최근 리뷰 모드 확인 라운드 완료. 다음 매장으로 이동.")
            break

        scroll_reviews(page)

    return collected


def scrape_store(page, store, existing_reviews=None):
    print(f"\n==============================")
    print(f"🏪 매장 크롤링 시작: {store['store_name']}")
    print(f"👤 담당 SV: {store['sv']} / 국가: {store['country']}")
    print(f"==============================")

    url_candidates = build_url_candidates(store["url"])

    for idx, target_url in enumerate(url_candidates):
        print(f"🌐 URL 후보 {idx + 1}/{len(url_candidates)} 진입 시도: {target_url}")

        try:
            page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
        except Exception as e:
            print(f"⚠️ 페이지 로딩 중 오류. 계속 진행: {e}")

        page.wait_for_timeout(5000)
        click_cookie_buttons(page)

        print("⏳ Google Maps 기본 페이지 렌더링 대기 중...")
        page.wait_for_timeout(7000)

        if not has_review_dom(page):
            open_reviews_panel(page)

        print("⏳ Google Maps 리뷰 패널 렌더링 대기 중...")
        page.wait_for_timeout(4000)

        if wait_for_reviews(page):
            set_reviews_sort_to_newest(page)
            existing_keys = get_existing_keys_for_store(existing_reviews or [], store["store_name"])
            reviews = extract_reviews(page, store, existing_keys)

            if reviews or existing_keys:
                if reviews:
                    print(f"✅ 매장 수집 성공: {store['store_name']} / 신규 후보 {len(reviews)}건")
                else:
                    print(f"✅ 매장 확인 완료: {store['store_name']} / 신규 리뷰 없음")

                return {
                    "ok": True,
                    "store_name": store["store_name"],
                    "sv": store["sv"],
                    "country": store["country"],
                    "collected_count": len(reviews),
                    "error": "",
                    "crawled_at": now_kst().strftime("%Y-%m-%d %H:%M:%S"),
                    "reviews": reviews,
                }

        print(f"⚠️ URL 후보 {idx + 1}에서 리뷰 DOM 감지 실패 또는 리뷰 없음")

    print(f"❌ 매장 수집 실패: {store['store_name']}")
    return {
        "ok": False,
        "store_name": store["store_name"],
        "sv": store["sv"],
        "country": store["country"],
        "collected_count": 0,
        "error": "리뷰 DOM 감지 실패 또는 리뷰 없음",
        "crawled_at": now_kst().strftime("%Y-%m-%d %H:%M:%S"),
        "reviews": [],
    }


def save_reviews(new_reviews):
    os.makedirs("public/data", exist_ok=True)

    existing_reviews = load_existing_reviews()
    merged_reviews = merge_reviews(existing_reviews, new_reviews)

    new_added_count = count_new_reviews(existing_reviews, new_reviews)
    duplicate_cleaned_count = len(existing_reviews) + len(new_reviews) - len(merged_reviews)

    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(merged_reviews, f, ensure_ascii=False, indent=4)

    print(f"\n✨ 저장 완료: {DATA_PATH}")
    print(f"   - 기존 리뷰: {len(existing_reviews)}건")
    print(f"   - 이번 수집: {len(new_reviews)}건")
    print(f"   - 신규 추가: {new_added_count}건")
    print(f"   - 중복 정리: {duplicate_cleaned_count}건")
    print(f"   - 최종 누적: {len(merged_reviews)}건")


def save_crawl_status(results):
    os.makedirs("public/data", exist_ok=True)

    status = {
        "last_crawled_at": now_kst().strftime("%Y-%m-%d %H:%M:%S"),
        "total_stores": len(results),
        "success_count": len([r for r in results if r["ok"]]),
        "failed_count": len([r for r in results if not r["ok"]]),
        "failed_stores": [
            {
                "store_name": r["store_name"],
                "sv": r["sv"],
                "country": r["country"],
                "error": r["error"],
            }
            for r in results
            if not r["ok"]
        ],
        "stores": [
            {
                "store_name": r["store_name"],
                "sv": r["sv"],
                "country": r["country"],
                "ok": r["ok"],
                "collected_count": r["collected_count"],
                "error": r["error"],
                "crawled_at": r["crawled_at"],
            }
            for r in results
        ],
    }

    with open(STATUS_PATH, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=4)

    print(f"🧾 크롤링 상태 저장 완료: {STATUS_PATH}")
    print(f"   - 성공: {status['success_count']}/{status['total_stores']}")
    print(f"   - 실패: {status['failed_count']}건")


def scrape():
    all_new_reviews = []
    crawl_results = []
    existing_reviews = load_existing_reviews()
    save_migrated_existing_reviews(existing_reviews)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--lang=en-US,en",
            ],
        )

        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            locale="en-US",
            timezone_id="Asia/Seoul",
            viewport={"width": 1440, "height": 1000},
        )

        context.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            """
        )

        page = context.new_page()
        page.set_default_timeout(45000)

        try:
            for store in STORES:
                result = scrape_store(page, store, existing_reviews)
                crawl_results.append(result)
                all_new_reviews.extend(result["reviews"])

                page.wait_for_timeout(3000)

            if all_new_reviews:
                save_reviews(all_new_reviews)
            else:
                print("❌ 이번 실행에서 수집된 리뷰가 없습니다.")

            save_crawl_status(crawl_results)

        except Exception as e:
            print(f"🔥 치명적 오류: {e}")

        finally:
            browser.close()


if __name__ == "__main__":
    scrape()
