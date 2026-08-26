from msgpack import packb, unpackb
import asyncio
from random import randint
from json import loads
from hashlib import md5 ,sha256
from Crypto.Cipher import AES
from base64 import b64encode, b64decode
from .bsgamesdk import bsdkclient
import re
from dateutil.parser import parse
import httpx
from loguru import logger

import time
import json
import secrets
import string

from .storage import DEVICE_FILE, STATIC_VERSION_ORIGIN_FILE, VERSION_FILE


DEFAULT_API_ROOTS = (
    "https://l3-prod-all-gs-gzlj.bilibiligame.net",
    "https://l2-prod-all-gs-gzlj.bilibiligame.net",
    "https://le1-prod-all-gs-gzlj.bilibiligame.net",
)
RETRYABLE_SERVER_ERROR_STATUS = frozenset({4, 5, 6, 7, 8})
TERMINAL_SERVER_ERROR_STATUS = frozenset({0, 1, 2, 3, 403, 999999})


def get_api_root(qudao):
    if qudao == 0:
        return DEFAULT_API_ROOTS[0]
    raise ValueError(f"unsupported priconne channel: {qudao}")

config = str(VERSION_FILE)


def _get_version() -> str:
    if VERSION_FILE.exists():
        with open(VERSION_FILE, encoding='utf-8') as ver:
            if version := ver.read().strip():
                return version
    elif STATIC_VERSION_ORIGIN_FILE.exists():
        with open(STATIC_VERSION_ORIGIN_FILE, encoding='utf-8') as ver:
            if version := ver.read().strip():
                return version
    return "11.7.2"


def _set_version(version: str):
    VERSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(VERSION_FILE, mode='w', encoding='utf-8') as ver:
        ver.write(version)

def init_device_id(clear_id = False):
    DEVICE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if DEVICE_FILE.exists():
        try:
            with open(DEVICE_FILE, 'r', encoding='UTF-8') as f:
                js = json.load(f)
        except Exception:
            js = {"DEVICE-ID": ""}
    else:
        js = {"DEVICE-ID": ""}
    device_id = js.get('DEVICE-ID', '')
    if device_id == '' or clear_id:
        random_string = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32))
        sha256_str = sha256(random_string.encode('utf-8')).digest()
        current_timestamp = time.time()
        timestamp_str = str(current_timestamp).encode('utf-8')
        device_id = md5(timestamp_str + sha256_str).hexdigest()
        logger.info(f'设备id已更新：{device_id}')
        js['DEVICE-ID'] = device_id
        with open(DEVICE_FILE, 'w', encoding='UTF-8') as f:
            json.dump(js, f, indent=4, ensure_ascii=False)
    return device_id

defaultHeaders = {
    'Accept-Encoding': 'gzip',
    'User-Agent': 'Dalvik/2.1.0 (Linux, U, Android 5.1.1, PCRT00 Build/LMY48Z)',
    'X-Unity-Version': '2021.3.20f1c1',
    'APP-VER': "11.7.2",
    'BATTLE-LOGIC-VERSION': '4',
    'BUNDLE-VER': '',
    'DEVICE': '2',
    'DEVICE-ID': init_device_id(),
    'DEVICE-NAME': 'OPPO PCRT00',
    'EXCEL-VER': '1.0.0',
    'GRAPHICS-DEVICE-NAME': 'Adreno (TM) 640',
    'IP-ADDRESS': '10.0.2.15',
    'KEYCHAIN': '',
    'LOCALE': 'CN',
    'PLATFORM-OS-VERSION': 'Android OS 5.1.1 / API-22 (LMY48Z/rel.se.infra.20200612.100533)',
    'REGION-CODE': '',
    'RES-KEY': 'ab00a0a6dd915a052a2ef7fd649083e5',
    'RES-VER': '10002200',
    'SHORT-UDID': '0',
    'CHANNEL-ID': '1',
    'PLATFORM': '2',
    "Connection": "Keep-Alive"
}

class ApiException(Exception):

    def __init__(self, message, code, result_code=None):
        super().__init__(message)
        self.code = code
        self.status = code
        self.result_code = result_code


