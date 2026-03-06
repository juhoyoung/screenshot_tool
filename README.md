# 📸 Screenshot Tray App

활성 창을 자동으로 캡처하여 저장하는 Windows 트레이 프로그램입니다.

---

## ✨ 기능

| 기능 | 설명 |
|------|------|
| 🖼️ 활성 창 캡처 | PrintScreen 키로 현재 활성화된 창만 정밀 캡처 |
| 📁 자동 폴더 생성 | 창 이름으로 하위 폴더 자동 생성하여 분류 저장 |
| 🗂️ 형식 선택 | PNG / JPEG / BMP / WEBP 지원 |
| ⚙️ 설정 UI | 저장 경로, 형식, 단축키, 알림 설정 |
| 🔔 트레이 알림 | 캡처 후 저장 경로 알림 표시 |
| ⌨️ 단축키 변경 | PrintScreen 외 다양한 단축키 설정 가능 |

---

## 🚀 설치 및 실행

### 방법 1: BAT 파일 실행 (권장)
```
install_and_run.bat 더블클릭
```

### 방법 2: 수동 설치
```bash
pip install pillow pystray pywin32 keyboard

# 실행 (창 없이 트레이로)
pythonw screenshot_app.py

# 또는 일반 실행 (콘솔 창 있음)
python screenshot_app.py
```

---

## 📂 저장 구조

```
저장경로/
├── Chrome/
│   ├── 20240315_143022.png
│   └── 20240315_143155.png
├── Visual Studio Code/
│   └── 20240315_150001.jpg
└── 메모장/
    └── 20240315_152233.png
```

---

## ⌨️ 지원 단축키

- `print_screen` (기본값)
- `ctrl+shift+s`
- `ctrl+alt+s`
- `ctrl+shift+p`
- `f12`
- `ctrl+f12`

---

## 🔧 시스템 요구사항

- **OS**: Windows 10 / 11
- **Python**: 3.8 이상
- **패키지**: pillow, pystray, pywin32, keyboard

---

## ⚠️ 참고사항

- **관리자 권한**이 필요할 수 있습니다 (특히 `keyboard` 전역 단축키 등록 시)
- 앱 시작 시 자동 실행하려면 `shell:startup` 폴더에 바로가기를 추가하세요
- 설정은 `%USERPROFILE%\.screenshot_tray_config.json`에 저장됩니다
