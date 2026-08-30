# 민사소송법 기본서·사례집 PDF → Markdown 변환기

변리사 2차 민사소송법 단권화 노트를 만들기 위한 **소스 전처리** 도구다.
결과물은 사람이 읽으려는 게 아니라 **뒤에 오는 AI 처리가 정확히 파싱할 수 있는
구조화 텍스트**다. 사람이 보기에 조금 어색해도 좋다. 대신 사건번호 한 글자,
두문자 한 글자가 틀리면 안 된다.

기존 `../dist/pdf2md.html`(특허 서식용 브라우저 도구)과는 별개 프로그램이다.
쓰임이 다르고 지켜야 할 것이 다르다.

## 설치

```bash
pip install -r requirements.txt          # PyYAML + PyMuPDF
```

`marker` / `mineru` / `paddleocr` 는 필요할 때만 깔면 된다. 무엇이 준비됐는지는
`convert parsers` 로 본다.

## 쓰는 법 (§7)

```bash
# 한 번에 (진단 → 변환 → 검증 → 교차검증). 파일마다 프로파일을 알아서 고른다.
./convert all "PDF가 든 폴더" --out output

# 0) 무엇을 쓸 수 있나
./convert parsers

# 1) 진단부터. 이걸 건너뛰면 run 이 막힌다.
./convert diagnose 기본서.pdf --out output
./convert diagnose "PDF가 든 폴더" --out output              # 폴더째 진단 + 요약표
./convert diagnose 기본서.pdf --out output --pages 120-122   # 조판을 볼 쪽 지정

# 2) 한 장(章)만 변환해서 파이프라인을 확인한다
./convert run 기본서.pdf --pages 120-145 --profile textbook --out output/기본서

# 3) 전체 변환
./convert run 기본서.pdf --profile textbook --out output/기본서
./convert run 사례집.pdf --profile casebook --out output/사례집

# 4) 검증만 다시 / 두 소스 교차 검증
./convert validate output
./convert crosscheck output/기본서 output/사례집

# 진단이 "없다" 고 할 때 — 원문 증거를 그대로 뜬다
./convert probe 기본서.pdf                    # 괄호·색·도형·옆번호·두문자 후보
./convert probe 기본서.pdf --find "시효중단"    # 몇 쪽에 있나 (변환할 장 고르기)
./convert probe 기본서.pdf --page 137          # 그 쪽 span·도형 전부 덤프
./convert probe 기본서.pdf --lines --pages 170-173   # 줄마다 무엇으로 읽혔는지
```

### Windows

`convert.cmd` 가 같은 일을 한다. `requirements.txt` 와 `convert.cmd` 는
**이 프로그램 폴더**에 있다. PDF 폴더가 아니라 프로그램 폴더에서 실행하고,
PDF 는 경로로 넘긴다.

전체를 한 번에 돌리려면:

```bat
convert all "%USERPROFILE%\Documents\9. 민소법\25년 윤곽" --out "%USERPROFILE%\Documents\민소출력"
```

리포트는 파일마다 이름을 붙여 남는다(`validation-<파일>.md`, `caselist-<파일>.txt` …).
FAIL 이 하나라도 있으면 종료 코드 1 이다.

```bat
REM 1) 프로그램 내려받기 (git 이 있을 때)
cd /d %USERPROFILE%\Documents
git clone -b claude/pdf-to-markdown-converter-lvkvkr https://github.com/ahn0405-cpu/pdf2md.git

REM 2) 설치
cd /d %USERPROFILE%\Documents\pdf2md\book2md
python -m pip install -r requirements.txt

REM 3) 진단 — 폴더째 넘기면 안의 PDF 를 모두 본다
convert diagnose "%USERPROFILE%\Documents\9. 민소법\25년 윤곽" --out "%USERPROFILE%\Documents\민소출력"
```

git 이 없으면 아래 ZIP 을 받아 `Documents` 아래에 풀고 2)부터 하면 된다.

```
https://github.com/ahn0405-cpu/pdf2md/archive/refs/heads/claude/pdf-to-markdown-converter-lvkvkr.zip
```

교재가 여러 권으로 나뉘어 있으면 **출력 폴더를 나눈다.** 사례집 상·하를 같은
폴더에 쏟으면 문제 그룹 파일 이름(`E_*.md`)이 겹친다.

```bat
convert run "...\윤곽 민소법 기본서_압축.pdf"  --profile textbook --out output\기본서
convert run "...\윤곽 민소 사례집 상.pdf"      --profile casebook --out output\사례집상
convert run "...\윤곽 민소 사례집 하.pdf"      --profile casebook --out output\사례집하
convert crosscheck output\기본서 output\사례집상
```

`--from` 으로 중간 단계부터 다시 돌릴 수 있다.

