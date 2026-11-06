# 예약오픈 알리미 — GitHub Pages + Actions 실험판

## 배포
1. GitHub에 새 저장소를 만들고 이 폴더의 파일/폴더를 그대로 업로드합니다.
2. Settings → Pages → Deploy from a branch → main / (root) → Save.
3. Actions 탭에서 워크플로 실행을 허용하고 `Reservation monitor`를 수동 실행해 봅니다.
4. 휴대전화에서 `https://사용자명.github.io/저장소명/` 접속 후 홈 화면에 추가합니다.
5. 웹 화면에서 사이트와 날짜를 입력하고 `설정 JSON 복사`를 누른 뒤 GitHub의 `sites.json` 파일에 붙여 넣어 커밋합니다. **휴대전화에서 입력만 하면 서버 감시 설정이 자동으로 변경되지는 않습니다.**
6. 선택: Settings → Secrets and variables → Actions에서 `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` 등록 시 '확인 필요' 후보만 텔레그램 메시지로 보냅니다.

## 중요한 제한
- GitHub Actions `*/10` 스케줄은 **정확히 10분마다 실행된다는 보장이 없습니다**. 지연·누락될 수 있습니다.
- GitHub Pages만으로는 카카오 페이지를 자동 판독할 수 없으며 Actions가 별도 브라우저를 띄워 시도합니다.
- 카카오 달력의 실제 DOM 구조는 검증되지 않았습니다. 현재 판독기는 날짜 셀에 `data-date`, `aria-label`, `title`이 명확히 있는 경우에만 상태를 판단합니다. 대부분의 경우 '판독 불가'가 정상이며, 예약 가능하다고 단정하지 않습니다.
- '예약마감' 문구가 없더라도 회차가 실제 예약 가능한지 확정되지 않습니다.
- 로그인/CAPTCHA/봇 차단은 우회하지 않습니다. 개인 로그인 정보를 GitHub 저장소에 올리지 마세요.
- 감시 결과는 공개 Pages 사이트에 게시되므로 비공개 정보는 등록하지 마세요.
- GitHub Actions 사용량 및 저장소 정책을 확인하세요.
- 이 버전은 **실험판**입니다. 실제 예약 사이트의 자동 감시 성공이 검증되지 않았습니다.
