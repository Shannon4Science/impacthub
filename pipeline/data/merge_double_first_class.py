"""Augment advisor_schools_211.json with the 32 schools that are in 2022 第二轮双一流
but were NOT in the original 211 list.

Authoritative reference: 中文 Wikipedia 双一流 (2022 第二轮 147 所) condition.
After this script runs, the seed contains ~146 schools, each flagged with
is_211 / is_985 / is_double_first_class.
"""

import json
from pathlib import Path

SEED = Path(__file__).resolve().parent.parent / "data" / "advisor_schools_211.json"

# 双一流 (2022) 中、原本不在 211 名单中的新增高校
DOUBLE_FIRST_CLASS_ADDITIONS = [
    # 北京 (8)
    {"name": "中央美术学院", "short_name": "央美", "english_name": "Central Academy of Fine Arts", "city": "北京", "province": "北京", "school_type": "艺术", "is_985": False, "is_double_first_class": True, "homepage_url": "https://www.cafa.edu.cn"},
    {"name": "中央戏剧学院", "short_name": "中戏", "english_name": "The Central Academy of Drama", "city": "北京", "province": "北京", "school_type": "艺术", "is_985": False, "is_double_first_class": True, "homepage_url": "https://www.zhongxi.cn"},
    {"name": "中国音乐学院", "short_name": "中音", "english_name": "China Conservatory of Music", "city": "北京", "province": "北京", "school_type": "艺术", "is_985": False, "is_double_first_class": True, "homepage_url": "https://www.ccmusic.edu.cn"},
    {"name": "首都师范大学", "short_name": "首师大", "english_name": "Capital Normal University", "city": "北京", "province": "北京", "school_type": "师范", "is_985": False, "is_double_first_class": True, "homepage_url": "https://www.cnu.edu.cn"},
    {"name": "中国科学院大学", "short_name": "国科大", "english_name": "University of Chinese Academy of Sciences", "city": "北京", "province": "北京", "school_type": "综合", "is_985": False, "is_double_first_class": True, "homepage_url": "https://www.ucas.edu.cn"},
    {"name": "北京协和医学院", "short_name": "协和", "english_name": "Peking Union Medical College", "city": "北京", "province": "北京", "school_type": "医药", "is_985": False, "is_double_first_class": True, "homepage_url": "https://www.pumc.edu.cn"},
    {"name": "外交学院", "short_name": "外院", "english_name": "China Foreign Affairs University", "city": "北京", "province": "北京", "school_type": "语言", "is_985": False, "is_double_first_class": True, "homepage_url": "https://www.cfau.edu.cn"},
    {"name": "中国人民公安大学", "short_name": "公大", "english_name": "People's Public Security University of China", "city": "北京", "province": "北京", "school_type": "政法", "is_985": False, "is_double_first_class": True, "homepage_url": "https://www.ppsuc.edu.cn"},

    # 天津 (2)
    {"name": "天津工业大学", "short_name": "天工大", "english_name": "Tiangong University", "city": "天津", "province": "天津", "school_type": "理工", "is_985": False, "is_double_first_class": True, "homepage_url": "https://www.tiangong.edu.cn"},
    {"name": "天津中医药大学", "short_name": "天中医", "english_name": "Tianjin University of Traditional Chinese Medicine", "city": "天津", "province": "天津", "school_type": "医药", "is_985": False, "is_double_first_class": True, "homepage_url": "https://www.tjutcm.edu.cn"},

    # 山西 (1)
    {"name": "山西大学", "short_name": "山大", "english_name": "Shanxi University", "city": "太原", "province": "山西", "school_type": "综合", "is_985": False, "is_double_first_class": True, "homepage_url": "https://www.sxu.edu.cn"},

    # 上海 (5)
    {"name": "上海海洋大学", "short_name": "上海海洋", "english_name": "Shanghai Ocean University", "city": "上海", "province": "上海", "school_type": "农林", "is_985": False, "is_double_first_class": True, "homepage_url": "https://www.shou.edu.cn"},
    {"name": "上海中医药大学", "short_name": "上中医", "english_name": "Shanghai University of Traditional Chinese Medicine", "city": "上海", "province": "上海", "school_type": "医药", "is_985": False, "is_double_first_class": True, "homepage_url": "https://www.shutcm.edu.cn"},
    {"name": "上海体育大学", "short_name": "上体", "english_name": "Shanghai University of Sport", "city": "上海", "province": "上海", "school_type": "体育", "is_985": False, "is_double_first_class": True, "homepage_url": "https://www.sus.edu.cn"},
    {"name": "上海音乐学院", "short_name": "上音", "english_name": "Shanghai Conservatory of Music", "city": "上海", "province": "上海", "school_type": "艺术", "is_985": False, "is_double_first_class": True, "homepage_url": "https://www.shcmusic.edu.cn"},
    {"name": "上海科技大学", "short_name": "上科大", "english_name": "ShanghaiTech University", "city": "上海", "province": "上海", "school_type": "理工", "is_985": False, "is_double_first_class": True, "homepage_url": "https://www.shanghaitech.edu.cn"},

    # 江苏 (5)
    {"name": "南京邮电大学", "short_name": "南邮", "english_name": "Nanjing University of Posts and Telecommunications", "city": "南京", "province": "江苏", "school_type": "理工", "is_985": False, "is_double_first_class": True, "homepage_url": "https://www.njupt.edu.cn"},
    {"name": "南京信息工程大学", "short_name": "南信大", "english_name": "Nanjing University of Information Science and Technology", "city": "南京", "province": "江苏", "school_type": "理工", "is_985": False, "is_double_first_class": True, "homepage_url": "https://www.nuist.edu.cn"},
    {"name": "南京林业大学", "short_name": "南林", "english_name": "Nanjing Forestry University", "city": "南京", "province": "江苏", "school_type": "农林", "is_985": False, "is_double_first_class": True, "homepage_url": "https://www.njfu.edu.cn"},
    {"name": "南京中医药大学", "short_name": "南中医", "english_name": "Nanjing University of Chinese Medicine", "city": "南京", "province": "江苏", "school_type": "医药", "is_985": False, "is_double_first_class": True, "homepage_url": "https://www.njucm.edu.cn"},
    {"name": "南京医科大学", "short_name": "南医大", "english_name": "Nanjing Medical University", "city": "南京", "province": "江苏", "school_type": "医药", "is_985": False, "is_double_first_class": True, "homepage_url": "https://www.njmu.edu.cn"},

    # 浙江 (2)
    {"name": "中国美术学院", "short_name": "国美", "english_name": "China Academy of Art", "city": "杭州", "province": "浙江", "school_type": "艺术", "is_985": False, "is_double_first_class": True, "homepage_url": "https://www.caa.edu.cn"},
    {"name": "宁波大学", "short_name": "宁大", "english_name": "Ningbo University", "city": "宁波", "province": "浙江", "school_type": "综合", "is_985": False, "is_double_first_class": True, "homepage_url": "https://www.nbu.edu.cn"},

    # 河南 (1)
    {"name": "河南大学", "short_name": "河大", "english_name": "Henan University", "city": "开封", "province": "河南", "school_type": "综合", "is_985": False, "is_double_first_class": True, "homepage_url": "https://www.henu.edu.cn"},

    # 湖南 (1)
    {"name": "湘潭大学", "short_name": "湘大", "english_name": "Xiangtan University", "city": "湘潭", "province": "湖南", "school_type": "综合", "is_985": False, "is_double_first_class": True, "homepage_url": "https://www.xtu.edu.cn"},

    # 广东 (4)
    {"name": "广州中医药大学", "short_name": "广中医", "english_name": "Guangzhou University of Chinese Medicine", "city": "广州", "province": "广东", "school_type": "医药", "is_985": False, "is_double_first_class": True, "homepage_url": "https://www.gzucm.edu.cn"},
    {"name": "华南农业大学", "short_name": "华农", "english_name": "South China Agricultural University", "city": "广州", "province": "广东", "school_type": "农林", "is_985": False, "is_double_first_class": True, "homepage_url": "https://www.scau.edu.cn"},
    {"name": "南方科技大学", "short_name": "南科大", "english_name": "Southern University of Science and Technology", "city": "深圳", "province": "广东", "school_type": "理工", "is_985": False, "is_double_first_class": True, "homepage_url": "https://www.sustech.edu.cn"},
    {"name": "广州医科大学", "short_name": "广医", "english_name": "Guangzhou Medical University", "city": "广州", "province": "广东", "school_type": "医药", "is_985": False, "is_double_first_class": True, "homepage_url": "https://www.gzhmu.edu.cn"},

    # 四川 (3)
    {"name": "西南石油大学", "short_name": "西南石大", "english_name": "Southwest Petroleum University", "city": "成都", "province": "四川", "school_type": "理工", "is_985": False, "is_double_first_class": True, "homepage_url": "https://www.swpu.edu.cn"},
    {"name": "成都理工大学", "short_name": "成理", "english_name": "Chengdu University of Technology", "city": "成都", "province": "四川", "school_type": "理工", "is_985": False, "is_double_first_class": True, "homepage_url": "https://www.cdut.edu.cn"},
    {"name": "成都中医药大学", "short_name": "成中医", "english_name": "Chengdu University of Traditional Chinese Medicine", "city": "成都", "province": "四川", "school_type": "医药", "is_985": False, "is_double_first_class": True, "homepage_url": "https://www.cdutcm.edu.cn"},
]