```bash
./convert run 기본서.pdf --profile textbook --from normalize    # 추출 결과 재사용
```

## 출력

```
output/
├── 기본서/  01_CHAPTER05소송물.md …      # 장(章) 단위, 400KB 넘으면 절 단위
├── 사례집/  E_일부청구.md …              # 문제 그룹 단위
└── _reports/
    ├── diagnosis.md      진단 (§3.1)  · diagnosis-<파일>.md 로도 남는다
    ├── palette.md        색상 팔레트 (§2.4) — 매핑은 사람이 정한다
    ├── validation.md     검증 판정 (§5.8)
    ├── caselist.txt      사건번호 전수 — 눈으로 확인할 목록
    ├── mnemonics.txt     두문자 전수
    ├── crosscheck.md     두 소스 두문자 대조 (§5.3)
    └── warnings.md       수동 확인 필요 지점
```

중간 파일은 `output/_work/<파일이름>/` 에 남는다
(`01_raw.jsonl` → `02_normalized.jsonl` → `03_blocks.jsonl` / `03_structured.md`,
그리고 `baseline.json`, `02_changes.jsonl`).

## 절대 보존 대상 (§2)

| 대상 | 어떻게 지키나 |
|---|---|
| 사건번호 | 여는 괄호 오인식(`＜74다1557)`)은 **사건번호에 붙은 것만** 고친다. 문서 전체 일괄 치환을 하면 두문자 `[확객시전]` 이 깨진다. 내부 공백(`91 다 43695`)은 없앤다 |
| 두문자 | 전각 `［］`·중괄호 `{}` 를 반각 대괄호로 되돌린다. **안쪽 글자는 어떤 경우에도 고치지 않는다.** `[확객시젠]` 은 그대로 두고 §5.3 이 사람에게 넘긴다 |
| 별표 `*` | 사건번호 뒤 별표는 위첨자든 아니든 중요 판례 표시로 보존하고, 프론트매터 `standard: true` 로 옮긴다. 개수를 원본과 대조한다 |
| 색상 강조 | span RGB 가 유채색이면 `==…==`, 검정 볼드는 `**…**`. 회색은 강조가 아니다. **글자 색이 전부 검정인 스캔본이면 쪽 그림의 픽셀에서 읽는다**(아래) |
| 각주 | 페이지 하단 작은 글자를 각주로 떼고, 본문 위첨자 숫자는 `[^264]` 로. 쪽을 넘어 이어지면 잇는다. **참조를 못 찾은 각주도 버리지 않고** 섹션 끝에 남긴다 |

### 교재 범례 (§1.5)

| # | 요소 | 출력 |
|---|---|---|
| ① | 논점 윤곽 띠 | 프론트매터 `outline` |
| ② | 두문자 | `` `[일나시 나소시]` `` + `mnemonics` |
| ③ | 판례 제목 라벨 | `cases[].label` |
| ④ | 표준판례 `*` | `cases[].standard` |
| ⑤ | 답안 활용 가이드(색) | `==텍스트==` |
| ⑥ | 각주 | `[^n]` / `[^n]: …` |
| ⑦ | 비교 개념 표 | 마크다운 표 (셀 병합은 단순화) |
| ⑧ | 보너스 논점 `☑` | `> ### ☑ 제목` + `bonus_topics` |
| ⑨ | 기출 `(11)` | `` `(11)` `` + `exam_years: [2011]` |
| ⑩ | 옆번호 `sE-8` | 좌표로 떼어 **버린다**(기본). `legend.sidenote.mode: keep` 로 바꾸면 `` `sE-8` `` + `sidenote` 로 남긴다 |
| ⑪ | 학판검 세트 | `**2. 학설**` / `**3. 判例**` / `**4. 검토**` |

## 스캔본 + OCR 텍스트 레이어

이 교재들은 born-digital PDF 가 아니다. **종이를 찍은 그림 위에 OCR 글자가
얹혀 있다.** 그래서 다음이 따라온다. 진단이 자동으로 알아채고 리포트에 적는다.

