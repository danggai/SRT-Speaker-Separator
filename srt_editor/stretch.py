"""재생 배속용 소리 만들기: 음 높이는 그대로 두고 속도만 바꾼 재생용 FLAC (PyAV atempo)."""
import hashlib
import os
import pathlib

SPEEDS = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0)
BOOST = 1.5    # 볼륨 100% 넘길 때 쓰는 키운 소리 (최대 150%)
RATE = 22050   # 말소리 확인용이라 모노 22kHz로 충분 (파일 크기 절약)


def _factors(speed):
    """atempo 한 번에 0.5~2배만 되는 오래된 ffmpeg도 있어 나눠서 곱한다."""
    out = []
    while speed > 2.0:
        out.append(2.0)
        speed /= 2.0
    while speed < 0.5:
        out.append(0.5)
        speed /= 0.5
    out.append(speed)
    return out


def cache_dir():
    from . import waveform
    return pathlib.Path(waveform.CACHE_DIR).parent / "speed"


def cache_path(src, speed, gain=1.0):
    st = os.stat(src)
    key = hashlib.sha1(f"{os.path.abspath(src)}|{st.st_size}|{st.st_mtime_ns}".encode("utf-8")).hexdigest()[:16]
    return cache_dir() / f"{key}_{speed:g}{f'_g{gain:g}' if gain != 1.0 else ''}.flac"


def render(src, speed, cancelled=None, gain=1.0):
    """src를 speed배·gain배 소리로 만든 재생용 FLAC 경로 (이미 있으면 그대로). 취소되면 None."""
    import av
    from .video import PlayAudioWriter
    dst = cache_path(src, speed, gain)
    if dst.exists():
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    part = dst.with_suffix(".part")
    rate = RATE if speed != 1.0 else 44100   # 1배속은 원래 음질로
    out = PlayAudioWriter(av, part, rate)
    with av.open(str(src)) as inp:
        stream = next(s for s in inp.streams if s.type == "audio")
        graph = av.filter.Graph()
        nodes = [graph.add_abuffer(template=stream)]
        if speed != 1.0:
            nodes += [graph.add("atempo", f"{f:.6f}") for f in _factors(speed)]
        if gain != 1.0:
            nodes += [graph.add("volume", f"{gain:g}"), graph.add("alimiter", "limit=0.97")]
        nodes += [graph.add("aresample", str(rate)), graph.add("aformat", f"sample_fmts=s16:channel_layouts=mono")]
        nodes.append(graph.add("abuffersink"))
        for a, b in zip(nodes, nodes[1:]):
            a.link_to(b)
        graph.configure()

        def drain():
            while True:
                try:
                    f = graph.pull()
                except (BlockingIOError, av.error.BlockingIOError):
                    return
                except (EOFError, av.error.EOFError):
                    return
                out.write(f)
        for frame in inp.decode(stream):
            if cancelled and cancelled():
                break
            graph.push(frame)
            drain()
        else:
            graph.push(None)
            drain()
    out.close()
    if cancelled and cancelled():
        part.unlink(missing_ok=True)
        return None
    os.replace(part, dst)
    return dst


def clear(keep_src=None):
    """다른 파일의 배속 소리를 지운다 (keep_src 것은 남김)."""
    d = cache_dir()
    if not d.exists():
        return
    keep = cache_path(keep_src, 1.0).name.split("_")[0] if keep_src and os.path.exists(keep_src) else None
    for f in list(d.glob("*.flac")) + list(d.glob("*.wav")):
        if keep is None or not f.name.startswith(keep) or f.suffix == ".wav":
            try:
                f.unlink()
            except OSError:
                pass
