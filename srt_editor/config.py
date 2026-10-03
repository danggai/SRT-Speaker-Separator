"""앱 설정 파일(.srt_speaker_editor_config.json) 로드/저장."""
import json
import os
import pathlib
import sys
import tempfile


# ── 앱 설정 저장/불러오기 ─────────────────────────────────
# 홈 디렉토리에 쓰기가 실패하는 환경(.py로 직접 실행 시 권한 문제 등)에서도
# 설정이 저장되도록, 순서대로 시도할 후보 경로 목록을 만든다.
def _build_config_candidates():
    paths = []
    try:
        paths.append(pathlib.Path.home() / ".srt_speaker_editor_config.json")
    except Exception:
        pass
    try:
        _script_dir = pathlib.Path(os.path.abspath(
            getattr(sys.modules.get("__main__"), "__file__", None) or __file__)).parent
        paths.append(_script_dir / ".srt_speaker_editor_config.json")
    except Exception:
        pass
    try:
        paths.append(pathlib.Path(tempfile.gettempdir()) / ".srt_speaker_editor_config.json")
    except Exception:
        pass
    # 중복 제거(순서 유지)
    seen = set(); uniq = []
    for p in paths:
        key = str(p)
        if key not in seen:
            seen.add(key); uniq.append(p)
    return uniq or [pathlib.Path(".srt_speaker_editor_config.json")]

_CONFIG_CANDIDATES = _build_config_candidates()
_CONFIG_PATH        = _CONFIG_CANDIDATES[0]   # 하위 호환용 (표시/참조용)
_MAX_RECENT_TOKENS = 5

def _load_config() -> dict:
    for p in _CONFIG_CANDIDATES:
        try:
            if p.exists():
                return json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[config] 읽기 실패({p}): {e}", file=sys.stderr)
            continue
    return {}

def _save_config(cfg: dict):
    """후보 경로에 순서대로 저장을 시도한다(임시파일에 쓴 뒤 교체 = 원자적 저장).
    첫 후보(홈 디렉토리)가 쓰기 실패하면 다음 후보(스크립트 폴더, 임시폴더)로
    자동 대체하므로, .py로 직접 실행해도 설정/고유명사 목록 등이 저장된다."""
    try:
        data = json.dumps(cfg, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[config] 직렬화 실패: {e}", file=sys.stderr)
        return False
    for p in _CONFIG_CANDIDATES:
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_name(p.name + ".tmp")
            tmp.write_text(data, encoding="utf-8")
            tmp.replace(p)
            return True
        except Exception as e:
            print(f"[config] 저장 실패({p}): {e}", file=sys.stderr)
            continue
    return False


def _add_recent_token(cfg: dict, token: str):
    """최근 토큰 목록에 추가 (최대 _MAX_RECENT_TOKENS개, 중복 제거)."""
    if not token:
        return cfg
    recent = cfg.get("recent_tokens", [])
    if token in recent:
        recent.remove(token)
    recent.insert(0, token)
    cfg["recent_tokens"] = recent[:_MAX_RECENT_TOKENS]
    return cfg