| 증상 | 왜 | 어떻게 다루나 |
|---|---|---|
| 글자 색이 전부 `#000000` | 색은 그림에만 있다 | `preserve.color.source: auto` 가 쪽 그림 픽셀에서 읽는다. 글자 상자 안 잉크 픽셀 중 유채색 비율이 `min_ratio` 를 넘으면 강조 |
| 여는 괄호가 `＜` | OCR 오인식 | 사건번호에 붙은 것만 `(` 로 (§4.1) |
| 닫는 대괄호가 사라짐 (`［일나시 나소시`) | OCR 이 흘림 | 괄호만 되살리고 **안쪽 글자는 손대지 않는다**. 되살린 자리는 `02_changes.jsonl` 과 warnings 에 남는다 |
| 각주 참조가 위첨자가 아니라 `100)` | OCR 이 위첨자를 본문 크기로 떨굼 | 그 쪽에 정의가 있는 번호만 `[^100]` 으로 (§2.5) |
| 각주 영역을 글자 크기로 못 가름 | OCR 글자 크기가 들쭉날쭉 | 쪽 아래에서 번호로 시작하는 줄 뭉치를 찾는 방식으로 자동 전환 |
| `정구`/`졀과` 류 오인식 | OCR 품질 | **자동 치환하지 않는다.** 세어서 warnings 에 올린다 (§4.6) |
| 낱말 사이 공백이 없음 (`수량적가분채권을`) | OCR 레이어에 공백 글자가 없다 | 글자 상자의 가로 간격이 글자 크기의 `extract.space_gap_ratio` 를 넘으면 공백을 넣는다 |
| 번호와 제목이 다른 줄로 (`3` / `.判例`) | 글자 크기가 달라 따로 떨어짐 | 세로로 겹치는 줄을 한 줄로 잇는다 (`extract.line_merge_overlap`) |
| 제목이 색을 입어 `==IV. 시효중단==` | 색을 먼저 입히기 때문 | 구조는 마크업을 걷어낸 글자로 판단한다 |
| 쪽 아래 `154·윤곽민사소송법`, `CHAPTER 05 \| 소송물 • 155` | 꼬리말인데 장 제목으로 잡힌다 | 쪽마다 되풀이되는지로 찾는다. 쪽번호·장식을 뺀 **글자만** 견주므로 OCR 이 쪽번호를 `]6!` 로 흘려도 묶인다. `--pages` 로 잘라 돌려도 **문서 전체**에서 찾는다 — 머리말·꼬리말은 책 전체의 성질이다 |

### 색을 읽을 해상도

`preserve.color.image_dpi: auto` 는 **쪽에 박힌 그림의 실제 해상도에 맞춘다**
(`image_dpi_min`~`image_dpi_max` 사이로 가둔다). 원본보다 높게 렌더링해 봐야
없는 화소를 늘리는 것뿐이고, 너무 낮으면 글자 획이 한 화소 아래로 얇아져
종이와 섞이면서 색이 옅어진다.

실제 값은 진단 리포트의 「2-1) 쪽 그림」과 `convert probe <pdf>` 의
「쪽 그림 해상도」 표에서 확인한다. 쪽마다 px 크기·dpi·색공간·bpc 가 나온다.

시간은 쪽당 0.1~0.4초다(150dpi, 픽셀 2칸씩 건너뜀). 급하면 `image_dpi` 를
숫자로 고정해 낮추거나 `pixel_step` 을 키운다.

## 판단이 갈릴 수 있는 곳

지침을 그대로 따르되, 자동으로 정하면 위험한 지점은 사람에게 넘긴다.

- **날짜 뒤 한글** (`2011. 4. 26로`). 지침 §4.2 는 "이상 문자 제거"라고 하지만
  한글을 지우면 `26.로부터` 같은 정상 문장을 부순다. 그래서 기본값은 **지우지 않고
  warnings 에만 남긴다**. 지우려면 `normalize.date_trailing_hangul: strip`.
- **② 두문자와 ③ 판례 라벨**은 생김새가 같다(`[…]`). 길이만으로는 안 갈린다
  (`[반복적 재심청구]` 는 8자짜리 라벨이다). **자리**로 가른다 — 줄 맨 앞에
  서면서 번호를 달거나 뒤에 설명이 이어지면 라벨, 문장 가운데 오거나 줄에
  홀로 서면 두문자다. 지침 §1.5 ③ 의 예(`1) [청구확장 취지 명백히 표시] …`)가
  그 꼴이다. 경계에 걸리는 게 있으면 `mnemonics.txt` 를 보고
  `preserve.mnemonic.max_total_len` / `label_at_line_start` 를 조정한다.
- **문단 잇기**. 한글 책은 어절 안에서도 줄을 바꾼다. 기본값 `paragraph.join: space`
  는 줄 사이에 공백 하나를 넣는다. 원문에 없던 글자를 절대 넣지 않아야 하면
  `none`(붙임) 또는 `break`(줄바꿈 유지, 완전 무손실).
- **§4.6 사례집 오인식**(`정구`→`청구` 등)은 **자동 치환하지 않는다.** 세어서
  warnings 에 올리고, 잦으면 파서를 바꾸라고 말한다. 지침이 정한 대로다.

## 검증 (§5)

`convert run` 은 마지막에 반드시 검증을 돌리고, FAIL 이 있으면 종료 코드 1 을
낸다. 프론트매터의 `validation:` 도 실제 판정으로 바뀐다.

