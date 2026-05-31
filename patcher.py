"""
Core patching engine for WeChat anti-revoke.
All platform-specific code (winreg, ctypes WinAPI) is isolated and guarded.
"""
import hashlib
import json
import os
import shutil
import sys
import struct


WILDCARD = 0x3F  # '?' wildcard byte in pattern arrays

# Wechat 3.x/4.0.x uses WeChatWin.dll; Weixin 4.1.x+ uses Weixin.dll
_WECHAT_DLLS = ('WeChatWin.dll', 'Weixin.dll')


# ── Version utilities ────────────────────────────────────────────────────────

def compare_versions(v1: str, v2: str) -> int:
    """
    Compare two version strings.
    Returns 1 if v1 > v2, 0 if equal, -1 if v1 < v2.
    Empty string is treated as infinity (largest possible).
    """
    if not v1:
        return 1
    if not v2:
        return -1
    p1 = [int(x) for x in v1.split('.')]
    p2 = [int(x) for x in v2.split('.')]
    length = max(len(p1), len(p2))
    p1 += [0] * (length - len(p1))
    p2 += [0] * (length - len(p2))
    for a, b in zip(p1, p2):
        if a > b:
            return 1
        if a < b:
            return -1
    return 0


def is_in_version_range(version: str, start: str, end: str) -> bool:
    """
    Returns True when start < version <= end.
    Empty end means no upper limit (version is always <= infinity).
    """
    try:
        return compare_versions(version, start) == 1 and compare_versions(version, end) <= 0
    except Exception:
        return False


# ── Windows API helpers ──────────────────────────────────────────────────────

def get_file_version(path: str) -> str | None:
    """Return the four-part version string of a PE file via Windows API."""
    if sys.platform != 'win32':
        return None
    try:
        import ctypes
        size = ctypes.windll.version.GetFileVersionInfoSizeW(path, None)
        if not size:
            return None
        buf = ctypes.create_string_buffer(size)
        if not ctypes.windll.version.GetFileVersionInfoW(path, 0, size, buf):
            return None
        pfi = ctypes.c_void_p()
        pfi_len = ctypes.c_uint()
        if not ctypes.windll.version.VerQueryValueW(
                buf, "\\", ctypes.byref(pfi), ctypes.byref(pfi_len)):
            return None
        if not pfi.value:
            return None
        # VS_FIXEDFILEINFO: dwFileVersionMS at index 2, dwFileVersionLS at index 3
        raw = (ctypes.c_uint * 14)()
        ctypes.memmove(raw, pfi.value, ctypes.sizeof(raw))
        ms, ls = raw[2], raw[3]
        return (f"{(ms >> 16) & 0xFFFF}.{ms & 0xFFFF}"
                f".{(ls >> 16) & 0xFFFF}.{ls & 0xFFFF}")
    except Exception:
        return None


def compute_sha1(path: str) -> str:
    h = hashlib.sha1()
    with open(path, 'rb') as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def is_admin() -> bool:
    """Return True if the process has administrator privileges (Windows only)."""
    if sys.platform != 'win32':
        return True  # non-Windows: assume ok for dev
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


# ── DLL detection helpers ────────────────────────────────────────────────────

def _detect_dll(install_path: str, apps_cfg: dict | None = None) -> str | None:
    """
    Return the WeChat DLL name to use in install_path.
    If apps_cfg is supplied and multiple DLLs are present, picks the one whose
    version actually matches a patch range instead of blindly taking the first.
    """
    present = [n for n in _WECHAT_DLLS
               if os.path.isfile(os.path.join(install_path, n))]
    if not present:
        return None
    if len(present) == 1 or apps_cfg is None:
        return present[0]

    def _has_match(dll_name: str) -> bool:
        version = get_file_version(os.path.join(install_path, dll_name))
        if not version:
            return False
        try:
            app_cfg = _app_cfg_for_dll(apps_cfg, dll_name)
        except KeyError:
            return False
        for info in (app_cfg.get('FileModifyInfos') or {}).get(dll_name, []):
            if info.get('Version') == version:
                return True
        for common in (app_cfg.get('FileCommonModifyInfos') or {}).get(dll_name, []):
            if is_in_version_range(version, common['StartVersion'],
                                   common.get('EndVersion', '')):
                return True
        return False

    matched = [n for n in present if _has_match(n)]
    return matched[0] if matched else present[0]


def _app_cfg_for_dll(apps_cfg: dict, dll_name: str) -> dict:
    """Return the app config dict that owns dll_name (via FileTargetInfos)."""
    for app in apps_cfg.values():
        if dll_name in app.get('FileTargetInfos', {}):
            return app
    raise KeyError(f'未找到 {dll_name} 对应的补丁配置')


# ── WeChat install detection ─────────────────────────────────────────────────

