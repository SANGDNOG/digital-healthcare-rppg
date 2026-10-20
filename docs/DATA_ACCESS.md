# 데이터 확보 및 검증 범위 — 2026-10-21

## 현재 선택

학습 목표 데이터는 UBFC-Phys이며 아직 원본을 확보하지 않았다. 현재 Mac에서는 작은 **UBFC-rPPG DATASET_2 subject1**을 이용해 영상 처리 경로를 점검한다. 두 데이터셋은 다르며 UBFC-rPPG의 심박 비교를 스트레스 분류 성능으로 해석하지 않는다. 원본/생성 결과는 git에서 제외한다.

## UBFC-rPPG

- 공식 안내: https://sites.google.com/view/ybenezeth/ubfcrppg
- 공식 공유 폴더: https://drive.google.com/drive/folders/1o0XU4gTIo46YfwaWjIgbtCncc-oF44Xk
- subject1: https://drive.google.com/drive/folders/1q6U7jKRBUtr6N2rVs1vwZ2wuUT2VDoRy
- 원본 문서: `data/raw/ubfc-rppg-docs/readme.txt`, `Agreement.xlsx`.
- Agreement의 subject1 이미지 공개 동의/데이터 공유 동의 모두 X를 확인했다. 공식 README는 subject21·27 얼굴의 논문·발표·보고서 포함을 금지한다. 동의 표는 데이터 전체에 대한 포괄적 재배포 라이선스를 대신하지 않는다. 원본을 저장소에 커밋하거나 재배포하지 않는다.
- 인용: S. Bobbia, R. Macwan, Y. Benezeth, A. Mansouri, J. Dubois, “Unsupervised skin tissue segmentation for remote photoplethysmography”, Pattern Recognition Letters (2017).
- `ground_truth.txt` 행1은 contact PPG, 행2는 센서 HR, 행3은 초 단위 시각이다. subject1은 1547개 샘플, 시간 0–52.691초, 중복 시각이 있다.
- 저자들은 센서 HR 행을 평가 정답으로 사용하지 않고 contact PPG에서 추정한 HR와 비교했다. 따라서 센서 HR 비교는 탐색적 장치-HR 비교이며 논문의 평가 프로토콜 재현이 아니다. 명시적 동기화 검증 없이 정확도 검증 성공으로 표현하지 않는다.

## UBFC-Phys

- IEEE: https://ieee-dataport.org/open-access/ubfc-phys-2
- 대학: https://search-data.ubfc.fr/ube/FR-18008901306731-2022-05-05_UBFC-Phys-A-Multimodal-Dataset-For.html
- 대학 페이지에서 CC BY-NC-SA 3.0, 연구 목적을 확인했다. README는 `data/raw/ubfc-phys-docs/READ_ME.pdf`에 저장했다. SHA256: `4d664d33e57f087ca870eb25fc497b4f6516343f172dc3774314111e57caa703`.
- 56명, T1/T2/T3 영상·BVP(64Hz)·EDA(4Hz), info의 test/ctrl은 실험 조건이며 ML train/test split이 아니다. 사전/사후 불안 설문을 프레임 단위 정답으로 간주하지 않는다.
- README만으로 영상/BVP 동기화 규칙을 확정하지 못했다. 실제 파일과 원 논문을 확인한 다음 정렬/윈도우 라벨 규칙을 고정한다.
- IEEE는 파일 접근 로그인을 요구한다. 표시된 개인 ZIP도 약13–17GB이다. 대학의 묶음은 약85–149GB, 전체 약795GB로 현재 일괄 다운로드하지 않았다.
- 대학의 초기 브라우저 검사는 정상 진행 후 통과했다. README fetch 실패 뒤 페이지의 정상 다운로드 버튼으로 확보했다.

## 조사했지만 사용하지 않은 경로

- LGI-PPGI: https://github.com/partofthestars/LGI-PPGI-DB (확인 commit `8b36e18365359736d67705567c928f136d646133`). CC BY4.0이나 README가 호스팅 문제로 다운로드 중단을 안내한다.
- pyVHR 공개 저장소에는 참조되는 sampleDataset 영상이 포함되지 않았다. 코드 복사나 임의의 비공개 영상 사용은 하지 않았다.

## 학습 장비 준비 후

1. 원격 학습 장비에서 GPU/드라이버/디스크를 확인하고 기존 설치 스크립트를 실행한다.
2. UBFC-Phys 접근·용량을 확인해 작은 허용 범위부터 받는다.
3. 파일 해시/피험자/조건/동기화를 manifest에 기록한다.
4. 피험자 분리 평가를 먼저 고정하고 POS baseline과 HR-only 분류를 실행한다.
5. 실제 검증 결과에 따라 전처리·품질 기준 개선과 학습 모델을 결정한다.

## 실제 파일 실행 결과

subject1 영상(1,425,830,568 bytes)을 다운로드하고 전체 1547프레임(640×480, 명목29.264106FPS)을 처리했다. 영상 SHA256 `f6745be5e6b6fe2f00dd6f32dd234aa559bb30b45f38ec9d87cf9a1cc41f6954`, 기준 파일 SHA256 `836852f57f9cc9e04ecab134ebe506f831ad3e7d95ee73771ab8ac32ce845b67`. 로컬 manifest: `data/ubfc-rppg-subject1-manifest.json`.

실행: `uv run --locked python -m rppg analyze --video data/raw/ubfc-rppg/subject1/vid.avi --output runs/ubfc-rppg-subject1`. 보고서 생성 성공. 384프레임이 얼굴 ROI 조건을 충족하지 못했고, 33개 창 중 2개만 HR를 출력했다(coverage 6.1%). 31개는 유효 샘플 부족/긴 ROI 공백으로 abstain했다. 기준을 낮춰 결과를 늘리지 않았다. 이 결과는 파일 경로의 실행 검증이며 생체 정확도 검증 성공이 아니다. 다음 개선 우선순위는 얼굴/피부 ROI의 안정성이다.

영상 presentation timestamp와 센서 시각의 대응을 입증하지 못했고 기준 시각에 중복1개가 있어 공식 정확도 평가는 실행하지 않았다. 영상 길이가 첫60초 calibration보다 짧아 delta HR도 아직 제공되지 않는다.