def main():
    payload = json.loads(SEED.read_text(encoding="utf-8"))
    schools = payload["schools"]
    existing_names = {s["name"] for s in schools}

    # Mark all existing as 211 (they are, since seed was hand-built from 211 list)
    for s in schools:
        s["is_211"] = True
        s["is_double_first_class"] = True

    added = 0
    for new in DOUBLE_FIRST_CLASS_ADDITIONS:
        if new["name"] in existing_names:
            continue
        new["is_211"] = False
        schools.append(new)
        added += 1

    payload["_meta"]["description"] = (
        "中国 211 + 双一流（2022 第二轮）建设高校种子列表。"
        "权威来源：教育部双一流名单（含全部原 211）。"
    )
    payload["_meta"]["count_total"] = len(schools)
    payload["_meta"]["count_985"] = sum(1 for s in schools if s.get("is_985"))
    payload["_meta"]["count_211"] = sum(1 for s in schools if s.get("is_211"))
    payload["_meta"]["count_double_first_class"] = sum(1 for s in schools if s.get("is_double_first_class"))
    payload["_meta"]["fields"] = ["name", "short_name", "english_name", "city", "province", "school_type", "is_985", "is_211", "is_double_first_class", "homepage_url"]

    SEED.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Added {added} double-first-class non-211 schools.")
    print(f"Total now: {len(schools)} (985={payload['_meta']['count_985']} / 211={payload['_meta']['count_211']} / 双一流={payload['_meta']['count_double_first_class']})")


if __name__ == "__main__":
    main()