def find_wechat_path() -> str:
    """Auto-detect WeChat install directory. Returns '' if not found."""
    if sys.platform != 'win32':
        return ''

    import winreg

    def any_dll_exists(p: str) -> bool:
        return bool(p) and any(
            os.path.isfile(os.path.join(p, dll)) for dll in _WECHAT_DLLS)

    def search_subdirs(base: str) -> str:
        """WeChat 3.5+ stores DLL in a version sub-directory."""
        if not os.path.isdir(base):
            return ''
        try:
            subs = sorted(
                [os.path.join(base, d) for d in os.listdir(base)
                 if os.path.isdir(os.path.join(base, d))],
                key=os.path.getmtime, reverse=True)
            for d in subs:
                if any_dll_exists(d):
                    return d
        except OSError:
            pass
        return ''

    candidates: list[str] = []

    # WeChat (3.x / 4.0.x): InstallLocation
    for hive, key_path in [
        (winreg.HKEY_LOCAL_MACHINE,
         r'Software\Microsoft\Windows\CurrentVersion\Uninstall\WeChat'),
        (winreg.HKEY_LOCAL_MACHINE,
         r'SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\WeChat'),
    ]:
        try:
            key = winreg.OpenKey(hive, key_path)
            value, _ = winreg.QueryValueEx(key, 'InstallLocation')
            winreg.CloseKey(key)
            if value:
                candidates.append(value.strip('"').strip())
        except OSError:
            pass

    # Weixin (4.1.x+): UninstallString → parent directory is the install root
    try:
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r'SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Weixin')
        value, _ = winreg.QueryValueEx(key, 'UninstallString')
        winreg.CloseKey(key)
        if value:
            parent = os.path.dirname(value.strip('"').strip())
            if parent:
                candidates.append(parent)
    except OSError:
        pass

    # Default install locations on all drives
    import string
    drives = [f'{d}:\\' for d in string.ascii_uppercase
              if os.path.exists(f'{d}:\\')]
    for drive in drives:
        for sub in (r'Program Files (x86)\Tencent\WeChat',
                    r'Program Files\Tencent\WeChat',
                    r'Program Files (x86)\Tencent\Weixin',
                    r'Program Files\Tencent\Weixin',
                    r'Tencent\WeChat',
                    r'Tencent\Weixin'):
            candidates.append(os.path.join(drive, sub))

    for path in candidates:
        if any_dll_exists(path):
            return path
        found = search_subdirs(path)
        if found:
            return found

    return ''


# ── Byte-pattern fuzzy matching ──────────────────────────────────────────────

def fuzzy_match_all(data: bytes, pattern: list[int]) -> list[int]:
    """
    Return all start positions where pattern matches data.
    WILDCARD (0x3F) in pattern matches any byte.
    """
    head_len = next((i for i, b in enumerate(pattern) if b == WILDCARD),
                    len(pattern))
    if head_len == 0:
        raise ValueError("Pattern must not start with a wildcard")
    head = bytes(pattern[:head_len])

    positions: list[int] = []
    start = 0
    pat_len = len(pattern)
    while True:
        pos = data.find(head, start)
        if pos == -1:
            break
        # Verify full pattern
        if pos + pat_len <= len(data):
            if all(pattern[i] == WILDCARD or data[pos + i] == pattern[i]
                   for i in range(pat_len)):
                positions.append(pos)
        start = pos + 1
    return positions


# ── Backup helpers ───────────────────────────────────────────────────────────

def _bak_path(dll: str) -> str:
    return dll + '.h.bak'


def _backup(dll: str) -> None:
    bak = _bak_path(dll)
    if os.path.exists(bak):
        curr = get_file_version(dll)
        old = get_file_version(bak)
        if curr and old and curr == old:
            return  # same version, keep existing backup
    shutil.copy2(dll, bak)


def backup_exists(install_path: str) -> bool:
    for name in _WECHAT_DLLS:
        dll = os.path.join(install_path, name)
        if os.path.isfile(_bak_path(dll)):
            return True
    return False


# ── Status check ─────────────────────────────────────────────────────────────

def get_status(install_path: str, apps_cfg: dict) -> tuple[str, str, str]:
    """
    Returns (version, status, message).
    status: 'ok' | 'patched' | 'unsupported' | 'error'
    apps_cfg: the full Apps dict from patch.json
    """
    dll_name = _detect_dll(install_path, apps_cfg)
    if not dll_name:
        return '', 'error', '未找到 WeChatWin.dll 或 Weixin.dll'

    dll = os.path.join(install_path, dll_name)
    version = get_file_version(dll)
    if not version:
        return '', 'error', '无法读取文件版本（需要在 Windows 上运行）'

    try:
        app_cfg = _app_cfg_for_dll(apps_cfg, dll_name)
    except KeyError as e:
        return version, 'error', str(e)

    sha1 = compute_sha1(dll)

    for info in (app_cfg.get('FileModifyInfos') or {}).get(dll_name, []):
        if info['SHA1After'] == sha1:
            return version, 'patched', '已安装补丁'
        if info['SHA1Before'] == sha1:
            return version, 'ok', '支持（精准匹配）'

    for common in (app_cfg.get('FileCommonModifyInfos') or {}).get(dll_name, []):
        if is_in_version_range(version, common['StartVersion'],
                               common.get('EndVersion', '')):
            cats = {p.get('Category', '') for p in common['ReplacePatterns']}
            if any('防撤回' in c for c in cats):
                return version, 'ok', '支持（特征码匹配）'

    return version, 'unsupported', f'暂不支持版本 {version}'


