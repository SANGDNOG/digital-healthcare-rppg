# Digital Healthcare rPPG

웹캠으로 얻은 생리 변화와 개인의 휴식 기준선·자가보고를 함께 관찰하는 **비접촉 스트레스 반응 자가 모니터링** 프로젝트입니다. 현재는 심박(HR) 추정·품질 관리와 3분 실험 기록 단계이며, 스트레스 점수·진단·분류 성능은 검증하지 않았습니다.

## 현재 결과 · 2026-10-28

- UBFC-rPPG 추가 3명(subject3·4·5)에서 얼굴 연속성 선택으로 HR 출력이 **48/101 → 67/101창**으로 증가했습니다.
- 영상·접촉 신호 모두 유효한 60창의 조건부 MAE **1.68 BPM**, RMSE **2.58 BPM**입니다. 비교에서 빠진 41창의 오차는 알 수 없습니다.
- 20초 창을 1초마다 분석하여 95% 중첩됩니다. 101회 독립 실험이 아니며, 시작 시각 대응도 독립 검증되지 않은 예비 결과입니다.
- 전후 공통 46창의 추정치는 동일합니다. 확인한 개선은 출력 가능 구간 증가이며 정확도 향상이 아닙니다.
- 웹캠 로컬 분석·품질 경고·휴식60초/무음 암산60초/회복60초 기록·JSON/CSV 내보내기를 구현했습니다. 실제 3분 실험의 생리적 타당성은 아직 확인하지 않았습니다.

팀원은 [현재 상태와 할 일](docs/TEAM_STATUS.md), [상세 결과 설명](docs/TEAM_UPDATE_2026-10-28.txt), [멘토 보고서 별첨 PDF](docs/mentor-report-20261028/멘토보고서_별첨.pdf)를 읽어 주세요. [읽기 좋은 HTML](docs/mentor-report-20261028/index.html)은 다운로드 후 브라우저에서 열 수 있습니다. 학번·서명이 있는 제출지는 공개하지 않습니다.

## 빠른 시작

