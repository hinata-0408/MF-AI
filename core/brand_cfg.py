BRAND_CONFIG = {
    "panasonic": {
        "display": "Panasonic",
        "order": 1,
        "domains": ["panasonic.jp", "dl-asset.panasonic.com"],
        "golden_paths": ["/support/manual/"],
    },
    "sony": {
        "display": "SONY",
        "order": 2,
        "domains": ["sony.jp", "cs.sony.jp", "helpguide.sony.net"],
        "golden_paths": ["/servicearea/impdf/", "helpguide.sony.net"],
        "shortcut_logic": {
            "type": "find_and_construct",
            "landing_page_hint": "/ServiceArea/impdf/manual/",
            "id_regex": r"/(\d{8})K-",
            "pdf_template": "https://www.sony.jp/ServiceArea/impdf/pdf/{}M-JP.pdf"
        }
    },
    "sharp": {
        "display": "SHARP",
        "order": 3,
        "domains": ["jp.sharp", "cs.sharp.co.jp"],
        "golden_paths": ["/support/manual/", "/support/aquos/doc/"],
        "filename_hints": ["_mn.pdf"],
    },
    "regza": {
        "display": "REGZA",
        "order": 4,
        "domains": ["cs.regza.com"],
        "golden_paths": ["/document/manual/"],
    },
    "toshiba": {
        "display": "東芝",
        "order": 5,
        "domains": ["toshiba-living.jp", "toshiba-lifestyle.com"],
        "shortcut_logic": {
            "type": "find_and_construct_from_html",
            "id_extraction_regex": r"rev\.php\?no=(\d+)",
            "pdf_template": "https://www.toshiba-living.jp/manual.pdf?no={}"
        }
    },
    "hitachi": {
        "display": "日立",
        "order": 6,
        "domains": ["kadenfan.hitachi.co.jp"],
        "golden_paths": ["/support/raj/item/docs/", "/support/rei/item/docs/", "/support/wash/item/docs/"],
        "filename_hints": ["_tori"],
    },
    "mitsubishi": {
        "display": "三菱",
        "order": 7,
        "domains": ["mitsubishielectric.co.jp", "dl.mitsubishielectric.co.jp"],
    },
    "dyson": {
        "display": "ダイソン",
        "order": 8,
        "domains": ["dyson.co.jp"],
        "golden_paths": ["/maintenance/user-guides/"],
        "filename_hints": ["manual"],
    },
    "irisohyama": {
        "display": "アイリスオオヤマ",
        "order": 10,
        "domains": ["irisohyama.co.jp"],
        "golden_paths": ["/products/manual/pdf/"],
    },
    "balmuda": {
        "display": "バルミューダ",
        "order": 11,
        "domains": ["balmuda.com"],
        "golden_paths": ["/downloads/pdf/"],
    },
    "zojirushi": {
        "display": "象印",
        "order": 12,
        "domains": ["zojirushi.co.jp"],
        "golden_paths": ["/toiawase/TR_PDF/"],
        "url_template": "https://www.zojirushi.co.jp/toiawase/TR_PDF/{model_code}.pdf"
    },
    "tiger": {
        "display": "タイガー",
        "order": 13,
        "domains": ["tiger-forest.com", "tiger.jp"],
        "golden_paths": ["/manual-box/", "/product/uploads/pdf/"],
    },
    "daikin": {
        "display": "ダイキン",
        "order": 14,
        "domains": ["daikin.co.jp", "dtnet.daikin.co.jp"],
        "golden_paths": ["/torisetu/"],
    },
}
