import json
import asyncio
import os

from nonebot import logger

from ..storage import PRICONNE_DATA_DIR, STATIC_FONT_DIR, STATIC_IMG_DIR

DATA_PATH = str(PRICONNE_DATA_DIR)
RES_PATH = str(STATIC_IMG_DIR)
FONT_PATH = str(STATIC_FONT_DIR)

stage_dict = {
    "B":1,
    "C":2,
    "D":3,
    0:"B",
    1:"B",
    2:"C",
    3:"D"
}

rate_score = {
    "B":[1.6,1.6,1.8,1.9,2],
    "C":[2,2,2.1,2.1,2.2],
    "D":[4.5,4.5,4.7,4.8,5]
}

stage = [0, 6, 22]

boss_max = [
    [
        6000000,
        8000000,
        10000000,
        12000000,
        15000000
    ],
    [
        6000000,
        8000000,
        10000000,
        12000000,
        15000000
    ],
    [
        12000000,
        14000000,
        17000000,
        19000000,
        22000000
    ],
    [
        19000000,
        20000000,
        23000000,
        25000000,
        27000000
    ],
    [
        85000000,
        90000000,
        95000000,
        100000000,
        110000000
    ]
]

def lap2stage(lap_num):
    if lap_num in range(7):
        stage = 'B'
    elif lap_num in range(7,23):
        stage = 'C'
    else:
        stage = 'D'
    return stage

async def load_config(path):
    try:
        with open(path, encoding='utf8') as f:
            config = json.load(f)
            return config
    except:
        return []

async def write_config(path, config):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False)


def _redact_error_value(value):
    if isinstance(value, dict):
        sensitive_keys = {"access_key", "password", "pwd", "sid", "token"}
        return {
            key: "***" if str(key).lower() in sensitive_keys else _redact_error_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_error_value(item) for item in value]
    return value


async def check_client(client):
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            load_index = await client.callapi('/load/index', {'carrier': 'OPPO'})
            if not isinstance(load_index, dict):
                logger.warning(
                    "priconne check_client invalid /load/index response: "
                    f"attempt={attempt}/{max_attempts}, type={type(load_index).__name__}, "
                    f"value={_redact_error_value(load_index)!r}"
                )
                continue
            if "server_error" not in load_index:
                return True
            error = load_index.get("server_error") or {}
            status = error.get('status')
            logger.warning(
                "priconne check_client /load/index server_error: "
                f"attempt={attempt}/{max_attempts}, status={status}, "
                f"title={error.get('title', '')!r}, message={error.get('message', '')!r}, "
                f"error={_redact_error_value(error)!r}"
            )
            if status in {0, 1, 2, 3, 999999}:
                return False
            if status in {4, 5, 6, 7, 8}:
                rotate_server = getattr(client, "rotate_server", None)
                if callable(rotate_server):
                    rotate_server()
        except Exception as e:
            logger.opt(exception=e).warning(
                "priconne check_client /load/index exception: "
                f"attempt={attempt}/{max_attempts}, error={e!r}"
            )
            if getattr(e, "code", None) in {0, 1, 2, 3, 999999}:
                return False
            rotate_server = getattr(client, "rotate_server", None)
            if callable(rotate_server):
                rotate_server()
    logger.warning(f"priconne check_client failed after {max_attempts} attempts")
    return False

async def safe_send(bot, ev, msg):
    if not msg:
        return
    try:
        await bot.send(ev, msg)
    except Exception as e:
        logger.opt(exception=e).warning(
            "priconne safe_send failed: "
            f"group_id={getattr(ev, 'group_id', None)}, "
            f"user_id={getattr(ev, 'user_id', None)}, "
            f"message={str(msg)[:120]!r}"
        )