# ── Patch ────────────────────────────────────────────────────────────────────

def patch(install_path: str, apps_cfg: dict, log) -> None:
    """
    Apply anti-revoke patch.
    Raises Exception on any failure.
    apps_cfg: the full Apps dict from patch.json
    log: callable(str) for progress messages.
    """
    dll_name = _detect_dll(install_path, apps_cfg)
    if not dll_name:
        raise FileNotFoundError('未找到 WeChatWin.dll 或 Weixin.dll')

    dll = os.path.join(install_path, dll_name)
    try:
        app_cfg = _app_cfg_for_dll(apps_cfg, dll_name)
    except KeyError as e:
        raise Exception(str(e))

    version = get_file_version(dll)
    if not version:
        raise RuntimeError('无法读取文件版本，请确认在 Windows 上以管理员运行')
    log(f'版本: {version}  ({dll_name})')

    sha1 = compute_sha1(dll)
    log(f'SHA1: {sha1[:16]}…')

    # ── Exact position patch ──────────────────────────────────────────────
    for info in (app_cfg.get('FileModifyInfos') or {}).get(dll_name, []):
        if info['SHA1After'] == sha1:
            raise Exception('当前文件已安装补丁，无需重复操作')
        if info['SHA1Before'] == sha1:
            log('匹配精准版本补丁')
            with open(dll, 'rb') as f:
                data = bytearray(f.read())
            _backup(dll)
            log('已备份原始文件')
            for ch in info['Changes']:
                pos, content = ch['Position'], bytes(ch['Content'])
                data[pos:pos + len(content)] = content
            with open(dll, 'wb') as f:
                f.write(data)
            log('✓ 补丁安装成功！')
            return

    # ── Pattern (fuzzy) patch ─────────────────────────────────────────────
    for common in (app_cfg.get('FileCommonModifyInfos') or {}).get(dll_name, []):
        if not is_in_version_range(version, common['StartVersion'],
                                   common.get('EndVersion', '')):
            continue
        end_display = common.get('EndVersion') or '最新'
        log(f'特征码范围: {common["StartVersion"]} ~ {end_display}')

        revoke_patterns = [p for p in common['ReplacePatterns']
                           if '防撤回' in p.get('Category', '')]
        if not revoke_patterns:
            raise Exception('此版本范围内无防撤回特征码')

        # When both 老/新 variants exist, prefer generic or 老 (simpler, more stable)
        if len(revoke_patterns) > 1:
            for preferred in ('防撤回', '防撤回(老)'):
                subset = [p for p in revoke_patterns if p.get('Category') == preferred]
                if subset:
                    revoke_patterns = subset
                    break

        size_mb = os.path.getsize(dll) // (1024 * 1024)
        log(f'读取 DLL ({size_mb} MB)…')
        with open(dll, 'rb') as f:
            data = bytearray(f.read())

        for pat in revoke_patterns:
            search = pat['Search']
            replace = pat['Replace']
            cat = pat.get('Category', '防撤回')
            log(f'搜索特征: {cat}')
            positions = fuzzy_match_all(bytes(data), search)
            if not positions:
                raise Exception(f'未找到特征码 [{cat}]，当前版本可能已不支持')
            log(f'  命中 {len(positions)} 处，应用替换…')
            for pos in positions:
                for i, b in enumerate(replace):
                    if b != WILDCARD:
                        data[pos + i] = b

        _backup(dll)
        log('已备份原始文件')
        with open(dll, 'wb') as f:
            f.write(data)
        log('✓ 补丁安装成功！')
        return

    raise Exception(f'不支持版本 {version}，补丁数据可能需要更新')


# ── Restore ──────────────────────────────────────────────────────────────────

def restore(install_path: str, log) -> None:
    """Restore DLL from backup. Raises on failure."""
    for name in _WECHAT_DLLS:
        dll = os.path.join(install_path, name)
        bak = _bak_path(dll)
        if os.path.isfile(bak):
            log(f'还原 {name}…')
            shutil.copy2(bak, dll)
            log('✓ 还原成功！')
            return
    raise FileNotFoundError('未找到备份文件 (.h.bak)，无法还原')