| 항목 | 기준 | 미달 시 |
|---|---|---|
| 사건번호 형식 오류 | 0건 | FAIL |
| 별표 개수 불일치 (원본 대조) | 0건 | FAIL |
| 각주 참조/정의 불일치 | 0건 | FAIL |
| 여백 마커 병합 의심 (`sE-81`) | 0건 | FAIL |
| 프론트매터 `cases` 누락 | 0건 | FAIL |
| 옆번호가 본문에 샘 (`sE-8`+`1.`) | 0건 | FAIL |
| 색상 강조 유실 | 5% 이하 | WARN |
| 잔여 노이즈 | 쪽당 3건 이하 | WARN |
| 두문자 교차 일치 | 0건 불일치 | `crosscheck` 가 종료 코드 1 |

별표·색상 대조는 `baseline.json`(추출 단계에서 **파서와 독립적으로** 뜬 원문
카운트)과 맞춰 본다. baseline 이 없으면 그 항목은 판정하지 않고 '대조 불가'라고
적는다. 없는 근거로 PASS 를 내지 않는다.

색상은 **잃은 것만** 센다. 이어진 span 이 마크업 한 덩어리로 합쳐지면서 사이의
구분자까지 안에 들어가 글자 수가 조금 느는 것은 보존에 문제가 없기 때문이다.
헤딩 제목으로 들어가며 `==` 가 걷힌 분량은 '구조가 대신 담은 것'으로 보고
되더한다.

`convert run` 은 쓰기 전에 **출력 폴더의 지난 결과물을 지운다.** 실행마다 분할이
달라지면 옛 파일이 남아 검증이 같은 내용을 두 번 세고, 별표가 4에서 8이 되어
엉뚱한 FAIL 이 난다. 프론트매터에 `parser:` 가 적힌, 우리가 만든 파일만 지운다.
사람이 그 폴더에 둔 파일은 지우지도, 검증하지도 않는다.

`--pages` 로 잘라 돌리면 범위 밖과 짝이 맞지 않는 각주·참조가 생긴다. 그건
FAIL 이 아니라 WARN 으로 낮춘다. 그러지 않으면 §8 의 '한 장만 먼저'가 영영
통과하지 못한다.

## 파서 교체 (§3.2)

`parsers/` 아래 어댑터를 두고 이름으로 고른다. 파서가 바뀌어도 §4 정규화와
§5 검증은 그대로 돈다 (`tests` 의 `파서교체` 참조).

| 이름 | 좌표·색 | 쓰임 |
|---|---|---|
| `pymupdf` | ○ | **권장.** 색·좌표·글자크기가 다 필요하다 |
| `pymupdf4llm` | × | 경량 |
| `marker` | × | 각주·구조 처리 |
| `mineru` | × | 2단 조판·한자 |
| `paddleocr` | × | 스캔본 |
| `upstage` | × | 스캔본. **문서를 외부로 보낸다** |
| `textfile` | × | `.txt`/`.md` 재처리·회귀 테스트 |

`--parser` 로 직접 고르거나, 생략하면 진단 결과(`parsers.by_diagnosis`)로 고른다.

## 설정

규칙은 전부 `config.yaml` 에 있다. 코드를 고치지 않고 여기만 손본다.
바꾼 뒤에는 반드시 `convert validate` 를 다시 돌린다.

## 테스트

```bash
python3 tests/make_fixtures.py tests/fixtures    # 검증용 PDF 생성
python3 -m unittest discover -s tests -t .
```

픽스처는 지침이 서술한 조판(1단, 하단 각주+가로선, 우측 여백 `sE-8`, 청색 강조
1종, ☑ 박스, 위첨자 각주, 별표, 한자)을 재현한 PDF다. 지침 §2.2 의 실측 사례
(기본서 `[확객시전]` vs 사례집 `[확객시젠]`)도 일부러 넣어 두어, 교차검증이
실제로 잡아내는지 확인한다.

## 개발 순서 (§8)

전체를 한 번에 변환하지 않는다.

1. `convert diagnose` — 텍스트 레이어·조판·색·옆번호 확인
2. `convert run --pages …` 로 한 장만 (IV. 시효중단이 든 장 권장)
3. `_reports/validation.md` 에서 FAIL 0 이 될 때까지 `config.yaml` 보완
4. 통과한 뒤 전체 변환
5. `convert crosscheck` 로 두문자 대조, `caselist.txt`·`mnemonics.txt` 육안 확인

3단계를 건너뛰고 전체를 돌리면, 문제가 나왔을 때 처음부터 다시 해야 한다.
그래서 진단 없이 `run` 을 부르면 막아 둔다(`--force` 로 넘길 수는 있다).
