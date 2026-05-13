# SRT 화자 분리기 (srt_speaker_separator)

SRT 자막을 `[화자] 내용` 형식으로 구분하여
화자별 `.srt` 파일로 분리하는 간단한 도구입니다.

---

## 📌 주요 기능

* `[화자] 내용` 형식 기반 자동 분리
* 화자별 `.srt` 파일 생성 (예: `a.srt`, `b.srt`)
* 태그 없는 자막은 별도 파일로 저장 (`*_untagged.srt`)
* 간단한 자막 편집 기능

---

## ▶ 사용 방법

* exe 실행 후 SRT 파일 드래그 & 드롭
  또는:

```bash
srt_speaker_separator.exe input.srt
```

---

## 🧩 예시

입력:

```srt
1
00:00:01,000 --> 00:00:03,000
[a] 안녕하세요

2
00:00:04,000 --> 00:00:06,000
[b] 반갑습니다
```

---

## 📤 출력

* `a.srt`
* `b.srt`
* `input_untagged.srt` (태그 없는 자막이 있을 경우만 생성)

---

## 🛠 빌드 방법

```bash
python -m pip install pyinstaller
python -m PyInstaller --onefile --noconsole --name srt_speaker_separator srt_speaker_separator.py
```

결과:

```
dist/srt_speaker_separator.exe
```

---

끝.