Python 3.11, [uv](https://docs.astral.sh/uv/getting-started/installation/)가 필요합니다. macOS/Linux 셸 기준이며 Windows는 WSL 사용을 권장합니다(네이티브 Windows 미검증).

```bash
git clone https://github.com/SANGDNOG/digital-healthcare-rppg.git
cd digital-healthcare-rppg
bash scripts/setup.sh
uv run --locked pytest -q
uv run --locked python -m rppg demo --output runs/my-first-demo
```

`runs/my-first-demo/report.html`을 브라우저로 열면 됩니다. demo는 **합성 신호**이며 실제 측정이 아닙니다. 출력 폴더가 이미 있으면 덮어쓰지 않으므로 새 이름을 지정하세요. setup은 uv 관리 Python과 잠금 의존성을 설치하고 데이터 폴더를 준비합니다. 데이터 다운로드·카메라 실행·학습은 자동으로 시작하지 않습니다.

```bash
uv run --locked python -m rppg --help
uv run --locked python -m rppg analyze --video /path/to/consented.mp4 --output runs/video-001
# 사용자가 직접 카메라를 사용할 때만 실행
uv run --locked python -m rppg capture --camera 0 --duration 90 --output runs/capture-001
```

`.tools/bin/uv`가 설치된 개발 환경에서는 `uv` 대신 해당 경로를 사용할 수 있습니다. 실제 카메라의 OS 권한과 실행 속도는 별도 확인해야 합니다.

## 웹캠·3분 실험

분석할 컴퓨터에 설치한 뒤 아래 명령으로 루프백 서버를 시작합니다. SSH나 다른 컴퓨터를 경유하지 않는 로컬 실행 기준입니다.

```bash
uv run --locked python -m rppg.live --port 8766
```

같은 컴퓨터에서 `http://127.0.0.1:8766/`을 열고 사용자가 카메라 시작을 선택합니다. 서버 시작만으로 카메라를 켜지 않습니다. 실험 안내는 [3분 실험 가이드](docs/STRESS_PILOT_GUIDE.txt)를 참고하세요. 카메라·브라우저·OS에 따른 동작은 별도 확인이 필요합니다. 개인 환경의 자동 설치·SSH 실행기는 공개본에 포함하지 않습니다.

현재 공개 실행은 로컬 매니페스트를 주지 않으므로 화면에 “원격 PC에서 분석”으로 표시되는 알려진 표시 제약이 있습니다. 위 명령은 같은 컴퓨터의 루프백 서버에서 처리합니다. 화면의 기존 결과·안내 링크(8765)는 개인 환경용으로 공개본에서는 연결되지 않습니다. 대신 저장소의 실험 가이드를 읽어 주세요.

## 코드와 검증

- `rppg/face_selection.py`, `video.py`: 얼굴 후보 연속성 선택·영상 입력
- `rppg/signal.py`: POS 맥파·심박·품질 보류
- `rppg/live.py`, `rppg/live_web/`: 루프백 웹캠 분석·상태 표시·3분 실험
- `rppg/evaluation.py`: 기준 HR 비교와 피험자 분리 분류 도구(실제 스트레스 성능 미평가)
- [사용법](docs/USAGE.md), [데이터 접근](docs/DATA_ACCESS.md), [협업 안내](CONTRIBUTING.md)

2026-10-28 비공개 개인 실행기까지 포함한 전체 작업본은 Python 224개, Node 78개(독립 점검 포함)가 통과했습니다. 공개본에서는 개인 실행기와 해당 테스트를 제외합니다. 공개할 스냅샷을 따로 추출하여 **Python 174개·저장소 Node 47개**가 모두 통과한 것도 확인했습니다. 기존 잠금 환경을 사용한 검증이며 새 컴퓨터의 처음 설치는 이번에 검증하지 않았습니다. 테스트 통과는 생체 정확도 검증이 아닙니다.

## 데이터와 공개 범위

원본 영상·원시 생체신호·개인별 실험 내보내기·학번·서명·인증정보는 공개하지 않습니다. `runs/`와 `workspace/`는 비공개 작업 결과 위치이며 저장소에서 배포하지 않습니다. 데이터는 공식 출처의 이용 조건을 확인해 별도로 확보합니다.

UBFC-rPPG는 이번 심박 예비 비교 자료이고, 1차 계획의 UBFC-Phys는 별도 스트레스 과제 데이터입니다. UBFC-Phys 학습·평가는 아직 실시하지 않았습니다. HRV/PRV·개인화·스트레스 분류도 미검증입니다. 품질 임계값은 연구용 휴리스틱이며 Haar 이마·볼 ROI는 피부 분할이 아닙니다.

10/26 문서는 당시 상태의 이력입니다. 최신 해석은 이 README와 10/28 보고서를 따릅니다. 외부 재사용 라이선스는 팀 합의 전 미지정이며 데이터셋 조건은 원저작자의 조건을 따릅니다.

멘토 피드백 요청은 [별도 상세 요청서 PDF](docs/mentor-report-20261028/멘토_피드백_상세요청서.pdf)에서 확인할 수 있습니다. 요청사항 1~5번과 각 항목의 설명으로 정리한 1쪽 자료입니다.

## Windows 팀원용 패키지

Windows x64 팀원에게는 검증된 ZIP을 전달합니다. 압축을 모두 풀고 `실험 시작.cmd`를 실행하면 bundled uv가 Python 3.11.17과 고정 의존성을 폴더 내부에 준비합니다. 첫 실행에는 인터넷이 필요하며 SSH나 GitHub 로그인을 요구하지 않습니다. 화면의 3분 예비 실험을 마친 뒤 JSON·CSV를 직접 내려받습니다.

배포 소스와 안내는 `packaging/windows/`, 핵심 검증은 `tests/test_windows_package.py`에 있습니다. 패키지는 기존 핵심 Python/JS를 유지하고 안내·결과 링크만 패키지 안으로 연결합니다. 실제 생리 측정의 정확도나 참여자별 성공을 보장하는 패키지가 아닙니다.

패키지를 다시 만들 때는 공식 uv 0.13.6 Windows x64 배포본의 SHA256을 검증하고 `workspace/windows-package-20261028/vendor/`에 `uv.exe`, `uv-LICENSE-MIT`, `uv-LICENSE-APACHE`를 준비한 뒤 `python packaging/windows/assemble_bundle.py`를 실행합니다. 빌더는 기존 출력 폴더를 덮어쓰지 않습니다. ZIP과 설치 캐시는 저장소에 커밋하지 않습니다.