class pcrclient:

    def __init__(self, bsclient: bsdkclient):
        self.viewer_id = 0
        self.bsdk = bsclient
        self.headers = defaultHeaders.copy()
        self.headers['PLATFORM-ID'] = self.bsdk.platform
        self.client = httpx.AsyncClient(trust_env=False)
        self.call_lock = asyncio.Lock()
        self.servers = list(DEFAULT_API_ROOTS)
        self.active_server = 0

    @staticmethod
    def _normalize_server(server: str) -> str:
        server = str(server).replace("\t", "").strip().rstrip("/")
        if not server.startswith(("http://", "https://")):
            server = f"https://{server}"
        return server

    @property
    def current_api_root(self) -> str:
        return self.servers[self.active_server]

    def rotate_server(self) -> str:
        self.active_server = (self.active_server + 1) % len(self.servers)
        return self.current_api_root

    def _replace_servers(self, servers) -> None:
        normalized = list(dict.fromkeys(
            self._normalize_server(server) for server in servers if str(server).strip()
        ))
        if not normalized:
            raise ApiException("游戏服务器列表为空", 501)
        current = self.current_api_root
        self.servers = normalized
        try:
            self.active_server = self.servers.index(current)
        except ValueError:
            self.active_server = 0

    @staticmethod
    def createkey() -> bytes:
        return bytes([ord('0123456789abcdef'[randint(0, 15)]) for _ in range(32)])

    @staticmethod
    def add_to_16(b: bytes) -> bytes:
        n = len(b) % 16
        n = n // 16 * 16 - n + 16
        return b + (n * bytes([n]))

    @staticmethod
    def pack(data: object, key: bytes) -> bytes:
        aes = AES.new(key, AES.MODE_CBC, b'7Fk9Lm3Np8Qr4Sv2')
        return aes.encrypt(pcrclient.add_to_16(packb(data, use_bin_type=False))) + key

    @staticmethod
    def encrypt(data: str, key: bytes) -> bytes:
        aes = AES.new(key, AES.MODE_CBC, b'7Fk9Lm3Np8Qr4Sv2')
        return aes.encrypt(pcrclient.add_to_16(data.encode('utf8'))) + key

    @staticmethod
    def decrypt(data: bytes):
        data = b64decode(data.decode('utf8'))
        aes = AES.new(data[-32:], AES.MODE_CBC, b'7Fk9Lm3Np8Qr4Sv2')
        return aes.decrypt(data[:-32]), data[-32:]

    @staticmethod
    def unpack(data: bytes):
        data = b64decode(data.decode('utf8'))
        aes = AES.new(data[-32:], AES.MODE_CBC, b'7Fk9Lm3Np8Qr4Sv2')
        dec = aes.decrypt(data[:-32])
        return unpackb(dec[:-dec[-1]], strict_map_key=False), data[-32:]

    async def callapi(self, apiurl: str, request: dict, crypted: bool = True, noerr: bool = True, header=False):
        async with self.call_lock:
            key = pcrclient.createkey()
            request = request.copy()

            try:
                if self.viewer_id is not None:
                    request['viewer_id'] = b64encode(pcrclient.encrypt(
                        str(self.viewer_id), key)) if crypted else str(self.viewer_id)
                payload = pcrclient.pack(request, key) if crypted else json.dumps(request).encode('utf8')
                http_response = await self.client.post(
                    self.current_api_root + apiurl,
                    data=payload,
                    headers=self.headers,
                    timeout=20,
                )
                http_response.raise_for_status()
                response = http_response.content

                response = pcrclient.unpack(
                    response)[0] if crypted else loads(response)

                data_headers = response['data_headers']

                if 'sid' in data_headers and data_headers["sid"] != '':
                    t = md5()
                    t.update((data_headers['sid'] + 'c!SID!n').encode('utf8'))
                    self.headers['SID'] = t.hexdigest()

                if 'request_id' in data_headers:
                    self.headers['REQUEST-ID'] = data_headers['request_id']
                data = response['data']
                if not noerr and 'server_error' in data:
                    error = data['server_error'] or {}
                    result_code = data_headers.get('result_code')
                    logger.warning(
                        f"pcrclient: {apiurl} api failed: server={self.current_api_root}, "
                        f"status={error.get('status')}, result_code={result_code}, "
                        f"title={error.get('title', '')!r}, message={error.get('message', '')!r}"
                    )
                    raise ApiException(
                        error.get('message') or error.get('title') or "游戏服务器返回未知错误",
                        error.get('status'),
                        result_code,
                    )

                return data if not header else (data, data_headers)
            except ApiException:
                raise
            except Exception as e:
                raise ApiException(f"网络或响应解析错误：{e}", 501) from e

    async def refresh_servers(self):
        source_ini = await self.callapi(
            '/source_ini/index?format=json', {}, False, noerr=False
        )
        servers = source_ini.get('server') if isinstance(source_ini, dict) else None
        if not isinstance(servers, list):
            raise ApiException("游戏服务器列表响应异常", 501)
        self._replace_servers(servers)

    async def check_gamestart(self):
        request = {
            'apptype': 0,
            'campaign_data': '',
            'campaign_user': randint(0, 100000) & ~1,
        }
        gamestart, data_headers = await self.callapi(
            '/check/game_start', request, noerr=False, header=True
        )
        if "store_url" in data_headers:
            if version := re.compile(r"\d+\.\d+\.\d+").findall(data_headers["store_url"]):
                version = version[0]
                _set_version(version)
            else:
                version = _get_version()
            defaultHeaders['APP-VER'] = version
            self.headers['APP-VER'] = version
            request['campaign_user'] = randint(0, 100000) & ~1
            gamestart, data_headers = await self.callapi(
                '/check/game_start', request, noerr=False, header=True
            )

        if 'now_tutorial' in gamestart:
            if not gamestart['now_tutorial']:
                raise ApiException("该账号没过完教程!", 403)

    async def check_dangerous(self):
        lres, data_headers = await self.callapi(
            '/tool/sdk_login',
            {
                'uid': str(self.uid),
                'access_key': self.access_key,
                'channel': "1",
                'platform': self.bsdk.platform,
            },
            noerr=False,
            header=True,
        )
        if 'is_risk' in lres and lres['is_risk'] == 1:
            raise ApiException("账号存在风险", 403)
        self.viewer_id = data_headers['viewer_id']

    @staticmethod
    def _can_refresh_token(error: Exception) -> bool:
        message = str(error)
        if any(text in message for text in ("服务器在维护", "账号存在风险", "没过完教程")):
            return False
        return isinstance(error, ApiException) and error.code in {2, 3}

    @staticmethod
    def _can_retry_session(error: Exception) -> bool:
        if not isinstance(error, ApiException):
            return False
        return error.code == 501 or error.code in RETRYABLE_SERVER_ERROR_STATUS

    def _reset_game_session(self):
        self.viewer_id = 0
        self.headers.pop('REQUEST-ID', None)
        self.headers.pop('SID', None)

    async def _login_once(self):
        self._reset_game_session()
        await self.refresh_servers()

        manifest = await self.callapi(
            '/source_ini/get_maintenance_status?format=json', {}, False, noerr=False
        )
        if 'maintenance_message' in manifest:
            match = re.search(
                r'\d\d\d\d-\d\d-\d\d \d\d:\d\d:\d\d',
                manifest['maintenance_message'],
            )
            maintenance_end = parse(match.group()) if match else None
            raise ApiException("服务器在维护", 403, maintenance_end)

        ver = manifest['required_manifest_ver']
        logger.info(f'using manifest ver = {ver}')
        self.headers['MANIFEST-VER'] = str(ver)

        await self.check_dangerous()
        await self.check_gamestart()
        return await self.callapi('/load/index', {'carrier': 'OPPO'}, noerr=False)

    async def _login_with_current_token(self, max_attempts=5):
        last_error = None
        for attempt in range(1, max_attempts + 1):
            try:
                return await self._login_once()
            except Exception as error:
                last_error = error
                if not self._can_retry_session(error):
                    raise
                failed_server = self.current_api_root
                next_server = self.rotate_server()
                logger.warning(
                    "priconne session login retry: "
                    f"attempt={attempt}/{max_attempts}, server={failed_server}, "
                    f"next_server={next_server}, status={getattr(error, 'code', None)}, "
                    f"result_code={getattr(error, 'result_code', None)}, error={error}"
                )
        raise last_error or ApiException("登录失败，请重试", 501)

    async def login(self):
        used_saved_token = self.bsdk.has_saved_token()
        self.uid, self.access_key = await self.bsdk.login()

        try:
            await self._login_with_current_token()
        except Exception as e:
            if used_saved_token and self.bsdk.has_password_credentials() and self._can_refresh_token(e):
                logger.warning(f"saved priconne token failed, refreshing with account password: {e}")
                self.uid, self.access_key = await self.bsdk.login(force_password=True)
                await self._login_with_current_token()
                return
            raise

